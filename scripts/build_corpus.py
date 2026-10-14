#!/usr/bin/env python3
"""Congela las fuentes y construye el corpus v2 de la tanda de F2 (tarea 14 del SDD).

Dos cosas que este script NO deja a mano, porque a mano ya fallaron:

- El rol y el numero de llamadas de cada caso no se escriben: se CAPTURAN llamando a la tool real
  de `server.py` con el backend interceptado. Asi «cada caso de calidad cabe en una sola llamada»
  se comprueba contra el codigo de produccion y no contra una tabla copiada, que es como se colo
  un `traducir-14k` que en produccion eran varios trozos.
- Los conteos del log los emite el programa. Contarlos a mano mezclo 152 eventos con 146.

La captura no toca el backend, no escribe en el log de uso real y corre sin las variables
`LOCAL_DELEGATE_*` del entorno, igual que la suite: un `MAX_CHARS` cambiado en tu shell no puede
colarse en el corpus.

El subcomando `affinity` construye el corpus de la evaluacion de afinidad del SDD
`daemon-reparte-el-backend` (REQ-040, `benchmarks/afinidad-2026-10/`): casos mecanicos con su
puntuador, los 30 commits de la regla escrita, las trampas y el techo. Captura los prompts
llamando a las tools reales con el backend interceptado; no carga ningun modelo.

Uso:

    uv run python scripts/build_corpus.py affinity     # corpus de afinidad (ver --help)
    uv run python scripts/build_corpus.py              # congela, captura, comprueba, escribe
    uv run python scripts/build_corpus.py --check      # recaptura contra lo versionado
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

from local_delegate import benchmark, config, legacy_names, server

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "benchmarks" / "catalogo-2026-09"
MARKER = "{CONTENIDO}"

Source = Callable[[Path], bytes]
Terms = tuple[str, ...] | Callable[[str], tuple[str, ...]]


# --- Fuentes -----------------------------------------------------------------------------------


def normalized(data: bytes) -> str:
    """Lo que ve el modelo: `_read_input` lee con `read_text`, que convierte `\\r\\n` en `\\n`."""
    text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def file_source(rel: str) -> Source:
    return lambda root: (root / rel).read_bytes()


def cut_by_lines(rel: str, limit: int, boundary: str | None = None) -> Source:
    """Lineas enteras hasta `limit` chars; con `boundary`, corta antes de una linea que case."""

    def generate(root: Path) -> bytes:
        return cut_lines(normalized((root / rel).read_bytes()), limit, boundary).encode()

    return generate


def cut_lines(text: str, limit: int, boundary: str | None = None) -> str:
    lines = text.splitlines(keepends=True)
    accumulated = 0
    cut = 0
    for index, line in enumerate(lines):
        if accumulated + len(line) > limit:
            break
        accumulated += len(line)
        next_one = lines[index + 1] if index + 1 < len(lines) else ""
        if boundary is None or re.match(boundary, next_one):
            cut = index + 1
    return "".join(lines[:cut])


def exact_cut(rel: str, limit: int) -> Source:
    """Los primeros `limit` chars sin buscar frontera: lo que `_read_input` deja ver al modelo."""
    return lambda root: normalized((root / rel).read_bytes())[:limit].encode("utf-8")


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def commit_diff(commit: str) -> Source:
    return lambda root: _git(root, "show", "--format=", "--no-color", "--no-ext-diff", commit)


def blob(commit: str, rel: str) -> Source:
    return lambda root: _git(root, "show", f"{commit}:{rel}")


def whole_files(output: str, limit: int) -> str:
    """Los avisos de ruff de los primeros archivos, ENTEROS, mientras quepan en `limit` chars.

    Un archivo cortado a medias daria conteos que la fuente no respalda. Lo que no es un aviso
    (`Found N errors.`) queda en su propio bloque, al final, y no se alcanza.
    """
    blocks: dict[str, list[str]] = {}
    for line in output.splitlines(keepends=True):
        blocks.setdefault(line.split(":", 1)[0], []).append(line)
    chosen: list[str] = []
    accumulated = 0
    for lines in blocks.values():
        size = sum(len(line) for line in lines)
        if accumulated + size > limit:
            break
        chosen += lines
        accumulated += size
    return "".join(chosen)


def ruff_output_by_file(limit: int) -> Source:
    def generate(root: Path) -> bytes:
        process = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select", "ALL"]
            + ["--output-format", "concise", "--no-cache", "src/local_delegate"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # ruff sale con 1 cuando encuentra algo, que es justo lo que se quiere. Las barras se
        # normalizan para que la salida no dependa del sistema en que se genero.
        return whole_files(process.stdout.replace("\\", "/"), limit).encode("utf-8")

    return generate


def version_sections(rel: str, since: str, until: str) -> Source:
    """Del `## [desde]` hasta antes de `## [hasta]`. Las secciones publicadas no cambian: el
    CHANGELOG solo crece por arriba, asi que el recorte es reproducible aunque el fichero no."""

    def generate(root: Path) -> bytes:
        text = normalized((root / rel).read_bytes())
        start = text.index(f"## [{since}]")
        return text[start : text.index(f"## [{until}]", start)].encode("utf-8")

    return generate


def literal_text(content: str) -> Source:
    return lambda _root: content.encode("utf-8")


# --- Terminos derivados de la fuente, no escritos a ojo -----------------------------------------


def _first_ones(pattern: str, n: int = 3, group: int = 1) -> Callable[[str], tuple[str, ...]]:
    def derive(text: str) -> tuple[str, ...]:
        seen: list[str] = []
        for match in re.finditer(pattern, text, flags=re.MULTILINE):
            value = match.group(group)
            if value not in seen:
                seen.append(value)
            if len(seen) == n:
                break
        return tuple(seen)

    return derive


def _most_frequent_rules(text: str) -> tuple[str, ...]:
    count = Counter(re.findall(r": ([A-Z]+[0-9]+) ", text))
    return tuple(rule for rule, _ in count.most_common(3))


# Segundo piloto de CP-3: el 2B se invento los conteos de lint y la cobertura no lo veia. Para cada
# regla que el caso pide nombrar, los numeros que la fuente respalda: el total, cuantos archivos la
# tienen y lo que suma en cada archivo. Salen de las lineas de ruff, no de lo que dijo un modelo.
def _rule_counts(text: str) -> dict[str, list[int]]:
    per_rule: dict[str, Counter[str]] = {}
    for file, rule in re.findall(r"^(\S+?):\d+:\d+: ([A-Z]+[0-9]+) ", text, flags=re.MULTILINE):
        per_rule.setdefault(rule, Counter())[file] += 1
    return {
        rule: sorted({sum(per_rule[rule].values()), len(per_rule[rule]), *per_rule[rule].values()})
        for rule in _most_frequent_rules(text)
    }


def requested_format(system: str | None) -> dict[str, Any]:
    """Lo que la instruccion de la tool pide de forma comprobable: limite de palabras y prosa.

    P-15: el usuario descarto respuestas por salirse de las dos cosas, y la cobertura de terminos no
    lo miraba. Sale del prompt capturado de la tool real, no de lo que devolvio un modelo.
    """
    if not system:
        return {}
    fmt: dict[str, Any] = {}
    if limit := re.search(r"M[aá]ximo (\d+) palabras", system):
        fmt["max_words"] = int(limit.group(1))
    if re.search(r"\bprosa\b", system):
        fmt["prose"] = True
    return fmt


def _module_docstring(text: str) -> str:
    parts = text.split('"""')
    return parts[1] if len(parts) > 2 else ""


# «Explica que hace el codigo y como» no pide nombrar helpers privados, y CP-3 (tarea 19) lo
# demostro: con los tres primeros `def` del fichero, dos explicaciones correctas sacaban 0. Lo que la
# explicacion SI tiene que cubrir es lo que el modulo declara de si mismo en su docstring: sus rutas
# o los ficheros y opciones que toca. Mas terminos, ademas, dan granularidad a la banda (P-12).
def _docstring_paths(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"GET (/api/\S+)", _module_docstring(text))))


def _docstring_files_and_flags(text: str) -> tuple[str, ...]:
    quoted = re.findall(r"`([^`]+)`", _module_docstring(text))
    files = [re.sub(r".*/", "", t) for t in quoted if re.search(r"\.(json|md|bak)$", t)]
    flags = [t for t in quoted if t.startswith("--")]
    return tuple(dict.fromkeys(files + flags))


# Un mensaje de commit tiene que nombrar el cambio, y el diff trae como lo nombro su autor: la
# primera entrada «Fixed» que anade al CHANGELOG. Con un unico termino (`inflight`), CP-3 dio 0 al
# mensaje que nombraba el arreglo y al que solo nombraba el bump de version. Se quitan los privados
# (`_x`) y los comandos con espacios; de una ruta a fichero se queda el nombre.
def _first_fix_identifiers(text: str) -> tuple[str, ...]:
    lines = text.splitlines()
    start = next((n for n, line in enumerate(lines) if line == "+### Fixed"), None)
    if start is None:
        return ()
    entry: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("+"):
            break
        body = line[1:]
        if body.startswith("#") or (body.startswith("- ") and entry):
            break
        if body.startswith("- ") or entry:
            entry.append(body)
    clean = []
    for term in re.findall(r"`([^`]+)`", " ".join(entry)):
        if " " in term or term.startswith("_"):
            continue
        last = term.rsplit("/", 1)[-1]
        clean.append((last if "." in last else term).removesuffix("()"))
    return tuple(dict.fromkeys(clean))


# Un resumen de un changelog tiene que decir que cambio, y cada entrada lo resume en su titular en
# negrita. Antes eran los numeros de version, que el prompt («resumen en prosa») no pide: CP-3 los
# dio a 0 en los dos modelos, un suelo.
def _headline_identifiers(text: str) -> tuple[str, ...]:
    headlines = re.findall(r"^- \*\*(.+?)\*\*", text, flags=re.MULTILINE | re.DOTALL)
    return tuple(
        dict.fromkeys(
            term.removesuffix("()")
            for headline in headlines
            for term in re.findall(r"`([^`]+)`", headline)
        )
    )


def _toml_values(*keys: str) -> Callable[[str], tuple[str, ...]]:
    def derive(text: str) -> tuple[str, ...]:
        values = []
        for key in keys:
            match = re.search(rf'^{re.escape(key)} = "?([^"\n]+)"?$', text, flags=re.MULTILINE)
            if match:
                values.append(match.group(1))
        return tuple(values)

    return derive


# --- Casos (protocolo-f2.md §4.4) -----------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    id: str
    tool: str
    role: str
    kind: str
    provenance: str
    origin: str
    source: Source
    extension: str = "txt"
    media_type: str = "text"
    arguments: dict[str, Any] = field(default_factory=dict)
    expected_terms: Terms = ()
    forbidden_terms: tuple[str, ...] = ()
    expected_json_fields: tuple[str, ...] = ()
    # Los terminos esperados tienen que estar en la fuente, salvo donde la salida no la copia:
    # una traduccion, una etiqueta elegida o lo que se ve en una imagen.
    terms_in_source: bool = True
    # Pareja de referencia de CP-4: (senal, respuesta buena, respuesta mala). Solo en seis casos.
    reference: tuple[str, str, str] | None = None
    # Comprobaciones que el puntuador EJECUTA sobre el codigo generado: {"expr", "expected"} o
    # {"expr", "raises"}. Salen de la especificacion del caso, no de lo que devolvio un modelo.
    checks: tuple[dict[str, Any], ...] = ()
    # Conteos que el puntuador comprueba contra la fuente, derivados de ella: {regla: validos}.
    counts: Callable[[str], dict[str, list[int]]] | None = None
    # False: la regla de §7 no lo cuenta y lo juzga solo la revision a ciegas (§4.8).
    automatic_score: bool = True


_TOP_LEVEL_PY = r"^(?:def |class |async def |@)"

# Referencia de CP-4 para la senal de ejecucion: la buena y la mala solo difieren en el factor de
# los minutos, asi que tienen la misma longitud, los mismos terminos y las dos cargan sin error.
_PARSE_DURATION = (
    "import re\n"
    "\n"
    "\n"
    "def parse_duration(texto):\n"
    "    \"\"\"Convierte '1h30m', '45s' o '2m' en segundos.\"\"\"\n"
    '    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", texto)\n'
    "    if not texto or m is None:\n"
    '        raise ValueError(f"formato no valido: {texto!r}")\n'
    "    h, mi, s = (int(g) if g else 0 for g in m.groups())\n"
    "    return h * 3600 + mi * {MINUTO} + s\n"
)

