"""Lectura de transcripts para `recalcular-coste`: cruce, `N`, caducidades y `cost-state` (T5).

Todo es SINTÉTICO y vive en `tmp_path`: ningún id de sesión, ruta ni texto real. Los
constructores de este fichero (`request_entry`, `result_entry`, `write_jsonl`…) los reutilizan
`test_quota.py` y `test_recompute.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_delegate import attribution, recompute, transcripts

BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SESSION = "sesion-sintetica-0001"
OPUS = "claude-opus-5-5"
PREFIX = transcripts.TOOL_PREFIX


# --- Constructores ------------------------------------------------------------------------------


def ts(s: float) -> str:
    """Hora de un transcript (con milisegundos y `Z`, como Claude Code)."""
    return (BASE + timedelta(seconds=s)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ts_log(s: float) -> str:
    """Hora de una línea del log (en segundos, como `server._log_event`)."""
    return (BASE + timedelta(seconds=s)).isoformat(timespec="seconds")


def request_entry(
    s: float,
    mid: str,
    *,
    model: str = OPUS,
    session: str = SESSION,
    tool_use: tuple[str, str, str | None] | None = None,
    effort: str | None = "high",
    usage: dict | None = None,
) -> dict:
    """Una línea `assistant`; con `tool_use=(id, tool, path)` lleva la llamada a local-delegate."""
    if tool_use:
        tid, tool, path = tool_use
        content = [
            {
                "type": "tool_use",
                "id": tid,
                "name": PREFIX + tool,
                "input": {"path": path} if path else {},
            }
        ]
    else:
        content = [{"type": "text", "text": "respuesta sintética"}]
    line = {
        "type": "assistant",
        "timestamp": ts(s),
        "sessionId": session,
        "requestId": f"req_{mid}",
        "message": {"id": mid, "model": model, "content": content, "usage": usage or {}},
    }
    if effort is not None:
        line["effort"] = effort
    return line


def result_entry(s: float, tid: str, text: str = "hecho", *, session: str = SESSION) -> dict:
    return {
        "type": "user",
        "timestamp": ts(s),
        "sessionId": session,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tid, "content": text}],
        },
    }


def synthetic(s: float, mid: str, *, quota: object = None, session: str = SESSION) -> dict:
    line = {
        "type": "assistant",
        "timestamp": ts(s),
        "sessionId": session,
        "message": {"id": mid, "model": "<synthetic>", "content": []},
    }
    if quota is not None:
        line["quotaLimits"] = quota
    return line


def compaction(s: float) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "timestamp": ts(s)}


def write_jsonl(path: Path, lines: list) -> Path:
    """Un JSONL; una cadena se escribe tal cual (para las líneas rotas)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines)
    path.write_text(text, encoding="utf-8")
    return path


def main_transcript(claude: Path, *, session: str = SESSION, project: str = "D--Proyecto") -> Path:
    return claude / "projects" / project / f"{session}.jsonl"


def subagent(
    claude: Path, agent: str, *, session: str = SESSION, project: str = "D--Proyecto"
) -> Path:
    return claude / "projects" / project / session / "subagents" / f"agent-{agent}.jsonl"


def log_line(s: float, tool: str = "local_summarize", **extra) -> dict:
    row = {
        "ts": ts_log(s),
        "tool": tool,
        "client": "claude-code",
        "ok": True,
        "source": "path",
        "chars_in": 4000,
        "chars_out": 400,
    }
    row.update(extra)
    return row


def write_log(log_dir: Path, rows: list[dict], month: str = "202610") -> Path:
    return write_jsonl(log_dir / f"usage-{month}.jsonl", rows)


def match_all(claude: Path, rows: list[dict]) -> list[dict | None]:
    """Las entradas de `casar` en el orden de las filas (`None` si una fila no tiene)."""
    index = transcripts.read(claude / "projects")
    keys = attribution.file_keys(rows)
    entries = transcripts.match_lines(zip(keys, rows), index, since=BASE - timedelta(days=1))
    return [entries.get(c) for c in keys]


# --- N y caducidades (REQ-043) --------------------------------------------------------------


def test_known_n_and_expiries(tmp_path):
    """Subagente (TTL 300 s). Escrito a mano: después de `t0` = 1 s cuentan m1 (una vez, aunque
    aparece en dos líneas), m2 y m3; la `<synthetic>` no cuenta y m4 cae tras el
    `compact_boundary`. Huecos: 1→10 (9 s), 10→311 (301 s, caducidad), 311→610 (299 s, no).
    N = 3, caducidades = 1."""
    claude = tmp_path / "claude"
    write_jsonl(
        subagent(claude, "a1"),
        [
            request_entry(0, "m0", tool_use=("toolu_n", "local_summarize", "docs/a.md")),
            result_entry(1, "toolu_n"),
            request_entry(10, "m1"),
            request_entry(11, "m1"),  # el mismo message.id en otra línea (otro bloque de contenido)
            synthetic(20, "s1"),
            request_entry(311, "m2"),
            request_entry(610, "m3"),
            compaction(700),
            request_entry(800, "m4"),
        ],
    )
    index = transcripts.read(claude / "projects")
    d = index.delegations["toolu_n"]
    assert d.kind == "subagent"
    n, expiries = transcripts.n_and_expiries(index, d)
    KNOWN_N = 3
    assert n == KNOWN_N
    assert expiries == 1


