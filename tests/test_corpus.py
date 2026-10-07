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
import os
import re
import shutil
import subprocess
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
    datos = b"x = 1  # prueba\n" * (config.max_chars_for_role("code") // 16 + 200)
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
        argumentos = (
            raw["expected_terms"],
            raw["forbidden_terms"],
            raw["expected_json_fields"],
            raw["execution_checks"],
            raw["expected_counts"],
        )
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


_RUFF = (
    "src/a.py:1:1: CPY001 Missing copyright\n"
    "src/a.py:3:5: T201 `print` found\n"
    "src/a.py:9:5: T201 `print` found\n"
    "src/b.py:2:1: T201 `print` found\n"
    "src/b.py:4:1: COM812 Trailing comma missing\n"
    "src/c.py:1:1: CPY001 Missing copyright\n"
    "Found 6 errors.\n"
)


def test_lint_se_recorta_en_archivos_enteros_y_nunca_a_medias():
    # a.py (3 lineas) cabe; b.py no cabe entero en el limite: no entra ni su primera linea.
    limite = len("".join(_RUFF.splitlines(keepends=True)[:4]))
    assert construir.archivos_enteros(_RUFF, limite) == "".join(_RUFF.splitlines(keepends=True)[:3])
    # Con sitio para todo, el resumen de ruff no se cuela: va en su propio bloque, al final.
    todo = construir.archivos_enteros(_RUFF, len(_RUFF) - len("Found 6 errors.\n"))
    assert "Found" not in todo and todo.count("\n") == 6


def test_conteos_validos_de_lint_son_total_archivos_y_cada_archivo():
    # T201: 3 en total, 2 archivos, 2 en a.py y 1 en b.py. CPY001: 2 en total, 2 archivos, 1 y 1.
    assert construir._conteos_de_las_reglas(_RUFF) == {
        "T201": [1, 2, 3],
        "CPY001": [1, 2],
        "COM812": [1],
    }


def test_oraculo_de_conteos_caza_el_conteo_inventado_del_segundo_piloto():
    conteos = {"T201": [1, 2, 3]}
    assert construir._conteos_cuadran("- src/a.py: T201 (2)\n- src/b.py: T201 (1)", conteos)
    assert not construir._conteos_cuadran("**T201 (Print):** 10 archivos (3 por archivo)", conteos)
    # Nombrarla sin conteo no cuadra, y el «1.» de una lista o el 201 del codigo no cuentan.
    assert not construir._conteos_cuadran("T201 aparece mucho", conteos)
    assert construir._conteos_cuadran("1. T201: 3", conteos)
    # Cada numero es de la regla que tiene delante, y el punto de final de frase no lo anula: los
    # dos defectos de la primera version, que rompieron la pareja de referencia.
    dos = {"T201": [1, 2, 3], "COM812": [1]}
    assert construir._conteos_cuadran("a.py: T201 (2), COM812 (1). b.py: T201 3.", dos)
    assert not construir._conteos_cuadran("a.py: T201 (2), COM812 (2).", dos)
    assert not construir._conteos_cuadran("Python 3.12: T201 3.5", conteos)


def test_formato_pedido_sale_del_prompt_de_la_tool():
    resumen = (
        "Output EXACTO: un resumen en prosa clara. Máximo 150 palabras. Nada fuera del formato."
    )
    assert construir.formato_pedido(resumen) == {"max_words": 150, "prose": True}
    lint = "Output EXACTO: un resumen agrupado por archivo. Maximo 200 palabras."
    assert construir.formato_pedido(lint) == {"max_words": 200}
    assert construir.formato_pedido("Clasifica en una etiqueta.") == {}
    assert construir.formato_pedido(None) == {}


def test_los_casos_de_texto_abierto_los_deciden_los_pares():
    corpus = {c.id: c.raw for c in benchmark.load_corpus(DESTINO / "cases.json").cases}
    abiertos = {
        "resumen-md-10k",
        "resumen-changelog-7k",
        "explicar-metrics-15k",
        "explicar-install-20k",
        "commit-diff-19k",
        "lint-9k",
    }
    assert {cid for cid, c in corpus.items() if c.get("automatic_scoring") is False} == abiertos
    assert corpus["resumen-md-10k"]["expected_format"] == {"max_words": 150, "prose": True}


def test_terminos_de_explicar_salen_del_docstring_del_modulo_y_no_de_una_funcion():
    fuente = (
        '"""m.py\n\n  GET /           -> html\n  GET /api/a     -> x\n  GET /api/b     -> y\n'
        'Toca `~/.x/settings.json`, `dir/` y `--dry-run`.\n"""\n\n'
        'def f():\n    """GET /api/fuera y `otro.md`."""\n'
    )
    assert construir._rutas_del_docstring(fuente) == ("/api/a", "/api/b")
    assert construir._ficheros_y_flags_del_docstring(fuente) == ("settings.json", "--dry-run")


# =====================================================================================================
# Corpus de afinidad (REQ-040): la regla de seleccion de commits, las trampas y el corpus construido.
# La regla se prueba sobre repos git sinteticos en `tmp_path`: un test que leyera el historial real
# fallaria en un checkout superficial del CI.
# =====================================================================================================

CORTE = "2026-10-06"
PASOS_SINTETICOS = ((None, 300, 1200),)


def _git_repo(
    repo: Path, *args: str, fecha: str | None = None, autor: str = "Ana <ana@example.org>"
):
    entorno = {
        **os.environ,
        "GIT_COMMITTER_NAME": "Ana",
        "GIT_COMMITTER_EMAIL": "ana@example.org",
        "GIT_AUTHOR_NAME": autor.split(" <")[0],
        "GIT_AUTHOR_EMAIL": autor.split("<")[1].rstrip(">"),
    }
    if fecha:
        entorno["GIT_COMMITTER_DATE"] = entorno["GIT_AUTHOR_DATE"] = f"{fecha}T12:00:00+00:00"
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=entorno,
    )


