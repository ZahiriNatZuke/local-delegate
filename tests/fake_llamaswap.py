"""llama-swap v255 de prueba: lo lanza en un puerto libre, sin cargar ningún modelo.

Lo usan los controles que necesitan un llama-swap de verdad (la carrera del TTL, la recarga con
`-watch-config`, la foto de peticiones en vuelo). Cada modelo de la config es un servidor falso en
Python (`fake_llama_server.py`) que arranca con `${PORT}`, así que no hay GGUF ni GPU de por medio.

Lo que garantiza:

* **No toca el llama-swap real.** Escucha en un puerto libre, con una config propia y su **propio**
  `store` (un `metrics.db` dentro de la carpeta temporal), y mueve `startPort` para que los puertos de
  sus modelos no choquen con los del real, que usa el mismo ejecutable y reparte desde el 5800.
* **Apunta cada PID que lanza** (llama-swap, los servidores falsos y los clientes de apoyo) y, al
  terminar, comprueba que **esos PID** ya no existen. Si alguno sigue vivo, lo termina por PID (con su
  árbol) y falla con «la fixture dejó vivo el PID …». Nunca se mata nada por nombre de imagen: el
  llama-swap real es el mismo ejecutable y corre siempre.

Uso típico, dentro de un test:

    with fake_llamaswap(tmp_path, [TestModel("m", ttl=2)]) as ls:
        ls.chat("m", delay_s=1)
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

BINARY = Path(r"D:\Projects\llms\llama-swap-v255\llama-swap.exe")
FAKE_SERVER = Path(__file__).with_name("fake_llama_server.py")

# Las cuatro salidas de una recarga (REQ-034), más la que no llegó a resolverse.
SURCHARGE = "recargó"
REFUSAL = "rechazó"
NOT_WATCHED = "no vigila el fichero"
DOWN = "caído"
UNRESOLVED = "sin resolver"

_RELOADING_PHRASE = "reloading configuration"
_RELOADED_PHRASE = "configuration reloaded"
_REFUSAL_PHRASES = ("failed to reload config", "failed to build new server during reload")


def _arg(path: str | Path) -> str:
    """Una ruta como argumento del `cmd` de llama-swap: sin comillas salvo que lleve espacios.

    llama-swap parte el `cmd` como un shell y trata la barra invertida dentro de comillas como
    escape, así que una ruta de Windows entrecomillada llega rota: se escribe tal cual.
    """
    text = str(path)
    if " " in text:
        raise ValueError(f"la ruta lleva espacios y llama-swap no la recibiría entera: {text}")
    return text


def binary_available() -> bool:
    return BINARY.is_file()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def free_start_port(how_many: int) -> int:
    """Primer puerto de un tramo de `how_many` seguidos que se puede enlazar.

    llama-swap reparte `${PORT}` desde `startPort` sumando uno por modelo. Windows reserva rangos
    enteros del tramo dinámico (`netsh int ipv4 show excludedportrange`), así que un puerto «libre»
    de `bind(0)` más una cantidad cualquiera puede caer en uno y el servidor del modelo no arranca.
    Se busca por debajo de ese tramo y se comprueba cada puerto.
    """
    for _ in range(200):
        start_ts = random.randrange(20000, 40000)
        try:
            for port in range(start_ts, start_ts + how_many):
                with socket.socket() as s:
                    s.bind(("127.0.0.1", port))
        except OSError:
            continue
        return start_ts
    raise RuntimeError("no hay un tramo de puertos libre para los modelos de prueba")


@dataclass(frozen=True)
class FakeModel:
    """Un modelo de la config de prueba: un servidor falso con su TTL y sus alias."""

    id: str
    ttl: int = 0
    alias: tuple[str, ...] = ()
    delay: float = 0.0


def process_image(pid: int) -> str | None:
    """Nombre de la imagen del proceso `pid`, o `None` si no existe. Solo lee."""
    output = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not output.startswith('"'):
        return None
    fields = output.splitlines()[0].split('","')
    if len(fields) < 2 or fields[1].strip('"') != str(pid):
        return None
    return fields[0].strip('"').lower()


def terminate_by_pid(pid: int) -> None:
    """Termina `pid` y su árbol. Es la única forma de matar que usa la fixture: nunca por nombre."""
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False
    )


def real_llamaswap_pid(port: int = 9292) -> int | None:
    """PID del llama-swap real, buscado por su línea de órdenes con `--listen 127.0.0.1:<puerto>`.

    Solo lee la lista de procesos; no abre ni toca el proceso. `None` si no hay ninguno en marcha.
    """
    order = (
        "Get-CimInstance Win32_Process -Filter \"Name='llama-swap.exe'\" | "
        'ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }'
    )
    output = subprocess.run(
        ["powershell", "-NoProfile", "-Command", order],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for line in output.splitlines():
        pid, _, command_line = line.partition("\t")
        if f"127.0.0.1:{port}" in command_line and pid.strip().isdigit():
            return int(pid)
    return None


def _count(text: str) -> dict[str, int]:
    return {
        "recargando": text.count(_RELOADING_PHRASE),
        "recargada": text.count(_RELOADED_PHRASE),
        "rechazo": sum(text.count(f) for f in _REFUSAL_PHRASES),
    }


@dataclass(frozen=True)
class InflightSnapshot:
    requests: list[dict[str, object]]
    seconds: float
    log_chars: int


@dataclass
class FakeLlamaSwap:
    """Un llama-swap v255 lanzado con su config y su `store` propios en `directory`."""

    directory: Path
    models: Sequence[FakeModel]
    watch_config: bool = True
    binary: Path = BINARY
    protected: Collection[int] = ()
    port: int = field(default_factory=free_port)
    start_port: int = field(default_factory=lambda: free_start_port(16))
    _proc: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _pids: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _clients: list[subprocess.Popen[bytes]] = field(default_factory=list, init=False, repr=False)
    _log: IO[bytes] | None = field(default=None, init=False, repr=False)
    reload_detail: str = field(default="", init=False)

    # --- rutas y config -------------------------------------------------------------------------

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def config(self) -> Path:
        return self.directory / "config.yaml"

    @property
    def store(self) -> Path:
        return self.directory / "store" / "metrics.db"

    def record(self, model: str) -> Path:
        return self.directory / f"{model}.jsonl"

    def _pid_file(self, model: str) -> Path:
        return self.directory / f"{model}.pid.jsonl"

    def config_text(self, models: Sequence[FakeModel] | None = None) -> str:
        """YAML de la config de prueba. Los `cmd` son el servidor falso con `${PORT}`."""
        lines = [
            "store:",
            f"  path: '{self.store}'",
            # Los modelos del real arrancan desde el 5800: este reparte desde un tramo libre.
            f"startPort: {self.start_port}",
            "models:",
        ]
        for m in self.models if models is None else models:
            cmd = " ".join(
                [
                    _arg(sys.executable),
                    _arg(FAKE_SERVER),
                    "--port ${PORT}",
                    f"--delay {m.delay}",
                    f"--record {_arg(self.record(m.id))}",
                    f"--pid-file {_arg(self._pid_file(m.id))}",
                ]
            )
            lines += [f"  {m.id}:", f"    cmd: '{cmd}'", f"    ttl: {m.ttl}"]
            if m.alias:
                lines.append("    aliases:")
                lines += [f"      - {a}" for a in m.alias]
        return "\n".join(lines) + "\n"

    def write_config(self, text: str | None = None) -> None:
        """Escribe la config directamente, como lo haría quien la edita a mano."""
        self.config.write_text(self.config_text() if text is None else text, encoding="utf-8")

    # --- ciclo de vida --------------------------------------------------------------------------

    def command(self) -> list[str]:
        order = [
            str(self.binary),
            "-config",
            str(self.config),
            "-listen",
            f"127.0.0.1:{self.port}",
        ]
        if self.watch_config:
            order.append("-watch-config")
        return order

    def start(self, wait: float = 20.0) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        if not self.config.exists():
            self.write_config()
        self._log = (self.directory / "llama-swap.log").open("wb")
        self._proc = subprocess.Popen(
            self.command(),
            stdout=self._log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        self._pids[self._proc.pid] = "llama-swap.exe"
        limit = time.monotonic() + wait
        while time.monotonic() < limit:
            if self._proc.poll() is not None:
                raise RuntimeError(f"llama-swap de prueba salió al arrancar: {self.log_text()}")
            with contextlib.suppress(httpx2.HTTPError):
                if httpx2.get(self.url + "/running", timeout=1).status_code == 200:
                    return
            time.sleep(0.1)
        raise RuntimeError(f"llama-swap de prueba no respondió en {wait} s: {self.log_text()}")

    def close_log(self) -> None:
        if self._log is not None:
            with contextlib.suppress(OSError):
                self._log.close()
            self._log = None

    def log_text(self) -> str:
        path = self.directory / "llama-swap.log"
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    def _record_server_pids(self) -> None:
        for m in self.models:
            path = self._pid_file(m.id)
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                with contextlib.suppress(ValueError):
                    datum = json.loads(line)
                    self._pids[int(datum["pid"])] = "python.exe"
                    self._pids.setdefault(int(datum["ppid"]), "python.exe")

    def stop(self) -> None:
        """Para llama-swap (Ctrl+Break, y por PID si no sale) sin comprobar nada más."""
        self._record_server_pids()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                terminate_by_pid(proc.pid)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=10)

    def check_processes(self, wait: float = 5.0) -> None:
        """Falla si algún PID apuntado sigue vivo, tras terminarlo por PID.

        Un PID solo se toca si su imagen es la que se apuntó (así un PID reutilizado por otro
        proceso no se mata) y nunca si es de `protected` (el llama-swap real).
        """
        self._record_server_pids()
        for client in self._clients:
            self._pids.setdefault(client.pid, "python.exe")
        limit = time.monotonic() + wait
        alive: dict[int, str] = {}
        while time.monotonic() < limit:
            alive = {
                pid: image
                for pid, image in self._pids.items()
                if pid not in self.protected and process_image(pid) == image
            }
            if not alive:
                return
            time.sleep(0.25)
        for pid in alive:
            terminate_by_pid(pid)
        raise AssertionError(f"la fixture dejó vivo el PID {sorted(alive)}")

    # --- consultas ------------------------------------------------------------------------------

    def get(self, path: str, timeout: float = 5.0) -> httpx2.Response:
        return httpx2.get(self.url + path, timeout=timeout)

    def running(self) -> list[dict[str, object]]:
        return list(self.get("/running").json()["running"])

    def is_loaded(self, model: str) -> bool:
        return any(m["model"] == model and m["state"] == "ready" for m in self.running())

    def chat(
        self, model: str, *, delay_s: float = 0.0, timeout: float = 60.0, **extra: object
    ) -> httpx2.Response:
        body: dict[str, object] = {
            "model": model,
            "messages": [{"role": "user", "content": "hola"}],
            "delay_s": delay_s,
            **extra,
        }
        return httpx2.post(self.url + "/v1/chat/completions", json=body, timeout=timeout)

    def activity(self, model: str | None = None, limit: int = 1) -> list[dict[str, object]]:
        query = f"?limit={limit}" + (f"&model={model}" if model else "")
        return list(self.get("/api/metrics/activity" + query).json()["data"])

    @staticmethod
    def activity_time(record: dict[str, object]) -> float:
        """Época del campo `timestamp` de una fila de actividad (resolución de un segundo)."""
        return datetime.fromisoformat(str(record["timestamp"])).timestamp()

    def server_events(self, model: str, event: str) -> list[dict[str, object]]:
        """Líneas `arrival` o `end` que el servidor falso de `model` apuntó, en orden."""
        path = self.record(model)
        if not path.exists():
            return []
        lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [x for x in lines if x["event"] == event]

    def arrivals(self, model: str) -> list[dict[str, object]]:
        return self.server_events(model, "arrival")

    def ends(self, model: str) -> list[dict[str, object]]:
        return self.server_events(model, "end")

    def last_end(self, model: str) -> float:
        """Hora (`time.time()`) a la que el servidor falso de `model` acabó su última petición."""
        return float(str(self.ends(model)[-1]["ts"]))

    def _messages(self, timeout: float) -> Iterator[tuple[str, dict[str, object]]]:
        """Mensajes de `/api/events` como (tipo, datos), hasta cerrar la conexión o el timeout."""
        with httpx2.stream("GET", self.url + "/api/events", timeout=timeout) as response:
            for line in response.iter_lines():
                if line.startswith("data:"):
                    message = json.loads(line[5:])
                    yield str(message["type"]), json.loads(message["data"])

    def inflight_snapshot(self, timeout: float = 5.0) -> InflightSnapshot:
        """La foto `inflight` de la carga inicial de `/api/events`, con lo que tardó en llegar.

        También cuenta los caracteres de log (de llama-swap y de los servidores) que llegaron antes
        que la foto: el historial que hay que tragarse para llegar a ella.
        """
        start_ts = time.monotonic()
        chars = 0
        for kind, data in self._messages(timeout):
            if kind == "logData":
                chars += len(str(data.get("data", "")))
            elif kind == "inflight":
                return InflightSnapshot(
                    list(data.get("requests") or []), time.monotonic() - start_ts, chars
                )
        raise RuntimeError("`/api/events` se cerró sin mandar la foto `inflight`")

    def log_history(self, timeout: float = 5.0) -> str:
        """Texto del primer mensaje `logData` de `/api/events`: el historial de logs."""
        for kind, data in self._messages(timeout):
            if kind == "logData":
                return str(data.get("data", ""))
        return ""

    # --- recarga --------------------------------------------------------------------------------

    def wait_reload_output(
        self,
        write: Callable[[], None],
        *,
        wait: float = 45.0,
        no_watchdog: float = 10.0,
    ) -> str:
        """Ejecuta `escribir()` y dice cuál de las cuatro salidas de REQ-034 ocurrió.

        Mira el historial de logs antes y después de escribir: un `/api/events` abierto se cierra
        cuando llama-swap reinicia su servidor, y el «configuration reloaded» lo escribe el nuevo,
        así que se vuelve a abrir. `caído` es que llama-swap no responde antes de escribir.
        """
        try:
            before = _count(self.log_history())
        except httpx2.TransportError:
            write()
            self.reload_detail = "conexión rechazada"
            return DOWN
        write()
        start_ts = time.monotonic()
        while (elapsed := time.monotonic() - start_ts) < wait:
            try:
                text = self.log_history(timeout=2)
            except httpx2.TransportError:
                text = ""  # el servidor viejo ya cerró y el nuevo aún no escucha
            now = _count(text) if text else before
            if now["rechazo"] > before["rechazo"]:
                self.reload_detail = next(
                    (x for x in text.splitlines() if any(f in x for f in _REFUSAL_PHRASES)), ""
                )
                return REFUSAL
            if now["recargada"] > before["recargada"]:
                return SURCHARGE
            if now["recargando"] == before["recargando"] and elapsed >= no_watchdog:
                return NOT_WATCHED
            time.sleep(0.5)
        return UNRESOLVED

    # --- clientes de apoyo ----------------------------------------------------------------------

    def launch_client(self, model: str, *, delay_s: float) -> subprocess.Popen[bytes]:
        """Un segundo proceso, otro cliente, que manda una petición larga y espera su respuesta."""
        code = (
            "import json, urllib.request;"
            f"c = json.dumps({{'model': {model!r}, 'messages': [], 'delay_s': {delay_s}}}).encode();"
            f"r = urllib.request.Request({self.url + '/v1/chat/completions'!r}, c,"
            " {'Content-Type': 'application/json'});"
            "urllib.request.urlopen(r, timeout=120).read()"
        )
        proc = subprocess.Popen([sys.executable, "-c", code])
        self._clients.append(proc)
        return proc


@contextlib.contextmanager
def fake_llamaswap(
    directory: Path,
    models: Sequence[FakeModel],
    *,
    watch_config: bool = True,
    start: bool = True,
) -> Iterator[FakeLlamaSwap]:
    """Lanza un llama-swap de prueba y, al salir, lo para y comprueba que no dejó procesos vivos."""
    real = real_llamaswap_pid()
    ls = FakeLlamaSwap(
        directory, models, watch_config=watch_config, protected=() if real is None else (real,)
    )
    try:
        if start:
            ls.start()
        yield ls
    finally:
        ls.stop()
        try:
            ls.check_processes()
        finally:
            ls.close_log()
