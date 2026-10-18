"""`/api/hooks`: lo que los hooks consultivos han sugerido, expuesto en el dashboard.

El dato ya se escribía —1800 eventos en tres días en la máquina de referencia— y `metrics.py` no
lo mencionaba ni una vez. Lo que estos tests vigilan sobre todo es que el panel **no diga más de
lo que el dato sostiene**: el hook sugiere, el usuario decide, y desde aquí no hay forma de saber
si la sugerencia se siguió.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from local_delegate import config, i18n
from local_delegate.web import metrics


@pytest.fixture(autouse=True)
def _without_cache():
    """El lector cachea por (mtime, size), y en tests dos ficheros pueden coincidir en ambos."""
    metrics._FILE_CACHE.clear()
    yield
    metrics._FILE_CACHE.clear()


def _event(when: datetime, *, event="PreToolUse", category="bash", suggested=False) -> dict:
    return {
        "ts": when.isoformat(),
        "event": event,
        "suggested": suggested,
        "category": category,
        "command_chars": 100,
    }


def _write(path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


# --- El agregado, que es donde vive todo el criterio ---------------------------


def test_counts_suggested_over_the_total():
    now = datetime.now(UTC)
    rows = [
        _event(now, suggested=True),
        _event(now, suggested=False),
        _event(now, suggested=False),
        _event(now, suggested=True),
    ]
    aggregate = metrics._aggregate_hooks(rows)

    assert aggregate["total"] == 4
    assert aggregate["suggested"] == 2
    assert aggregate["rate"] == 0.5


def test_an_old_event_without_the_suggested_field_counts_as_not_suggested():
    """El campo se añadió después; su ausencia significaba exactamente «no sugirió».

    Tratarla como `True` inflaría la tasa con eventos que nunca sugirieron nada, y el número
    saldría más bonito — que es justo por lo que hay que fijarlo con un test.
    """
    row = {"ts": datetime.now(UTC).isoformat(), "event": "PreToolUse"}
    aggregate = metrics._aggregate_hooks([row])

    assert aggregate["total"] == 1
    assert aggregate["suggested"] == 0


def test_without_events_the_rate_is_zero_and_nothing_blows_up():
    """Dividir entre cero aquí tumbaría el endpoint entero por no tener datos."""
    aggregate = metrics._aggregate_hooks([])
    assert aggregate == {
        "total": 0,
        "suggested": 0,
        "rate": 0.0,
        "by_event": [],
        "by_category": [],
        "by_day": [],
        "read_total": 0,
        "by_reason": [],
        "by_ext": [],
    }


def test_groups_by_event_category_and_day():
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    rows = [
        _event(today, event="PreToolUse", category="bash", suggested=True),
        _event(today, event="PreToolUse", category="bash", suggested=False),
        _event(today, event="UserPromptSubmit", category="read", suggested=True),
        _event(yesterday, event="PreToolUse", category="bash", suggested=False),
    ]
    aggregate = metrics._aggregate_hooks(rows)

    by_event = {d["event"]: d for d in aggregate["by_event"]}
    assert by_event["PreToolUse"] == {"event": "PreToolUse", "total": 3, "suggested": 1}
    assert by_event["UserPromptSubmit"]["suggested"] == 1

    by_category = {d["category"]: d for d in aggregate["by_category"]}
    assert by_category["bash"]["total"] == 3

    assert [d["day"] for d in aggregate["by_day"]] == [
        yesterday.date().isoformat(),
        today.date().isoformat(),
    ], "los días tienen que salir en orden cronológico, no por volumen"


def test_a_missing_category_is_not_lost_in_the_count():
    """Sin la casilla `no_category` («Sin categoría»), los totales por categoría no sumarían el total."""
    row = {"ts": datetime.now(UTC).isoformat(), "event": "PreToolUse", "suggested": True}
    aggregate = metrics._aggregate_hooks([row])

    assert sum(d["total"] for d in aggregate["by_category"]) == aggregate["total"]
    assert aggregate["by_category"][0]["category"] == "no_category"


def test_the_lists_come_out_sorted_by_volume():
    now = datetime.now(UTC)
    rows = [_event(now, category="bash")] * 3 + [_event(now, category="read")]
    aggregate = metrics._aggregate_hooks(rows)
    assert [d["category"] for d in aggregate["by_category"]] == ["bash", "read"]


# --- El endpoint --------------------------------------------------------------


def test_without_the_variable_the_endpoint_says_so_instead_of_pretending_there_is_nothing(
    monkeypatch,
):
    """«No activaste la telemetría» y «está activada y no hay eventos» son cosas distintas.

    Sin `enabled`, un panel a cero se lee como «los hooks no sugieren nada» — una conclusión falsa
    sacada de un fichero que ni siquiera existe.
    """
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    data = TestClient(metrics.app).get("/api/hooks").json()

    assert data["enabled"] is False
    assert "LD_HOOK_TELEMETRY_LOG" in data["reason"]
    assert data["total"] == 0


def test_with_the_variable_but_no_file_it_says_it_is_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", tmp_path / "missing.jsonl")
    data = TestClient(metrics.app).get("/api/hooks").json()

    assert data["enabled"] is True
    assert data["exists"] is False
    assert data["total"] == 0


def test_reads_the_real_log(monkeypatch, tmp_path):
    log = tmp_path / "telemetry.jsonl"
    now = datetime.now(UTC)
    _write(log, [_event(now, suggested=True), _event(now, suggested=False)])
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)

    data = TestClient(metrics.app).get("/api/hooks").json()

    assert data["enabled"] is True
    assert data["exists"] is True
    assert (data["total"], data["suggested"]) == (2, 1)


def test_the_range_filters_as_in_the_rest_of_the_dashboard(monkeypatch, tmp_path):
    """Si no filtrara, la tarjeta contradiría al resto de la página con el mismo rango puesto."""
    log = tmp_path / "telemetry.jsonl"
    now = datetime.now(UTC)
    _write(
        log,
        [
            _event(now - timedelta(days=40), suggested=True),
            _event(now, suggested=True),
        ],
    )
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)

    since = (now - timedelta(days=2)).date().isoformat()
    data = TestClient(metrics.app).get(f"/api/hooks?from={since}").json()

    assert data["total"] == 1, "el evento de hace 40 días no debería entrar en el rango"


def test_a_corrupt_line_does_not_bring_the_endpoint_down(monkeypatch, tmp_path):
    """El log lo escriben procesos que pueden morir a media línea."""
    log = tmp_path / "telemetry.jsonl"
    good = json.dumps(_event(datetime.now(UTC), suggested=True))
    log.write_text(f"{good}\n{{esto no es json\n{good}\n", encoding="utf-8")
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)

    data = TestClient(metrics.app).get("/api/hooks").json()
    assert data["total"] == 2


def test_the_endpoint_returns_neither_commands_nor_prompts(monkeypatch, tmp_path):
    """La telemetría promete no registrar contenido, y el dashboard no puede romper esa promesa.

    Aunque el hook solo escribe tamaños, exponer el evento crudo dejaría la puerta abierta a que
    un campo nuevo del hook acabe publicado sin que nadie lo decida.
    """
    log = tmp_path / "telemetry.jsonl"
    row = _event(datetime.now(UTC), suggested=True)
    row["command"] = "rm -rf /algo/secreto"
    _write(log, [row])
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)

    raw = TestClient(metrics.app).get("/api/hooks").text
    assert "secreto" not in raw
    assert "rm -rf" not in raw


# --- El JS de la tarjeta, ejecutado de verdad ---------------------------------


def _labels_js(page: str) -> str:
    """Las etiquetas legibles (clave interna → texto del panel) y la tabla de valores viejos que
    inyecta el servidor, tal como salen en la página servida. Los textos salen del catálogo que
    inyecta el servidor (`I18N`) por `T`, con el panel en español, como el `locale` de los tests
    de Playwright (REQ-043)."""
    parts = [
        "const LANG = 'es'",
        *(_extract_js_function(page, header) for header in ("const I18N = {", "function T(")),
    ] + [
        _extract_js_function(page, header)
        for header in (
            "const LABELS = {",
            "const LEGACY_VALUES = {",
            "function humanLabel(",
            "function labelFor(",
        )
    ]
    return ";\n".join(parts) + ";"


def _extract_js_function(source: str, header: str) -> str:
    """Recorta una función del `<script>` balanceando llaves. Igual que en `test_metrics.py`."""
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


def test_the_log_category_is_escaped_before_rendering(tmp_path):
    """Se **ejecuta** con node, no se busca por grep: lo que importa es qué produce, no qué dice.

    La categoría es el único texto de esta página que no controla el daemon — sale de un fichero
    que escriben los hooks. El resto del panel interpola directo porque sus datos son propios;
    aquí no lo son.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    esc_js = _extract_js_function(metrics.HTML, "function escHooks(s){")
    cases = ["bash", "<img src=x onerror=alert(1)>", None, "a&b", '"comillas"', "it's"]
    input_file = tmp_path / "cases.json"
    input_file.write_text(json.dumps(cases), encoding="utf-8")

    program = tmp_path / "esc.mjs"
    program.write_text(
        "import {readFileSync} from 'node:fs';\n"
        f"{esc_js}\n"
        f"const testCases = JSON.parse(readFileSync({json.dumps(str(input_file))}, 'utf-8'));\n"
        "console.log(JSON.stringify(testCases.map(escHooks)));\n",
        encoding="utf-8",
    )
    output = subprocess.run(
        [node, str(program)], capture_output=True, text=True, timeout=30, check=True
    )
    result = json.loads(output.stdout)

    assert result[0] == "bash", "el caso normal no se toca"
    assert result[1] == "&lt;img src=x onerror=alert(1)&gt;"
    assert result[2] == "", "null se pinta vacío, no como la cadena 'null'"
    assert result[3] == "a&amp;b"
    assert result[4] == "&quot;comillas&quot;"
    assert result[5] == "it&#39;s"

    for rendered in result:
        assert "<" not in rendered and ">" not in rendered


