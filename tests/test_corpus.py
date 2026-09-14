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
    unica = None
    if caso.kind == "techo":
        unica = construir.capturar(caso, ruta, datos, sin_troceo=True)
    return construir.comprobar(caso, construir.capturar(caso, ruta, datos), datos, unica)


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


# --- Parejas de referencia de CP-4 (tarea 15) -----------------------------------------------------


def _parejas():
    corpus = benchmark.load_corpus(DESTINO / "cases.json")
    return [c for c in corpus.cases if "reference_signal" in c.raw]


def test_las_senales_de_texto_tienen_cada_una_su_pareja():
    parejas = _parejas()
    assert sorted(c.raw["reference_signal"] for c in parejas) == sorted(
        construir.DIFERENCIAS_ESPERADAS
    )
    assert all(c.kind == "calidad" for c in parejas)


def test_cada_pareja_versionada_difiere_solo_en_su_senal_y_mide_lo_mismo():
    # Lee el JSON versionado, no el constructor: una referencia retocada a mano tambien cae aqui.
    for caso in _parejas():
        raw = caso.raw
        argumentos = (raw["expected_terms"], raw["forbidden_terms"], raw["expected_json_fields"])
        ok = construir.senales(raw["reference_ok"], *argumentos)
        malo = construir.senales(raw["reference_bad"], *argumentos)
        difieren = {nombre for nombre in ok if ok[nombre] != malo[nombre]}
        assert difieren == construir.DIFERENCIAS_ESPERADAS[raw["reference_signal"]], caso.id
        assert len(raw["reference_ok"]) == len(raw["reference_bad"]), caso.id
        assert ok["cobertura"] and not ok["prohibido"], caso.id


def test_pareja_que_difiere_en_dos_senales_se_rechaza():
    # La mala mete el termino prohibido Y pierde el esperado: separaria por cobertura, y CP-4 no
    # sabria si el puntuador acerto por la senal que se queria ejercitar.
    caso = _caso(
        expected_terms=("0.27.0",),
        forbidden_terms=("0.24.0",),
        referencia=("prohibido", "Version 0.27.0 hoy", "Version 0.24.0 hoy"),
    )
    assert construir.comprobar_referencia(caso, ("0.27.0",)) == [
        (
            "prueba: la pareja de prohibido difiere en ['cobertura', 'cobertura_literal', "
            "'prohibido'], no en ['prohibido']"
        )
    ]


def test_pareja_de_distinta_longitud_se_rechaza():
    caso = _caso(expected_terms=("bug",), referencia=("cobertura", "bug", "nada"))
    assert construir.comprobar_referencia(caso, ("bug",)) == [
        "prueba: la pareja no tiene la misma longitud (3 y 4)"
    ]


def test_respuesta_buena_que_no_es_buena_se_rechaza():
    caso = _caso(expected_terms=("bug",), referencia=("cobertura", "nada", "bug."))
    errores = construir.comprobar_referencia(caso, ("bug",))
    assert len(errores) == 1 and "la respuesta buena no es buena" in errores[0]


def test_nfkd_solo_no_quita_el_acento_y_la_normalizacion_si():
    import unicodedata

    assert "computo" not in unicodedata.normalize("NFKD", "cómputo").casefold()
    assert construir.plano("CÓMPUTO") == "computo"


def test_referencia_retocada_que_sigue_siendo_valida_la_caza_la_vigilancia(tmp_path):
    # El retoque deja una pareja VALIDA —misma longitud, difiere solo en cobertura—, asi que el
    # oraculo no lo ve: solo la comparacion contra el constructor puede. Un mutante que quitaba las
    # referencias de los campos vigilados sobrevivia a todo lo demas.
    copia = tmp_path / "corpus"
    shutil.copytree(DESTINO, copia)
    ruta = copia / "cases.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    (caso,) = [c for c in datos["cases"] if c["id"] == "resumen-md-2k"]
    caso["reference_ok"] = caso["reference_ok"].replace("Guía", "Guia", 1)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    raw = caso
    ok = construir.senales(raw["reference_ok"], raw["expected_terms"], raw["forbidden_terms"], [])
    assert ok["cobertura"], "el retoque tiene que dejar la pareja valida"
    assert construir.comprobar_versionado(copia) == [
        "resumen-md-2k: reference_ok ya no coincide con el constructor"
    ]


def test_reconstruir_no_recongela_una_fuente_desde_el_fichero_vivo(tmp_path):
    # Paso en la tarea 16: regenerar para anadir un campo volvio a leer CHANGELOG.md y la salida de
    # ruff, y sobrescribio dos fuentes congeladas. La marca solo esta en la copia congelada: si el
    # constructor vuelve a leer CONTRIBUTING.md, desaparece.
    copia = tmp_path / "corpus"
    shutil.copytree(DESTINO, copia)
    fuente = copia / "fuentes" / "resumen-md-2k.md"
    marcada = fuente.read_bytes() + b"<!-- congelado -->\n"
    fuente.write_bytes(marcada)

    rc = construir.construir(RAIZ, copia, None)

    # La marca ANTES que el exit code: recongelando, la construccion puede fallar por otra regla
    # (el CHANGELOG vivo crece y cambia el tamano de su recorte), y el test caeria por eso en vez
    # de por lo que prueba. Tras una release que no cambiara el tamano, sobreviviria el defecto.
    assert fuente.read_bytes() == marcada
    assert rc == 0
    (caso,) = [
        c for c in benchmark.load_corpus(copia / "cases.json").cases if c.id == "resumen-md-2k"
    ]
    assert caso.raw["source_sha256"] == hashlib.sha256(marcada).hexdigest()


# --- Terminos derivados tras CP-3 (tarea 19) ------------------------------------------------------


def test_terminos_del_commit_salen_solo_de_su_primera_entrada_fixed():
    diff = (
        " ## [Unreleased]\n"
        "+## [1.0.0]\n"
        "+\n"
        "+### Fixed\n"
        "+- Arreglo de `inflight`: `_privado` y `python -m x` no entran; `LOG_DIR/estado.json`,\n"
        "+  `/api/estado` y `snap()` si.\n"
        "+- Segunda entrada con `no_entra`.\n"
        "+### Added\n"
        "+- `tampoco`\n"
        "diff --git a/x b/x\n"
    )
    assert construir._identificadores_del_primer_arreglo(diff) == (
        "inflight",
        "estado.json",
        "/api/estado",
        "snap",
    )
    assert construir._identificadores_del_primer_arreglo("+### Added\n+- `x`\n") == ()


def test_terminos_del_changelog_salen_solo_de_los_titulares_en_negrita():
    texto = (
        "## [1.0.0]\n\n### Changed\n"
        "- **Retirados `viejo.py` y `f()`.** El cuerpo nombra `no_entra`.\n"
        "- Entrada sin titular en negrita: `tampoco`.\n"
    )
    assert construir._identificadores_de_los_titulares(texto) == ("viejo.py", "f")


def test_terminos_de_explicar_salen_del_docstring_del_modulo_y_no_de_una_funcion():
    fuente = (
        '"""m.py\n\n  GET /           -> html\n  GET /api/a     -> x\n  GET /api/b     -> y\n'
        'Toca `~/.x/settings.json`, `dir/` y `--dry-run`.\n"""\n\n'
        'def f():\n    """GET /api/fuera y `otro.md`."""\n'
    )
    assert construir._rutas_del_docstring(fuente) == ("/api/a", "/api/b")
    assert construir._ficheros_y_flags_del_docstring(fuente) == ("settings.json", "--dry-run")
