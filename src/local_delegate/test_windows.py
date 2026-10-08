"""Ventanas de prueba: intervalos UTC cuyas filas del log no cuentan como uso (test-windows-out-of-metrics).

Una prueba en vivo contra el MCP o el daemon escribe en el mismo log que el trabajo real. En vez de
reescribir el log, quien prueba marca el intervalo (`local-delegate test-window start|stop|add`) y
todo el que lee el log aparta las filas que caen dentro. Este módulo es la **única** copia de esa
regla: el panel, `local_status`, el coste, el recálculo y los medidores de `scripts/` la importan.

- `load(log_dir)` lee `LOG_DIR/test-windows.json` de forma tolerante (REQ-003): nunca lanza, y lo
  que no entiende lo cuenta como ignorado o lo deja en `error`.
- `Windows.find(ts)` dice en qué ventana cae una marca de tiempo (REQ-002): intervalo cerrado
  comparando instantes truncados al segundo, porque el log escribe `ts` truncado al segundo.
- `start`, `stop` y `add` escriben bajo un `FileLock` y con reemplazo atómico (REQ-010).

Solo guarda fechas, ids y la etiqueta que escriba quien marca: ni rutas ni contenido.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from filelock import FileLock, Timeout

FILE_NAME = "test-windows.json"
LOCK_NAME = "test-windows.lock"
VERSION = 1
#: Una ventana abierta más de esto es, casi seguro, una que se olvidó cerrar (D6).
OPEN_WARN_HOURS = 12
#: Lo que espera una escritura por el cerrojo antes de rendirse (REQ-010).
LOCK_TIMEOUT_S = 10.0


class TestWindowError(Exception):
    """Una operación sobre las ventanas no se pudo hacer. El texto va en español, para el usuario."""

    __test__ = False  # pytest: no es una clase de tests aunque empiece por «Test»


def parse_instant(text: object) -> datetime:
    """Un instante ISO 8601 con o sin zona y con o sin fracciones; sin zona = UTC.

    Lanza `ValueError` si no se entiende. Devuelve un `datetime` consciente de zona en UTC.
    """
    if isinstance(text, datetime):
        dt = text
    elif isinstance(text, str) and text.strip():
        dt = datetime.fromisoformat(text.strip())
    else:
        raise ValueError(f"fecha ilegible: {text!r}")
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def format_instant(dt: datetime) -> str:
    """El instante en UTC con milisegundos y `Z`, como se guarda en el fichero."""
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch_s(dt: datetime) -> int:
    """Segundos enteros desde la época, truncados (`floor_s` de REQ-002)."""
    return math.floor(dt.timestamp())


def _floor_ms(dt: datetime) -> datetime:
    return dt.replace(microsecond=dt.microsecond // 1000 * 1000)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Window:
    id: str
    start: datetime
    end: datetime | None
    label: str = ""
    created_at: str | None = None

    @property
    def is_open(self) -> bool:
        return self.end is None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "start": format_instant(self.start),
            "end": format_instant(self.end) if self.end is not None else None,
            "label": self.label,
            "created_at": self.created_at,
        }


@dataclass
class Windows:
    """Lo leído del fichero: las ventanas válidas ordenadas por inicio, lo ignorado y el error."""

    windows: list[Window] = field(default_factory=list)
    ignored: int = 0
    error: str | None = None
    exists: bool = False

    def __post_init__(self) -> None:
        # Índice en segundos enteros (REQ-002: truncados al segundo), por inicio. `_max_end[i]` es
        # el mayor fin de las ventanas 0..i (abierta = infinito): si es menor que la marca, ninguna
        # ventana anterior la contiene y se descarta sin recorrerlas. Es el caso de casi todas las
        # filas del log, y lo que mantiene el coste del panel dentro del 10 % con decenas de
        # ventanas (requisito no funcional del spec).
        self.windows.sort(key=lambda w: (w.start, w.id))
        self._starts = [_epoch_s(w.start) for w in self.windows]
        self._ends = [None if w.end is None else _epoch_s(w.end) for w in self.windows]
        self._max_end: list[float] = []
        tope = float("-inf")
        for e in self._ends:
            tope = max(tope, float("inf") if e is None else e)
            self._max_end.append(tope)

    def find(self, ts: object, now: datetime | None = None) -> str | None:
        """El id de la primera ventana (por inicio) que contiene `ts`, o `None`. Nunca lanza.

        Una marca ilegible no está en ninguna ventana. Una ventana abierta llega hasta `now`.
        """
        if not self.windows:
            return None
        try:
            t = _epoch_s(parse_instant(ts))
        except (ValueError, TypeError, OverflowError):
            return None
        hi = bisect.bisect_right(self._starts, t)
        if hi == 0 or self._max_end[hi - 1] < t:
            return None
        ahora: int | None = None
        for i in range(hi):
            fin = self._ends[i]
            if fin is None:
                if ahora is None:
                    ahora = _epoch_s(now if now is not None else _now())
                fin = ahora
            if t <= fin:
                return self.windows[i].id
        return None

    def open_windows(self) -> list[Window]:
        return [w for w in self.windows if w.is_open]

    def stale(self, now: datetime | None = None, hours: float = OPEN_WARN_HOURS) -> list[Window]:
        """Las abiertas hace más de `hours` horas (D6)."""
        now = now if now is not None else _now()
        return [w for w in self.open_windows() if (now - w.start).total_seconds() > hours * 3600]


def path_for(log_dir: Path) -> Path:
    return Path(log_dir) / FILE_NAME


def _window_from(entry: object) -> Window | None:
    """Una entrada del fichero como `Window`, o `None` si no se entiende (se ignora sola)."""
    if not isinstance(entry, dict):
        return None
    wid = entry.get("id")
    if not isinstance(wid, str) or not wid:
        return None
    try:
        start = parse_instant(entry.get("start"))
        raw_end = entry.get("end")
        end = None if raw_end is None else parse_instant(raw_end)
    except (ValueError, TypeError):
        return None
    if end is not None and end < start:
        return None
    label = entry.get("label")
    created = entry.get("created_at")
    return Window(
        id=wid,
        start=start,
        end=end,
        label=label if isinstance(label, str) else "",
        created_at=created if isinstance(created, str) else None,
    )


def _read_raw(path: Path) -> tuple[list | None, str | None, bool]:
    """(entradas crudas, motivo si el fichero entero es ilegible, existe)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], None, False
    except OSError as exc:
        return None, f"no se puede leer: {exc.__class__.__name__}", True
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"JSON roto (línea {getattr(exc, 'lineno', '?')})", True
    if not isinstance(data, dict):
        return None, "no es un objeto JSON", True
    if data.get("version") != VERSION:
        return None, f"versión desconocida: {data.get('version')!r}", True
    entries = data.get("windows")
    if not isinstance(entries, list):
        return None, "falta la lista «windows»", True
    return entries, None, True


