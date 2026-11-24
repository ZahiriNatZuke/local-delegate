"""Pruebas de `scripts/ci_gate.py`.

Este gate decide si un merge puede pasar, así que lo que hay que probar no es que apruebe: es que
**suspenda**. Un gate que se equivoca hacia el verde desprotege la rama entera sin que nadie lo note,
que es peor que el problema que viene a resolver.

De ahí el reparto de casos: por cada uno que da OK hay otro casi idéntico que tiene que dar FALLO o
ESPERAR — un job a medias frente al fantasma, un step fallido frente al `Complete job` en success.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"

# Mismo criterio que en `test_bump_version.py`: `scripts/` no viaja en el sdist.
if not SCRIPTS.is_dir():
    pytest.skip(
        "scripts/ no está en el árbol (sdist): estas pruebas necesitan el repositorio",
        allow_module_level=True,
    )


def _load_script():
    spec = importlib.util.spec_from_file_location("ci_gate", SCRIPTS / "ci_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci_gate = _load_script()


def _step(name: str, conclusion: str | None = "success") -> dict:
    return {"name": name, "conclusion": conclusion}


def _job(
    name: str,
    *,
    status: str = "completed",
    conclusion: str | None = None,
    steps=(),
    runner: str | None = "GitHub Actions 1000027327",
) -> dict:
    """Un job como lo devuelve la API. Por defecto con runner asignado, como casi todos."""
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "steps": list(steps),
        "runner_id": 1000027327 if runner else None,
        "runner_name": runner,
    }


COMPLETE_STEPS = [
    _step("Set up job"),
    _step("Run actions/checkout@v7"),
    _step("Tests (pytest)"),
    _step("Complete job"),
]


# --- El veredicto por job ------------------------------------------------------------------


def test_job_finished_in_success_is_good():
    v = ci_gate.job_verdict(_job("lint", conclusion="success"))
    assert v.state == ci_gate.GOOD
    assert not v.phantom


def test_skipped_job_counts_as_good():
    v = ci_gate.job_verdict(_job("lint", conclusion="skipped"))
    assert v.state == ci_gate.GOOD


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
def test_any_conclusion_that_is_not_good_fails(conclusion):
    v = ci_gate.job_verdict(_job("lint", conclusion=conclusion))
    assert v.state == ci_gate.BAD
    assert conclusion in v.reason


# --- REQ-001 (SDD ci-root-cause): el job al que GitHub no le dio máquina -------------------
#
# Del 2026-11-03 al 2026-11-23, 71 jobs de macOS salieron `cancelled` sin runner y sin pasos: 31 de
# los 90 rojos del gate. Cada caso que da OK tiene al lado su control casi idéntico que da FALLO.


def test_a_cancelled_job_that_never_got_a_runner_is_good_with_a_warning():
    v = ci_gate.job_verdict(_job("test (macos-latest)", conclusion="cancelled", runner=None))
    assert v.state == ci_gate.GOOD
    assert v.no_runner
    assert "sin runner" in v.reason


def test_the_api_empty_string_and_zero_also_mean_no_runner():
    """La API devuelve a veces `runner_name: ""` y `runner_id: 0` en vez de `null`."""
    job = _job("plugin (macos-latest)", conclusion="cancelled", runner=None)
    job.update(runner_id=0, runner_name="")
    assert ci_gate.job_verdict(job).state == ci_gate.GOOD


def test_control_a_cancelled_job_with_a_runner_still_fails():
    """Hubo máquina, aunque no llegara a dar pasos: ya no es la infraestructura."""
    v = ci_gate.job_verdict(_job("test (macos-latest)", conclusion="cancelled"))
    assert v.state == ci_gate.BAD
    assert not v.no_runner


def test_control_a_cancelled_job_with_an_executed_step_still_fails():
    """Sin runner en la respuesta pero con un paso ejecutado: algo corrió, y se canceló."""
    steps = [_step("Set up job"), _step("Tests (pytest)", "cancelled")]
    v = ci_gate.job_verdict(
        _job("test (macos-latest)", conclusion="cancelled", steps=steps, runner=None)
    )
    assert v.state == ci_gate.BAD


def test_skipped_or_pending_steps_are_not_executed_steps():
    steps = [_step("Set up job", None), _step("Tests (pytest)", "skipped")]
    v = ci_gate.job_verdict(
        _job("test (macos-latest)", conclusion="cancelled", steps=steps, runner=None)
    )
    assert v.state == ci_gate.GOOD


@pytest.mark.parametrize("conclusion", ["timed_out", "failure"])
def test_control_without_a_runner_only_cancelled_is_forgiven(conclusion):
    v = ci_gate.job_verdict(_job("test (macos-latest)", conclusion=conclusion, runner=None))
    assert v.state == ci_gate.BAD


@pytest.mark.parametrize("name", ["test (ubuntu-latest)", "test (windows-latest)", "perf", "lint"])
def test_control_only_macos_is_forgiven_a_cancel_without_runner(name):
    """Ubuntu and Windows carry the suite: cancelled there without a machine, nothing was tested."""
    v = ci_gate.job_verdict(_job(name, conclusion="cancelled", runner=None))
    assert v.state == ci_gate.BAD


def test_the_phantom_job_passes_by_its_steps():
    """El caso que motiva todo: `in_progress`, sin `completed_at`, y el runner llegó al final."""
    v = ci_gate.job_verdict(
        _job("test (windows-latest)", status="in_progress", conclusion=None, steps=COMPLETE_STEPS)
    )
    assert v.state == ci_gate.GOOD
    assert v.phantom is True


def test_a_half_done_job_is_not_taken_as_good():
    """El contraejemplo del anterior, y el que evita el falso verde.

    Todos los pasos LISTADOS están en success, pero el último no es `Complete job`: el runner va por
    la mitad y los pasos que faltan todavía no aparecen en la API. Dar esto por bueno sería aprobar
    un job que aún puede fallar.
    """
    v = ci_gate.job_verdict(
        _job(
            "test (windows-latest)",
            status="in_progress",
            steps=[_step("Set up job"), _step("Install uv")],
        )
    )
    assert v.state == ci_gate.WAIT


def test_a_failed_step_wins_over_the_complete_job():
    """El orden de las comprobaciones importa: cuando un step falla, GitHub cierra el job con su
    `Complete job` en success igualmente. Mirar el fantasma primero sería un falso verde."""
    v = ci_gate.job_verdict(
        _job(
            "test (ubuntu-latest)",
            status="in_progress",
            steps=[
                _step("Set up job"),
                _step("Tests (pytest)", "failure"),
                _step("Complete job"),
            ],
        )
    )
    assert v.state == ci_gate.BAD
    assert "Tests (pytest)" in v.reason


def test_unconcluded_steps_do_not_count_as_bad():
    v = ci_gate.job_verdict(
        _job("lint", status="in_progress", steps=[_step("Set up job"), _step("Lint (ruff)", None)])
    )
    assert v.state == ci_gate.WAIT


def test_a_job_without_steps_is_waited_for():
    v = ci_gate.job_verdict(_job("lint", status="queued", steps=[]))
    assert v.state == ci_gate.WAIT


# --- La evaluación del run entero ----------------------------------------------------------


def test_an_expected_job_missing_from_the_run_is_waited_for():
    results = ci_gate.evaluate([_job("lint", conclusion="success")])
    assert results["lint"].state == ci_gate.GOOD
    assert results["test (windows-latest)"].state == ci_gate.WAIT
    assert set(results) == set(ci_gate.EXPECTED_JOBS)


def test_the_gate_does_not_wait_for_itself():
    assert ci_gate.GATE_NAME not in ci_gate.EXPECTED_JOBS


# --- El bucle de espera --------------------------------------------------------------------


class _Clock:
    """Reloj falso: solo avanza cuando el bucle duerme."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _all(conclusion: str = "success") -> list[dict]:
    return [_job(n, conclusion=conclusion) for n in ci_gate.EXPECTED_JOBS]


