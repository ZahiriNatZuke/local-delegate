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

El subcomando `afinidad` construye el corpus de la evaluacion de afinidad del SDD
`daemon-reparte-el-backend` (REQ-040, `benchmarks/afinidad-2026-10/`): casos mecanicos con su
puntuador, los 30 commits de la regla escrita, las trampas y el techo. Captura los prompts
llamando a las tools reales con el backend interceptado; no carga ningun modelo.

Uso:

    uv run python scripts/construir_corpus.py afinidad     # corpus de afinidad (ver --help)
    uv run python scripts/construir_corpus.py              # congela, captura, comprueba, escribe
    uv run python scripts/construir_corpus.py --comprobar  # recaptura contra lo versionado
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

from local_delegate import benchmark, config, server

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "benchmarks" / "catalogo-2026-09"
MARCADOR = "{CONTENIDO}"

Fuente = Callable[[Path], bytes]
Terminos = tuple[str, ...] | Callable[[str], tuple[str, ...]]


# --- Fuentes -----------------------------------------------------------------------------------


def normalizado(datos: bytes) -> str:
    """Lo que ve el modelo: `_read_input` lee con `read_text`, que convierte `\\r\\n` en `\\n`."""
    texto = datos.decode("utf-8", errors="replace")
    return texto.replace("\r\n", "\n").replace("\r", "\n")


def fichero(rel: str) -> Fuente:
    return lambda raiz: (raiz / rel).read_bytes()


def recorte_por_lineas(rel: str, limite: int, frontera: str | None = None) -> Fuente:
    """Lineas enteras hasta `limite` chars; con `frontera`, corta antes de una linea que case."""

    def generar(raiz: Path) -> bytes:
        return cortar_lineas(normalizado((raiz / rel).read_bytes()), limite, frontera).encode()

    return generar


def cortar_lineas(texto: str, limite: int, frontera: str | None = None) -> str:
    lineas = texto.splitlines(keepends=True)
    acumulado = 0
    corte = 0
    for indice, linea in enumerate(lineas):
        if acumulado + len(linea) > limite:
            break
        acumulado += len(linea)
        siguiente = lineas[indice + 1] if indice + 1 < len(lineas) else ""
        if frontera is None or re.match(frontera, siguiente):
            corte = indice + 1
    return "".join(lineas[:corte])


def recorte_exacto(rel: str, limite: int) -> Fuente:
    """Los primeros `limite` chars sin buscar frontera: lo que `_read_input` deja ver al modelo."""
    return lambda raiz: normalizado((raiz / rel).read_bytes())[:limite].encode("utf-8")


def _git(raiz: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=raiz, capture_output=True, check=True).stdout


def diff_de_commit(commit: str) -> Fuente:
    return lambda raiz: _git(raiz, "show", "--format=", "--no-color", "--no-ext-diff", commit)


def blob(commit: str, rel: str) -> Fuente:
    return lambda raiz: _git(raiz, "show", f"{commit}:{rel}")


def archivos_enteros(salida: str, limite: int) -> str:
    """Los avisos de ruff de los primeros archivos, ENTEROS, mientras quepan en `limite` chars.

    Un archivo cortado a medias daria conteos que la fuente no respalda. Lo que no es un aviso
    (`Found N errors.`) queda en su propio bloque, al final, y no se alcanza.
    """
    bloques: dict[str, list[str]] = {}
    for linea in salida.splitlines(keepends=True):
        bloques.setdefault(linea.split(":", 1)[0], []).append(linea)
    elegidas: list[str] = []
    acumulado = 0
    for lineas in bloques.values():
        tamano = sum(len(linea) for linea in lineas)
        if acumulado + tamano > limite:
            break
        elegidas += lineas
        acumulado += tamano
    return "".join(elegidas)


def salida_de_ruff_por_archivos(limite: int) -> Fuente:
    def generar(raiz: Path) -> bytes:
        proceso = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select", "ALL"]
            + ["--output-format", "concise", "--no-cache", "src/local_delegate"],
            cwd=raiz,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # ruff sale con 1 cuando encuentra algo, que es justo lo que se quiere. Las barras se
        # normalizan para que la salida no dependa del sistema en que se genero.
        return archivos_enteros(proceso.stdout.replace("\\", "/"), limite).encode("utf-8")

    return generar


def secciones_de_version(rel: str, desde: str, hasta: str) -> Fuente:
    """Del `## [desde]` hasta antes de `## [hasta]`. Las secciones publicadas no cambian: el
    CHANGELOG solo crece por arriba, asi que el recorte es reproducible aunque el fichero no."""

    def generar(raiz: Path) -> bytes:
        texto = normalizado((raiz / rel).read_bytes())
        inicio = texto.index(f"## [{desde}]")
        return texto[inicio : texto.index(f"## [{hasta}]", inicio)].encode("utf-8")

    return generar


def texto_literal(contenido: str) -> Fuente:
    return lambda _raiz: contenido.encode("utf-8")


# --- Terminos derivados de la fuente, no escritos a ojo -----------------------------------------


def _primeros(patron: str, n: int = 3, grupo: int = 1) -> Callable[[str], tuple[str, ...]]:
    def derivar(texto: str) -> tuple[str, ...]:
        vistos: list[str] = []
        for match in re.finditer(patron, texto, flags=re.MULTILINE):
            valor = match.group(grupo)
            if valor not in vistos:
                vistos.append(valor)
            if len(vistos) == n:
                break
        return tuple(vistos)

    return derivar


def _reglas_mas_frecuentes(texto: str) -> tuple[str, ...]:
    conteo = Counter(re.findall(r": ([A-Z]+[0-9]+) ", texto))
    return tuple(regla for regla, _ in conteo.most_common(3))


# Segundo piloto de CP-3: el 2B se invento los conteos de lint y la cobertura no lo veia. Para cada
# regla que el caso pide nombrar, los numeros que la fuente respalda: el total, cuantos archivos la
# tienen y lo que suma en cada archivo. Salen de las lineas de ruff, no de lo que dijo un modelo.
def _conteos_de_las_reglas(texto: str) -> dict[str, list[int]]:
    por_regla: dict[str, Counter[str]] = {}
    for archivo, regla in re.findall(
        r"^(\S+?):\d+:\d+: ([A-Z]+[0-9]+) ", texto, flags=re.MULTILINE
    ):
        por_regla.setdefault(regla, Counter())[archivo] += 1
    return {
        regla: sorted(
            {sum(por_regla[regla].values()), len(por_regla[regla]), *por_regla[regla].values()}
        )
        for regla in _reglas_mas_frecuentes(texto)
    }


def formato_pedido(system: str | None) -> dict[str, Any]:
    """Lo que la instruccion de la tool pide de forma comprobable: limite de palabras y prosa.

    P-15: el usuario descarto respuestas por salirse de las dos cosas, y la cobertura de terminos no
    lo miraba. Sale del prompt capturado de la tool real, no de lo que devolvio un modelo.
    """
    if not system:
        return {}
    formato: dict[str, Any] = {}
    if limite := re.search(r"M[aá]ximo (\d+) palabras", system):
        formato["max_words"] = int(limite.group(1))
    if re.search(r"\bprosa\b", system):
        formato["prose"] = True
    return formato


def _docstring_del_modulo(texto: str) -> str:
    partes = texto.split('"""')
    return partes[1] if len(partes) > 2 else ""


# «Explica que hace el codigo y como» no pide nombrar helpers privados, y CP-3 (tarea 19) lo
# demostro: con los tres primeros `def` del fichero, dos explicaciones correctas sacaban 0. Lo que la
# explicacion SI tiene que cubrir es lo que el modulo declara de si mismo en su docstring: sus rutas
# o los ficheros y opciones que toca. Mas terminos, ademas, dan granularidad a la banda (P-12).
def _rutas_del_docstring(texto: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"GET (/api/\S+)", _docstring_del_modulo(texto))))


def _ficheros_y_flags_del_docstring(texto: str) -> tuple[str, ...]:
    entre_comillas = re.findall(r"`([^`]+)`", _docstring_del_modulo(texto))
    ficheros = [re.sub(r".*/", "", t) for t in entre_comillas if re.search(r"\.(json|md|bak)$", t)]
    flags = [t for t in entre_comillas if t.startswith("--")]
    return tuple(dict.fromkeys(ficheros + flags))


# Un mensaje de commit tiene que nombrar el cambio, y el diff trae como lo nombro su autor: la
# primera entrada «Fixed» que anade al CHANGELOG. Con un unico termino (`inflight`), CP-3 dio 0 al
# mensaje que nombraba el arreglo y al que solo nombraba el bump de version. Se quitan los privados
# (`_x`) y los comandos con espacios; de una ruta a fichero se queda el nombre.
def _identificadores_del_primer_arreglo(texto: str) -> tuple[str, ...]:
    lineas = texto.splitlines()
    inicio = next((n for n, linea in enumerate(lineas) if linea == "+### Fixed"), None)
    if inicio is None:
        return ()
    entrada: list[str] = []
    for linea in lineas[inicio + 1 :]:
        if not linea.startswith("+"):
            break
        cuerpo = linea[1:]
        if cuerpo.startswith("#") or (cuerpo.startswith("- ") and entrada):
            break
        if cuerpo.startswith("- ") or entrada:
            entrada.append(cuerpo)
    limpios = []
    for termino in re.findall(r"`([^`]+)`", " ".join(entrada)):
        if " " in termino or termino.startswith("_"):
            continue
        ultimo = termino.rsplit("/", 1)[-1]
        limpios.append((ultimo if "." in ultimo else termino).removesuffix("()"))
    return tuple(dict.fromkeys(limpios))


# Un resumen de un changelog tiene que decir que cambio, y cada entrada lo resume en su titular en
# negrita. Antes eran los numeros de version, que el prompt («resumen en prosa») no pide: CP-3 los
# dio a 0 en los dos modelos, un suelo.
def _identificadores_de_los_titulares(texto: str) -> tuple[str, ...]:
    titulares = re.findall(r"^- \*\*(.+?)\*\*", texto, flags=re.MULTILINE | re.DOTALL)
    return tuple(
        dict.fromkeys(
            termino.removesuffix("()")
            for titular in titulares
            for termino in re.findall(r"`([^`]+)`", titular)
        )
    )


def _valores_toml(*claves: str) -> Callable[[str], tuple[str, ...]]:
    def derivar(texto: str) -> tuple[str, ...]:
        valores = []
        for clave in claves:
            match = re.search(rf'^{re.escape(clave)} = "?([^"\n]+)"?$', texto, flags=re.MULTILINE)
            if match:
                valores.append(match.group(1))
        return tuple(valores)

    return derivar


# --- Casos (protocolo-f2.md §4.4) -----------------------------------------------------------------


@dataclass(frozen=True)
class Caso:
    id: str
    tool: str
    role: str
    kind: str
    procedencia: str
    origen: str
    fuente: Fuente
    extension: str = "txt"
    media_type: str = "texto"
    argumentos: dict[str, Any] = field(default_factory=dict)
    expected_terms: Terminos = ()
    forbidden_terms: tuple[str, ...] = ()
    expected_json_fields: tuple[str, ...] = ()
    # Los terminos esperados tienen que estar en la fuente, salvo donde la salida no la copia:
    # una traduccion, una etiqueta elegida o lo que se ve en una imagen.
    terminos_en_fuente: bool = True
    # Pareja de referencia de CP-4: (senal, respuesta buena, respuesta mala). Solo en seis casos.
    referencia: tuple[str, str, str] | None = None
    # Comprobaciones que el puntuador EJECUTA sobre el codigo generado: {"expr", "expected"} o
    # {"expr", "raises"}. Salen de la especificacion del caso, no de lo que devolvio un modelo.
    comprobaciones: tuple[dict[str, Any], ...] = ()
    # Conteos que el puntuador comprueba contra la fuente, derivados de ella: {regla: validos}.
    conteos: Callable[[str], dict[str, list[int]]] | None = None
    # False: la regla de §7 no lo cuenta y lo juzga solo la revision a ciegas (§4.8).
    puntuacion_automatica: bool = True


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