def _repo_nuevo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo(repo, "init", "-q", "-b", "main")
    return repo


def _confirmar(
    repo, asunto, fichero, tamano=400, fecha="2026-09-01", autor="Ana <ana@example.org>", cuerpo=""
):
    """Un commit que deja en `fichero` una linea de `tamano` caracteres, propia de este commit."""
    linea = (asunto + " " + "x" * tamano)[:tamano]
    (repo / fichero).write_text(linea + "\n", encoding="utf-8", newline="\n")
    _git_repo(repo, "add", "-A")
    mensaje = asunto + (f"\n\n{cuerpo}" if cuerpo else "")
    _git_repo(repo, "commit", "-q", "-m", mensaje, fecha=fecha, autor=autor)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _repo_de_la_regla(tmp_path):
    """Los elegibles `ok-NN`, mezclados con todo lo que la regla excluye entre los mas recientes."""
    repo = _repo_nuevo(tmp_path)
    dia = iter(range(1, 28))

    def fecha():
        return f"2026-09-{next(dia):02d}"

    for i in range(1, 11):
        _confirmar(repo, f"feat: ok-{i:02d}", f"f{i}.txt", fecha=fecha())
    excluidos = [
        ("ok-11", {}),
        ("chore(release): 1.1", {}),
        ("ok-12", {}),
        ("chore(deps): sube una libreria", {}),
        ("chore: release v1.0", {}),
        ("ok-13", {}),
        ("fix: subir otra libreria", {"autor": "dependabot[bot] <bot@example.org>"}),
        ("fix: diff chico", {"tamano": 20}),
        ("ok-14", {}),
        ("fix: diff enorme", {"tamano": 3000}),
    ]
    for n, (asunto, kw) in enumerate(excluidos):
        if asunto.startswith("ok-"):
            asunto = f"feat: {asunto}"
        _confirmar(repo, asunto, f"g{n}.txt", fecha=fecha(), **kw)
    # Un merge sin conflicto y un commit posterior a la fecha de corte.
    _git_repo(repo, "checkout", "-q", "-b", "rama")
    _confirmar(repo, "fix: diff chico de la rama", "rama.txt", tamano=20, fecha=fecha())
    _git_repo(repo, "checkout", "-q", "main")
    _git_repo(repo, "merge", "-q", "--no-ff", "rama", "-m", "Merge rama", fecha=fecha())
    _confirmar(repo, "feat: tardio", "tardio.txt", fecha="2026-10-07")
    return repo


