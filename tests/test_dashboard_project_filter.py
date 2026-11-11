"""The project filter, the per-project card and the caller columns of the dashboard
(dashboard-project-filter; the caller columns come from usage-log-project-and-own-repo-exclusion,
REQ-015).

The pure functions (`buildQuery`, `fetchData`, `renderProjects`, `renderClients`) run with node,
like the rest of the panel; the selector itself runs in a browser against the real dashboard,
served in a thread on a free port (`panel_server`), never against the installed daemon.

A project's name is the name of a folder (untrusted text): every test that paints one uses a
hostile name and checks that it reaches the page as text, never as markup.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from panel_server import PanelServer
from test_dashboard_js import _run
from test_dashboard_states import _DOM, _f, _js

from local_delegate import config, i18n
from local_delegate.web import metrics

P_A = "a1b2c3d4e5f60718"
P_B = "0718a1b2c3d4e5f6"
HOSTILE = '<img src=x onerror="window.__xss=1">&"\''

# --- buildQuery and fetchData (node) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (f"false, 'es', '{P_A}'", {"project": P_A, "lang": "es"}),
        ("true, 'es', 'none'", {"include_tests": "1", "project": "none", "lang": "es"}),
        ("false, 'es', ''", {"lang": "es"}),
        ("true, 'es'", {"include_tests": "1", "lang": "es"}),  # three arguments: every project
    ],
)
def test_build_query_carries_the_project_as_a_fourth_argument(tmp_path, args, expected):
    body = (
        f"const q = new URLSearchParams(buildQuery({{from: 'F', to: 'T'}}, {args}));\n"
        "console.log(JSON.stringify(Object.fromEntries(q)));"
    )
    data = _run(tmp_path, ["function buildQuery("], body)
    assert data == {"from": "F", "to": "T", **expected}


_PRELUDE_FETCH = """
const urls = [];
globalThis.fetch = async u => { urls.push(u); return {json: async () => ({})}; };
const state = {range: 'today', tests: false, project: PROJECT, events: [], meta: {}};
function computeRange(){ return {from: '2026-10-08T04:00:00.000Z', to: '2026-10-08T16:00:00.000Z'}; }
function renderClients(){} function renderProjects(){} function renderCost(){} function renderTestsInfo(){}
function renderHooks(){} function render(){} function updateLive(){} function renderFoot(){}
function plural(){ return ''; }
const CPT = 4, TZ = 'x', TZ_OFFSET_TXT = 'y';
const document = {getElementById: () => ({textContent: '', innerHTML: '', classList: {add(){}}})};
"""


@pytest.mark.parametrize("project", ["", P_A, "none"])
def test_the_three_requests_carry_the_same_project(tmp_path, project):
    """Mutant (`buildQuery` does not add the parameter): the three carry `project=` together."""
    prelude = _PRELUDE_FETCH.replace("PROJECT", json.dumps(project))
    body = "await fetchData();\nconsole.log(JSON.stringify(urls));"
    urls = _run(tmp_path, ["function buildQuery(", "async function fetchData("], body, prelude)
    assert [u.split("?")[0] for u in urls] == ["/api/events", "/api/stats", "/api/hooks"]
    queries = {u.split("?", 1)[1] for u in urls}
    assert len(queries) == 1, urls
    (query,) = queries
    assert ("project=" in query) is bool(project)
    if project:
        assert f"project={project}" in query
    assert "include_self" not in query


# --- renderProjects (node) -------------------------------------------------------------------------

_SELECT = """
const _opts = [{value: '', textContent: 'all'}];
_els.project = {options: _opts, value: '', remove(i){ _opts.splice(i, 1); },
                appendChild(o){ _opts.push(o); }};
