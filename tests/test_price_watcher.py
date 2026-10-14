"""Pruebas de `scripts/price_watcher.py`, el vigilante semanal de precios y límites.

Sin red (REQ-024): las dos páginas oficiales están guardadas en `tests/fixtures/vigilante/` y lo
que se espera de ellas va **congelado en este fichero**, no leído de la tabla del paquete. Así el
PR del vigilante, que cambia la tabla del paquete, no rompe estas pruebas.

El flujo de GitHub se prueba con un cliente `api` falso que registra cada llamada: lo que importa
es que el commit vaya por la API de contenidos (que lo firma), que se lancen los dos workflows del
ruleset y que el PR existente se actualice en vez de abrir otro.
"""

from __future__ import annotations

import ast
import base64
import datetime as dt
import functools
import importlib.util
import json
import secrets
import sys
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "price_watcher.py"
FIXTURES = Path(__file__).parent / "fixtures" / "vigilante"
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "price-watcher.yml"

# Mismo criterio que en `test_ci_gate.py`: `scripts/` no viaja en el sdist.
if not SCRIPT.is_file():
    pytest.skip("scripts/ no está en el árbol (sdist)", allow_module_level=True)


@functools.cache
def _v():
    """El script, cargado a demanda: el test de «solo stdlib» no debe depender de que cargue."""
    spec = importlib.util.spec_from_file_location("price_watcher", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["price_watcher"] = module
    spec.loader.exec_module(module)
    return module


# --- Lo esperado, congelado ---------------------------------------------------------------------

# La tabla que da `precios.html` tal como se guardó el 2026-10-06. Trece modelos: fuera los cuatro
# «Retired» (Opus 4.1, Opus 4, Sonnet 4, Haiku 3.5) y los dos «Invite only» (Mythos 5.1 y 5).
_P = ("input", "output", "w5m", "w1h", "cache_read")
EXPECTED = {
    "web_search_per_1000": 10,
    "models": {
        mid: dict(zip(_P, values, strict=True))
        for mid, values in {
            "claude-fable-5-1": (10, 50, 12.5, 20, 0.25),
            "claude-opus-5-5": (4, 20, 5, 8, 0.20),
            "claude-sonnet-5-5": (2, 10, 2.5, 4, 0.20),
            "claude-haiku-4-5": (1, 5, 1.25, 2, 0.10),
            "claude-fable-5": (10, 50, 12.5, 20, 1),
            "claude-opus-5": (5, 25, 6.25, 10, 0.50),
            "claude-opus-4-8": (5, 25, 6.25, 10, 0.50),
            "claude-opus-4-7": (5, 25, 6.25, 10, 0.50),
            "claude-opus-4-6": (5, 25, 6.25, 10, 0.50),
            "claude-opus-4-5": (5, 25, 6.25, 10, 0.50),
            "claude-sonnet-5": (2, 10, 2.5, 4, 0.20),
            "claude-sonnet-4-6": (3, 15, 3.75, 6, 0.30),
            "claude-sonnet-4-5": (3, 15, 3.75, 6, 0.30),
        }.items()
    },
}

# Una tabla «del paquete» congelada, con la forma de `prices.json`, igual a la página guardada.
PACKAGE = {
    "source": "https://platform.claude.com/docs/en/about-claude/pricing",
    "consulted": "2026-10-06",
    "web_search_per_1000": 10,
    "models": {
        mid: {**prices, "family": "new", "supports_effort": True}
        for mid, prices in EXPECTED["models"].items()
    },
}

TODAY = dt.date(2026, 10, 12)


def _clean_real_table() -> tuple[str, dict]:
    """El `prices.json` del checkout, con su formato, sin marcas de ensayo (`_dry_run...`).

    En la rama de un PR de ensayo el fichero ya trae `_dry_run`, y un test que lo lea tal cual da
    otro resultado que en `main` (run 37526624930). Se quita aquí, sobre una copia, para que los
    tests den lo mismo en las dos ramas. `_note` no es de ensayo y se queda.
    """
    v = _v()
    real = (ROOT / v.PRICES_PATH).read_text(encoding="utf-8")
    table = {k: x for k, x in json.loads(real).items() if not k.startswith(v.DRY_RUN_KEY)}
    return v.serialize_prices(table, real), table


NEW = 0.30


def _prices_page() -> str:
    return (FIXTURES / "prices.html").read_text(encoding="utf-8")


def _limits_page() -> str:
    return (FIXTURES / "limits.html").read_text(encoding="utf-8")


def _html_table(html: str) -> tuple[int, int]:
    start = html.index("<table", html.index('<h2 id="model-pricing"'))
    return start, html.index("</table>", start)


def _row(html: str, name: str) -> tuple[int, int]:
    """Inicio y fin (exclusivo) del `<tr>` de la tabla de precios cuyo enlace es `name`."""
    start, end = _html_table(html)
    pos = html.index(f"{name}</a>", start, end)
    since = html.rindex("<tr", start, pos)
    until = html.index("</tr>", pos) + len("</tr>")
    return since, until


def _change_in_row(html: str, name: str, old: str, new: str) -> str:
    since, until = _row(html, name)
    row = html[since:until]
    assert old in row, f"{old!r} no está en la fila de {name}: la copia guardada cambió"
    return html[:since] + row.replace(old, new, 1) + html[until:]


# --- Precios: la extracción ---------------------------------------------------------------------


def test_the_intact_page_gives_the_frozen_table():
    table = _v().extract_price_table(_prices_page())
    assert table == EXPECTED


def test_the_saved_copy_has_rows_to_ignore():
    """Guarda del test anterior: sin filas «Retired» no probaría que se ignoran."""
    html = _prices_page()
    start, end = _html_table(html)
    assert 'aria-label="Claude Opus 4.1 (Retired)"' in html[start:end]
    assert 'aria-label="Claude Mythos 5.1 (Invite only)"' in html[start:end]


def test_a_footnote_in_the_name_does_not_change_the_id():
    html = _change_in_row(
        _prices_page(),
        "Claude Opus 5.5",
        "Claude Opus 5.5</a>",
        "Claude Opus 5.5<sup>1</sup></a>",
    )
    assert "claude-opus-5-5" in _v().extract_price_table(html)["models"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Claude Opus 4.5", "claude-opus-4-5"),
        ("Claude Opus 5", "claude-opus-5"),
        ("Claude Fable 5.1 (new)", "claude-fable-5-1"),
    ],
)
def test_name_to_id(name, expected):
    assert _v().name_to_id(name) == expected