def _asuntos(commits):
    return [c.asunto for c in commits]


def test_la_regla_elige_exactamente_los_esperados_en_orden_y_los_siguientes_como_trampa(tmp_path):
    repo = _repo_de_la_regla(tmp_path)
    sel = construir.seleccionar_commits(
        repo, antes=CORTE, excluir=(), n_reales=3, n_trampas=2, pasos=PASOS_SINTETICOS
    )
    elegidos = _asuntos(sel.reales) + _asuntos(sel.trampas)
    # `chore(release): 1.1` SI es candidato: la regla excluye el texto exacto `chore: release`.
    assert elegidos == [
        "feat: ok-14",
        "feat: ok-13",
        "feat: ok-12",
        "chore(release): 1.1",
        "feat: ok-11",
    ]
    assert _asuntos(sel.reales) == ["feat: ok-14", "feat: ok-13", "feat: ok-12"]
    assert _asuntos(sel.trampas) == ["chore(release): 1.1", "feat: ok-11"]
    # Todo lo que la regla excluye, de verdad estaba en el historial (control positivo).
    todos = _asuntos(construir._commits_de(repo, "main", None))
    for excluido in (
        "chore: release v1.0",
        "fix: subir otra libreria",
        "feat: tardio",
    ):
        assert excluido in todos


def test_ninguna_trampa_coincide_con_un_caso_real(tmp_path):
    repo = _repo_de_la_regla(tmp_path)
    sel = construir.seleccionar_commits(
        repo, antes=CORTE, excluir=(), n_reales=3, n_trampas=2, pasos=PASOS_SINTETICOS
    )
    reales = {c.hash for c in sel.reales}
    trampas = {c.hash for c in sel.trampas}
    assert len(trampas) == 2
    assert not reales & trampas
    diffs_reales = {construir._diff_normalizado(repo, h) for h in reales}
    assert not diffs_reales & {construir._diff_normalizado(repo, h) for h in trampas}


def test_la_regla_se_amplia_si_la_ventana_no_da_los_commits(tmp_path):
    repo = _repo_de_la_regla(tmp_path)
    # Una ventana de 3 commits no da 5: el segundo paso mira todo el historial.
    pasos = ((3, 300, 700), (None, 300, 700))
    sel = construir.seleccionar_commits(
        repo, antes=CORTE, excluir=(), n_reales=3, n_trampas=2, pasos=pasos
    )
    assert sel.paso == 1
    assert len(sel.reales) == 3 and len(sel.trampas) == 2
    with pytest.raises(ValueError, match="no da 40 commits"):
        construir.seleccionar_commits(
            repo, antes=CORTE, excluir=(), n_reales=30, n_trampas=10, pasos=pasos
        )


def test_el_caso_que_ya_esta_en_f2_y_los_diffs_con_datos_privados_no_se_eligen(tmp_path):
    repo = _repo_nuevo(tmp_path)
    for i in range(1, 6):
        _confirmar(repo, f"feat: ok-{i}", f"f{i}.txt", fecha=f"2026-09-{i:02d}")
    privado = repo / "p.txt"
    privado.write_text("ruta C:\\Users\\Persona\\secreto " + "x" * 400 + "\n", encoding="utf-8")
    _git_repo(repo, "add", "-A")
    _git_repo(repo, "commit", "-q", "-m", "feat: con ruta privada", fecha="2026-09-10")
    sel = construir.seleccionar_commits(
        repo, antes=CORTE, n_reales=2, n_trampas=1, pasos=PASOS_SINTETICOS, excluir=()
    )
    assert _asuntos(sel.reales)[0] == "feat: con ruta privada"
    sel = construir.seleccionar_commits(
        repo,
        antes=CORTE,
        n_reales=2,
        n_trampas=1,
        pasos=PASOS_SINTETICOS,
        excluir=(),
        descartar_si=lambda texto: bool(construir.datos_privados(texto)),
    )
    assert "feat: con ruta privada" not in _asuntos(sel.reales + sel.trampas)
    primero = sel.reales[0]
    sel = construir.seleccionar_commits(
        repo,
        antes=CORTE,
        n_reales=2,
        n_trampas=1,
        pasos=PASOS_SINTETICOS,
        excluir=(primero.hash[:7],),
        descartar_si=lambda texto: bool(construir.datos_privados(texto)),
    )
    assert primero.hash not in {c.hash for c in sel.reales + sel.trampas}


