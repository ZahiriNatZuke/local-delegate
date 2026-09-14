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

import httpx2
import pytest

from local_delegate import benchmark

RAIZ = Path(__file__).parents[1]
CORPUS = RAIZ / "benchmarks" / "catalogo-2026-09" / "cases.json"


def _corpus():
    return benchmark.load_corpus(CORPUS)


def _case(case_id):
    return next(c for c in _corpus().cases if c.id == case_id)


def _raw(**cambios):
    base = {"expected_terms": [], "forbidden_terms": [], "expected_json_fields": []}
    base.update(cambios)
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


def test_el_corpus_de_julio_ya_no_carga():
    # Ningun REQ-F2 pide repetir la prueba de julio; su fichero se conserva como archivo.
    with pytest.raises(ValueError, match="schema_version=2"):
        benchmark.load_corpus(RAIZ / "benchmarks" / "moe" / "cases.json")


# --- Puntuador ------------------------------------------------------------------------------------


def test_acentos_correctos_ya_no_pierden_cobertura():
    # El defecto de julio, reproducido en rojo antes de arreglarlo: el puntuador literal le daba
    # 0,5 a esta misma respuesta (verification.md, tarea 16).
    raw = _raw(expected_terms=["computo", "delegaciones"])
    score = benchmark.score_output(
        raw, "Panel de las delegaciones y dónde corrió el cómputo.", "stop"
    )
    assert (score["coverage"], score["quality"]) == (1.0, 1.0)


def test_la_forma_descompuesta_tambien_casa():
    raw = _raw(expected_terms=["cómputo"])
    assert benchmark.score_output(raw, "el cómputo", "stop")["coverage"] == 1.0


def test_termino_prohibido_pone_la_calidad_a_cero_aunque_la_cobertura_sea_uno():
    raw = _raw(expected_terms=["0.27.0"], forbidden_terms=["0.24.0"])
    malo = benchmark.score_output(raw, "Versión 0.27.0, antes 0.24.0", "stop")
    assert malo["coverage"] == 1.0
    assert (malo["quality"], malo["zero_by"]) == (0.0, "forbidden_terms")
    # Control positivo: sin el termino prohibido, la misma respuesta puntua entera.
    bueno = benchmark.score_output(raw, "Versión 0.27.0, la publicada", "stop")
    assert (bueno["quality"], bueno["zero_by"]) == (1.0, None)


def test_corrida_truncada_no_cuenta_como_mala_calidad():
    # `truncado` se ejercita inyectando finish_reason: es la senal que CP-4 no cubre con texto.
    raw = _raw(expected_terms=["uno", "dos"])
    truncada = benchmark.score_output(raw, "uno", "length")
    assert truncada["truncated"] is True
    assert (truncada["quality"], truncada["zero_by"]) == (None, None)
    # La misma respuesta sin truncar si cuenta, y a medias.
    assert benchmark.score_output(raw, "uno", "stop")["quality"] == 0.5


def test_json_invalido_hunde_por_json_valid_y_campos_que_faltan_por_proporcion():
    raw = _raw(expected_terms=["MIT"], expected_json_fields=["name", "license"])
    invalido = benchmark.score_output(raw, "{'name': 'x', 'license': 'MIT'}", "stop")
    assert (invalido["quality"], invalido["zero_by"]) == (0.0, "json_valid")
    a_medias = benchmark.score_output(raw, '{"name": "x", "licencia": "MIT"}', "stop")
    assert (a_medias["json_fields_ratio"], a_medias["quality"], a_medias["zero_by"]) == (
        0.5,
        0.5,
        None,
    )


def test_cobertura_cero_se_atribuye_a_coverage():
    score = benchmark.score_output(_raw(expected_terms=["bug"]), "feature", "stop")
    assert (score["quality"], score["zero_by"]) == (0.0, "coverage")


# --- CP-4: el puntuador separa cada pareja, y por la senal correcta -------------------------------

_COMPONENTES_POR_SENAL = {
    "cobertura": {"coverage", "matched_terms"},
    "prohibido": {"forbidden_hits"},
    "json_valido": {"json_valid", "json_fields_ratio"},
    "json_campos": {"json_fields_ratio"},
    "unicode": {"coverage", "matched_terms"},
}