def test_a_name_outside_the_rule_fails():
    with pytest.raises(_v().WatcherError):
        _v().name_to_id("Opus Ultra")


def test_a_changed_price_gives_that_diff():
    v = _v()
    html = _change_in_row(_prices_page(), "Claude Opus 5.5", "$0.20", f"${NEW:.2f}")
    changes = v.compare(v.extract_price_table(html), PACKAGE)
    assert changes.prices == [("claude-opus-5-5", "cache_read", 0.20, NEW)]
    assert changes.new_ones == [] and changes.vanished == []
    assert changes.has_changes


def test_the_intact_page_gives_no_changes():
    v = _v()
    changes = v.compare(v.extract_price_table(_prices_page()), PACKAGE)
    assert not changes.has_changes
    assert changes.prices == [] and changes.vanished == []


def _with_new_model(html: str) -> str:
    since, until = _row(html, "Claude Opus 5.5")
    copied = html[since:until].replace("Claude Opus 5.5</a>", "Claude New 9</a>")
    return html[:until] + copied + html[until:]


def test_a_new_model_is_listed_in_the_pr():
    v = _v()
    changes = v.compare(v.extract_price_table(_with_new_model(_prices_page())), PACKAGE)
    assert changes.new_ones == ["claude-new-9"]
    body = v.prices_pr_body(changes)
    assert "claude-new-9" in body
    table = v.updated_table(
        PACKAGE, v.extract_price_table(_with_new_model(_prices_page())), changes, TODAY
    )
    assert table["models"]["claude-new-9"]["input"] == 4
    assert table["consulted"] == TODAY.isoformat()


def test_a_disappearing_model_is_not_deleted():
    v = _v()
    html = _prices_page()
    since, until = _row(html, "Claude Opus 4.5")
    html = html[:since] + html[until:]
    html = _change_in_row(html, "Claude Opus 5.5", "$0.20", f"${NEW:.2f}")
    new = v.extract_price_table(html)
    assert "claude-opus-4-5" not in new["models"]  # guarda: de verdad desapareció
    changes = v.compare(new, PACKAGE)
    assert changes.vanished == ["claude-opus-4-5"]
    result = v.updated_table(PACKAGE, new, changes, TODAY)
    assert "claude-opus-4-5" in result["models"]
    assert result["models"]["claude-opus-5-5"]["cache_read"] == NEW
    assert "claude-opus-4-5" in v.prices_pr_body(changes)


