"""El detector de nombres en español (`scripts/detect_spanish_names.py`, REQ-044).

Dos clases de prueba, y no valen lo mismo:

- **Regresión.** El léxico sale del propio repo, así que los 30 nombres españoles y los 54 ingleses
  conocidos se cumplen casi por construcción. Sirven para que nadie rompa el léxico o el troceo de
  nombres sin enterarse, no para demostrar que el detector funciona.
- **Control de las heurísticas.** Palabras **reservadas** (`scripts/data/reserved_words.json`) que
  no están en el léxico: ahí decide solo la heurística (eñe, tilde, sufijo), y es lo único que
  dice algo de una palabra que aparezca mañana en el repo.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "detect_spanish_names.py"

if not SCRIPT.is_file():
    pytest.skip(
        "scripts/ no está en el árbol (sdist): estas pruebas necesitan el repositorio",
        allow_module_level=True,
    )

_spec = importlib.util.spec_from_file_location("detect_spanish_names", SCRIPT)
assert _spec is not None and _spec.loader is not None
det = importlib.util.module_from_spec(_spec)
sys.modules["detect_spanish_names"] = det
_spec.loader.exec_module(det)

LEXICON = det.Lexicon.load()

# Los 30 de la investigación (rename §0). `tokensClaude` es el que se escapa: palabras inglesas en
# orden español, que una regla por palabras no puede ver.
KNOWN_SPANISH = (
    "bloqueo_id", "secciones", "fallo_conexion", "recalcular_coste", "enfriamiento", "cuota",
    "atribucion", "VARIABLES_DE_ENTORNO", "reiniciar_calibracion", "fundirFila", "tokensClaude",
    "aplicarBackend", "HOOK_READ_INTERRUPTOR", "rol_retirado", "config.coste",
    "local-delegate-bloqueo-apagado", "respaldo_invalido", "leido_server_side", "camino", "motivo",
    "densidad", "precios", "huella", "comprobaciones", "andamiaje", "entorno", "sondas",
    "preguntas", "valoracion", "cadenas",
)  # fmt: skip
# Los 52 del script de la investigación, más dos nombres ingleses del repo para llegar a los 54
# que cita rename §0 (`fallback` y `cooldown`).
KNOWN_ENGLISH = (
    "cooldown_failures", "test_windows", "build_parser", "max_chars", "tool_use_id",
    "caller_model", "error_class", "fallback_class", "saved", "returned", "net", "residency",
    "topology", "footprint", "inflight", "daemon", "status", "loaded", "model", "role", "install",
    "update", "pace", "matrix", "turn", "transcripts", "clients", "agents", "version", "benchmark",
    "metrics", "auth", "sysinfo", "chunk", "label", "start", "stop", "window", "no_restart",
    "general", "total", "real", "local", "error", "control", "base", "plan", "prompt", "hooks",
    "shell", "read", "suggest_delegate", "fallback", "cooldown",
)  # fmt: skip
JS_CONTROL_NAMES = ("claudeTokens", "applyBackend", "acct", "fmtNum", "decimals")


# --- Regresión ----------------------------------------------------------------
def test_regression_lists_have_the_research_sizes():
    assert len(KNOWN_SPANISH) == 30
    assert len(KNOWN_ENGLISH) == 54
    assert len(set(KNOWN_SPANISH)) == 30 and len(set(KNOWN_ENGLISH)) == 54


def test_detects_at_least_29_of_the_30_known_spanish_names():
    missed = [n for n in KNOWN_SPANISH if not det.detect(n)]
    assert len(missed) <= 1, missed


def test_no_known_english_name_is_a_false_positive():
    false_positives = [(n, det.spanish_words(n, LEXICON)) for n in KNOWN_ENGLISH if det.detect(n)]
    assert false_positives == []


def test_js_tokenizer_finds_the_five_panel_control_names():
    """Con un tokenizador malo se pierde código entero: el primero de la investigación vio 77 de
    311 declaraciones. Estos cinco nombres están repartidos por todo el `<script>`."""
    found = det._panel_html(ROOT)
    assert found is not None, "no se encontró el HTML del panel en metrics.py"
    html, _line = found
    scripts = re.findall(
        r"<script(?![^>]*src=)[^>]*>(.*?)</script[^>]*>", html, re.DOTALL | re.IGNORECASE
    )
    declared = {name for name, _l in det.js_declared_names(det.tokenize_js(scripts[-1]))}
    missing = [n for n in JS_CONTROL_NAMES if n not in declared]
    assert missing == []
    # Guarda de «esto llegó a comprobar algo»: el panel declara cientos de nombres.
    assert len(declared) > 250


# --- Control de las heurísticas -----------------------------------------------
RESERVED = json.loads((ROOT / "scripts" / "data" / "reserved_words.json").read_text("utf-8"))
RESERVED_SPANISH = [w for group in RESERVED["spanish"].values() for w in group]


def test_no_reserved_word_is_in_the_lexicon():
    """Si una reservada entrara en el léxico, su test pasaría por el léxico y no por la heurística."""
    leaked = [
        w
        for w in [*RESERVED_SPANISH, *RESERVED["english"]]
        if w in LEXICON or det.fold(w) in LEXICON.function_words
    ]
    assert leaked == []


@pytest.mark.parametrize("word", RESERVED_SPANISH)
def test_heuristics_detect_each_reserved_spanish_word(word):
    assert det.detect(word), f"{word} no se detecta como español"


@pytest.mark.parametrize("word", RESERVED["english"])
def test_heuristics_do_not_flag_lookalike_english_words(word):
    assert not det.detect(word), f"{word} se marca como español"


def test_new_word_without_heuristic_is_unclassified_not_english():
    """Que el léxico no se quede viejo en silencio: lo desconocido se informa aparte."""
    # Se arma en tiempo de ejecución: escrita entera, el propio detector la vería en este fichero.
    new_word = "zaran" + "dajas"
    assert new_word not in LEXICON
    assert det.classify_word(new_word, LEXICON) == "unclassified"
    assert det.unclassified_words(f"{new_word}_count", LEXICON) == [new_word]


def test_one_function_word_is_not_enough_but_two_are():
    assert not det.detect("en")
    assert det.detect("de_la")


# --- Tokenizador de JS ------------------------------------------------------
def test_regex_with_backtick_does_not_open_a_template():
    """La trampa de `metrics.py`: `.replace(/`([^`]+)`/g, …)`."""
    src = "x = s.replace(/`([^`]+)`/g, '<code>$1</code>');\nconst despues = 1;"
    tokens = det.tokenize_js(src)
    assert [t.kind for t in tokens if t.kind in ("regex", "template")] == ["regex"]
    assert ("despues", 2) in det.js_declared_names(tokens)


def test_division_is_not_mistaken_for_a_regex():
    tokens = det.tokenize_js("const a = b / c / d;")
    assert not [t for t in tokens if t.kind == "regex"]


def test_nested_templates_and_comments():
    src = (
        "// const fuera = 1;\n/* let tampoco = 2; */\nconst t = `a ${f(`b ${c}`)} d`;\nlet ultimo;"
    )
    declared = [n for n, _l in det.js_declared_names(det.tokenize_js(src))]
    assert declared == ["t", "ultimo"]


def test_function_and_arrow_parameters():
    src = "function fmt(n, decimales = 2){}\nconst g = (uno, {dos}) => uno;\nh = tres => tres;"
    declared = {n for n, _l in det.js_declared_names(det.tokenize_js(src))}
    assert {"fmt", "n", "decimales", "g", "uno", "dos", "tres"} <= declared


# --- Lista de excepciones (REQ-016) -------------------------------------------
def test_exception_list_sets_aside_only_its_name_and_file(tmp_path):
    exceptions = tmp_path / "rename-exceptions.md"
    exceptions.write_text(
        "# Excepciones\n\n## Alias de compatibilidad\n\n"
        "| Nombre | Fichero | Motivo |\n| --- | --- | --- |\n"
        "| `recalcular-coste` | `src/local_delegate/cli.py` | alias, se retira en la 0.38.0 |\n",
        encoding="utf-8",
    )
    entries = det.load_exceptions(exceptions)
    assert [(e.name, e.section) for e in entries] == [
        ("recalcular-coste", "Alias de compatibilidad")
    ]
    scan = det.Scan()
    scan.add("string_value", "src/local_delegate/cli.py", 1, "recalcular-coste")
    scan.add("string_value", "src/local_delegate/otro.py", 1, "recalcular-coste")
    report = det.analyse(scan, LEXICON, entries)
    assert report["unique_findings"] == 2
    assert report["outside_exceptions"] == 1
    assert report["findings"][0]["file"] == "src/local_delegate/otro.py"


def test_change_exception_list_exists_and_parses():
    path = ROOT / ".sdd" / "changes" / "english-names-bilingual-output" / "rename-exceptions.md"
    if not path.is_file():
        pytest.skip("la carpeta del cambio no está en este árbol")
    entries = det.load_exceptions(path)
    # Tras A0 solo hay excepciones para los datos de prueba del propio detector; cada ola añade
    # las suyas con su motivo.
    assert entries, "la lista debe parsear al menos las filas de los datos del detector"
    assert all(e.reason.strip() for e in entries), "toda excepción lleva su motivo"


def test_detector_walks_a_tree_and_sees_each_category(tmp_path):
    """Un no-resultado no vale si la búsqueda no podía encontrar nada: árbol sembrado a mano."""
    pkg = tmp_path / "src" / "local_delegate"
    (pkg / "resources").mkdir(parents=True)
    (pkg / "cuota.py").write_text(
        'def leer_precios(x):\n    return {"motivo": x.get("camino"), "k": "fallo_conexion"}\n',
        encoding="utf-8",
    )
    (pkg / "resources" / "datos.json").write_text('{"familia": "nueva"}', encoding="utf-8")
    report = det.analyse(det.collect(tmp_path), LEXICON)
    names = {(f["category"], f["name"]) for f in report["findings"]}
    assert {
        ("identifier", "leer_precios"),
        ("string_key", "motivo"),
        ("string_key", "camino"),
        ("string_value", "fallo_conexion"),
        ("json_key", "familia"),
        ("file_name", "cuota"),
    } <= names