def test_the_ttl_depends_on_the_thread(tmp_path):
    """En el principal el TTL es de 3 600 s: un hueco de 3 599 s no es caducidad."""
    claude = tmp_path / "claude"
    write_jsonl(
        main_transcript(claude),
        [
            request_entry(0, "m0", tool_use=("toolu_t", "local_summarize", "docs/a.md")),
            result_entry(1, "toolu_t"),
            request_entry(3600, "m1"),
        ],
    )
    index = transcripts.read(claude / "projects")
    d = index.delegations["toolu_t"]
    assert d.kind == "main"
    n, expiries = transcripts.n_and_expiries(index, d)
    assert n == 1
    assert expiries == 0


def test_even_percentile():
    assert transcripts.median([1, 2, 3, 4]) == 2.5
    assert transcripts.median([3, 1, 2]) == 2
    assert transcripts.percentile([10, 20, 30, 40, 50], 0.25) == 20
    assert transcripts.median([]) is None


# --- Cruce (REQ-004) ------------------------------------------------------------------------


def _two_subagents(claude: Path, path_a: str, path_b: str) -> None:
    """Dos subagentes llaman a la vez a `local_summarize`: A deja 2 peticiones después de su
    resultado y B, 5; así la `n` de la entrada dice con cuál casó cada línea."""
    write_jsonl(
        subagent(claude, "A"),
        [
            request_entry(0, "a0", tool_use=("toolu_a", "local_summarize", path_a)),
            result_entry(5, "toolu_a"),
            request_entry(6, "a1"),
            request_entry(7, "a2"),
        ],
    )
    write_jsonl(
        subagent(claude, "B"),
        [
            request_entry(1, "b0", tool_use=("toolu_b", "local_summarize", path_b)),
            result_entry(6, "toolu_b"),
        ]
        + [request_entry(7 + i, f"b{i + 1}") for i in range(5)],
    )


def test_exact_match_window_and_path(tmp_path):
    claude = tmp_path / "claude"
    _two_subagents(claude, "docs/a.md", "docs/b.md")
    write_jsonl(
        main_transcript(claude),
        [
            request_entry(100, "c0", tool_use=("toolu_c", "local_extract", None)),
            result_entry(103, "toolu_c"),
        ],
    )
    rows = [
        log_line(4, path="docs/a.md"),
        log_line(4, path="docs/b.md"),
        log_line(4, tool_use_id="toolu_a"),
        log_line(102, tool="local_extract"),
    ]
    e = match_all(claude, rows)
    assert [x["match"] for x in e] == ["window+path", "window+path", "exact", "window"]
    assert [e[0]["n"], e[1]["n"], e[2]["n"]] == [2, 5, 2]
    assert e[0]["caller_model"] == OPUS
    assert e[0]["caller_kind"] == "subagent"
    assert e[0]["caller_effort"] == "high"
    assert e[3]["caller_kind"] == "main"

    # Con los dos `path` iguales no hay desempate posible: las dos, ambiguas.
    other = tmp_path / "otro"
    _two_subagents(other, "docs/a.md", "docs/a.md")
    matches = [x["match"] for x in match_all(other, rows[:2])]
    assert matches == ["ambiguous", "ambiguous"]


def test_the_backfill_uses_the_period_read(tmp_path):
    """Con `cleanupPeriodDays: 90`, una línea de hace 45 días con su transcript se rellena."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 90}), encoding="utf-8")
    write_jsonl(
        main_transcript(claude),
        [
            request_entry(0, "m0", tool_use=("toolu_p", "local_summarize", "docs/a.md")),
            result_entry(2, "toolu_p"),
        ],
    )
    write_log(log, [log_line(1, tool_use_id="toolu_p")])
    recompute.run(claude, log, now=BASE + timedelta(days=45))
    entries = attribution.read_backfill(log, "202610")
    key = "toolu_p"
    assert key in entries
    assert entries[key]["match"] == "exact"


def test_no_match_and_bench(tmp_path):
    claude = tmp_path / "claude"
    write_jsonl(
        main_transcript(claude, project="C--Users-x-AppData-Local-Temp-banco"),
        [
            request_entry(0, "m0", tool_use=("toolu_banco", "local_summarize", "x.md")),
            result_entry(1, "toolu_banco"),
        ],
    )
    rows = [
        log_line(1, tool_use_id="toolu_banco"),
        log_line(1, tool_use_id="toolu_no_esta"),
        log_line(5000, tool="local_translate"),
    ]
    e_bench, e_id, e = match_all(claude, rows)
    assert e_bench["bench"] is True
    assert e_bench["match"] == "exact"
    assert e_id["match"] == "no_match"
    assert e["match"] == "no_match"


# --- cost-state (REQ-014) -------------------------------------------------------------------


def _cost_state(cost: float) -> dict:
    usage = {
        "inputTokens": 10,
        "cacheCreationInputTokens": 0,
        "cacheReadInputTokens": 0,
        "outputTokens": 0,
        "webSearchRequests": 0,
        "costUSD": cost,
    }
    return {
        "type": "cost-state",
        "sessionId": SESSION,
        "startTime": ts(0),
        "modelUsage": {OPUS: usage},
    }


def test_cost_state_takes_the_last_by_position(tmp_path):
    claude = tmp_path / "claude"
    FIRST, LAST = 1.0, 2.5
    write_jsonl(main_transcript(claude), [_cost_state(FIRST), _cost_state(LAST)])
    rows = transcripts.cost_state(transcripts.read(claude / "projects"))
    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == OPUS
    assert row["costUSD"] == LAST
    assert SESSION not in json.dumps(rows)