def test_without_header_fails():
    v = _v()
    html = _prices_page().replace(
        '<h2 id="model-pricing" class="group">Model pricing',
        '<h2 id="model-pricing" class="group">Model prices',
    )
    with pytest.raises(v.WatcherError, match="cabecera"):
        v.extract_price_table(html)


def test_fewer_than_5_rows_fails():
    v = _v()
    html = _prices_page()
    start, end = _html_table(html)
    group = html.index("<tbody id=", start, end)
    closing = html.index("</tbody>", group) + len("</tbody>")
    trimmed = html[:group] + html[closing:]  # quedan las cuatro filas destacadas
    with pytest.raises(v.WatcherError, match="filas"):
        v.extract_price_table(trimmed)


def test_a_cell_that_is_not_a_number_fails():
    v = _v()
    html = _change_in_row(_prices_page(), "Claude Opus 5.5", "$4<!--", "Consultar<!--")
    with pytest.raises(v.WatcherError, match="ilegible"):
        v.extract_price_table(html)


def test_serialise_keeps_the_package_format():
    """El PR solo debe enseñar lo que cambia: el `0.20` del fichero no se reescribe como `0.2`."""
    v = _v()
    original, table = _clean_real_table()
    assert v.serialize_prices(table, original) == original
    first = next(iter(table["models"]))
    table["models"][first]["output"] = 999
    table["consulted"] = TODAY.isoformat()
    distinct = [
        (a, b)
        for a, b in zip(
            original.splitlines(), v.serialize_prices(table, original).splitlines(), strict=True
        )
        if a != b
    ]
    assert len(distinct) == 2
    assert TODAY.isoformat() in distinct[0][1] and "999" in distinct[1][1]


# --- Límites ------------------------------------------------------------------------------------


def _expected_limits() -> str:
    return (FIXTURES / "limits-expected.txt").read_text(encoding="utf-8")


def test_intact_limits_give_the_expected_text():
    assert _v().extract_limits_text(_limits_page()) == _expected_limits()


def test_limits_with_a_changed_paragraph_give_a_diff():
    v = _v()
    old = "Think of this as your"
    html = _limits_page()
    assert old in html
    text = v.extract_limits_text(html.replace(old, "Picture this as your", 1))
    distinct = [
        b for a, b in zip(_expected_limits().splitlines(), text.splitlines(), strict=True) if a != b
    ]
    assert len(distinct) == 1 and "Picture this as your" in distinct[0]


def test_emptied_limits_fails():
    v = _v()
    html = _limits_page()
    start = html.index(">", html.index("<article")) + 1
    end = html.index("</article>")
    emptied = html[:start] + "<p>Pronto volvemos.</p>" + html[end:]
    with pytest.raises(v.WatcherError, match="caracteres"):
        v.extract_limits_text(emptied)


def test_limits_without_title_fails():
    v = _v()
    h1 = f">{v.LIMITS_TITLE}</h1>"
    assert h1 in _limits_page()
    html = _limits_page().replace(h1, ">Otra cosa</h1>")
    with pytest.raises(v.WatcherError, match="título"):
        v.extract_limits_text(html)


def test_the_limits_pr_says_how_to_restart():
    body = _v().limits_pr_body()
    assert "recompute-cost --reset-calibration" in body


# --- El flujo de GitHub, con un cliente falso ---------------------------------------------------

REPO = "o/r"
PRICES_CONTENTS_PATH = f"/repos/{REPO}/contents/src/local_delegate/resources/data/prices.json"


