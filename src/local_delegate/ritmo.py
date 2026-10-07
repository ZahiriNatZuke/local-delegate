"""La velocidad normal de cada modelo y el ritmo de una llamada contra ella (REQ-025, REQ-028).

La velocidad **normal** de un modelo es la mediana de `tok_s` de sus ultimos 50 eventos correctos
con `tokens_out >= 8`. Vive en una ventana en memoria por modelo que se siembra al arrancar con el
log de uso del mes en curso y del anterior (`sembrar`) y se alimenta con cada evento propio
(`registrar`); nunca se relee el log en cada llamada. Con al menos 10 muestras, `medir` devuelve
`ritmo_rel` (`tok_s` / mediana, a dos decimales) y `lento` (`ritmo_rel < umbral`); sin referencia
devuelve `{}` y el evento omite los dos campos (nunca valen 0).

Se compara **solo la generacion** (`tok_s`), nunca el prefill (`prefill_tok_s`): una entrada larga
sube el prefill y no dice nada de si el modelo genera lento.

Forma de la referencia: el control de T3 (`scripts/medir_lentitud.py`, evidencia en
`evidencias/T3.md`) decidio **una referencia por modelo**: con los datos de la PC el tramo de mas de
10k tokens de entrada no baja de 0,75 x el de menos de 2k. El modo por tramos (`por_tramos=True`,
`<2k`, `2k-10k`, `>10k`, cada uno con su ventana y su minimo) queda disponible para el script de
control, que lo usa si su decision cambia; el daemon usa una sola.

Este modulo no conoce la topologia ni la config: el umbral llega como argumento. Y **nunca lanza**
(REQ-028): una entrada rara se ignora o da `{}`, porque observar no puede romper una tool.

`scripts/medir_lentitud.py` importa de aqui la regla (`calcular_lentitud`, `tramo_de` y las
constantes): una sola fuente para el script de control y para el daemon.
"""

from __future__ import annotations

import json
import math
import statistics
import threading
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

#: Eventos que forman la velocidad normal (REQ-025).
VENTANA = 50
MINIMO = 10
SALIDA_MINIMA = 8
#: Umbral por defecto de `lento` (decision del usuario); el daemon pasa `config.UMBRAL_LENTO`.
UMBRAL = 0.5
TRAMOS = ("<2k", "2k-10k", ">10k")
LIMITES_TRAMO = (2_000, 10_000)

Evento = dict[str, Any]


def tramo_de(tokens_entrada: float | None) -> str | None:
    """`<2k`, `2k-10k` o `>10k` segun los tokens de entrada; `None` si no se conocen."""
    if tokens_entrada is None:
        return None
    if tokens_entrada < LIMITES_TRAMO[0]:
        return TRAMOS[0]
    if tokens_entrada <= LIMITES_TRAMO[1]:
        return TRAMOS[1]
    return TRAMOS[2]


def _numero(valor: Any) -> float | None:
    """El valor como float finito; `None` si no es un numero (los `bool` no cuentan)."""
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return None
    valor = float(valor)
    return valor if math.isfinite(valor) else None


def _elegible(ok: Any, tokens_out: Any, tok_s: Any) -> bool:
    """Un evento forma (y se compara con) la velocidad normal: correcto, >= 8 tokens, `tok_s` > 0."""
    salida = _numero(tokens_out)
    velocidad = _numero(tok_s)
    return (
        ok is not False
        and ok is not None
        and salida is not None
        and salida >= SALIDA_MINIMA
        and velocidad is not None
        and velocidad > 0
    )