def test_cp4_el_puntuador_separa_cada_pareja_por_su_senal():
    parejas = [c for c in _corpus().cases if "reference_signal" in c.raw]
    assert len(parejas) == 5
    for caso in parejas:
        raw = caso.raw
        ok = benchmark.score_output(raw, raw["reference_ok"], "stop")
        malo = benchmark.score_output(raw, raw["reference_bad"], "stop")
        assert ok["quality"] > malo["quality"], caso.id
        distintos = {
            nombre
            for nombre in ok
            if nombre not in {"quality", "zero_by", "truncated"} and ok[nombre] != malo[nombre]
        }
        assert distintos == _COMPONENTES_POR_SENAL[raw["reference_signal"]], caso.id


def test_cp4_un_puntuador_literal_no_separaria_la_pareja_de_unicode():
    # Si el puntuador dejara de normalizar, esta pareja puntuaria igual: es la que lo delata.
    (caso,) = [c for c in _corpus().cases if c.raw.get("reference_signal") == "unicode"]
    raw = caso.raw

    def literal(texto):
        return sum(t.casefold() in texto.casefold() for t in raw["expected_terms"])

    assert literal(raw["reference_ok"]) == literal(raw["reference_bad"])


# --- Payload --------------------------------------------------------------------------------------


def test_caso_de_imagen_lleva_image_url_y_uno_de_texto_no():
    imagen = _case("describir-dashboard")
    bloques = benchmark.build_payload(imagen, "m", 42, None)["messages"][1]["content"]
    assert [b["type"] for b in bloques] == ["text", "image_url"]
    url = bloques[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == imagen.source

    texto = benchmark.build_payload(_case("clasificar-53"), "m", 42, None)
    assert isinstance(texto["messages"][1]["content"], str)
    assert "image_url" not in json.dumps(texto)
    assert (texto["temperature"], texto["seed"]) == (0.0, 42)


def test_cada_caso_de_texto_lleva_su_contenido_entero_y_sin_marcador():
    for caso in _corpus().cases:
        if caso.media_type != "texto":
            continue
        payload = benchmark.build_payload(caso, "m", 1, None)
        user = payload["messages"][1]["content"]
        contenido = caso.source.decode("utf-8").replace("\r\n", "\n")
        assert contenido in user, caso.id
        assert benchmark.CONTENT_MARKER not in user, caso.id
        assert payload["messages"][0]["content"], caso.id


def test_la_imagen_de_control_sustituye_a_la_del_caso():
    control = _corpus().controls[0]
    datos = (CORPUS.parent / "fuentes" / control["source_file"]).read_bytes()
    payload = benchmark.build_payload(_case("leer-cifras-dashboard"), "m", 1, None, source=datos)
    assert (
        base64.b64encode(datos).decode() in payload["messages"][1]["content"][1]["image_url"]["url"]
    )


def test_apagado_llega_al_payload_y_el_caso_manda_sobre_el_modelo():
    caso = _case("clasificar-53")
    assert benchmark.build_payload(caso, "m", 1, "off")["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    assert benchmark.build_payload(caso, "m", 1, "low")["chat_template_kwargs"] == {
        "reasoning_effort": "low"
    }
    assert "chat_template_kwargs" not in benchmark.build_payload(caso, "m", 1, None)
    con_valor_propio = dataclasses.replace(caso, raw={**caso.raw, "reasoning_effort": "off"})
    assert benchmark.effective_reasoning(con_valor_propio, "high") == ("off", "case")
    assert benchmark.effective_reasoning(caso, "high") == ("high", "model")
    assert benchmark.effective_reasoning(caso, None) == (None, None)


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


# El Client real, capturado al importar: dentro de `_correr` ya podria ser el lambda de una llamada
# anterior del mismo test, y envolverlo otra vez pasaria `transport` dos veces.
_CLIENT_REAL = httpx2.Client


def _correr(tmp_path, monkeypatch, handler, *extra):
    monkeypatch.setattr(
        benchmark.httpx2,
        "Client",
        lambda **kwargs: _CLIENT_REAL(transport=httpx2.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(benchmark, "MetricsSampler", _NullMetrics)
    parser = argparse.ArgumentParser()
    benchmark.add_parser(parser.add_subparsers())
    salida = tmp_path / "out.jsonl"
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
            str(salida),
            *extra,
        ]
    )
    rc = benchmark.run_benchmark(args)
    registros = []
    if salida.exists():
        registros = [json.loads(l) for l in salida.read_text(encoding="utf-8").splitlines()]
    return rc, registros


def _respuesta(content="bug", finish="stop", **mensaje):
    return httpx2.Response(
        200,
        json={"choices": [{"message": {"content": content, **mensaje}, "finish_reason": finish}]},
    )


def test_runner_puntua_con_el_corpus_real_y_sin_sonda_no_inventa_estado_termico(
    tmp_path, monkeypatch
):
    rc, (registro,) = _correr(
        tmp_path, monkeypatch, lambda _r: _respuesta("bug"), "--case", "clasificar-53"
    )
    assert rc == 0
    assert (registro["schema_version"], registro["outcome"], registro["role"]) == (
        2,
        "ok",
        "mechanical",
    )
    assert registro["score"]["quality"] == 1.0
    assert registro["thermal_state"] is None
    assert registro["descartada"] is False
    # Sin declararlo, el analisis no puede comprobar §6 y declara el rol no concluyente.
    assert registro["variant"]["load_mode"] is None


def test_el_registro_guarda_contexto_y_load_mode_que_compara_el_analisis(tmp_path, monkeypatch):
    rc, (registro,) = _correr(
        tmp_path,
        monkeypatch,
        lambda _r: _respuesta("bug"),
        "--case",
        "clasificar-53",
        "--context-size",
        "16384",
        "--load-mode",
        "none",
    )
    assert rc == 0
    assert (registro["variant"]["context_size"], registro["variant"]["load_mode"]) == (
        16384,
        "none",
    )


def test_rechazo_por_contexto_no_es_mala_calidad_ni_descartada(tmp_path, monkeypatch):
    def desborde(_request):
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

    rc, (registro,) = _correr(tmp_path, monkeypatch, desborde, "--case", "techo-resumen-103k")
    assert registro["outcome"] == "rechazo_por_contexto"
    assert registro["score"] is None and registro["descartada"] is False
    assert "exceed_context_size_error" in registro["error_body"]
    assert rc == 0

    # Control positivo: otro 400 cualquiera es un error, no un rechazo por contexto.
    def otro(_request):
        return httpx2.Response(400, json={"error": {"type": "invalid_request_error"}})

    rc, (registro,) = _correr(tmp_path / "b", monkeypatch, otro, "--case", "techo-resumen-103k")
    assert (registro["outcome"], rc) == ("error", 1)


def test_truncada_se_repite_una_vez_con_el_doble_de_max_tokens(tmp_path, monkeypatch):
    vistos = []

    def handler(request):
        vistos.append(json.loads(request.content)["max_tokens"])
        return _respuesta("bug", "length" if len(vistos) == 1 else "stop")

    _, registros = _correr(tmp_path, monkeypatch, handler, "--case", "clasificar-53")
    assert [r["outcome"] for r in registros] == ["truncado", "ok"]
    assert vistos == [16, 32]
    assert registros[0]["score"]["quality"] is None
    assert registros[1]["score"]["quality"] == 1.0


def test_contenido_vacio_por_razonar_es_configuracion_y_no_se_repite(tmp_path, monkeypatch):
    vistos = []

    def handler(request):
        vistos.append(1)
        return _respuesta("", "length", reasoning_content="pensando largo y tendido")

    _, (registro,) = _correr(tmp_path, monkeypatch, handler, "--case", "clasificar-53")
    assert registro["outcome"] == "configuracion"
    assert registro["reasoning_chars"] > 0 and registro["score"] is None
    assert len(vistos) == 1


def test_estado_termico_frio_solo_tras_un_cambio_de_pid(tmp_path, monkeypatch):
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
    _, registros = _correr(
        tmp_path,
        monkeypatch,
        lambda _r: _respuesta("bug"),
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
    assert [r["thermal_state"] for r in registros] == ["cold", "hot", "cold", "hot"]


def test_rol_y_control_seleccionan_los_casos_que_tocan(tmp_path, monkeypatch):
    _, registros = _correr(tmp_path, monkeypatch, lambda _r: _respuesta("x"), "--role", "vision")
    assert sorted(r["case"] for r in registros) == ["describir-dashboard", "leer-cifras-dashboard"]
    assert all(r["input_variant"] is None for r in registros)

    control = _corpus().controls[0]
    _, registros = _correr(
        tmp_path / "c", monkeypatch, lambda _r: _respuesta("x"), "--input-control", control["id"]
    )
    assert sorted(r["case"] for r in registros) == sorted(control["para"])
    assert {r["input_variant"] for r in registros} == {control["id"]}
    assert {r["input_sha256"] for r in registros} == {control["source_sha256"]}