class FakeGitHub:
    """La REST de GitHub en memoria: lo justo para el flujo del vigilante."""

    def __init__(self, clock, *, open_pr=False, behind_by=0, state="clean", conclusion="success"):
        self.clock = clock
        self.calls: list[tuple[str, str]] = []
        self.bodies: list[object] = []
        self.pr = {"number": 7} if open_pr else None
        self.branch_exists = open_pr
        self.behind_by = behind_by
        self.state = state
        self.conclusion = conclusion
        self.head = "sha-1"
        self.runs: list[dict] = []
        self.files: dict[str, str] = {}

    def __call__(self, method, path, body=None):
        v = _v()
        self.calls.append((method, path))
        self.bodies.append(body)
        b = f"/repos/{REPO}"
        url_path, _, query = path.partition("?")
        if method == "GET" and url_path == f"{b}/git/ref/heads/main":
            return {"object": {"sha": "sha-main"}}
        if method == "GET" and url_path.startswith(f"{b}/git/ref/heads/"):
            if self.branch_exists:
                return {"object": {"sha": self.head}}
            raise v.ErrorHTTP(404, "Not Found")
        if method == "POST" and url_path == f"{b}/git/refs":
            self.branch_exists = True
            return {}
        if method == "PATCH" and url_path.startswith(f"{b}/git/refs/heads/"):
            return {}
        if method == "GET" and url_path == f"{b}/pulls":
            return [self.pr] if self.pr else []
        if method == "GET" and url_path.startswith(f"{b}/contents/"):
            text = self.files[url_path.removeprefix(f"{b}/contents/")]
            return {"sha": "blob-1", "content": base64.b64encode(text.encode()).decode()}
        if method == "PUT" and url_path.startswith(f"{b}/contents/"):
            self.head = "sha-2"
            return {}
        if method == "POST" and url_path == f"{b}/pulls":
            self.pr = {"number": 7}
            return dict(self.pr)
        if method == "PATCH" and url_path == f"{b}/pulls/7":
            return {}
        if method == "GET" and url_path.startswith(f"{b}/compare/"):
            return {"behind_by": self.behind_by}
        if method == "PUT" and url_path == f"{b}/pulls/7/update-branch":
            self.behind_by = 0
            self.head = "updated-sha"
            return {}
        if method == "GET" and url_path == f"{b}/pulls/7":
            return {"number": 7, "head": {"sha": self.head}, "mergeable_state": self.state}
        if method == "POST" and url_path.endswith("/dispatches"):
            wf = url_path.split("/")[-2]
            self.runs.insert(
                0,
                {
                    "path": f".github/workflows/{wf}",
                    "created_at": v._iso(self.clock()),
                    "status": "completed",
                    "conclusion": self.conclusion,
                    "head_sha": self.head,
                },
            )
            return None
        if method == "GET" and url_path == f"{b}/actions/runs":
            sha = dict(p.split("=", 1) for p in query.split("&"))["head_sha"]
            return {"workflow_runs": [r for r in self.runs if r["head_sha"] == sha]}
        if method == "POST" and url_path == f"{b}/issues/7/comments":
            return {}
        raise AssertionError(f"llamada inesperada: {method} {path}")

    def dispatched(self) -> set[str]:
        return {r.split("/")[-2] for _m, r in self.calls if r.endswith("/dispatches")}


@pytest.fixture
def root(tmp_path):
    """Un repo de mentira con la tabla congelada: el test no depende de la del paquete."""
    v = _v()
    path = tmp_path / v.PRICES_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(PACKAGE, indent=2) + "\n", encoding="utf-8")
    limits = tmp_path / v.LIMITS_PATH
    limits.parent.mkdir(parents=True)
    limits.write_text(_expected_limits(), encoding="utf-8")
    return tmp_path


def _run(root, job, page, **options):
    v = _v()
    t = [1_790_000_000.0]
    fake = FakeGitHub(lambda: t[0], **options)
    fake.files = {
        v.PRICES_PATH: (root / v.PRICES_PATH).read_text(encoding="utf-8"),
        v.LIMITS_PATH: (root / v.LIMITS_PATH).read_text(encoding="utf-8"),
    }

    def sleep(seconds):
        t[0] += seconds

    code = v.main(
        [job],
        api=fake,
        lower=lambda _url: page,
        today=TODAY,
        sleep=sleep,
        clock=lambda: t[0],
        root=root,
        env={"GITHUB_REPOSITORY": REPO},
    )
    return code, fake


def _altered_page() -> str:
    return _change_in_row(_prices_page(), "Claude Opus 5.5", "$0.20", f"${NEW:.2f}")