# --- La trampa «de la misma zona» --------------------------------------------------------------------


def _repo_de_la_zona(tmp_path):
    repo = _repo_nuevo(tmp_path)
    largo = "docs: " + "un asunto demasiado largo para una linea de commit " * 2  # > 72
    assert len(largo) > 72
    _confirmar(repo, largo.strip(), "grande.txt", tamano=80, fecha="2026-08-01")
    _confirmar(
        repo,
        "fix: asunto del segundo fichero (#12)",
        "chico.txt",
        tamano=80,
        fecha="2026-08-02",
        cuerpo="Primera linea del cuerpo.\n* feat: el asunto repetido por el squash\nSegunda linea.\n\n"
        "Co-Authored-By: Alguien <a@example.org>\nClaude-Session: https://claude.ai/code/session_ABCDEFGHIJ",
    )
    # El commit del caso trampa: toca `grande.txt` mucho y `chico.txt` poco.
    ruta = repo / "grande.txt"
    ruta.write_text(
        ruta.read_text(encoding="utf-8") + "linea nueva\n" * 40, encoding="utf-8", newline="\n"
    )
    (repo / "chico.txt").write_text("otro\n", encoding="utf-8", newline="\n")
    _git_repo(repo, "add", "-A")
    _git_repo(repo, "commit", "-q", "-m", "feat: el cambio del caso", fecha="2026-09-01")
    return repo


def test_la_trampa_de_la_misma_zona_tiene_un_asunto_de_72_caracteres_como_mucho(tmp_path):
    repo = _repo_de_la_zona(tmp_path)
    caso = next(
        c
        for c in construir._commits_de(repo, "main", None)
        if c.asunto == "feat: el cambio del caso"
    )
    # `grande.txt` es el fichero mas cambiado: su unico otro commit tiene un asunto de mas de 72.
    assert construir._numstat(repo, caso.hash)[0][1] == "grande.txt"
    zona = construir.asunto_misma_zona(repo, caso, {caso.hash}, antes=CORTE)
    assert zona is not None
    assert len(zona["asunto"]) <= 72
    # Pasa al siguiente fichero mas cambiado, y le quita el « (#12)» del squash.
    assert (zona["fichero"], zona["asunto"]) == ("chico.txt", "fix: asunto del segundo fichero")
    # El cuerpo real, sin firmas, sin enlaces de sesion y sin el asunto repetido.
    assert zona["cuerpo_real"] == ["Primera linea del cuerpo.", "Segunda linea."]
    # Sin ningun candidato, no inventa ninguno.
    assert (
        construir.asunto_misma_zona(repo, caso, {caso.hash}, antes=CORTE, maximo_asunto=5) is None
    )


