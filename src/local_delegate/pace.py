"""La velocidad normal de cada modelo y el ritmo de una llamada contra ella (REQ-025, REQ-028).

La velocidad **normal** de un modelo es la mediana de `tok_s` de sus ultimos 50 eventos correctos
con `tokens_out >= 8`. Vive en una ventana en memoria por modelo que se siembra la primera vez que
hace falta (el primer evento con ritmo, o `local_status`) con el log de uso del mes en curso y del
anterior (`seed`) y se alimenta con cada evento propio
(`record`); nunca se relee el log en cada llamada. Con al menos 10 muestras, `measure` devuelve
`pace_rel` (`tok_s` / mediana, a dos decimales) y `slow` (`pace_rel < umbral`); sin referencia
devuelve `{}` y el evento omite los dos campos (nunca valen 0).

Se compara **solo la generacion** (`tok_s`), nunca el prefill (`prefill_tok_s`): una entrada larga
sube el prefill y no dice nada de si el modelo genera lento.

Forma de la referencia: el control de T3 (`scripts/measure_slowness.py`, evidencia en
`evidencias/T3.md`) decidio **una referencia por modelo**: con los datos de la PC el tramo de mas de
10k tokens de entrada no baja de 0,75 x el de menos de 2k. El modo por tramos (`by_spans=True`,
`<2k`, `2k-10k`, `>10k`, cada uno con su ventana y su minimo) queda disponible para el script de
control, que lo usa si su decision cambia; el daemon usa una sola.

Este modulo no conoce la topologia ni la config: el umbral llega como argumento. Y **nunca lanza**
(REQ-028): una entrada rara se ignora o da `{}`, porque observar no puede romper una tool.

`scripts/measure_slowness.py` importa de aqui la regla (`compute_slowness`, `span_of` y las
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
WINDOW = 50
MINIMUM = 10
MINIMAL_OUTPUT = 8
#: Umbral por defecto de `slow` (decision del usuario); el daemon pasa `config.SLOW_THRESHOLD`.
THRESHOLD = 0.5
SPANS = ("<2k", "2k-10k", ">10k")
SPAN_LIMITS = (2_000, 10_000)

Event = dict[str, Any]


def span_of(input_tokens: float | None) -> str | None:
    """`<2k`, `2k-10k` o `>10k` segun los tokens de entrada; `None` si no se conocen."""
    if input_tokens is None:
        return None
    if input_tokens < SPAN_LIMITS[0]:
        return SPANS[0]
    if input_tokens <= SPAN_LIMITS[1]:
        return SPANS[1]
    return SPANS[2]


def _number(value: Any) -> float | None:
    """El valor como float finito; `None` si no es un numero (los `bool` no cuentan)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _eligible(ok: Any, tokens_out: Any, tok_s: Any) -> bool:
    """Un evento forma (y se compara con) la velocidad normal: correcto, >= 8 tokens, `tok_s` > 0."""
    output = _number(tokens_out)
    speed = _number(tok_s)
    return (
        ok is not False
        and ok is not None
        and output is not None
        and output >= MINIMAL_OUTPUT
        and speed is not None
        and speed > 0
    )