CASES: tuple[Case, ...] = (
    # --- mechanical ---
    Case(
        "resumen-md-2k",
        "local_summarize",
        "mechanical",
        "quality",
        "frozen",
        "CONTRIBUTING.md",
        file_source("CONTRIBUTING.md"),
        extension="md",
        expected_terms=("pre-commit", "pull request"),
        reference=(
            "coverage",
            (
                "Guía para contribuir: el entorno de desarrollo, cómo ejecutar el MCP en local, las "
                "reglas del proyecto, cómo abrir un pull request y el uso de pre-commit."
            ),
            (
                "Guía para contribuir: el entorno de desarrollo, cómo ejecutar el MCP en local, las "
                "reglas del proyecto, cómo abrir un merge commit y el uso de pre-commit."
            ),
        ),
    ),
    Case(
        "extraer-toml-2k",
        "local_extract",
        "mechanical",
        "quality",
        "frozen",
        "pyproject.toml, recortado en linea entera a 2 100 chars (entero pesa mas de 6 000 y "
        "produccion lo mandaria a long)",
        cut_by_lines("pyproject.toml", 2100),
        extension="toml",
        expected_json_fields=("name", "version", "requires-python", "license"),
        expected_terms=_toml_values("name", "version", "requires-python", "license"),
        reference=(
            "json_valid",
            (
                '{"name": "local-delegate-mcp", "version": "0.27.0", "requires-python": ">=3.11", '
                '"license": "MIT"}'
            ),
            (
                "{'name': 'local-delegate-mcp', 'version': '0.27.0', 'requires-python': '>=3.11', "
                "'license': 'MIT'}"
            ),
        ),
    ),
    Case(
        "clasificar-53",
        "local_classify",
        "mechanical",
        "quality",
        "reconstructed",
        "evento inline real de 53 chars; texto recreado con esa forma",
        literal_text("El dashboard dejó de cargar tras actualizar a 0.27.0."),
        arguments={"labels": ["bug", "feature", "docs", "pregunta"]},
        expected_terms=("bug",),
        forbidden_terms=("feature", "docs", "pregunta"),
        terms_in_source=False,
    ),
    Case(
        "traducir-42",
        "local_translate",
        "mechanical",
        "quality",
        "reconstructed",
        "evento inline real de 42 chars; texto recreado con esa forma",
        literal_text("Reinicia el daemon después de actualizarlo"),
        arguments={"target_lang": "inglés"},
        expected_terms=("restart", "daemon", "updat"),
        forbidden_terms=("reinicia",),
        terms_in_source=False,
    ),
    Case(
        "delegar-56",
        "local_delegate",
        "mechanical",
        "quality",
        "reconstructed",
        "evento inline real de 56 chars; texto recreado con esa forma",
        literal_text("tokens, latencia, modelo, errores, reintentos y el coste"),
        arguments={
            "task": "Convierte esta enumeración en una lista con una viñeta por elemento.",
            "output_format": "lista Markdown con una viñeta '- ' por elemento",
        },
        expected_terms=("tokens", "latencia", "modelo", "errores", "reintentos", "coste"),
    ),
    # --- long ---
    Case(
        "resumen-md-10k",
        "local_summarize",
        "long",
        "quality",
        "frozen",
        "docs/recipes/claude-code-hooks.md",
        file_source("docs/recipes/claude-code-hooks.md"),
        extension="md",
        expected_terms=("UserPromptSubmit", "PreToolUse", "LD_HOOK_READ_BLOQUEAR"),
        # P-15: la cobertura de terminos no coincidio con el juicio humano (0 de 3, invertida). Lo
        # decide la comparacion por pares a ciegas; los terminos se quedan como dato.
        automatic_score=False,
    ),
    Case(
        # Tarea 19: sustituye a `resumen-changelog-43k`, cuyos terminos eran un suelo. Dos secciones
        # y no una: la 0.27.0 sola pesa 5 507 chars, bajo LONG_INPUT_CHARS, y produccion la
        # mandaria a mechanical. Son las mismas que abrian la fuente congelada anterior.
        "resumen-changelog-7k",
        "local_summarize",
        "long",
        "quality",
        "frozen",
        "CHANGELOG.md, secciones 0.27.0 y 0.26.0",
        version_sections("CHANGELOG.md", "0.27.0", "0.25.0"),
        extension="md",
        expected_terms=_headline_identifiers,
        automatic_score=False,  # P-15: 3 de 4 contra el juicio humano; lo deciden los pares
    ),
    Case(
        "extraer-uvlock-48k",
        "local_extract",
        "long",
        "quality",
        "frozen",
        "uv.lock, recortado a los 48 000 chars que `_read_input` deja ver al rol long",
        exact_cut("uv.lock", 48000),
        extension="lock",
        expected_json_fields=("version", "requires-python", "primer_paquete"),
        # `version = 1` no sirve de termino: un «1» aparece en cualquier respuesta.
        expected_terms=lambda text: (
            _toml_values("requires-python")(text)
            + _first_ones(r'^\[\[package\]\]\nname = "([^"]+)"', n=1)(text)
        ),
        reference=(
            "json_fields",
            '{"version": 1, "requires-python": ">=3.11", "primer_paquete": "annotated-doc"}',
            '{"version": 1, "requires-python": ">=3.11", "paquete_primer": "annotated-doc"}',
        ),
    ),
    Case(
        # Segundo piloto de CP-3: `lint-33k` (14 archivos, 48 reglas) no cabia «agrupado por archivo»
        # en 200 palabras, y los dos modelos truncaban siempre. Archivos enteros hasta 9 000 chars:
        # sigue por encima de LONG_INPUT_CHARS, asi que produccion la manda a long.
        "lint-9k",
        "local_lint_summary",
        "long",
        "quality",
        "generated",
        "ruff check --select ALL --output-format concise --no-cache src/local_delegate, "
        "archivos enteros hasta 9 000 chars",
        ruff_output_by_file(9000),
        expected_terms=_most_frequent_rules,
        counts=_rule_counts,
        # Tercer piloto de CP-3: 0 en los dos modelos otra vez. El 2B se inventa los conteos y el 14B
        # los da bien pero lista TODO y trunca: el prompt de la tool no cabe con esta entrada, y eso
        # se arregla en la tool (F3). Lo juzga la revision a ciegas (decision del usuario).
        automatic_score=False,
        # Pareja de CP-4 de conteos: las dos nombran las tres reglas; la mala cambia un 7 por un 9,
        # que no es ni el total, ni los archivos, ni lo de ningun archivo.
        reference=(
            "counts",
            "COM812: 16 avisos en 2 archivos. TRY003: 8. D102: 7.",
            "COM812: 16 avisos en 2 archivos. TRY003: 8. D102: 9.",
        ),
    ),
    # --- code ---
    Case(
        "commit-diff-19k",
        "local_commit_msg",
        "code",
        "quality",
        "frozen",
        "git show 4d644ae (fix(web): inflight multi-proceso)",
        commit_diff("4d644ae"),
        extension="diff",
        expected_terms=_first_fix_identifiers,
        # Dos pilotos de CP-3 con 0 en los dos modelos: un asunto de <=72 chars rara vez lleva
        # identificadores y el cuerpo es opcional. Lo juzga la revision a ciegas (decision del
        # usuario, 2026-09-14); los terminos se quedan como dato.
        automatic_score=False,
    ),
    Case(
        "explicar-metrics-15k",
        "local_explain_code",
        "code",
        "quality",
        "frozen",
        "src/local_delegate/web/metrics.py, recortado antes de un bloque de nivel superior",
        cut_by_lines("src/local_delegate/web/metrics.py", 17000, _TOP_LEVEL_PY),
        extension="py.txt",
        expected_terms=_docstring_paths,
        automatic_score=False,  # P-15: sin base contra el juicio humano; lo deciden los pares
    ),
    Case(
        "explicar-install-20k",
        "local_explain_code",
        "code",
        "quality",
        "frozen",
        "src/local_delegate/install.py, recortado a los 20 000 chars que ve el rol code",
        exact_cut("src/local_delegate/install.py", 20000),
        extension="py.txt",
        expected_terms=_docstring_files_and_flags,
        automatic_score=False,  # P-15: 2 de 4 contra el juicio humano; lo deciden los pares
    ),
    Case(
        "boilerplate-156",
        "local_boilerplate",
        "code",
        "quality",
        "reconstructed",
        "evento inline real de 156 chars; especificacion recreada con esa forma",
        literal_text(
            "Función parse_duration(texto) que convierta '1h30m', '45s' o '2m' en segundos "
            "(int) y lance ValueError si el formato no es válido. Con docstring y ejemplos."
        ),
        arguments={"language": "python"},
        expected_terms=("parse_duration", "ValueError"),
        # CP-3 (tarea 19) dio 1,0 por terminos a dos funciones rotas. Una por ejemplo de la
        # especificacion (y `expected` exige el tipo: pide un int) y dos formatos invalidos, que
        # la especificacion dice que lanzan ValueError.
        checks=(
            {"expr": "parse_duration('1h30m')", "expected": 5400},
            {"expr": "parse_duration('45s')", "expected": 45},
            {"expr": "parse_duration('2m')", "expected": 120},
            {"expr": "parse_duration('abc')", "raises": "ValueError"},
            {"expr": "parse_duration('5x')", "raises": "ValueError"},
        ),
        reference=(
            "execution",
            _PARSE_DURATION.replace("{MINUTO}", "60"),
            _PARSE_DURATION.replace("{MINUTO}", "61"),
        ),
    ),
    # --- vision ---
    Case(
        "describir-dashboard",
        "local_describe_image",
        "vision",
        "quality",
        "frozen",
        "docs/assets/dashboard.png",
        file_source("docs/assets/dashboard.png"),
        extension="png",
        media_type="image",
        # `computo` va SIN acento a proposito, y el panel dice «cómputo»: es el termino que solo
        # casa si el puntuador normaliza. Sin el, la pareja de Unicode de CP-4 no tendria donde caer.
        expected_terms=("delegaciones", "backend", "ahorro", "computo"),
        reference=(
            "unicode",
            "Panel de ahorro con el estado del backend, las delegaciones y dónde corrió el cómputo.",
            "Panel de ahorro con el estado del backend, las delegaciones y dónde corrió el cálculo.",
        ),
        terms_in_source=False,
    ),
    Case(
        "leer-cifras-dashboard",
        "local_describe_image",
        "vision",
        "quality",
        "made_up",
        "docs/assets/dashboard.png con una pregunta que no corresponde a ningun evento real",
        file_source("docs/assets/dashboard.png"),
        extension="png",
        media_type="image",
        arguments={
            # Las seis cifras grandes del panel son IDENTICAS en esta imagen y en la de control
            # (datos de demostracion fijos): preguntar por ellas no podria bajar con la imagen
            # equivocada. Se pregunta por lo que si cambia entre las dos.
            "question": (
                "¿Qué versión muestra la insignia junto al logo, y qué fecha y hora tiene la "
                "primera fila de «Actividad reciente»? Responde solo con esos tres datos."
            )
        },
        expected_terms=("0.27.0", "29/8", "05:01"),
        reference=(
            "forbidden",
            "Versión 0.27.0 (la publicada); primera fila: 29/8 a las 05:01.",
            "Versión 0.27.0 (antes 0.24.0); primera fila: 29/8 a las 05:01.",
        ),
        forbidden_terms=("0.24.0", "24/7", "23:12"),
        terms_in_source=False,
    ),
    # --- sondeos de techo: no puntuan calidad ---
    Case(
        "techo-resumen-103k",
        "local_summarize",
        "long",
        "ceiling",
        "frozen",
        "src/local_delegate/server.py entero",
        file_source("src/local_delegate/server.py"),
        extension="py.txt",
    ),
    Case(
        "techo-commit-156k",
        "local_commit_msg",
        "code",
        "ceiling",
        "reconstructed",
        "git show d7c3dcc: el diff de 164 585 chars del log ya no existe; este es el mayor del "
        "historial de ese orden",
        commit_diff("d7c3dcc"),
        extension="diff",
    ),
)

CONTROLS = (
    {
        "id": "dashboard-bcbe39f",
        "para": ["describir-dashboard", "leer-cifras-dashboard"],
        "provenance": "frozen",
        "origin": "git show bcbe39f:docs/assets/dashboard.png (0.24.0)",
        "source": blob("bcbe39f", "docs/assets/dashboard.png"),
        "extension": "png",
    },
)


# --- Captura contra el codigo de produccion -----------------------------------------------------


# Lo que la captura NO quita del entorno: el idioma del mensaje de commit (REQ-044) es parte del prompt
# de produccion de `local_commit_msg`, y los casos de commit del corpus de afinidad tienen que llevar
# el prompt con el idioma que tendra la maquina (`LOCAL_DELEGATE_COMMIT_LANGUAGE=es`), no el de un
# entorno limpio. `config.commit_language()` lee al llamar, asi que no hace falta recargar `config`.
# Con la variable puesta, el corpus que sale cambia: `main_affinity` imprime el idioma usado y
# `affinity --check` tiene que correr con el mismo.
PRESERVED_VARIABLES = frozenset({"LOCAL_DELEGATE_COMMIT_LANGUAGE"})


@dataclass
class Call:
    model: str
    system: str
    user: Any
    max_tokens: int
    temperature: float
    response_format: dict | None