def test_the_pr_is_made_through_the_api_and_launches_both_checks(root):
    code, fake = _run(root, "prices", _altered_page())
    assert code == 0
    assert ("PUT", PRICES_CONTENTS_PATH) in fake.calls
    assert ("POST", f"/repos/{REPO}/pulls") in fake.calls
    assert {"ci.yml", "codeql.yml"} <= fake.dispatched()
    # El commit lleva la tabla nueva con la fecha de hoy.
    body = fake.bodies[fake.calls.index(("PUT", PRICES_CONTENTS_PATH))]
    written = json.loads(base64.b64decode(body["content"]))
    assert body["branch"] == "vigilante/precios"
    assert written["models"]["claude-opus-5-5"]["cache_read"] == NEW
    assert written["consulted"] == TODAY.isoformat()
    # Con el PR en `clean`, no hay comentario.
    assert not any(r.endswith("/comments") for _m, r in fake.calls)


def test_without_changes_does_not_touch_github(root):
    code, fake = _run(root, "prices", _prices_page())
    assert code == 0
    assert fake.calls == []


def test_if_there_is_already_a_pr_it_updates_it(root):
    code, fake = _run(root, "prices", _altered_page(), open_pr=True)
    assert code == 0
    assert not any(m == "POST" and r.endswith("/pulls") for m, r in fake.calls)
    assert ("PATCH", f"/repos/{REPO}/pulls/7") in fake.calls
    assert ("PUT", PRICES_CONTENTS_PATH) in fake.calls


def test_if_main_moved_on_it_updates_the_branch_and_relaunches(root):
    code, fake = _run(root, "prices", _altered_page(), open_pr=True, behind_by=3)
    assert code == 0
    update = ("PUT", f"/repos/{REPO}/pulls/7/update-branch")
    assert update in fake.calls
    first_dispatch = next(i for i, (_m, r) in enumerate(fake.calls) if r.endswith("/dispatches"))
    assert fake.calls.index(update) < first_dispatch
    # Los checks se esperan sobre el head que dejó la actualización, no sobre el viejo.
    assert any("head_sha=updated-sha" in r for _m, r in fake.calls)


def test_if_it_stays_blocked_it_says_so_in_the_pr(root):
    code, fake = _run(root, "prices", _altered_page(), state="blocked")
    assert code == 0
    assert any(r.endswith("/comments") for _m, r in fake.calls)
    comment = fake.bodies[
        next(i for i, (_m, r) in enumerate(fake.calls) if r.endswith("/comments"))
    ]
    assert "reábrelo" in comment["body"]


def test_red_checks_end_in_error(root):
    code, fake = _run(root, "prices", _altered_page(), conclusion="failure")
    assert code == 1
    assert {"ci.yml", "codeql.yml"} <= fake.dispatched()


def test_a_broken_page_ends_in_error_and_not_in_no_changes(root):
    broken = _prices_page().replace(">Model pricing<", ">Pricing<")
    code, fake = _run(root, "prices", broken)
    assert code == 1
    assert fake.calls == []


def _run_dry_run(root, today, extra_env=None):
    v = _v()
    t = [1_790_000_000.0]
    fake = FakeGitHub(lambda: t[0])
    fake.files = {v.PRICES_PATH: (root / v.PRICES_PATH).read_text(encoding="utf-8")}
    code = v.main(
        ["prices"],
        api=fake,
        lower=lambda _url: _prices_page(),
        today=today,
        sleep=lambda s: t.__setitem__(0, t[0] + s),
        clock=lambda: t[0],
        root=root,
        env={"GITHUB_REPOSITORY": REPO, "WATCHER_DRY_RUN": "true", **(extra_env or {})},
    )
    return code, fake


def _written_table(fake):
    body = fake.bodies[fake.calls.index(("PUT", PRICES_CONTENTS_PATH))]
    return json.loads(base64.b64decode(body["content"]))


def test_the_dry_run_has_a_diff_even_if_checked_is_already_today(root):
    """T11: el día en que se mezcla la tabla, `consulted` ya es hoy y el ensayo abortaba.

    Mutante «el ensayo vuelve a forzar `consulted` = hoy» → `code == 1` (sin diff).
    Mutante «la marca no lleva el id del run» → falla el assert de la marca.
    """
    v = _v()
    # La tabla real del paquete, con su formato: la de `root` (indent=2) siempre daría diff al
    # reserializarla y el test no vería el fallo del run 37524585928.
    real, table = _clean_real_table()
    assert v.serialize_prices(table, real) == real, "guarda: sin cambios no hay diff"
    (root / v.PRICES_PATH).write_text(real, encoding="utf-8")
    today = dt.date.fromisoformat(table["consulted"])
    code, fake = _run_dry_run(root, today, {"GITHUB_RUN_ID": "37524585928"})
    assert code == 0
    written = _written_table(fake)
    mark = written.pop("_dry_run")
    assert "37524585928" in mark
    assert written == table  # la tabla no cambia: ni `consulted` ni ningún precio


