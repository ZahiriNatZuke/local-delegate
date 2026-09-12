"""El script que responde si la regla de delegacion funciona.

Se prueba porque es quien va a dar el numero: cuatro mediciones anteriores se hicieron cruzando
dos logs a mano, y la pregunta central —de los avisos dados, cuantos acabaron en delegacion— se
quedo sin responder. Un script que cuenta mal es peor que no tenerlo, porque parece una medida.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]


def _cargar():
    spec = importlib.util.spec_from_file_location(
        "medir_adopcion", RAIZ / "scripts" / "medir_adopcion.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["medir_adopcion"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


medir_adopcion = _cargar()


def _escribir(ruta: Path, eventos: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in eventos) + "\n", encoding="utf-8"
    )


@pytest.fixture
def escenario(tmp_path, monkeypatch):
    """Una muestra pequena pero completa: de cada caso, uno que cuenta y uno que no."""
    hooks = tmp_path / "telemetry.jsonl"
    usos = tmp_path / "usage"
    _escribir(
        hooks,
        [
            # Un bloqueo que SI acabo en delegacion.
            {
                "ts": "2026-09-12T10:00:00Z",
                "category": "read",
                "suggested": True,
                "blocked": True,
                "id": "aaa",
                "session_id": "s1",
                "version": "abc12345",
                "path_sha": "f1",
                "motivo": "prosa_grande",
            },
            # Otro que no.
            {
                "ts": "2026-09-12T10:01:00Z",
                "category": "read",
                "suggested": True,
                "blocked": True,
                "id": "bbb",
                "session_id": "s1",
                "version": "abc12345",
                "path_sha": "f2",
                "motivo": "prosa_grande",
            },
            # Un aviso sin bloqueo: ofrecido, pero no cuenta como bloqueo.
            {
                "ts": "2026-09-12T10:02:00Z",
                "category": "read",
                "suggested": True,
                "id": "ccc",
                "session_id": "s1",
                "version": "abc12345",
                "path_sha": "f3",
            },
            # Una acotada de un fichero que despues se leyo entero: convenia delegarla.
            {
                "ts": "2026-09-12T10:03:00Z",
                "category": "read",
                "suggested": False,
                "motivo": "acotada",
                "session_id": "s1",
                "version": "abc12345",
                "path_sha": "f9",
            },
            {
                "ts": "2026-09-12T10:04:00Z",
                "category": "read",
                "suggested": True,
                "id": "ddd",
                "session_id": "s1",
                "version": "abc12345",
                "path_sha": "f9",
            },
            # Una acotada suelta: no convenia.
            {
                "ts": "2026-09-12T10:05:00Z",
                "category": "read",
                "suggested": False,
                "motivo": "acotada",
                "session_id": "s1",
                "version": "abc12345",
                "path_sha": "f8",
            },
            # Un comando de shell contado, que no se bloqueo.
            {
                "ts": "2026-09-12T10:06:00Z",
                "category": "shell",
                "camino": "shell",
                "suggested": False,
                "motivo": "no_es_volcado",
                "session_id": "s1",
                "version": "def67890",
            },
            # Fuera de ventana: no debe contarse cuando se pide --desde.
            {
                "ts": "2026-09-01T10:00:00Z",
                "category": "read",
                "suggested": True,
                "blocked": True,
                "id": "viejo",
                "session_id": "s0",
                "version": "abc12345",
                "path_sha": "f7",
            },
        ],
    )
    _escribir(
        usos / "usage-202609.jsonl",
        [
            {"ts": "2026-09-12T10:00:05Z", "tool": "local_summarize", "bloqueo_id": "aaa"},
            {"ts": "2026-09-12T10:10:00Z", "tool": "local_extract"},
            {"ts": "2026-09-12T10:11:00Z", "tool": "otra_cosa"},
        ],
    )
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(hooks))
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(usos))
    return hooks


def test_el_cruce_dice_cuantos_bloqueos_acabaron_en_delegacion(escenario):
    """La pregunta que ninguna de las cuatro mediciones anteriores pudo responder."""
    resultado = medir_adopcion.medir("2026-09-10")

    assert resultado["bloqueos"] == 2
    assert resultado["aceptados"] == 1
    assert resultado["tasa_de_aceptacion"] == 0.5


def test_una_delegacion_que_nadie_provoco_no_cuenta_como_aceptada(escenario):
    """Control positivo: contarla inflaria la adopcion con lo que el agente ya hacia solo."""
    resultado = medir_adopcion.medir("2026-09-10")

    assert resultado["delegaciones_totales"] == 2, "`otra_cosa` no es una tool local_*"
    assert resultado["delegaciones_espontaneas"] == 1


def test_la_ventana_deja_fuera_lo_de_antes(escenario):
    con_ventana = medir_adopcion.medir("2026-09-10")
    sin_ventana = medir_adopcion.medir(None)

    assert con_ventana["bloqueos"] == 2
    assert sin_ventana["bloqueos"] == 3, "sin ventana entra tambien el bloqueo del 1 de septiembre"


def test_la_guarda_de_acotada_se_mide_con_el_criterio_escrito(escenario):
    """De las dos lecturas por franjas, solo una era de un fichero que acabo leyendose entero."""
    resultado = medir_adopcion.medir("2026-09-10")

    assert resultado["acotadas_con_huella"] == 2
    assert resultado["acotadas_que_convenia_delegar"] == 1


def test_se_cuentan_los_dos_caminos_de_lectura(escenario):
    resultado = medir_adopcion.medir("2026-09-10")

    assert resultado["por_camino"] == {"read": 6, "shell": 1}


def test_se_ve_si_la_muestra_mezcla_dos_versiones_de_script(escenario):
    """Una sesion abierta hereda el entorno del lanzador: sin esto la muestra miente y no lo dice."""
    resultado = medir_adopcion.medir("2026-09-10")

    assert resultado["versiones_de_script"] == ["abc12345", "def67890"]


def test_sin_logs_no_revienta(tmp_path, monkeypatch):
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(tmp_path / "no-existe.jsonl"))
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "tampoco"))

    resultado = medir_adopcion.medir(None)

    assert resultado["lecturas"] == 0
    assert resultado["tasa_de_aceptacion"] is None


def test_una_linea_corrupta_no_tumba_la_medicion(tmp_path, monkeypatch):
    hooks = tmp_path / "telemetry.jsonl"
    hooks.write_text(
        'no es json\n{"ts": "2026-09-12T10:00:00Z", "category": "read", "suggested": true}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(hooks))
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "vacio"))

    assert medir_adopcion.medir(None)["ofrecidos"] == 1
