"""Estructura de un documento Markdown para `local_summarize` (SDD `resumen-por-secciones`).

Por qué existe: en el piloto de T5 del SDD `subagente-lector-local`, Claude pidió resúmenes de
450–600 palabras y la tool nombró entre el 0 % y el 27 % de los títulos del documento. El prompt
pedía «prosa clara» y el modelo aplanaba la estructura; Claude, sin saber qué secciones había,
volvía a leer el fichero. Aquí vive todo lo que no le pedimos al modelo porque se puede calcular:

- **detectar** las secciones (títulos ATX y setext, fuera de bloques de código y del front matter);
- **emparejar** la salida del modelo con los títulos esperados y **completar** los que falten, para
  que «no omite ninguna» no dependa de que el modelo obedezca;
- **trocear** un documento largo por esas secciones, sin cortar dentro de una valla de código.

Todo es puro (sin red ni disco): lo prueban `tests/test_resumen_estructurado.py` y lo usa también
`scripts/medir_resumen_estructurado.py`, que mide con estas mismas funciones.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

# --- Detección -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Titulo:
    texto: str
    nivel: int
    inicio: int  # posición del primer carácter de la línea del título en el texto analizado


@dataclass(frozen=True)
class Estructura:
    nivel: int
    titulos: tuple[Titulo, ...]

    @property
    def textos(self) -> list[str]:
        return [t.texto for t in self.titulos]


_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_ATX_CIERRE = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_VALLA = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LISTA = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _lineas(text: str) -> list[tuple[int, str]]:
    """(posición, línea sin su salto). Acepta `\\n` y `\\r\\n` sin cambiar las posiciones."""
    salida: list[tuple[int, str]] = []
    pos = 0
    for linea in text.splitlines(keepends=True):
        salida.append((pos, linea.rstrip("\r\n")))
        pos += len(linea)
    return salida


def _es_parrafo(linea: str) -> bool:
    """¿Puede esta línea ser el texto de un título setext?"""
    if not linea.strip():
        return False
    if _ATX.match(linea) or _SETEXT.match(linea) or _VALLA.match(linea):
        return False
    if _LISTA.match(linea) or linea.lstrip().startswith(("|", ">")):
        return False
    return not linea.startswith(("    ", "\t"))  # bloque de código indentado


def titulos_markdown(text: str) -> list[Titulo]:
    """Todos los títulos del documento, en orden, sin los de dentro de vallas ni front matter."""
    lineas = _lineas(text)
    titulos: list[Titulo] = []
    i = 0
    # Front matter YAML: `---` en la primera línea hasta el siguiente `---` o `...`. Si no se
    # cierra, no es front matter y se analiza como texto.
    if lineas and lineas[0][1].strip() == "---":
        for j in range(1, len(lineas)):
            if lineas[j][1].strip() in {"---", "..."}:
                i = j + 1
                break
    valla: str | None = None
    anterior: tuple[int, str] | None = None  # línea previa candidata a texto de un setext
    while i < len(lineas):
        pos, linea = lineas[i]
        i += 1
        if valla is not None:
            cierre = _VALLA.match(linea)
            if (
                cierre
                and cierre.group(1)[0] == valla[0]
                and len(cierre.group(1)) >= len(valla)
                and not linea.strip().strip(valla[0])
            ):
                valla = None
            continue
        abre = _VALLA.match(linea)
        if abre:
            valla = abre.group(1)
            anterior = None
            continue
        atx = _ATX.match(linea)
        if atx:
            texto = _ATX_CIERRE.sub("", atx.group(2) or "").strip()
            if texto:
                titulos.append(Titulo(texto, len(atx.group(1)), pos))
            anterior = None
            continue
        setext = _SETEXT.match(linea)
        if setext and anterior is not None:
            nivel = 1 if setext.group(1)[0] == "=" else 2
            titulos.append(Titulo(anterior[1].strip(), nivel, anterior[0]))
            anterior = None
            continue
        # Solo la ÚLTIMA línea de un párrafo puede ser el texto de un setext: una línea en
        # blanco rompe la candidatura, y por eso `---` tras una línea vacía es una regla.
        anterior = (pos, linea) if _es_parrafo(linea) else None
    return titulos


def detectar(text: str) -> Estructura | None:
    """Nivel estructural (el más alto con al menos dos títulos) y sus títulos, o None."""
    titulos = titulos_markdown(text)
    for nivel in range(1, 7):
        del_nivel = tuple(t for t in titulos if t.nivel == nivel)
        if len(del_nivel) >= 2:
            return Estructura(nivel, del_nivel)
    return None


# --- Normalización y emparejamiento --------------------------------------------------------------

_NUMERACION = re.compile(r"^\s*(?:\d+|[ivxlc]+)[.)]\s+", re.IGNORECASE)
_TITULO_SALIDA = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_NEGRITA_SALIDA = re.compile(r"^\s*(\*\*|__)(.+?)\1\s*:?\s*$")


def normal_titulo(texto: str) -> str:
    """La forma comparable de un título: sin tildes, mayúsculas, signos ni numeración inicial."""
    sin_marcas = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    sin_numero = _NUMERACION.sub("", sin_marcas.lower())
    return " ".join(re.sub(r"[\W_]+", " ", sin_numero).split())


def _casa(esperado: str, candidata: str) -> bool:
    """Igual, o la candidata empieza por el esperado y sigue una palabra nueva."""
    return bool(esperado) and (candidata == esperado or candidata.startswith(esperado + " "))


def lineas_de_titulo(salida: str) -> list[tuple[int, str]]:
    """(índice de línea, texto normalizado) de cada línea de título de una salida del modelo."""
    encontradas: list[tuple[int, str]] = []
    for indice, linea in enumerate(salida.split("\n")):
        m = _TITULO_SALIDA.match(linea) or _NEGRITA_SALIDA.match(linea)
        if m:
            encontradas.append((indice, normal_titulo(m.group(m.lastindex or 1))))
    return encontradas


@dataclass
class Emparejamiento:
    """Resultado de emparejar la salida con los títulos esperados (índices sobre esperados)."""

    pares: dict[int, int] = field(default_factory=dict)  # esperado -> índice de línea
    faltan: list[int] = field(default_factory=list)
    fuera_de_orden: list[int] = field(default_factory=list)
    vacias: list[int] = field(default_factory=list)


def _palabras(texto: str) -> int:
    return len(re.findall(r"\w+", texto))


def emparejar(salida: str, esperados: list[str], *, minimo_contenido: int = 3) -> Emparejamiento:
    """Subsecuencia común más larga entre los títulos esperados y las líneas de título.

    Uno a uno y en orden: un título duplicado necesita dos apariciones, y una mención en la prosa
    no cuenta. Un esperado sin pareja que sí aparece en una línea de título libre está **fuera de
    orden** (existe, pero no donde tocaba); si no aparece en ninguna, **falta**. Una sección
    emparejada es **vacía** si tiene menos de `minimo_contenido` palabras hasta la siguiente
    línea emparejada: los subtítulos y negritas que el modelo pone dentro cuentan como contenido.
    """
    normales = [normal_titulo(e) for e in esperados]
    candidatas = lineas_de_titulo(salida)
    n, m = len(normales), len(candidatas)
    tabla = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if _casa(normales[i], candidatas[j][1]):
                tabla[i][j] = tabla[i + 1][j + 1] + 1
            else:
                tabla[i][j] = max(tabla[i + 1][j], tabla[i][j + 1])
    resultado = Emparejamiento()
    usadas: set[int] = set()
    i = j = 0
    while i < n and j < m:
        if _casa(normales[i], candidatas[j][1]) and tabla[i][j] == tabla[i + 1][j + 1] + 1:
            resultado.pares[i] = candidatas[j][0]
            usadas.add(j)
            i += 1
            j += 1
        elif tabla[i + 1][j] >= tabla[i][j + 1]:
            i += 1
        else:
            j += 1
    libres = [c for k, c in enumerate(candidatas) if k not in usadas]
    for k in range(n):
        if k in resultado.pares:
            continue
        if any(_casa(normales[k], c[1]) for c in libres):
            resultado.fuera_de_orden.append(k)
        else:
            resultado.faltan.append(k)
    lineas = salida.split("\n")
    orden = sorted(resultado.pares.items(), key=lambda par: par[1])
    for pos, (k, linea) in enumerate(orden):
        fin = orden[pos + 1][1] if pos + 1 < len(orden) else len(lineas)
        cuerpo = "\n".join(lineas[linea + 1 : fin])
        if _palabras(cuerpo) < minimo_contenido:
            resultado.vacias.append(k)
    return resultado


# --- Completitud ---------------------------------------------------------------------------------

SIN_RESUMIR = "(sin resumir)"


@dataclass
class Completado:
    texto: str
    faltan: int
    vacias: int
    fuera_de_orden: int


def completar(salida: str, esperados: list[str], *, cortada: bool = False) -> Completado:
    """Inserta en su sitio los títulos que el modelo no puso, y avisa de cuántos quedaron sin resumir.

    Con `cortada` (la salida acabó por `length`), una última línea de título es un título a medias:
    se quita antes de emparejar, y el título entero vuelve a entrar como faltante.
    """
    lineas = salida.rstrip("\n").split("\n")
    if cortada and lineas and lineas_de_titulo(lineas[-1]):
        lineas = lineas[:-1]
    texto = "\n".join(lineas)
    emp = emparejar(texto, esperados)
    inserciones: dict[int, list[str]] = {}
    for k in emp.faltan:
        siguiente = min((linea for e, linea in emp.pares.items() if e > k), default=len(lineas))
        inserciones.setdefault(siguiente, []).append(f"## {esperados[k]}\n{SIN_RESUMIR}\n")
    if inserciones:
        nuevas: list[str] = []
        for indice in range(len(lineas) + 1):
            for bloque in inserciones.get(indice, []):
                if nuevas and nuevas[-1].strip():
                    nuevas.append("")
                nuevas.extend(bloque.rstrip("\n").split("\n"))
                nuevas.append("")
            if indice < len(lineas):
                nuevas.append(lineas[indice])
        texto = "\n".join(nuevas).rstrip("\n")
    sin_resumir = len(emp.faltan) + len(emp.vacias)
    if sin_resumir:
        texto += (
            f"\n\n[local-delegate aviso: {sin_resumir} secciones sin resumir por el límite de "
            "palabras o del modelo]"
        )
    return Completado(texto, len(emp.faltan), len(emp.vacias), len(emp.fuera_de_orden))


# --- Troceado por secciones ----------------------------------------------------------------------


@dataclass(frozen=True)
class Trozo:
    texto: str
    inicio: int
    titulos: tuple[str, ...]  # títulos del nivel estructural que EMPIEZAN dentro del trozo
    continua_de: str | None  # si el trozo empieza a mitad de una sección, su título
    palabras: int = 0


def _seccion_en(estructura: Estructura, pos: int) -> str | None:
    """El título de la sección que contiene la posición `pos` (None: antes del primer título)."""
    dentro = [t for t in estructura.titulos if t.inicio <= pos]
    return dentro[-1].texto if dentro else None


def trozos_por_secciones(
    text: str,
    estructura: Estructura,
    presupuesto: int,
    partir: Callable[[str, int], list[str]],
    *,
    desde: int = 0,
    hasta: int | None = None,
) -> list[Trozo]:
    """Corta `text[desde:hasta]` SOLO en los títulos del nivel estructural y empaqueta secciones
    enteras hasta el presupuesto.

    Cortar por las posiciones ya detectadas —y no por cualquier `#`— es lo que impide partir
    dentro de una valla de código o en un subtítulo. Una sección mayor que el presupuesto se parte
    con `partir` (el troceado genérico); sus partes siguientes son continuaciones de esa sección.
    Las palabras se reparten después, con `repartir_palabras`.
    """
    hasta = len(text) if hasta is None else hasta
    cortes = [t.inicio for t in estructura.titulos if desde < t.inicio < hasta]
    limites = [desde, *cortes, hasta]
    segmentos: list[tuple[int, str]] = [(a, text[a:b]) for a, b in pairwise(limites) if b > a]
    inicios = {t.inicio: t.texto for t in estructura.titulos}

    def _trozo(inicio: int, texto: str) -> Trozo:
        fin = inicio + len(texto)
        titulos = tuple(t.texto for t in estructura.titulos if inicio <= t.inicio < fin)
        continua = None if inicio in inicios else _seccion_en(estructura, inicio)
        return Trozo(texto, inicio, titulos, continua)

    trozos: list[Trozo] = []
    actual: tuple[int, str] | None = None
    for inicio, texto in segmentos:
        if len(texto) > presupuesto:
            if actual is not None:
                trozos.append(_trozo(*actual))
                actual = None
            pos = inicio
            for parte in partir(texto, presupuesto):
                trozos.append(_trozo(pos, parte))
                pos += len(parte)
            continue
        if actual is None:
            actual = (inicio, texto)
        elif len(actual[1]) + len(texto) <= presupuesto:
            actual = (actual[0], actual[1] + texto)
        else:
            trozos.append(_trozo(*actual))
            actual = (inicio, texto)
    if actual is not None:
        trozos.append(_trozo(*actual))
    return trozos


def repartir_palabras(trozos: list[Trozo], max_words: int, *, minimo: int = 40) -> list[Trozo]:
    """Reparte `max_words` en proporción al tamaño de cada trozo, sin pasar nunca del total.

    El mínimo solo se aplica si cabe para todos (`minimo × trozos ≤ max_words`); si no, el
    reparto es proporcional puro. Así la suma de lo que se pide al modelo nunca supera el tope.
    """
    if not trozos:
        return []
    total = sum(len(t.texto) for t in trozos) or 1
    base = minimo if minimo * len(trozos) <= max_words else 0
    resto = max_words - base * len(trozos)
    salida = []
    for t in trozos:
        palabras = base + (resto * len(t.texto)) // total
        salida.append(Trozo(t.texto, t.inicio, t.titulos, t.continua_de, max(1, palabras)))
    return salida


def partir_trozo(
    trozo: Trozo,
    text: str,
    estructura: Estructura,
    partir: Callable[[str, int], list[str]],
) -> list[Trozo]:
    """Parte en dos (aprox.) un trozo que no cupo, con las posiciones del documento entero.

    Es el reintento por desborde en modo por secciones: usar aquí el troceado genérico volvería a
    cortar en los `#` de las vallas de código. Las palabras del trozo se reparten entre las partes.
    """
    presupuesto = max(1, len(trozo.texto) // 2)
    partes = trozos_por_secciones(
        text,
        estructura,
        presupuesto,
        partir,
        desde=trozo.inicio,
        hasta=trozo.inicio + len(trozo.texto),
    )
    return repartir_palabras(partes, trozo.palabras, minimo=20)


# --- Enfoque --------------------------------------------------------------------------------------

FOCUS_MAX = 200
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanear_focus(focus: str | None) -> str | None:
    """Una línea, sin caracteres de control ni comillas angulares, 200 caracteres como mucho.

    `focus` va al prompt de sistema: un texto de varias líneas o con instrucciones ganaría
    autoridad de sistema. Colapsarlo a una línea y delimitarlo lo deja como un dato.
    """
    if focus is None:
        return None
    limpio = " ".join(_CONTROL.sub(" ", focus).replace("«", '"').replace("»", '"').split())
    return limpio[:FOCUS_MAX].rstrip() or None
