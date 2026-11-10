"""The own-repo switch and the caller columns of the dashboard (usage-log-project-and-own-repo-
exclusion, T5: REQ-013 and REQ-015).

The pure functions (`buildQuery`, `fetchData`, `selfText`, `renderClients`) run with node, like the
rest of the panel; the switch itself runs in a browser against the real dashboard, served in a
thread on a free port (`panel_server`).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from panel_server import PanelServer
from test_dashboard_js import _run
from test_dashboard_states import _DOM, _EMIT, _f, _js

from local_delegate import config, i18n
from local_delegate.web import metrics

# --- buildQuery and fetchData (node) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("false, 'es', true", {"include_self": "1", "lang": "es"}),
        ("true, 'es', true", {"include_tests": "1", "include_self": "1", "lang": "es"}),
        ("false, 'es', false", {"lang": "es"}),
        ("true, 'es'", {"include_tests": "1", "lang": "es"}),  # three arguments, as today
    ],
)
def test_build_query_carries_the_own_repo_switch_as_a_fourth_argument(tmp_path, args, expected):
    body = (
        f"const q = new URLSearchParams(buildQuery({{from: 'F', to: 'T'}}, {args}));\n"
        "console.log(JSON.stringify(Object.fromEntries(q)));"
    )
    data = _run(tmp_path, ["function buildQuery("], body)
    assert data == {"from": "F", "to": "T", **expected}


_PRELUDE_FETCH = """
const urls = [];
globalThis.fetch = async u => { urls.push(u); return {json: async () => ({})}; };
const state = {range: 'today', tests: false, self: SELF, events: [], meta: {}};
function computeRange(){ return {from: '2026-10-08T04:00:00.000Z', to: '2026-10-08T16:00:00.000Z'}; }
function renderClients(){} function renderCost(){} function renderTestsInfo(){}
function renderHooks(){} function render(){} function updateLive(){} function renderFoot(){}
function plural(){ return ''; }
const CPT = 4, TZ = 'x', TZ_OFFSET_TXT = 'y';
const document = {getElementById: () => ({textContent: '', innerHTML: '', classList: {add(){}}})};
"""


@pytest.mark.parametrize("include", [False, True])
def test_the_three_requests_carry_include_self_together(tmp_path, include):
    """Mutant 40 (`buildQuery` does not add the parameter): the three carry `include_self=1`."""
    prelude = _PRELUDE_FETCH.replace("SELF", "true" if include else "false")
    body = "await fetchData();\nconsole.log(JSON.stringify(urls));"
    urls = _run(tmp_path, ["function buildQuery(", "async function fetchData("], body, prelude)
    assert [u.split("?")[0] for u in urls] == ["/api/events", "/api/stats", "/api/hooks"]
    queries = {u.split("?", 1)[1] for u in urls}
    assert len(queries) == 1, urls
    (query,) = queries
    assert ("include_self=1" in query) is include


# --- selfText (node) ------------------------------------------------------------------------------

_SELF_TEXT = ["function fmtNum(", "function plural(", "function selfText("]
_PRELUDE_F = "const F = {format: n => fmtNum(n, 0)};\n"


def _self_text(tmp_path, stats, lang: str = "es") -> str:
    # `emit` escapes what is not ASCII: node writes UTF-8 and the reader decodes with the locale.
    body = f"emit(selfText({json.dumps(stats)}).join('\\n'));"
    return _run(tmp_path, _SELF_TEXT, body, _EMIT + _PRELUDE_F, lang=lang)


def test_self_text_says_how_many_delegations_are_left_out(tmp_path):
    text = _self_text(tmp_path, {"excluded_self": 7, "self_in_range": 9, "unknown_project": 0})
    assert "Fuera de las cifras: 7 delegaciones del propio repo" in text
    assert "self-projects.json" in text  # the rule says where the extra names live
    assert "Sin proyecto registrado" not in text


def test_self_text_included_none_and_unknown(tmp_path):
    included = _self_text(tmp_path, {"excluded_self": 0, "self_in_range": 1})
    assert "Propio repo incluido: 1 delegación" in included
    none = _self_text(tmp_path, {"excluded_self": 0, "self_in_range": 0, "unknown_project": 3})
    assert "no hay delegaciones del propio repo" in none
    assert "Sin proyecto registrado: 3 delegaciones" in none


def test_self_text_in_english(tmp_path):
    text = _self_text(tmp_path, {"excluded_self": 2, "self_in_range": 2}, lang="en")
    assert "Left out of the figures: 2 delegations from the own repo" in text


# --- renderClients: the three columns (node, REQ-015) ---------------------------------------------


def _clients(tmp_path, by_client: list[dict]) -> str:
    r = _js(
        tmp_path,
        [_f("renderClients")],
        f"renderClients({json.dumps({'by_client': by_client})});\n"
        "emit({body: _els.clientsBody.innerHTML});",
        _DOM,
    )
    return r["body"]


def _client(name: str, calls: int, main: int, subagent: int, mod: int, unknown: int) -> dict:
    return {
        "client": name,
        "calls": calls,
        "main_calls": main,
        "subagent_calls": subagent,
        "mod_calls": mod,
        "unknown_caller_calls": unknown,
        "backend_calls": calls,
        "tokens_net": 100,
    }


def _headers(body: str) -> list[str]:
    return re.findall(r"<th>([^<]*)</th>", body)


def _t(key: str, **kw) -> str:
    return i18n.t_lang("es", f"panel.{key}", **kw)


def test_the_card_has_three_caller_columns_and_no_unknown_when_it_is_zero(tmp_path):
    body = _clients(tmp_path, [_client("claude-code", 10, 6, 3, 1, 0)])
    headers = _headers(body)
    assert headers[-3:] == [
        _t("clients.col.main"),
        _t("clients.col.subagent"),
        _t("clients.col.mod"),
    ]
    assert _t("clients.col.unknown") not in headers
    row = body.split("<tbody>", 1)[1]
    cells = re.findall(r"<td[^>]*>([^<]*)</td>", row)
    assert cells[-3:] == ["6", "3", "1"]
    assert f'title="{_t("clients.mod_calls", n="1")}"' in row  # the mod cell keeps its words


def test_the_unknown_column_shows_only_when_some_row_has_it(tmp_path):
    body = _clients(
        tmp_path,
        [_client("claude-code", 10, 6, 3, 1, 0), _client("codex-mcp-client", 4, 0, 0, 0, 4)],
    )
    headers = _headers(body)
    assert headers[-1] == _t("clients.col.unknown")
    codex = next(tr for tr in body.split("<tr>") if "Codex" in tr)
    assert re.findall(r"<td[^>]*>([^<]*)</td>", codex)[-4:] == ["0", "0", "0", "4"]
    assert "del mod" not in codex


def test_the_net_column_stays_the_fourth(tmp_path):
    """The other cards' tests read the net from the fourth cell: the new columns go after it."""
    body = _clients(tmp_path, [_client("claude-code", 10, 6, 3, 1, 0)])
    assert _headers(body)[3] == _t("clients.col.net")


