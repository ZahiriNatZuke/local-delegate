"""Atribución en vivo: `tool_use_id`, hook, resolución y reglas comunes (coste-api-y-cuota, T2).

Los transcripts, las notas y los logs son SINTÉTICOS y viven en `tmp_path`. Los tests que lanzan el
hook como proceso le ponen `TEMP`, `TMP` y `TMPDIR` en `tmp_path`, para no escribir en el temporal
real que lee el daemon en vivo.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import Implementation

from local_delegate import attribution, clients, server
from local_delegate.resources.hooks import hook_common

HOOK = Path(hook_common.__file__).parent / "record_call.py"
AGENT = "general-purpose"
OPUS = "claude-opus-5-5"


# --- Arnés --------------------------------------------------------------------------------------


def _tmp_dir(tmp_path: Path, name: str = "temp") -> Path:
    dest = tmp_path / name
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _hook_env(tmp_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {"TEMP": str(tmp_dir), "TMP": str(tmp_dir), "TMPDIR": str(tmp_dir)},
        CLAUDE_EFFORT="high",
    )
    return env


def _launch_hook(entry: bytes, tmp_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=entry,
        env=_hook_env(tmp_dir),
        capture_output=True,
        timeout=30,
        check=False,
    )


def _notes_dir(tmp_dir: Path) -> Path:
    return tmp_dir / "local-delegate-calls"


def _hook_input(tool_use_id: str, transcript: Path | str, **extra) -> dict:
    return {
        "session_id": "sesion-sintetica",
        "transcript_path": str(transcript),
        "cwd": "C:/proyecto",
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__local-delegate__local_summarize",
        "tool_use_id": tool_use_id,
        **extra,
    }


def _tool_use_line(tool_use_id: str, model: str, session: str = "s1") -> str:
    return json.dumps(
        {
            "type": "assistant",
            "sessionId": session,
            "message": {
                "model": model,
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": "mcp__local-delegate__local_summarize",
                        "input": {},
                    }
                ],
            },
        }
    )


def _projects(tmp_path: Path) -> Path:
    root = tmp_path / "home" / ".claude" / "projects"
    (root / "D--proyecto").mkdir(parents=True, exist_ok=True)
    return root


def _write(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_note(notes: Path, tool_use_id: str, transcript: Path, **extra) -> None:
    assert hook_common.record_call(_hook_input(tool_use_id, transcript, **extra), notes)


# --- El hook ------------------------------------------------------------------------------------


def test_hook_server_round_trip(tmp_path):
    """REQ-002: escribe el hook (proceso aparte) y lee el servidor. El esfuerzo sale de la entrada.

    Control (b): mutante «el hook toma `os.environ.get("CLAUDE_EFFORT")`» → el entorno dice
    `high` y la entrada `low`.
    """
    tmp_dir = _tmp_dir(tmp_path)
    entry = _hook_input(
        "toolu_ida",
        "C:/x/s1.jsonl",
        agent_id="a1",
        agent_type=AGENT,
        effort={"level": "low"},
    )
    proc = _launch_hook(json.dumps(entry).encode("utf-8"), tmp_dir)
    assert proc.returncode == 0, proc.stderr
    note = attribution.read_note("toolu_ida", directory=_notes_dir(tmp_dir))
    assert note is not None, "el hook no dejó nota legible"
    assert note.get("effort") == "low"
    assert note.get("agent_id") == "a1"
    assert note.get("agent_type") == AGENT
    assert note.get("transcript_path") == "C:/x/s1.jsonl"
    assert "session_id" not in note


@pytest.mark.parametrize(
    "case",
    ["valida", "stdin_roto", "id_malo"],
)
def test_the_hook_stays_silent_and_exits_with_0(tmp_path, case):
    """El hook no imprime nada y sale con 0 siempre; con un id que no casa, no deja nota.

    Control (b): mutante «el hook imprime la nota» → `proc.stdout` no vacío.
    """
    tmp_dir = _tmp_dir(tmp_path)
    if case == "valida":
        entry = json.dumps(_hook_input("toolu_calla", "C:/x/s.jsonl")).encode("utf-8")
    elif case == "stdin_roto":
        entry = b'{"tool_use_id": "toolu_roto", '
    else:
        entry = json.dumps(_hook_input("toolu_../../fuera", "C:/x/s.jsonl")).encode("utf-8")
    proc = _launch_hook(entry, tmp_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == b""
    notes_dir = _notes_dir(tmp_dir)
    written = sorted(p.name for p in notes_dir.iterdir()) if notes_dir.exists() else []
    if case == "valida":
        assert written == ["toolu_calla.json"], "guarda: el caso bueno sí escribe"
    else:
        assert written == []
    assert not any(tmp_path.rglob("fuera*")), "un id con `..` no puede escribir fuera"


def test_two_calls_do_not_overwrite_each_other(tmp_path):
    """Control (b), comprobado: con un nombre de fichero fijo la primera nota se pierde."""
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_a", tmp_path / "s.jsonl")
    _write_note(notes, "toolu_b", tmp_path / "s.jsonl")
    assert attribution.read_note("toolu_a", directory=notes) is not None
    assert attribution.read_note("toolu_b", directory=notes) is not None


def test_eight_hooks_at_once(tmp_path):
    """Guarda: ocho procesos del hook lanzados juntos dejan ocho notas legibles."""
    tmp_dir = _tmp_dir(tmp_path)
    ids = [f"toolu_par{i}" for i in range(8)]
    processes = [
        subprocess.Popen(
            [sys.executable, str(HOOK)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_hook_env(tmp_dir),
        )
        for _ in ids
    ]
    for process, tool_use_id in zip(processes, ids, strict=True):
        data = json.dumps(_hook_input(tool_use_id, "C:/x/s.jsonl", agent_id=tool_use_id))
        process.communicate(data.encode("utf-8"), timeout=30)
    assert all(p.returncode == 0 for p in processes)
    notes = _notes_dir(tmp_dir)
    assert sum(attribution.read_note(i, directory=notes) is not None for i in ids) == 8


def test_a_half_written_note_counts_as_no_note(tmp_path):
    """Control (b): mutante «`read_note` sin `try`» → la excepción escapa."""
    notes = tmp_path / "notas"
    notes.mkdir()
    (notes / "toolu_medias.json").write_text('{"tool_use_id": ', encoding="utf-8")
    escaped = False
    result = "sin leer"
    try:
        result = attribution.read_note("toolu_medias", directory=notes)
    except Exception:
        escaped = True
    assert not escaped
    assert result is None


def test_the_hook_prunes_old_notes(tmp_path):
    """Las notas de más de 10 min ya no cuentan, y el hook las borra al escribir otra."""
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_vieja", tmp_path / "s.jsonl")
    old = notes / "toolu_vieja.json"
    eleven_min_ago = time.time() - 11 * 60
    os.utime(old, (eleven_min_ago, eleven_min_ago))
    _write_note(notes, "toolu_nueva", tmp_path / "s.jsonl")
    assert not old.exists()
    assert (notes / "toolu_nueva.json").is_file()


# --- La resolución ------------------------------------------------------------------------------


def test_resolves_the_subagent_model(tmp_path):
    """REQ-003: la línea está en el transcript del SUBAGENTE, no en el que trae la nota.

    Control (b): mutante «buscar en el `transcript_path` de la nota» → `caller_model` None.
    """
    root = _projects(tmp_path)
    main_transcript = _write(
        root / "D--proyecto" / "s1.jsonl", [_tool_use_line("toolu_otro", OPUS)]
    )
    _write(
        root / "D--proyecto" / "s1" / "subagents" / "agent-a1.jsonl",
        [_tool_use_line("toolu_sub", OPUS)],
    )
    notes = tmp_path / "notas"
    _write_note(
        notes,
        "toolu_sub",
        main_transcript,
        agent_id="a1",
        agent_type=AGENT,
        effort={"level": "low"},
    )
    r = attribution.resolve_call("toolu_sub", notes=notes, projects=root)
    assert r.get("caller_model") == OPUS
    assert r.get("caller_kind") == "subagent"
    assert r.get("caller_agent_type") == AGENT
    assert r.get("caller_effort") == "low"
    assert r.get("caller_src") == "hook+transcript"


def test_the_main_agent_has_no_agent_type(tmp_path):
    """Control (b): mutante «copiar siempre `agent_type`» → aparece en el principal."""
    root = _projects(tmp_path)
    main_transcript = _write(
        root / "D--proyecto" / "s1.jsonl", [_tool_use_line("toolu_main", OPUS)]
    )
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_main", main_transcript, agent_type=AGENT, effort={"level": "high"})
    r = attribution.resolve_call("toolu_main", notes=notes, projects=root)
    assert r.get("caller_model") == OPUS, "guarda: la resolución llegó al transcript"
    assert r.get("caller_kind") == "main"
    assert "caller_agent_type" not in r


def test_a_path_outside_projects_is_not_opened(tmp_path):
    """Control (b): mutante «sin la validación de la ruta» → el fichero tiene la línea."""
    root = _projects(tmp_path)
    outside = _write(tmp_path / "fuera" / "s1.jsonl", [_tool_use_line("toolu_fuera", OPUS)])
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_fuera", outside, effort={"level": "high"})
    r = attribution.resolve_call("toolu_fuera", notes=notes, projects=root)
    assert r.get("caller_kind") == "main", "guarda: la nota sí se leyó"
    assert r.get("caller_model") is None
    assert r.get("caller_src") == "hook"


def test_the_race_leaves_caller_src_hook(tmp_path):
    """Guarda: hay nota pero la línea aún no está escrita (la carrera medida)."""
    root = _projects(tmp_path)
    main_transcript = _write(
        root / "D--proyecto" / "s1.jsonl", [_tool_use_line("toolu_otra", OPUS)]
    )
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_carrera", main_transcript, effort={"level": "high"})
    r = attribution.resolve_call("toolu_carrera", notes=notes, projects=root)
    assert r.get("caller_src") == "hook"
    assert "caller_model" not in r


def test_an_old_note_does_not_count(tmp_path):
    """Control (b): mutante «sin el filtro de edad» → la nota de hace 11 min cuenta."""
    root = _projects(tmp_path)
    main_transcript = _write(
        root / "D--proyecto" / "s1.jsonl", [_tool_use_line("toolu_vieja", OPUS)]
    )
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_vieja", main_transcript)
    now = time.time()
    assert "caller_kind" in attribution.resolve_call(
        "toolu_vieja", notes=notes, projects=root, now=now
    ), "guarda: la misma nota, fresca, sí cuenta"
    r = attribution.resolve_call("toolu_vieja", notes=notes, projects=root, now=now + 660)
    assert "caller_kind" not in r


def test_haiku_without_effort_is_na_and_opus_without_effort_is_missing(tmp_path):
    """Control (b): mutante «`n/a` para todo esfuerzo que falte» → Opus lleva `n/a`."""
    root = _projects(tmp_path)
    main_transcript = _write(
        root / "D--proyecto" / "s1.jsonl",
        [
            _tool_use_line("toolu_haiku", "claude-haiku-4-5-20251001"),
            _tool_use_line("toolu_opus", OPUS),
        ],
    )
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_haiku", main_transcript)
    _write_note(notes, "toolu_opus", main_transcript)
    r_haiku = attribution.resolve_call("toolu_haiku", notes=notes, projects=root)
    r_opus = attribution.resolve_call("toolu_opus", notes=notes, projects=root)
    assert r_haiku.get("caller_model") == "claude-haiku-4-5"
    assert r_haiku.get("caller_effort") == "n/a"
    assert r_opus.get("caller_model") == OPUS, "guarda: Opus también se resolvió"
    assert "caller_effort" not in r_opus


class _Counter:
    """Un flujo que suma en `spy.reads` los bytes que se leen de verdad."""

    def __init__(self, stream, spy) -> None:
        self._stream = stream
        self._spy = spy

    def seek(self, *a):
        return self._stream.seek(*a)

    def tell(self):
        return self._stream.tell()

    def read(self, *a):
        data = self._stream.read(*a)
        self._spy.reads += len(data)
        return data


class _ReadSpy:
    """Sustituye a `open` en `resolve_call(opener=...)`."""

    def __init__(self) -> None:
        self.reads = 0

    @contextlib.contextmanager
    def __call__(self, path, mode="r", *args, **kwargs):
        with open(path, mode, *args, **kwargs) as stream:
            yield _Counter(stream, self)


def test_does_not_read_more_than_256_kb(tmp_path):
    """Control (b): mutante «leer el fichero entero» → lee 50 MB."""
    root = _projects(tmp_path)
    main_transcript = root / "D--proyecto" / "s1.jsonl"
    padding = (json.dumps({"type": "user", "relleno": "x" * 1000}) + "\n").encode("utf-8")
    with main_transcript.open("wb") as stream:
        stream.write((_tool_use_line("toolu_lejos", OPUS) + "\n").encode("utf-8"))
        block = padding * 1024
        while stream.tell() < 50 * 1024 * 1024:
            stream.write(block)
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_lejos", main_transcript)
    spy = _ReadSpy()
    r = attribution.resolve_call("toolu_lejos", notes=notes, projects=root, opener=spy)
    assert spy.reads > 0, "guarda: se llegó a abrir el transcript"
    assert spy.reads <= 256 * 1024
    assert r.get("caller_model") is None


def test_the_50_ms_budget_cuts_off(tmp_path):
    """Control (b): mutante «ignorar el reloj» → la línea, que está en la cola, se encuentra."""
    root = _projects(tmp_path)
    main_transcript = _write(
        root / "D--proyecto" / "s1.jsonl",
        [json.dumps({"type": "user"})] * 5 + [_tool_use_line("toolu_lento", OPUS)],
    )
    notes = tmp_path / "notas"
    _write_note(notes, "toolu_lento", main_transcript)
    stopped = attribution.resolve_call("toolu_lento", notes=notes, projects=root, clock=lambda: 0.0)
    assert stopped.get("caller_model") == OPUS, "guarda: con tiempo de sobra se encuentra"

    instants = iter(i * 0.060 for i in range(1000))
    r = attribution.resolve_call(
        "toolu_lento", notes=notes, projects=root, clock=lambda: next(instants)
    )
    assert r.get("caller_model") is None


# --- `_log_event` -------------------------------------------------------------------------------


@pytest.fixture
def log_and_notes(tmp_path, monkeypatch):
    """El log de uso, el directorio de notas y la raíz de proyectos, todos en `tmp_path`."""
    log = tmp_path / "usage.jsonl"
    notes = tmp_path / "notas"
    root = _projects(tmp_path)
    monkeypatch.setattr(server, "_current_log_path", lambda: log)
    monkeypatch.setattr(hook_common, "call_notes_dir", lambda: notes)
    monkeypatch.setattr(attribution, "_projects_root", lambda: root)
    return log, notes, root


def _lines(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


def _minimal_log() -> None:
    server._log_event(
        tool="local_summarize",
        model="m",
        source="inline",
        chars_in=10,
        chars_out=5,
        latency_ms=1,
        ok=True,
    )


def _in_request(tool_use_id: str, function):
    """Corre `function` como si fuera dentro de una petición con ese `tool_use_id`."""
    t1 = clients._CURRENT_TOOL_USE_ID.set(tool_use_id)
    t2 = clients._REQUEST_MEMORY.set({})
    try:
        return function()
    finally:
        clients._REQUEST_MEMORY.reset(t2)
        clients._CURRENT_TOOL_USE_ID.reset(t1)


def test_log_event_writes_the_attribution_and_no_session_id(log_and_notes):
    """Control (c): en el corte, `current_tool_use_id()` devolvía `None` y no había campo."""
    log, notes, root = log_and_notes
    marker = "sesion-marcador-7f3a"
    main_transcript = _write(
        root / "D--proyecto" / f"{marker}.jsonl",
        [_tool_use_line("toolu_x", OPUS, session=marker)],
    )
    _write_note(notes, "toolu_x", main_transcript, session_id=marker, effort={"level": "high"})
    _in_request("toolu_x", _minimal_log)
    lines = _lines(log)
    assert len(lines) == 1
    line = lines[0]
    assert line.get("tool_use_id") == "toolu_x"
    assert line.get("caller_model") == OPUS
    assert line.get("caller_src") == "hook+transcript"
    assert "session_id" not in line
    assert marker not in json.dumps(line)


def test_without_tool_use_id_the_line_has_no_attribution_fields(log_and_notes):
    log, _notes, _root = log_and_notes
    _minimal_log()
    line = _lines(log)[0]
    assert "tool_use_id" not in line
    assert not [k for k in line if k.startswith("caller_")]


def test_a_broken_resolution_does_not_take_the_line_down(log_and_notes, monkeypatch):
    """Control (b), comprobado: sin su `try` propio, la `RuntimeError` sale de `_log_event`."""
    log, _notes, _root = log_and_notes

    def blows_up(*_a, **_k):
        raise RuntimeError("resolución rota")

    monkeypatch.setattr(attribution, "resolve_call", blows_up)
    escaped = False
    try:
        _in_request("toolu_roto", _minimal_log)
    except Exception:
        escaped = True
    assert not escaped
    lines = _lines(log)
    assert len(lines) == 1
    assert lines[0].get("tool_use_id") == "toolu_roto"


class _Spy:
    def __init__(self, original):
        self.original = original
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        return self.original(*a, **k)


async def _requests(ids: list[str], in_tool) -> list:
    """Arnés de `test_clients.py`: un servidor con el middleware y una llamada por id."""
    server = MCPServer("prueba", version="0.0.0", middleware=[clients.observe_client])
    seen: list = []

    @server.tool()
    def delegates() -> str:
        """Tool SÍNCRONA, como las de verdad."""
        seen.append(in_tool())
        return "ok"

    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):
        low = server._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=True)
            )
            info = Implementation(name="claude-code", version="1.0.0")
            async with ClientSession(cr, cw, client_info=info) as client:
                await client.initialize()
                for tool_use_id in ids:
                    await client.call_tool(
                        "delegates", {}, meta={clients.TOOL_USE_ID_KEY: tool_use_id}
                    )
            tg.cancel_scope.cancel()
    return seen


def test_resolution_happens_once_per_request(log_and_notes, monkeypatch):
    """Control (b): mutante «`current_call` sin memoria» → se resuelve dos veces."""
    log, notes, root = log_and_notes
    main_transcript = _write(root / "D--proyecto" / "s1.jsonl", [_tool_use_line("toolu_una", OPUS)])
    _write_note(notes, "toolu_una", main_transcript)
    spy = _Spy(attribution.resolve_call)
    monkeypatch.setattr(attribution, "resolve_call", spy)

    def in_tool():
        _minimal_log()
        return attribution.current_call()

    seen = anyio.run(_requests, ["toolu_una"], in_tool)
    assert seen and seen[0].get("caller_model") == OPUS, "guarda: se resolvió de verdad"
    assert _lines(log)[0].get("caller_model") == OPUS
    assert spy.calls == 1


def test_memory_does_not_cross_requests(log_and_notes):
    """Control (b): mutante «memoria en un dict del módulo» → en la segunda hay dos entradas."""
    _log, notes, root = log_and_notes
    main_transcript = _write(
        root / "D--proyecto" / "s1.jsonl",
        [_tool_use_line("toolu_p1", OPUS), _tool_use_line("toolu_p2", OPUS)],
    )
    _write_note(notes, "toolu_p1", main_transcript)
    _write_note(notes, "toolu_p2", main_transcript)

    def in_tool():
        attribution.current_call()
        memory = clients.request_memory()
        return sorted(memory) if memory is not None else None

    seen = anyio.run(_requests, ["toolu_p1", "toolu_p2"], in_tool)
    assert len(seen) == 2
    assert seen[0] == ["toolu_p1"], "guarda: la primera memorizó su resolución"
    second_memory = seen[1]
    assert len(second_memory) == 1
    assert second_memory == ["toolu_p2"]


# --- Relleno, exclusión y plazo ------------------------------------------------------------------


def test_two_lines_in_the_same_second_do_not_share_a_key():
    """REQ-005. Control (b): mutante «clave `ts|tool`» → las dos comparten clave."""
    ts = "2026-10-06T12:00:00+00:00"
    rows = [{"ts": ts, "tool": "local_summarize"}, {"ts": ts, "tool": "local_summarize"}]
    keys_before = attribution.file_keys(rows)
    assert len(set(keys_before)) == 2
    keys = attribution.file_keys([*rows, {"ts": ts, "tool": "local_summarize"}])
    assert keys[:2] == keys_before
    assert len(set(keys)) == 3
    with_id = attribution.file_keys([{"ts": ts, "tool": "x", "tool_use_id": "toolu_k"}])
    assert with_id == ["toolu_k"]


def test_the_backfill_only_improves(tmp_path):
    """REQ-005. Control (b): mutante «escribir siempre la nueva» → `ventana` pisa a `exacto`."""
    attribution.write_backfill(
        tmp_path,
        "202610",
        {"k1": {"match": "exact", "caller_model": OPUS}, "k2": {"match": "ambiguous"}},
    )
    attribution.write_backfill(
        tmp_path,
        "202610",
        {
            "k1": {"match": "window", "caller_model": "claude-haiku-4-5"},
            "k2": {"match": "window", "caller_model": OPUS},
        },
    )
    assert (tmp_path / "attribution-202610.json").is_file()
    entries = attribution.read_backfill(tmp_path, "202610")
    assert entries["k1"]["match"] == "exact"
    assert entries["k1"]["caller_model"] == OPUS
    assert entries["k2"]["match"] == "window", "guarda: un cruce mejor sí sustituye"
    attribution.write_backfill(tmp_path, "202610", {"k3": {"match": "no_match"}})
    assert set(attribution.read_backfill(tmp_path, "202610")) == {"k1", "k2", "k3"}


def test_excluded():
    """REQ-007. Control (b): mutante «sin la rama de `banco`» → la de banco cuenta."""
    assert attribution.exclusion_reason({"client": "codex-mcp-client"}) == "no es Claude"
    assert attribution.exclusion_reason({"client": "mcp"}) == "pruebas"
    f = {"client": "claude-code"}
    assert attribution.exclusion_reason(f, {"bench": True}) == "pruebas"
    assert attribution.exclusion_reason(f, {"bench": False}) is None
    assert attribution.exclusion_reason(f) is None


def test_deletion_deadline(tmp_path):
    """Enmienda 1. Control (b): mutante «devolver 30 siempre» → no lee los 90."""
    d = tmp_path / "claude"
    d.mkdir()
    assert attribution.cleanup_period_days(d) == 30
    (d / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 90}), encoding="utf-8")
    assert attribution.cleanup_period_days(d) == 90
    for bad in ("abc", 0, -5, True, 1.5):
        (d / "settings.json").write_text(json.dumps({"cleanupPeriodDays": bad}), encoding="utf-8")
        assert attribution.cleanup_period_days(d) == 30, bad
    (d / "settings.json").write_text("{roto", encoding="utf-8")
    assert attribution.cleanup_period_days(d) == 30


# --- Una sola regla de «es una prueba» (test-windows-out-of-metrics, REQ-004) -------------------


def test_test_reason_recognizes_the_three_test_classes():
    """Control: mutante «`test_reason` ignora `test_window`» → falla el caso de la ventana."""
    assert attribution.test_reason({"client": "mcp"}) == "pruebas"
    assert attribution.test_reason({"client": "claude-code"}, {"bench": True}) == "pruebas"
    # El panel la llama con un solo argumento sobre la fila ya fundida, que trae `bench`.
    assert attribution.test_reason({"client": "claude-code", "bench": True}) == "pruebas"
    assert attribution.test_reason({"client": "claude-code", "test_window": "w-1"}) == "pruebas"
    assert attribution.test_reason({"client": "codex-mcp-client"}) is None
    assert attribution.test_reason({"client": "claude-code"}) is None


def test_excluded_adds_up_non_claude_and_tests():
    assert attribution.exclusion_reason({"client": "codex-mcp-client"}) == "no es Claude"
    assert (
        attribution.exclusion_reason({"client": "claude-code", "test_window": "w-1"}) == "pruebas"
    )
    assert attribution.exclusion_reason({"client": "claude-code"}) is None


# --- Caché del relleno: nombre nuevo, lectura dual y siembra una sola vez (A5a, REQ-005/006) ----


def _old_backfill(log_dir: Path, month: str, entries: dict) -> Path:
    """Un `atribucion-AAAAMM.json` como lo dejaba una versión anterior: claves y valores viejos."""
    old = log_dir / f"atribucion-{month}.json"
    old.write_text(
        json.dumps({"version": 1, "entradas": entries}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return old


OLD_ENTRIES = {
    "k1": {"cruce": "exacto", "banco": False, "n": 3, "caducidades": 1, "caller_model": OPUS},
    "k2": {"cruce": "ventana+path", "banco": True, "n": 0, "caducidades": 0},
    "k3": {"cruce": "ambiguo", "banco": False},
    "k4": {"cruce": "sin_cruce", "banco": False},
}


def test_the_old_backfill_is_read_translated_if_there_is_no_new_one(tmp_path):
    """REQ-006. Control: mutante «`read_backfill` solo lee `attribution-*`» → `{}`."""
    _old_backfill(tmp_path, "202609", OLD_ENTRIES)
    read_back = attribution.read_backfill(tmp_path, "202609")
    assert read_back["k1"] == {
        "match": "exact",
        "bench": False,
        "n": 3,
        "expiries": 1,
        "caller_model": OPUS,
    }
    assert [read_back[k]["match"] for k in ("k2", "k3", "k4")] == [
        "window+path",
        "ambiguous",
        "no_match",
    ]
    assert not (tmp_path / "attribution-202609.json").exists(), "leer no escribe nada"


def test_seeding_happens_only_once(tmp_path):
    """REQ-006 (siembra). Control: mutante «sembrar desde el viejo en cada escritura» → la entrada
    que una versión anterior añade al viejo DESPUÉS de sembrar entra en la segunda corrida."""
    old = _old_backfill(tmp_path, "202609", OLD_ENTRIES)
    first = attribution.write_backfill(tmp_path, "202609", {"k9": {"match": "exact"}})
    assert set(first) == {"k1", "k2", "k3", "k4", "k9"}, "guarda: la primera corrida siembra"
    # Una 0.34.0 rezagada (la Mac) sigue escribiendo el fichero viejo.
    _old_backfill(tmp_path, "202609", {**OLD_ENTRIES, "k5": {"cruce": "exacto"}})
    assert old.is_file()
    second = attribution.write_backfill(tmp_path, "202609", {})
    assert len(second) == len(first)
    assert second == first
    assert set(attribution.read_backfill(tmp_path, "202609")) == set(first)


def test_an_old_exact_match_is_not_lost_to_a_new_window(tmp_path):
    """REQ-006 (mejor cruce al sembrar). Control: mutante «fundir sin la regla de mejor cruce»
    (la entrada nueva pisa siempre) → `k1` pasa a `window` y pierde su modelo."""
    _old_backfill(tmp_path, "202609", OLD_ENTRIES)
    merged = attribution.write_backfill(
        tmp_path,
        "202609",
        {
            "k1": {"match": "window", "caller_model": "claude-haiku-4-5"},
            "k3": {"match": "window", "caller_model": OPUS},
        },
    )
    assert merged["k1"]["match"] == "exact"
    assert merged["k1"]["caller_model"] == OPUS
    assert merged["k3"]["match"] == "window", "guarda: un cruce mejor sí sustituye"


def test_seeding_leaves_the_old_file_intact_byte_for_byte(tmp_path):
    """REQ-006 (intactos). Control: mutante «reescribir el viejo en el formato nuevo al sembrar» →
    cambian los bytes."""
    old = _old_backfill(tmp_path, "202609", OLD_ENTRIES)
    before = old.read_bytes()
    attribution.write_backfill(tmp_path, "202609", {"k9": {"match": "exact"}})
    attribution.write_backfill(tmp_path, "202609", {"k1": {"match": "window"}})
    assert (tmp_path / "attribution-202609.json").is_file(), "guarda: se sembró el nuevo"
    assert old.read_bytes() == before


def test_the_backfill_is_written_only_in_the_new_format(tmp_path):
    """REQ-005. Control: mutante «`write_backfill` no traduce lo que recibe» → `cruce` en disco."""
    _old_backfill(tmp_path, "202609", OLD_ENTRIES)
    attribution.write_backfill(tmp_path, "202609", {"k8": {"cruce": "ventana", "banco": True}})
    data = json.loads((tmp_path / "attribution-202609.json").read_text(encoding="utf-8"))
    assert set(data) == {"version", "entries"}
    text = json.dumps(data, ensure_ascii=False)
    for old in ('"cruce"', '"banco"', '"caducidades"', '"exacto"', '"ventana', '"sin_cruce"'):
        assert old not in text, old
    assert data["entries"]["k8"] == {"match": "window", "bench": True}


def test_with_both_files_the_new_one_wins(tmp_path):
    """REQ-006. Control: mutante «leer primero el viejo» → `k1` vuelve a ser el del viejo."""
    _old_backfill(tmp_path, "202609", OLD_ENTRIES)
    (tmp_path / "attribution-202609.json").write_text(
        json.dumps({"version": 1, "entries": {"k1": {"match": "window"}}}), encoding="utf-8"
    )
    assert attribution.read_backfill(tmp_path, "202609") == {"k1": {"match": "window"}}