def _parse(entries: list | None, error: str | None, exists: bool) -> Windows:
    if entries is None:
        return Windows(error=error, exists=exists)
    valid: list[Window] = []
    seen: set[str] = set()
    ignored = 0
    for entry in entries:
        w = _window_from(entry)
        if w is None or w.id in seen:
            ignored += 1
            continue
        seen.add(w.id)
        valid.append(w)
    valid.sort(key=lambda w: (w.start, w.id))
    return Windows(windows=valid, ignored=ignored, exists=exists)


# {ruta: (mtime_ns, size, Windows)}: releer solo si el fichero cambió (REQ-003).
_CACHE: dict[str, tuple[int, int, Windows]] = {}


def load(log_dir: Path) -> Windows:
    """Las ventanas de `log_dir`. Fichero ausente = sin ventanas. Nunca lanza."""
    try:
        path = path_for(log_dir)
        try:
            st = path.stat()
        except FileNotFoundError:
            _CACHE.pop(str(path), None)
            return Windows()
        key = str(path)
        cached = _CACHE.get(key)
        if cached and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
            return cached[2]
        result = _parse(*_read_raw(path))
        _CACHE[key] = (st.st_mtime_ns, st.st_size, result)
        return result
    except Exception as exc:  # observar nunca rompe una tool ni el panel
        return Windows(error=f"error inesperado: {exc.__class__.__name__}")


# --- Escritura -----------------------------------------------------------------------------------


