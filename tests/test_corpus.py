"""Corpus v2 de la tanda de F2 (tarea 14 del SDD delegacion-precisa-y-fiable).

Las reglas del corpus se comprueban contra el codigo de produccion, no contra la tabla del
protocolo: se llama a la tool real con el backend interceptado y se mira que modelo elige y
cuantas llamadas hace. Cada regla tiene su control positivo —un caso que DEBE romperla— porque
una regla que no puede fallar no comprueba nada.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest

from local_delegate import benchmark, config

RAIZ = Path(__file__).parents[1]
DESTINO = RAIZ / "benchmarks" / "catalogo-2026-09"


def _cargar():
    spec = importlib.util.spec_from_file_location(
        "construir_corpus", RAIZ / "scripts" / "construir_corpus.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["construir_corpus"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


construir = _cargar()


# --- Lo versionado ------------------------------------------------------------------------------


def test_corpus_versionado_sigue_reflejando_a_produccion():
    # Si cambia un MAX_CHARS, el enrutado o un prompt, el corpus ya no mide lo que dice.
    assert construir.comprobar_versionado(DESTINO) == []


def test_reparto_es_el_del_protocolo():
    corpus = benchmark.load_corpus(DESTINO / "cases.json")
    calidad = Counter(c.role for c in corpus.cases if c.kind == "calidad")
    assert calidad == {"mechanical": 5, "long": 4, "code": 4, "vision": 2}
    assert sorted(c.role for c in corpus.cases if c.kind == "techo") == ["code", "long"]


def test_imagen_de_control_existe_y_no_es_la_del_caso():
    corpus = benchmark.load_corpus(DESTINO / "cases.json")
    (control,) = corpus.controls
    casos = [c for c in corpus.cases if c.id in control["para"]]
    assert len(casos) == 2
    assert all(c.raw["source_sha256"] != control["source_sha256"] for c in casos)


def test_ninguna_ruta_del_usuario_llega_al_corpus_versionado():
    for nombre in ("cases.json", "conteos-log.json"):
        texto = (DESTINO / nombre).read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:(\\\\|/)|/Users/|/home/|AppData", texto), nombre
        assert str(Path.home()) not in texto


def test_conteos_versionados_cuadran_entre_si():
    # El error de la primera version del protocolo: una fila sumaba 152 y las demas 146.
    conteos = json.loads((DESTINO / "conteos-log.json").read_text(encoding="utf-8"))
    local = conteos["eventos_local"]
    assert sum(t["n"] for t in conteos["por_tool"].values()) == local
    assert sum(conteos["por_modelo"].values()) == local
    assert sum(conteos["por_source"].values()) == local
    assert conteos["eventos"] == local + sum(conteos["descartados_no_local"].values())


# --- El cargador ----------------------------------------------------------------------------------


def test_hash_que_no_cuadra_hace_fallar_la_carga(tmp_path):
    copia = tmp_path / "corpus"
    shutil.copytree(DESTINO, copia)
    fuente = copia / "fuentes" / "clasificar-53.txt"
    fuente.write_bytes(fuente.read_bytes() + b" ")
    with pytest.raises(ValueError, match="clasificar-53: source_sha256 no cuadra"):
        benchmark.load_corpus(copia / "cases.json")


def test_hash_del_control_tambien_se_verifica(tmp_path):
    copia = tmp_path / "corpus"
    shutil.copytree(DESTINO, copia)
    control = copia / "fuentes" / "dashboard-bcbe39f.png"
    control.write_bytes(control.read_bytes()[:-1])
    with pytest.raises(ValueError, match="dashboard-bcbe39f: source_sha256 no cuadra"):
        benchmark.load_corpus(copia / "cases.json")


def test_una_ruta_viva_en_source_file_se_rechaza(tmp_path):
    copia = tmp_path / "corpus"
    shutil.copytree(DESTINO, copia)
    ruta = copia / "cases.json"
    # La ruta viva EXISTE y su hash cuadra: solo la regla del nombre puede pararla. Sin el
    # fichero, la carga fallaria igual por «falta la fuente» y el test no probaria la regla.
    viva = tmp_path / "CHANGELOG.md"
    viva.write_bytes(b"## [9.9.9]\n")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["cases"][0]["source_file"] = "../../CHANGELOG.md"
    datos["cases"][0]["source_sha256"] = hashlib.sha256(viva.read_bytes()).hexdigest()
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(ValueError, match="nombre en fuentes/"):
        benchmark.load_corpus(ruta)


# --- Cada regla, con un caso que la tiene que romper ----------------------------------------------


def _caso(**cambios):
    base = {
        "id": "prueba",
        "tool": "local_summarize",
        "role": "mechanical",
        "kind": "calidad",
        "procedencia": "inventado",
        "origen": "test",
        "fuente": construir.texto_literal(""),
        "expected_terms": ("prueba",),
    }
    base.update(cambios)
    return construir.Caso(**base)


def _errores(caso, tmp_path, datos: bytes, nombre="fuente.txt"):
    ruta = tmp_path / nombre
    ruta.write_bytes(datos)
    return construir.comprobar(caso, construir.capturar(caso, ruta, datos), datos)


def test_caso_bien_formado_no_da_errores(tmp_path):
    assert _errores(_caso(), tmp_path, b"linea de prueba\n" * 20) == []


def test_regla_de_rol_caza_un_fichero_que_produccion_manda_a_otro_rol(tmp_path):
    # Es el pyproject.toml entero: 7 073 bytes pasan de LONG_INPUT_CHARS y van a long.
    datos = b"name = 'prueba'\n" * (config.LONG_INPUT_CHARS // 16 + 10)
    caso = _caso(tool="local_extract", expected_json_fields=("name",))
    errores = _errores(caso, tmp_path, datos, "grande.toml")
    assert errores == [
        f"prueba: declarado mechanical, pero produccion eligio {config.MODEL_LONG} (long)"
    ]


def test_regla_de_una_llamada_caza_el_traducir_14k(tmp_path):
    # local_translate trocea SIEMPRE a CHUNK_CHARS: 14 000 chars nunca llegan juntos al modelo.
    texto = "Frase de prueba que hay que traducir entera.\n\n" * 300
    caso = _caso(
        tool="local_translate",
        role="long",
        argumentos={"target_lang": "inglés"},
        terminos_en_fuente=False,
    )
    errores = _errores(caso, tmp_path, texto.encode())
    assert len(errores) == 1 and "no cabe en una llamada, produccion hace" in errores[0]


def test_regla_de_entrada_entera_caza_un_truncado(tmp_path):
    # explain_code nunca trocea: trunca a MAX_CHARS del rol code y el modelo ve solo el principio.
    datos = b"x = 1  # prueba\n" * (config.max_chars_for(config.MODEL_CODE) // 16 + 200)
    caso = _caso(tool="local_explain_code", role="code")
    errores = _errores(caso, tmp_path, datos, "grande.py")
    assert errores == ["prueba: el modelo no ve la entrada entera (truncada)"]


def test_sondeo_de_techo_que_cabe_en_una_llamada_no_sondea_nada(tmp_path):
    caso = _caso(kind="techo", expected_terms=())
    errores = _errores(caso, tmp_path, b"corto\n" * 10)
    assert errores == ["prueba: cabe en una llamada, asi que no sondea ningun techo"]


def test_termino_esperado_que_no_esta_en_la_fuente_se_rechaza(tmp_path):
    caso = _caso(expected_terms=("prueba", "inexistente"))
    errores = _errores(caso, tmp_path, b"linea de prueba\n" * 20)
    assert errores == ["prueba: el termino 'inexistente' no esta en la fuente"]


def test_id_que_promete_un_tamano_que_la_fuente_no_tiene():
    assert construir._comprobar_tamano_del_id("techo-resumen-120k", 106_092) != []
    assert construir._comprobar_tamano_del_id("techo-resumen-106k", 105_800) == []
    assert construir._comprobar_tamano_del_id("clasificar-53", 52) != []
    assert construir._comprobar_tamano_del_id("clasificar-53", 53) == []


def test_la_captura_no_escribe_en_el_log_de_uso_ni_llama_al_backend(tmp_path, monkeypatch):
    log = tmp_path / "log"
    log.mkdir()
    monkeypatch.setattr(config, "LOG_DIR", log)
    caso = _caso()
    _errores(caso, tmp_path, b"linea de prueba\n" * 20)
    assert list(log.iterdir()) == []


# --- Conteos del log ------------------------------------------------------------------------------


def test_contar_log_descarta_rutas_de_fuera_del_repo_y_eventos_no_locales(tmp_path):
    raiz = tmp_path / "repo"
    (raiz / "docs").mkdir(parents=True)
    log = tmp_path / "log"
    log.mkdir()
    eventos = [
        {
            "tool": "local_summarize",
            "model": "llama31-8b",
            "chars_in": 100,
            "source": "path",
            "path": str(raiz / "docs" / "a.md"),
        },
        {
            "tool": "local_summarize",
            "model": "gemma3-4b",
            "chars_in": 300,
            "source": "path",
            "path": str(tmp_path / "vault" / "nota-personal.md"),
            "chunks": 3,
        },
        {"tool": "local_classify", "model": "gemma3-4b", "chars_in": 53, "source": "inline"},
        {"tool": "concurrency_test_resident", "model": "gemma3-4b", "chars_in": 1},
    ]
    lineas = [json.dumps(e) for e in eventos] + ["{no es json"]
    (log / "usage-202609.jsonl").write_text("\n".join(lineas) + "\n", encoding="utf-8")

    conteos = construir.contar_log(log, raiz)

    assert (conteos["eventos"], conteos["eventos_local"]) == (4, 3)
    assert conteos["descartados_no_local"] == {"concurrency_test_resident": 1}
    assert conteos["por_tool"]["local_summarize"]["n"] == 2
    assert conteos["por_tool"]["local_summarize"]["chars_in_mediana"] == 200
    assert conteos["por_modelo"] == {"gemma3-4b": 2, "llama31-8b": 1}
    assert conteos["troceados"] == 1
    assert conteos["fuentes_del_repo"] == {"docs/a.md": 1}
    assert conteos["fuentes_fuera_del_repo"] == 1
    volcado = json.dumps(conteos)
    assert "nota-personal" not in volcado and "vault" not in volcado
