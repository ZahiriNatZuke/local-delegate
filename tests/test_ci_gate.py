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
    v = ci_gate.veredicto_de_job(_job("lint", conclusion="success"))
    assert v.estado == ci_gate.BIEN
    assert not v.fantasma


def test_skipped_job_counts_as_good():
    v = ci_gate.veredicto_de_job(_job("lint", conclusion="skipped"))
    assert v.estado == ci_gate.BIEN


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
def test_any_conclusion_that_is_not_good_fails(conclusion):
    v = ci_gate.veredicto_de_job(_job("lint", conclusion=conclusion))
    assert v.estado == ci_gate.MAL
    assert conclusion in v.motivo


def test_the_phantom_job_passes_by_its_steps():
    """El caso que motiva todo: `in_progress`, sin `completed_at`, y el runner llegó al final."""
    v = ci_gate.veredicto_de_job(
        _job("test (windows-latest)", status="in_progress", conclusion=None, steps=COMPLETE_STEPS)
    )
    assert v.estado == ci_gate.BIEN
    assert v.fantasma is True


def test_a_half_done_job_is_not_taken_as_good():
    """El contraejemplo del anterior, y el que evita el falso verde.

    Todos los pasos LISTADOS están en success, pero el último no es `Complete job`: el runner va por
    la mitad y los pasos que faltan todavía no aparecen en la API. Dar esto por bueno sería aprobar
    un job que aún puede fallar.
    """
    v = ci_gate.veredicto_de_job(
        _job(
            "test (windows-latest)",
            status="in_progress",
            steps=[_step("Set up job"), _step("Install uv")],
        )
    )
    assert v.estado == ci_gate.ESPERAR


def test_a_failed_step_wins_over_the_complete_job():
    """El orden de las comprobaciones importa: cuando un step falla, GitHub cierra el job con su
    `Complete job` en success igualmente. Mirar el fantasma primero sería un falso verde."""
    v = ci_gate.veredicto_de_job(
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
    assert v.estado == ci_gate.MAL
    assert "Tests (pytest)" in v.motivo


def test_unconcluded_steps_do_not_count_as_bad():
    v = ci_gate.veredicto_de_job(
        _job("lint", status="in_progress", steps=[_step("Set up job"), _step("Lint (ruff)", None)])
    )
    assert v.estado == ci_gate.ESPERAR


def test_a_job_without_steps_is_waited_for():
    v = ci_gate.veredicto_de_job(_job("lint", status="queued", steps=[]))
    assert v.estado == ci_gate.ESPERAR


# --- La evaluación del run entero ----------------------------------------------------------


def test_an_expected_job_missing_from_the_run_is_waited_for():
    results = ci_gate.evaluar([_job("lint", conclusion="success")])
    assert results["lint"].estado == ci_gate.BIEN
    assert results["test (windows-latest)"].estado == ci_gate.ESPERAR
    assert set(results) == set(ci_gate.JOBS_ESPERADOS)


def test_the_gate_does_not_wait_for_itself():
    assert ci_gate.NOMBRE_DEL_GATE not in ci_gate.JOBS_ESPERADOS


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
    return [_job(n, conclusion=conclusion) for n in ci_gate.JOBS_ESPERADOS]


def _run(read, clock=None):
    clock = clock or _Clock()
    output: list[str] = []
    code = ci_gate.esperar_veredicto(
        "owner/repo",
        "1",
        "token",
        leer=read,
        reloj=clock,
        dormir=clock.sleep,
        escribir=output.append,
    )
    return code, "\n".join(output)


def test_complete_run_comes_out_green():
    code, output = _run(lambda *a: _all())
    assert code == ci_gate.OK
    assert "test (windows-latest)" in output


def test_the_phantom_comes_out_green_and_is_named():
    jobs = [
        _job(n, conclusion="success")
        for n in ci_gate.JOBS_ESPERADOS
        if n != "test (windows-latest)"
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
    assert code == ci_gate.FALLO_JOB
    assert clock.t == 0.0, "no debe dormir ni una vez: el veredicto ya es definitivo"
    assert "lint" in output


def test_a_job_that_never_appears_exhausts_the_timeout_and_fails():
    jobs = [_job(n, conclusion="success") for n in ci_gate.JOBS_ESPERADOS if n != "install-smoke"]
    code, output = _run(lambda *a: jobs)
    assert code == ci_gate.FALLO_PLAZO
    assert "install-smoke" in output


def test_if_the_api_cannot_be_read_the_gate_fails():
    def read(*_):
        raise ci_gate.ApiNoDisponible("connection reset")

    code, output = _run(read)
    assert code == ci_gate.FALLO_API
    assert "connection reset" in output


def test_waits_for_the_missing_ones_and_then_passes():
    """Un job tarda en aparecer: el gate espera y termina en verde cuando llega."""
    responses = [
        [_job(n, status="queued", steps=[]) for n in ci_gate.JOBS_ESPERADOS],
        _all(),
    ]

    def read(*_):
        return responses.pop(0) if len(responses) > 1 else responses[0]

    clock = _Clock()
    code, _ = _run(read, clock)
    assert code == ci_gate.OK
    assert clock.t == ci_gate.INTERVALO_S


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
    declared = _jobs_declared_in_ci() - {ci_gate.NOMBRE_DEL_GATE}
    assert declared == set(ci_gate.JOBS_ESPERADOS)


def test_the_gate_is_declared_in_ci_yml():
    assert ci_gate.NOMBRE_DEL_GATE in _jobs_declared_in_ci()


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