@contextlib.contextmanager
def intercepted_production() -> Iterator[list[Call]]:
    """Las tools reales, sin backend, sin log de uso y sin las variables del paquete."""
    calls: list[Call] = []
    saved = {
        n: os.environ[n]
        for n in config.ENVIRONMENT_VARIABLES
        if n in os.environ and n not in PRESERVED_VARIABLES
    }

    def run_chat(model, system, user, max_tokens, temperature, *, response_format=None, **_):
        calls.append(Call(model, system, user, max_tokens, temperature, response_format))
        result = server.ChatResult(text="{}", ok=True, finish_reason="stop")
        return result, 0, None, [server.Attempt(model, True, None, None, 0)]

    try:
        # Solo se recarga si habia algo que quitar: dentro de la suite el entorno ya viene limpio,
        # y recargar desharia el LOG_DIR temporal de conftest y apuntaria al log real.
        for name in saved:
            del os.environ[name]
        if saved:
            importlib.reload(config)
        with (
            mock.patch.object(server, "_run_chat", run_chat),
            mock.patch.object(server, "_log_event", lambda **_: None),
            mock.patch.object(server, "_inflight_start", lambda **_: 0),
            mock.patch.object(server, "_inflight_end", lambda *_: None),
            # Un LOCAL_DELEGATE_ALLOWED_DIRS del usuario no debe impedir leer las fuentes.
            mock.patch.object(server, "_check_allowed_dir", lambda _path: None),
        ):
            yield calls
    finally:
        os.environ.update(saved)
        if saved:
            importlib.reload(config)


def production_roles() -> dict[str, str]:
    return {
        config.MODEL_MECHANICAL: "mechanical",
        config.MODEL_LONG: "long",
        config.MODEL_CODE: "code",
        config.MODEL_VISION: "vision",
    }


def invoke(case: Case, path: Path, text: str, tmp: Path) -> None:
    args = case.arguments
    tool = case.tool
    if tool == "local_summarize":
        server.local_summarize(path=str(path))
    elif tool == "local_extract":
        server.local_extract(fields=list(case.expected_json_fields), path=str(path))
    elif tool == "local_lint_summary":
        server.local_lint_summary(path=str(path))
    elif tool == "local_commit_msg":
        server.local_commit_msg(path=str(path))
    elif tool == "local_explain_code":
        server.local_explain_code(path=str(path))
    elif tool == "local_describe_image":
        server.local_describe_image(path=str(path), question=args.get("question"))
    elif tool == "local_classify":
        server.local_classify(text=text, labels=args["labels"])
    elif tool == "local_translate":
        server.local_translate(target_lang=args["target_lang"], text=text)
    elif tool == "local_delegate":
        server.local_delegate(task=args["task"], input=text, output_format=args["output_format"])
    elif tool == "local_boilerplate":
        server.local_boilerplate(
            spec=text, language=args["language"], target=str(tmp / "generated.txt")
        )
    else:
        raise ValueError(f"tool sin invocacion: {tool}")


@dataclass
class Capture:
    calls: list[Call]
    role: str | None
    models: set[str]
    whole_input: bool
    user_template: str | None


def capture_case(case: Case, path: Path, data: bytes, *, no_chunking: bool = False) -> Capture:
    """Con `no_chunking`, la tool sigue la ruta de UNA llamada aunque la entrada no quepa: es el
    prompt que necesita un sondeo de techo, que mide justo la mayor llamada unica que acepta el
    modelo. Produccion no lo manda nunca asi; por eso se captura aparte."""
    text = normalized(data) if case.media_type == "text" else ""
    with intercepted_production() as calls, tempfile.TemporaryDirectory() as tmp:
        # Los dos topes: el del rol (modelo principal de cada tool) y el del modelo (respaldos).
        unlimited = mock.patch.multiple(
            config, max_chars_for=lambda _model: 2**31, max_chars_for_role=lambda _role: 2**31
        )
        with unlimited if no_chunking else contextlib.nullcontext():
            invoke(case, path, text, Path(tmp))
        roles = production_roles()
    models = {call.model for call in calls}
    role = roles.get(calls[0].model) if calls else None
    whole_input = False
    template = None
    if len(calls) == 1:
        user = calls[0].user
        if case.media_type == "image" and isinstance(user, list):
            image = base64.b64encode(data).decode("ascii")
            whole_input = any(image in json.dumps(block) for block in user)
            template = next(b["text"] for b in user if b.get("type") == "text")
        elif isinstance(user, str) and text and text in user:
            whole_input = True
            template = user.replace(text, MARKER, 1)
    return Capture(calls, role, models, whole_input, template)


def terms(case: Case, text: str) -> tuple[str, ...]:
    return case.expected_terms(text) if callable(case.expected_terms) else case.expected_terms


# --- Parejas de referencia de CP-4 (tarea 15) ---------------------------------------------------

# Las senales en que TIENE que diferir cada pareja, y ninguna mas. Si difiere en otra, CP-4 no podra
# decir por que separo el puntuador. `literal_coverage` es la cobertura sin normalizar: la pareja de
# Unicode es la unica donde NO cambia, porque su buena solo acierta quitando acentos, y un puntuador
# literal puntuaria igual de mal las dos. `json_fields` acompana a `json_valid` por construccion:
# sin JSON no hay campos que mirar.
EXPECTED_DIFFERENCES: dict[str, set[str]] = {
    "coverage": {"coverage", "literal_coverage"},
    "forbidden": {"forbidden"},
    "json_valid": {"json_valid", "json_fields"},
    "json_fields": {"json_fields"},
    "unicode": {"coverage"},
    "execution": {"execution"},
    "counts": {"counts"},
}


def _loose_integers(span: str) -> list[int]:
    """Tiradas de digitos que no pegan a una letra, un digito o `_`, ni forman un decimal. Un punto
    de final de frase no las anula. Recorrido a mano, sin las expresiones del puntuador: es su
    oraculo."""
    integers: list[int] = []
    i = 0
    while i < len(span):
        if not span[i].isdigit():
            i += 1
            continue
        j = i
        while j < len(span) and span[j].isdigit():
            j += 1
        before = span[i - 1] if i else " "
        after = span[j] if j < len(span) else " "
        decimal = after == "." and j + 1 < len(span) and span[j + 1].isdigit()
        if not (before.isalnum() or before in "._") and not (
            after.isalnum() or after == "_" or decimal
        ):
            integers.append(int(span[i:j]))
        i = j
    return integers


def _spans_per_rule(line: str) -> list[tuple[str, str]]:
    """(codigo, lo que le sigue hasta el siguiente codigo) de cada codigo de regla de la linea."""
    spans: list[tuple[str, str]] = []
    current: str | None = None
    chunk: list[str] = []
    i = 0
    while i < len(line):
        if line[i].isupper() and (i == 0 or not line[i - 1].isalnum()):
            letters = i
            while letters < len(line) and line[letters].isupper():
                letters += 1
            end = letters
            while end < len(line) and line[end].isdigit():
                end += 1
            if end > letters and (end == len(line) or not line[end].isalnum()):
                if current is not None:
                    spans.append((current, "".join(chunk)))
                current, chunk = line[i:end], []
                i = end
                continue
        if current is not None:
            chunk.append(line[i])
        i += 1
    if current is not None:
        spans.append((current, "".join(chunk)))
    return spans


def _counts_add_up(text: str, counts: Mapping[str, Sequence[int]]) -> bool:
    numbers: dict[str, list[int]] = {rule: [] for rule in counts}
    for line in text.split("\n"):
        for rule, span in _spans_per_rule(line):
            if rule in numbers:
                numbers[rule] += _loose_integers(span)
    return all(numbers[rule] and set(numbers[rule]) <= set(valid) for rule, valid in counts.items())


def _runs_ok(code: str, checks: Sequence[dict[str, Any]]) -> bool:
    """El oraculo de la senal de ejecucion, en proceso y sin el arnes del puntuador: si los dos
    compartieran codigo compartirian tambien el error. Solo corre referencias escritas a mano."""
    space: dict[str, Any] = {"__name__": "referencia"}
    try:
        exec(compile(code, "referencia", "exec"), space)  # noqa: S102 - referencia propia
    except Exception:
        return False
    for check_result in checks:
        try:
            value = eval(check_result["expr"], space)
        except Exception as exc:
            if type(exc).__name__ != check_result.get("raises"):
                return False
            continue
        expected = check_result.get("expected")
        if "raises" in check_result or type(value) is not type(expected) or value != expected:
            return False
    return True


def flat(text: str) -> str:
    """NFKD, sin marcas combinantes y casefold.

    NFKD solo NO basta: descompone la «ó» en «o» mas un acento suelto, y el acento sigue ahi.
    """
    broken_down = unicodedata.normalize("NFKD", text)
    return "".join(c for c in broken_down if not unicodedata.combining(c)).casefold()


def signals(
    text: str,
    expected: Sequence[str],
    forbidden: Sequence[str],
    fields: Sequence[str],
    checks: Sequence[dict[str, Any]] = (),
    counts: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, bool | None]:
    """Oraculo de CP-4. Independiente del puntuador de la tarea 16 a proposito: es contra lo que
    ese puntuador se valida, y si compartieran codigo compartirian tambien el error."""
    try:
        obj = json.loads(text.strip())
    except ValueError:
        obj = None
    valid = isinstance(obj, dict) if fields else None
    return {
        "coverage": all(flat(t) in flat(text) for t in expected),
        "literal_coverage": all(t.casefold() in text.casefold() for t in expected),
        "forbidden": any(flat(t) in flat(text) for t in forbidden),
        "json_valid": valid,
        "json_fields": (set(fields) <= set(obj)) if valid else None,
        "execution": _runs_ok(text, checks) if checks else None,
        "counts": _counts_add_up(text, counts) if counts else None,
    }


def check_reference(
    case: Case, expected: Sequence[str], counts: Mapping[str, Sequence[int]] | None = None
) -> list[str]:
    if case.reference is None:
        return []
    signal, good, bad_answer = case.reference
    if signal not in EXPECTED_DIFFERENCES:
        return [f"{case.id}: senal de referencia desconocida {signal!r}"]
    errors: list[str] = []
    if len(good) != len(bad_answer):
        errors.append(
            f"{case.id}: la pareja no tiene la misma longitud ({len(good)} y {len(bad_answer)})"
        )
    arguments = (case.forbidden_terms, case.expected_json_fields, case.checks, counts)
    ok = signals(good, expected, *arguments)
    bad_signals = signals(bad_answer, expected, *arguments)
    if (
        not ok["coverage"]
        or ok["forbidden"]
        or False
        in (
            ok["json_valid"],
            ok["json_fields"],
            ok["execution"],
            ok["counts"],
        )
    ):
        errors.append(f"{case.id}: la respuesta buena no es buena: {ok}")
    differ = {name for name in ok if ok[name] != bad_signals[name]}
    if differ != EXPECTED_DIFFERENCES[signal]:
        errors.append(
            f"{case.id}: la pareja de {signal} difiere en {sorted(differ)}, "
            f"no en {sorted(EXPECTED_DIFFERENCES[signal])}"
        )
    return errors


def check(case: Case, captured: Capture, data: bytes, single: Capture | None = None) -> list[str]:
    """Las reglas de §4.4, contra lo que hizo produccion. Cada una puede fallar."""
    errors: list[str] = []
    n = len(captured.calls)
    if n == 0:
        return [f"{case.id}: la tool no llamo al backend"]
    if len(captured.models) > 1:
        errors.append(f"{case.id}: produccion uso varios modelos {sorted(captured.models)}")
    if captured.role != case.role:
        errors.append(
            f"{case.id}: declarado {case.role}, pero produccion eligio "
            f"{captured.calls[0].model} ({captured.role})"
        )
    if case.kind == "quality":
        if n != 1:
            errors.append(f"{case.id}: no cabe en una llamada, produccion hace {n}")
        elif not captured.whole_input:
            errors.append(f"{case.id}: el modelo no ve la entrada entera (truncada)")
    elif case.kind == "ceiling":
        if n == 1:
            errors.append(f"{case.id}: cabe en una llamada, asi que no sondea ningun techo")
        if single is None or len(single.calls) != 1 or not single.whole_input:
            errors.append(
                f"{case.id}: el sondeo no tiene un prompt de una llamada con la entrada entera"
            )
    if case.media_type == "text":
        text = normalized(data)
        expected = terms(case, text)
        if case.kind == "quality" and not expected:
            errors.append(f"{case.id}: sin terminos esperados no hay nada que puntuar")
        if case.terms_in_source:
            for term in expected:
                if term.casefold() not in text.casefold():
                    errors.append(f"{case.id}: el termino {term!r} no esta en la fuente")
        errors.extend(_check_id_size(case.id, len(text)))
    if case.reference is not None:
        source = normalized(data) if case.media_type == "text" else ""
        counts = case.counts(source) if case.counts else None
        errors.extend(check_reference(case, terms(case, source), counts))
    return errors


def _check_id_size(case_id: str, chars: int) -> list[str]:
    # Un id que promete un tamano que la fuente no tiene es el `techo-resumen-120k` que apuntaba a
    # un fichero de 106 000: se comprueba, no se confia.
    match = re.search(r"-(\d+)(k?)$", case_id)
    if not match:
        return []
    number = int(match.group(1))
    if match.group(2):
        ok = round(chars / 1000) == number
    else:
        ok = chars == number
    return (
        [] if ok else [f"{case_id}: el id promete {match.group(0)[1:]} y la fuente tiene {chars}"]
    )