def _run(read, clock=None):
    clock = clock or _Clock()
    output: list[str] = []
    code = ci_gate.wait_for_verdict(
        "owner/repo",
        "1",
        "token",
        read=read,
        clock=clock,
        sleep=clock.sleep,
        write=output.append,
    )
    return code, "\n".join(output)


def test_complete_run_comes_out_green():
    code, output = _run(lambda *a: _all())
    assert code == ci_gate.OK
    assert "test (windows-latest)" in output


def test_the_phantom_comes_out_green_and_is_named():
    jobs = [
        _job(n, conclusion="success") for n in ci_gate.EXPECTED_JOBS if n != "test (windows-latest)"
    ]
    jobs.append(
        _job("test (windows-latest)", status="in_progress", conclusion=None, steps=COMPLETE_STEPS)
    )
    code, output = _run(lambda *a: jobs)
    assert code == ci_gate.OK
    assert "job fantasma" in output
    assert "test (windows-latest)" in output


def test_a_run_with_macos_never_started_is_green_and_names_it(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    jobs = [_job(n, conclusion="success") for n in ci_gate.EXPECTED_JOBS if "macos" not in n]
    jobs += [
        _job(n, conclusion="cancelled", runner=None) for n in ci_gate.EXPECTED_JOBS if "macos" in n
    ]
    code, output = _run(lambda *a: jobs)
    assert code == ci_gate.OK
    assert "::warning::test (macos-latest): cancelado sin runner" in output
    assert "plugin (macos-latest)" in output.split("Jobs cancelados sin runner")[1]
    assert "Cancelado sin runner" in summary.read_text(encoding="utf-8")


def test_control_the_same_run_with_macos_cancelled_after_starting_fails():
    jobs = [_job(n, conclusion="success") for n in ci_gate.EXPECTED_JOBS if "macos" not in n]
    jobs += [
        _job(n, conclusion="cancelled", steps=[_step("Set up job")])
        for n in ci_gate.EXPECTED_JOBS
        if "macos" in n
    ]
    code, _ = _run(lambda *a: jobs)
    assert code == ci_gate.JOB_FAILURE


def test_a_failure_cuts_without_waiting_for_the_rest():
    jobs = [_job("lint", conclusion="failure")]  # los demás ni aparecen
    clock = _Clock()
    code, output = _run(lambda *a: jobs, clock)
    assert code == ci_gate.JOB_FAILURE
    assert clock.t == 0.0, "no debe dormir ni una vez: el veredicto ya es definitivo"
    assert "lint" in output


def test_the_job_summary_prints_each_state_in_spanish(tmp_path, monkeypatch):
    """El estado es interno (`good`/`bad`/`wait`); el resumen del job lo imprime con su rótulo, que
    sigue en español hasta el frente B (cierre del frente A, lote 5).
    Control: escribir `v.state` tal cual → sale `**good**` y este test falla."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    results = {
        "lint": ci_gate.Verdict(ci_gate.GOOD, "terminó"),
        "tests": ci_gate.Verdict(ci_gate.BAD, "falló"),
        "install-smoke": ci_gate.Verdict(ci_gate.WAIT, "todavía no aparece en el run"),
    }
    ci_gate._report("Gate", results, lambda _line: None)
    text = summary.read_text(encoding="utf-8")
    assert "- `lint`: **bien** — terminó" in text
    assert "- `tests`: **mal** — falló" in text
    assert "- `install-smoke`: **esperar** — todavía no aparece en el run" in text


def test_a_job_that_never_appears_exhausts_the_timeout_and_fails():
    jobs = [_job(n, conclusion="success") for n in ci_gate.EXPECTED_JOBS if n != "install-smoke"]
    code, output = _run(lambda *a: jobs)
    assert code == ci_gate.TIMEOUT_FAILURE
    assert "install-smoke" in output


def test_if_the_api_cannot_be_read_the_gate_fails():
    def read(*_):
        raise ci_gate.ApiUnavailable("connection reset")

    code, output = _run(read)
    assert code == ci_gate.API_FAILURE
    assert "connection reset" in output


def test_waits_for_the_missing_ones_and_then_passes():
    """Un job tarda en aparecer: el gate espera y termina en verde cuando llega."""
    responses = [
        [_job(n, status="queued", steps=[]) for n in ci_gate.EXPECTED_JOBS],
        _all(),
    ]

    def read(*_):
        return responses.pop(0) if len(responses) > 1 else responses[0]

    clock = _Clock()
    code, _ = _run(read, clock)
    assert code == ci_gate.OK
    assert clock.t == ci_gate.INTERVAL_S


# --- REQ-004: la lista de esperados no puede ser una segunda fuente de verdad ---------------


def _jobs_declared_in_ci() -> set[str]:
    """Los nombres de check que publica `ci.yml`, con la matriz expandida.

    Falla ruidosamente ante una matriz que no sepa expandir: un parser que calla convertiría el test
    de conjuntos en decoración, que es justo lo que no queremos aquí.
    """
    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    names: set[str] = set()

    for job_id, job in data["jobs"].items():
        base = job.get("name", job_id)
        matrix = (job.get("strategy") or {}).get("matrix")

        if not matrix:
            names.add(base)
            continue

        keys = [k for k in matrix if k not in ("include", "exclude")]
        if "include" in matrix or "exclude" in matrix or len(keys) != 1:
            raise AssertionError(
                f"el job '{job_id}' usa una matriz que este parser no sabe expandir "
                f"({sorted(matrix)}). Actualiza el parser antes de confiar en este test."
            )

        for value in matrix[keys[0]]:
            names.add(f"{base} ({value})")

    return names


def test_the_expected_jobs_are_exactly_those_of_ci_yml():
    """Por conjuntos IGUALES, no por inclusión.

    Mismo patrón que ata la tabla de tools de `SKILL.md` a `list_tools()`: con inclusión, añadir un
    job a `ci.yml` y olvidarlo aquí pasaría desapercibido, y el gate aprobaría un run sin haberlo
    mirado.
    """
    declared = _jobs_declared_in_ci() - {ci_gate.GATE_NAME}
    assert declared == set(ci_gate.EXPECTED_JOBS)


def test_the_plugin_job_is_required_on_every_os():
    """REQ-001 (SDD claude-plugin-and-mods, F1-package): `validate --strict`, the wheel with the
    plugin and the install in an empty `CLAUDE_CONFIG_DIR` block the merge on the three systems.
    Required, not optional: a plugin that only fails on macOS fails for the Mac."""
    for os_name in ("ubuntu-latest", "windows-latest", "macos-latest"):
        assert f"plugin ({os_name})" in ci_gate.EXPECTED_JOBS


def test_the_cli_matrix_starts_at_the_oldest_supported_python():
    """La matriz cubre desde el `requires-python` del paquete (D8)."""
    import tomllib

    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    versions = data["jobs"]["cli-python-matrix"]["strategy"]["matrix"]["python"]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    oldest = pyproject["project"]["requires-python"].removeprefix(">=")
    assert versions[0] == oldest
    assert versions == sorted(versions, key=lambda v: tuple(int(p) for p in v.split(".")))


def test_the_gate_is_declared_in_ci_yml():
    assert ci_gate.GATE_NAME in _jobs_declared_in_ci()


# --- Los números del cuelgue de Windows, atados a lo que declara `ci.yml` --------------------
#
# Estos dos tests existen porque el comentario de `ci.yml` sostuvo durante días un diagnóstico
# falso —«`timeout-minutes` no dispara»— y nadie podía verlo: un comentario no falla nunca. El
# 2026-07-31 se midió que sí dispara y que la firma del cuelgue son 13 minutos (8 del límite + 5
# de gracia de GitHub). Si alguien cambia el límite, el texto que explica el 13 se queda viejo, y
# eso es lo que se impide aquí.
#
# El 2026-10-13 el límite subió a 15 (la suite tardaba ~5 min en Windows y el paso de 5 cortaba
# corridas sin ningún test fallido): la firma pasa a 20:00. El 2026-11-23 (SDD ci-root-cause) el
# paso en serie de `real_io` lo sube a 25 (la suma de los límites de sus pasos es 24): la firma
# pasa a 30:00.

TIMEOUT_JOB_TEST = 25
GITHUB_GRACE = 5


def _job_test() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]["test"]


def test_the_tests_job_limit_is_the_one_explaining_the_hang_signature():
    """El `30:00` que se lee en un `cancelled` no es magia: es este número más la gracia.

    Se ata porque la conclusión operativa depende de él — «un cancelled de 13:00 en main es el
    cuelgue conocido y no una avería»— y esa frase deja de ser cierta si el límite cambia.
    """
    assert _job_test()["timeout-minutes"] == TIMEOUT_JOB_TEST

    signature = TIMEOUT_JOB_TEST + GITHUB_GRACE
    text = CI_YML.read_text(encoding="utf-8")
    assert f"{signature}:00" in text, (
        f"el comentario de ci.yml debe explicar la firma de {signature}:00 "
        f"({TIMEOUT_JOB_TEST} de límite + {GITHUB_GRACE} de gracia)"
    )


def test_the_tests_step_has_its_own_limit_lower_than_the_jobs():
    """Cubre el cuelgue de **pytest**, distinto del cuelgue del runner.

    En dos de los tres `cancelled` medidos, `Tests (pytest)` seguía `in_progress` al morir el job.
    Un límite de paso corta eso pronto y con log; si fuera mayor o igual que el del job, no
    llegaría a actuar nunca y sería decoración.
    """
    steps = _job_test()["steps"]
    tests = [p for p in steps if p.get("name") == "Tests (pytest)"]
    assert tests, "el job `test` ya no tiene un paso llamado 'Tests (pytest)'"

    limit = tests[0].get("timeout-minutes")
    assert limit is not None, "el paso de tests perdió su `timeout-minutes`"
    assert limit < TIMEOUT_JOB_TEST, (
        f"el límite del paso ({limit}) tiene que ser menor que el del job "
        f"({TIMEOUT_JOB_TEST}) para llegar a actuar"
    )


def test_the_tests_job_limit_covers_the_limits_of_its_steps():
    """Sin esto, un paso lento lo corta el job (sin log, con la firma del cuelgue) y no su límite.

    Revisión del PR #730: el job tenía 20 min y sus pasos con límite sumaban 24.
    """
    steps = _job_test()["steps"]
    total = sum(step.get("timeout-minutes", 0) for step in steps)
    assert total + 1 <= TIMEOUT_JOB_TEST, (
        f"los pasos suman {total} min y el job tiene {TIMEOUT_JOB_TEST}: "
        "queda sin margen para checkout, uv y sync"
    )


def test_the_lint_job_limit_leaves_room_for_the_browser_steps():
    """El job `lint` no puede quedarse sin tiempo antes que sus propios pasos del navegador.

    El 2026-10-27 el job tenía 5 minutos: una instalación lenta del navegador (3 min) se comió el
    tiempo de los tests del panel y `lint` salió `cancelled` en main sin ningún fallo de código.
    Cada paso del navegador declara su límite, y el job debe superar su suma con margen para el
    resto de pasos (checkout, uv, ruff, Node), que en verde tardan ~20 s.
    """
    job = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]["lint"]
    names = (
        "Install the browser system dependencies",
        "Install browser for the dashboard UI tests",
        "Dashboard UI (Playwright)",
    )
    limits = {p["name"]: p.get("timeout-minutes") for p in job["steps"] if p.get("name") in names}
    assert set(limits) == set(names), f"faltan pasos del navegador en `lint`: {limits}"
    assert all(v is not None for v in limits.values()), f"paso sin `timeout-minutes`: {limits}"

    margin = 2
    assert job["timeout-minutes"] >= sum(limits.values()) + margin, (
        f"el límite de `lint` ({job['timeout-minutes']}) debe ser al menos la suma de sus pasos "
        f"del navegador ({sum(limits.values())}) más {margin} de margen"
    )


BROWSER_JOBS = ("lint", "test-lang-es")


def _steps(job: str) -> list[dict]:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"][job]["steps"]


@pytest.mark.parametrize("job", BROWSER_JOBS)
def test_the_browser_is_cached_and_system_packages_are_retried(job):
    """Un mirror de apt lento no deja main en rojo sin cambio de código (2026-11-11).

    Ese día `lint` agotó los 5 min del `playwright install --with-deps` y `test-lang-es` salió con
    `exited with code: 100` de apt. Desde entonces: las dependencias del sistema van por el script
    con reintentos, el navegador sale de `actions/cache` con una clave atada a la versión exacta de
    playwright, y solo se descarga cuando la caché falla.
    """
    steps = _steps(job)
    runs = [s.get("run", "") for s in steps]
    assert not any("--with-deps" in r for r in runs), "vuelve a instalar apt y navegador de una vez"

    by_id = {s["id"]: s for s in steps if "id" in s}
    cache = by_id.get("browser-cache")
    assert cache is not None, f"`{job}` sin paso de caché del navegador"
    assert cache["uses"].startswith("actions/cache@")
    assert cache["with"]["path"] == "~/.cache/ms-playwright"
    key = cache["with"]["key"]
    for part in ("runner.os", "steps.playwright.outputs.version", "steps.playwright.outputs.image"):
        assert part in key, f"la clave de la caché no incluye {part}: {key}"
    assert 'm.version("playwright")' in by_id["playwright"]["run"]

    names = [s.get("name") for s in steps]
    packages = steps[names.index("Install the browser system dependencies")]
    browser = steps[names.index("Install browser for the dashboard UI tests")]
    assert packages["run"].strip() == "bash scripts/ci_playwright_system_packages.sh"
    assert "if" not in packages, (
        "las dependencias del sistema no van en la caché: se instalan siempre"
    )
    assert browser["if"] == "steps.browser-cache.outputs.cache-hit != 'true'"
    assert (
        browser["run"].strip() == "bash scripts/ci_retry.sh 3 60 uv run playwright install chromium"
    )
    assert packages.get("timeout-minutes") and browser.get("timeout-minutes")
    # Orden: versión, caché, navegador y al final las librerías del sistema, porque el script
    # arranca Chromium para saber si hace falta apt.
    order = [
        names.index(n)
        for n in (
            "Resolve the Playwright version",
            "Cache the Playwright browser",
            "Install browser for the dashboard UI tests",
            "Install the browser system dependencies",
        )
    ]
    assert order == sorted(order)


def test_the_system_package_retry_is_bounded_and_fits_its_step():
    """El script reintenta un número acotado de veces y su peor caso cabe en el tope del paso."""
    text = (SCRIPTS / "ci_playwright_system_packages.sh").read_text(encoding="utf-8")
    assert '"$venv_bin/playwright" install-deps chromium' in text
    # apt solo si Chromium no arranca con lo que trae la imagen (caída de DNS del 2026-11-11).
    assert text.index("if chromium_launches; then") < text.index("for ((i = 1;")
    # El tope corre como root: si no, el `apt-get` de `install-deps` sobrevive y deja el lock.
    assert "sudo timeout --kill-after=15" in text and "sudo pkill -x apt-get" in text
    assert "PLAYWRIGHT_INSTALL_ATTEMPTS:-3" in text and "PLAYWRIGHT_INSTALL_TIMEOUT:-120" in text
    assert "sleep $((15 * i))" in text
    attempts, per_attempt, kill_after = 3, 120, 15
    worst_s = attempts * (per_attempt + kill_after) + sum(15 * i for i in range(1, attempts))
    for job in BROWSER_JOBS:
        step = next(
            s for s in _steps(job) if s.get("name") == "Install the browser system dependencies"
        )
        assert step["timeout-minutes"] * 60 > worst_s, (job, step["timeout-minutes"], worst_s)


def test_the_spanish_job_fits_the_gate_wait():
    """`test-lang-es` cabe con margen en la espera de `ci_gate.py` aun con sus pasos al tope."""
    job = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]["test-lang-es"]
    limited = sum(s.get("timeout-minutes", 0) for s in job["steps"])
    assert job["timeout-minutes"] >= limited + 2
    assert job["timeout-minutes"] * 60 < ci_gate.MAX_WAIT_S


def test_the_classifiers_are_the_blocking_cells_of_the_matrix():
    """`pyproject.toml` declara justo las versiones de la matriz del CLI, que bloquean todas (D8)."""
    import tomllib

    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    versions = data["jobs"]["cli-python-matrix"]["strategy"]["matrix"]["python"]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    prefix = "Programming Language :: Python :: 3."
    declared = {
        c.removeprefix("Programming Language :: Python :: ")
        for c in pyproject["project"]["classifiers"]
        if c.startswith(prefix)
    }
    assert declared == set(versions)


# --- SDD ci-root-cause: el reparto de la suite y los reintentos -----------------------------


def _jobs() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]


@pytest.mark.parametrize(
    ("job", "step"),
    [("test", "Tests (pytest)"), ("test-lang-es", "Tests (pytest, LANG=es_ES.UTF-8)")],
)
def test_the_parallel_step_leaves_out_perf_and_real_io(job, step):
    """REQ-002: nada que compare un reloj con un tope corre bajo `-n auto`."""
    run = next(s for s in _jobs()[job]["steps"] if s.get("name") == step)["run"]
    assert "-n auto" in run
    assert '-m "not perf and not real_io"' in run


@pytest.mark.parametrize("job", ["test", "test-lang-es"])
def test_real_io_runs_after_the_parallel_step_in_series_with_a_retry(job):
    """REQ-002 y REQ-006: en los tres sistemas (y en español), en serie y con un reintento. Sin
    `COMPLETION_TEST_REQUIRE_SHELLS`: esa sesión no tiene tests de shell, y la guarda de
    `tests/conftest.py` la daría por fallida."""
    steps = _jobs()[job]["steps"]
    names = [s.get("name", "") for s in steps]
    real_io = [i for i, n in enumerate(names) if n.startswith("Tests with real I/O")]
    parallel = [i for i, n in enumerate(names) if n.startswith("Tests (pytest")]
    assert len(real_io) == 1 and len(parallel) == 1
    step = steps[real_io[0]]
    assert real_io[0] > parallel[0]
    assert step["run"].strip() == "bash scripts/ci_pytest_retry.sh -m real_io"
    if job == "test":  # the matrix includes Windows: Git Bash, not whatever `pwsh` finds
        assert step["shell"] == "bash"
    assert "env" not in step
    assert step.get("timeout-minutes")


def test_the_perf_job_runs_alone_on_ubuntu_and_blocks():
    """REQ-002: un job propio, sin `-n`, con un reintento, y exigido por el gate."""
    job = _jobs()["perf"]
    assert job["runs-on"].startswith("ubuntu-")
    assert "strategy" not in job
    runs = [s.get("run", "") for s in job["steps"]]
    assert "bash scripts/ci_pytest_retry.sh -m perf" in runs
    assert not any(" -n " in r for r in runs)
    assert "perf" in ci_gate.EXPECTED_JOBS
    limited = sum(s.get("timeout-minutes", 0) for s in job["steps"])
    assert job["timeout-minutes"] >= limited + 2


def test_the_pytest_retry_reruns_only_the_failures_and_only_once():
    text = (SCRIPTS / "ci_pytest_retry.sh").read_text(encoding="utf-8")
    assert text.count("uv run pytest") == 2
    assert "--last-failed --last-failed-no-failures none" in text
    # 5 (nothing selected) and the other non-test exits are final: no retry hides them
    assert "if ((status != 1)); then" in text
    assert " -n " not in text


def test_the_shell_scripts_of_the_ci_are_checked_out_with_lf():
    """Windows checks out with `core.autocrlf=true`: a CRLF `.sh` breaks bash on its first line."""
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "*.sh text eol=lf" in attributes


def test_the_browser_download_retry_is_bounded_and_fits_its_step():
    """REQ-009: 3 intentos de 60 s, pausas de 10 y 20 s, y el peor caso cabe en el paso."""
    text = (SCRIPTS / "ci_retry.sh").read_text(encoding="utf-8")
    assert 'timeout --kill-after=10 "${per_attempt}" "$@"' in text
    assert "sleep $((10 * i))" in text
    attempts, per_attempt, kill_after = 3, 60, 10
    worst_s = attempts * (per_attempt + kill_after) + sum(10 * i for i in range(1, attempts))
    for job in BROWSER_JOBS:
        step = next(
            s for s in _steps(job) if s.get("name") == "Install browser for the dashboard UI tests"
        )
        assert step["run"].split()[2:4] == [str(attempts), str(per_attempt)]
        assert step["timeout-minutes"] * 60 > worst_s, (job, step["timeout-minutes"], worst_s)


def test_every_job_fits_the_gate_wait():
    """El gate espera cola + ejecución: ningún job puede durar más que su plazo."""
    for name, job in _jobs().items():
        if name == ci_gate.GATE_NAME:
            continue
        assert job["timeout-minutes"] * 60 < ci_gate.MAX_WAIT_S, name
    assert _jobs()[ci_gate.GATE_NAME]["timeout-minutes"] * 60 > ci_gate.MAX_WAIT_S
