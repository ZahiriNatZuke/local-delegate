"""Escrituras concurrentes a la telemetría (SDD `telemetria-escritura-concurrente`).

Varios procesos de verdad (no hilos con el GIL de por medio) escriben a la vez detrás de una barrera
de inicio, con el `hook_common` suelto, como lo importan los hooks. Antes del arreglo, en Windows,
6 procesos x 300 líneas perdían entre el 10 y el 16 % y dejaban líneas partidas: con 6 x 400 y
exigiendo la cuenta exacta, pasar por suerte no está al alcance. En POSIX el `write` con
`O_APPEND` ya suele ser atómico: allí estos tests vigilan que no haya regresión.

Todo en `tmp_path`; nunca el log de uso real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import local_delegate
from local_delegate import hook_entry
from local_delegate.resources.hooks import hook_common

SRC = Path(local_delegate.__file__).resolve().parents[1]
HOOKS = Path(hook_common.__file__).resolve().parent
PROCESSES = 6
LINES = 400
PAD = 250  # ~330 bytes por línea, como las reales

WORKER = r"""
import json, os, sys, time
from pathlib import Path

mode, go, worker, count, pad, hooks = sys.argv[1:7]
worker, count, pad = int(worker), int(count), int(pad)
sys.path.insert(0, hooks)
import hook_common
from local_delegate import hook_entry

# Todo lo que tarda en cargarse, ANTES de la barrera: si no, arrancan desfasados y no chocan.
if mode == "mod":
    hook_entry._load_hook_module("suggest_delegate_read")
    hook_entry._load_hook_module("hook_common")
Path(go + f".ready{worker}").write_text("")
while not os.path.exists(go):
    time.sleep(0.001)
if mode == "record":
    for i in range(count):
        hook_common.record("PreToolUse", worker=worker, n=i, pad="x" * pad)
elif mode == "block":
    notes = Path(os.environ["NOTES"])
    for i in range(count):
        hook_common.record_block(f"w{worker}n{i:04d}", f"/doc/{worker}/{i}.md", notes)
elif mode == "failure":
    for i in range(count):
        hook_entry._log_failure(f"hook{worker}", ValueError("x" * pad), {"decision": "summarized"})
elif mode == "mod":
    env = dict(os.environ)
    for i in range(count):
        entry = {"id": f"{i:012x}", "via": "read_tool", "decision": "read_whole",
                 "scope": "whole", "session_id": "s"}
        hook_entry.record_read(entry, env)