def corpus_entry(
    case: Case, name: str, data: bytes, captured: Capture, single: Capture | None = None
) -> dict[str, Any]:
    # El prompt: el de produccion en los casos de calidad; en un sondeo de techo, el de la ruta
    # de una llamada. `production` sigue contando las llamadas que produccion hizo de verdad.
    prompt = single if single is not None else captured
    call = prompt.calls[0]
    text = normalized(data) if case.media_type == "text" else ""
    quality = case.kind == "quality"
    with_prompt = quality or single is not None
    return {
        "id": case.id,
        "tool": case.tool,
        "role": case.role,
        "kind": case.kind,
        "provenance": case.provenance,
        "origin": case.origin,
        "media_type": case.media_type,
        "source_file": name,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": len(data),
        "source_chars": len(text) if text else None,
        "production": {"model": captured.calls[0].model, "calls": len(captured.calls)},
        "system": call.system if with_prompt else None,
        "user_template": prompt.user_template if with_prompt else None,
        "max_tokens": call.max_tokens if with_prompt else None,
        "temperature": call.temperature if with_prompt else None,
        "response_format": call.response_format if with_prompt else None,
        "reasoning_effort": None,
        "expected_terms": list(terms(case, text)) if quality else [],
        "forbidden_terms": list(case.forbidden_terms) if quality else [],
        "expected_json_fields": list(case.expected_json_fields) if quality else [],
        "execution_checks": list(case.checks) if quality else [],
        "expected_counts": case.counts(text) if quality and case.counts else {},
        "automatic_scoring": case.automatic_score if quality else None,
        "expected_format": requested_format(call.system) if quality else {},
        **(
            {
                "reference_signal": case.reference[0],
                "reference_ok": case.reference[1],
                "reference_bad": case.reference[2],
            }
            if case.reference
            else {}
        ),
    }


# --- Conteos del log ----------------------------------------------------------------------------


def count_log(log_dir: Path, root: Path) -> dict[str, Any]:
    """Conteos agregados de §4.2. Ninguna ruta de fuera del repo sale de aqui, ni siquiera como
    nombre: el log guarda rutas del vault y de otros proyectos del usuario."""
    events: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("usage-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    local = [e for e in events if str(e.get("tool", "")).startswith("local_")]
    root_norm = os.path.normcase(os.path.abspath(root)) + os.sep
    per_tool: dict[str, Any] = {}
    for tool in sorted({e["tool"] for e in local}):
        from_tool = [e for e in local if e["tool"] == tool]
        chars = [int(e.get("chars_in") or 0) for e in from_tool]
        median = statistics.median(chars)
        per_tool[tool] = {
            "n": len(from_tool),
            "chars_in_median": int(median) if median == int(median) else median,
            "chars_in_min": min(chars),
            "chars_in_max": max(chars),
            "models": dict(Counter(e.get("model") for e in from_tool).most_common()),
        }
    from_repo: Counter[str] = Counter()
    outside = 0
    for event in local:
        path = event.get("path")
        if not path:
            continue
        absolute = os.path.normcase(os.path.abspath(path))
        if absolute.startswith(root_norm):
            # normcase solo para comparar: el nombre se guarda con sus mayusculas.
            relative = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
            from_repo[relative.replace("\\", "/")] += 1
        else:
            outside += 1
    return {
        "events": len(events),
        "local_events": len(local),
        "discarded_not_local": dict(
            Counter(e.get("tool") for e in events if e not in local).most_common()
        ),
        "by_tool": per_tool,
        "by_model": dict(Counter(e.get("model") for e in local).most_common()),
        "by_source": dict(Counter(e.get("source") for e in local).most_common()),
        "chunked": sum(1 for e in local if int(e.get("chunks") or 1) > 1),
        "repo_sources": dict(from_repo.most_common()),
        "sources_outside_repo": outside,
    }


# --- Construir y comprobar ----------------------------------------------------------------------


def _write_json(path: Path, data: Any) -> None:
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _frozen_source(sources: Path, name: str, generate: Source, root: Path, refresh: bool) -> bytes:
    """La copia congelada si ya existe; el fichero vivo solo si falta o se pide refrescar.

    Congelar sirve para que el corpus no cambie cuando cambia el repo: `CHANGELOG.md` crece en
    cada release y `lint-33k` sale de pasar ruff por `src/`. Regenerar para anadir un campo no
    puede recongelar de paso, o el contenido medido cambia sin que nadie lo decida.
    """
    path = sources / name
    if path.is_file() and not refresh:
        return path.read_bytes()
    return generate(root)


def build(root: Path, dest: Path, log_dir: Path | None, *, refresh_sources: bool = False) -> int:
    sources = dest / "fuentes"
    sources.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    cases: list[dict[str, Any]] = []
    expected: set[str] = set()
    for case in CASES:
        data = _frozen_source(
            sources, f"{case.id}.{case.extension}", case.source, root, refresh_sources
        )
        name = f"{case.id}.{case.extension}"
        expected.add(name)
        (sources / name).write_bytes(data)
        captured = capture_case(case, sources / name, data)
        single = (
            capture_case(case, sources / name, data, no_chunking=True)
            if case.kind == "ceiling"
            else None
        )
        errors.extend(check(case, captured, data, single))
        if captured.calls:
            cases.append(corpus_entry(case, name, data, captured, single))
    controls = []
    for control in CONTROLS:
        data = _frozen_source(
            sources,
            f"{control['id']}.{control['extension']}",
            control["source"],
            root,
            refresh_sources,
        )
        name = f"{control['id']}.{control['extension']}"
        expected.add(name)
        (sources / name).write_bytes(data)
        control_cases = [c for c in cases if c["id"] in control["para"]]
        if any(c["source_sha256"] == hashlib.sha256(data).hexdigest() for c in control_cases):
            errors.append(f"{control['id']}: la imagen de control es la misma que la del caso")
        controls.append(
            {
                "id": control["id"],
                "para": control["para"],
                "provenance": control["provenance"],
                "origin": control["origin"],
                "source_file": name,
                "source_sha256": hashlib.sha256(data).hexdigest(),
                "source_bytes": len(data),
            }
        )
    for surplus in sources.iterdir():
        if surplus.name not in expected:
            surplus.unlink()
    if errors:
        print("El corpus NO se escribe. Reglas que no se cumplen:")
        for error in errors:
            print(f"  - {error}")
        return 1
    _write_json(
        dest / "cases.json",
        {
            "schema_version": 2,
            "production_config": production_config(),
            "controls": controls,
            "cases": cases,
        },
    )
    if log_dir is not None and log_dir.is_dir():
        _write_json(dest / legacy_names.LOG_COUNTS_FILE_NAMES[1], count_log(log_dir, root))
    benchmark.load_corpus(dest / "cases.json")
    quality = sum(1 for c in cases if c["kind"] == "quality")
    print(
        f"ok: {quality} casos de calidad, {len(cases) - quality} sondeos, {len(controls)} control"
    )
    for case in cases:
        print(
            f"  {case['id']:<24} {case['role']:<10} llamadas={case['production']['calls']:<3} "
            f"chars={case['source_chars']} bytes={case['source_bytes']}"
        )
    return 0


def production_config() -> dict[str, Any]:
    with intercepted_production():
        return {
            "long_input_chars": config.LONG_INPUT_CHARS,
            "chunk_chars": config.CHUNK_CHARS,
            "models": {role: model for model, role in production_roles().items()},
            "max_chars": {
                role: config.max_chars_for_role(role) for role in production_roles().values()
            },
        }


_WATCHED_FIELDS = (
    "production",
    "system",
    "user_template",
    "max_tokens",
    "response_format",
    "expected_terms",
    "forbidden_terms",
    "expected_json_fields",
    "execution_checks",
    "expected_counts",
    "automatic_scoring",
    "expected_format",
    "reference_signal",
    "reference_ok",
    "reference_bad",
)


def check_versioned(dest: Path) -> list[str]:
    """Recaptura cada caso versionado contra el codigo de hoy. Si produccion cambio de rol, de
    troceado o de prompt, el corpus ya no mide lo que dice y hay que regenerarlo."""
    corpus = benchmark.load_corpus(dest / "cases.json")
    by_id = {case.id: case for case in CASES}
    errors: list[str] = []
    if {c.id for c in corpus.cases} != set(by_id):
        errors.append("los ids versionados no coinciden con los casos del constructor")
    for versioned in corpus.cases:
        case = by_id.get(versioned.id)
        if case is None:
            continue
        path = dest / "fuentes" / versioned.source_file
        data = path.read_bytes()
        captured = capture_case(case, path, data)
        single = (
            capture_case(case, path, data, no_chunking=True) if case.kind == "ceiling" else None
        )
        errors.extend(check(case, captured, data, single))
        current = corpus_entry(case, versioned.source_file, data, captured, single)
        for field_name in _WATCHED_FIELDS:
            if current.get(field_name) != versioned.raw.get(field_name):
                # Tambien lo que no sale de produccion: el corpus no se edita a mano, y una
                # referencia retocada en el JSON dejaria de ser la que el constructor comprobo.
                errors.append(f"{versioned.id}: {field_name} ya no coincide con el constructor")
    if corpus.production_config != production_config():
        errors.append("production_config ya no coincide con config.py")
    return errors


# --- Corpus de afinidad (REQ-040): la seleccion de commits y las trampas --------------------------

AFFINITY_TARGET = ROOT / "benchmarks" / "afinidad-2026-10"
DEADLINE = "2026-10-06"  # los commits son ANTERIORES a esta fecha (la del commiter, `%cs`)
F2_COMMIT = "d7c3dcc"  # `commit-diff-19k`: ya esta en el corpus, no se elige otra vez
N_NEW_REAL = 29  # 30 casos reales en total: `commit-diff-19k` mas estos
N_TRAPS = 9  # tres por juego: la hoja 1 y dos repeticiones posibles
# Pasos de la regla, en el orden de la spec: ventana de commits, rango de chars del diff. Si un paso
# no da los 38 commits (29 + 9) se pasa al siguiente: sin limite de ventana y, despues, al rango de
# 1 000 a 30 000 chars.
SELECTION_STEPS: tuple[tuple[int | None, int, int], ...] = (
    (400, 2000, 20000),
    (None, 2000, 20000),
    (None, 1000, 30000),
)
SELECTION_RULE = (
    "Commits de `main` con fecha anterior a 2026-10-06, de mas reciente a mas antiguo, sin merges, "
    "sin autor Dependabot, sin asunto `chore(deps...)`, sin asunto `chore: release`, "
    "con un diff (`git show --format=`) de 2 000 a 20 000 chars. Los 29 primeros "
    "(sin contar el de `commit-diff-19k`) son los casos reales; los 9 siguientes, las trampas. Si "
    "no salen 38, se amplia la ventana de 400 commits a todo el historial y, despues, el rango a "
    "1 000-30 000 chars."
)
_NOT_CANDIDATE = re.compile(r"^(?:chore\(deps|chore: release)")
_CONVENTIONAL_PREFIX = re.compile(
    r"^(feat|fix|docs|refactor|perf|test|build|ci|chore|style|revert)(\([^)]+\))?!?: "
)
_TRAILER = re.compile(r"^[A-Za-z][A-Za-z-]*: \S")


@dataclass(frozen=True)
class Commit:
    hash: str
    date: str
    author: str
    subject: str
    chars: int = 0

    @property
    def short(self) -> str:
        return self.hash[:7]


def _git_text(root: Path, *args: str) -> str:
    return _git(root, *args).decode("utf-8", errors="replace")


def _commits_of(
    root: Path, ref: str, window: int | None, extra: Sequence[str] = ()
) -> list[Commit]:
    fmt = "%H%x1f%cs%x1f%an <%ae>%x1f%s"
    limit = [f"-n{window}"] if window else []
    output = _git_text(root, "log", ref, "--no-merges", f"--format={fmt}", *limit, *extra)
    commits = []
    for line in output.splitlines():
        h, date, author, subject = line.split("\x1f", 3)
        commits.append(Commit(h, date, author, subject))
    return commits


def _is_candidate(c: Commit, before: str) -> bool:
    return (
        c.date < before
        and "dependabot" not in c.author.lower()
        and _NOT_CANDIDATE.match(c.subject) is None
    )


def _normalized_diff(root: Path, h: str) -> str:
    return normalized(commit_diff(h)(root))


@dataclass(frozen=True)
class Selection:
    real: list[Commit]
    traps: list[Commit]
    step: int  # indice en SELECTION_STEPS del paso que dio los commits


def select_commits(
    root: Path,
    *,
    ref: str = "main",
    before: str = DEADLINE,
    exclude: Sequence[str] = (F2_COMMIT,),
    n_real: int = N_NEW_REAL,
    n_traps: int = N_TRAPS,
    steps: Sequence[tuple[int | None, int, int]] = SELECTION_STEPS,
    discard_if: Callable[[str], bool] | None = None,
) -> Selection:
    """La regla escrita de REQ-040, aplicada por codigo. La lista de hashes sale de aqui, nunca a mano.

    `exclude` son prefijos de hash que no se eligen (el caso que ya esta en el corpus de F2).
    `discard_if` recibe el diff normalizado y, si devuelve `True`, el commit no es candidato (el
    modo `--privacy exclude`: un diff con datos privados no entra en el repo).
    """
    sizes: dict[str, int | None] = {}
    last: list[Commit] = []
    for index, (window, minimum, maximum) in enumerate(steps):
        candidates: list[Commit] = []
        for c in _commits_of(root, ref, window):
            if not _is_candidate(c, before) or any(c.hash.startswith(x) for x in exclude):
                continue
            if c.hash not in sizes:
                text = _normalized_diff(root, c.hash)
                private_item = discard_if is not None and discard_if(text)
                sizes[c.hash] = None if private_item else len(text)
            size = sizes[c.hash]
            if size is not None and minimum <= size <= maximum:
                candidates.append(Commit(c.hash, c.date, c.author, c.subject, size))
            if len(candidates) == n_real + n_traps:
                break
        last = candidates
        if len(candidates) >= n_real + n_traps:
            return Selection(candidates[:n_real], candidates[n_real:], index)
    raise ValueError(
        f"la regla no da {n_real + n_traps} commits ni en el ultimo paso ({len(last)})"
    )


def _numstat(root: Path, h: str) -> list[tuple[int, str]]:
    """Ficheros del commit por lineas cambiadas (anadidas mas quitadas), de mas a menos."""
    rows = []
    for line in _git_text(root, "show", "--numstat", "--format=", h).splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]) + int(parts[1]), parts[2]))
    return sorted(rows, key=lambda f: (-f[0], f[1]))


