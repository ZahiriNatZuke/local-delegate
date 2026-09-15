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

Uso:

    uv run python scripts/construir_corpus.py              # congela, captura, comprueba, escribe
    uv run python scripts/construir_corpus.py --comprobar  # recaptura contra lo versionado
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib
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
    guardado = {n: os.environ[n] for n in config.VARIABLES_DE_ENTORNO if n in os.environ}

    def run_chat(model, system, user, max_tokens, temperature, *, response_format=None, **_):
        llamadas.append(Llamada(model, system, user, max_tokens, temperature, response_format))
        return server.ChatResult(text="{}", ok=True, finish_reason="stop"), 0, None

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
        config.MODEL_FAST: "fast",
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
        sin_limite = mock.patch.object(config, "max_chars_for", lambda _modelo: 2**31)
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
                rol: config.max_chars_for(modelo) for modelo, rol in roles_de_produccion().items()
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


def main(argv: list[str] | None = None) -> int:
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