class Referencias:
    """Ventanas de `tok_s` por modelo (y por tramo de entrada si `por_tramos`).

    Seguro entre hilos: el daemon registra y mide desde varias tools a la vez.
    """

    def __init__(
        self, *, ventana: int = VENTANA, minimo: int = MINIMO, por_tramos: bool = False
    ) -> None:
        self._tam = ventana
        self._minimo = minimo
        self._por_tramos = por_tramos
        self._ventanas: dict[tuple[str, str | None], deque[float]] = defaultdict(
            lambda: deque(maxlen=self._tam)
        )
        self._cerrojo = threading.Lock()

    def _clave(self, modelo: str, tokens_in: Any) -> tuple[str, str | None]:
        return (modelo, tramo_de(_numero(tokens_in)) if self._por_tramos else None)

    # -- alimentar ----------------------------------------------------------------------------

    def anadir(self, modelo: Any, tok_s: Any, tokens_in: Any = None) -> bool:
        """Mete una muestra ya filtrada. Devuelve si entro (modelo y `tok_s` validos)."""
        velocidad = _numero(tok_s)
        if not isinstance(modelo, str) or not modelo or velocidad is None or velocidad <= 0:
            return False
        with self._cerrojo:
            self._ventanas[self._clave(modelo, tokens_in)].append(velocidad)
        return True

    def registrar(self, evento: Any) -> bool:
        """Mete un evento del log de uso (`model`, `ok`, `tokens_out`, `tok_s`, `tokens_in`).

        Solo entran los correctos con `tokens_out >= 8`. Nunca lanza; devuelve si entro.
        """
        try:
            if not isinstance(evento, dict):
                return False
            if not _elegible(evento.get("ok", True), evento.get("tokens_out"), evento.get("tok_s")):
                return False
            return self.anadir(evento.get("model"), evento.get("tok_s"), evento.get("tokens_in"))
        except Exception:
            return False

    def sembrar(self, lineas: Iterable[Any]) -> int:
        """Siembra con lineas JSON del log de uso, en orden. Devuelve cuantas muestras entraron.

        Una linea corrupta (JSON roto, tipo raro) se salta: la siembra sigue con las demas. Algo
        que no es iterable da 0. Si el propio iterable falla al recorrerse, el error sube: lo
        recoge `sembrar_desde_log`, que es la entrada del daemon.
        """
        try:
            iterador = iter(lineas)
        except TypeError:
            return 0
        return sum(1 for linea in iterador if self._registrar_linea(linea))

    def _registrar_linea(self, linea: Any) -> bool:
        """Una linea JSON del log; la corrupta da `False` en vez de lanzar."""
        try:
            return self.registrar(json.loads(linea))
        except Exception:
            return False

    # -- consultar ----------------------------------------------------------------------------

    def ventana(self, modelo: str, tokens_in: Any = None) -> list[float]:
        """Copia de las muestras de la ventana del modelo (y del tramo de `tokens_in`)."""
        try:
            with self._cerrojo:
                return list(self._ventanas.get(self._clave(modelo, tokens_in), ()))
        except Exception:
            return []

    def referencia(self, modelo: Any, tokens_in: Any = None) -> float | None:
        """Mediana de la ventana, o `None` con menos del minimo de muestras."""
        if not isinstance(modelo, str):
            return None
        muestras = self.ventana(modelo, tokens_in)
        if len(muestras) < self._minimo or not muestras:
            return None
        return statistics.median(muestras)

    def evaluar(
        self, modelo: Any, tok_s: Any, tokens_in: Any = None, *, umbral: float = UMBRAL
    ) -> tuple[float, float, bool] | None:
        """`(referencia, ritmo_rel, lento)` de una velocidad, o `None` sin referencia."""
        velocidad = _numero(tok_s)
        if velocidad is None or velocidad <= 0:
            return None
        ref = self.referencia(modelo, tokens_in)
        if ref is None or ref <= 0:
            return None
        ritmo = round(velocidad / ref, 2)
        return ref, ritmo, ritmo < umbral

    def medir(
        self,
        modelo: Any,
        tok_s: Any,
        tokens_in: Any = None,
        *,
        umbral: float = UMBRAL,
        tokens_out: Any = None,
    ) -> dict[str, Any]:
        """`{"ritmo_rel", "lento"}` de una llamada contra la velocidad normal; `{}` sin referencia.

        `tokens_out`, si se pasa, aplica el mismo filtro que la ventana: con menos de 8 tokens de
        salida la velocidad no dice nada y no se evalua. Nunca lanza.
        """
        try:
            if tokens_out is not None and not _elegible(True, tokens_out, tok_s):
                return {}
            resultado = self.evaluar(modelo, tok_s, tokens_in, umbral=umbral)
            if resultado is None:
                return {}
            _, ritmo, lento = resultado
            return {"ritmo_rel": ritmo, "lento": bool(lento)}
        except Exception:
            return {}

    def resumen(self) -> list[dict[str, Any]]:
        """Por ventana: `modelo`, `tramo`, `mediana` (o `None` bajo el minimo) y `muestras`."""
        try:
            with self._cerrojo:
                copias = {clave: list(v) for clave, v in self._ventanas.items()}
            filas = []
            for (modelo, tramo), muestras in sorted(copias.items(), key=lambda kv: str(kv[0])):
                filas.append(
                    {
                        "modelo": modelo,
                        "tramo": tramo,
                        "mediana": statistics.median(muestras)
                        if len(muestras) >= self._minimo and muestras
                        else None,
                        "muestras": len(muestras),
                    }
                )
            return filas
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Siembra desde el log de uso
# ---------------------------------------------------------------------------


