"""Las ventanas de prueba: forma del fichero, la regla del borde y la escritura segura (T1).

Cada test usa `tmp_path` como `LOG_DIR`: nunca toca el fichero real de la máquina.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
from datetime import UTC, datetime, timedelta

import pytest
from filelock import FileLock

from local_delegate import test_windows as tw


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(tmp_path, data) -> None:
    (tmp_path / tw.FILE_NAME).write_text(
        data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
    )


# --- Forma del fichero (REQ-001) -----------------------------------------------------------------


def test_start_stop_add_keep_the_file_shape(tmp_path):
    t0 = datetime(2026, 10, 8, 1, 20, 5, 255000, tzinfo=UTC)
    w = tw.start(tmp_path, "ola 11", now=t0)
    assert w.id == "w-20261008T012005Z"
    tw.stop(tmp_path, w.id, now=t0 + timedelta(seconds=146, microseconds=289000))
    data = json.loads((tmp_path / tw.FILE_NAME).read_text(encoding="utf-8"))
    assert data["version"] == 1
    (entry,) = data["windows"]
    assert set(entry) == {"id", "start", "end", "label", "created_at"}
    assert entry["start"] == "2026-10-08T01:20:05.255Z"
    assert entry["end"] == "2026-10-08T01:22:31.544Z"
    assert entry["label"] == "ola 11"
    assert entry["created_at"].endswith("Z")


def test_the_id_gets_a_suffix_if_repeated(tmp_path):
    t0 = datetime(2026, 10, 8, 1, 0, 0, tzinfo=UTC)
    ids = [tw.start(tmp_path, now=t0).id for _ in range(3)]
    assert ids == ["w-20261008T010000Z", "w-20261008T010000Z-2", "w-20261008T010000Z-3"]


# --- La regla del borde (REQ-002) ----------------------------------------------------------------


@pytest.fixture
def wave11(tmp_path):
    tw.add(tmp_path, "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z", "ola 11")
    return tw.load(tmp_path)


@pytest.mark.parametrize(
    ("hour", "inside"),
    [
        ("01:20:04", False),
        ("01:20:05", True),
        ("01:22:31", True),
        ("01:22:32", False),
        ("01:22:33", False),
    ],
)
def test_the_edge_second(wave11, hour, inside):
    ts = f"2026-10-08T{hour}+00:00"
    assert (wave11.find(ts) is not None) is inside, ts


def test_a_timestamp_without_zone_is_utc_and_an_unreadable_one_is_in_none(wave11):
    assert wave11.find("2026-10-08T01:21:00") == "w-20261008T012005Z"
    assert wave11.find("ayer") is None
    assert wave11.find(None) is None


def test_an_open_window_reaches_now(tmp_path):
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
    tw.start(tmp_path, now=t0)
    windows = tw.load(tmp_path)
    now = t0 + timedelta(minutes=5)
    assert windows.find(now - timedelta(seconds=1), now=now) is not None
    assert windows.find(now + timedelta(seconds=1), now=now) is None


def test_overlapping_ones_stamp_the_first_by_start(tmp_path):
    tw.add(tmp_path, "2026-10-08T02:00:00Z", "2026-10-08T03:00:00Z", "b")
    tw.add(tmp_path, "2026-10-08T01:00:00Z", "2026-10-08T04:00:00Z", "a")
    v = tw.load(tmp_path)
    assert v.find("2026-10-08T02:30:00Z") == "w-20261008T010000Z"
    # Dentro de «a» y después del fin de «b», la última por inicio: el descarte rápido tiene que
    # mirar el mayor fin de las anteriores, no solo el de la última.
    assert v.find("2026-10-08T03:30:00Z") == "w-20261008T010000Z"
    assert v.find("2026-10-08T04:00:01Z") is None


# --- Lectura tolerante (REQ-003) -----------------------------------------------------------------


def test_without_a_file_there_are_no_windows_and_no_error(tmp_path):
    v = tw.load(tmp_path)
    assert (v.windows, v.ignored, v.error, v.exists) == ([], 0, None, False)
    assert v.find("2026-10-08T01:00:00Z") is None


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{roto", "JSON roto"),
        ({"version": 2, "windows": []}, "versión desconocida"),
        ([1, 2], "no es un objeto"),
    ],
)
def test_an_unreadable_file_gives_an_error_and_does_not_raise(tmp_path, content, reason):
    _write(tmp_path, content)
    v = tw.load(tmp_path)
    assert v.windows == []
    assert v.error is not None and reason in v.error
    assert v.find("2026-10-08T01:00:00Z") is None


def test_unreadable_entries_are_ignored_on_their_own(tmp_path):
    good = {"id": "w-1", "start": "2026-10-08T01:00:00Z", "end": "2026-10-08T02:00:00Z"}
    _write(
        tmp_path,
        {
            "version": 1,
            "windows": [
                good,
                {"id": "w-2", "end": "2026-10-08T02:00:00Z"},  # falta start
                {"id": "w-3", "start": "not-a-date", "end": None},
                {"id": "w-4", "start": "2026-10-08T03:00:00Z", "end": "2026-10-08T02:00:00Z"},
                {**good},  # id repetido
            ],
        },
    )
    v = tw.load(tmp_path)
    assert [w.id for w in v.windows] == ["w-1"]
    assert v.ignored == 4
    assert v.error is None


def test_the_read_is_cached_and_renewed_on_write(tmp_path):
    tw.add(tmp_path, "2026-10-08T01:00:00Z", "2026-10-08T02:00:00Z")
    a = tw.load(tmp_path)
    assert tw.load(tmp_path) is a
    tw.add(tmp_path, "2026-10-08T03:00:00Z", "2026-10-08T04:00:00Z")
    b = tw.load(tmp_path)
    assert b is not a and len(b.windows) == 2


# --- Escritura segura (REQ-010) ------------------------------------------------------------------


@pytest.mark.parametrize("operation", ["start", "stop", "add"])
def test_does_not_overwrite_an_unreadable_file(tmp_path, operation):
    _write(tmp_path, "{roto")
    before = _sha(tmp_path / tw.FILE_NAME)
    with pytest.raises(tw.TestWindowError, match="ilegible"):
        if operation == "start":
            tw.start(tmp_path)
        elif operation == "stop":
            tw.stop(tmp_path)
        else:
            tw.add(tmp_path, "2026-10-08T01:00:00Z", "2026-10-08T02:00:00Z")
    assert _sha(tmp_path / tw.FILE_NAME) == before


def test_with_the_lock_taken_it_gives_up(tmp_path):
    foreign = FileLock(str(tmp_path / tw.LOCK_NAME))
    with foreign, pytest.raises(tw.TestWindowError, match="ocupado"):
        tw.start(tmp_path, lock_timeout=0.2)
    assert not (tmp_path / tw.FILE_NAME).exists()


def _open(log_dir: str, label: str) -> None:
    from pathlib import Path

    from local_delegate import test_windows

    test_windows.start(Path(log_dir), label, now=datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC))


def test_two_processes_open_at_once_and_both_remain(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    processes = [ctx.Process(target=_open, args=(str(tmp_path), f"p{i}")) for i in range(2)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(60)
        assert p.exitcode == 0
    v = tw.load(tmp_path)
    assert len(v.open_windows()) == 2
    assert len({w.id for w in v.windows}) == 2
    assert {w.label for w in v.windows} == {"p0", "p1"}


# --- stop y add (REQ-007, REQ-008, en el módulo) -------------------------------------------------


def test_stop_without_id_with_several_open_closes_none(tmp_path):
    a = tw.start(tmp_path, now=datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC))
    b = tw.start(tmp_path, now=datetime(2026, 10, 8, 9, 0, 1, tzinfo=UTC))
    with pytest.raises(tw.TestWindowError) as info:
        tw.stop(tmp_path)
    assert a.id in str(info.value) and b.id in str(info.value)
    assert len(tw.load(tmp_path).open_windows()) == 2


def test_stop_of_a_closed_or_nonexistent_one_fails(tmp_path):
    w = tw.start(tmp_path, now=datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC))
    tw.stop(tmp_path, w.id, now=datetime(2026, 10, 8, 9, 5, 0, tzinfo=UTC))
    with pytest.raises(tw.TestWindowError, match="ya estaba cerrada"):
        tw.stop(tmp_path, w.id)
    with pytest.raises(tw.TestWindowError, match="no existe"):
        tw.stop(tmp_path, "w-none")
    with pytest.raises(tw.TestWindowError, match="ninguna ventana abierta"):
        tw.stop(tmp_path)


def test_repeated_add_does_not_duplicate(tmp_path):
    _, created = tw.add(tmp_path, "2026-09-15T19:31:14Z", "2026-09-15T19:35:14Z", "P-4")
    assert created
    _, created = tw.add(tmp_path, "2026-09-15T19:31:14+00:00", "2026-09-15T19:35:14.000", "otra")
    assert not created
    assert len(tw.load(tmp_path).windows) == 1


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-10-08T02:00:00Z", "2026-10-08T01:00:00Z"),
        ("2026-10-08T01:00:00Z", "2026-10-08T01:00:00Z"),
        ("ayer", "hoy"),
    ],
)
def test_add_rejects_broken_or_reversed_dates(tmp_path, start, end):
    with pytest.raises(tw.TestWindowError):
        tw.add(tmp_path, start, end)


def test_stale_counts_the_ones_open_for_more_than_twelve_hours(tmp_path):
    now = datetime(2026, 10, 8, 22, 0, 0, tzinfo=UTC)
    old = tw.start(tmp_path, now=now - timedelta(hours=13))
    tw.start(tmp_path, now=now - timedelta(hours=1))
    assert [w.id for w in tw.load(tmp_path).stale(now)] == [old.id]