class References:
    """Ventanas de `tok_s` por modelo (y por tramo de entrada si `by_spans`).

    Seguro entre hilos: el daemon registra y mide desde varias tools a la vez.
    """

    def __init__(
        self, *, window: int = WINDOW, minimum: int = MINIMUM, by_spans: bool = False
    ) -> None:
        self._tam = window
        self._minimum = minimum
        self._by_spans = by_spans
        self._windows: dict[tuple[str, str | None], deque[float]] = defaultdict(
            lambda: deque(maxlen=self._tam)
        )
        self._lock = threading.Lock()

    def _key(self, model: str, tokens_in: Any) -> tuple[str, str | None]:
        return (model, span_of(_number(tokens_in)) if self._by_spans else None)

    # -- alimentar ----------------------------------------------------------------------------

    def add(self, model: Any, tok_s: Any, tokens_in: Any = None) -> bool:
        """Mete una muestra ya filtrada. Devuelve si entro (modelo y `tok_s` validos)."""
        speed = _number(tok_s)
        if not isinstance(model, str) or not model or speed is None or speed <= 0:
            return False
        with self._lock:
            self._windows[self._key(model, tokens_in)].append(speed)
        return True

    def record(self, event: Any) -> bool:
        """Mete un evento del log de uso (`model`, `ok`, `tokens_out`, `tok_s`, `tokens_in`).

        Solo entran los correctos con `tokens_out >= 8`. Nunca lanza; devuelve si entro.
        """
        try:
            if not isinstance(event, dict):
                return False
            if not _eligible(event.get("ok", True), event.get("tokens_out"), event.get("tok_s")):
                return False
            return self.add(event.get("model"), event.get("tok_s"), event.get("tokens_in"))
        except Exception:
            return False

    def seed(self, lines: Iterable[Any]) -> int:
        """Siembra con lineas JSON del log de uso, en orden. Devuelve cuantas muestras entraron.

        Una linea corrupta (JSON roto, tipo raro) se salta: la siembra sigue con las demas. Algo
        que no es iterable da 0. Si el propio iterable falla al recorrerse, el error sube: lo
        recoge `seed_from_log`, que es la entrada del daemon.
        """
        try:
            iterador = iter(lines)
        except TypeError:
            return 0
        return sum(1 for line in iterador if self._record_line(line))

    def _record_line(self, line: Any) -> bool:
        """Una linea JSON del log; la corrupta da `False` en vez de lanzar."""
        try:
            return self.record(json.loads(line))
        except Exception:
            return False

    # -- consultar ----------------------------------------------------------------------------

    def window(self, model: str, tokens_in: Any = None) -> list[float]:
        """Copia de las muestras de la ventana del modelo (y del tramo de `tokens_in`)."""
        try:
            with self._lock:
                return list(self._windows.get(self._key(model, tokens_in), ()))
        except Exception:
            return []

    def reference(self, model: Any, tokens_in: Any = None) -> float | None:
        """Mediana de la ventana, o `None` con menos del minimo de muestras."""
        if not isinstance(model, str):
            return None
        samples = self.window(model, tokens_in)
        if len(samples) < self._minimum or not samples:
            return None
        return statistics.median(samples)

    def evaluate(
        self, model: Any, tok_s: Any, tokens_in: Any = None, *, threshold: float = THRESHOLD
    ) -> tuple[float, float, bool] | None:
        """`(referencia, pace_rel, lento)` de una velocidad, o `None` sin referencia."""
        speed = _number(tok_s)
        if speed is None or speed <= 0:
            return None
        ref = self.reference(model, tokens_in)
        if ref is None or ref <= 0:
            return None
        pace = round(speed / ref, 2)
        return ref, pace, pace < threshold

    def measure(
        self,
        model: Any,
        tok_s: Any,
        tokens_in: Any = None,
        *,
        threshold: float = THRESHOLD,
        tokens_out: Any = None,
    ) -> dict[str, Any]:
        """`{"pace_rel", "slow"}` de una llamada contra la velocidad normal; `{}` sin referencia.

        `tokens_out`, si se pasa, aplica el mismo filtro que la ventana: con menos de 8 tokens de
        salida la velocidad no dice nada y no se evalua. Nunca lanza.
        """
        try:
            if tokens_out is not None and not _eligible(True, tokens_out, tok_s):
                return {}
            result = self.evaluate(model, tok_s, tokens_in, threshold=threshold)
            if result is None:
                return {}
            _, pace, slow = result
            return {"pace_rel": pace, "slow": bool(slow)}
        except Exception:
            return {}

    def summary(self) -> list[dict[str, Any]]:
        """Por ventana: `model`, `span`, `median` (o `None` bajo el minimo) y `samples`."""
        try:
            with self._lock:
                copies = {key: list(v) for key, v in self._windows.items()}
            rows = []
            for (model, span), samples in sorted(copies.items(), key=lambda kv: str(kv[0])):
                rows.append(
                    {
                        "model": model,
                        "span": span,
                        "median": statistics.median(samples)
                        if len(samples) >= self._minimum and samples
                        else None,
                        "samples": len(samples),
                    }
                )
            return rows
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Siembra desde el log de uso
# ---------------------------------------------------------------------------


def _previous_month(now: datetime) -> tuple[int, int]:
    return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)


def seed_files(directory: Path, now: datetime) -> list[Path]:
    """`usage-AAAAMM.jsonl` del mes anterior y del mes en curso, en ese orden (los que existan)."""
    try:
        year, month = _previous_month(now)
        names = (f"usage-{year:04d}{month:02d}.jsonl", f"usage-{now:%Y%m}.jsonl")
        return [Path(directory) / n for n in names if (Path(directory) / n).is_file()]
    except Exception:
        return []


def _text(file: Path) -> str:
    """El contenido del fichero; uno ilegible cuenta como vacio."""
    try:
        return file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def seed_lines(directory: Path, now: datetime) -> Iterator[str]:
    """Las lineas del log del mes anterior y del mes en curso. Un fichero ilegible se salta."""
    for file in seed_files(directory, now):
        yield from _text(file).splitlines()


def seed_from_log(references: References, directory: Path, now: datetime) -> int:
    """Siembra `references` con el log de uso del mes en curso y del anterior. Nunca lanza."""
    try:
        return references.seed(seed_lines(directory, now))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# La regla sobre una serie de eventos (script de control de T3)
# ---------------------------------------------------------------------------


def compute_slowness(
    events: Iterable[Event],
    *,
    window: int = WINDOW,
    minimum: int = MINIMUM,
    threshold: float = THRESHOLD,
    by_spans: bool = False,
) -> list[Event]:
    """Aplica la regla de REQ-025 a una serie y devuelve los eventos ordenados con su referencia.

    Cada evento de entrada es un dict con `ts` (numero; orden temporal), `modelo`, `tok_s`,
    `tokens_out`, `ok` (opcional, por defecto cierto) y, si `by_spans`, `tokens_in`. La salida
    son copias en orden temporal con `ref`, `pace_rel` y `slow` **solo** cuando hay referencia
    (con menos de `minimum` muestras se omiten, nunca valen 0).

    La referencia de un evento mira solo hacia atras: es la de `References` antes de registrarlo.
    El propio evento no entra en su referencia; despues de evaluarlo, si es elegible, entra.
    """
    sorted_ones = sorted((dict(e) for e in events), key=lambda e: e["ts"])
    references = References(window=window, minimum=minimum, by_spans=by_spans)
    for event in sorted_ones:
        eligible = _eligible(event.get("ok", True), event.get("tokens_out"), event.get("tok_s"))
        event["eligible"] = eligible
        if not eligible:
            continue
        result = references.evaluate(
            event["modelo"], event["tok_s"], event.get("tokens_in"), threshold=threshold
        )
        if result is not None:
            event["ref"], event["pace_rel"], event["slow"] = result
        references.add(event["modelo"], event["tok_s"], event.get("tokens_in"))
    return sorted_ones