def _write(path: Path, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".test-windows.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"version": VERSION, "windows": entries}, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass  # limpieza de mejor esfuerzo: que se propague el error original
        raise
    _CACHE.pop(str(path), None)


class _Locked:
    """Cerrojo + lectura cruda; niega la escritura si el fichero existente es ilegible."""

    def __init__(self, log_dir: Path, lock_timeout: float) -> None:
        self.log_dir = Path(log_dir)
        self.path = path_for(self.log_dir)
        self.lock_timeout = lock_timeout
        self.entries: list = []

    def __enter__(self) -> Self:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.log_dir / LOCK_NAME), timeout=self.lock_timeout)
        try:
            self.lock.acquire()
        except Timeout as exc:
            raise TestWindowError(
                f"otro proceso tiene ocupado {self.log_dir / LOCK_NAME} desde hace más de "
                f"{self.lock_timeout:g} s; vuelve a intentarlo"
            ) from exc
        entries, error, _exists = _read_raw(self.path)
        if entries is None:
            self.lock.release()
            raise TestWindowError(
                f"{self.path} es ilegible ({error}); no se toca. Arréglalo a mano o bórralo"
            )
        self.entries = entries
        return self

    def __exit__(self, *exc: object) -> None:
        self.lock.release()

    def windows(self) -> list[Window]:
        return [w for w in (_window_from(e) for e in self.entries) if w is not None]

    def new_id(self, start: datetime) -> str:
        base = "w-" + start.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        taken = {e.get("id") for e in self.entries if isinstance(e, dict)}
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"


def start(
    log_dir: Path,
    label: str = "",
    *,
    now: datetime | None = None,
    lock_timeout: float = LOCK_TIMEOUT_S,
) -> Window:
    """Abre una ventana que empieza ahora (REQ-006). Puede haber varias abiertas a la vez."""
    now = _floor_ms(now if now is not None else _now())
    with _Locked(log_dir, lock_timeout) as f:
        w = Window(
            id=f.new_id(now), start=now, end=None, label=label or "", created_at=format_instant(now)
        )
        f.entries.append(w.to_json())
        _write(f.path, f.entries)
    return w


def stop(
    log_dir: Path,
    window_id: str | None = None,
    *,
    now: datetime | None = None,
    lock_timeout: float = LOCK_TIMEOUT_S,
) -> Window:
    """Cierra la ventana `window_id`, o la única abierta si no se da id (REQ-007)."""
    now = _floor_ms(now if now is not None else _now())
    with _Locked(log_dir, lock_timeout) as f:
        if window_id is None:
            abiertas = [w for w in f.windows() if w.is_open]
            if not abiertas:
                raise TestWindowError("no hay ninguna ventana abierta")
            if len(abiertas) > 1:
                ids = ", ".join(w.id for w in abiertas)
                raise TestWindowError(
                    f"hay {len(abiertas)} ventanas abiertas ({ids}); di cuál con "
                    "`local-delegate test-window stop <id>`"
                )
            window_id = abiertas[0].id
        for i, entry in enumerate(f.entries):
            if isinstance(entry, dict) and entry.get("id") == window_id:
                w = _window_from(entry)
                if w is None:
                    raise TestWindowError(f"la ventana {window_id} está mal escrita en el fichero")
                if not w.is_open:
                    raise TestWindowError(f"la ventana {window_id} ya estaba cerrada")
                if now < w.start:
                    raise TestWindowError(f"la ventana {window_id} empieza después de ahora")
                closed = Window(w.id, w.start, now, w.label, w.created_at)
                f.entries[i] = {**entry, "end": format_instant(now)}
                _write(f.path, f.entries)
                return closed
        raise TestWindowError(f"no existe la ventana {window_id}")


def add(
    log_dir: Path,
    start_at: object,
    end_at: object,
    label: str = "",
    *,
    now: datetime | None = None,
    lock_timeout: float = LOCK_TIMEOUT_S,
) -> tuple[Window, bool]:
    """Añade una ventana cerrada (REQ-008). Devuelve (ventana, creada); si ya existía una con el
    mismo inicio y fin, no añade nada y devuelve esa con `False`."""
    try:
        # Al milisegundo, que es lo que se guarda: así un `add` repetido se reconoce como tal.
        s, e = (_floor_ms(parse_instant(x)) for x in (start_at, end_at))
    except (ValueError, TypeError) as exc:
        raise TestWindowError(f"fecha ilegible: {exc}") from exc
    if s >= e:
        raise TestWindowError("el inicio tiene que ser anterior al fin")
    now = _floor_ms(now if now is not None else _now())
    with _Locked(log_dir, lock_timeout) as f:
        for w in f.windows():
            if w.start == s and w.end == e:
                return w, False
        w = Window(
            id=f.new_id(s), start=s, end=e, label=label or "", created_at=format_instant(now)
        )
        f.entries.append(w.to_json())
        _write(f.path, f.entries)
    return w, True
