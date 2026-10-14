"""Densidad de Claude por evento, fusión del relleno y tramos (coste-api-y-cuota, T4).

Los campos nuevos se leen con `.get(...)` donde el código de antes no los tenía: contra ese código
el test tiene que fallar por su assert, no por un `KeyError`.
"""

from __future__ import annotations

import inspect
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import backend_mock
import httpx2
import pytest

from local_delegate import attribution, config, cost, legacy_names, server
from local_delegate.web import metrics


@pytest.fixture(autouse=True)
def _declared_fallback(monkeypatch):
    """Sin variable de respaldo: el declarado (Opus 5.5 en subagente) en todos los tests."""
    monkeypatch.setattr(config, "COST_FALLBACK", "")


def _row(**kw) -> dict:
    base = {
        "ts": "2026-10-06T10:00:00+00:00",
        "tool": "local_summarize",
        "model": "m",
        "source": "path",
        "chars_in": 4000,
        "chars_out": 400,
        "ok": True,
    }
    base.update(kw)
    return base


def _extract_js_function(source: str, header: str) -> str:
    i = source.index(header)
    depth, j = 0, i
    while True:
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i : j + 1]
        j += 1


def _acct_in_js(tmp_path, cases: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    entry = tmp_path / "cases.json"
    entry.write_text(json.dumps(cases), encoding="utf-8")
    program = tmp_path / "acct.mjs"
    program.write_text(
        "import {readFileSync} from 'node:fs';\n"
        "const CPT = 4;\n"
        "const tok = c => Math.floor(c/CPT);\n"
        f"const LEGACY_VALUES = {json.dumps(legacy_names.PANEL_VALUE_ALIASES)};\n"
        f"{_extract_js_function(metrics.HTML, 'function legacyValue(')}\n"
        f"{_extract_js_function(metrics.HTML, 'function claudeTokens(')}\n"
        f"{_extract_js_function(metrics.HTML, 'function acct(e){')}\n"
        f"const casos = JSON.parse(readFileSync({json.dumps(str(entry))}, 'utf-8'));\n"
        "console.log(JSON.stringify(casos.map(acct)));\n",
        encoding="utf-8",
    )
    output = subprocess.run(
        [node, str(program)], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(output.stdout)


# --- Las dos copias solo dividen -----------------------------------------------------------------


def test_without_density_both_give_zero(tmp_path):
    """Una fila SIN fundir no trae `density`: Python y JS dan 0, no una cifra con un respaldo
    inventado (REQ-033). Una fusión olvidada se ve."""
    row = _row(path="C:/docs/guia.md")
    assert "density" not in row  # guarda: de verdad está sin fundir
    assert server.claude_tokens(4000, kind="text", event=row) == 0
    assert server.claude_tokens(400, kind="returned", event=row) == 0
    (js,) = _acct_in_js(tmp_path, [row])
    assert (js.get("saved"), js.get("returned")) == (0, 0)
    # Control de que la misma fila, fundida, sí da tokens en las dos copias.
    (merged,) = cost.merge([row], log_dir=tmp_path)
    assert server.claude_tokens(4000, kind="text", event=merged) == 2000  # 4000 × 100 // 200


def test_the_same_py_with_haiku_gives_fewer_tokens():
    """Escenario de la spec: un `.py` por `path`. Opus 5.5 usa `c` = 2,03 (familia nueva, formato
    `Read`, `medida`); Haiku, `c` = 3,12 (familia anterior, `read_format` sin medir → respaldo (2),
    `unnumbered`). El valor de Haiku coincide con el del respaldo (3) porque `code` es la mayor
    `c` de su familia: lo que discrimina es el ORIGEN."""
    base = _row(path="C:/src/app.py")
    d_opus = cost.resolve_density(dict(base, caller_model="claude-opus-5-5"))
    d_haiku = cost.resolve_density(dict(base, caller_model="claude-haiku-4-5"))
    assert d_opus["text"] == [203, "measured"]
    assert d_haiku["text"] == [312, "unnumbered"]
    t_opus = server.claude_tokens(4000, kind="text", event={"density": d_opus})
    t_haiku = server.claude_tokens(4000, kind="text", event={"density": d_haiku})
    assert (t_opus, t_haiku) == (1970, 1282)  # 4000 × 100 // 203 y 4000 × 100 // 312
    assert t_haiku < t_opus


def test_the_tool_wins_over_the_extension():
    """REQ-032: primero la tool, después la extensión."""
    content_class = cost.content_class({"tool": "local_lint_summary", "path": "C:/src/app.py"})
    assert content_class == "log"
    assert cost.content_class({"tool": "local_commit_msg", "path": "x.md"}) == "diff"
    assert cost.content_class({"tool": "local_summarize", "path": "C:/src/app.py"}) == "code"
    assert cost.content_class({"tool": "local_summarize", "path": "/a/b.LOCK"}) == "structured"
    assert cost.content_class({"tool": "local_summarize", "path": "C:\\a.b\\volcado"}) == "other"


def test_the_returned_and_output_columns():
    """REQ-031: lo devuelto y lo escrito no van numerados; su clase sale de la tool."""
    d = cost.resolve_density(_row(tool="local_extract", path="C:/a.md"))
    assert d["text"] == [200, "measured"]  # prosa, formato `Read`
    assert d["returned"] == [188, "measured"]  # estructurado, sin numerar
    assert d["output"] == [223, "measured"]  # prosa, sin numerar
    b = cost.resolve_density(_row(tool="local_boilerplate", source="inline"))
    assert b["text"] == [241, "conservative"]  # inline sin path: clase `other`, sin numerar → (3)
    assert (b["returned"], b["output"]) == ([241, "measured"], [241, "measured"])  # codigo


def test_fallback_by_variable(monkeypatch):
    """REQ-008: la variable manda sobre el declarado; con solo `modelo`, el hilo es `subagent`;
    un valor inválido usa el declarado y lo dice."""
    monkeypatch.setattr(config, "COST_FALLBACK", "claude-haiku-4-5")
    r = cost.fallback()
    assert r["family"] == "previous"
    assert (r["model"], r["thread"], r.get("fallback_invalid")) == (
        "claude-haiku-4-5",
        "subagent",
        False,
    )

    monkeypatch.setattr(config, "COST_FALLBACK", "claude-opus-5:main")
    r = cost.fallback()
    assert (r["model"], r["thread"], r["family"]) == ("claude-opus-5", "main", "new")

    monkeypatch.setattr(config, "COST_FALLBACK", "xyz")
    r = cost.fallback()
    assert r.get("fallback_invalid") is True
    assert (r["model"], r["thread"]) == ("claude-opus-5-5", "subagent")

    # Y la fila fundida lo dice.
    (row,) = cost.merge([_row()], log_dir=config.LOG_DIR)
    assert row.get("fallback_invalid") is True
    assert (row["caller_model"], row["caller_kind"]) == ("claude-opus-5-5", "subagent")


def test_the_fallback_variable_is_read_through_the_registered_door():
    assert "LOCAL_DELEGATE_COST_FALLBACK" in config.ENVIRONMENT_VARIABLES
    assert "LOCAL_DELEGATE_COSTE_RESPALDO" in config.ENVIRONMENT_VARIABLES  # alias (REQ-002)


def test_family_marks():
    """REQ-030/031: un modelo de la familia que no está entre los medidos lleva
    `family_density`; uno fuera de la tabla, `assumed_family` y la familia nueva."""
    assert cost.family_and_marks("claude-opus-5-5") == ("new", [])
    assert cost.family_and_marks("claude-sonnet-4-6") == ("previous", ["family_density"])
    assert cost.family_and_marks("claude-opus-4-8") == ("new", ["family_density"])
    assert cost.family_and_marks("claude-xyz-1") == ("new", ["assumed_family"])


# --- Imágenes fuera del neto (REQ-038) ----------------------------------------------------------


def test_an_image_does_not_subtract_from_the_net(tmp_path):
    """Escenario de la spec, con el evento de imagen del hermano: los campos del contrato no
    cambian, pero `saved = returned = net = 0` en las dos copias."""
    event = {
        "tool": "local_describe_image",
        "source": "path",
        "chars_in": 250000,
        "chars_out": 800,
        "ok": True,
        "tokens_in": 1200,
        "tokens_out": 200,
    }
    (row,) = cost.merge([event], log_dir=tmp_path)
    a = metrics._accounting(row)
    assert a["saved"] == 0
    assert (a.get("returned"), a.get("net")) == (0, 0)
    assert a.get("bytes_saved_image") == 250000
    assert a.get("chars_returned") == 800
    assert row["density"] == {"text": None, "returned": None, "output": None}
    (js,) = _acct_in_js(tmp_path, [row])
    assert (js.get("saved"), js.get("returned"), js.get("net")) == (0, 0, 0)
    assert (js.get("bytesSavedImage"), js.get("charsReturned")) == (250000, 800)


# --- Fusión (REQ-006) ----------------------------------------------------------------------------

MODEL_FROM_LINE = "claude-opus-5"
MODEL_FROM_BACKFILL = "claude-haiku-4-5"


def test_the_merge_respects_the_order(tmp_path):
    """Por campo: la línea, luego el relleno, luego el respaldo."""
    lines = [
        _row(tool_use_id="toolu_a", caller_model=MODEL_FROM_LINE, caller_kind="main"),
        _row(tool_use_id="toolu_b", caller_kind="main", caller_src="hook"),
        _row(ts="2026-10-06T10:00:05+00:00"),
    ]
    attribution.write_backfill(
        tmp_path,
        "202610",
        {
            "toolu_a": {
                "caller_model": MODEL_FROM_BACKFILL,
                "caller_kind": "subagent",
                "match": "exact",
            },
            "toolu_b": {
                "caller_model": MODEL_FROM_BACKFILL,
                "caller_kind": "subagent",
                "caller_effort": "n/a",
                "n": 12,
                "expiries": 1,
                "match": "exact",
                "bench": False,
            },
        },
    )
    a, b, c = cost.merge(lines, log_dir=tmp_path)

    assert a["caller_model"] == MODEL_FROM_LINE
    assert (a["caller_kind"], a.get("caller_origin")) == ("main", "line")

    assert (b["caller_model"], b.get("caller_origin")) == (MODEL_FROM_BACKFILL, "backfill")
    assert b["caller_kind"] == "main", "por campo: el hilo de la línea manda sobre el del relleno"
    assert (b.get("n"), b.get("expiries"), b.get("caller_effort")) == (12, 1, "n/a")
    assert b.get("family") == "previous"

    assert (c["caller_model"], c["caller_kind"], c.get("caller_origin")) == (
        "claude-opus-5-5",
        "subagent",
        "fallback",
    )
    assert "fallback_invalid" not in c
    # La entrada del relleno se busca con la clave del fichero entero.
    assert attribution.file_keys(lines)[2] == "2026-10-06T10:00:05+00:00|local_summarize|0"


def test_the_merge_does_not_touch_the_cache(tmp_path, monkeypatch):
    """`fundir` copia: dos `_load` seguidos no dejan claves nuevas en las filas cacheadas."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    path = tmp_path / "usage-202610.jsonl"
    path.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    metrics._FILE_CACHE.clear()
    since = datetime(2026, 10, 1, tzinfo=UTC)
    until = datetime(2026, 11, 1, tzinfo=UTC)
    rows, _ = metrics._load(since, until)
    assert rows[0].get("density") is not None  # guarda: lo que sale de `_load` va fundido
    metrics._load(since, until)
    assert "density" not in metrics._read_file_cached(path)[0]
    assert "caller_origin" not in metrics._read_file_cached(path)[0]


# --- Tramos de la barra (REQ-007) ----------------------------------------------------------------


def test_brackets(tmp_path):
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

    def ago(days: int) -> str:
        return (now - timedelta(days=days)).isoformat(timespec="seconds")

    def merged(row: dict, entry: dict | None = None) -> dict:
        return cost.merge_row(row, entry)

    t = cost.segment
    # Excluidos: clientes declarados y bancos, aunque traigan modelo.
    assert t(merged(_row(client="codex-mcp-client")), now=now, cleanup_days=30) == "excluded"
    assert t(merged(_row(client="mcp")), now=now, cleanup_days=30) == "excluded"
    bench = merged(_row(client="claude-code"), {"caller_model": MODEL_FROM_BACKFILL, "bench": True})
    assert t(bench, now=now, cleanup_days=30) == "excluded"
    # Al momento y por relleno.
    line = merged(_row(caller_model=MODEL_FROM_LINE, ts=ago(100)))
    assert t(line, now=now, cleanup_days=30) == "at_call"
    padding = merged(_row(ts=ago(100)), {"caller_model": MODEL_FROM_BACKFILL, "match": "exact"})
    assert t(padding, now=now, cleanup_days=30) == "backfilled"
    # Sin modelo: pendiente mientras el transcript puede existir; supuesto después.
    f29, f31, f60 = (merged(_row(ts=ago(d))) for d in (29, 31, 60))
    assert t(f29, now=now, cleanup_days=30) == "pending"
    assert t(f31, now=now, cleanup_days=30) == "assumed"
    assert t(f60, now=now, cleanup_days=90) == "pending"
    assert t(f60, now=now, cleanup_days=30) == "assumed"
    # Un cruce `ambiguo` o `sin_cruce` ya no se arregla: supuesto aunque sea reciente.
    f = merged(_row(ts=ago(1)), {"match": "ambiguous"})
    assert t(f, now=now, cleanup_days=30) == "assumed"
    f = merged(_row(ts=ago(1)), {"match": "no_match"})
    assert t(f, now=now, cleanup_days=30) == "assumed"


# --- Ningún `CHARS_PER_TOKEN` para tokens de Claude (REQ-034) ------------------------------------


def _approx_tokens_block() -> str:
    source = inspect.getsource(server.local_extract)
    i = source.index('meta["leido_server_side"]')
    return source[i : source.index("}", i) + 1]


def test_no_chars_per_token_in_the_conversion():
    sources = {
        "claude_tokens": inspect.getsource(server.claude_tokens),
        "_savings_feedback": inspect.getsource(server._savings_feedback),
        "_write_target": inspect.getsource(server._write_target),
        "tokens_aprox": _approx_tokens_block(),
    }
    assert "tokens_aprox" in sources["tokens_aprox"]  # guarda: el recorte encontró el bloque
    for name, source in sources.items():
        assert "CHARS_PER_TOKEN" not in source, name


# --- Los mensajes a Claude (REQ-035) -------------------------------------------------------------


def _backend(monkeypatch, tmp_path, *, prompt_tokens: int, text: str = "resumen") -> None:
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 5},
            },
        )
    )


@backend_mock.mock
def test_the_tagline_uses_claude_tokens(monkeypatch, tmp_path):
    """`local_summarize` con `path` a un `.md` de 4000 caracteres: prosa, formato `Read`, familia
    nueva del respaldo → 4000 × 100 // 200 = 2000 tokens de Claude, no los 9999 del modelo local."""
    _backend(monkeypatch, tmp_path, prompt_tokens=9999)
    doc = tmp_path / "notes.md"
    doc.write_text("palabra " * 500, encoding="utf-8")
    assert len(doc.read_text(encoding="utf-8")) == 4000  # guarda del tamaño
    text = server.local_summarize(path=str(doc))
    assert "≈ 2,000 tokens de Claude" in text
    assert "9,999" not in text
    assert text.rstrip().endswith("que no entraron a tu contexto)")


@backend_mock.mock
def test_the_output_receipt_uses_claude_tokens(monkeypatch, tmp_path):
    """Salida a fichero de `local_boilerplate`: clase `code`, sin numerar → c = 2,41."""
    code = "x = 1\n" * 100  # 600 caracteres
    _backend(monkeypatch, tmp_path, prompt_tokens=10, text=code.strip())
    dest = tmp_path / "output.py"
    receipt = server.local_boilerplate(spec="un módulo", language="python", target=str(dest))
    assert len(dest.read_text(encoding="utf-8")) == 600  # guarda del tamaño escrito
    assert (
        "600 chars (≈248 tokens de Claude que no entraron a tu contexto)" in receipt
    )  # 60000 // 241


@backend_mock.mock
def test_extract_approx_tokens_are_claudes(monkeypatch, tmp_path):
    _backend(monkeypatch, tmp_path, prompt_tokens=9999, text='{"titulo": "x"}')
    doc = tmp_path / "data.json"
    doc.write_text('{"a": "' + "b" * 3991 + '"}', encoding="utf-8")
    data = server.local_extract(fields=["titulo"], path=str(doc))
    read_back = data.get("_local_delegate", {}).get("leido_server_side", {})
    assert read_back.get("chars") == 4000
    # estructurado, formato `Read` sin medir → respaldo (2), sin numerar: 4000 × 100 // 188
    assert read_back.get("tokens_aprox") == 2127


@backend_mock.mock
def test_the_tagline_uses_the_note_model_if_already_present(monkeypatch, tmp_path):
    """REQ-035: con la atribución de la llamada en curso (nota del hook y transcript), la coletilla
    usa ese modelo y no el respaldo. Haiku, `.md` por `path`: su `read_format` está sin medir →
    respaldo (2), prosa sin numerar, c = 3,01 → 4000 × 100 // 301 = 1328 (con Opus 5.5, 2000)."""
    _backend(monkeypatch, tmp_path, prompt_tokens=9999)
    monkeypatch.setattr(
        attribution,
        "current_call",
        lambda: {"caller_model": "claude-haiku-4-5", "caller_kind": "main", "caller_src": "hook"},
    )
    doc = tmp_path / "notes.md"
    doc.write_text("palabra " * 500, encoding="utf-8")
    text = server.local_summarize(path=str(doc))
    assert "≈ 1,328 tokens de Claude" in text