document.createElement = () => ({value: '', textContent: ''});
const state = {project: CHOSEN, projectNames: {}};
"""


def _projects(tmp_path, by_project, chosen: str = "", lang: str = "es") -> dict:
    prelude = _DOM + _SELECT.replace("CHOSEN", json.dumps(chosen))
    functions = [_f("projectLabel"), _f("renderProjectOptions"), _f("renderProjects")]
    body = (
        f"renderProjects({json.dumps({'by_project': by_project})});\n"
        "emit({body: (_els.projectsBody || {}).innerHTML || '', head: (_els.projectsHead || {}).textContent,"
        " display: _els.projectsCard.style.display,"
        " options: _opts.map(o => [o.value, o.textContent]), value: _els.project.value});"
    )
    return (
        _js(tmp_path, functions, body, prelude)
        if lang == "es"
        else _run_en(tmp_path, functions, body, prelude)
    )


def _run_en(tmp_path, functions, body, prelude):
    from test_dashboard_states import _globals

    return _run(tmp_path, functions, body, _globals() + "\n" + prelude, lang="en")


def _group(project: str, name, calls: int, net: int = 100) -> dict:
    return {
        "project": project,
        "name": name,
        "calls": calls,
        "tokens_saved": net,
        "tokens_net": net,
    }


def test_the_card_lists_each_project_with_its_name_or_its_fallback(tmp_path):
    r = _projects(
        tmp_path,
        [_group(P_A, "C--work-shop", 6), _group(P_B, None, 3), _group("none", None, 1)],
    )
    rows = r["body"].split("<tbody>", 1)[1].split("</tr>")
    assert "C--work-shop" in rows[0]
    assert _t("project.unnamed") in rows[1]
    assert _t("project.none") in rows[2]
    assert re.findall(r"<th>([^<]*)</th>", r["body"]) == [
        _t("projects.col.project"),
        _t("projects.col.delegations"),
        _t("projects.col.net"),
        _t("projects.col.share"),
    ]
    assert "60,0 %" in rows[0]
    assert r["display"] == ""
    assert r["options"] == [
        ["", "all"],
        [P_A, "C--work-shop"],
        [P_B, _t("project.unnamed")],
        ["none", _t("project.none")],
    ]


def test_the_fallbacks_are_in_english_too(tmp_path):
    r = _projects(tmp_path, [_group(P_B, None, 3), _group("none", None, 1)], lang="en")
    assert "Unnamed project" in r["body"] and "No project" in r["body"]


def test_a_hostile_name_reaches_the_card_escaped_and_the_option_as_text(tmp_path):
    """Mutant: the name goes into the HTML without `escHooks` (it would carry a live `<img`)."""
    r = _projects(tmp_path, [_group(P_A, HOSTILE, 2)])
    assert "<img" not in r["body"]
    assert "&lt;img src=x onerror=&quot;window.__xss=1&quot;&gt;&amp;&quot;&#39;" in r["body"]
    # The option gets it through `textContent`, which never parses markup: it stays the raw text.
    assert r["options"][1] == [P_A, HOSTILE]


def test_the_chosen_project_stays_an_option_and_its_row_is_marked(tmp_path):
    marked = _projects(tmp_path, [_group(P_A, "C--work-shop", 2), _group(P_B, None, 1)], P_A)
    assert marked["value"] == P_A
    assert marked["body"].split("<tbody>", 1)[1].startswith('<tr class="sel">')
    gone = _projects(tmp_path, [_group(P_B, None, 1)], P_A)
    assert gone["value"] == P_A
    assert [o[0] for o in gone["options"]] == ["", P_B, P_A]


def test_without_projects_the_card_hides(tmp_path):
    assert _projects(tmp_path, [])["display"] == "none"


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


# --- The selector in the browser ------------------------------------------------------------------


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


def _usage_row(ts: datetime, n: int, project: str | None) -> dict:
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
    if project:
        row["caller_project"] = project
        row["caller_project_kind"] = "self" if project == P_B else "other"
    return row


@pytest.mark.xdist_group("dashboard_ui")
def test_the_project_selector_filters_the_whole_panel(
    tmp_path, monkeypatch, new_page, backend_down
):
    """By default every project (no `project=` in the requests, the own repo counted); choosing
    one, the three requests carry it and the activity table keeps only its rows; a hostile name
    is shown as text and runs nothing; reloading goes back to every project."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    monkeypatch.setattr(metrics, "_NAMES_BACKFILL_TRIED", {})
    now = datetime.now(UTC)
    local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    step = min(timedelta(minutes=1), (now - local_midnight) / 8)  # all of them today
    projects = (P_A, P_A, P_A, P_B, None)
    rows = [_usage_row(now - step * n, n, p) for n, p in enumerate(projects)]
    (tmp_path / f"usage-{now:%Y%m}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (tmp_path / "project-names.json").write_text(
        json.dumps({"version": 1, "names": {P_A: HOSTILE}}), encoding="utf-8"
    )
    metrics._FILE_CACHE.clear()
    requested: list[str] = []
    api = re.compile(r"/api/(events|stats|hooks)\?")
    with PanelServer() as server, sync_playwright() as pw:
        browser = _browser(pw)
        page = new_page(browser, viewport={"width": 1440, "height": 1000})
        page.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"), lambda r: r.abort())
        page.on("request", lambda r: requested.append(r.url) if "/api/" in r.url else None)
        page.goto(server.url)
        page.wait_for_selector("#activity tbody tr")
        page.wait_for_selector("#projectsBody tbody tr")
        before = [u for u in requested if api.search(u)]
        rows_all = page.locator("#activity tbody tr[data-i]").count()
        card_rows = page.locator("#projectsBody tbody tr").count()
        card_text = page.inner_text("#projectsBody")
        injected = page.locator("#projectsBody img, #project img").count()
        options = page.eval_on_selector_all(
            "#project option", "os => os.map(o => [o.value, o.textContent])"
        )
        requested.clear()
        with page.expect_response(lambda r: "/api/stats" in r.url and f"project={P_A}" in r.url):
            page.select_option("#project", P_A)
        page.wait_for_function(
            "n => document.querySelectorAll('#activity tbody tr[data-i]').length === n", arg=3
        )
        after = [u for u in requested if api.search(u)]
        rows_one = page.locator("#activity tbody tr[data-i]").count()
        picked = page.evaluate(
            "() => document.getElementById('project').classList.contains('picked')"
        )
        xss = page.evaluate("() => window.__xss === 1")
        requested.clear()
        with page.expect_response(lambda r: "/api/stats" in r.url):
            page.reload()
        page.wait_for_selector("#activity tbody tr")
        after_reload = [u for u in requested if api.search(u)]
        value_after_reload = page.eval_on_selector("#project", "s => s.value")
        browser.close()
    metrics._FILE_CACHE.clear()

    assert len(before) >= 3 and not any("project=" in u or "include_self" in u for u in before)
    assert rows_all == 5  # every project, the own repo's row too
    assert card_rows == 3
    assert HOSTILE in card_text and injected == 0 and xss is False
    assert [o[0] for o in options] == ["", P_A, P_B, "none"]
    assert options[1][1] == HOSTILE
    assert sorted(u.split("?")[0].rsplit("/", 1)[1] for u in after) == ["events", "hooks", "stats"]
    assert all(f"project={P_A}" in u for u in after), after
    assert rows_one == 3
    assert picked is True
    assert after_reload and not any("project=" in u for u in after_reload)
    assert value_after_reload == ""
