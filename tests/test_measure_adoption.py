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

from local_delegate import config

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "measure_adoption", ROOT / "scripts" / "measure_adoption.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_adoption"] = module
    spec.loader.exec_module(module)
    return module


measure_adoption = _load()


def _write(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8"
    )


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    """Una muestra pequena pero completa: de cada caso, uno que cuenta y uno que no."""
    hooks = tmp_path / "telemetry.jsonl"
    usages = tmp_path / "usage"
    _write(
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
            # Fuera de ventana: no debe contarse cuando se pide --since.
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
    _write(
        usages / "usage-202609.jsonl",
        [
            {"ts": "2026-09-12T10:00:05Z", "tool": "local_summarize", "bloqueo_id": "aaa"},
            {"ts": "2026-09-12T10:10:00Z", "tool": "local_extract"},
            {"ts": "2026-09-12T10:11:00Z", "tool": "something_else"},
        ],
    )
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(hooks))
    monkeypatch.setattr(config, "LOG_DIR", usages)
    return hooks


def test_the_join_says_how_many_blocks_ended_in_delegation(scenario):
    """La pregunta que ninguna de las cuatro mediciones anteriores pudo responder."""
    result = measure_adoption.measure("2026-09-10")

    assert result["blocks"] == 2
    assert result["accepted"] == 1
    assert result["acceptance_rate"] == 0.5


def test_a_delegation_nobody_prompted_does_not_count_as_accepted(scenario):
    """Control positivo: contarla inflaria la adopcion con lo que el agente ya hacia solo."""
    result = measure_adoption.measure("2026-09-10")

    assert result["total_delegations"] == 2, "`something_else` no es una tool local_*"
    assert result["spontaneous_delegations"] == 1


def test_the_window_leaves_out_what_came_before(scenario):
    with_window = measure_adoption.measure("2026-09-10")
    without_window = measure_adoption.measure(None)

    assert with_window["blocks"] == 2
    assert without_window["blocks"] == 3, "sin ventana entra tambien el bloqueo del 1 de septiembre"


def test_the_bounded_guard_is_measured_with_the_written_criterion(scenario):
    """De las dos lecturas por franjas, solo una era de un fichero que acabo leyendose entero."""
    result = measure_adoption.measure("2026-09-10")

    assert result["bounded_with_footprint"] == 2
    assert result["bounded_worth_delegating"] == 1


def test_both_read_paths_are_counted(scenario):
    result = measure_adoption.measure("2026-09-10")

    assert result["by_path"] == {"read": 6, "shell": 1}


def test_it_shows_if_the_sample_mixes_two_script_versions(scenario):
    """Una sesion abierta hereda el entorno del lanzador: sin esto la muestra miente y no lo dice."""
    result = measure_adoption.measure("2026-09-10")

    assert result["script_versions"] == ["abc12345", "def67890"]


def test_without_logs_it_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(tmp_path / "does-not-exist.jsonl"))
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "tampoco")

    result = measure_adoption.measure(None)

    assert result["reads"] == 0
    assert result["acceptance_rate"] is None


def test_a_corrupt_line_does_not_break_the_measurement(tmp_path, monkeypatch):
    hooks = tmp_path / "telemetry.jsonl"
    hooks.write_text(
        'no es json\n{"ts": "2026-09-12T10:00:00Z", "category": "read", "suggested": true}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(hooks))
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "vacio")

    assert measure_adoption.measure(None)["offered"] == 1


# --- Ventanas de prueba (test-windows-out-of-metrics, REQ-021 y REQ-022) -------------------------