def _mes_anterior(ahora: datetime) -> tuple[int, int]:
    return (ahora.year - 1, 12) if ahora.month == 1 else (ahora.year, ahora.month - 1)


def ficheros_de_siembra(directorio: Path, ahora: datetime) -> list[Path]:
    """`usage-AAAAMM.jsonl` del mes anterior y del mes en curso, en ese orden (los que existan)."""
    try:
        anio, mes = _mes_anterior(ahora)
        nombres = (f"usage-{anio:04d}{mes:02d}.jsonl", f"usage-{ahora:%Y%m}.jsonl")
        return [Path(directorio) / n for n in nombres if (Path(directorio) / n).is_file()]
    except Exception:
        return []


def _texto(fichero: Path) -> str:
    """El contenido del fichero; uno ilegible cuenta como vacio."""
    try:
        return fichero.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def lineas_de_siembra(directorio: Path, ahora: datetime) -> Iterator[str]:
    """Las lineas del log del mes anterior y del mes en curso. Un fichero ilegible se salta."""
    for fichero in ficheros_de_siembra(directorio, ahora):
        yield from _texto(fichero).splitlines()


def sembrar_desde_log(referencias: Referencias, directorio: Path, ahora: datetime) -> int:
    """Siembra `referencias` con el log de uso del mes en curso y del anterior. Nunca lanza."""
    try:
        return referencias.sembrar(lineas_de_siembra(directorio, ahora))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# La regla sobre una serie de eventos (script de control de T3)
# ---------------------------------------------------------------------------


def calcular_lentitud(
    eventos: Iterable[Evento],
    *,
    ventana: int = VENTANA,
    minimo: int = MINIMO,
    umbral: float = UMBRAL,
    por_tramos: bool = False,
) -> list[Evento]:
    """Aplica la regla de REQ-025 a una serie y devuelve los eventos ordenados con su referencia.

    Cada evento de entrada es un dict con `ts` (numero; orden temporal), `modelo`, `tok_s`,
    `tokens_out`, `ok` (opcional, por defecto cierto) y, si `por_tramos`, `tokens_in`. La salida
    son copias en orden temporal con `ref`, `ritmo_rel` y `lento` **solo** cuando hay referencia
    (con menos de `minimo` muestras se omiten, nunca valen 0).

    La referencia de un evento mira solo hacia atras: es la de `Referencias` antes de registrarlo.
    El propio evento no entra en su referencia; despues de evaluarlo, si es elegible, entra.
    """
    ordenados = sorted((dict(e) for e in eventos), key=lambda e: e["ts"])
    referencias = Referencias(ventana=ventana, minimo=minimo, por_tramos=por_tramos)
    for evento in ordenados:
        elegible = _elegible(evento.get("ok", True), evento.get("tokens_out"), evento.get("tok_s"))
        evento["elegible"] = elegible
        if not elegible:
            continue
        resultado = referencias.evaluar(
            evento["modelo"], evento["tok_s"], evento.get("tokens_in"), umbral=umbral
        )
        if resultado is not None:
            evento["ref"], evento["ritmo_rel"], evento["lento"] = resultado
        referencias.anadir(evento["modelo"], evento["tok_s"], evento.get("tokens_in"))
    return ordenados
