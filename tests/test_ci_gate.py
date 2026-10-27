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


def _job(name: str, *, status: str = "completed", conclusion: str | None = None, steps=()) -> dict:
    return {"name": name, "status": status, "conclusion": conclusion, "steps": list(steps)}


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
# corridas sin ningún test fallido): la firma pasa a 20:00.

TIMEOUT_JOB_TEST = 15
GITHUB_GRACE = 5


def _job_test() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]["test"]


def test_the_tests_job_limit_is_the_one_explaining_the_hang_signature():
    """El `20:00` que se lee en un `cancelled` no es magia: es este número más la gracia.

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


def test_the_lint_job_limit_leaves_room_for_the_browser_steps():
    """El job `lint` no puede quedarse sin tiempo antes que sus propios pasos del navegador.

    El 2026-10-27 el job tenía 5 minutos: una instalación lenta del navegador (3 min) se comió el
    tiempo de los tests del panel y `lint` salió `cancelled` en main sin ningún fallo de código.
    Cada paso del navegador declara su límite, y el job debe superar su suma con margen para el
    resto de pasos (checkout, uv, ruff, Node), que en verde tardan ~20 s.
    """
    job = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]["lint"]
    names = ("Install browser for the dashboard UI tests", "Dashboard UI (Playwright)")
    limits = {p["name"]: p.get("timeout-minutes") for p in job["steps"] if p.get("name") in names}
    assert set(limits) == set(names), f"faltan pasos del navegador en `lint`: {limits}"
    assert all(v is not None for v in limits.values()), f"paso sin `timeout-minutes`: {limits}"

    margin = 2
    assert job["timeout-minutes"] >= sum(limits.values()) + margin, (
        f"el límite de `lint` ({job['timeout-minutes']}) debe ser al menos la suma de sus pasos "
        f"del navegador ({sum(limits.values())}) más {margin} de margen"
    )


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
