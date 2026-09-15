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


def test_conteo_inventado_hunde_la_calidad_aunque_nombre_todas_las_reglas():
    raw = _raw(
        expected_terms=["T201", "COM812"], expected_counts={"T201": [1, 2, 3], "COM812": [1]}
    )
    bien = benchmark.score_output(raw, "- a.py: T201 (2), COM812 (1)\n- b.py: T201 (1)", "stop")
    assert (bien["counts_ratio"], bien["counts_wrong"], bien["quality"]) == (1.0, [], 1.0)
    # La salida del 2B: nombra las dos reglas (cobertura 1,0) con numeros que la fuente no tiene.
    inventado = benchmark.score_output(
        raw, "**T201 (Print):** 10 archivos (3 por archivo)\n**COM812:** 1 archivo", "stop"
    )
    assert (inventado["coverage"], inventado["counts_wrong"], inventado["quality"]) == (
        1.0,
        ["T201"],
        0.5,
    )
    sin_numeros = benchmark.score_output(raw, "Sobre todo T201 y COM812.", "stop")
    assert (sin_numeros["quality"], sin_numeros["zero_by"]) == (0.0, "counts")
    # Cada numero es de la regla que tiene delante (no de toda la linea), y el punto de final de
    # frase no lo anula. Con la regla por lineas, TRY003 se llevaria tambien el 7 y fallaria.
    una_linea = _raw(
        expected_terms=["TRY003", "D102"], expected_counts={"TRY003": [8], "D102": [7]}
    )
    score = benchmark.score_output(una_linea, "TRY003: 8. D102: 7.", "stop")
    assert (score["counts_wrong"], score["quality"]) == ([], 1.0)


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
    "ejecucion": {"execution_ratio", "execution_passed"},
    "conteos": {"counts_ratio", "counts_wrong"},
}


def test_cp4_el_puntuador_separa_cada_pareja_por_su_senal():
    parejas = [c for c in _corpus().cases if "reference_signal" in c.raw]
    assert len(parejas) == 7
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


# --- Ejecucion del codigo generado (tarea 19) -----------------------------------------------------


def _boilerplate():
    return _case("boilerplate-156").raw


def test_codigo_correcto_entre_vallas_se_ejecuta_como_lo_escribiria_produccion():
    raw = _boilerplate()
    score = benchmark.score_output(raw, f"```python\n{raw['reference_ok']}```", "stop")
    assert score["execution_passed"] == [True] * 5
    assert (score["execution_ratio"], score["quality"], score["zero_by"]) == (1.0, 1.0, None)


def test_codigo_que_no_carga_puntua_cero_por_ejecucion_aunque_nombre_los_terminos():
    # La salida del 2B en CP-3: usa `re` sin importarlo y 1,0 por terminos.
    codigo = (
        "def parse_duration(texto):\n"
        '    """Lanza ValueError si no vale."""\n'
        "    m = re.match(r'^(\\d+)h$', texto)\n"
        "    return int(m.group(1)) * 3600\n"
    )
    score = benchmark.score_output(_boilerplate(), codigo, "stop")
    assert score["coverage"] == 1.0
    assert (score["execution_ratio"], score["quality"], score["zero_by"]) == (0.0, 0.0, "execution")