def test_the_card_hides_when_there_is_no_telemetry(tmp_path):
    """Enseñar ceros diría «los hooks no sugieren nada» leyendo un fichero que no existe.

    Se ejercita la función real con node y tres entradas: sin telemetría, activada pero vacía, y
    con datos. Comprobarlo por grep sobre el HTML no distinguiría los tres casos.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    page = metrics.render_index()
    render_js = _extract_js_function(page, "function renderHooks(h){")
    esc_js = _extract_js_function(page, "function escHooks(s){")
    # Los formateadores del panel (REQ-030/031): `F` y `F1` son objetos sobre `fmtNum`.
    fmt_js = _extract_js_function(page, "function fmtNum(")
    labels_js = _labels_js(page)

    program = tmp_path / "render.mjs"
    program.write_text(
        # DOM mínimo: cada `getElementById` devuelve un objeto que apunta lo que le escriben.
        "const nodes = {};\n"
        "const elem = () => ({style:{display:'?'}, textContent:'', innerHTML:''});\n"
        "globalThis.document = {getElementById: id => (nodes[id] ??= elem())};\n"
        f"{fmt_js}\n"
        "globalThis.F = {format: n => fmtNum(n, 0)};\n"
        "globalThis.F1 = {format: n => fmtNum(n, 1)};\n"
        f"{esc_js}\n"
        f"{labels_js}\n"
        f"{render_js}\n"
        "const results = [];\n"
        "for (const testCase of [null, {enabled:false}, {enabled:true, total:0},\n"
        "  {enabled:true, total:10, suggested:3, rate:0.3,\n"
        "   by_category:[{category:'bash', total:8, suggested:2},\n"
        "                {category:'<img src=x onerror=alert(1)>', total:2, suggested:1}]}]) {\n"
        "  for (const k in nodes) delete nodes[k];\n"
        "  renderHooks(testCase);\n"
        "  results.push({display: nodes.hooksCard.style.display,\n"
        "               head: nodes.hooksHead ? nodes.hooksHead.textContent : '',\n"
        "               body: nodes.hooksBody ? nodes.hooksBody.innerHTML : ''});\n"
        "}\n"
        "console.log(JSON.stringify(results));\n",
        encoding="utf-8",
    )
    output = subprocess.run(
        [node, str(program)], capture_output=True, text=True, timeout=30, check=True
    )
    without_data, disabled, empty, with_data = json.loads(output.stdout)

    assert without_data["display"] == "none", "sin respuesta del endpoint, la tarjeta no se enseña"
    assert disabled["display"] == "none", "telemetría desactivada: no se enseñan ceros"
    assert empty["display"] == "none", "activada pero sin eventos: tampoco se enseñan ceros"

    assert with_data["display"] == "", "con datos, la tarjeta se enseña"
    assert "3 de 10" in with_data["head"]
    assert "30,0 %" in with_data["head"], "el porcentaje va con coma decimal, como el resto"
    assert "Shell" in with_data["body"]  # `bash`, con su etiqueta legible
    assert "25,0 %" in with_data["body"], "la tasa por categoría es 2 de 8"
    # Lo que la tarjeta NO puede dejar de decir: que esto cuenta sugerencias, no delegaciones. Lo
    # dice el diálogo de información que abre el ⓘ de su cabecera, no un párrafo en el cuerpo.
    assert "sugieren" not in with_data["body"]
    dialog = metrics.HTML[metrics.HTML.index('<section id="dlgHooks"') :]
    dialog = dialog[: dialog.index("</section>")]
    assert 'data-i18n-html="dialog.hooks.body_html"' in dialog  # el texto sale del catálogo
    body = i18n.t_lang("es", "panel.dialog.hooks.body_html")
    assert "Los hooks <b>sugieren</b>; delegar lo decides tú." in body
    assert 'id="hooksInfo" data-group="hooks"' in metrics.HTML

    # Y que el escapado se USE, no solo que exista. Probar `escHooks` por su cuenta deja pasar
    # el mutante que quita la llamada — ya ocurrió, y por eso el caso malicioso entra aquí, en
    # el HTML que produce la función de verdad.
    assert "<img src=x" not in with_data["body"], "la categoría se pintó sin escapar"
    assert "&lt;img src=x onerror=alert(1)&gt;" in with_data["body"]


# --- Puntería del hook de lectura --------------------------------------------------------------
#
# El hook pasó tres semanas avisando sobre lecturas de código sin que se notara, porque la
# telemetría guardaba tamaño y banda pero no qué se estaba leyendo. Estos tests fijan que el panel
# pueda enseñar esa selectividad — y que no la invente donde no la hay.


def _read_event(**extra) -> dict:
    base = {"ts": datetime.now(UTC).isoformat(), "event": "PreToolUse", "category": "read"}
    base.update(extra)
    return base


def test_groups_the_reads_by_discard_reason():
    aggregate = metrics._aggregate_hooks(
        [
            _read_event(suggested=True, ext=".md", band="strong"),
            _read_event(suggested=False, ext=".ts", reason="code"),
            _read_event(suggested=False, ext=".ts", reason="code"),
            _read_event(suggested=False, ext=".md", reason="bounded"),
        ]
    )

    assert {m["reason"]: m["total"] for m in aggregate["by_reason"]} == {
        "code": 2,
        "suggested": 1,
        "bounded": 1,
    }
    assert aggregate["read_total"] == 4


def test_groups_the_reads_by_extension():
    aggregate = metrics._aggregate_hooks(
        [
            _read_event(suggested=False, ext=".ts", reason="code"),
            _read_event(suggested=False, ext=".ts", reason="code"),
            _read_event(suggested=True, ext=".md"),
        ]
    )

    assert aggregate["by_ext"] == [{"ext": ".ts", "total": 2}, {"ext": ".md", "total": 1}]


def test_old_telemetry_does_not_get_a_made_up_reason():
    """Los eventos anteriores al PR #146 no traen `motivo` (hoy `reason`) ni `ext`.

    Meterlos en un motivo concreto diría que el hook descartaba por una razón que nunca registró,
    y en este log eso son miles de líneas: la tarjeta contaría una historia falsa sobre el pasado.
    """
    aggregate = metrics._aggregate_hooks(
        [_read_event(suggested=False), _read_event(suggested=False)]
    )

    assert {m["reason"]: m["total"] for m in aggregate["by_reason"]} == {"unrecorded": 2}
    assert aggregate["by_ext"] == [{"ext": "no_extension", "total": 2}]


def test_the_other_hooks_do_not_count_in_the_read_aim():
    """Control de los tres de arriba, y el fallo más fácil de cometer aquí.

    `reason` sólo lo escribe el hook de lectura. Si el agregado recorriera todos los eventos, los
    de `lint` y `summarize` caerían en «sin registrar» y la tarjeta diría que el hook descarta sin
    motivo la mitad de las veces — un número que se lee bien y significa otra cosa.
    """
    aggregate = metrics._aggregate_hooks(
        [
            _read_event(suggested=True, ext=".md"),
            {"ts": datetime.now(UTC).isoformat(), "event": "PreToolUse", "category": "lint"},
            {
                "ts": datetime.now(UTC).isoformat(),
                "event": "UserPromptSubmit",
                "category": "summarize",
                "suggested": True,
            },
        ]
    )

    assert aggregate["total"] == 3
    assert aggregate["read_total"] == 1
    assert {m["reason"]: m["total"] for m in aggregate["by_reason"]} == {"suggested": 1}


# --- Telemetría vieja y nueva mezcladas (REQ-005/006/009, ola A2) -------------------------------


def _read_rows(fmt: str) -> list[dict]:
    """El mismo reparto de motivos, escrito con las claves y valores viejos o con los nuevos."""
    old = fmt == "viejo"
    key, block_key = ("motivo", "bloqueo") if old else ("reason", "block")
    values = (
        ["codigo", "codigo", "acotada", "mcp_ajeno", "prosa_grande"]
        if old
        else ["code", "code", "bounded", "foreign_mcp", "large_prose"]
    )
    state = "encendido" if old else "on"
    return [_read_event(suggested=False, **{key: v, block_key: state}) for v in values]


def test_mixed_telemetry_gives_the_same_split_as_the_new_one():
    """Un fichero con filas viejas y nuevas da el mismo `by_reason` que con todas nuevas: la
    historia en español (31 691 líneas en la máquina de referencia) se sigue leyendo entera."""
    new_ones = _read_rows("nuevo")
    mixed = _read_rows("viejo")[:3] + new_ones[3:]

    only_new = metrics._aggregate_hooks(new_ones)
    mix = metrics._aggregate_hooks(mixed)

    assert only_new["by_reason"] == [
        {"reason": "code", "total": 2},
        {"reason": "bounded", "total": 1},
        {"reason": "foreign_mcp", "total": 1},
        {"reason": "large_prose", "total": 1},
    ]
    assert mix["by_reason"] == only_new["by_reason"]
    assert metrics._aggregate_hooks(_read_rows("viejo"))["by_reason"] == (only_new["by_reason"])


def test_the_reason_dictionary_gives_the_same_label_to_the_old_and_new_value(tmp_path):
    """Se ejecuta con node el `labelFor` de la página servida: `mcp_ajeno` y `foreign_mcp` (y el
    resto de pares viejo/nuevo) tienen que pintarse igual, sin una segunda copia de la tabla."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    from local_delegate import legacy_names

    pairs = sorted(legacy_names.PANEL_VALUE_ALIASES["hookReason"].items())
    program = tmp_path / "labels.mjs"
    program.write_text(
        f"{_labels_js(metrics.render_index())}\n"
        f"const aliasPairs = {json.dumps(pairs)};\n"
        "console.log(JSON.stringify(aliasPairs.map(([v, n]) => [labelFor('hookReason', v),"
        " labelFor('hookReason', n)])));\n",
        encoding="utf-8",
    )
    output = subprocess.run(
        [node, str(program)], capture_output=True, text=True, timeout=30, check=True
    )
    labels = json.loads(output.stdout)

    assert len(labels) == len(pairs) >= 14
    assert dict(zip([v for v, _n in pairs], labels, strict=True))["mcp_ajeno"] == [
        "Por otro MCP",
        "Por otro MCP",
    ]
    for (old, new), (from_old, from_new) in zip(pairs, labels, strict=True):
        assert from_old == from_new, f"{old} y {new} se pintan distinto"
        # Y con una etiqueta escrita, no la que inventa `humanLabel` a partir de la clave.
        assert from_new != new, f"{new} no tiene etiqueta en LABELS.hookReason"
