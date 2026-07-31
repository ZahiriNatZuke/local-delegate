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


def _step(nombre: str, conclusion: str | None = "success") -> dict:
    return {"name": nombre, "conclusion": conclusion}


def _job(
    nombre: str, *, status: str = "completed", conclusion: str | None = None, steps=()
) -> dict:
    return {"name": nombre, "status": status, "conclusion": conclusion, "steps": list(steps)}


PASOS_COMPLETOS = [
    _step("Set up job"),
    _step("Run actions/checkout@v7"),
    _step("Tests (pytest)"),
    _step("Complete job"),
]


# --- El veredicto por job ------------------------------------------------------------------


def test_job_terminado_en_success_es_bueno():
    v = ci_gate.veredicto_de_job(_job("lint", conclusion="success"))
    assert v.estado == ci_gate.BIEN
    assert not v.fantasma


def test_job_saltado_cuenta_como_bueno():
    v = ci_gate.veredicto_de_job(_job("lint", conclusion="skipped"))
    assert v.estado == ci_gate.BIEN


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
def test_cualquier_conclusion_que_no_sea_buena_suspende(conclusion):
    v = ci_gate.veredicto_de_job(_job("lint", conclusion=conclusion))
    assert v.estado == ci_gate.MAL
    assert conclusion in v.motivo


def test_el_job_fantasma_pasa_por_sus_pasos():
    """El caso que motiva todo: `in_progress`, sin `completed_at`, y el runner llegó al final."""
    v = ci_gate.veredicto_de_job(
        _job("test (windows-latest)", status="in_progress", conclusion=None, steps=PASOS_COMPLETOS)
    )
    assert v.estado == ci_gate.BIEN
    assert v.fantasma is True


def test_un_job_a_medias_no_se_da_por_bueno():
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


def test_un_paso_fallido_manda_sobre_el_complete_job():
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


def test_pasos_sin_concluir_no_cuentan_como_malos():
    v = ci_gate.veredicto_de_job(
        _job("lint", status="in_progress", steps=[_step("Set up job"), _step("Lint (ruff)", None)])
    )
    assert v.estado == ci_gate.ESPERAR


def test_un_job_sin_pasos_se_espera():
    v = ci_gate.veredicto_de_job(_job("lint", status="queued", steps=[]))
    assert v.estado == ci_gate.ESPERAR


# --- La evaluación del run entero ----------------------------------------------------------


def test_un_job_esperado_que_no_esta_en_el_run_se_espera():
    resultados = ci_gate.evaluar([_job("lint", conclusion="success")])
    assert resultados["lint"].estado == ci_gate.BIEN
    assert resultados["test (windows-latest)"].estado == ci_gate.ESPERAR
    assert set(resultados) == set(ci_gate.JOBS_ESPERADOS)


def test_el_gate_no_se_espera_a_si_mismo():
    assert ci_gate.NOMBRE_DEL_GATE not in ci_gate.JOBS_ESPERADOS


# --- El bucle de espera --------------------------------------------------------------------


