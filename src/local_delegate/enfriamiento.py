"""Enfriamiento por modelo, compartido entre procesos (F3: REQ-009 a REQ-012).

Un modelo que acumula N fallos seguidos de las clases que cuentan deja de recibir peticiones durante
T segundos. Al vencer vuelve a recibir: el primer éxito lo deja limpio y el primer fallo que cuente
lo enfría otra vez con la espera doblada, hasta Tmax. Ningún enfriamiento es permanente.

El estado vive en un fichero (`LOG_DIR/enfriamiento.json`) para que el daemon y cualquier proceso
stdio de la misma máquina vean el mismo contador y para que sobreviva a un reinicio. Se lee y se
escribe bajo bloqueo, y **si el fichero no se puede leer o el bloqueo no llega a tiempo, se sigue
como si no hubiera enfriamiento**: este módulo nunca bloquea ni hace fallar una delegación.

Solo guarda nombres de modelo, contadores y fechas. Nunca prompts, rutas ni contenido.

Además del estado, cada transición deja una línea en `enfriamiento-eventos.jsonl`: `entra`,
`reentra` y `limpia`. El estado solo guarda el presente y el primer éxito lo borra, así que sin ese
registro nadie podría contar después cuántos episodios hubo ni cómo acabaron, que es lo que decide
el criterio de P-4 (tarea 30).

Este módulo decide el estado; quién lo consulta y qué hace con él (saltar al respaldo, fallar al
momento) es de la tarea 28.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout

from . import config
from .estado_json import escribir_json_atomico, leer_json
from .fallos import Clase

#: Las clases que suman para el enfriamiento (tabla de F3). El resto son neutras: ni suman ni ponen
#: a cero. Capacidad y configuración incluidas (plan, tarea 26): no dicen nada de si el modelo
#: responde bien cuando se le deja.
CLASES_QUE_CUENTAN = frozenset({Clase.MODELO, Clase.TIMEOUT_LECTURA})

#: Cuánto se espera al bloqueo del fichero antes de seguir sin enfriamiento, como `inflight.json`.
ESPERA_BLOQUEO_S = 2.0

#: El registro de episodios, junto al fichero de estado. Lo lee `scripts/medir_enfriamiento.py`.
FICHERO_EVENTOS = "enfriamiento-eventos.jsonl"


def _anadir_lineas(ruta: Path, eventos: list[dict]) -> None:
    with ruta.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(evento, ensure_ascii=False) + "\n" for evento in eventos)


def _evento(ahora: float, modelo: str, tipo: str, entrada: dict, **extra: object) -> dict:
    """Una línea del registro: nombre de modelo, contadores y fechas, como el estado."""
    return {
        "ts": datetime.fromtimestamp(ahora, UTC).isoformat(timespec="seconds"),
        "modelo": modelo,
        "evento": tipo,
        "reentradas": entrada["reentradas"],
        "espera_s": entrada["espera_s"],
        **extra,
    }


@dataclass(frozen=True)
class Enfriado:
    """Un modelo que ahora mismo no debe recibir peticiones."""

    hasta: float
    restante_s: float
    #: Cuántas veces seguidas ha vuelto a entrar sin un éxito de por medio (1 la primera).
    reentradas: int


def _entrada(bruta: object) -> dict:
    """La entrada de un modelo con su esquema fijo, tolerando lo que haya dejado un fichero viejo."""
    entrada: dict = {"fallos": 0, "espera_s": 0.0, "hasta": None, "reentradas": 0}
    if not isinstance(bruta, dict):
        return entrada
    for clave in ("fallos", "reentradas"):
        valor = bruta.get(clave)
        if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0:
            entrada[clave] = valor
    for clave in ("espera_s", "hasta"):
        valor = bruta.get(clave)
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            entrada[clave] = float(valor)
    return entrada


class Estado:
    def __init__(
        self,
        ruta: Path,
        *,
        fallos: int,
        espera_s: float,
        espera_max_s: float,
        activo: bool = True,
        reloj: Callable[[], float] = time.time,
    ) -> None:
        self._ruta = Path(ruta)
        self._ruta_eventos = self._ruta.with_name(FICHERO_EVENTOS)
        self._fallos = max(1, int(fallos))
        self._espera_max_s = float(espera_max_s)
        self._espera_s = min(float(espera_s), self._espera_max_s)
        self._activo = activo
        self._reloj = reloj

    # --- Escribir ------------------------------------------------------------------------------

    def registrar_fallo(self, modelo: str, clase: Clase | str) -> None:
        """Suma un fallo si su clase cuenta; enfría al llegar a N, o al primer fallo tras vencer."""
        if Clase(clase) not in CLASES_QUE_CUENTAN:
            return
        ahora = self._reloj()
        eventos: list[dict] = []

        def aplicar(datos: dict) -> None:
            entrada = _entrada(datos.get(modelo))
            hasta = entrada["hasta"]
            if hasta is not None and ahora < hasta:
                # Ya está enfriándose (solo le llegan llamadas con `model` explícito, REQ-005): no
                # se dobla la espera por cada una, o unas pocas lo llevarían a Tmax de golpe.
                pass
            elif hasta is not None:
                # Venció y el primer fallo que cuenta lo vuelve a enfriar con la espera doblada.
                entrada["espera_s"] = min(entrada["espera_s"] * 2, self._espera_max_s)
                entrada["hasta"] = ahora + entrada["espera_s"]
                entrada["reentradas"] += 1
                entrada["fallos"] = 0
                eventos.append(_evento(ahora, modelo, "reentra", entrada, clase=Clase(clase).value))
            else:
                entrada["fallos"] += 1
                if entrada["fallos"] >= self._fallos:
                    entrada["espera_s"] = self._espera_s
                    entrada["hasta"] = ahora + self._espera_s
                    entrada["reentradas"] = 1
                    entrada["fallos"] = 0
                    eventos.append(
                        _evento(ahora, modelo, "entra", entrada, clase=Clase(clase).value)
                    )
            datos[modelo] = entrada

        self._mutar(aplicar, eventos)

    def registrar_exito(self, modelo: str) -> None:
        """Cualquier éxito deja el modelo limpio: sin contador y con la espera base (REQ-010/011).

        Sin entrada no hay nada que limpiar y no se escribe: el éxito es el camino de casi todas
        las delegaciones, y reescribir el fichero en cada una sería el coste que la spec no admite.
        Si el modelo llegó a enfriarse, el éxito cierra el episodio. `tras_vencer` distingue la
        recuperación de verdad de un éxito con `model` explícito en pleno enfriamiento (REQ-005).
        """
        ahora = self._reloj()
        eventos: list[dict] = []

        def aplicar(datos: dict) -> bool:
            bruta = datos.pop(modelo, None)
            if bruta is None:
                return False
            entrada = _entrada(bruta)
            if entrada["hasta"] is not None:
                tras_vencer = ahora >= entrada["hasta"]
                eventos.append(_evento(ahora, modelo, "limpia", entrada, tras_vencer=tras_vencer))
            return True

        self._mutar(aplicar, eventos)

    # --- Leer ----------------------------------------------------------------------------------

    def consultar(self, modelo: str) -> Enfriado | None:
        """El enfriamiento vigente del modelo, o None si puede recibir peticiones."""
        return self.activos().get(modelo)

    def activos(self) -> dict[str, Enfriado]:
        """Los modelos que ahora mismo están enfriándose, para `local_status`."""
        datos = self._leer()
        ahora = self._reloj()
        self._recortar_vencimientos_lejanos(datos, ahora)
        vigentes = {modelo: self._vigente(bruta, ahora) for modelo, bruta in datos.items()}
        return {modelo: enfriado for modelo, enfriado in vigentes.items() if enfriado is not None}

    # --- Interno -------------------------------------------------------------------------------

    def _recortar_vencimientos_lejanos(self, datos: dict, ahora: float) -> None:
        """Un `hasta` más allá de Tmax (un cambio de hora, un fichero de otra máquina) se GUARDA
        recortado, no solo se recorta al leer.

        Recortar contra «ahora» en cada lectura dejaba siempre Tmax por delante: el modelo no
        vencía nunca, que es justo el enfriamiento permanente que la spec prohíbe. Lo destapó un
        test que comprobaba el restante y no que el modelo llegara a quedar libre.
        """
        limite = ahora + self._espera_max_s
        lejanos = [
            modelo
            for modelo, bruta in datos.items()
            if (hasta := _entrada(bruta)["hasta"]) is not None and hasta > limite
        ]
        if not lejanos:
            return

        def recortar(actuales: dict) -> None:
            for modelo in lejanos:
                entrada = _entrada(actuales.get(modelo))
                if entrada["hasta"] is not None and entrada["hasta"] > limite:
                    entrada["hasta"] = limite
                    actuales[modelo] = entrada

        self._mutar(recortar)
        for modelo in lejanos:
            entrada = _entrada(datos[modelo])
            entrada["hasta"] = limite
            datos[modelo] = entrada

    def _vigente(self, bruta: object, ahora: float) -> Enfriado | None:
        entrada = _entrada(bruta)
        hasta = entrada["hasta"]
        if hasta is None or hasta <= ahora:
            return None
        return Enfriado(hasta=hasta, restante_s=hasta - ahora, reentradas=entrada["reentradas"])

    def _bloqueo(self) -> FileLock:
        return FileLock(str(self._ruta) + ".lock", timeout=ESPERA_BLOQUEO_S)

    def _leer(self) -> dict:
        if not self._activo:
            return {}
        try:
            with self._bloqueo():
                return leer_json(self._ruta)
        except (Timeout, OSError):
            return {}  # REQ-012: sin bloqueo o sin disco, como si no hubiera enfriamiento

    def _mutar(self, aplicar: Callable[[dict], object], eventos: list[dict] | None = None) -> None:
        """Aplica un cambio bajo el bloqueo. `aplicar` llena `eventos` si hubo transición: se
        escriben bajo el mismo bloqueo para que el orden del registro sea el del estado."""
        if not self._activo:
            return
        try:
            self._ruta.parent.mkdir(parents=True, exist_ok=True)
            with self._bloqueo():
                datos = leer_json(self._ruta)
                if aplicar(datos) is False:
                    return  # nada cambió: no se reescribe el fichero
                escribir_json_atomico(self._ruta, datos)
                if eventos:
                    try:
                        _anadir_lineas(self._ruta_eventos, eventos)
                    except OSError:
                        pass  # el registro es para medir: perderlo no deshace el estado ya escrito
        except (Timeout, OSError):
            return  # REQ-012: nunca bloquea ni hace fallar una delegación


def desde_config() -> Estado:
    """El estado con la configuración vigente, leída al llamar (los tests cambian `LOG_DIR`)."""
    return Estado(
        config.LOG_DIR / "enfriamiento.json",
        fallos=config.COOLDOWN_FAILURES,
        espera_s=config.COOLDOWN_S,
        espera_max_s=config.COOLDOWN_MAX_S,
        activo=config.COOLDOWN,
    )