def commit_body(root: Path, h: str, maximum: int = 5) -> list[str]:
    """Hasta `maximo` lineas del cuerpo de un commit, sin firmas ni enlaces de sesion."""
    lines = []
    for line in _git_text(root, "log", "-1", "--format=%b", h).splitlines():
        if not line.strip() or _TRAILER.match(line) or "claude.ai/code/session" in line:
            continue
        # Un squash repite el asunto como primera linea del cuerpo («* feat: ...»).
        if _CONVENTIONAL_PREFIX.match(line.lstrip("* ").strip()):
            continue
        lines.append(line.rstrip())
    return lines[:maximum]


def same_zone_subject(
    root: Path,
    case: Commit,
    outside: set[str],
    *,
    ref: str = "main",
    before: str = DEADLINE,
    max_subject: int = 72,
) -> dict[str, Any] | None:
    """El asunto REAL de otro commit, fuera de los 30 y de los 9, que toca el fichero mas cambiado.

    Elegido por codigo entre los asuntos de 72 caracteres como mucho y con prefijo convencional
    (tiene que tener buen formato: la trampa es infiel, no malformada). Si ese fichero no da
    ninguno, se pasa al siguiente fichero mas cambiado. El mas reciente gana.
    """
    for _lines, file in _numstat(root, case.hash):
        for c in _commits_of(root, ref, None, ("--", file)):
            # Sin el « (#123)» que GitHub anade al hacer squash: un mensaje que devuelve la tool no
            # lo lleva, y seria la marca que delata la trampa.
            subject = re.sub(r"\s*\(#\d+\)$", "", c.subject)
            if (
                c.hash in outside
                or c.hash == case.hash
                or not _is_candidate(c, before)
                or len(subject) > max_subject
                or _CONVENTIONAL_PREFIX.match(subject) is None
            ):
                continue
            return {
                "hash": c.hash,
                "file": file,
                "subject": subject,
                "real_body": commit_body(root, c.hash),
            }
    return None


# --- Datos privados: nada de eso va al repo ---------------------------------------------------------

_PRIVATE_PATTERNS = {
    # Un nombre de usuario real tras `Users`; `C:\Users\...` o `/home/<usuario>` son marcadores.
    "ruta de perfil": re.compile(
        r"[A-Za-z]:[\\/]Users[\\/](?![.<{$%])[^\\/\s\"'<>]+"
        r"|/Users/(?![.<{$%])[^/\s\"'<>]+"
        r"|/home/(?![.<{$%])[^/\s\"'<>]+"
        r"|AppData[\\/][^\s]+"
    ),
    "ip": re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w)"),
    "id de sesion": re.compile(r"session_[0-9A-Za-z]{8,}|claude\.ai/code/session"),
    # Un dominio que empieza por letra: `paquete@1.18.11` y `+@pytest.fixture` no son correos.
    "correo": re.compile(r"(?<![\w.+@-])[A-Za-z0-9][\w.+-]*@[A-Za-z][\w-]*\.[A-Za-z][\w.-]*"),
}
# Lo que se deja pasar: bucle local, direcciones sin enrutar y los rangos reservados para
# documentacion (RFC 5737), los correos de ejemplo y los de noreply.
_ALLOWED_IP = re.compile(
    r"^(?:127\.\d+\.\d+\.\d+|0\.0\.0\.0|255\.255\.255\.\d+|192\.0\.2\.\d+|198\.51\.100\.\d+|203\.0\.113\.\d+)$"
)
_ALLOWED_EMAIL = re.compile(r"@(?:example\.(?:org|com|net)|users\.noreply\.github\.com)$|^noreply@")


def private_data(text: str) -> list[str]:
    """Lo que parece un dato privado en un texto que va al repo: `tipo: coincidencia`."""
    findings: list[str] = []
    for kind, pattern in _PRIVATE_PATTERNS.items():
        for m in pattern.finditer(text):
            value = m.group(0)
            if kind == "ip" and (_ALLOWED_IP.match(value) or max(map(int, value.split("."))) > 255):
                continue
            if kind == "correo" and _ALLOWED_EMAIL.search(value):
                continue
            findings.append(f"{kind}: {value}")
    return sorted(set(findings))


# --- Corpus de afinidad: las tools mecanicas (REQ-040) ------------------------------------------------
#
# Casos DISTINTOS en vez de repeticiones: a temperatura 0 repetir da la misma respuesta. Cada caso
# comprueba algo objetivo que un modelo puede fallar, con su `reference_ok` (puntua 1) y su
# `reference_bad` (puntua menos de 1) escritos antes de medir. Los textos son inventados para el
# caso: ninguno sale de un log ni de un fichero del usuario. Los puntuadores viven en
# `analyze_benchmark.py` (no importa el paquete) y se cargan por ruta.