def test_the_directory_is_the_config_one(tmp_path, monkeypatch):
    """REQ-022: el panel y los scripts leen el MISMO `test-windows.json`."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "uno")
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "otro"))
    assert measure_adoption.logs_dir() == tmp_path / "uno"
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR")
    assert measure_adoption.logs_dir() == config.LOG_DIR


def test_a_block_and_its_delegation_in_a_window_do_not_count(scenario):
    """Control: mutante «se ignora el fichero de ventanas» → los bloqueos siguen en 2."""
    from local_delegate import test_windows

    test_windows.add(config.LOG_DIR, "2026-09-12T09:59:00Z", "2026-09-12T10:00:30Z", "prueba")
    without_tests = measure_adoption.measure("2026-09-10")
    with_tests = measure_adoption.measure("2026-09-10", include_tests=True)
    assert (with_tests["blocks"], with_tests["accepted"]) == (2, 1), (
        "guarda: sin quitar nada, lo de siempre"
    )
    assert (without_tests["blocks"], without_tests["accepted"]) == (1, 0)
    assert without_tests["excluded_tests"] == {"hooks": 1, "usage": 1}
    assert with_tests["excluded_tests"] == {"hooks": 0, "usage": 0}


def test_mcp_client_rows_do_not_count_as_delegation(scenario):
    _write(
        config.LOG_DIR / "usage-202610.jsonl",
        [{"ts": "2026-10-01T10:00:00Z", "tool": "local_summarize", "client": "mcp"}],
    )
    assert measure_adoption.measure("2026-09-10")["total_delegations"] == 2
    assert measure_adoption.measure("2026-09-10", include_tests=True)["total_delegations"] == 3


def test_real_main_exits_with_zero(scenario, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["measure_adoption.py", "--since", "2026-09-10", "--json"])
    assert measure_adoption.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert "excluded_tests" in data and "test_windows" in data
    # `--desde`, el nombre de antes de `--since`, sigue valiendo (alias).
    monkeypatch.setattr(sys, "argv", ["measure_adoption.py", "--desde", "2026-09-10"])
    assert measure_adoption.main() == 0
    assert "Pruebas fuera:" in capsys.readouterr().out


def test_bench_rows_do_not_count_as_delegation(scenario):
    """La marca `banco` llega por el relleno, no por el log: sin fundir, la fila se colaba.
    Control: mutante «sin fundir» (filas crudas) → la delegación de banco vuelve a contar."""
    from local_delegate import attribution

    _write(
        config.LOG_DIR / "usage-202610.jsonl",
        [{"ts": "2026-10-01T10:00:00Z", "tool": "local_summarize", "tool_use_id": "toolu_bk"}],
    )
    assert measure_adoption.measure("2026-09-10")["total_delegations"] == 3, "guarda: sin relleno"
    attribution.write_backfill(config.LOG_DIR, "202610", {"toolu_bk": {"bench": True}})
    assert measure_adoption.measure("2026-09-10")["total_delegations"] == 2
    assert measure_adoption.measure("2026-09-10", include_tests=True)["total_delegations"] == 3


# --- Telemetría vieja y nueva (REQ-006, ola A2 del renombrado) ---------------------------------


def _to_new_format(event: dict) -> dict:
    """La misma fila con las claves y valores en inglés, como la escribe un hook de hoy."""
    from local_delegate import legacy_names

    return legacy_names.normalize("hook_telemetry", event)


@pytest.mark.parametrize("fmt", ["new", "mixed"])
def test_new_or_mixed_rows_give_the_same_measure_as_the_old_ones(scenario, fmt):
    """El escenario está escrito en el formato viejo (`motivo`, `camino`…). Traducido entero, o la
    mitad, la medida tiene que salir idéntica: la historia en español se sigue contando."""
    before = measure_adoption.measure("2026-09-10")
    rows = [json.loads(x) for x in scenario.read_text(encoding="utf-8").splitlines() if x]
    assert any("motivo" in f for f in rows), "guarda: el escenario trae filas viejas"
    new_ones = [_to_new_format(f) if fmt == "new" or i % 2 else f for i, f in enumerate(rows)]
    assert any("reason" in f for f in new_ones)
    _write(scenario, new_ones)

    assert measure_adoption.measure("2026-09-10") == before


# --- Log de uso viejo y nuevo (REQ-006, ola A3 del renombrado) ---------------------------------


def test_the_new_block_id_counts_the_same_as_the_old_bloqueo_id(scenario):
    """El escenario trae la delegación aceptada con `bloqueo_id` (0.34.0). Con `block_id`, la
    aceptación y las delegaciones espontáneas salen iguales."""
    before = measure_adoption.measure("2026-09-10")
    assert before["accepted"] == 1, "guarda: el escenario cruza un bloqueo con su delegación"
    usage = config.LOG_DIR / "usage-202609.jsonl"
    rows = [json.loads(x) for x in usage.read_text(encoding="utf-8").splitlines() if x]
    assert any("bloqueo_id" in f for f in rows), "guarda: el escenario trae la clave vieja"
    _write(
        usage, [{("block_id" if k == "bloqueo_id" else k): v for k, v in f.items()} for f in rows]
    )

    assert measure_adoption.measure("2026-09-10") == before