def test_armar_trampas_da_tres_por_juego_con_los_tres_tipos(tmp_path, monkeypatch):
    repo = _repo_nuevo(tmp_path)
    for z in range(3):  # el commit de cada zona, de asunto corto y fuera de la seleccion
        _confirmar(repo, f"docs: zona {z}", f"z{z}.txt", tamano=30, fecha="2026-08-01")
    for i in range(1, 12):
        fichero = f"z{(i - 1) % 3}.txt"
        _confirmar(repo, f"feat: ok-{i:02d}", fichero, tamano=400, fecha=f"2026-09-{i:02d}")
    sel = construir.seleccionar_commits(
        repo, antes=CORTE, excluir=(), n_reales=2, n_trampas=9, pasos=PASOS_SINTETICOS
    )
    assert len(sel.trampas) == 9
    redactadas = {
        c.corto: {
            "asunto": f"chore: redactada {c.corto}",
            "cuerpo": [f"linea {n}" for n in range(5)],
        }
        for k, c in enumerate(sel.trampas)
        if k % 3 != 0
    }
    reservas = {
        c.corto: [f"reserva {n}" for n in range(5)] for k, c in enumerate(sel.trampas) if k % 3 == 0
    }
    monkeypatch.setattr(construir, "TRAMPAS_REDACTADAS", redactadas)
    monkeypatch.setattr(construir, "RESERVAS_MISMA_ZONA", reservas)
    trampas = construir.armar_trampas(repo, sel, antes=CORTE)
    assert [j["juego"] for j in trampas["juegos"]] == [1, 2, 3]
    todos = []
    for juego in trampas["juegos"]:
        assert [t["tipo"] for t in juego["trampas"]] == ["misma-zona", "secundario", "generico"]
        for t in juego["trampas"]:
            assert len(t["asunto"]) <= 72 and 1 <= len(t["cuerpo"]) <= 5
            todos.append(t["caso"])
    assert len(set(todos)) == 9
    assert set(todos) == {f"commit-trampa-{c.corto}" for c in sel.trampas}
    # La de la misma zona es el asunto REAL de otro commit del mismo fichero, fuera de la seleccion.
    primera = trampas["juegos"][0]["trampas"][0]
    assert primera["asunto"].startswith("docs: zona ")
    assert primera["asunto_de"]["hash"] not in {c.hash for c in sel.reales + sel.trampas}
    assert primera["cuerpo_origen"] != "real-reescrito"
    # Con el cuerpo reescrito a mano, ese cuerpo manda sobre las lineas reales (partidas a 80 columnas).
    monkeypatch.setattr(
        construir, "CUERPOS_MISMA_ZONA", {sel.trampas[0].corto: ["Una frase entera."]}
    )
    reescrita = construir.armar_trampas(repo, sel, antes=CORTE)["juegos"][0]["trampas"][0]
    assert reescrita["cuerpo"] == ["Una frase entera."]
    assert reescrita["cuerpo_origen"] == "real-reescrito"
    # Si falta la trampa redactada de un caso, no se inventa: se para.
    monkeypatch.setattr(construir, "TRAMPAS_REDACTADAS", {})
    with pytest.raises(ValueError, match="falta la trampa redactada"):
        construir.armar_trampas(repo, sel, antes=CORTE)


# --- Datos privados -----------------------------------------------------------------------------------


def test_datos_privados_detecta_lo_privado_y_deja_pasar_lo_inocuo():
    privados = construir.datos_privados(
        "ruta C:\\Users\\Persona\\x.py y /home/persona/y, ip 100.64.1.2, sesion session_ABCDEFGH12, "
        "correo persona@gmail.com"
    )
    assert len(privados) == 5, privados
    inocuo = (
        "C:\\Users\\...\\hook.py, /Users/<usuario>/x, 127.0.0.1, 0.0.0.0, 203.0.113.7, version 0.28.0, "
        "marta@example.org, +@pytest.fixture y opencode-ai@1.18.11"
    )
    assert construir.datos_privados(inocuo) == []


# --- El corpus construido -----------------------------------------------------------------------------


def _corpus_construido():
    ruta = os.environ.get("LD_AFINIDAD_CORPUS") or str(RAIZ / "benchmarks" / "afinidad-2026-10")
    cases = Path(ruta) / "cases.json"
    if not cases.is_file():
        pytest.skip(f"el corpus de afinidad aun no esta construido en {ruta}")
    return Path(ruta), cases