def analyzer() -> Any:
    """`analyze_benchmark.py` cargado por ruta: de el salen los puntuadores y el veredicto."""
    module = sys.modules.get("analyze_benchmark")
    if module is not None and hasattr(module, "score_affinity"):
        return module
    spec = importlib.util.spec_from_file_location(
        "analyze_benchmark", ROOT / "scripts" / "analyze_benchmark.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["analyze_benchmark"] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class MechanicalCase:
    id: str
    tool: str
    origin: str
    text: str
    extension: str
    scorer: dict[str, Any]
    reference_ok: str
    reference_bad: str
    arguments: dict[str, Any] = field(default_factory=dict)
    fields: tuple[str, ...] = ()  # `local_extract`: las claves que se piden
    provenance: str = "made_up"


def _classifies(id_: str, text: str, tags: list[str], acceptable_ones: list[str], bad_one: str):
    return MechanicalCase(
        id_,
        "local_classify",
        "texto escrito para el caso",
        text,
        "txt",
        {"kind": "classify", "labels": tags, "acceptable": acceptable_ones},
        acceptable_ones[0],
        bad_one,
        arguments={"labels": tags},
    )


def _extracts(
    id_: str, text: str, expected: dict[str, Any], bad_one: dict[str, Any], ext: str = "txt"
):
    keys = tuple(expected)
    return MechanicalCase(
        id_,
        "local_extract",
        "texto escrito para el caso",
        text,
        ext,
        {"kind": "extract", "keys": list(keys), "expected": expected},
        json.dumps(expected, ensure_ascii=False),
        json.dumps(bad_one, ensure_ascii=False),
        fields=keys,
    )


def _translates(id_: str, text: str, good_one: str, bad_one: str):
    # `_chat_chunked` recorta el fin de linea final: el modelo ve el texto sin el.
    text = text.rstrip("\n")
    est = analyzer().markdown_structure(text)
    return MechanicalCase(
        id_,
        "local_translate",
        "Markdown escrito para el caso, en ingles; se traduce al español",
        text,
        "md",
        {
            "kind": "translate",
            "titles": est["titles"],
            "lists": est["lists"],
            "blocks": est["blocks"],
            "code": est["code"],
        },
        good_one,
        bad_one,
        arguments={"target_lang": "español"},
    )


def _linter_output(warnings: list[tuple[str, int, int, str, str]]) -> str:
    return "\n".join(f"{f}:{ln}:{col}: {c} {m}" for f, ln, col, c, m in warnings) + "\n"


def _linter_counts(warnings: list[tuple[str, int, int, str, str]]) -> dict[str, list[int]]:
    """Por regla, los numeros que valen: el total y los archivos que la tienen (y lo que suma en
    cada uno), como en `check_counts` de F2."""
    by_rule: dict[str, dict[str, int]] = {}
    for file, _ln, _col, code, _msg in warnings:
        by_rule.setdefault(code, {}).setdefault(file, 0)
        by_rule[code][file] += 1
    return {
        code: sorted({sum(files_list.values()), len(files_list), *files_list.values()})
        for code, files_list in by_rule.items()
    }


def _resume_linter(id_: str, warnings, good_one: str, bad_one: str):
    return MechanicalCase(
        id_,
        "local_lint_summary",
        "salida de ruff escrita para el caso (sin rutas reales)",
        _linter_output(warnings),
        "txt",
        {"kind": "lint", "counts": _linter_counts(warnings), "max_words": 200},
        good_one,
        bad_one,
        provenance="generated",
    )


def _delegates(id_: str, task: str, entry: str, fmt: str, expected: str, regex: str, bad_one: str):
    return MechanicalCase(
        id_,
        "local_delegate",
        "texto escrito para el caso",
        entry,
        "txt",
        {"kind": "delegate", "expected": expected, "format": regex},
        expected,
        bad_one,
        arguments={"task": task, "output_format": fmt},
    )


_FENCE = "```"


def _md(*blocks: str) -> str:
    return "\n".join(blocks) + "\n"


_TRANSLATION_1_EN = _md(
    "# Quick start",
    "",
    "Install the package and run the check:",
    "",
    "- Install it with pip.",
    "- Run the check command.",
    "- Read the report.",
    "",
    _FENCE + "bash",
    "pip install demo-tool  # installs the CLI",
    "demo-tool check --strict",
    _FENCE,
    "",
    "## Configuration",
    "",
    "Set the timeout in seconds:",
    "",
    _FENCE + "toml",
    "[demo]",
    "timeout = 30  # seconds",
    _FENCE,
)
_TRANSLATION_1_ES = _md(
    "# Inicio rápido",
    "",
    "Instala el paquete y ejecuta la comprobación:",
    "",
    "- Instálalo con pip.",
    "- Ejecuta el comando de comprobación.",
    "- Lee el informe.",
    "",
    _FENCE + "bash",
    "pip install demo-tool  # installs the CLI",
    "demo-tool check --strict",
    _FENCE,
    "",
    "## Configuración",
    "",
    "Define el tiempo de espera en segundos:",
    "",
    _FENCE + "toml",
    "[demo]",
    "timeout = 30  # seconds",
    _FENCE,
)
_TRANSLATION_2_EN = _md(
    "# Troubleshooting",
    "",
    "If the service does not start, follow these steps in order:",
    "",
    "1. Check that the port is free.",
    "2. Delete the stale lock file.",
    "3. Start the service again.",
    "",
    _FENCE + "python",
    "def is_free(port):",
    '    """Return True when nothing listens on the port."""',
    "    # try to bind and close at once",
    "    return True",
    _FENCE,
    "",
    "### Still failing?",
    "",
    "Open an issue and attach the log.",
)
_TRANSLATION_2_ES = _md(
    "# Solución de problemas",
    "",
    "Si el servicio no arranca, sigue estos pasos en orden:",
    "",
    "1. Comprueba que el puerto está libre.",
    "2. Borra el archivo de bloqueo obsoleto.",
    "3. Arranca el servicio otra vez.",
    "",
    _FENCE + "python",
    "def is_free(port):",
    '    """Return True when nothing listens on the port."""',
    "    # try to bind and close at once",
    "    return True",
    _FENCE,
    "",
    "### ¿Sigue fallando?",
    "",
    "Abre una incidencia y adjunta el registro.",
)
_TRANSLATION_3_EN = _md(
    "## Changelog",
    "",
    "### Added",
    "",
    "- New `--dry-run` flag.",
    "- Support for custom templates.",
    "",
    "### Fixed",
    "",
    "- The parser no longer crashes on empty files.",
    "",
    "Example of the new flag:",
    "",
    _FENCE,
    "$ demo run --dry-run",
    "# nothing was written",
    _FENCE,
)
_TRANSLATION_3_ES = _md(
    "## Registro de cambios",
    "",
    "### Añadido",
    "",
    "- Nuevo indicador `--dry-run`.",
    "- Soporte para plantillas personalizadas.",
    "",
    "### Corregido",
    "",
    "- El analizador ya no falla con archivos vacíos.",
    "",
    "Ejemplo del nuevo indicador:",
    "",
    _FENCE,
    "$ demo run --dry-run",
    "# nothing was written",
    _FENCE,
)
_TRANSLATION_4_EN = _md(
    "# Release checklist",
    "",
    "Before tagging a release:",
    "",
    "- Update the version:",
    "  - in `pyproject.toml`",
    "  - in the changelog",
    "- Run the full test suite.",
    "",
    _FENCE + "python",
    "# bump the version everywhere",
    "VERSION = '1.2.0'",
    _FENCE,
    "",
    "Then push the tag.",
)
_TRANSLATION_4_ES = _md(
    "# Lista de comprobación de la versión",
    "",
    "Antes de etiquetar una versión:",
    "",
    "- Actualiza la versión:",
    "  - en `pyproject.toml`",
    "  - en el registro de cambios",
    "- Ejecuta toda la batería de pruebas.",
    "",
    _FENCE + "python",
    "# bump the version everywhere",
    "VERSION = '1.2.0'",
    _FENCE,
    "",
    "Después, sube la etiqueta.",
)

_WARNINGS_1 = [
    ("app/main.py", 12, 101, "E501", "Line too long"),
    ("app/main.py", 40, 105, "E501", "Line too long"),
    ("app/main.py", 7, 8, "F401", "`os` imported but unused"),
    ("app/util.py", 3, 8, "F401", "`sys` imported but unused"),
    ("app/util.py", 9, 8, "F401", "`re` imported but unused"),
    ("app/util.py", 55, 120, "E501", "Line too long"),
    ("app/util.py", 70, 5, "W291", "Trailing whitespace"),
    ("app/cli.py", 21, 110, "E501", "Line too long"),
]
_WARNINGS_2 = [
    ("src/a.py", 5, 1, "D100", "Missing docstring in public module"),
    ("src/b.py", 1, 1, "D100", "Missing docstring in public module"),
    ("src/c.py", 1, 1, "D100", "Missing docstring in public module"),
    ("src/a.py", 14, 5, "D103", "Missing docstring in public function"),
    ("src/a.py", 30, 5, "D103", "Missing docstring in public function"),
    ("src/b.py", 8, 5, "D103", "Missing docstring in public function"),
    ("src/b.py", 22, 5, "D103", "Missing docstring in public function"),
    ("src/b.py", 44, 5, "D103", "Missing docstring in public function"),
    ("src/c.py", 17, 9, "T201", "`print` found"),
    ("src/c.py", 18, 9, "T201", "`print` found"),
    ("src/c.py", 19, 9, "T201", "`print` found"),
    ("src/a.py", 61, 12, "B006", "Do not use mutable data structures for argument defaults"),
]
_WARNINGS_3 = (
    [("tools/gen.py", n, 1, "E402", "Module level import not at top of file") for n in (4, 5, 6, 7)]
    + [("tools/gen.py", n, 90 + n, "E501", "Line too long") for n in (20, 31, 32)]
    + [("tools/gen.py", 50, 5, "E711", "Comparison to `None` should be `cond is None`")]
)
_WARNINGS_4 = (
    [("lib/io.py", n, 1, "I001", "Import block is un-sorted or un-formatted") for n in (1, 30)]
    + [("lib/net.py", 1, 1, "I001", "Import block is un-sorted or un-formatted")]
    + [("lib/net.py", n, 9, "SIM102", "Use a single `if` statement") for n in (12, 44, 80)]
    + [("lib/db.py", n, 7, "SIM102", "Use a single `if` statement") for n in (5, 6)]
    + [("lib/db.py", 33, 15, "UP006", "Use `list` instead of `List` for type annotation")]
    + [
        ("lib/io.py", n, 15, "UP006", "Use `dict` instead of `Dict` for type annotation")
        for n in (9, 10)
    ]
    + [("lib/net.py", 91, 3, "RET504", "Unnecessary assignment before `return`")]
    + [("lib/db.py", 70, 3, "RET504", "Unnecessary assignment before `return`")]
)


MECHANICAL_CASES: tuple[MechanicalCase, ...] = (
    # --- local_classify: 8 casos, >= 4 etiquetas, el conjunto aceptable declarado antes de medir ---
    _classifies(
        "clasifica-bug-con-etiquetas-en-ingles",
        "Al pulsar «Guardar», la aplicación se cierra sin mostrar ningún mensaje.",
        ["bug", "feature", "docs", "question"],
        ["bug"],
        "feature",
    ),
    _classifies(
        "clasifica-peticion-de-funcion",
        "Estaría bien que el panel permitiera exportar los datos a CSV.",
        ["bug", "feature", "docs", "question"],
        ["feature"],
        "bug",
    ),
    _classifies(
        "clasifica-idioma-aleman",
        "Das Wetter ist heute wirklich schön, wir gehen spazieren.",
        ["inglés", "alemán", "francés", "español"],
        ["alemán"],
        "inglés",
    ),
    _classifies(
        "clasifica-ironia",
        "Qué maravilla: tres semanas esperando y el paquete llegó aplastado.",
        ["positivo", "negativo", "neutro", "mixto"],
        ["negativo"],
        "positivo",
    ),
    _classifies(
        "clasifica-deportes",
        "El equipo local ganó 3-1 con dos goles en el segundo tiempo.",
        ["deportes", "política", "economía", "tecnología"],
        ["deportes"],
        "política",
    ),
    _classifies(
        "clasifica-economia",
        "La inflación interanual bajó al 3,1 % según el banco central.",
        ["deportes", "política", "economía", "tecnología"],
        ["economía"],
        "tecnología",
    ),
    _classifies(
        "clasifica-negacion-reenvio",
        "No quiero que me devuelvan el dinero: quiero que me envíen la pieza que falta.",
        ["reembolso", "reenvío", "cancelación", "consulta"],
        ["reenvío"],
        "reembolso",
    ),
    _classifies(
        "clasifica-lenguaje-de-programacion",
        "def suma(a, b):\n    return a + b",
        ["python", "javascript", "rust", "sql"],
        ["python"],
        "javascript",
    ),
    # --- local_extract: 8 casos, JSON estricto con las claves exactas ---
    _extracts(
        "extrae-factura",
        "Factura: F-2026-0457\nFecha: 14/03/2026\nCliente: Talleres Almaguer S.L.\n"
        "Concepto: mantenimiento mensual\nTotal: 1234.50 EUR\n",
        {
            "factura": "F-2026-0457",
            "fecha": "14/03/2026",
            "cliente": "Talleres Almaguer S.L.",
            "total": 1234.5,
            "moneda": "EUR",
        },
        {
            "factura": "F-2026-0457",
            "fecha": "14/03/2026",
            "cliente": "Talleres Almaguer S.L.",
            "total": "1234.50",
            "moneda": "EUR",
        },
    ),
    _extracts(
        "extrae-linea-de-log-con-numeros",
        "2026-03-14T09:21:07Z ERROR payment-service req=8f3a21 status=502 latency_ms=1840\n",
        {
            "timestamp": "2026-03-14T09:21:07Z",
            "nivel": "ERROR",
            "servicio": "payment-service",
            "status": 502,
            "latencia_ms": 1840,
        },
        {
            "timestamp": "2026-03-14T09:21:07Z",
            "nivel": "ERROR",
            "servicio": "payment-service",
            "status": "502",
            "latencia_ms": 1840,
        },
        "log",
    ),
    _extracts(
        "extrae-correo-sin-telefono",
        "De: Marta Ruiz <marta.ruiz@example.org>\nAsunto: Cambio de fecha de la reunión\n\n"
        "Hola, ¿podemos pasar la reunión al jueves? Gracias.\n",
        {
            "nombre": "Marta Ruiz",
            "correo": "marta.ruiz@example.org",
            "asunto": "Cambio de fecha de la reunión",
            "telefono": None,
        },
        {
            "nombre": "Marta Ruiz",
            "correo": "marta.ruiz@example.org",
            "asunto": "Cambio de fecha de la reunión",
            "telefono": "",
        },
    ),
    _extracts(
        "extrae-producto-sin-existencias",
        "Camiseta Azul Marino — talla M — precio 19,99 € — quedan 0 unidades.\n",
        {"nombre": "Camiseta Azul Marino", "talla": "M", "precio": 19.99, "stock": 0},
        {"nombre": "Camiseta Azul Marino", "talla": "M", "precio": 19.99, "stock": None},
    ),
    _extracts(
        "extrae-toml-sin-licencia",
        '[project]\nname = "demo-tool"\nversion = "1.4.2"\nrequires-python = ">=3.11"\n',
        {"name": "demo-tool", "version": "1.4.2", "requires-python": ">=3.11", "license": None},
        {"name": "demo-tool", "version": "1.4.2", "requires-python": ">=3.11"},
        "toml",
    ),
    _extracts(
        "extrae-acta-con-cifras",
        "Asistieron 12 de los 20 socios. La propuesta se aprobó con 9 votos a favor, "
        "2 en contra y 1 abstención.\n",
        {"asistentes": 12, "socios": 20, "a_favor": 9, "en_contra": 2, "abstenciones": 1},
        {"asistentes": 12, "socios": 20, "a_favor": 9, "en_contra": 1, "abstenciones": 2},
    ),
    _extracts(
        "extrae-linea-de-acceso-web",
        '203.0.113.7 - - [14/Mar/2026:09:21:07 +0000] "GET /api/v2/users?id=42 HTTP/1.1" 404 512\n',
        {
            "ip": "203.0.113.7",
            "metodo": "GET",
            "ruta": "/api/v2/users?id=42",
            "codigo": 404,
            "bytes": 512,
        },
        {
            "ip": "203.0.113.7",
            "metodo": "GET",
            "ruta": "/api/v2/users",
            "codigo": 404,
            "bytes": 512,
        },
        "log",
    ),
    _extracts(
        "extrae-reunion-sin-organizador",
        "Reunión de seguimiento el 5 de abril a las 16:30 en la sala B.\n",
        {"fecha": "5 de abril", "hora": "16:30", "lugar": "sala B", "organizador": None},
        {"fecha": "5 de abril", "hora": "16:30", "lugar": "sala B", "organizador": "ninguno"},
    ),
    # --- local_translate: 4 casos Markdown; se conservan titulos, listas, bloques y el codigo ---
    _translates(
        "traduce-guia-de-inicio",
        _TRANSLATION_1_EN,
        _TRANSLATION_1_ES,
        _TRANSLATION_1_ES.replace("# installs the CLI", "# instala la CLI"),
    ),
    _translates(
        "traduce-solucion-de-problemas",
        _TRANSLATION_2_EN,
        _TRANSLATION_2_ES,
        _TRANSLATION_2_ES.replace("3. Arranca el servicio otra vez.\n", ""),
    ),
    _translates(
        "traduce-registro-de-cambios",
        _TRANSLATION_3_EN,
        _TRANSLATION_3_ES,
        _TRANSLATION_3_ES.replace("# nothing was written", "# no se escribió nada"),
    ),
    _translates(
        "traduce-lista-de-version",
        _TRANSLATION_4_EN,
        _TRANSLATION_4_ES,
        _TRANSLATION_4_ES.replace(
            "# Lista de comprobación de la versión", "Lista de comprobación de la versión"
        ),
    ),
    # --- local_lint_summary (tamano mecanico): los conteos coinciden con la fuente ---
    _resume_linter(
        "resume-ruff-tres-reglas",
        _WARNINGS_1,
        "Resumen de ruff: 8 avisos en 3 archivos.\n"
        "- E501: 4 avisos en 3 archivos (línea demasiado larga).\n"
        "- F401: 3 avisos en 2 archivos (importaciones sin usar).\n"
        "- W291: 1 aviso en 1 archivo (espacios al final de línea).",
        "Resumen de ruff: 8 avisos en 3 archivos.\n"
        "- E501: 6 avisos en 3 archivos (línea demasiado larga).\n"
        "- F401: 3 avisos en 2 archivos (importaciones sin usar).\n"
        "- W291: 1 aviso en 1 archivo (espacios al final de línea).",
    ),
    _resume_linter(
        "resume-ruff-docstrings",
        _WARNINGS_2,
        "Resumen de ruff: 12 avisos en 3 archivos.\n"
        "- D100: 3 avisos en 3 archivos (módulo sin docstring).\n"
        "- D103: 5 avisos en 2 archivos (función pública sin docstring).\n"
        "- T201: 3 avisos en 1 archivo (uso de print).\n"
        "- B006: 1 aviso en 1 archivo (argumento mutable por defecto).",
        "Resumen de ruff: 12 avisos en 3 archivos.\n"
        "- D100: 3 avisos en 3 archivos (módulo sin docstring).\n"
        "- D103: 4 avisos en 2 archivos (función pública sin docstring).\n"
        "- T201: 3 avisos en 1 archivo (uso de print).\n"
        "- B006: 1 aviso en 1 archivo (argumento mutable por defecto).",
    ),
    _resume_linter(
        "resume-ruff-un-solo-archivo",
        _WARNINGS_3,
        "Resumen de ruff: 8 avisos, todos en tools/gen.py.\n"
        "- E402: 4 avisos (importación fuera de la cabecera).\n"
        "- E501: 3 avisos (línea demasiado larga).\n"
        "- E711: 1 aviso (comparación con None).",
        "Resumen de ruff: 8 avisos, todos en tools/gen.py.\n"
        "- E402: 4 avisos (importación fuera de la cabecera).\n"
        "- E501: 2 avisos (línea demasiado larga).\n"
        "- E711: 2 avisos (comparación con None).",
    ),
    _resume_linter(
        "resume-ruff-cinco-reglas",
        _WARNINGS_4,
        "Resumen de ruff: 13 avisos en 3 archivos.\n"
        "- I001: 3 avisos en 2 archivos (importaciones sin ordenar).\n"
        "- SIM102: 5 avisos en 2 archivos (if anidados).\n"
        "- UP006: 3 avisos en 2 archivos (anotaciones antiguas).\n"
        "- RET504: 2 avisos en 2 archivos (asignación innecesaria antes de return).",
        "Resumen de ruff: 13 avisos en 3 archivos.\n"
        "- I001: 3 avisos en 2 archivos (importaciones sin ordenar).\n"
        "- SIM102: 4 avisos en 2 archivos (if anidados).\n"
        "- UP006: 3 avisos en 2 archivos (anotaciones antiguas).\n"
        "- RET504: 2 avisos en 2 archivos (asignación innecesaria antes de return).",
    ),
    # --- local_delegate sin modelo: 4 casos con formato exacto de salida ---
    _delegates(
        "delega-contar-palabras",
        "Cuenta cuántas palabras tiene el texto",
        "El rápido zorro marrón salta sobre el perro perezoso",
        "Solo un número entero, sin texto adicional",
        "9",
        r"\d+",
        "El texto tiene 9 palabras.",
    ),
    _delegates(
        "delega-lista-a-csv",
        "Convierte la lista en una sola línea CSV",
        "manzana\npera\nuva\nkiwi",
        "Una sola línea con los valores separados por comas, sin espacios",
        "manzana,pera,uva,kiwi",
        r"[^,\s]+(?:,[^,\s]+)*",
        "manzana, pera, uva, kiwi",
    ),
    _delegates(
        "delega-fecha-iso",
        "Convierte la fecha a formato ISO 8601",
        "14 de marzo de 2026",
        "Solo la fecha con el formato AAAA-MM-DD",
        "2026-03-14",
        r"\d{4}-\d{2}-\d{2}",
        "14-03-2026",
    ),
    _delegates(
        "delega-mayusculas",
        "Pasa el texto a mayúsculas",
        "entrega pospuesta al lunes",
        "Solo el texto en mayúsculas, en una línea",
        "ENTREGA POSPUESTA AL LUNES",
        r"[^a-záéíóúñ\n]+",
        "Entrega pospuesta al lunes",
    ),
)


# --- Corpus de afinidad: las trampas y la construccion -------------------------------------------------

# Del corpus de F2, sin cambios: `commit-diff-19k` es uno de los 30 reales; el techo y los cinco
# casos mecanicos se repiten como regresion y NO cuentan como discriminantes.
F2_REGRESSION = (
    "resumen-md-2k",
    "extraer-toml-2k",
    "clasificar-53",
    "traducir-42",
    "delegar-56",
)
F2_REAL_CASE = "commit-diff-19k"
F2_CEILING_CASE = "techo-commit-156k"
TRAP_KINDS = ("same-zone", "secondary", "generic")
SETS = 3

TRAP_RULES = {
    "shape_rule": (
        "Si el mensaje del modelo emparejado tiene cuerpo, la trampa lleva el asunto mas tantas "
        "lineas de su cuerpo como lineas de cuerpo tenga ese mensaje (como mucho 5); si no lo tiene, "
        "solo el asunto. La aplica `hoja_pares.py generar-commit` al armar el par. El cuerpo se "
        "parte por unidades enteras (una viñeta o una frase), nunca por lineas fisicas, y al recortar "
        "se quitan unidades enteras. La trampa copia la puntuacion final de su pareja (sin punto si "
        "la mayoria de sus lineas no lo llevan) y su viñeta media no pasa de 1,5 veces la de la "
        "pareja. Idioma: español, el de la tool (su prompt esta en español) y el del historial del "
        "repo."
    ),
    "same-zone": (
        "El asunto REAL de otro commit, fuera de los 30 y de los 9, que toca el fichero mas cambiado "
        "del caso trampa; elegido por codigo entre los asuntos de 72 caracteres como mucho y con "
        "prefijo convencional (el mas reciente); si ese fichero no da ninguno, el siguiente fichero "
        "mas cambiado. Cuerpo: el cuerpo real de ese commit (sin firmas ni enlaces), condensado en "
        "hasta 5 frases completas y cortas, con tildes y una afirmacion por frase, cada una comprobada contra "
        "el cuerpo de ese commit; si no hay cuerpo redactado a mano, las 5 primeras lineas reales y, "
        "si tiene menos de 5, lineas redactadas sobre lo secundario del diff."
    ),
    "secondary": (
        "Redactado a mano: un mensaje con buen formato que solo nombra un cambio SECUNDARIO del diff "
        "(aqui, el registro de un gate de una traza SDD, la entrada del CHANGELOG de una subida de "
        "version o una explicacion lateral de un documento, que acompañan al cambio principal pero "
        "no lo son). Cada linea del cuerpo se comprueba "
        "contra el diff: no dice nada falso, solo deja fuera lo principal."
    ),
    "generic": (
        "Redactado a mano: un mensaje con buen formato (prefijo convencional, asunto corto) que no "
        "dice nada concreto del diff. El cuerpo repite vaguedades sin nombrar ficheros ni cambios."
    ),
}

# Por el prefijo de 7 caracteres del commit del CASO TRAMPA (el diff sobre el que se empareja).
WRITTEN_TRAPS: dict[str, dict[str, Any]] = {
    # --- secundario: un mensaje con buen formato que solo nombra un cambio secundario del diff ---
    "4f41311": {
        "subject": "docs(sdd): registra la aprobación de la conformidad de una traza",
        "body": [
            "Actualiza el state.json de una traza SDD.",
            "Registra el gate de conformidad como aprobado.",
            "Anota que el CI del PR estaba en verde y que se mergeó.",
            "Pasa la traza de verificando a cierre.",
            "No cambia código.",
        ],
    },
    "b04a5e2": {
        "subject": "docs: añade la entrada 0.18.1 al CHANGELOG",
        "body": [
            "Añade la sección 0.18.1 al CHANGELOG.",
            "Actualiza el enlace Unreleased y añade el de la 0.18.1.",
            "Fija la fecha de la entrada en 2026-07-31.",
            "No reescribe entradas anteriores.",
            "No cambia código de la aplicación.",
        ],
    },
    "fa08d64": {
        "subject": "docs(sdd): precisa por qué subscriptions no aplica",
        "body": [
            "Reescribe en research.md la explicación del descarte de subscriptions.",
            "Dice que esas notificaciones son sobre recursos y prompts.",
            "Anota que el servidor no expone ningún recurso ni prompt.",
            "Cambia una palabra en la fila de elicitation de la tabla.",
            "No toca código.",
        ],
    },
    # --- generico: buen formato, nada concreto ---
    "3b20fb3": {
        "subject": "chore: realiza tareas de mantenimiento",
        "body": [
            "Actualiza varios archivos.",
            "Mejora algunos detalles.",
            "Ajusta el contenido existente.",
            "Pone al día partes del proyecto.",
            "Revisa y corrige cosas menores.",
        ],
    },
    "7d0f4ac": {
        "subject": "docs: mejora la documentación",
        "body": [
            "Realiza ajustes en varias partes.",
            "Corrige pequeños detalles.",
            "Actualiza el texto donde hacía falta.",
            "Mantiene todo al día.",
            "Ordena algunos elementos.",
        ],
    },
    "6710a6b": {
        "subject": "fix: corrige varios problemas",
        "body": [
            "Corrige varios problemas.",
            "Resuelve algunos errores menores.",
            "Mejora la robustez general.",
            "Actualiza lo necesario.",
            "Revisa los casos pendientes.",
        ],
    },
}
# El cuerpo REAL del commit del que sale el asunto de cada trampa de la misma zona, condensado en frases
# completas y cortas (una afirmacion por frase, con tildes, de unos 60 caracteres: la viñeta media de la
# trampa no puede pasar de 1,5 veces la de su pareja), por el prefijo de 7 caracteres del commit del
# CASO TRAMPA. Las lineas reales estan partidas a 80 columnas: pasadas a viñetas por la regla de forma
# daban viñetas que empiezan a mitad de frase, la ultima cortada y sin tildes, y la trampa se
# reconocia sin leer el diff. Cada frase se comprueba contra el cuerpo del commit de `asunto_de`
# (no contra el diff del caso trampa: la trampa es mala justo porque describe OTRO cambio).
SAME_ZONE_BODIES: dict[str, list[str]] = {
    # asunto_de 821d1dc: «feat(wiki): la wiki nativa se sincroniza sola desde docs/wiki»
    "1314b0b": [
        "Era el último fleco manual del release.",
        "La wiki estaba congelada desde el 28 de julio.",
        "El workflow se dispara en el push a main, no en el tag.",
        "Arregla 18 enlaces rotos en 6 páginas de la wiki.",
        "La wiki pasa a ser un artefacto generado.",
    ],
    # asunto_de cf527b7: «docs: preparación de la release 0.28.0»
    "6d442e7": [
        "Diez títulos del CHANGELOG pasan a cuatro, uno por tipo.",
        "Quedan las mismas 37 entradas y las mismas 321 líneas.",
        "Los defaults del paquete son los ganadores de F2.",
        "El apagado en caliente es el fichero, no la variable.",
        "El README documenta las variables de respaldo y enfriamiento.",
    ],
    # asunto_de d0934c5: «feat(docs): la captura del README no puede quedarse vieja en silencio»
    "9d2c242": [
        "Publishing.md pedía regenerar la captura y nadie lo verificaba.",
        "Solo 5 de 25 releases regeneraron la captura en su commit.",
        "La 0.16.0 salió con el badge diciendo v0.15.0.",
        "Un test compara la versión de dashboard.json con pyproject.toml.",
        "El manifiesto lo escribe solo el script que captura.",
    ],
}
# Lo secundario de cada diff «de la misma zona», dicho sin inventar, por si el commit elegido no tiene
# cuerpo (o lo tiene corto): completa hasta 5 lineas.
SAME_ZONE_RESERVES: dict[str, list[str]] = {
    "1314b0b": [
        "Actualiza el state.json de ocho trazas SDD.",
        "Cambia el estado de esas trazas a cerrado.",
        "Registra sus gates de conformidad y memoria.",
        "Toca solo ficheros de la carpeta .sdd.",
        "No cambia código.",
    ],
    "6d442e7": [
        "Añade una prueba en tests/test_update.py.",
        "Amplía la página Troubleshooting de la wiki.",
        "Añade unas líneas a SECURITY.md.",
        "Actualiza el state.json de una traza SDD.",
        "Toca update.py y el CHANGELOG.",
    ],
    "9d2c242": [
        "Cierra la sección Unreleased del CHANGELOG.",
        "Sube la versión en pyproject.toml y server.json.",
        "Actualiza uv.lock.",
        "Actualiza docs/assets/dashboard.json y la captura.",
        "No cambia código de la aplicación.",
    ],
}


def build_traps(
    root: Path, selection: Selection, *, ref: str = "main", before: str = DEADLINE
) -> dict[str, Any]:
    """`traps.json`: una trampa por caso `trampa`, tres por juego y los tres tipos en cada juego."""
    outside = {c.hash for c in selection.real + selection.traps}
    sets: list[dict[str, Any]] = []
    for case_set_item in range(SETS):
        entries = []
        for position in range(len(TRAP_KINDS)):
            k = case_set_item * len(TRAP_KINDS) + position
            commit = selection.traps[k]
            kind = TRAP_KINDS[position]
            entry: dict[str, Any] = {
                "case": f"commit-trampa-{commit.short}",
                "commit": commit.hash,
                "kind": kind,
            }
            if kind == "same-zone":
                real = same_zone_subject(root, commit, outside, ref=ref, before=before)
                if real is None:
                    raise ValueError(f"{commit.short}: ningun asunto de la misma zona")
                body = list(real["real_body"])
                origin = "real"
                if commit.short in SAME_ZONE_BODIES:
                    body = list(SAME_ZONE_BODIES[commit.short])
                    origin = "real-rewritten"
                elif len(body) < 5:
                    reserve = SAME_ZONE_RESERVES.get(commit.short)
                    if reserve is None:
                        raise ValueError(f"{commit.short}: falta el cuerpo de reserva")
                    body += reserve[: 5 - len(body)]
                    origin = "real+written" if real["real_body"] else "written"
                entry.update(
                    subject=real["subject"],
                    body=body,
                    source_body=origin,
                    subject_of={"hash": real["hash"], "file": real["file"]},
                )
            else:
                text = WRITTEN_TRAPS.get(commit.short)
                if text is None:
                    raise ValueError(f"{commit.short}: falta la trampa redactada ({kind})")
                entry.update(
                    subject=text["subject"], body=list(text["body"]), source_body="written"
                )
            if len(entry["subject"]) > 72:
                raise ValueError(f"{commit.short}: el asunto de la trampa pasa de 72 caracteres")
            entries.append(entry)
        sets.append({"set": case_set_item + 1, "traps": entries})
    return {"schema_version": 1, **TRAP_RULES, "sets": sets}


# --- Construccion --------------------------------------------------------------------------------


def check_affinity(case: Case, capture: Capture) -> list[str]:
    """Las reglas de §4.4 que valen para un caso nuevo, contra lo que hizo produccion."""
    n = len(capture.calls)
    if n == 0:
        return [f"{case.id}: la tool no llamo al backend"]
    errors = []
    if len(capture.models) > 1:
        errors.append(f"{case.id}: produccion uso varios modelos {sorted(capture.models)}")
    if capture.role != case.role:
        errors.append(f"{case.id}: declarado {case.role}, pero produccion eligio {capture.role}")
    if n != 1:
        errors.append(f"{case.id}: no cabe en una llamada, produccion hace {n}")
    elif not capture.whole_input:
        errors.append(f"{case.id}: el modelo no ve la entrada entera (truncada)")
    return errors


def _corpus_case(c: MechanicalCase) -> Case:
    return Case(
        c.id,
        c.tool,
        "mechanical",
        "quality",
        c.provenance,
        c.origin,
        literal_text(c.text),
        extension=c.extension,
        arguments=c.arguments,
        expected_json_fields=c.fields,
    )


def _clear_f2_scoring(entry: dict[str, Any]) -> None:
    """Los casos nuevos no se puntuan con los campos de F2 (terminos, campos, conteos): su puntuador
    es `scorer`, que el veredicto aplica sobre la respuesta guardada."""
    for key in ("expected_terms", "forbidden_terms", "expected_json_fields", "execution_checks"):
        entry[key] = []
    entry["expected_counts"] = {}
    entry["automatic_scoring"] = False


def _affinity_entry(
    case: Case, name: str, data: bytes, capture: Capture, single: Capture | None, **extra: Any
) -> dict[str, Any]:
    entry = corpus_entry(case, name, data, capture, single)
    entry.update(extra)
    return entry


def _write_json_lf(path: Path, data: Any) -> None:
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def build_affinity(
    root: Path, target: Path, *, privacy: str = "fail", write: bool = True
) -> tuple[int, dict[str, Any]]:
    """Construye `benchmarks/afinidad-2026-10/`: `cases.json`, `traps.json` y `fuentes/`.

    `privacy`: `fail` (por defecto) para si algun texto lleva datos privados; `exclude` saca de
    la seleccion los commits cuyo diff los lleva y sigue con el siguiente candidato de la misma
    regla. Devuelve `(codigo, informe)`; con `write=False` no toca el disco.
    """
    discard = (lambda t: bool(private_data(t))) if privacy == "exclude" else None
    selection = select_commits(root, discard_if=discard)
    by_f2_id = {c.id: c for c in CASES}
    f2_sources = DESTINATION / "fuentes"
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    sources: dict[str, bytes] = {}
    score_fn = analyzer().score_affinity
    # Las tools leen la fuente de un fichero: se captura sobre una copia temporal, no sobre el destino.
    tmp_dir = tempfile.TemporaryDirectory()

    def capture_and_check(case: Case, data: bytes, name: str, *, ceiling: bool = False):
        sources[name] = data
        path = Path(tmp_dir.name) / name
        path.write_bytes(data)
        capture = capture_case(case, path, data)
        single = capture_case(case, path, data, no_chunking=True) if ceiling else None
        return capture, single

    # 1. Las cinco tools mecanicas: casos nuevos, con su puntuador y sus referencias.
    for c in MECHANICAL_CASES:
        case = _corpus_case(c)
        name = f"{c.id}.{c.extension}"
        data = c.text.encode("utf-8")
        capture, _ = capture_and_check(case, data, name)
        errors.extend(check_affinity(case, capture))
        spec = {"id": c.id, "scorer": c.scorer}
        ok, bad = score_fn(spec, c.reference_ok), score_fn(spec, c.reference_bad)
        if ok["quality"] != 1.0 or not ok["format"] or bad["quality"] >= 1.0:
            errors.append(f"{c.id}: las referencias no separan (ok={ok}, bad={bad})")
        if not capture.calls:
            continue
        entry = _affinity_entry(
            case,
            name,
            data,
            capture,
            None,
            discriminating=True,
            sheet_role=None,
            scorer=c.scorer,
            reference_ok=c.reference_ok,
            reference_bad=c.reference_bad,
        )
        _clear_f2_scoring(entry)
        limit = entry["expected_format"].get("max_words")
        if c.scorer["kind"] == "lint" and limit != c.scorer["max_words"]:
            errors.append(
                f"{c.id}: el prompt pide {limit} palabras y el puntuador {c.scorer['max_words']}"
            )
        entries.append(entry)

    # 2. Los commits: `commit-diff-19k` de F2, los 29 de la regla y los 9 trampa.
    def commit_input(case: Case, name: str, data: bytes, role: str, subject: str, **extra):
        capture, _ = capture_and_check(case, data, name)
        errors.extend(check_affinity(case, capture))
        entry = _affinity_entry(
            case,
            name,
            data,
            capture,
            None,
            discriminating=role == "real",
            sheet_role=role,
            scorer={"kind": "sheet"},
            reference_ok=subject,
            reference_bad="chore: actualiza archivos del proyecto",
            **extra,
        )
        _clear_f2_scoring(entry)
        return entry

    case19 = by_f2_id[F2_REAL_CASE]
    data19 = _frozen_source(
        f2_sources, f"{case19.id}.{case19.extension}", case19.source, root, False
    )
    subject19 = _git_text(root, "log", "-1", "--format=%s", F2_COMMIT).strip()
    entries.append(
        commit_input(
            case19,
            f"{case19.id}.{case19.extension}",
            data19,
            "real",
            subject19,
            commit=F2_COMMIT,
        )
    )
    for role, commits in (("real", selection.real), ("trap", selection.traps)):
        for c in commits:
            id_ = f"commit-{c.short}" if role == "real" else f"commit-trampa-{c.short}"
            case = Case(
                id_,
                "local_commit_msg",
                "code",
                "quality",
                "frozen",
                f"git show {c.short} (main, {c.date})",
                commit_diff(c.hash),
                extension="diff",
            )
            data = case.source(root)
            entries.append(commit_input(case, f"{id_}.diff", data, role, c.subject, commit=c.hash))

    # 3. El techo y los cinco casos mecanicos de F2, como regresion (no discriminantes).
    for id_ in (F2_CEILING_CASE, *F2_REGRESSION):
        case = by_f2_id[id_]
        name = f"{case.id}.{case.extension}"
        data = _frozen_source(f2_sources, name, case.source, root, False)
        capture, single = capture_and_check(case, data, name, ceiling=case.kind == "ceiling")
        errors.extend(check(case, capture, data, single))
        kind = "ceiling" if case.kind == "ceiling" else "f2"
        entries.append(
            _affinity_entry(
                case,
                name,
                data,
                capture,
                single,
                discriminating=False,
                sheet_role=None,
                scorer={"kind": kind},
            )
        )

    ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)):
        errors.append("hay ids repetidos en el corpus")
    real = {e["commit"] for e in entries if e.get("sheet_role") == "real"}
    traps_c = {e["commit"] for e in entries if e.get("sheet_role") == "trap"}
    if real & traps_c:
        errors.append("un commit es a la vez caso real y caso trampa")
    real_diffs = {e["source_sha256"] for e in entries if e.get("sheet_role") == "real"}
    if any(e["source_sha256"] in real_diffs for e in entries if e.get("sheet_role") == "trap"):
        errors.append("un caso trampa tiene el mismo diff que un caso real")

    # El dato privado de un diff se ve antes de armar las trampas: en el modo `fail` es el motivo.
    private_before = [
        f"dato privado en fuentes/{name}: {finding}"
        for name, data in sorted(sources.items())
        for finding in private_data(normalized(data))
    ]
    if private_before:
        return 1, {
            "cases": len(entries),
            "by_tool": {},
            "errors": errors + private_before,
            "step": selection.step,
        }
    traps = build_traps(root, selection)
    corpus = {
        "schema_version": 2,
        "production_config": production_config(),
        "controls": [],
        "selection": {
            "rule": SELECTION_RULE,
            "ref": "main",
            "deadline": DEADLINE,
            "step": selection.step,
            "privacy": privacy,
            "f2_case": {"id": F2_REAL_CASE, "commit": F2_COMMIT},
            "real": [{"hash": c.hash, "date": c.date, "chars": c.chars} for c in selection.real],
            "traps": [{"hash": c.hash, "date": c.date, "chars": c.chars} for c in selection.traps],
        },
        "cases": entries,
    }

    # 4. Nada privado en lo que va al repo.
    private_items: list[str] = []
    for name, data in sorted(sources.items()):
        private_items += [f"fuentes/{name}: {h}" for h in private_data(normalized(data))]
    for tag, content in (("cases.json", corpus), (legacy_names.TRAPS_FILE_NAMES[1], traps)):
        private_items += [
            f"{tag}: {h}" for h in private_data(json.dumps(content, ensure_ascii=False))
        ]
    errors += [f"dato privado en {p}" for p in private_items]

    def group(e: dict[str, Any]) -> str:
        return e.get("sheet_role") or ("new" if e["discriminating"] else "regression")

    tmp_dir.cleanup()
    report = {
        "by_tool": dict(Counter(f"{e['tool']}:{group(e)}" for e in entries)),
        "cases": len(entries),
        "errors": errors,
        "step": selection.step,
    }
    if errors:
        return 1, report
    if write:
        (target / "fuentes").mkdir(parents=True, exist_ok=True)
        for name, data in sources.items():
            (target / "fuentes" / name).write_bytes(data)
        for leftover in (target / "fuentes").iterdir():
            if leftover.name not in sources:
                leftover.unlink()
        # Las fuentes son bytes con su sha256: git no puede tocarles el fin de linea.
        (target / ".gitattributes").write_bytes(b"fuentes/** -text\n")
        _write_json_lf(target / "cases.json", corpus)
        _write_json_lf(target / legacy_names.TRAPS_FILE_NAMES[1], traps)
        benchmark.load_corpus(target / "cases.json")
    return 0, report