def test_codigo_a_medias_puntua_la_proporcion_de_comprobaciones():
    # La salida del 14B en CP-3: parte por espacios y no parsea '1h30m'; lo demas lo hace bien.
    codigo = (
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
    score = benchmark.score_output(_boilerplate(), codigo, "stop")
    assert score["execution_passed"] == [False, True, True, True, True]
    assert score["quality"] == 0.8


def test_un_bucle_infinito_no_cuelga_el_runner(monkeypatch):
    monkeypatch.setattr(benchmark, "EXEC_TIMEOUT_S", 2.0)
    score = benchmark.score_output(_boilerplate(), "while True:\n    pass\n", "stop")
    assert score["execution_passed"] == [False] * 5


def test_el_codigo_generado_no_ve_el_entorno_ni_el_directorio_del_operador(monkeypatch):
    monkeypatch.setenv("LD_SECRETO_DE_PRUEBA", "no-deberia-verse")
    monkeypatch.chdir(RAIZ)
    raw = _raw(
        execution_checks=[
            {"expr": "__import__('os').environ.get('LD_SECRETO_DE_PRUEBA')", "expected": None},
            {"expr": "__import__('os').path.exists('pyproject.toml')", "expected": False},
            # Control positivo: el arnes si evalua, o las dos de arriba pasarian por no correr.
            {"expr": "1 + 1", "expected": 2},
        ]
    )
    assert benchmark.run_execution_checks("x = 1\n", raw["execution_checks"]) == [True] * 3
    assert (RAIZ / "pyproject.toml").exists()


def test_el_valor_correcto_con_otro_tipo_no_pasa():
    # La especificacion pide segundos en int: 45.0 es igual a 45 para `==`, y no vale.
    checks = [{"expr": "f()", "expected": 45}]
    assert benchmark.run_execution_checks("def f():\n    return 45.0\n", checks) == [False]
    assert benchmark.run_execution_checks("def f():\n    return 45\n", checks) == [True]


def test_un_print_del_codigo_generado_no_finge_el_resultado():
    checks = [{"expr": "1", "expected": 2}]
    codigo = "print('[true]')\n"
    assert benchmark.run_execution_checks(codigo, checks) == [False]


def test_truncada_otra_vez_tras_doblar_puntua_cero():
    raw = _raw(expected_terms=["uno"])
    primera = benchmark.score_output(raw, "uno", "length")
    repetida = benchmark.score_output(raw, "uno", "length", repeated=True)
    assert (primera["quality"], primera["zero_by"]) == (None, None)
    assert (repetida["quality"], repetida["zero_by"], repetida["truncated"]) == (
        0.0,
        "truncado_repetido",
        True,
    )


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
    # La temperatura de produccion que capturo el constructor, no 0 (P-12).
    assert (texto["temperature"], texto["seed"]) == (0.0, 42)
    resumen = benchmark.build_payload(_case("resumen-md-2k"), "m", 7, None)
    assert (resumen["temperature"], resumen["seed"]) == (0.2, 7)


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


def test_cada_corrida_lleva_su_semilla_y_la_temperatura_del_caso(tmp_path, monkeypatch):
    enviados = []

    def handler(request):
        enviados.append(json.loads(request.content))
        return _respuesta("# Titulo\n\nresumen")

    rc, registros = _correr(
        tmp_path, monkeypatch, handler, "--case", "resumen-md-2k", "--runs", "3", "--seed", "10"
    )
    assert rc == 0
    assert [p["seed"] for p in enviados] == [10, 11, 12]
    assert {p["temperature"] for p in enviados} == {0.2}
    assert [(r["run"], r["seed"], r["temperature"]) for r in registros] == [
        (1, 10, 0.2),
        (2, 11, 0.2),
        (3, 12, 0.2),
    ]


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
    assert [r["retry_reason"] for r in registros] == [None, "truncado"]


def test_truncada_dos_veces_no_se_repite_mas_y_puntua_cero(tmp_path, monkeypatch):
    vistos = []

    def handler(request):
        vistos.append(json.loads(request.content)["max_tokens"])
        return _respuesta("bug", "length")

    _, registros = _correr(tmp_path, monkeypatch, handler, "--case", "clasificar-53")
    assert vistos == [16, 32]
    assert registros[1]["score"]["quality"] == 0.0
    assert registros[1]["score"]["zero_by"] == "truncado_repetido"


class _SondaQueAnula:
    """Sustituye al muestreador: cada peticion consume el siguiente motivo de anulacion."""

    motivos: ClassVar[list[str | None]] = []

    def __init__(self, *_args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def summary(self):
        motivo = type(self).motivos.pop(0) if type(self).motivos else None
        return {"enabled": False, "pids": [], "annul": motivo}


def test_corrida_anulada_se_repite_con_los_mismos_tokens(tmp_path, monkeypatch):
    vistos = []

    def handler(request):
        vistos.append(json.loads(request.content)["max_tokens"])
        return _respuesta("bug")

    monkeypatch.setattr(_SondaQueAnula, "motivos", ["process_changed", None])
    monkeypatch.setattr(benchmark, "ResourceSampler", _SondaQueAnula)
    _, registros = _correr(tmp_path, monkeypatch, handler, "--case", "clasificar-53")
    assert vistos == [16, 16]
    assert [(r["run"], r["attempt"]) for r in registros] == [(1, 1), (1, 2)]
    assert [r["descartada"] for r in registros] == [True, False]
    assert [r["retry_reason"] for r in registros] == [None, "anulada"]


def test_la_anulada_se_repite_como_mucho_dos_veces(tmp_path, monkeypatch):
    monkeypatch.setattr(_SondaQueAnula, "motivos", ["process_changed"] * 10)
    monkeypatch.setattr(benchmark, "ResourceSampler", _SondaQueAnula)
    _, registros = _correr(
        tmp_path, monkeypatch, lambda _r: _respuesta("bug"), "--case", "clasificar-53"
    )
    assert len(registros) == 1 + benchmark.MAX_ANNUL_RETRIES
    assert all(r["descartada"] for r in registros)


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