@pytest.fixture
def afinidad():
    carpeta, cases = _corpus_construido()
    corpus = benchmark.load_corpus(cases)  # verifica el sha256 de cada fuente
    return carpeta, json.loads(cases.read_text(encoding="utf-8")), corpus


def test_el_corpus_de_afinidad_tiene_el_tamano_de_la_spec(afinidad):
    _, datos, corpus = afinidad
    casos = datos["cases"]

    def contar(tool, **filtro):
        return sum(
            1 for c in casos if c["tool"] == tool and all(c.get(k) == v for k, v in filtro.items())
        )

    nuevos = {"discriminante": True, "rol_en_hoja": None}
    assert contar("local_classify", **nuevos) == 8
    assert contar("local_extract", **nuevos) == 8
    assert contar("local_translate", **nuevos) == 4
    assert contar("local_lint_summary", **nuevos) == 4
    assert contar("local_delegate", **nuevos) == 4
    assert contar("local_commit_msg", rol_en_hoja="real") == 30
    assert contar("local_commit_msg", rol_en_hoja="trampa") == 9
    regresion = [
        c["id"]
        for c in casos
        if c["discriminante"] is False and c["kind"] == "calidad" and c["rol_en_hoja"] is None
    ]
    assert sorted(regresion) == sorted(construir.REGRESION_DE_F2)
    assert [c["id"] for c in casos if c["kind"] == "techo"] == [construir.CASO_TECHO_DE_F2]
    assert len(corpus.cases) == len(casos) == 73
    assert construir.CASO_REAL_DE_F2 in {c["id"] for c in casos if c.get("rol_en_hoja") == "real"}


def test_cada_caso_mecanico_discrimina_con_su_puntuador(afinidad):
    # El criterio 1, en su parte del corpus: la referencia buena puntua 1 y la mala, menos de 1. Si
    # falla, el caso esta mal construido: se corrige el caso, no el puntuador.
    _, datos, _ = afinidad
    analizar = construir.analizador()
    mecanicos = [
        c for c in datos["cases"] if c["discriminante"] and c["tool"] != "local_commit_msg"
    ]
    assert len(mecanicos) == 28
    for caso in mecanicos:
        ok = analizar.puntuar_afinidad(caso, caso["reference_ok"])
        malo = analizar.puntuar_afinidad(caso, caso["reference_bad"])
        assert ok == {"calidad": 1.0, "formato": True}, caso["id"]
        assert malo["calidad"] < 1.0, caso["id"]


def test_el_corpus_declara_lo_que_exige_la_spec(afinidad):
    _, datos, _ = afinidad
    por_id = {c["id"]: c for c in datos["cases"]}
    clasificar = [c for c in datos["cases"] if c["tool"] == "local_classify" and c["discriminante"]]
    assert all(len(c["puntuador"]["etiquetas"]) >= 4 for c in clasificar)
    assert all(
        set(c["puntuador"]["aceptables"]) <= set(c["puntuador"]["etiquetas"]) for c in clasificar
    )
    assert (
        "clasifica-bug-con-etiquetas-en-ingles" in por_id
    )  # etiquetas en ingles, texto en español
    extraer = [
        c["puntuador"]["esperado"]
        for c in por_id.values()
        if c["tool"] == "local_extract" and c["discriminante"]
    ]
    assert any(None in e.values() for e in extraer)  # un campo ausente que sale null
    assert any(isinstance(v, (int, float)) for e in extraer for v in e.values())  # numeros
    for caso in datos["cases"]:
        assert caso["procedencia"] and caso["origen"]
        if caso["kind"] == "calidad":
            assert caso["system"] and caso["user_template"] and caso["max_tokens"]
            assert caso["production"]["calls"] == 1, caso["id"]
        if caso["discriminante"]:
            assert caso["reference_ok"] and caso["reference_bad"], caso["id"]
    # Cada caso pide lo que la tool de produccion pide: el rol sale de la captura, no de una tabla.
    assert {c["role"] for c in datos["cases"] if c["tool"] == "local_commit_msg"} == {"code"}
    assert {c["role"] for c in datos["cases"] if c["tool"] == "local_classify"} == {"mechanical"}