def test_the_dry_run_overwrites_the_mark_the_table_already_has(root):
    """Run 37526624930: en la rama de ensayo `prices.json` ya trae `_dry_run` de un run anterior.

    Mutante «la marca del paquete pisa a la nueva» (`{CLAVE_ENSAYO: marca, **paquete}`, el código
    de #233) → `code == 1`: la tabla propuesta es idéntica y no hay diff.
    """
    v = _v()
    real, table = _clean_real_table()
    old = {v.DRY_RUN_KEY: v.dry_run_mark("111"), **table}
    seeded = v.serialize_prices(old, real)
    assert '"_dry_run"' in seeded and "111" in seeded, "guarda: la marca vieja está sembrada"
    (root / v.PRICES_PATH).write_text(seeded, encoding="utf-8")
    today = dt.date.fromisoformat(table["consulted"])
    code, fake = _run_dry_run(root, today, {"GITHUB_RUN_ID": "222"})
    assert code == 0, "con la marca vieja en la tabla el ensayo no tuvo diff"
    written = _written_table(fake)
    mark = written.pop(v.DRY_RUN_KEY)
    assert mark == v.dry_run_mark("222")
    assert written == table


def test_the_dry_run_forces_a_harmless_diff_on_its_branch(root):
    v = _v()
    code, fake = _run_dry_run(root, TODAY)
    assert code == 0
    pr = fake.bodies[fake.calls.index(("POST", f"/repos/{REPO}/pulls"))]
    assert pr["head"] == "vigilante/ensayo" and pr["title"].startswith("[ensayo]")
    assert "No mezclar" in pr["body"]
    assert _written_table(fake) == {"_dry_run": v.dry_run_mark(""), **PACKAGE}


def test_changed_limits_open_their_pr(root):
    v = _v()
    html = _limits_page().replace("Think of this as your", "Picture this as your", 1)
    code, fake = _run(root, "limits", html)
    assert code == 0
    path = f"/repos/{REPO}/contents/{v.LIMITS_PATH}"
    assert ("PUT", path) in fake.calls
    pr = fake.bodies[fake.calls.index(("POST", f"/repos/{REPO}/pulls"))]
    assert pr["head"] == "vigilante/limites"
    assert "recompute-cost --reset-calibration" in pr["body"]


def test_equal_limits_do_not_touch_github(root):
    code, fake = _run(root, "limits", _limits_page())
    assert code == 0
    assert fake.calls == []


# --- Workflows y script -------------------------------------------------------------------------


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    # PyYAML lee la clave `on:` como el booleano True (YAML 1.1).
    return data.get("on", data.get(True))


def test_the_workflow_has_just_what_it_needs():
    assert WORKFLOW.is_file()
    data = _yaml(WORKFLOW)
    on = _on(data)
    assert on["schedule"] and on["schedule"][0]["cron"]
    assert on["workflow_dispatch"]["inputs"]["dry_run"]["type"] == "boolean"
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert data["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "write",
    }
    assert set(data["jobs"]) == {"prices", "limits"}
    for name, job in data["jobs"].items():
        assert "permissions" not in job, name
        assert job["timeout-minutes"] == 60, name
        runs = [step["run"] for step in job["steps"] if "run" in step]
        assert runs == [f"python3 scripts/price_watcher.py {name}"]
        checkout = [p for p in job["steps"] if p.get("uses", "").startswith("actions/checkout")]
        assert checkout and checkout[0]["with"]["persist-credentials"] is False


@pytest.mark.parametrize("file", ["ci.yml", "codeql.yml"])
def test_ci_and_codeql_accept_workflow_dispatch(file):
    data = _yaml(WORKFLOWS / file)
    assert "workflow_dispatch" in _on(data)
    assert data["permissions"] == {"contents": "read"}


def _foreign_imports(source: str) -> list[str]:
    modules = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return sorted(m for m in modules if m not in sys.stdlib_module_names)


def test_the_script_is_stdlib_only():
    foreign = _foreign_imports(SCRIPT.read_text(encoding="utf-8"))
    assert foreign == []