class _Reloj:
    """Reloj falso: solo avanza cuando el bucle duerme."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def dormir(self, segundos: float) -> None:
        self.t += segundos


def _todos(conclusion: str = "success") -> list[dict]:
    return [_job(n, conclusion=conclusion) for n in ci_gate.JOBS_ESPERADOS]


def _correr(leer, reloj=None):
    reloj = reloj or _Reloj()
    salida: list[str] = []
    codigo = ci_gate.esperar_veredicto(
        "owner/repo",
        "1",
        "token",
        leer=leer,
        reloj=reloj,
        dormir=reloj.dormir,
        escribir=salida.append,
    )
    return codigo, "\n".join(salida)


def test_run_completo_sale_en_verde():
    codigo, salida = _correr(lambda *a: _todos())
    assert codigo == ci_gate.OK
    assert "test (windows-latest)" in salida


def test_el_fantasma_sale_en_verde_y_queda_nombrado():
    jobs = [
        _job(n, conclusion="success")
        for n in ci_gate.JOBS_ESPERADOS
        if n != "test (windows-latest)"
    ]
    jobs.append(
        _job("test (windows-latest)", status="in_progress", conclusion=None, steps=PASOS_COMPLETOS)
    )
    codigo, salida = _correr(lambda *a: jobs)
    assert codigo == ci_gate.OK
    assert "job fantasma" in salida
    assert "test (windows-latest)" in salida


def test_un_fallo_corta_sin_esperar_al_resto():
    jobs = [_job("lint", conclusion="failure")]  # los demás ni aparecen
    reloj = _Reloj()
    codigo, salida = _correr(lambda *a: jobs, reloj)
    assert codigo == ci_gate.FALLO_JOB
    assert reloj.t == 0.0, "no debe dormir ni una vez: el veredicto ya es definitivo"
    assert "lint" in salida


def test_un_job_que_nunca_aparece_agota_el_plazo_y_suspende():
    jobs = [_job(n, conclusion="success") for n in ci_gate.JOBS_ESPERADOS if n != "install-smoke"]
    codigo, salida = _correr(lambda *a: jobs)
    assert codigo == ci_gate.FALLO_PLAZO
    assert "install-smoke" in salida


def test_si_la_api_no_se_puede_leer_el_gate_suspende():
    def leer(*_):
        raise ci_gate.ApiNoDisponible("connection reset")

    codigo, salida = _correr(leer)
    assert codigo == ci_gate.FALLO_API
    assert "connection reset" in salida


def test_espera_a_los_que_faltan_y_luego_aprueba():
    """Un job tarda en aparecer: el gate espera y termina en verde cuando llega."""
    respuestas = [
        [_job(n, status="queued", steps=[]) for n in ci_gate.JOBS_ESPERADOS],
        _todos(),
    ]

    def leer(*_):
        return respuestas.pop(0) if len(respuestas) > 1 else respuestas[0]

    reloj = _Reloj()
    codigo, _ = _correr(leer, reloj)
    assert codigo == ci_gate.OK
    assert reloj.t == ci_gate.INTERVALO_S


# --- REQ-004: la lista de esperados no puede ser una segunda fuente de verdad ---------------


def _jobs_declarados_en_ci() -> set[str]:
    """Los nombres de check que publica `ci.yml`, con la matriz expandida.

    Falla ruidosamente ante una matriz que no sepa expandir: un parser que calla convertiría el test
    de conjuntos en decoración, que es justo lo que no queremos aquí.
    """
    datos = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    nombres: set[str] = set()

    for job_id, job in datos["jobs"].items():
        base = job.get("name", job_id)
        matriz = (job.get("strategy") or {}).get("matrix")

        if not matriz:
            nombres.add(base)
            continue

        claves = [k for k in matriz if k not in ("include", "exclude")]
        if "include" in matriz or "exclude" in matriz or len(claves) != 1:
            raise AssertionError(
                f"el job '{job_id}' usa una matriz que este parser no sabe expandir "
                f"({sorted(matriz)}). Actualiza el parser antes de confiar en este test."
            )

        for valor in matriz[claves[0]]:
            nombres.add(f"{base} ({valor})")

    return nombres


def test_los_jobs_esperados_son_exactamente_los_de_ci_yml():
    """Por conjuntos IGUALES, no por inclusión.

    Mismo patrón que ata la tabla de tools de `SKILL.md` a `list_tools()`: con inclusión, añadir un
    job a `ci.yml` y olvidarlo aquí pasaría desapercibido, y el gate aprobaría un run sin haberlo
    mirado.
    """
    declarados = _jobs_declarados_en_ci() - {ci_gate.NOMBRE_DEL_GATE}
    assert declarados == set(ci_gate.JOBS_ESPERADOS)


def test_el_gate_esta_declarado_en_ci_yml():
    assert ci_gate.NOMBRE_DEL_GATE in _jobs_declarados_en_ci()
