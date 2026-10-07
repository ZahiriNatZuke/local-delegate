"""llama-swap v255 de prueba: lo lanza en un puerto libre, sin cargar ningún modelo.

Lo usan los controles que necesitan un llama-swap de verdad (la carrera del TTL, la recarga con
`-watch-config`, la foto de peticiones en vuelo). Cada modelo de la config es un servidor falso en
Python (`servidor_falso_llama.py`) que arranca con `${PORT}`, así que no hay GGUF ni GPU de por medio.

Lo que garantiza:

* **No toca el llama-swap real.** Escucha en un puerto libre, con una config propia y su **propio**
  `store` (un `metrics.db` dentro de la carpeta temporal), y mueve `startPort` para que los puertos de
  sus modelos no choquen con los del real, que usa el mismo ejecutable y reparte desde el 5800.
* **Apunta cada PID que lanza** (llama-swap, los servidores falsos y los clientes de apoyo) y, al
  terminar, comprueba que **esos PID** ya no existen. Si alguno sigue vivo, lo termina por PID (con su
  árbol) y falla con «la fixture dejó vivo el PID …». Nunca se mata nada por nombre de imagen: el
  llama-swap real es el mismo ejecutable y corre siempre.

Uso típico, dentro de un test:

    with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m", ttl=2)]) as ls:
        ls.chat("m", retraso_s=1)
"""

from __future__ import annotations

import contextlib
import json
import random
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO

import httpx2

BINARIO = Path(r"D:\Projects\llms\llama-swap-v255\llama-swap.exe")
SERVIDOR_FALSO = Path(__file__).with_name("servidor_falso_llama.py")

# Las cuatro salidas de una recarga (REQ-034), más la que no llegó a resolverse.
RECARGO = "recargó"
RECHAZO = "rechazó"
NO_VIGILA = "no vigila el fichero"
CAIDO = "caído"
SIN_RESOLVER = "sin resolver"

_FRASE_RECARGANDO = "reloading configuration"
_FRASE_RECARGADA = "configuration reloaded"
_FRASES_RECHAZO = ("failed to reload config", "failed to build new server during reload")


def _arg(ruta: str | Path) -> str:
    """Una ruta como argumento del `cmd` de llama-swap: sin comillas salvo que lleve espacios.

    llama-swap parte el `cmd` como un shell y trata la barra invertida dentro de comillas como
    escape, así que una ruta de Windows entrecomillada llega rota: se escribe tal cual.
    """
    texto = str(ruta)
    if " " in texto:
        raise ValueError(f"la ruta lleva espacios y llama-swap no la recibiría entera: {texto}")
    return texto


def binario_disponible() -> bool:
    return BINARIO.is_file()


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def puerto_inicial_libre(cuantos: int) -> int:
    """Primer puerto de un tramo de `cuantos` seguidos que se puede enlazar.

    llama-swap reparte `${PORT}` desde `startPort` sumando uno por modelo. Windows reserva rangos
    enteros del tramo dinámico (`netsh int ipv4 show excludedportrange`), así que un puerto «libre»
    de `bind(0)` más una cantidad cualquiera puede caer en uno y el servidor del modelo no arranca.
    Se busca por debajo de ese tramo y se comprueba cada puerto.
    """
    for _ in range(200):
        inicio = random.randrange(20000, 40000)
        try:
            for puerto in range(inicio, inicio + cuantos):
                with socket.socket() as s:
                    s.bind(("127.0.0.1", puerto))
        except OSError:
            continue
        return inicio
    raise RuntimeError("no hay un tramo de puertos libre para los modelos de prueba")


@dataclass(frozen=True)
class ModeloPrueba:
    """Un modelo de la config de prueba: un servidor falso con su TTL y sus alias."""

    id: str
    ttl: int = 0
    alias: tuple[str, ...] = ()
    retraso: float = 0.0


def imagen_del_proceso(pid: int) -> str | None:
    """Nombre de la imagen del proceso `pid`, o `None` si no existe. Solo lee."""
    salida = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not salida.startswith('"'):
        return None
    campos = salida.splitlines()[0].split('","')
    if len(campos) < 2 or campos[1].strip('"') != str(pid):
        return None
    return campos[0].strip('"').lower()


def terminar_por_pid(pid: int) -> None:
    """Termina `pid` y su árbol. Es la única forma de matar que usa la fixture: nunca por nombre."""
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False
    )


