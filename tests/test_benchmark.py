"""Runner del corpus v2 y su puntuador (tarea 16 del SDD delegacion-precisa-y-fiable).

No requieren backend real: el HTTP va por `MockTransport`. Cada senal del puntuador tiene su control
positivo, y CP-4 —«el puntuador separa cada pareja por la senal correcta»— corre aqui como test
sobre las parejas de referencia del corpus versionado, que es lo que el protocolo dice que es.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import json
from pathlib import Path
from typing import ClassVar

import httpx2
import pytest

from local_delegate import benchmark

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "benchmarks" / "catalogo-2026-09" / "cases.json"


def _corpus():
    return benchmark.load_corpus(CORPUS)


def _case(case_id):
    return next(c for c in _corpus().cases if c.id == case_id)


def _raw(**changes):
    base = {"expected_terms": [], "forbidden_terms": [], "expected_json_fields": []}
    base.update(changes)
    return base


def test_parse_prometheus_metrics_aggregates_gpu_series_and_ignores_noise():
    text = """
# HELP ignored comment
llamaswap_memory_used_bytes 100
llamaswap_gpu_memory_used_bytes{id="0"} 40
llamaswap_gpu_memory_used_bytes{id="1"} 60
unrelated_metric 999
"""
    assert benchmark.parse_prometheus_metrics(text) == {
        "llamaswap_memory_used_bytes": 100.0,
        "llamaswap_gpu_memory_used_bytes": 100.0,
    }


def test_the_july_corpus_no_longer_loads():
    # Ningun REQ-F2 pide repetir la prueba de julio; su fichero se conserva como archivo.
    with pytest.raises(ValueError, match="schema_version=2"):
        benchmark.load_corpus(ROOT / "benchmarks" / "moe" / "cases.json")


# --- Puntuador ------------------------------------------------------------------------------------


def test_correct_accents_no_longer_lose_coverage():
    # El defecto de julio, reproducido en rojo antes de arreglarlo: el puntuador literal le daba
    # 0,5 a esta misma respuesta (verification.md, tarea 16).
    raw = _raw(expected_terms=["computo", "delegaciones"])
    score = benchmark.score_output(
        raw, "Panel de las delegaciones y dónde corrió el cómputo.", "stop"
    )
    assert (score["coverage"], score["quality"]) == (1.0, 1.0)


def test_the_decomposed_form_also_matches():
    raw = _raw(expected_terms=["cómputo"])
    assert benchmark.score_output(raw, "el cómputo", "stop")["coverage"] == 1.0


def test_forbidden_term_sets_quality_to_zero_even_with_coverage_one():
    raw = _raw(expected_terms=["0.27.0"], forbidden_terms=["0.24.0"])
    bad = benchmark.score_output(raw, "Versión 0.27.0, antes 0.24.0", "stop")
    assert bad["coverage"] == 1.0
    assert (bad["quality"], bad["zero_by"]) == (0.0, "forbidden_terms")
    # Control positivo: sin el termino prohibido, la misma respuesta puntua entera.
    good = benchmark.score_output(raw, "Versión 0.27.0, la publicada", "stop")
    assert (good["quality"], good["zero_by"]) == (1.0, None)


def test_truncated_run_does_not_count_as_bad_quality():
    # `truncado` se ejercita inyectando finish_reason: es la senal que CP-4 no cubre con texto.
    raw = _raw(expected_terms=["uno", "dos"])
    truncated = benchmark.score_output(raw, "uno", "length")
    assert truncated["truncated"] is True
    assert (truncated["quality"], truncated["zero_by"]) == (None, None)
    # La misma respuesta sin truncar si cuenta, y a medias.
    assert benchmark.score_output(raw, "uno", "stop")["quality"] == 0.5


def test_invalid_json_sinks_by_json_valid_and_missing_fields_by_proportion():
    raw = _raw(expected_terms=["MIT"], expected_json_fields=["name", "license"])
    invalid = benchmark.score_output(raw, "{'name': 'x', 'license': 'MIT'}", "stop")
    assert (invalid["quality"], invalid["zero_by"]) == (0.0, "json_valid")
    partial = benchmark.score_output(raw, '{"name": "x", "licencia": "MIT"}', "stop")
    assert (partial["json_fields_ratio"], partial["quality"], partial["zero_by"]) == (
        0.5,
        0.5,
        None,
    )


def test_made_up_count_sinks_quality_even_if_it_names_every_rule():
    raw = _raw(
        expected_terms=["T201", "COM812"], expected_counts={"T201": [1, 2, 3], "COM812": [1]}
    )
    good = benchmark.score_output(raw, "- a.py: T201 (2), COM812 (1)\n- b.py: T201 (1)", "stop")
    assert (good["counts_ratio"], good["counts_wrong"], good["quality"]) == (1.0, [], 1.0)
    # La salida del 2B: nombra las dos reglas (cobertura 1,0) con numeros que la fuente no tiene.
    made_up = benchmark.score_output(
        raw, "**T201 (Print):** 10 archivos (3 por archivo)\n**COM812:** 1 archivo", "stop"
    )
    assert (made_up["coverage"], made_up["counts_wrong"], made_up["quality"]) == (
        1.0,
        ["T201"],
        0.5,
    )
    without_numbers = benchmark.score_output(raw, "Sobre todo T201 y COM812.", "stop")
    assert (without_numbers["quality"], without_numbers["zero_by"]) == (0.0, "counts")
    # Cada numero es de la regla que tiene delante (no de toda la linea), y el punto de final de
    # frase no lo anula. Con la regla por lineas, TRY003 se llevaria tambien el 7 y fallaria.
    one_line = _raw(expected_terms=["TRY003", "D102"], expected_counts={"TRY003": [8], "D102": [7]})
    score = benchmark.score_output(one_line, "TRY003: 8. D102: 7.", "stop")
    assert (score["counts_wrong"], score["quality"]) == ([], 1.0)


def test_tool_format_is_stored_and_does_not_touch_quality():
    # P-15: el usuario descarto respuestas por lista o por pasarse de palabras.
    raw = _raw(expected_terms=["hooks"], expected_format={"max_words": 5, "prose": True})
    prose = benchmark.score_output(raw, "Los hooks sugieren delegar.", "stop")
    assert (prose["format_ok"], prose["format_words"], prose["format_list_lines"]) == (True, 4, 0)
    listing = benchmark.score_output(raw, "Los hooks:\n- uno\n2. dos", "stop")
    assert (listing["format_ok"], listing["format_list_lines"], listing["quality"]) == (
        False,
        2,
        1.0,
    )
    long_text = benchmark.score_output(raw, "Los hooks sugieren delegar casi siempre.", "stop")
    assert (long_text["format_ok"], long_text["quality"]) == (False, 1.0)
    assert benchmark.score_output(_raw(expected_terms=["x"]), "x", "stop")["format_ok"] is None


def test_zero_coverage_is_attributed_to_coverage():
    score = benchmark.score_output(_raw(expected_terms=["bug"]), "feature", "stop")
    assert (score["quality"], score["zero_by"]) == (0.0, "coverage")


# --- CP-4: el puntuador separa cada pareja, y por la senal correcta -------------------------------

_COMPONENTS_BY_SIGNAL = {
    "cobertura": {"coverage", "matched_terms"},
    "prohibido": {"forbidden_hits"},
    "json_valido": {"json_valid", "json_fields_ratio"},
    "json_campos": {"json_fields_ratio"},
    "unicode": {"coverage", "matched_terms"},
    "ejecucion": {"execution_ratio", "execution_passed"},
    "conteos": {"counts_ratio", "counts_wrong"},
}


def test_cp4_the_scorer_separates_each_pair_by_its_signal():
    pairs = [c for c in _corpus().cases if "reference_signal" in c.raw]
    assert len(pairs) == 7
    for case in pairs:
        raw = case.raw
        ok = benchmark.score_output(raw, raw["reference_ok"], "stop")
        bad = benchmark.score_output(raw, raw["reference_bad"], "stop")
        assert ok["quality"] > bad["quality"], case.id
        distinct = {
            name
            for name in ok
            # El formato (P-15) se guarda pero no es una senal de calidad: dos respuestas de distinto
            # largo difieren en palabras sin que eso separe nada.
            if name not in {"quality", "zero_by", "truncated"}
            and not name.startswith("format_")
            and ok[name] != bad[name]
        }
        assert distinct == _COMPONENTS_BY_SIGNAL[raw["reference_signal"]], case.id


def test_cp4_a_literal_scorer_would_not_separate_the_unicode_pair():
    # Si el puntuador dejara de normalizar, esta pareja puntuaria igual: es la que lo delata.
    (case,) = [c for c in _corpus().cases if c.raw.get("reference_signal") == "unicode"]
    raw = case.raw

    def literal(text):
        return sum(t.casefold() in text.casefold() for t in raw["expected_terms"])

    assert literal(raw["reference_ok"]) == literal(raw["reference_bad"])


# --- Ejecucion del codigo generado (tarea 19) -----------------------------------------------------


def _boilerplate():
    return _case("boilerplate-156").raw


def test_correct_fenced_code_runs_as_production_would_write_it():
    raw = _boilerplate()
    score = benchmark.score_output(raw, f"```python\n{raw['reference_ok']}```", "stop")
    assert score["execution_passed"] == [True] * 5
    assert (score["execution_ratio"], score["quality"], score["zero_by"]) == (1.0, 1.0, None)


def test_code_that_does_not_load_scores_zero_on_execution_even_if_it_names_the_terms():
    # La salida del 2B en CP-3: usa `re` sin importarlo y 1,0 por terminos.
    code = (
        "def parse_duration(texto):\n"
        '    """Lanza ValueError si no vale."""\n'
        "    m = re.match(r'^(\\d+)h$', texto)\n"
        "    return int(m.group(1)) * 3600\n"
    )
    score = benchmark.score_output(_boilerplate(), code, "stop")
    assert score["coverage"] == 1.0
    assert (score["execution_ratio"], score["quality"], score["zero_by"]) == (0.0, 0.0, "execution")


def test_half_done_code_scores_the_proportion_of_checks():
    # La salida del 14B en CP-3: parte por espacios y no parsea '1h30m'; lo demas lo hace bien.
    code = (
        "def parse_duration(texto):\n"
        "    total = 0\n"
        "    for parte in texto.split():\n"
        "        if parte.endswith('h'):\n"
        "            total += int(parte[:-1]) * 3600\n"
        "        elif parte.endswith('m'):\n"
        "            total += int(parte[:-1]) * 60\n"
        "        elif parte.endswith('s'):\n"
        "            total += int(parte[:-1])\n"
        "        else:\n"
        "            raise ValueError('formato')\n"
        "    return total\n"
    )
    score = benchmark.score_output(_boilerplate(), code, "stop")
    assert score["execution_passed"] == [False, True, True, True, True]
    assert score["quality"] == 0.8


def test_an_infinite_loop_does_not_hang_the_runner(monkeypatch):
    monkeypatch.setattr(benchmark, "EXEC_TIMEOUT_S", 2.0)
    score = benchmark.score_output(_boilerplate(), "while True:\n    pass\n", "stop")
    assert score["execution_passed"] == [False] * 5


def test_generated_code_sees_neither_the_environment_nor_the_operator_directory(monkeypatch):
    monkeypatch.setenv("LD_TEST_SECRET", "should-not-be-seen")
    monkeypatch.chdir(ROOT)
    raw = _raw(
        execution_checks=[
            {"expr": "__import__('os').environ.get('LD_TEST_SECRET')", "expected": None},
            {"expr": "__import__('os').path.exists('pyproject.toml')", "expected": False},
            # Control positivo: el arnes si evalua, o las dos de arriba pasarian por no correr.
            {"expr": "1 + 1", "expected": 2},
        ]
    )
    assert benchmark.run_execution_checks("x = 1\n", raw["execution_checks"]) == [True] * 3
    assert (ROOT / "pyproject.toml").exists()


def test_the_correct_value_with_another_type_does_not_pass():
    # La especificacion pide segundos en int: 45.0 es igual a 45 para `==`, y no vale.
    checks = [{"expr": "f()", "expected": 45}]
    assert benchmark.run_execution_checks("def f():\n    return 45.0\n", checks) == [False]
    assert benchmark.run_execution_checks("def f():\n    return 45\n", checks) == [True]


def test_a_print_from_generated_code_does_not_fake_the_result():
    checks = [{"expr": "1", "expected": 2}]
    code = "print('[true]')\n"
    assert benchmark.run_execution_checks(code, checks) == [False]


def test_truncated_again_after_doubling_scores_zero():
    raw = _raw(expected_terms=["uno"])
    first = benchmark.score_output(raw, "uno", "length")
    repeated = benchmark.score_output(raw, "uno", "length", repeated=True)
    assert (first["quality"], first["zero_by"]) == (None, None)
    assert (repeated["quality"], repeated["zero_by"], repeated["truncated"]) == (
        0.0,
        "truncated_repeated",
        True,
    )


# --- Payload --------------------------------------------------------------------------------------


def test_image_case_carries_image_url_and_text_case_does_not():
    image = _case("describir-dashboard")
    blocks = benchmark.build_payload(image, "m", 42, None)["messages"][1]["content"]
    assert [b["type"] for b in blocks] == ["text", "image_url"]
    url = blocks[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == image.source

    text = benchmark.build_payload(_case("clasificar-53"), "m", 42, None)
    assert isinstance(text["messages"][1]["content"], str)
    assert "image_url" not in json.dumps(text)
    # La temperatura de produccion que capturo el constructor, no 0 (P-12).
    assert (text["temperature"], text["seed"]) == (0.0, 42)
    summary = benchmark.build_payload(_case("resumen-md-2k"), "m", 7, None)
    assert (summary["temperature"], summary["seed"]) == (0.2, 7)


def test_each_text_case_carries_its_whole_content_without_marker():
    for case in _corpus().cases:
        if case.media_type != "texto":
            continue
        payload = benchmark.build_payload(case, "m", 1, None)
        user = payload["messages"][1]["content"]
        content = case.source.decode("utf-8").replace("\r\n", "\n")
        assert content in user, case.id
        assert benchmark.CONTENT_MARKER not in user, case.id
        assert payload["messages"][0]["content"], case.id


def test_the_control_image_replaces_the_case_image():
    control = _corpus().controls[0]
    data = (CORPUS.parent / "fuentes" / control["source_file"]).read_bytes()
    payload = benchmark.build_payload(_case("leer-cifras-dashboard"), "m", 1, None, source=data)
    assert (
        base64.b64encode(data).decode() in payload["messages"][1]["content"][1]["image_url"]["url"]
    )


def test_off_reaches_the_payload_and_the_case_wins_over_the_model():
    case = _case("clasificar-53")
    assert benchmark.build_payload(case, "m", 1, "off")["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    assert benchmark.build_payload(case, "m", 1, "low")["chat_template_kwargs"] == {
        "reasoning_effort": "low"
    }
    assert "chat_template_kwargs" not in benchmark.build_payload(case, "m", 1, None)
    with_own_value = dataclasses.replace(case, raw={**case.raw, "reasoning_effort": "off"})
    assert benchmark.effective_reasoning(with_own_value, "high") == ("off", "case")
    assert benchmark.effective_reasoning(case, "high") == ("high", "model")
    assert benchmark.effective_reasoning(case, None) == (None, None)


# --- El runner de punta a punta, con backend falso ------------------------------------------------


class _NullMetrics:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def peaks(self):
        return {}


# El Client real, capturado al importar: dentro de `_run` ya podria ser el lambda de una llamada
# anterior del mismo test, y envolverlo otra vez pasaria `transport` dos veces.
_CLIENT_REAL = httpx2.Client


def _run(tmp_path, monkeypatch, handler, *extra):
    monkeypatch.setattr(
        benchmark.httpx2,
        "Client",
        lambda **kwargs: _CLIENT_REAL(transport=httpx2.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(benchmark, "MetricsSampler", _NullMetrics)
    parser = argparse.ArgumentParser()
    benchmark.add_parser(parser.add_subparsers())
    output = tmp_path / "out.jsonl"
    args = parser.parse_args(
        [
            "benchmark",
            "--model",
            "m",
            "--label",
            "l",
            "--cases",
            str(CORPUS),
            "--runs",
            "1",
            "--endpoint",
            "http://backend.test/v1",
            "--output",
            str(output),
            *extra,
        ]
    )
    rc = benchmark.run_benchmark(args)
    records = []
    if output.exists():
        records = [json.loads(l) for l in output.read_text(encoding="utf-8").splitlines()]
    return rc, records


def _response(content="bug", finish="stop", **message):
    return httpx2.Response(
        200,
        json={"choices": [{"message": {"content": content, **message}, "finish_reason": finish}]},
    )


def test_default_is_five_runs_per_case():
    # Tercer piloto de CP-3: con temperatura de produccion, una corrida mala movia la mediana de 3.
    parser = argparse.ArgumentParser()
    benchmark.add_parser(parser.add_subparsers())
    args = parser.parse_args(
        ["benchmark", "--model", "m", "--label", "l", "--cases", "c.json", "--output", "o.jsonl"]
    )
    assert args.runs == 5


def test_each_run_carries_its_seed_and_the_case_temperature(tmp_path, monkeypatch):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return _response("# Titulo\n\nresumen")

    rc, records = _run(
        tmp_path, monkeypatch, handler, "--case", "resumen-md-2k", "--runs", "3", "--seed", "10"
    )
    assert rc == 0
    assert [p["seed"] for p in sent] == [10, 11, 12]
    assert {p["temperature"] for p in sent} == {0.2}
    assert [(r["run"], r["seed"], r["temperature"]) for r in records] == [
        (1, 10, 0.2),
        (2, 11, 0.2),
        (3, 12, 0.2),
    ]


def test_runner_scores_with_the_real_corpus_and_without_probe_does_not_make_up_thermal_state(
    tmp_path, monkeypatch
):
    rc, (record,) = _run(
        tmp_path, monkeypatch, lambda _r: _response("bug"), "--case", "clasificar-53"
    )
    assert rc == 0
    assert (record["schema_version"], record["outcome"], record["role"]) == (
        2,
        "ok",
        "mechanical",
    )
    assert record["score"]["quality"] == 1.0
    assert record["thermal_state"] is None
    assert record["discarded"] is False
    # Sin declararlo, el analisis no puede comprobar §6 y declara el rol no concluyente.
    assert record["variant"]["load_mode"] is None


def test_the_record_stores_context_and_load_mode_that_the_analysis_compares(tmp_path, monkeypatch):
    rc, (record,) = _run(
        tmp_path,
        monkeypatch,
        lambda _r: _response("bug"),
        "--case",
        "clasificar-53",
        "--context-size",
        "16384",
        "--load-mode",
        "none",
    )
    assert rc == 0
    assert (record["variant"]["context_size"], record["variant"]["load_mode"]) == (
        16384,
        "none",
    )


def test_context_rejection_is_neither_bad_quality_nor_discarded(tmp_path, monkeypatch):
    def overflow(_request):
        return httpx2.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": "the request exceeds the available context size",
                    "type": "exceed_context_size_error",
                }
            },
        )

    rc, (record,) = _run(tmp_path, monkeypatch, overflow, "--case", "techo-resumen-103k")
    assert record["outcome"] == "context_rejection"
    assert record["score"] is None and record["discarded"] is False
    assert "exceed_context_size_error" in record["error_body"]
    assert rc == 0

    # Control positivo: otro 400 cualquiera es un error, no un rechazo por contexto.
    def other(_request):
        return httpx2.Response(400, json={"error": {"type": "invalid_request_error"}})

    rc, (record,) = _run(tmp_path / "b", monkeypatch, other, "--case", "techo-resumen-103k")
    assert (record["outcome"], rc) == ("error", 1)


def test_truncated_is_repeated_once_with_double_max_tokens(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["max_tokens"])
        return _response("bug", "length" if len(seen) == 1 else "stop")

    _, records = _run(tmp_path, monkeypatch, handler, "--case", "clasificar-53")
    assert [r["outcome"] for r in records] == ["truncado", "ok"]
    assert seen == [16, 32]
    assert records[0]["score"]["quality"] is None
    assert records[1]["score"]["quality"] == 1.0
    assert [r["retry_reason"] for r in records] == [None, "truncado"]


def test_truncated_twice_is_not_repeated_again_and_scores_zero(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["max_tokens"])
        return _response("bug", "length")

    _, records = _run(tmp_path, monkeypatch, handler, "--case", "clasificar-53")
    assert seen == [16, 32]
    assert records[1]["score"]["quality"] == 0.0
    assert records[1]["score"]["zero_by"] == "truncated_repeated"


class _VoidingProbe:
    """Sustituye al muestreador: cada peticion consume el siguiente motivo de anulacion."""

    reasons: ClassVar[list[str | None]] = []

    def __init__(self, *_args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def summary(self):
        reason = type(self).reasons.pop(0) if type(self).reasons else None
        return {"enabled": False, "pids": [], "annul": reason}


def test_voided_run_is_repeated_with_the_same_tokens(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["max_tokens"])
        return _response("bug")

    monkeypatch.setattr(_VoidingProbe, "reasons", ["process_changed", None])
    monkeypatch.setattr(benchmark, "ResourceSampler", _VoidingProbe)
    _, records = _run(tmp_path, monkeypatch, handler, "--case", "clasificar-53")
    assert seen == [16, 16]
    assert [(r["run"], r["attempt"]) for r in records] == [(1, 1), (1, 2)]
    assert [r["discarded"] for r in records] == [True, False]
    assert [r["retry_reason"] for r in records] == [None, "anulada"]


def test_the_voided_run_is_repeated_at_most_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(_VoidingProbe, "reasons", ["process_changed"] * 10)
    monkeypatch.setattr(benchmark, "ResourceSampler", _VoidingProbe)
    _, records = _run(tmp_path, monkeypatch, lambda _r: _response("bug"), "--case", "clasificar-53")
    assert len(records) == 1 + benchmark.MAX_ANNUL_RETRIES
    assert all(r["discarded"] for r in records)


def test_empty_content_from_reasoning_is_configuration_and_is_not_repeated(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(1)
        return _response("", "length", reasoning_content="pensando largo y tendido")

    _, (record,) = _run(tmp_path, monkeypatch, handler, "--case", "clasificar-53")
    assert record["outcome"] == "configuration"
    assert record["reasoning_chars"] > 0 and record["score"] is None
    assert len(seen) == 1


def test_cold_thermal_state_only_after_a_pid_change(tmp_path, monkeypatch):
    # Cuatro peticiones con lectura antes y despues (intervalo largo = exactamente dos muestras):
    # la 1.ª carga el modelo, la 2.ª con el mismo PID, la 3.ª tras un swap, la 4.ª ya caliente.
    pids = iter([None, 1, 1, 1, 2, 2, 2, 2])

    class Probe:
        gpu_luid = "0x0_0x1"

        def __init__(self, *_args):
            pass

        def sample(self):
            pid = next(pids)
            if pid is None:
                return benchmark.ResourceSample(None, reason="no_process")
            return benchmark.ResourceSample(pid, 1, 1, 1, 1)

        def close(self):
            pass

    monkeypatch.setattr(benchmark, "probe_supported", lambda: True)
    monkeypatch.setattr(benchmark, "ProcessProbe", Probe)
    _, records = _run(
        tmp_path,
        monkeypatch,
        lambda _r: _response("bug"),
        "--case",
        "clasificar-53",
        "--runs",
        "4",
        "--sample-interval",
        "60",
        "--probe-process",
        "llama-server.exe",
        "--gpu-luid",
        "0x0_0x1",
    )
    assert [r["thermal_state"] for r in records] == ["cold", "hot", "cold", "hot"]


def test_role_and_control_select_the_matching_cases(tmp_path, monkeypatch):
    _, records = _run(tmp_path, monkeypatch, lambda _r: _response("x"), "--role", "vision")
    assert sorted(r["case"] for r in records) == ["describir-dashboard", "leer-cifras-dashboard"]
    assert all(r["input_variant"] is None for r in records)

    control = _corpus().controls[0]
    _, records = _run(
        tmp_path / "c", monkeypatch, lambda _r: _response("x"), "--input-control", control["id"]
    )
    assert sorted(r["case"] for r in records) == sorted(control["para"])
    assert {r["input_variant"] for r in records} == {control["id"]}
    assert {r["input_sha256"] for r in records} == {control["source_sha256"]}


# --- Lectura dual del corpus congelado (ola A10b-1) -----------------------------------------------


def test_frozen_corpus_old_provenance_key_is_read_as_the_new_one():
    """El corpus versionado dice `procedencia`; `load_corpus` lo da como `provenance`."""
    frozen = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]
    assert frozen and all("procedencia" in c and "provenance" not in c for c in frozen)
    cases = _corpus().cases
    assert all("provenance" in c.raw and "procedencia" not in c.raw for c in cases)
    assert [c.provenance for c in cases] == [c["procedencia"] for c in frozen]