def _versioned(target: Path, names: tuple[str, str]) -> Path:
    """El fichero nuevo si existe y, si no, el congelado con el nombre viejo."""
    old_name, new_name = names
    return target / new_name if (target / new_name).exists() else target / old_name


def check_versioned_affinity(target: Path, root: Path = ROOT) -> list[str]:
    """Reconstruye el corpus en una carpeta temporal y lo compara con lo versionado. Lo versionado
    puede estar en el formato viejo (congelado, ola A10b-4): se compara ya normalizado."""
    versioned_corpus = legacy_names.normalize_affinity_corpus(
        json.loads((target / "cases.json").read_text(encoding="utf-8"))
    )
    privacy = versioned_corpus["selection"]["privacy"]
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp)
        (copy / "fuentes").mkdir()
        code, report = build_affinity(root, copy, privacy=privacy)
        if code:
            return list(report["errors"])
        differences = []
        built_corpus = json.loads((copy / "cases.json").read_text(encoding="utf-8"))
        if legacy_names.normalize_affinity_corpus(built_corpus) != versioned_corpus:
            differences.append("cases.json ya no coincide con el constructor")
        traps_name = legacy_names.TRAPS_FILE_NAMES[1]
        built_traps = json.loads((copy / traps_name).read_text(encoding="utf-8"))
        versioned_traps = json.loads(
            _versioned(target, legacy_names.TRAPS_FILE_NAMES).read_text(encoding="utf-8")
        )
        if legacy_names.normalize_affinity_traps(
            built_traps
        ) != legacy_names.normalize_affinity_traps(versioned_traps):
            differences.append(f"{traps_name} ya no coincide con el constructor")
        for source in sorted((copy / "fuentes").iterdir()):
            versioned = target / "fuentes" / source.name
            if not versioned.is_file() or versioned.read_bytes() != source.read_bytes():
                differences.append(f"fuentes/{source.name} ya no coincide con el constructor")
    return differences