def pid_del_llamaswap_real(puerto: int = 9292) -> int | None:
    """PID del llama-swap real, buscado por su línea de órdenes con `--listen 127.0.0.1:<puerto>`.

    Solo lee la lista de procesos; no abre ni toca el proceso. `None` si no hay ninguno en marcha.
    """
    orden = (
        "Get-CimInstance Win32_Process -Filter \"Name='llama-swap.exe'\" | "
        'ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }'
    )
    salida = subprocess.run(
        ["powershell", "-NoProfile", "-Command", orden],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for linea in salida.splitlines():
        pid, _, linea_de_ordenes = linea.partition("\t")
        if f"127.0.0.1:{puerto}" in linea_de_ordenes and pid.strip().isdigit():
            return int(pid)
    return None


def _contar(texto: str) -> dict[str, int]:
    return {
        "recargando": texto.count(_FRASE_RECARGANDO),
        "recargada": texto.count(_FRASE_RECARGADA),
        "rechazo": sum(texto.count(f) for f in _FRASES_RECHAZO),
    }


@dataclass(frozen=True)
class FotoInflight:
    peticiones: list[dict[str, object]]
    segundos: float
    caracteres_de_log: int


@dataclass
class LlamaSwapDePrueba:
    """Un llama-swap v255 lanzado con su config y su `store` propios en `directorio`."""

    directorio: Path
    modelos: Sequence[ModeloPrueba]
    watch_config: bool = True
    binario: Path = BINARIO
    protegidos: Collection[int] = ()
    puerto: int = field(default_factory=puerto_libre)
    puerto_inicial: int = field(default_factory=lambda: puerto_inicial_libre(16))
    _proc: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _pids: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _clientes: list[subprocess.Popen[bytes]] = field(default_factory=list, init=False, repr=False)
    _log: IO[bytes] | None = field(default=None, init=False, repr=False)
    detalle_recarga: str = field(default="", init=False)

    # --- rutas y config -------------------------------------------------------------------------

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.puerto}"

    @property
    def config(self) -> Path:
        return self.directorio / "config.yaml"

    @property
    def store(self) -> Path:
        return self.directorio / "store" / "metrics.db"

    def registro(self, modelo: str) -> Path:
        return self.directorio / f"{modelo}.jsonl"

    def _pid_file(self, modelo: str) -> Path:
        return self.directorio / f"{modelo}.pid.jsonl"

    def texto_config(self, modelos: Sequence[ModeloPrueba] | None = None) -> str:
        """YAML de la config de prueba. Los `cmd` son el servidor falso con `${PORT}`."""
        lineas = [
            "store:",
            f"  path: '{self.store}'",
            # Los modelos del real arrancan desde el 5800: este reparte desde un tramo libre.
            f"startPort: {self.puerto_inicial}",
            "models:",
        ]
        for m in self.modelos if modelos is None else modelos:
            cmd = " ".join(
                [
                    _arg(sys.executable),
                    _arg(SERVIDOR_FALSO),
                    "--port ${PORT}",
                    f"--retraso {m.retraso}",
                    f"--registro {_arg(self.registro(m.id))}",
                    f"--pid-file {_arg(self._pid_file(m.id))}",
                ]
            )
            lineas += [f"  {m.id}:", f"    cmd: '{cmd}'", f"    ttl: {m.ttl}"]
            if m.alias:
                lineas.append("    aliases:")
                lineas += [f"      - {a}" for a in m.alias]
        return "\n".join(lineas) + "\n"

    def escribir_config(self, texto: str | None = None) -> None:
        """Escribe la config directamente, como lo haría quien la edita a mano."""
        self.config.write_text(self.texto_config() if texto is None else texto, encoding="utf-8")

    # --- ciclo de vida --------------------------------------------------------------------------

    def comando(self) -> list[str]:
        orden = [
            str(self.binario),
            "-config",
            str(self.config),
            "-listen",
            f"127.0.0.1:{self.puerto}",
        ]
        if self.watch_config:
            orden.append("-watch-config")
        return orden

    def arrancar(self, espera: float = 20.0) -> None:
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        if not self.config.exists():
            self.escribir_config()
        self._log = (self.directorio / "llama-swap.log").open("wb")
        self._proc = subprocess.Popen(
            self.comando(),
            stdout=self._log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        self._pids[self._proc.pid] = "llama-swap.exe"
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            if self._proc.poll() is not None:
                raise RuntimeError(f"llama-swap de prueba salió al arrancar: {self.log_texto()}")
            with contextlib.suppress(httpx2.HTTPError):
                if httpx2.get(self.url + "/running", timeout=1).status_code == 200:
                    return
            time.sleep(0.1)
        raise RuntimeError(f"llama-swap de prueba no respondió en {espera} s: {self.log_texto()}")

    def cerrar_log(self) -> None:
        if self._log is not None:
            with contextlib.suppress(OSError):
                self._log.close()
            self._log = None

    def log_texto(self) -> str:
        ruta = self.directorio / "llama-swap.log"
        return ruta.read_text(encoding="utf-8", errors="replace") if ruta.exists() else ""

    def _apuntar_pids_de_los_servidores(self) -> None:
        for m in self.modelos:
            ruta = self._pid_file(m.id)
            if not ruta.exists():
                continue
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                with contextlib.suppress(ValueError):
                    dato = json.loads(linea)
                    self._pids[int(dato["pid"])] = "python.exe"
                    self._pids.setdefault(int(dato["ppid"]), "python.exe")

    def detener(self) -> None:
        """Para llama-swap (Ctrl+Break, y por PID si no sale) sin comprobar nada más."""
        self._apuntar_pids_de_los_servidores()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                terminar_por_pid(proc.pid)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=10)

    def comprobar_procesos(self, espera: float = 5.0) -> None:
        """Falla si algún PID apuntado sigue vivo, tras terminarlo por PID.

        Un PID solo se toca si su imagen es la que se apuntó (así un PID reutilizado por otro
        proceso no se mata) y nunca si es de `protegidos` (el llama-swap real).
        """
        self._apuntar_pids_de_los_servidores()
        for cliente in self._clientes:
            self._pids.setdefault(cliente.pid, "python.exe")
        limite = time.monotonic() + espera
        vivos: dict[int, str] = {}
        while time.monotonic() < limite:
            vivos = {
                pid: imagen
                for pid, imagen in self._pids.items()
                if pid not in self.protegidos and imagen_del_proceso(pid) == imagen
            }
            if not vivos:
                return
            time.sleep(0.25)
        for pid in vivos:
            terminar_por_pid(pid)
        raise AssertionError(f"la fixture dejó vivo el PID {sorted(vivos)}")

    # --- consultas ------------------------------------------------------------------------------

    def get(self, ruta: str, timeout: float = 5.0) -> httpx2.Response:
        return httpx2.get(self.url + ruta, timeout=timeout)

    def running(self) -> list[dict[str, object]]:
        return list(self.get("/running").json()["running"])

    def esta_cargado(self, modelo: str) -> bool:
        return any(m["model"] == modelo and m["state"] == "ready" for m in self.running())

    def chat(
        self, modelo: str, *, retraso_s: float = 0.0, timeout: float = 60.0, **extra: object
    ) -> httpx2.Response:
        cuerpo: dict[str, object] = {
            "model": modelo,
            "messages": [{"role": "user", "content": "hola"}],
            "retraso_s": retraso_s,
            **extra,
        }
        return httpx2.post(self.url + "/v1/chat/completions", json=cuerpo, timeout=timeout)

    def actividad(self, modelo: str | None = None, limite: int = 1) -> list[dict[str, object]]:
        consulta = f"?limit={limite}" + (f"&model={modelo}" if modelo else "")
        return list(self.get("/api/metrics/activity" + consulta).json()["data"])

    @staticmethod
    def hora_de_actividad(registro: dict[str, object]) -> float:
        """Época del campo `timestamp` de una fila de actividad (resolución de un segundo)."""
        return datetime.fromisoformat(str(registro["timestamp"])).timestamp()

    def eventos_del_servidor(self, modelo: str, evento: str) -> list[dict[str, object]]:
        """Líneas `llegada` o `fin` que el servidor falso de `modelo` apuntó, en orden."""
        ruta = self.registro(modelo)
        if not ruta.exists():
            return []
        lineas = [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [x for x in lineas if x["evento"] == evento]

    def llegadas(self, modelo: str) -> list[dict[str, object]]:
        return self.eventos_del_servidor(modelo, "llegada")

    def fines(self, modelo: str) -> list[dict[str, object]]:
        return self.eventos_del_servidor(modelo, "fin")

    def ultimo_fin(self, modelo: str) -> float:
        """Hora (`time.time()`) a la que el servidor falso de `modelo` acabó su última petición."""
        return float(str(self.fines(modelo)[-1]["ts"]))

    def _mensajes(self, timeout: float) -> Iterator[tuple[str, dict[str, object]]]:
        """Mensajes de `/api/events` como (tipo, datos), hasta cerrar la conexión o el timeout."""
        with httpx2.stream("GET", self.url + "/api/events", timeout=timeout) as respuesta:
            for linea in respuesta.iter_lines():
                if linea.startswith("data:"):
                    mensaje = json.loads(linea[5:])
                    yield str(mensaje["type"]), json.loads(mensaje["data"])

    def foto_inflight(self, timeout: float = 5.0) -> FotoInflight:
        """La foto `inflight` de la carga inicial de `/api/events`, con lo que tardó en llegar.

        También cuenta los caracteres de log (de llama-swap y de los servidores) que llegaron antes
        que la foto: el historial que hay que tragarse para llegar a ella.
        """
        inicio = time.monotonic()
        caracteres = 0
        for tipo, datos in self._mensajes(timeout):
            if tipo == "logData":
                caracteres += len(str(datos.get("data", "")))
            elif tipo == "inflight":
                return FotoInflight(
                    list(datos.get("requests") or []), time.monotonic() - inicio, caracteres
                )
        raise RuntimeError("`/api/events` se cerró sin mandar la foto `inflight`")

    def historial_de_log(self, timeout: float = 5.0) -> str:
        """Texto del primer mensaje `logData` de `/api/events`: el historial de logs."""
        for tipo, datos in self._mensajes(timeout):
            if tipo == "logData":
                return str(datos.get("data", ""))
        return ""

    # --- recarga --------------------------------------------------------------------------------

    def esperar_salida_recarga(
        self,
        escribir: Callable[[], None],
        *,
        espera: float = 45.0,
        sin_vigia: float = 10.0,
    ) -> str:
        """Ejecuta `escribir()` y dice cuál de las cuatro salidas de REQ-034 ocurrió.

        Mira el historial de logs antes y después de escribir: un `/api/events` abierto se cierra
        cuando llama-swap reinicia su servidor, y el «configuration reloaded» lo escribe el nuevo,
        así que se vuelve a abrir. `caído` es que llama-swap no responde antes de escribir.
        """
        try:
            antes = _contar(self.historial_de_log())
        except httpx2.TransportError:
            escribir()
            self.detalle_recarga = "conexión rechazada"
            return CAIDO
        escribir()
        inicio = time.monotonic()
        while (transcurrido := time.monotonic() - inicio) < espera:
            try:
                texto = self.historial_de_log(timeout=2)
            except httpx2.TransportError:
                texto = ""  # el servidor viejo ya cerró y el nuevo aún no escucha
            ahora = _contar(texto) if texto else antes
            if ahora["rechazo"] > antes["rechazo"]:
                self.detalle_recarga = next(
                    (x for x in texto.splitlines() if any(f in x for f in _FRASES_RECHAZO)), ""
                )
                return RECHAZO
            if ahora["recargada"] > antes["recargada"]:
                return RECARGO
            if ahora["recargando"] == antes["recargando"] and transcurrido >= sin_vigia:
                return NO_VIGILA
            time.sleep(0.5)
        return SIN_RESOLVER

    # --- clientes de apoyo ----------------------------------------------------------------------

    def lanzar_cliente(self, modelo: str, *, retraso_s: float) -> subprocess.Popen[bytes]:
        """Un segundo proceso, otro cliente, que manda una petición larga y espera su respuesta."""
        codigo = (
            "import json, urllib.request;"
            f"c = json.dumps({{'model': {modelo!r}, 'messages': [], 'retraso_s': {retraso_s}}}).encode();"
            f"r = urllib.request.Request({self.url + '/v1/chat/completions'!r}, c,"
            " {'Content-Type': 'application/json'});"
            "urllib.request.urlopen(r, timeout=120).read()"
        )
        proc = subprocess.Popen([sys.executable, "-c", codigo])
        self._clientes.append(proc)
        return proc


@contextlib.contextmanager
def llamaswap_de_prueba(
    directorio: Path,
    modelos: Sequence[ModeloPrueba],
    *,
    watch_config: bool = True,
    arrancar: bool = True,
) -> Iterator[LlamaSwapDePrueba]:
    """Lanza un llama-swap de prueba y, al salir, lo para y comprueba que no dejó procesos vivos."""
    real = pid_del_llamaswap_real()
    ls = LlamaSwapDePrueba(
        directorio, modelos, watch_config=watch_config, protegidos=() if real is None else (real,)
    )
    try:
        if arrancar:
            ls.arrancar()
        yield ls
    finally:
        ls.detener()
        try:
            ls.comprobar_procesos()
        finally:
            ls.cerrar_log()