CASOS: tuple[Caso, ...] = (
    # --- mechanical ---
    Caso(
        "resumen-md-2k",
        "local_summarize",
        "mechanical",
        "calidad",
        "congelado",
        "CONTRIBUTING.md",
        fichero("CONTRIBUTING.md"),
        extension="md",
        expected_terms=("pre-commit", "pull request"),
        referencia=(
            "cobertura",
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
    Caso(
        "extraer-toml-2k",
        "local_extract",
        "mechanical",
        "calidad",
        "congelado",
        "pyproject.toml, recortado en linea entera a 2 100 chars (entero pesa mas de 6 000 y "
        "produccion lo mandaria a long)",
        recorte_por_lineas("pyproject.toml", 2100),
        extension="toml",
        expected_json_fields=("name", "version", "requires-python", "license"),
        expected_terms=_valores_toml("name", "version", "requires-python", "license"),
        referencia=(
            "json_valido",
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
    Caso(
        "clasificar-53",
        "local_classify",
        "mechanical",
        "calidad",
        "reconstruido",
        "evento inline real de 53 chars; texto recreado con esa forma",
        texto_literal("El dashboard dejó de cargar tras actualizar a 0.27.0."),
        argumentos={"labels": ["bug", "feature", "docs", "pregunta"]},
        expected_terms=("bug",),
        forbidden_terms=("feature", "docs", "pregunta"),
        terminos_en_fuente=False,
    ),
    Caso(
        "traducir-42",
        "local_translate",
        "mechanical",
        "calidad",
        "reconstruido",
        "evento inline real de 42 chars; texto recreado con esa forma",
        texto_literal("Reinicia el daemon después de actualizarlo"),
        argumentos={"target_lang": "inglés"},
        expected_terms=("restart", "daemon", "updat"),
        forbidden_terms=("reinicia",),
        terminos_en_fuente=False,
    ),
    Caso(
        "delegar-56",
        "local_delegate",
        "mechanical",
        "calidad",
        "reconstruido",
        "evento inline real de 56 chars; texto recreado con esa forma",
        texto_literal("tokens, latencia, modelo, errores, reintentos y el coste"),
        argumentos={
            "task": "Convierte esta enumeración en una lista con una viñeta por elemento.",
            "output_format": "lista Markdown con una viñeta '- ' por elemento",
        },
        expected_terms=("tokens", "latencia", "modelo", "errores", "reintentos", "coste"),
    ),
    # --- long ---
    Caso(
        "resumen-md-10k",
        "local_summarize",
        "long",
        "calidad",
        "congelado",
        "docs/recipes/claude-code-hooks.md",
        fichero("docs/recipes/claude-code-hooks.md"),
        extension="md",
        expected_terms=("UserPromptSubmit", "PreToolUse", "LD_HOOK_READ_BLOQUEAR"),
        # P-15: la cobertura de terminos no coincidio con el juicio humano (0 de 3, invertida). Lo
        # decide la comparacion por pares a ciegas; los terminos se quedan como dato.
        puntuacion_automatica=False,
    ),
    Caso(
        # Tarea 19: sustituye a `resumen-changelog-43k`, cuyos terminos eran un suelo. Dos secciones
        # y no una: la 0.27.0 sola pesa 5 507 chars, bajo LONG_INPUT_CHARS, y produccion la
        # mandaria a mechanical. Son las mismas que abrian la fuente congelada anterior.
        "resumen-changelog-7k",
        "local_summarize",
        "long",
        "calidad",
        "congelado",
        "CHANGELOG.md, secciones 0.27.0 y 0.26.0",
        secciones_de_version("CHANGELOG.md", "0.27.0", "0.25.0"),
        extension="md",
        expected_terms=_identificadores_de_los_titulares,
        puntuacion_automatica=False,  # P-15: 3 de 4 contra el juicio humano; lo deciden los pares
    ),
    Caso(
        "extraer-uvlock-48k",
        "local_extract",
        "long",
        "calidad",
        "congelado",
        "uv.lock, recortado a los 48 000 chars que `_read_input` deja ver al rol long",
        recorte_exacto("uv.lock", 48000),
        extension="lock",
        expected_json_fields=("version", "requires-python", "primer_paquete"),
        # `version = 1` no sirve de termino: un «1» aparece en cualquier respuesta.
        expected_terms=lambda texto: (
            _valores_toml("requires-python")(texto)
            + _primeros(r'^\[\[package\]\]\nname = "([^"]+)"', n=1)(texto)
        ),
        referencia=(
            "json_campos",
            '{"version": 1, "requires-python": ">=3.11", "primer_paquete": "annotated-doc"}',
            '{"version": 1, "requires-python": ">=3.11", "paquete_primer": "annotated-doc"}',
        ),
    ),
    Caso(
        # Segundo piloto de CP-3: `lint-33k` (14 archivos, 48 reglas) no cabia «agrupado por archivo»
        # en 200 palabras, y los dos modelos truncaban siempre. Archivos enteros hasta 9 000 chars:
        # sigue por encima de LONG_INPUT_CHARS, asi que produccion la manda a long.
        "lint-9k",
        "local_lint_summary",
        "long",
        "calidad",
        "generado",
        "ruff check --select ALL --output-format concise --no-cache src/local_delegate, "
        "archivos enteros hasta 9 000 chars",
        salida_de_ruff_por_archivos(9000),
        expected_terms=_reglas_mas_frecuentes,
        conteos=_conteos_de_las_reglas,
        # Tercer piloto de CP-3: 0 en los dos modelos otra vez. El 2B se inventa los conteos y el 14B
        # los da bien pero lista TODO y trunca: el prompt de la tool no cabe con esta entrada, y eso
        # se arregla en la tool (F3). Lo juzga la revision a ciegas (decision del usuario).
        puntuacion_automatica=False,
        # Pareja de CP-4 de conteos: las dos nombran las tres reglas; la mala cambia un 7 por un 9,
        # que no es ni el total, ni los archivos, ni lo de ningun archivo.
        referencia=(
            "conteos",
            "COM812: 16 avisos en 2 archivos. TRY003: 8. D102: 7.",
            "COM812: 16 avisos en 2 archivos. TRY003: 8. D102: 9.",
        ),
    ),
    # --- code ---
    Caso(
        "commit-diff-19k",
        "local_commit_msg",
        "code",
        "calidad",
        "congelado",
        "git show 4d644ae (fix(web): inflight multi-proceso)",
        diff_de_commit("4d644ae"),
        extension="diff",
        expected_terms=_identificadores_del_primer_arreglo,
        # Dos pilotos de CP-3 con 0 en los dos modelos: un asunto de <=72 chars rara vez lleva
        # identificadores y el cuerpo es opcional. Lo juzga la revision a ciegas (decision del
        # usuario, 2026-09-14); los terminos se quedan como dato.
        puntuacion_automatica=False,
    ),
    Caso(
        "explicar-metrics-15k",
        "local_explain_code",
        "code",
        "calidad",
        "congelado",
        "src/local_delegate/web/metrics.py, recortado antes de un bloque de nivel superior",
        recorte_por_lineas("src/local_delegate/web/metrics.py", 17000, _TOP_LEVEL_PY),
        extension="py.txt",
        expected_terms=_rutas_del_docstring,
        puntuacion_automatica=False,  # P-15: sin base contra el juicio humano; lo deciden los pares
    ),
    Caso(
        "explicar-install-20k",
        "local_explain_code",
        "code",
        "calidad",
        "congelado",
        "src/local_delegate/install.py, recortado a los 20 000 chars que ve el rol code",
        recorte_exacto("src/local_delegate/install.py", 20000),
        extension="py.txt",
        expected_terms=_ficheros_y_flags_del_docstring,
        puntuacion_automatica=False,  # P-15: 2 de 4 contra el juicio humano; lo deciden los pares
    ),
    Caso(
        "boilerplate-156",
        "local_boilerplate",
        "code",
        "calidad",
        "reconstruido",
        "evento inline real de 156 chars; especificacion recreada con esa forma",
        texto_literal(
            "Función parse_duration(texto) que convierta '1h30m', '45s' o '2m' en segundos "
            "(int) y lance ValueError si el formato no es válido. Con docstring y ejemplos."
        ),
        argumentos={"language": "python"},
        expected_terms=("parse_duration", "ValueError"),
        # CP-3 (tarea 19) dio 1,0 por terminos a dos funciones rotas. Una por ejemplo de la
        # especificacion (y `expected` exige el tipo: pide un int) y dos formatos invalidos, que
        # la especificacion dice que lanzan ValueError.
        comprobaciones=(
            {"expr": "parse_duration('1h30m')", "expected": 5400},
            {"expr": "parse_duration('45s')", "expected": 45},
            {"expr": "parse_duration('2m')", "expected": 120},
            {"expr": "parse_duration('abc')", "raises": "ValueError"},
            {"expr": "parse_duration('5x')", "raises": "ValueError"},
        ),
        referencia=(
            "ejecucion",
            _PARSE_DURATION.replace("{MINUTO}", "60"),
            _PARSE_DURATION.replace("{MINUTO}", "61"),
        ),
    ),
    # --- vision ---
    Caso(
        "describir-dashboard",
        "local_describe_image",
        "vision",
        "calidad",
        "congelado",
        "docs/assets/dashboard.png",
        fichero("docs/assets/dashboard.png"),
        extension="png",
        media_type="imagen",
        # `computo` va SIN acento a proposito, y el panel dice «cómputo»: es el termino que solo
        # casa si el puntuador normaliza. Sin el, la pareja de Unicode de CP-4 no tendria donde caer.
        expected_terms=("delegaciones", "backend", "ahorro", "computo"),
        referencia=(
            "unicode",
            "Panel de ahorro con el estado del backend, las delegaciones y dónde corrió el cómputo.",
            "Panel de ahorro con el estado del backend, las delegaciones y dónde corrió el cálculo.",
        ),
        terminos_en_fuente=False,
    ),
    Caso(
        "leer-cifras-dashboard",
        "local_describe_image",
        "vision",
        "calidad",
        "inventado",
        "docs/assets/dashboard.png con una pregunta que no corresponde a ningun evento real",
        fichero("docs/assets/dashboard.png"),
        extension="png",
        media_type="imagen",
        argumentos={
            # Las seis cifras grandes del panel son IDENTICAS en esta imagen y en la de control
            # (datos de demostracion fijos): preguntar por ellas no podria bajar con la imagen
            # equivocada. Se pregunta por lo que si cambia entre las dos.
            "question": (
                "¿Qué versión muestra la insignia junto al logo, y qué fecha y hora tiene la "
                "primera fila de «Actividad reciente»? Responde solo con esos tres datos."
            )
        },
        expected_terms=("0.27.0", "29/8", "05:01"),
        referencia=(
            "prohibido",
            "Versión 0.27.0 (la publicada); primera fila: 29/8 a las 05:01.",
            "Versión 0.27.0 (antes 0.24.0); primera fila: 29/8 a las 05:01.",
        ),
        forbidden_terms=("0.24.0", "24/7", "23:12"),
        terminos_en_fuente=False,
    ),
    # --- sondeos de techo: no puntuan calidad ---
    Caso(
        "techo-resumen-103k",
        "local_summarize",
        "long",
        "techo",
        "congelado",
        "src/local_delegate/server.py entero",
        fichero("src/local_delegate/server.py"),
        extension="py.txt",
    ),
    Caso(
        "techo-commit-156k",
        "local_commit_msg",
        "code",
        "techo",
        "reconstruido",
        "git show d7c3dcc: el diff de 164 585 chars del log ya no existe; este es el mayor del "
        "historial de ese orden",
        diff_de_commit("d7c3dcc"),
        extension="diff",
    ),
)

CONTROLES = (
    {
        "id": "dashboard-bcbe39f",
        "para": ["describir-dashboard", "leer-cifras-dashboard"],
        "procedencia": "congelado",
        "origen": "git show bcbe39f:docs/assets/dashboard.png (0.24.0)",
        "fuente": blob("bcbe39f", "docs/assets/dashboard.png"),
        "extension": "png",
    },
)


# --- Captura contra el codigo de produccion -----------------------------------------------------


# Lo que la captura NO quita del entorno: el idioma del mensaje de commit (REQ-044) es parte del prompt
# de produccion de `local_commit_msg`, y los casos de commit del corpus de afinidad tienen que llevar
# el prompt con el idioma que tendra la maquina (`LOCAL_DELEGATE_COMMIT_IDIOMA=es`), no el de un
# entorno limpio. `config.commit_idioma()` lee al llamar, asi que no hace falta recargar `config`.
# Con la variable puesta, el corpus que sale cambia: `main_afinidad` imprime el idioma usado y
# `afinidad --comprobar` tiene que correr con el mismo.
VARIABLES_QUE_SE_CONSERVAN = frozenset({"LOCAL_DELEGATE_COMMIT_IDIOMA"})


@dataclass
class Llamada:
    model: str
    system: str
    user: Any
    max_tokens: int
    temperature: float
    response_format: dict | None


@contextlib.contextmanager
def produccion_interceptada() -> Iterator[list[Llamada]]:
    """Las tools reales, sin backend, sin log de uso y sin las variables del paquete."""
    llamadas: list[Llamada] = []
    guardado = {
        n: os.environ[n]
        for n in config.VARIABLES_DE_ENTORNO
        if n in os.environ and n not in VARIABLES_QUE_SE_CONSERVAN
    }

    def run_chat(model, system, user, max_tokens, temperature, *, response_format=None, **_):
        llamadas.append(Llamada(model, system, user, max_tokens, temperature, response_format))
        resultado = server.ChatResult(text="{}", ok=True, finish_reason="stop")
        return resultado, 0, None, [server.Intento(model, True, None, None, 0)]

    try:
        # Solo se recarga si habia algo que quitar: dentro de la suite el entorno ya viene limpio,
        # y recargar desharia el LOG_DIR temporal de conftest y apuntaria al log real.
        for nombre in guardado:
            del os.environ[nombre]
        if guardado:
            importlib.reload(config)
        with (
            mock.patch.object(server, "_run_chat", run_chat),
            mock.patch.object(server, "_log_event", lambda **_: None),
            mock.patch.object(server, "_inflight_start", lambda **_: 0),
            mock.patch.object(server, "_inflight_end", lambda *_: None),
            # Un LOCAL_DELEGATE_ALLOWED_DIRS del usuario no debe impedir leer las fuentes.
            mock.patch.object(server, "_check_allowed_dir", lambda _ruta: None),
        ):
            yield llamadas
    finally:
        os.environ.update(guardado)
        if guardado:
            importlib.reload(config)


def roles_de_produccion() -> dict[str, str]:
    return {
        config.MODEL_MECHANICAL: "mechanical",
        config.MODEL_LONG: "long",
        config.MODEL_CODE: "code",
        config.MODEL_VISION: "vision",
    }


def invocar(caso: Caso, ruta: Path, texto: str, tmp: Path) -> None:
    args = caso.argumentos
    tool = caso.tool
    if tool == "local_summarize":
        server.local_summarize(path=str(ruta))
    elif tool == "local_extract":
        server.local_extract(fields=list(caso.expected_json_fields), path=str(ruta))
    elif tool == "local_lint_summary":
        server.local_lint_summary(path=str(ruta))
    elif tool == "local_commit_msg":
        server.local_commit_msg(path=str(ruta))
    elif tool == "local_explain_code":
        server.local_explain_code(path=str(ruta))
    elif tool == "local_describe_image":
        server.local_describe_image(path=str(ruta), question=args.get("question"))
    elif tool == "local_classify":
        server.local_classify(text=texto, labels=args["labels"])
    elif tool == "local_translate":
        server.local_translate(target_lang=args["target_lang"], text=texto)
    elif tool == "local_delegate":
        server.local_delegate(task=args["task"], input=texto, output_format=args["output_format"])
    elif tool == "local_boilerplate":
        server.local_boilerplate(
            spec=texto, language=args["language"], target=str(tmp / "generado.txt")
        )
    else:
        raise ValueError(f"tool sin invocacion: {tool}")


@dataclass
class Captura:
    llamadas: list[Llamada]
    role: str | None
    modelos: set[str]
    entrada_entera: bool
    user_template: str | None


def capturar(caso: Caso, ruta: Path, datos: bytes, *, sin_troceo: bool = False) -> Captura:
    """Con `sin_troceo`, la tool sigue la ruta de UNA llamada aunque la entrada no quepa: es el
    prompt que necesita un sondeo de techo, que mide justo la mayor llamada unica que acepta el
    modelo. Produccion no lo manda nunca asi; por eso se captura aparte."""
    texto = normalizado(datos) if caso.media_type == "texto" else ""
    with produccion_interceptada() as llamadas, tempfile.TemporaryDirectory() as tmp:
        # Los dos topes: el del rol (modelo principal de cada tool) y el del modelo (respaldos).
        sin_limite = mock.patch.multiple(
            config, max_chars_for=lambda _modelo: 2**31, max_chars_for_role=lambda _rol: 2**31
        )
        with sin_limite if sin_troceo else contextlib.nullcontext():
            invocar(caso, ruta, texto, Path(tmp))
        roles = roles_de_produccion()
    modelos = {llamada.model for llamada in llamadas}
    role = roles.get(llamadas[0].model) if llamadas else None
    entrada_entera = False
    plantilla = None
    if len(llamadas) == 1:
        user = llamadas[0].user
        if caso.media_type == "imagen" and isinstance(user, list):
            imagen = base64.b64encode(datos).decode("ascii")
            entrada_entera = any(imagen in json.dumps(bloque) for bloque in user)
            plantilla = next(b["text"] for b in user if b.get("type") == "text")
        elif isinstance(user, str) and texto and texto in user:
            entrada_entera = True
            plantilla = user.replace(texto, MARCADOR, 1)
    return Captura(llamadas, role, modelos, entrada_entera, plantilla)


def terminos(caso: Caso, texto: str) -> tuple[str, ...]:
    return caso.expected_terms(texto) if callable(caso.expected_terms) else caso.expected_terms


# --- Parejas de referencia de CP-4 (tarea 15) ---------------------------------------------------

# Las senales en que TIENE que diferir cada pareja, y ninguna mas. Si difiere en otra, CP-4 no podra
# decir por que separo el puntuador. `cobertura_literal` es la cobertura sin normalizar: la pareja de
# Unicode es la unica donde NO cambia, porque su buena solo acierta quitando acentos, y un puntuador
# literal puntuaria igual de mal las dos. `json_campos` acompana a `json_valido` por construccion:
# sin JSON no hay campos que mirar.
DIFERENCIAS_ESPERADAS: dict[str, set[str]] = {
    "cobertura": {"cobertura", "cobertura_literal"},
    "prohibido": {"prohibido"},
    "json_valido": {"json_valido", "json_campos"},
    "json_campos": {"json_campos"},
    "unicode": {"cobertura"},
    "ejecucion": {"ejecucion"},
    "conteos": {"conteos"},
}


def _enteros_sueltos(tramo: str) -> list[int]:
    """Tiradas de digitos que no pegan a una letra, un digito o `_`, ni forman un decimal. Un punto
    de final de frase no las anula. Recorrido a mano, sin las expresiones del puntuador: es su
    oraculo."""
    enteros: list[int] = []
    i = 0
    while i < len(tramo):
        if not tramo[i].isdigit():
            i += 1
            continue
        j = i
        while j < len(tramo) and tramo[j].isdigit():
            j += 1
        antes = tramo[i - 1] if i else " "
        despues = tramo[j] if j < len(tramo) else " "
        decimal = despues == "." and j + 1 < len(tramo) and tramo[j + 1].isdigit()
        if not (antes.isalnum() or antes in "._") and not (
            despues.isalnum() or despues == "_" or decimal
        ):
            enteros.append(int(tramo[i:j]))
        i = j
    return enteros


def _tramos_por_regla(linea: str) -> list[tuple[str, str]]:
    """(codigo, lo que le sigue hasta el siguiente codigo) de cada codigo de regla de la linea."""
    tramos: list[tuple[str, str]] = []
    actual: str | None = None
    trozo: list[str] = []
    i = 0
    while i < len(linea):
        if linea[i].isupper() and (i == 0 or not linea[i - 1].isalnum()):
            letras = i
            while letras < len(linea) and linea[letras].isupper():
                letras += 1
            fin = letras
            while fin < len(linea) and linea[fin].isdigit():
                fin += 1
            if fin > letras and (fin == len(linea) or not linea[fin].isalnum()):
                if actual is not None:
                    tramos.append((actual, "".join(trozo)))
                actual, trozo = linea[i:fin], []
                i = fin
                continue
        if actual is not None:
            trozo.append(linea[i])
        i += 1
    if actual is not None:
        tramos.append((actual, "".join(trozo)))
    return tramos


def _conteos_cuadran(texto: str, conteos: Mapping[str, Sequence[int]]) -> bool:
    numeros: dict[str, list[int]] = {regla: [] for regla in conteos}
    for linea in texto.split("\n"):
        for regla, tramo in _tramos_por_regla(linea):
            if regla in numeros:
                numeros[regla] += _enteros_sueltos(tramo)
    return all(
        numeros[regla] and set(numeros[regla]) <= set(validos) for regla, validos in conteos.items()
    )


def _ejecuta_bien(codigo: str, comprobaciones: Sequence[dict[str, Any]]) -> bool:
    """El oraculo de la senal de ejecucion, en proceso y sin el arnes del puntuador: si los dos
    compartieran codigo compartirian tambien el error. Solo corre referencias escritas a mano."""
    espacio: dict[str, Any] = {"__name__": "referencia"}
    try:
        exec(compile(codigo, "referencia", "exec"), espacio)  # noqa: S102 - referencia propia
    except Exception:
        return False
    for comprobacion in comprobaciones:
        try:
            valor = eval(comprobacion["expr"], espacio)
        except Exception as exc:
            if type(exc).__name__ != comprobacion.get("raises"):
                return False
            continue
        esperado = comprobacion.get("expected")
        if "raises" in comprobacion or type(valor) is not type(esperado) or valor != esperado:
            return False
    return True


def plano(texto: str) -> str:
    """NFKD, sin marcas combinantes y casefold.

    NFKD solo NO basta: descompone la «ó» en «o» mas un acento suelto, y el acento sigue ahi.
    """
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).casefold()


def senales(
    texto: str,
    esperados: Sequence[str],
    prohibidos: Sequence[str],
    campos: Sequence[str],
    comprobaciones: Sequence[dict[str, Any]] = (),
    conteos: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, bool | None]:
    """Oraculo de CP-4. Independiente del puntuador de la tarea 16 a proposito: es contra lo que
    ese puntuador se valida, y si compartieran codigo compartirian tambien el error."""
    try:
        objeto = json.loads(texto.strip())
    except ValueError:
        objeto = None
    valido = isinstance(objeto, dict) if campos else None
    return {
        "cobertura": all(plano(t) in plano(texto) for t in esperados),
        "cobertura_literal": all(t.casefold() in texto.casefold() for t in esperados),
        "prohibido": any(plano(t) in plano(texto) for t in prohibidos),
        "json_valido": valido,
        "json_campos": (set(campos) <= set(objeto)) if valido else None,
        "ejecucion": _ejecuta_bien(texto, comprobaciones) if comprobaciones else None,
        "conteos": _conteos_cuadran(texto, conteos) if conteos else None,
    }


def comprobar_referencia(
    caso: Caso, esperados: Sequence[str], conteos: Mapping[str, Sequence[int]] | None = None
) -> list[str]:
    if caso.referencia is None:
        return []
    senal, buena, mala = caso.referencia
    if senal not in DIFERENCIAS_ESPERADAS:
        return [f"{caso.id}: senal de referencia desconocida {senal!r}"]
    errores: list[str] = []
    if len(buena) != len(mala):
        errores.append(
            f"{caso.id}: la pareja no tiene la misma longitud ({len(buena)} y {len(mala)})"
        )
    argumentos = (caso.forbidden_terms, caso.expected_json_fields, caso.comprobaciones, conteos)
    ok = senales(buena, esperados, *argumentos)
    malo = senales(mala, esperados, *argumentos)
    if (
        not ok["cobertura"]
        or ok["prohibido"]
        or False
        in (
            ok["json_valido"],
            ok["json_campos"],
            ok["ejecucion"],
            ok["conteos"],
        )
    ):
        errores.append(f"{caso.id}: la respuesta buena no es buena: {ok}")
    difieren = {nombre for nombre in ok if ok[nombre] != malo[nombre]}
    if difieren != DIFERENCIAS_ESPERADAS[senal]:
        errores.append(
            f"{caso.id}: la pareja de {senal} difiere en {sorted(difieren)}, "
            f"no en {sorted(DIFERENCIAS_ESPERADAS[senal])}"
        )
    return errores


def comprobar(
    caso: Caso, captura: Captura, datos: bytes, unica: Captura | None = None
) -> list[str]:
    """Las reglas de §4.4, contra lo que hizo produccion. Cada una puede fallar."""
    errores: list[str] = []
    n = len(captura.llamadas)
    if n == 0:
        return [f"{caso.id}: la tool no llamo al backend"]
    if len(captura.modelos) > 1:
        errores.append(f"{caso.id}: produccion uso varios modelos {sorted(captura.modelos)}")
    if captura.role != caso.role:
        errores.append(
            f"{caso.id}: declarado {caso.role}, pero produccion eligio "
            f"{captura.llamadas[0].model} ({captura.role})"
        )
    if caso.kind == "calidad":
        if n != 1:
            errores.append(f"{caso.id}: no cabe en una llamada, produccion hace {n}")
        elif not captura.entrada_entera:
            errores.append(f"{caso.id}: el modelo no ve la entrada entera (truncada)")
    elif caso.kind == "techo":
        if n == 1:
            errores.append(f"{caso.id}: cabe en una llamada, asi que no sondea ningun techo")
        if unica is None or len(unica.llamadas) != 1 or not unica.entrada_entera:
            errores.append(
                f"{caso.id}: el sondeo no tiene un prompt de una llamada con la entrada entera"
            )
    if caso.media_type == "texto":
        texto = normalizado(datos)
        esperados = terminos(caso, texto)
        if caso.kind == "calidad" and not esperados:
            errores.append(f"{caso.id}: sin terminos esperados no hay nada que puntuar")
        if caso.terminos_en_fuente:
            for termino in esperados:
                if termino.casefold() not in texto.casefold():
                    errores.append(f"{caso.id}: el termino {termino!r} no esta en la fuente")
        errores.extend(_comprobar_tamano_del_id(caso.id, len(texto)))
    if caso.referencia is not None:
        fuente = normalizado(datos) if caso.media_type == "texto" else ""
        conteos = caso.conteos(fuente) if caso.conteos else None
        errores.extend(comprobar_referencia(caso, terminos(caso, fuente), conteos))
    return errores


def _comprobar_tamano_del_id(case_id: str, chars: int) -> list[str]:
    # Un id que promete un tamano que la fuente no tiene es el `techo-resumen-120k` que apuntaba a
    # un fichero de 106 000: se comprueba, no se confia.
    match = re.search(r"-(\d+)(k?)$", case_id)
    if not match:
        return []
    numero = int(match.group(1))
    if match.group(2):
        ok = round(chars / 1000) == numero
    else:
        ok = chars == numero
    return (
        [] if ok else [f"{case_id}: el id promete {match.group(0)[1:]} y la fuente tiene {chars}"]
    )


def entrada_de_corpus(
    caso: Caso, nombre: str, datos: bytes, captura: Captura, unica: Captura | None = None
) -> dict[str, Any]:
    # El prompt: el de produccion en los casos de calidad; en un sondeo de techo, el de la ruta
    # de una llamada. `production` sigue contando las llamadas que produccion hizo de verdad.
    prompt = unica if unica is not None else captura
    llamada = prompt.llamadas[0]
    texto = normalizado(datos) if caso.media_type == "texto" else ""
    calidad = caso.kind == "calidad"
    con_prompt = calidad or unica is not None
    return {
        "id": caso.id,
        "tool": caso.tool,
        "role": caso.role,
        "kind": caso.kind,
        "procedencia": caso.procedencia,
        "origen": caso.origen,
        "media_type": caso.media_type,
        "source_file": nombre,
        "source_sha256": hashlib.sha256(datos).hexdigest(),
        "source_bytes": len(datos),
        "source_chars": len(texto) if texto else None,
        "production": {"model": captura.llamadas[0].model, "calls": len(captura.llamadas)},
        "system": llamada.system if con_prompt else None,
        "user_template": prompt.user_template if con_prompt else None,
        "max_tokens": llamada.max_tokens if con_prompt else None,
        "temperature": llamada.temperature if con_prompt else None,
        "response_format": llamada.response_format if con_prompt else None,
        "reasoning_effort": None,
        "expected_terms": list(terminos(caso, texto)) if calidad else [],
        "forbidden_terms": list(caso.forbidden_terms) if calidad else [],
        "expected_json_fields": list(caso.expected_json_fields) if calidad else [],
        "execution_checks": list(caso.comprobaciones) if calidad else [],
        "expected_counts": caso.conteos(texto) if calidad and caso.conteos else {},
        "automatic_scoring": caso.puntuacion_automatica if calidad else None,
        "expected_format": formato_pedido(llamada.system) if calidad else {},
        **(
            {
                "reference_signal": caso.referencia[0],
                "reference_ok": caso.referencia[1],
                "reference_bad": caso.referencia[2],
            }
            if caso.referencia
            else {}
        ),
    }


# --- Conteos del log ----------------------------------------------------------------------------


def contar_log(log_dir: Path, raiz: Path) -> dict[str, Any]:
    """Conteos agregados de §4.2. Ninguna ruta de fuera del repo sale de aqui, ni siquiera como
    nombre: el log guarda rutas del vault y de otros proyectos del usuario."""
    eventos: list[dict[str, Any]] = []
    for ruta in sorted(log_dir.glob("usage-*.jsonl")):
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            try:
                evento = json.loads(linea)
            except ValueError:
                continue
            if isinstance(evento, dict):
                eventos.append(evento)
    locales = [e for e in eventos if str(e.get("tool", "")).startswith("local_")]
    raiz_norm = os.path.normcase(os.path.abspath(raiz)) + os.sep
    por_tool: dict[str, Any] = {}
    for tool in sorted({e["tool"] for e in locales}):
        del_tool = [e for e in locales if e["tool"] == tool]
        chars = [int(e.get("chars_in") or 0) for e in del_tool]
        mediana = statistics.median(chars)
        por_tool[tool] = {
            "n": len(del_tool),
            "chars_in_mediana": int(mediana) if mediana == int(mediana) else mediana,
            "chars_in_min": min(chars),
            "chars_in_max": max(chars),
            "modelos": dict(Counter(e.get("model") for e in del_tool).most_common()),
        }
    del_repo: Counter[str] = Counter()
    fuera = 0
    for evento in locales:
        ruta = evento.get("path")
        if not ruta:
            continue
        absoluta = os.path.normcase(os.path.abspath(ruta))
        if absoluta.startswith(raiz_norm):
            # normcase solo para comparar: el nombre se guarda con sus mayusculas.
            relativa = os.path.relpath(os.path.abspath(ruta), os.path.abspath(raiz))
            del_repo[relativa.replace("\\", "/")] += 1
        else:
            fuera += 1
    return {
        "eventos": len(eventos),
        "eventos_local": len(locales),
        "descartados_no_local": dict(
            Counter(e.get("tool") for e in eventos if e not in locales).most_common()
        ),
        "por_tool": por_tool,
        "por_modelo": dict(Counter(e.get("model") for e in locales).most_common()),
        "por_source": dict(Counter(e.get("source") for e in locales).most_common()),
        "troceados": sum(1 for e in locales if int(e.get("chunks") or 1) > 1),
        "fuentes_del_repo": dict(del_repo.most_common()),
        "fuentes_fuera_del_repo": fuera,
    }


# --- Construir y comprobar ----------------------------------------------------------------------


def _escribir_json(ruta: Path, datos: Any) -> None:
    ruta.write_bytes((json.dumps(datos, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _fuente_congelada(
    fuentes: Path, nombre: str, generar: Fuente, raiz: Path, refrescar: bool
) -> bytes:
    """La copia congelada si ya existe; el fichero vivo solo si falta o se pide refrescar.

    Congelar sirve para que el corpus no cambie cuando cambia el repo: `CHANGELOG.md` crece en
    cada release y `lint-33k` sale de pasar ruff por `src/`. Regenerar para anadir un campo no
    puede recongelar de paso, o el contenido medido cambia sin que nadie lo decida.
    """
    ruta = fuentes / nombre
    if ruta.is_file() and not refrescar:
        return ruta.read_bytes()
    return generar(raiz)


def construir(
    raiz: Path, destino: Path, log_dir: Path | None, *, refrescar_fuentes: bool = False
) -> int:
    fuentes = destino / "fuentes"
    fuentes.mkdir(parents=True, exist_ok=True)
    errores: list[str] = []
    casos: list[dict[str, Any]] = []
    esperados: set[str] = set()
    for caso in CASOS:
        datos = _fuente_congelada(
            fuentes, f"{caso.id}.{caso.extension}", caso.fuente, raiz, refrescar_fuentes
        )
        nombre = f"{caso.id}.{caso.extension}"
        esperados.add(nombre)
        (fuentes / nombre).write_bytes(datos)
        captura = capturar(caso, fuentes / nombre, datos)
        unica = (
            capturar(caso, fuentes / nombre, datos, sin_troceo=True)
            if caso.kind == "techo"
            else None
        )
        errores.extend(comprobar(caso, captura, datos, unica))
        if captura.llamadas:
            casos.append(entrada_de_corpus(caso, nombre, datos, captura, unica))
    controles = []
    for control in CONTROLES:
        datos = _fuente_congelada(
            fuentes,
            f"{control['id']}.{control['extension']}",
            control["fuente"],
            raiz,
            refrescar_fuentes,
        )
        nombre = f"{control['id']}.{control['extension']}"
        esperados.add(nombre)
        (fuentes / nombre).write_bytes(datos)
        casos_de_control = [c for c in casos if c["id"] in control["para"]]
        if any(c["source_sha256"] == hashlib.sha256(datos).hexdigest() for c in casos_de_control):
            errores.append(f"{control['id']}: la imagen de control es la misma que la del caso")
        controles.append(
            {
                "id": control["id"],
                "para": control["para"],
                "procedencia": control["procedencia"],
                "origen": control["origen"],
                "source_file": nombre,
                "source_sha256": hashlib.sha256(datos).hexdigest(),
                "source_bytes": len(datos),
            }
        )
    for sobrante in fuentes.iterdir():
        if sobrante.name not in esperados:
            sobrante.unlink()
    if errores:
        print("El corpus NO se escribe. Reglas que no se cumplen:")
        for error in errores:
            print(f"  - {error}")
        return 1
    _escribir_json(
        destino / "cases.json",
        {
            "schema_version": 2,
            "production_config": configuracion_de_produccion(),
            "controls": controles,
            "cases": casos,
        },
    )
    if log_dir is not None and log_dir.is_dir():
        _escribir_json(destino / "conteos-log.json", contar_log(log_dir, raiz))
    benchmark.load_corpus(destino / "cases.json")
    calidad = sum(1 for c in casos if c["kind"] == "calidad")
    print(
        f"ok: {calidad} casos de calidad, {len(casos) - calidad} sondeos, {len(controles)} control"
    )
    for caso in casos:
        print(
            f"  {caso['id']:<24} {caso['role']:<10} llamadas={caso['production']['calls']:<3} "
            f"chars={caso['source_chars']} bytes={caso['source_bytes']}"
        )
    return 0


def configuracion_de_produccion() -> dict[str, Any]:
    with produccion_interceptada():
        return {
            "long_input_chars": config.LONG_INPUT_CHARS,
            "chunk_chars": config.CHUNK_CHARS,
            "models": {rol: modelo for modelo, rol in roles_de_produccion().items()},
            "max_chars": {
                rol: config.max_chars_for_role(rol) for rol in roles_de_produccion().values()
            },
        }


_CAMPOS_VIGILADOS = (
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


def comprobar_versionado(destino: Path) -> list[str]:
    """Recaptura cada caso versionado contra el codigo de hoy. Si produccion cambio de rol, de
    troceado o de prompt, el corpus ya no mide lo que dice y hay que regenerarlo."""
    corpus = benchmark.load_corpus(destino / "cases.json")
    por_id = {caso.id: caso for caso in CASOS}
    errores: list[str] = []
    if {c.id for c in corpus.cases} != set(por_id):
        errores.append("los ids versionados no coinciden con los casos del constructor")
    for versionado in corpus.cases:
        caso = por_id.get(versionado.id)
        if caso is None:
            continue
        ruta = destino / "fuentes" / versionado.source_file
        datos = ruta.read_bytes()
        captura = capturar(caso, ruta, datos)
        unica = capturar(caso, ruta, datos, sin_troceo=True) if caso.kind == "techo" else None
        errores.extend(comprobar(caso, captura, datos, unica))
        actual = entrada_de_corpus(caso, versionado.source_file, datos, captura, unica)
        for campo in _CAMPOS_VIGILADOS:
            if actual.get(campo) != versionado.raw.get(campo):
                # Tambien lo que no sale de produccion: el corpus no se edita a mano, y una
                # referencia retocada en el JSON dejaria de ser la que el constructor comprobo.
                errores.append(f"{versionado.id}: {campo} ya no coincide con el constructor")
    if corpus.production_config != configuracion_de_produccion():
        errores.append("production_config ya no coincide con config.py")
    return errores


# --- Corpus de afinidad (REQ-040): la seleccion de commits y las trampas --------------------------

DESTINO_AFINIDAD = RAIZ / "benchmarks" / "afinidad-2026-10"
FECHA_LIMITE = "2026-10-06"  # los commits son ANTERIORES a esta fecha (la del commiter, `%cs`)
COMMIT_DE_F2 = "d7c3dcc"  # `commit-diff-19k`: ya esta en el corpus, no se elige otra vez
N_REALES_NUEVOS = 29  # 30 casos reales en total: `commit-diff-19k` mas estos
N_TRAMPAS = 9  # tres por juego: la hoja 1 y dos repeticiones posibles
# Pasos de la regla, en el orden de la spec: ventana de commits, rango de chars del diff. Si un paso
# no da los 38 commits (29 + 9) se pasa al siguiente: sin limite de ventana y, despues, al rango de
# 1 000 a 30 000 chars.
PASOS_DE_SELECCION: tuple[tuple[int | None, int, int], ...] = (
    (400, 2000, 20000),
    (None, 2000, 20000),
    (None, 1000, 30000),
)
REGLA_DE_SELECCION = (
    "Commits de `main` con fecha anterior a 2026-10-06, de mas reciente a mas antiguo, sin merges, "
    "sin autor Dependabot, sin asunto `chore(deps...)`, sin asunto `chore: release`, "
    "con un diff (`git show --format=`) de 2 000 a 20 000 chars. Los 29 primeros "
    "(sin contar el de `commit-diff-19k`) son los casos reales; los 9 siguientes, las trampas. Si "
    "no salen 38, se amplia la ventana de 400 commits a todo el historial y, despues, el rango a "
    "1 000-30 000 chars."
)
_NO_ES_CANDIDATO = re.compile(r"^(?:chore\(deps|chore: release)")
_PREFIJO_CONVENCIONAL = re.compile(
    r"^(feat|fix|docs|refactor|perf|test|build|ci|chore|style|revert)(\([^)]+\))?!?: "
)
_TRAILER = re.compile(r"^[A-Za-z][A-Za-z-]*: \S")


@dataclass(frozen=True)
class Commit:
    hash: str
    fecha: str
    autor: str
    asunto: str
    chars: int = 0

    @property
    def corto(self) -> str:
        return self.hash[:7]


def _git_texto(raiz: Path, *args: str) -> str:
    return _git(raiz, *args).decode("utf-8", errors="replace")


def _commits_de(
    raiz: Path, ref: str, ventana: int | None, extra: Sequence[str] = ()
) -> list[Commit]:
    formato = "%H%x1f%cs%x1f%an <%ae>%x1f%s"
    limite = [f"-n{ventana}"] if ventana else []
    salida = _git_texto(raiz, "log", ref, "--no-merges", f"--format={formato}", *limite, *extra)
    commits = []
    for linea in salida.splitlines():
        h, fecha, autor, asunto = linea.split("\x1f", 3)
        commits.append(Commit(h, fecha, autor, asunto))
    return commits


def _es_candidato(c: Commit, antes: str) -> bool:
    return (
        c.fecha < antes
        and "dependabot" not in c.autor.lower()
        and _NO_ES_CANDIDATO.match(c.asunto) is None
    )


def _diff_normalizado(raiz: Path, h: str) -> str:
    return normalizado(diff_de_commit(h)(raiz))


@dataclass(frozen=True)
class Seleccion:
    reales: list[Commit]
    trampas: list[Commit]
    paso: int  # indice en PASOS_DE_SELECCION del paso que dio los commits


def seleccionar_commits(
    raiz: Path,
    *,
    ref: str = "main",
    antes: str = FECHA_LIMITE,
    excluir: Sequence[str] = (COMMIT_DE_F2,),
    n_reales: int = N_REALES_NUEVOS,
    n_trampas: int = N_TRAMPAS,
    pasos: Sequence[tuple[int | None, int, int]] = PASOS_DE_SELECCION,
    descartar_si: Callable[[str], bool] | None = None,
) -> Seleccion:
    """La regla escrita de REQ-040, aplicada por codigo. La lista de hashes sale de aqui, nunca a mano.

    `excluir` son prefijos de hash que no se eligen (el caso que ya esta en el corpus de F2).
    `descartar_si` recibe el diff normalizado y, si devuelve `True`, el commit no es candidato (el
    modo `--privacidad excluir`: un diff con datos privados no entra en el repo).
    """
    tamanos: dict[str, int | None] = {}
    ultimo: list[Commit] = []
    for indice, (ventana, minimo, maximo) in enumerate(pasos):
        candidatos: list[Commit] = []
        for c in _commits_de(raiz, ref, ventana):
            if not _es_candidato(c, antes) or any(c.hash.startswith(x) for x in excluir):
                continue
            if c.hash not in tamanos:
                texto = _diff_normalizado(raiz, c.hash)
                privado = descartar_si is not None and descartar_si(texto)
                tamanos[c.hash] = None if privado else len(texto)
            tamano = tamanos[c.hash]
            if tamano is not None and minimo <= tamano <= maximo:
                candidatos.append(Commit(c.hash, c.fecha, c.autor, c.asunto, tamano))
            if len(candidatos) == n_reales + n_trampas:
                break
        ultimo = candidatos
        if len(candidatos) >= n_reales + n_trampas:
            return Seleccion(candidatos[:n_reales], candidatos[n_reales:], indice)
    raise ValueError(
        f"la regla no da {n_reales + n_trampas} commits ni en el ultimo paso ({len(ultimo)})"
    )


def _numstat(raiz: Path, h: str) -> list[tuple[int, str]]:
    """Ficheros del commit por lineas cambiadas (anadidas mas quitadas), de mas a menos."""
    filas = []
    for linea in _git_texto(raiz, "show", "--numstat", "--format=", h).splitlines():
        partes = linea.split("\t", 2)
        if len(partes) == 3 and partes[0].isdigit() and partes[1].isdigit():
            filas.append((int(partes[0]) + int(partes[1]), partes[2]))
    return sorted(filas, key=lambda f: (-f[0], f[1]))


def cuerpo_del_commit(raiz: Path, h: str, maximo: int = 5) -> list[str]:
    """Hasta `maximo` lineas del cuerpo de un commit, sin firmas ni enlaces de sesion."""
    lineas = []
    for linea in _git_texto(raiz, "log", "-1", "--format=%b", h).splitlines():
        if not linea.strip() or _TRAILER.match(linea) or "claude.ai/code/session" in linea:
            continue
        # Un squash repite el asunto como primera linea del cuerpo («* feat: ...»).
        if _PREFIJO_CONVENCIONAL.match(linea.lstrip("* ").strip()):
            continue
        lineas.append(linea.rstrip())
    return lineas[:maximo]


def asunto_misma_zona(
    raiz: Path,
    caso: Commit,
    fuera: set[str],
    *,
    ref: str = "main",
    antes: str = FECHA_LIMITE,
    maximo_asunto: int = 72,
) -> dict[str, Any] | None:
    """El asunto REAL de otro commit, fuera de los 30 y de los 9, que toca el fichero mas cambiado.

    Elegido por codigo entre los asuntos de 72 caracteres como mucho y con prefijo convencional
    (tiene que tener buen formato: la trampa es infiel, no malformada). Si ese fichero no da
    ninguno, se pasa al siguiente fichero mas cambiado. El mas reciente gana.
    """
    for _lineas, fichero in _numstat(raiz, caso.hash):
        for c in _commits_de(raiz, ref, None, ("--", fichero)):
            # Sin el « (#123)» que GitHub anade al hacer squash: un mensaje que devuelve la tool no
            # lo lleva, y seria la marca que delata la trampa.
            asunto = re.sub(r"\s*\(#\d+\)$", "", c.asunto)
            if (
                c.hash in fuera
                or c.hash == caso.hash
                or not _es_candidato(c, antes)
                or len(asunto) > maximo_asunto
                or _PREFIJO_CONVENCIONAL.match(asunto) is None
            ):
                continue
            return {
                "hash": c.hash,
                "fichero": fichero,
                "asunto": asunto,
                "cuerpo_real": cuerpo_del_commit(raiz, c.hash),
            }
    return None


# --- Datos privados: nada de eso va al repo ---------------------------------------------------------

_PATRONES_PRIVADOS = {
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
_IP_PERMITIDA = re.compile(
    r"^(?:127\.\d+\.\d+\.\d+|0\.0\.0\.0|255\.255\.255\.\d+|192\.0\.2\.\d+|198\.51\.100\.\d+|203\.0\.113\.\d+)$"
)
_CORREO_PERMITIDO = re.compile(
    r"@(?:example\.(?:org|com|net)|users\.noreply\.github\.com)$|^noreply@"
)


def datos_privados(texto: str) -> list[str]:
    """Lo que parece un dato privado en un texto que va al repo: `tipo: coincidencia`."""
    hallazgos: list[str] = []
    for tipo, patron in _PATRONES_PRIVADOS.items():
        for m in patron.finditer(texto):
            valor = m.group(0)
            if tipo == "ip" and (
                _IP_PERMITIDA.match(valor) or max(map(int, valor.split("."))) > 255
            ):
                continue
            if tipo == "correo" and _CORREO_PERMITIDO.search(valor):
                continue
            hallazgos.append(f"{tipo}: {valor}")
    return sorted(set(hallazgos))


# --- Corpus de afinidad: las tools mecanicas (REQ-040) ------------------------------------------------
#
# Casos DISTINTOS en vez de repeticiones: a temperatura 0 repetir da la misma respuesta. Cada caso
# comprueba algo objetivo que un modelo puede fallar, con su `reference_ok` (puntua 1) y su
# `reference_bad` (puntua menos de 1) escritos antes de medir. Los textos son inventados para el
# caso: ninguno sale de un log ni de un fichero del usuario. Los puntuadores viven en
# `analizar_benchmark.py` (no importa el paquete) y se cargan por ruta.


def analizador() -> Any:
    """`analizar_benchmark.py` cargado por ruta: de el salen los puntuadores y el veredicto."""
    modulo = sys.modules.get("analizar_benchmark")
    if modulo is not None and hasattr(modulo, "puntuar_afinidad"):
        return modulo
    spec = importlib.util.spec_from_file_location(
        "analizar_benchmark", RAIZ / "scripts" / "analizar_benchmark.py"
    )
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["analizar_benchmark"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@dataclass(frozen=True)
class CasoMecanico:
    id: str
    tool: str
    origen: str
    texto: str
    extension: str
    puntuador: dict[str, Any]
    reference_ok: str
    reference_bad: str
    argumentos: dict[str, Any] = field(default_factory=dict)
    campos: tuple[str, ...] = ()  # `local_extract`: las claves que se piden
    procedencia: str = "inventado"


def _clasifica(id_: str, texto: str, etiquetas: list[str], aceptables: list[str], mala: str):
    return CasoMecanico(
        id_,
        "local_classify",
        "texto escrito para el caso",
        texto,
        "txt",
        {"tipo": "classify", "etiquetas": etiquetas, "aceptables": aceptables},
        aceptables[0],
        mala,
        argumentos={"labels": etiquetas},
    )


def _extrae(id_: str, texto: str, esperado: dict[str, Any], mala: dict[str, Any], ext: str = "txt"):
    claves = tuple(esperado)
    return CasoMecanico(
        id_,
        "local_extract",
        "texto escrito para el caso",
        texto,
        ext,
        {"tipo": "extract", "claves": list(claves), "esperado": esperado},
        json.dumps(esperado, ensure_ascii=False),
        json.dumps(mala, ensure_ascii=False),
        campos=claves,
    )


def _traduce(id_: str, texto: str, buena: str, mala: str):
    # `_chat_chunked` recorta el fin de linea final: el modelo ve el texto sin el.
    texto = texto.rstrip("\n")
    est = analizador().estructura_markdown(texto)
    return CasoMecanico(
        id_,
        "local_translate",
        "Markdown escrito para el caso, en ingles; se traduce al español",
        texto,
        "md",
        {
            "tipo": "translate",
            "titulos": est["titulos"],
            "listas": est["listas"],
            "bloques": est["bloques"],
            "codigo": est["codigo"],
        },
        buena,
        mala,
        argumentos={"target_lang": "español"},
    )


def _salida_de_linter(avisos: list[tuple[str, int, int, str, str]]) -> str:
    return "\n".join(f"{f}:{ln}:{col}: {c} {m}" for f, ln, col, c, m in avisos) + "\n"


def _conteos_del_linter(avisos: list[tuple[str, int, int, str, str]]) -> dict[str, list[int]]:
    """Por regla, los numeros que valen: el total y los archivos que la tienen (y lo que suma en
    cada uno), como en `check_counts` de F2."""
    por_regla: dict[str, dict[str, int]] = {}
    for fichero, _ln, _col, codigo, _msg in avisos:
        por_regla.setdefault(codigo, {}).setdefault(fichero, 0)
        por_regla[codigo][fichero] += 1
    return {
        codigo: sorted({sum(ficheros.values()), len(ficheros), *ficheros.values()})
        for codigo, ficheros in por_regla.items()
    }


def _resume_linter(id_: str, avisos, buena: str, mala: str):
    return CasoMecanico(
        id_,
        "local_lint_summary",
        "salida de ruff escrita para el caso (sin rutas reales)",
        _salida_de_linter(avisos),
        "txt",
        {"tipo": "lint", "conteos": _conteos_del_linter(avisos), "max_words": 200},
        buena,
        mala,
        procedencia="generado",
    )


def _delega(id_: str, tarea: str, entrada: str, formato: str, esperado: str, regex: str, mala: str):
    return CasoMecanico(
        id_,
        "local_delegate",
        "texto escrito para el caso",
        entrada,
        "txt",
        {"tipo": "delegate", "esperado": esperado, "formato": regex},
        esperado,
        mala,
        argumentos={"task": tarea, "output_format": formato},
    )


_VALLA = "```"


def _md(*bloques: str) -> str:
    return "\n".join(bloques) + "\n"


_TRADUCCION_1_EN = _md(
    "# Quick start",
    "",
    "Install the package and run the check:",
    "",
    "- Install it with pip.",
    "- Run the check command.",
    "- Read the report.",
    "",
    _VALLA + "bash",
    "pip install demo-tool  # installs the CLI",
    "demo-tool check --strict",
    _VALLA,
    "",
    "## Configuration",
    "",
    "Set the timeout in seconds:",
    "",
    _VALLA + "toml",
    "[demo]",
    "timeout = 30  # seconds",
    _VALLA,
)
_TRADUCCION_1_ES = _md(
    "# Inicio rápido",
    "",
    "Instala el paquete y ejecuta la comprobación:",
    "",
    "- Instálalo con pip.",
    "- Ejecuta el comando de comprobación.",
    "- Lee el informe.",
    "",
    _VALLA + "bash",
    "pip install demo-tool  # installs the CLI",
    "demo-tool check --strict",
    _VALLA,
    "",
    "## Configuración",
    "",
    "Define el tiempo de espera en segundos:",
    "",
    _VALLA + "toml",
    "[demo]",
    "timeout = 30  # seconds",
    _VALLA,
)
_TRADUCCION_2_EN = _md(
    "# Troubleshooting",
    "",
    "If the service does not start, follow these steps in order:",
    "",
    "1. Check that the port is free.",
    "2. Delete the stale lock file.",
    "3. Start the service again.",
    "",
    _VALLA + "python",
    "def is_free(port):",
    '    """Return True when nothing listens on the port."""',
    "    # try to bind and close at once",
    "    return True",
    _VALLA,
    "",
    "### Still failing?",
    "",
    "Open an issue and attach the log.",
)
_TRADUCCION_2_ES = _md(
    "# Solución de problemas",
    "",
    "Si el servicio no arranca, sigue estos pasos en orden:",
    "",
    "1. Comprueba que el puerto está libre.",
    "2. Borra el archivo de bloqueo obsoleto.",
    "3. Arranca el servicio otra vez.",
    "",
    _VALLA + "python",
    "def is_free(port):",
    '    """Return True when nothing listens on the port."""',
    "    # try to bind and close at once",
    "    return True",
    _VALLA,
    "",
    "### ¿Sigue fallando?",
    "",
    "Abre una incidencia y adjunta el registro.",
)
_TRADUCCION_3_EN = _md(
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
    _VALLA,
    "$ demo run --dry-run",
    "# nothing was written",
    _VALLA,
)
_TRADUCCION_3_ES = _md(
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
    _VALLA,
    "$ demo run --dry-run",
    "# nothing was written",
    _VALLA,
)
_TRADUCCION_4_EN = _md(
    "# Release checklist",
    "",
    "Before tagging a release:",
    "",
    "- Update the version:",
    "  - in `pyproject.toml`",
    "  - in the changelog",
    "- Run the full test suite.",
    "",
    _VALLA + "python",
    "# bump the version everywhere",
    "VERSION = '1.2.0'",
    _VALLA,
    "",
    "Then push the tag.",
)
_TRADUCCION_4_ES = _md(
    "# Lista de comprobación de la versión",
    "",
    "Antes de etiquetar una versión:",
    "",
    "- Actualiza la versión:",
    "  - en `pyproject.toml`",
    "  - en el registro de cambios",
    "- Ejecuta toda la batería de pruebas.",
    "",
    _VALLA + "python",
    "# bump the version everywhere",
    "VERSION = '1.2.0'",
    _VALLA,
    "",
    "Después, sube la etiqueta.",
)

_AVISOS_1 = [
    ("app/main.py", 12, 101, "E501", "Line too long"),
    ("app/main.py", 40, 105, "E501", "Line too long"),
    ("app/main.py", 7, 8, "F401", "`os` imported but unused"),
    ("app/util.py", 3, 8, "F401", "`sys` imported but unused"),
    ("app/util.py", 9, 8, "F401", "`re` imported but unused"),
    ("app/util.py", 55, 120, "E501", "Line too long"),
    ("app/util.py", 70, 5, "W291", "Trailing whitespace"),
    ("app/cli.py", 21, 110, "E501", "Line too long"),
]
_AVISOS_2 = [
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
_AVISOS_3 = (
    [("tools/gen.py", n, 1, "E402", "Module level import not at top of file") for n in (4, 5, 6, 7)]
    + [("tools/gen.py", n, 90 + n, "E501", "Line too long") for n in (20, 31, 32)]
    + [("tools/gen.py", 50, 5, "E711", "Comparison to `None` should be `cond is None`")]
)
_AVISOS_4 = (
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


CASOS_MECANICOS: tuple[CasoMecanico, ...] = (
    # --- local_classify: 8 casos, >= 4 etiquetas, el conjunto aceptable declarado antes de medir ---
    _clasifica(
        "clasifica-bug-con-etiquetas-en-ingles",
        "Al pulsar «Guardar», la aplicación se cierra sin mostrar ningún mensaje.",
        ["bug", "feature", "docs", "question"],
        ["bug"],
        "feature",
    ),
    _clasifica(
        "clasifica-peticion-de-funcion",
        "Estaría bien que el panel permitiera exportar los datos a CSV.",
        ["bug", "feature", "docs", "question"],
        ["feature"],
        "bug",
    ),
    _clasifica(
        "clasifica-idioma-aleman",
        "Das Wetter ist heute wirklich schön, wir gehen spazieren.",
        ["inglés", "alemán", "francés", "español"],
        ["alemán"],
        "inglés",
    ),
    _clasifica(
        "clasifica-ironia",
        "Qué maravilla: tres semanas esperando y el paquete llegó aplastado.",
        ["positivo", "negativo", "neutro", "mixto"],
        ["negativo"],
        "positivo",
    ),
    _clasifica(
        "clasifica-deportes",
        "El equipo local ganó 3-1 con dos goles en el segundo tiempo.",
        ["deportes", "política", "economía", "tecnología"],
        ["deportes"],
        "política",
    ),
    _clasifica(
        "clasifica-economia",
        "La inflación interanual bajó al 3,1 % según el banco central.",
        ["deportes", "política", "economía", "tecnología"],
        ["economía"],
        "tecnología",
    ),
    _clasifica(
        "clasifica-negacion-reenvio",
        "No quiero que me devuelvan el dinero: quiero que me envíen la pieza que falta.",
        ["reembolso", "reenvío", "cancelación", "consulta"],
        ["reenvío"],
        "reembolso",
    ),
    _clasifica(
        "clasifica-lenguaje-de-programacion",
        "def suma(a, b):\n    return a + b",
        ["python", "javascript", "rust", "sql"],
        ["python"],
        "javascript",
    ),
    # --- local_extract: 8 casos, JSON estricto con las claves exactas ---
    _extrae(
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
    _extrae(
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
    _extrae(
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
    _extrae(
        "extrae-producto-sin-existencias",
        "Camiseta Azul Marino — talla M — precio 19,99 € — quedan 0 unidades.\n",
        {"nombre": "Camiseta Azul Marino", "talla": "M", "precio": 19.99, "stock": 0},
        {"nombre": "Camiseta Azul Marino", "talla": "M", "precio": 19.99, "stock": None},
    ),
    _extrae(
        "extrae-toml-sin-licencia",
        '[project]\nname = "demo-tool"\nversion = "1.4.2"\nrequires-python = ">=3.11"\n',
        {"name": "demo-tool", "version": "1.4.2", "requires-python": ">=3.11", "license": None},
        {"name": "demo-tool", "version": "1.4.2", "requires-python": ">=3.11"},
        "toml",
    ),
    _extrae(
        "extrae-acta-con-cifras",
        "Asistieron 12 de los 20 socios. La propuesta se aprobó con 9 votos a favor, "
        "2 en contra y 1 abstención.\n",
        {"asistentes": 12, "socios": 20, "a_favor": 9, "en_contra": 2, "abstenciones": 1},
        {"asistentes": 12, "socios": 20, "a_favor": 9, "en_contra": 1, "abstenciones": 2},
    ),
    _extrae(
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
    _extrae(
        "extrae-reunion-sin-organizador",
        "Reunión de seguimiento el 5 de abril a las 16:30 en la sala B.\n",
        {"fecha": "5 de abril", "hora": "16:30", "lugar": "sala B", "organizador": None},
        {"fecha": "5 de abril", "hora": "16:30", "lugar": "sala B", "organizador": "ninguno"},
    ),
    # --- local_translate: 4 casos Markdown; se conservan titulos, listas, bloques y el codigo ---
    _traduce(
        "traduce-guia-de-inicio",
        _TRADUCCION_1_EN,
        _TRADUCCION_1_ES,
        _TRADUCCION_1_ES.replace("# installs the CLI", "# instala la CLI"),
    ),
    _traduce(
        "traduce-solucion-de-problemas",
        _TRADUCCION_2_EN,
        _TRADUCCION_2_ES,
        _TRADUCCION_2_ES.replace("3. Arranca el servicio otra vez.\n", ""),
    ),
    _traduce(
        "traduce-registro-de-cambios",
        _TRADUCCION_3_EN,
        _TRADUCCION_3_ES,
        _TRADUCCION_3_ES.replace("# nothing was written", "# no se escribió nada"),
    ),
    _traduce(
        "traduce-lista-de-version",
        _TRADUCCION_4_EN,
        _TRADUCCION_4_ES,
        _TRADUCCION_4_ES.replace(
            "# Lista de comprobación de la versión", "Lista de comprobación de la versión"
        ),
    ),
    # --- local_lint_summary (tamano mecanico): los conteos coinciden con la fuente ---
    _resume_linter(
        "resume-ruff-tres-reglas",
        _AVISOS_1,
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
        _AVISOS_2,
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
        _AVISOS_3,
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
        _AVISOS_4,
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
    _delega(
        "delega-contar-palabras",
        "Cuenta cuántas palabras tiene el texto",
        "El rápido zorro marrón salta sobre el perro perezoso",
        "Solo un número entero, sin texto adicional",
        "9",
        r"\d+",
        "El texto tiene 9 palabras.",
    ),
    _delega(
        "delega-lista-a-csv",
        "Convierte la lista en una sola línea CSV",
        "manzana\npera\nuva\nkiwi",
        "Una sola línea con los valores separados por comas, sin espacios",
        "manzana,pera,uva,kiwi",
        r"[^,\s]+(?:,[^,\s]+)*",
        "manzana, pera, uva, kiwi",
    ),
    _delega(
        "delega-fecha-iso",
        "Convierte la fecha a formato ISO 8601",
        "14 de marzo de 2026",
        "Solo la fecha con el formato AAAA-MM-DD",
        "2026-03-14",
        r"\d{4}-\d{2}-\d{2}",
        "14-03-2026",
    ),
    _delega(
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
REGRESION_DE_F2 = (
    "resumen-md-2k",
    "extraer-toml-2k",
    "clasificar-53",
    "traducir-42",
    "delegar-56",
)
CASO_REAL_DE_F2 = "commit-diff-19k"
CASO_TECHO_DE_F2 = "techo-commit-156k"
TIPOS_DE_TRAMPA = ("misma-zona", "secundario", "generico")
JUEGOS = 3

REGLAS_DE_TRAMPA = {
    "regla_de_forma": (
        "Si el mensaje del modelo emparejado tiene cuerpo, la trampa lleva el asunto mas tantas "
        "lineas de su cuerpo como lineas de cuerpo tenga ese mensaje (como mucho 5); si no lo tiene, "
        "solo el asunto. La aplica `hoja_pares.py generar-commit` al armar el par. Idioma: español, "
        "el de la tool (su prompt esta en español) y el del historial del repo."
    ),
    "misma-zona": (
        "El asunto REAL de otro commit, fuera de los 30 y de los 9, que toca el fichero mas cambiado "
        "del caso trampa; elegido por codigo entre los asuntos de 72 caracteres como mucho y con "
        "prefijo convencional (el mas reciente); si ese fichero no da ninguno, el siguiente fichero "
        "mas cambiado. Cuerpo: el cuerpo real de ese commit (hasta 5 lineas, sin firmas ni enlaces); "
        "si tiene menos de 5, se completa con lineas redactadas sobre lo secundario del diff."
    ),
    "secundario": (
        "Redactado a mano: un mensaje con buen formato que solo nombra un cambio SECUNDARIO del diff "
        "(aqui, el registro de un gate de una traza SDD, la entrada del CHANGELOG de una subida de "
        "version o una explicacion lateral de un documento, que acompañan al cambio principal pero "
        "no lo son). Cada linea del cuerpo se comprueba "
        "contra el diff: no dice nada falso, solo deja fuera lo principal."
    ),
    "generico": (
        "Redactado a mano: un mensaje con buen formato (prefijo convencional, asunto corto) que no "
        "dice nada concreto del diff. El cuerpo repite vaguedades sin nombrar ficheros ni cambios."
    ),
}

# Por el prefijo de 7 caracteres del commit del CASO TRAMPA (el diff sobre el que se empareja).
TRAMPAS_REDACTADAS: dict[str, dict[str, Any]] = {
    # --- secundario: un mensaje con buen formato que solo nombra un cambio secundario del diff ---
    "4f41311": {
        "asunto": "docs(sdd): registra la aprobación de la conformidad de una traza",
        "cuerpo": [
            "Actualiza el state.json de una traza SDD.",
            "Registra el gate de conformidad como aprobado.",
            "Anota que el CI del PR estaba en verde y que se mergeó.",
            "Pasa la traza de verificando a cierre.",
            "No cambia código.",
        ],
    },
    "b04a5e2": {
        "asunto": "docs: añade la entrada 0.18.1 al CHANGELOG",
        "cuerpo": [
            "Añade la sección 0.18.1 al CHANGELOG.",
            "Actualiza el enlace Unreleased y añade el de la 0.18.1.",
            "Fija la fecha de la entrada en 2026-07-31.",
            "No reescribe entradas anteriores.",
            "No cambia código de la aplicación.",
        ],
    },
    "fa08d64": {
        "asunto": "docs(sdd): precisa por qué subscriptions no aplica",
        "cuerpo": [
            "Reescribe en research.md la explicación del descarte de subscriptions.",
            "Dice que esas notificaciones son sobre recursos y prompts.",
            "Anota que el servidor no expone ningún recurso ni prompt.",
            "Cambia una palabra en la fila de elicitation de la tabla.",
            "No toca código.",
        ],
    },
    # --- generico: buen formato, nada concreto ---
    "3b20fb3": {
        "asunto": "chore: realiza tareas de mantenimiento",
        "cuerpo": [
            "Actualiza varios archivos.",
            "Mejora algunos detalles.",
            "Ajusta el contenido existente.",
            "Pone al día partes del proyecto.",
            "Revisa y corrige cosas menores.",
        ],
    },
    "7d0f4ac": {
        "asunto": "docs: mejora la documentación",
        "cuerpo": [
            "Realiza ajustes en varias partes.",
            "Corrige pequeños detalles.",
            "Actualiza el texto donde hacía falta.",
            "Mantiene todo al día.",
            "Ordena algunos elementos.",
        ],
    },
    "6710a6b": {
        "asunto": "fix: corrige varios problemas",
        "cuerpo": [
            "Corrige varios problemas.",
            "Resuelve algunos errores menores.",
            "Mejora la robustez general.",
            "Actualiza lo necesario.",
            "Revisa los casos pendientes.",
        ],
    },
}
# Lo secundario de cada diff «de la misma zona», dicho sin inventar, por si el commit elegido no tiene
# cuerpo (o lo tiene corto): completa hasta 5 lineas.
RESERVAS_MISMA_ZONA: dict[str, list[str]] = {
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


def armar_trampas(
    raiz: Path, seleccion: Seleccion, *, ref: str = "main", antes: str = FECHA_LIMITE
) -> dict[str, Any]:
    """`trampas.json`: una trampa por caso `trampa`, tres por juego y los tres tipos en cada juego."""
    fuera = {c.hash for c in seleccion.reales + seleccion.trampas}
    juegos: list[dict[str, Any]] = []
    for juego in range(JUEGOS):
        entradas = []
        for posicion in range(len(TIPOS_DE_TRAMPA)):
            k = juego * len(TIPOS_DE_TRAMPA) + posicion
            commit = seleccion.trampas[k]
            tipo = TIPOS_DE_TRAMPA[posicion]
            entrada: dict[str, Any] = {
                "caso": f"commit-trampa-{commit.corto}",
                "commit": commit.hash,
                "tipo": tipo,
            }
            if tipo == "misma-zona":
                real = asunto_misma_zona(raiz, commit, fuera, ref=ref, antes=antes)
                if real is None:
                    raise ValueError(f"{commit.corto}: ningun asunto de la misma zona")
                cuerpo = list(real["cuerpo_real"])
                origen = "real"
                if len(cuerpo) < 5:
                    reserva = RESERVAS_MISMA_ZONA.get(commit.corto)
                    if reserva is None:
                        raise ValueError(f"{commit.corto}: falta el cuerpo de reserva")
                    cuerpo += reserva[: 5 - len(cuerpo)]
                    origen = "real+redactado" if real["cuerpo_real"] else "redactado"
                entrada.update(
                    asunto=real["asunto"],
                    cuerpo=cuerpo,
                    cuerpo_origen=origen,
                    asunto_de={"hash": real["hash"], "fichero": real["fichero"]},
                )
            else:
                texto = TRAMPAS_REDACTADAS.get(commit.corto)
                if texto is None:
                    raise ValueError(f"{commit.corto}: falta la trampa redactada ({tipo})")
                entrada.update(
                    asunto=texto["asunto"], cuerpo=list(texto["cuerpo"]), cuerpo_origen="redactado"
                )
            if len(entrada["asunto"]) > 72:
                raise ValueError(f"{commit.corto}: el asunto de la trampa pasa de 72 caracteres")
            entradas.append(entrada)
        juegos.append({"juego": juego + 1, "trampas": entradas})
    return {"schema_version": 1, **REGLAS_DE_TRAMPA, "juegos": juegos}


# --- Construccion --------------------------------------------------------------------------------


def comprobar_afinidad(caso: Caso, captura: Captura) -> list[str]:
    """Las reglas de §4.4 que valen para un caso nuevo, contra lo que hizo produccion."""
    n = len(captura.llamadas)
    if n == 0:
        return [f"{caso.id}: la tool no llamo al backend"]
    errores = []
    if len(captura.modelos) > 1:
        errores.append(f"{caso.id}: produccion uso varios modelos {sorted(captura.modelos)}")
    if captura.role != caso.role:
        errores.append(f"{caso.id}: declarado {caso.role}, pero produccion eligio {captura.role}")
    if n != 1:
        errores.append(f"{caso.id}: no cabe en una llamada, produccion hace {n}")
    elif not captura.entrada_entera:
        errores.append(f"{caso.id}: el modelo no ve la entrada entera (truncada)")
    return errores


def _caso_de_corpus(c: CasoMecanico) -> Caso:
    return Caso(
        c.id,
        c.tool,
        "mechanical",
        "calidad",
        c.procedencia,
        c.origen,
        texto_literal(c.texto),
        extension=c.extension,
        argumentos=c.argumentos,
        expected_json_fields=c.campos,
    )


def _limpiar_puntuacion_de_f2(entrada: dict[str, Any]) -> None:
    """Los casos nuevos no se puntuan con los campos de F2 (terminos, campos, conteos): su puntuador
    es `puntuador`, que el veredicto aplica sobre la respuesta guardada."""
    for campo in ("expected_terms", "forbidden_terms", "expected_json_fields", "execution_checks"):
        entrada[campo] = []
    entrada["expected_counts"] = {}
    entrada["automatic_scoring"] = False


def _entrada_afinidad(
    caso: Caso, nombre: str, datos: bytes, captura: Captura, unica: Captura | None, **extra: Any
) -> dict[str, Any]:
    entrada = entrada_de_corpus(caso, nombre, datos, captura, unica)
    entrada.update(extra)
    return entrada


def _escribir_json_lf(ruta: Path, datos: Any) -> None:
    ruta.write_bytes((json.dumps(datos, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def construir_afinidad(
    raiz: Path, destino: Path, *, privacidad: str = "fallar", escribir: bool = True
) -> tuple[int, dict[str, Any]]:
    """Construye `benchmarks/afinidad-2026-10/`: `cases.json`, `trampas.json` y `fuentes/`.

    `privacidad`: `fallar` (por defecto) para si algun texto lleva datos privados; `excluir` saca de
    la seleccion los commits cuyo diff los lleva y sigue con el siguiente candidato de la misma
    regla. Devuelve `(codigo, informe)`; con `escribir=False` no toca el disco.
    """
    descartar = (lambda t: bool(datos_privados(t))) if privacidad == "excluir" else None
    seleccion = seleccionar_commits(raiz, descartar_si=descartar)
    por_id_f2 = {c.id: c for c in CASOS}
    f2_fuentes = DESTINO / "fuentes"
    errores: list[str] = []
    entradas: list[dict[str, Any]] = []
    fuentes: dict[str, bytes] = {}
    puntuar = analizador().puntuar_afinidad
    # Las tools leen la fuente de un fichero: se captura sobre una copia temporal, no sobre el destino.
    temporal = tempfile.TemporaryDirectory()

    def capturar_y_comprobar(caso: Caso, datos: bytes, nombre: str, *, techo: bool = False):
        fuentes[nombre] = datos
        ruta = Path(temporal.name) / nombre
        ruta.write_bytes(datos)
        captura = capturar(caso, ruta, datos)
        unica = capturar(caso, ruta, datos, sin_troceo=True) if techo else None
        return captura, unica

    # 1. Las cinco tools mecanicas: casos nuevos, con su puntuador y sus referencias.
    for c in CASOS_MECANICOS:
        caso = _caso_de_corpus(c)
        nombre = f"{c.id}.{c.extension}"
        datos = c.texto.encode("utf-8")
        captura, _ = capturar_y_comprobar(caso, datos, nombre)
        errores.extend(comprobar_afinidad(caso, captura))
        spec = {"id": c.id, "puntuador": c.puntuador}
        ok, malo = puntuar(spec, c.reference_ok), puntuar(spec, c.reference_bad)
        if ok["calidad"] != 1.0 or not ok["formato"] or malo["calidad"] >= 1.0:
            errores.append(f"{c.id}: las referencias no separan (ok={ok}, bad={malo})")
        if not captura.llamadas:
            continue
        entrada = _entrada_afinidad(
            caso,
            nombre,
            datos,
            captura,
            None,
            discriminante=True,
            rol_en_hoja=None,
            puntuador=c.puntuador,
            reference_ok=c.reference_ok,
            reference_bad=c.reference_bad,
        )
        _limpiar_puntuacion_de_f2(entrada)
        limite = entrada["expected_format"].get("max_words")
        if c.puntuador["tipo"] == "lint" and limite != c.puntuador["max_words"]:
            errores.append(
                f"{c.id}: el prompt pide {limite} palabras y el puntuador {c.puntuador['max_words']}"
            )
        entradas.append(entrada)

    # 2. Los commits: `commit-diff-19k` de F2, los 29 de la regla y los 9 trampa.
    def entrada_de_commit(caso: Caso, nombre: str, datos: bytes, rol: str, asunto: str, **extra):
        captura, _ = capturar_y_comprobar(caso, datos, nombre)
        errores.extend(comprobar_afinidad(caso, captura))
        entrada = _entrada_afinidad(
            caso,
            nombre,
            datos,
            captura,
            None,
            discriminante=rol == "real",
            rol_en_hoja=rol,
            puntuador={"tipo": "hoja"},
            reference_ok=asunto,
            reference_bad="chore: actualiza archivos del proyecto",
            **extra,
        )
        _limpiar_puntuacion_de_f2(entrada)
        return entrada

    caso19 = por_id_f2[CASO_REAL_DE_F2]
    datos19 = _fuente_congelada(
        f2_fuentes, f"{caso19.id}.{caso19.extension}", caso19.fuente, raiz, False
    )
    asunto19 = _git_texto(raiz, "log", "-1", "--format=%s", COMMIT_DE_F2).strip()
    entradas.append(
        entrada_de_commit(
            caso19,
            f"{caso19.id}.{caso19.extension}",
            datos19,
            "real",
            asunto19,
            commit=COMMIT_DE_F2,
        )
    )
    for rol, commits in (("real", seleccion.reales), ("trampa", seleccion.trampas)):
        for c in commits:
            id_ = f"commit-{c.corto}" if rol == "real" else f"commit-trampa-{c.corto}"
            caso = Caso(
                id_,
                "local_commit_msg",
                "code",
                "calidad",
                "congelado",
                f"git show {c.corto} (main, {c.fecha})",
                diff_de_commit(c.hash),
                extension="diff",
            )
            datos = caso.fuente(raiz)
            entradas.append(
                entrada_de_commit(caso, f"{id_}.diff", datos, rol, c.asunto, commit=c.hash)
            )

    # 3. El techo y los cinco casos mecanicos de F2, como regresion (no discriminantes).
    for id_ in (CASO_TECHO_DE_F2, *REGRESION_DE_F2):
        caso = por_id_f2[id_]
        nombre = f"{caso.id}.{caso.extension}"
        datos = _fuente_congelada(f2_fuentes, nombre, caso.fuente, raiz, False)
        captura, unica = capturar_y_comprobar(caso, datos, nombre, techo=caso.kind == "techo")
        errores.extend(comprobar(caso, captura, datos, unica))
        tipo = "techo" if caso.kind == "techo" else "f2"
        entradas.append(
            _entrada_afinidad(
                caso,
                nombre,
                datos,
                captura,
                unica,
                discriminante=False,
                rol_en_hoja=None,
                puntuador={"tipo": tipo},
            )
        )

    ids = [e["id"] for e in entradas]
    if len(ids) != len(set(ids)):
        errores.append("hay ids repetidos en el corpus")
    reales = {e["commit"] for e in entradas if e.get("rol_en_hoja") == "real"}
    trampas_c = {e["commit"] for e in entradas if e.get("rol_en_hoja") == "trampa"}
    if reales & trampas_c:
        errores.append("un commit es a la vez caso real y caso trampa")
    diffs_reales = {e["source_sha256"] for e in entradas if e.get("rol_en_hoja") == "real"}
    if any(
        e["source_sha256"] in diffs_reales for e in entradas if e.get("rol_en_hoja") == "trampa"
    ):
        errores.append("un caso trampa tiene el mismo diff que un caso real")

    # El dato privado de un diff se ve antes de armar las trampas: en el modo `fallar` es el motivo.
    privados_antes = [
        f"dato privado en fuentes/{nombre}: {hallazgo}"
        for nombre, datos in sorted(fuentes.items())
        for hallazgo in datos_privados(normalizado(datos))
    ]
    if privados_antes:
        return 1, {
            "casos": len(entradas),
            "por_tool": {},
            "errores": errores + privados_antes,
            "paso": seleccion.paso,
        }
    trampas = armar_trampas(raiz, seleccion)
    corpus = {
        "schema_version": 2,
        "production_config": configuracion_de_produccion(),
        "controls": [],
        "seleccion": {
            "regla": REGLA_DE_SELECCION,
            "ref": "main",
            "fecha_limite": FECHA_LIMITE,
            "paso": seleccion.paso,
            "privacidad": privacidad,
            "caso_de_f2": {"id": CASO_REAL_DE_F2, "commit": COMMIT_DE_F2},
            "reales": [
                {"hash": c.hash, "fecha": c.fecha, "chars": c.chars} for c in seleccion.reales
            ],
            "trampas": [
                {"hash": c.hash, "fecha": c.fecha, "chars": c.chars} for c in seleccion.trampas
            ],
        },
        "cases": entradas,
    }

    # 4. Nada privado en lo que va al repo.
    privados: list[str] = []
    for nombre, datos in sorted(fuentes.items()):
        privados += [f"fuentes/{nombre}: {h}" for h in datos_privados(normalizado(datos))]
    for etiqueta, contenido in (("cases.json", corpus), ("trampas.json", trampas)):
        privados += [
            f"{etiqueta}: {h}" for h in datos_privados(json.dumps(contenido, ensure_ascii=False))
        ]
    errores += [f"dato privado en {p}" for p in privados]

    def grupo(e: dict[str, Any]) -> str:
        return e.get("rol_en_hoja") or ("nuevo" if e["discriminante"] else "regresion")

    temporal.cleanup()
    informe = {
        "por_tool": dict(Counter(f"{e['tool']}:{grupo(e)}" for e in entradas)),
        "casos": len(entradas),
        "errores": errores,
        "paso": seleccion.paso,
    }
    if errores:
        return 1, informe
    if escribir:
        (destino / "fuentes").mkdir(parents=True, exist_ok=True)
        for nombre, datos in fuentes.items():
            (destino / "fuentes" / nombre).write_bytes(datos)
        for sobrante in (destino / "fuentes").iterdir():
            if sobrante.name not in fuentes:
                sobrante.unlink()
        # Las fuentes son bytes con su sha256: git no puede tocarles el fin de linea.
        (destino / ".gitattributes").write_bytes(b"fuentes/** -text\n")
        _escribir_json_lf(destino / "cases.json", corpus)
        _escribir_json_lf(destino / "trampas.json", trampas)
        benchmark.load_corpus(destino / "cases.json")
    return 0, informe


def comprobar_afinidad_versionado(destino: Path, raiz: Path = RAIZ) -> list[str]:
    """Reconstruye el corpus en una carpeta temporal y lo compara con lo versionado."""
    privacidad = json.loads((destino / "cases.json").read_text(encoding="utf-8"))["seleccion"][
        "privacidad"
    ]
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp)
        (copia / "fuentes").mkdir()
        codigo, informe = construir_afinidad(raiz, copia, privacidad=privacidad)
        if codigo:
            return list(informe["errores"])
        diferencias = []
        for nombre in ("cases.json", "trampas.json"):
            if (copia / nombre).read_bytes() != (destino / nombre).read_bytes():
                diferencias.append(f"{nombre} ya no coincide con el constructor")
        for fuente in sorted((copia / "fuentes").iterdir()):
            versionada = destino / "fuentes" / fuente.name
            if not versionada.is_file() or versionada.read_bytes() != fuente.read_bytes():
                diferencias.append(f"fuentes/{fuente.name} ya no coincide con el constructor")
    return diferencias


def main_afinidad(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="construir_corpus.py afinidad")
    parser.add_argument("--destino", type=Path, default=DESTINO_AFINIDAD)
    parser.add_argument(
        "--privacidad",
        choices=("fallar", "excluir"),
        default="fallar",
        help="que hacer si un diff lleva datos privados: parar, o pasar al siguiente candidato",
    )
    parser.add_argument("--comprobar", action="store_true", help="reconstruye y compara")
    parser.add_argument("--en-seco", action="store_true", help="no escribe nada, solo informa")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    # El idioma de los prompts de commit sale del entorno (REQ-044): se dice, para que un corpus
    # construido o comprobado sin la variable no pase por el de produccion sin que se note.
    print(f"idioma del mensaje de commit: {config.commit_idioma() or '(el del diff)'}")
    if args.comprobar:
        diferencias = comprobar_afinidad_versionado(args.destino)
        for d in diferencias:
            print(f"  - {d}")
        print("ok" if not diferencias else f"{len(diferencias)} diferencias")
        return 1 if diferencias else 0
    codigo, informe = construir_afinidad(
        RAIZ, args.destino, privacidad=args.privacidad, escribir=not args.en_seco
    )
    for linea in informe["errores"]:
        print(f"  - {linea}")
    print(
        json.dumps(
            {"casos": informe["casos"], "por_tool": informe["por_tool"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    if codigo:
        print("El corpus NO se escribe. Reglas que no se cumplen (arriba).")
    return codigo


def main(argv: list[str] | None = None) -> int:
    argumentos = sys.argv[1:] if argv is None else argv
    if argumentos and argumentos[0] == "afinidad":
        return main_afinidad(argumentos[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--destino", type=Path, default=DESTINO)
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", "")) / "local-delegate",
        help="carpeta con usage-*.jsonl; si no existe, no se regeneran los conteos",
    )
    parser.add_argument("--comprobar", action="store_true", help="solo recaptura lo versionado")
    parser.add_argument(
        "--refrescar-fuentes",
        action="store_true",
        help="vuelve a congelar las fuentes desde los ficheros vivos (cambia el corpus medido)",
    )
    args = parser.parse_args(argv)
    if args.comprobar:
        errores = comprobar_versionado(args.destino)
        for error in errores:
            print(f"  - {error}")
        print("ok" if not errores else f"{len(errores)} diferencias")
        return 1 if errores else 0
    return construir(RAIZ, args.destino, args.log_dir, refrescar_fuentes=args.refrescar_fuentes)


if __name__ == "__main__":
    sys.exit(main())