# --- Privacidad de las copias (arreglo tras T10) -------------------------------------------------


def _cleaner():
    path = ROOT / "scripts" / "clean_watcher_fixtures.py"
    spec = importlib.util.spec_from_file_location("clean_watcher_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_copies_store_no_visit_data():
    """Las páginas guardadas no llevan el id anónimo, el de sesión, el país de la IP ni el `nonce`
    de quien las bajó: las limpia `scripts/clean_watcher_fixtures.py`."""
    cleaner = _cleaner()
    for name in ("prices.html", "limits.html"):
        assert cleaner.leftovers((FIXTURES / name).read_text(encoding="utf-8")) == [], name


# Valores SINTÉTICOS para el control positivo: se generan en cada ejecución, así que el repo no
# guarda ningún valor de una visita real (ni siquiera como control).
def _synthetic() -> dict[str, str]:
    return {
        "anonymous": str(uuid.uuid4()),
        "stable": str(uuid.uuid4()),
        "session": str(uuid.uuid4()),
        "session2": str(uuid.uuid4()),
        "nonce": secrets.token_urlsafe(16),
        "nonce2": secrets.token_urlsafe(16),
        "country": "QM",  # ISO 3166 de uso privado, distinto del neutro «ZZ»
        "country2": "XA",
        "country3": "QN",
    }


def _seeding(v: dict[str, str]) -> list[tuple[str, str]]:
    """(fragmento, valor que el guardián debe ver) en todas las formas que admite el limpiador:
    comillas dobles o simples, con o sin espacios, atributo, JSON y JSON escapado."""
    return [
        (f'"user":{{"anonymousId":"{v["anonymous"]}"}}', v["anonymous"]),
        (f"{{'stableId' : '{v['stable']}'}}", v["stable"]),
        (f'_sift.push([\\"_setSessionId\\", \\"{v["session"]}\\"])', v["session"]),
        (f'\\\\\\"sessionId\\\\\\":\\\\\\"{v["session2"]}\\\\\\"', v["session2"]),
        (f'<script nonce="{v["nonce"]}">', v["nonce"]),
        (f"<link nonce = '{v['nonce2']}'>", v["nonce2"]),
        (f'<div data-consent-ip-country="{v["country"]}">', v["country"]),
        (f'\\"ipCountry\\":\\"{v["country2"]}\\"', v["country2"]),
        (f"{{'ip_country': '{v['country3']}'}}", v["country3"]),
    ]


def test_the_guard_detects_synthetic_data_planted_in_a_copy(tmp_path):
    """Control positivo del guardián: siembra valores sintéticos en una copia temporal de cada
    página y comprueba que `leftovers()` los ve TODOS y que `clean()` (vía `main`) los quita sin
    tocar nada más."""
    cleaner = _cleaner()
    for name in ("prices.html", "limits.html"):
        v = _synthetic()
        seeding = _seeding(v)
        original = (FIXTURES / name).read_bytes().decode("utf-8")
        half = len(original) // 2
        dirty = original[:half] + " ".join(f for f, _ in seeding) + original[half:]
        copied = tmp_path / name
        copied.write_bytes(dirty.encode("utf-8"))

        assert sorted(cleaner.leftovers(dirty)) == sorted(value for _, value in seeding), name

        assert cleaner.main([str(copied)]) == 0
        clean = copied.read_bytes().decode("utf-8")
        assert cleaner.leftovers(clean) == [], name
        assert not any(value in clean for _, value in seeding if len(value) > 2), name
        # Solo cambia lo sembrado: fuera de la siembra, la página queda byte a byte igual.
        assert clean.startswith(original[:half]) and clean.endswith(original[half:]), name


def test_the_guard_does_not_depend_on_concrete_values():
    """El guardián busca formas, no valores: un valor de visita cualquiera, en cualquier clave
    vigilada, sale; el valor neutro, no."""
    cleaner = _cleaner()
    assert cleaner.leftovers(f'"anonymousId":"{cleaner.NEUTRAL_UUID}"') == []
    assert cleaner.leftovers(f'"ipCountry":"{cleaner.NEUTRAL_COUNTRY}"') == []
    assert cleaner.leftovers(f'nonce="{cleaner.NEUTRAL_NONCE}"') == []
    for _ in range(3):
        other = str(uuid.uuid4())
        assert cleaner.leftovers(f'"anonymousId":"{other}"') == [other]