# --- The switch in the browser (REQ-013) ----------------------------------------------------------


@pytest.fixture
def backend_down(request, monkeypatch):
    """The test panel's backend is the suite's connection-cutting server, never the real one."""
    from conftest import CUT_DAEMON

    port = request.node.stash[CUT_DAEMON].port
    monkeypatch.setattr(config, "BASE_URL", f"http://127.0.0.1:{port}/v1")


def _browser(pw):
    from playwright.sync_api import Error as PlaywrightError

    try:
        return pw.chromium.launch()
    except PlaywrightError as exc:
        pytest.skip(f"no hay navegador de Playwright instalado: {exc}")
        raise AssertionError("unreachable: pytest.skip raises Skipped") from exc


def _usage_row(ts: datetime, n: int, kind: str | None) -> dict:
    row = {
        "ts": ts.isoformat(timespec="seconds"),
        "tool": f"local_tool_{n:03d}",
        "model": "test-model",
        "source": "path",
        "chars_in": 1000 + n,
        "chars_out": 100,
        "ok": True,
        "tokens_in": 250,
        "backend": "local",
        "client": "claude-code",
    }
    if kind:
        row["caller_project_kind"] = kind
    return row


@pytest.mark.xdist_group("dashboard_ui")
def test_the_own_repo_switch_requests_all_three_and_is_remembered(
    tmp_path, monkeypatch, new_page, backend_down
):
    """Off at first with the number of what is left out beside it; pressed, the three requests
    carry `include_self=1`; reloaded, it is still on. Mutant 41 (the state is not saved): after
    reloading it is still on."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    now = datetime.now(UTC)
    local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    step = min(timedelta(minutes=1), (now - local_midnight) / 4)  # all of them today
    rows = [_usage_row(now - step * n, n, kind) for n, kind in enumerate(("other", "self", None))]
    (tmp_path / f"usage-{now:%Y%m}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    metrics._FILE_CACHE.clear()
    requested: list[str] = []
    state = """() => ({on: document.getElementById('self').classList.contains('on'),
                       pressed: document.getElementById('self').getAttribute('aria-pressed'),
                       count: document.getElementById('selfCount').checkVisibility()
                         ? document.getElementById('selfCount').textContent : null})"""
    with PanelServer() as server, sync_playwright() as pw:
        browser = _browser(pw)
        page = new_page(browser, viewport={"width": 1440, "height": 1000})
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.on("request", lambda r: requested.append(r.url) if "/api/" in r.url else None)
        page.goto(server.url)
        page.wait_for_selector("#activity tbody tr")
        page.wait_for_function("() => document.getElementById('dlgSelfBody').innerText.length")
        initial = page.evaluate(state)
        page.click("#selfInfo")
        text_off = page.inner_text("#dlgSelf")
        page.keyboard.press("Escape")
        before = [u for u in requested if re.search(r"/api/(events|stats|hooks)\?", u)]
        requested.clear()
        with page.expect_response(lambda r: "/api/stats" in r.url and "include_self=1" in r.url):
            page.click("#self")
        page.wait_for_function(
            "() => document.getElementById('dlgSelfBody').innerText.includes('incluido')"
        )
        after = [u for u in requested if re.search(r"/api/(events|stats|hooks)\?", u)]
        pressed = page.evaluate(state)
        requested.clear()
        with page.expect_response(lambda r: "/api/stats" in r.url):
            page.reload()
        page.wait_for_selector("#activity tbody tr")
        reloaded = page.evaluate(state)
        after_reload = [u for u in requested if re.search(r"/api/(events|stats|hooks)\?", u)]
        remembered = page.evaluate("() => localStorage.getItem('ld-self')")
        browser.close()
    metrics._FILE_CACHE.clear()

    assert initial == {"on": False, "pressed": "false", "count": "1"}
    assert "Fuera de las cifras: 1 delegación del propio repo" in text_off
    assert len(before) >= 3 and not any("include_self" in u for u in before), before
    assert sorted(u.split("?")[0].rsplit("/", 1)[1] for u in after) == ["events", "hooks", "stats"]
    assert all("include_self=1" in u for u in after), after
    assert pressed == {"on": True, "pressed": "true", "count": None}  # nothing is left out
    assert reloaded == {"on": True, "pressed": "true", "count": None}  # still on after reloading
    assert after_reload and all("include_self=1" in u for u in after_reload), after_reload
    assert remembered == "1"