def test_las_trampas_no_coinciden_con_ningun_caso_real_ni_se_repiten(afinidad):
    carpeta, datos, _ = afinidad
    reales = [c for c in datos["cases"] if c.get("rol_en_hoja") == "real"]
    trampas = [c for c in datos["cases"] if c.get("rol_en_hoja") == "trampa"]
    assert not {c["commit"] for c in reales} & {c["commit"] for c in trampas}
    assert not {c["source_sha256"] for c in reales} & {c["source_sha256"] for c in trampas}
    assert len({c["source_sha256"] for c in reales + trampas}) == 39
    trampas_json = json.loads((carpeta / "trampas.json").read_text(encoding="utf-8"))
    ids = []
    for juego in trampas_json["juegos"]:
        assert [t["tipo"] for t in juego["trampas"]] == ["misma-zona", "secundario", "generico"]
        for t in juego["trampas"]:
            assert len(t["asunto"]) <= 72 and 1 <= len(t["cuerpo"]) <= 5
            assert construir._PREFIJO_CONVENCIONAL.match(t["asunto"]), t["asunto"]
            ids.append(t["caso"])
    assert sorted(ids) == sorted(c["id"] for c in trampas)
    # Cada commit sale de la regla; la lista esta en cases.json.
    sel = datos["seleccion"]
    assert [x["hash"] for x in sel["reales"]] == [
        c["commit"] for c in reales if c["id"] != construir.CASO_REAL_DE_F2
    ]


def test_nada_privado_en_lo_que_va_al_repo(afinidad):
    carpeta, _, _ = afinidad
    for fichero in [
        carpeta / "cases.json",
        carpeta / "trampas.json",
        *sorted((carpeta / "fuentes").iterdir()),
    ]:
        if fichero.suffix in (".png",):
            continue
        texto = fichero.read_text(encoding="utf-8", errors="replace")
        assert construir.datos_privados(texto) == [], fichero.name


# --- El idioma del mensaje de commit entra en el prompt capturado (REQ-044) -----------------------
# Los casos de commit del corpus de afinidad llevan el prompt de produccion. Con
# `LOCAL_DELEGATE_COMMIT_IDIOMA=es`, que es lo que tendra la PC, ese prompt tiene que pedir espanol.
# La captura quita las variables del paquete del entorno, y esta es la excepcion.
_DIFF_CHICO = "diff --git a/uno.py b/uno.py\n--- a/uno.py\n+++ b/uno.py\n@@ -1 +1 @@\n-a\n+b\n"


def _system_de_commit_capturado(tmp_path) -> str:
    from local_delegate import server

    ruta = tmp_path / "chico.diff"
    ruta.write_text(_DIFF_CHICO, encoding="utf-8")
    with construir.produccion_interceptada() as llamadas:
        server.local_commit_msg(path=str(ruta))
    assert len(llamadas) == 1
    return llamadas[0].system


def test_la_captura_conserva_el_idioma_del_commit_de_la_maquina(tmp_path, monkeypatch):
    """Mutante: vaciar `VARIABLES_QUE_SE_CONSERVAN`. La captura borra la variable y el assert de
    `en español.` falla: el corpus se habria construido con el prompt de un entorno limpio."""
    monkeypatch.setenv("LOCAL_DELEGATE_COMMIT_IDIOMA", "es")
    system = _system_de_commit_capturado(tmp_path)
    assert "(primera línea y cuerpo) en español." in system
    assert os.environ["LOCAL_DELEGATE_COMMIT_IDIOMA"] == "es"  # y la deja como estaba


def test_la_captura_sin_la_variable_pide_el_idioma_del_diff(tmp_path):
    """Control del anterior: sin la variable, la captura sale con la otra orden."""
    assert "LOCAL_DELEGATE_COMMIT_IDIOMA" not in os.environ
    system = _system_de_commit_capturado(tmp_path)
    assert "en el idioma predominante de los textos del diff" in system