def main_affinity(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="build_corpus.py affinity")
    parser.add_argument("--dest", type=Path, default=AFFINITY_TARGET)
    parser.add_argument(
        "--privacy",
        choices=("fail", "exclude"),
        default="fail",
        help="que hacer si un diff lleva datos privados: parar, o pasar al siguiente candidato",
    )
    parser.add_argument("--check", action="store_true", help="reconstruye y compara")
    parser.add_argument("--dry-run", action="store_true", help="no escribe nada, solo informa")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    # El idioma de los prompts de commit sale del entorno (REQ-044): se dice, para que un corpus
    # construido o comprobado sin la variable no pase por el de produccion sin que se note.
    print(f"idioma del mensaje de commit: {config.commit_language() or '(el del diff)'}")
    if args.check:
        differences = check_versioned_affinity(args.dest)
        for d in differences:
            print(f"  - {d}")
        print("ok" if not differences else f"{len(differences)} diferencias")
        return 1 if differences else 0
    code, report = build_affinity(ROOT, args.dest, privacy=args.privacy, write=not args.dry_run)
    for line in report["errors"]:
        print(f"  - {line}")
    print(
        json.dumps(
            {"cases": report["cases"], "by_tool": report["by_tool"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    if code:
        print("El corpus NO se escribe. Reglas que no se cumplen (arriba).")
    return code


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] == "affinity":
        return main_affinity(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dest", type=Path, default=DESTINATION)
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", "")) / "local-delegate",
        help="carpeta con usage-*.jsonl; si no existe, no se regeneran los conteos",
    )
    parser.add_argument("--check", action="store_true", help="solo recaptura lo versionado")
    parser.add_argument(
        "--refresh-sources",
        action="store_true",
        help="vuelve a congelar las fuentes desde los ficheros vivos (cambia el corpus medido)",
    )
    args = parser.parse_args(argv)
    if args.check:
        errors = check_versioned(args.dest)
        for error in errors:
            print(f"  - {error}")
        print("ok" if not errors else f"{len(errors)} diferencias")
        return 1 if errors else 0
    return build(ROOT, args.dest, args.log_dir, refresh_sources=args.refresh_sources)


if __name__ == "__main__":
    sys.exit(main())