"""


def _run_workers(tmp_path: Path, mode: str, *, processes=PROCESSES, count=LINES, env=None):
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    go = tmp_path / "go"
    base = {**os.environ, "PYTHONPATH": str(SRC), **(env or {})}
    procs: list[subprocess.Popen] = []
    try:
        for k in range(processes):
            procs.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(script),
                        mode,
                        str(go),
                        str(k),
                        str(count),
                        str(PAD),
                        str(HOOKS),
                    ],
                    env=base,
                )
            )
        # Barrera de verdad: cada proceso avisa de que está listo, con tope; luego salen a la vez.
        deadline = time.monotonic() + 60
        while not all(Path(f"{go}.ready{k}").exists() for k in range(processes)):
            assert all(p.poll() is None for p in procs), "un proceso murió antes de la barrera"
            assert time.monotonic() < deadline, "los procesos no llegaron a la barrera"
            time.sleep(0.01)
        go.write_text("", encoding="utf-8")
        for p in procs:
            assert p.wait(timeout=120) == 0
    finally:
        for p in procs:  # nada huérfano si algo falla a mitad
            if p.poll() is None:
                p.kill()
                p.wait(timeout=30)


def _lines(path: Path) -> tuple[list[dict], int]:
    good, bad = [], 0
    for raw in path.read_bytes().split(b"\n"):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict):
            good.append(row)
        else:
            bad += 1
    return good, bad


# --- REQ-001 / REQ-002: `record` --------------------------------------------------------------


def test_concurrent_records_keep_every_line(tmp_path):
    log = tmp_path / "telemetry.jsonl"
    _run_workers(tmp_path, "record", env={"LD_HOOK_TELEMETRY_LOG": str(log)})
    good, bad = _lines(log)
    assert bad == 0, f"{bad} líneas partidas"
    assert len(good) == PROCESSES * LINES
    assert {(r["worker"], r["n"]) for r in good} == {
        (w, n) for w in range(PROCESSES) for n in range(LINES)
    }


def test_concurrent_threads_keep_every_line(tmp_path, monkeypatch):
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    start = threading.Barrier(8)

    def worker(k: int) -> None:
        start.wait()
        for i in range(200):
            hook_common.record("PreToolUse", worker=k, n=i, pad="x" * PAD)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    good, bad = _lines(log)
    assert bad == 0
    assert len(good) == 8 * 200


# --- REQ-003: notas de bloqueo -----------------------------------------------------------------


def test_concurrent_blocks_keep_every_note(tmp_path):
    notes = tmp_path / "blocks.jsonl"
    per = (hook_common.MAX_NOTES // 2 - 1) // 4  # que quepan todas sin recortar
    _run_workers(tmp_path, "block", processes=4, count=per, env={"NOTES": str(notes)})
    good, bad = _lines(notes)
    assert bad == 0
    assert len({r["id"] for r in good}) == 4 * per
    assert len(good) <= hook_common.MAX_NOTES


# --- REQ-004: el log de fallos ------------------------------------------------------------------


def test_concurrent_failures_keep_every_line(tmp_path):
    log_dir = tmp_path / "logs"
    count = 60  # 6 x 60 líneas de ~120 bytes: por debajo del tope de 256 KiB
    _run_workers(tmp_path, "failure", count=count, env={"LOCAL_DELEGATE_LOG_DIR": str(log_dir)})
    good, bad = _lines(log_dir / hook_entry.FAILURE_LOG)
    assert bad == 0
    assert len(good) == PROCESSES * count


# --- REQ-005: dos vías del mod con el mismo `id` ---------------------------------------------


def test_racing_mod_roads_write_one_line(tmp_path):
    """El daemon tardío y el proceso de respaldo escriben la misma decisión a la vez."""
    log = tmp_path / "telemetry.jsonl"
    count = 150
    _run_workers(
        tmp_path,
        "mod",
        processes=8,
        count=count,
        env={"LD_HOOK_TELEMETRY_LOG": str(log), "LOCAL_DELEGATE_LOG_DIR": str(tmp_path / "l")},
    )
    good, bad = _lines(log)
    assert bad == 0
    ids = [r["id"] for r in good]
    assert len(set(ids)) == count, "guarda: llegaron todas las decisiones"
    assert len(ids) == count, f"{len(ids) - count} decisiones escritas dos veces"


# --- REQ-006: una línea partida no se traga la siguiente --------------------------------------


def test_a_torn_last_line_does_not_swallow_the_next(tmp_path, monkeypatch):
    log = tmp_path / "telemetry.jsonl"
    log.write_bytes(b'{"event": "ok"}\n{"event": "Pre')  # cortada, sin salto final
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    hook_common.record("PreToolUse", n=1)
    good, bad = _lines(log)
    assert bad == 1  # la cortada sigue ahí, sola
    assert [r.get("n") for r in good] == [None, 1]


# --- REQ-007: lectores ante una línea que es JSON pero no objeto -------------------------------


def test_readers_skip_a_non_object_line(tmp_path, monkeypatch):
    from local_delegate.web import metrics

    sys.path.insert(0, str(SRC.parent / "scripts"))
    try:
        import measure_adoption
    finally:
        sys.path.remove(str(SRC.parent / "scripts"))

    path = tmp_path / "usage-202611.jsonl"
    path.write_text('{"ts": "2026-11-09T10:00:00+00:00", "tool": "x"}\n123\n"frag"\n', "utf-8")
    rows = metrics._read_file_cached(path)
    assert all(isinstance(r, dict) for r in rows)
    assert len(rows) == 1
    assert len(measure_adoption.read(path, None)) == 1
    assert len(measure_adoption.read(path, "2026-01-01")) == 1


# --- REQ-008: un cerrojo retenido no cuelga el hook ------------------------------------------

HOLDER = r"""
import os, sys, time
sys.path.insert(0, sys.argv[3])
import hook_common
fd = os.open(sys.argv[1], os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0))
assert hook_common._try_lock(fd)
open(sys.argv[2], "w").close()
time.sleep(30)
"""


def test_a_held_lock_does_not_hang_the_hook(tmp_path, monkeypatch):
    log = tmp_path / "telemetry.jsonl"
    ready = tmp_path / "ready"
    holder_script = tmp_path / "holder.py"
    holder_script.write_text(HOLDER, encoding="utf-8")
    holder = subprocess.Popen(
        [sys.executable, str(holder_script), str(log), str(ready), str(HOOKS)]
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists():
            assert holder.poll() is None, "el proceso del cerrojo murió"
            assert time.monotonic() < deadline
            time.sleep(0.01)
        monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
        started = time.monotonic()
        hook_common.record("PreToolUse", n=1)
        elapsed = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert elapsed < hook_common.APPEND_LOCK_WAIT_S + 1.0
    good, _ = _lines(log)
    assert [r["n"] for r in good] == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="el cerrojo de rango obligatorio es de Windows")
def test_the_lock_does_not_block_readers(tmp_path):
    """El byte cerrado está muy lejos del final: leer el fichero con el cerrojo puesto funciona."""
    log = tmp_path / "telemetry.jsonl"
    log.write_text('{"a": 1}\n', encoding="utf-8")
    fd = os.open(log, os.O_RDWR | os.O_APPEND | getattr(os, "O_BINARY", 0))
    try:
        assert hook_common._try_lock(fd)
        assert log.read_text(encoding="utf-8") == '{"a": 1}\n'
        hook_common._unlock(fd)
    finally:
        os.close(fd)


@pytest.mark.skipif(sys.platform == "win32", reason="los bits de modo son de POSIX")
def test_a_new_file_is_private(tmp_path, monkeypatch):
    """En un `/tmp` compartido, otro usuario no puede abrirlo para retener el cerrojo."""
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    hook_common.record("PreToolUse", n=1)
    assert log.stat().st_mode & 0o077 == 0
