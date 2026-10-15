"""Estructura de un documento Markdown para `local_summarize` (SDD `resumen-por-secciones`).

Por qué existe: en el piloto de T5 del SDD `subagente-lector-local`, Claude pidió resúmenes de
450–600 palabras y la tool nombró entre el 0 % y el 27 % de los títulos del documento. El prompt
pedía «prosa clara» y el modelo aplanaba la estructura; Claude, sin saber qué secciones había,
volvía a leer el fichero. Aquí vive todo lo que no le pedimos al modelo porque se puede calcular:

- **detectar** las secciones (títulos ATX y setext, fuera de bloques de código y del front matter);
- **emparejar** la salida del modelo con los títulos esperados y **completar** los que falten, para
  que «no omite ninguna» no dependa de que el modelo obedezca;
- **trocear** un documento largo por esas secciones, sin cortar dentro de una valla de código.

Todo es puro (sin red ni disco): lo prueban `tests/test_structured_summary.py` y lo usa también
`scripts/measure_structured_summary.py`, que mide con estas mismas funciones.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

from . import i18n

# --- Detección -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Heading:
    text: str
    level: int
    start: int  # posición del primer carácter de la línea del título en el texto analizado


@dataclass(frozen=True)
class Structure:
    level: int
    headings: tuple[Heading, ...]

    @property
    def texts(self) -> list[str]:
        return [t.text for t in self.headings]


_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_ATX_CLOSING = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _lines(text: str) -> list[tuple[int, str]]:
    """(posición, línea sin su salto). Acepta `\\n` y `\\r\\n` sin cambiar las posiciones."""
    out: list[tuple[int, str]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        out.append((pos, line.rstrip("\r\n")))
        pos += len(line)
    return out


def _is_paragraph(line: str) -> bool:
    """¿Puede esta línea ser el texto de un título setext?"""
    if not line.strip():
        return False
    if _ATX.match(line) or _SETEXT.match(line) or _FENCE.match(line):
        return False
    if _LIST_ITEM.match(line) or line.lstrip().startswith(("|", ">")):
        return False
    return not line.startswith(("    ", "\t"))  # bloque de código indentado


def markdown_headings(text: str) -> list[Heading]:
    """Todos los títulos del documento, en orden, sin los de dentro de vallas ni front matter."""
    lines = _lines(text)
    headings: list[Heading] = []
    i = 0
    # Front matter YAML: `---` en la primera línea hasta el siguiente `---` o `...`. Si no se
    # cierra, no es front matter y se analiza como texto.
    if lines and lines[0][1].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j][1].strip() in {"---", "..."}:
                i = j + 1
                break
    fence: str | None = None
    previous: tuple[int, str] | None = None  # línea previa candidata a texto de un setext
    while i < len(lines):
        pos, line = lines[i]
        i += 1
        if fence is not None:
            closing = _FENCE.match(line)
            if (
                closing
                and closing.group(1)[0] == fence[0]
                and len(closing.group(1)) >= len(fence)
                and not line.strip().strip(fence[0])
            ):
                fence = None
            continue
        opening = _FENCE.match(line)
        if opening:
            fence = opening.group(1)
            previous = None
            continue
        atx = _ATX.match(line)
        if atx:
            heading_text = _ATX_CLOSING.sub("", atx.group(2) or "").strip()
            if heading_text:
                headings.append(Heading(heading_text, len(atx.group(1)), pos))
            previous = None
            continue
        setext = _SETEXT.match(line)
        if setext and previous is not None:
            level = 1 if setext.group(1)[0] == "=" else 2
            headings.append(Heading(previous[1].strip(), level, previous[0]))
            previous = None
            continue
        # Solo la ÚLTIMA línea de un párrafo puede ser el texto de un setext: una línea en
        # blanco rompe la candidatura, y por eso `---` tras una línea vacía es una regla.
        previous = (pos, line) if _is_paragraph(line) else None
    return headings


def detect(text: str) -> Structure | None:
    """Nivel estructural (el más alto con al menos dos títulos) y sus títulos, o None."""
    headings = markdown_headings(text)
    for level in range(1, 7):
        at_level = tuple(t for t in headings if t.level == level)
        if len(at_level) >= 2:
            return Structure(level, at_level)
    return None


# --- Normalización y emparejamiento --------------------------------------------------------------

_NUMBERING = re.compile(r"^\s*(?:\d+|[ivxlc]+)[.)]\s+", re.IGNORECASE)
_OUTPUT_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_OUTPUT_BOLD = re.compile(r"^\s*(\*\*|__)(.+?)\1\s*:?\s*$")


def normalize_heading(text: str) -> str:
    """La forma comparable de un título: sin tildes, mayúsculas, signos ni numeración inicial."""
    unmarked = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    unnumbered = _NUMBERING.sub("", unmarked.lower())
    return " ".join(re.sub(r"[\W_]+", " ", unnumbered).split())


def _matches(expected: str, candidate: str) -> bool:
    """Igual, o la candidata empieza por el esperado y sigue una palabra nueva."""
    return bool(expected) and (candidate == expected or candidate.startswith(expected + " "))


def heading_lines(output: str) -> list[tuple[int, str]]:
    """(índice de línea, texto normalizado) de cada línea de título de una salida del modelo."""
    found: list[tuple[int, str]] = []
    for index, line in enumerate(output.split("\n")):
        m = _OUTPUT_HEADING.match(line) or _OUTPUT_BOLD.match(line)
        if m:
            found.append((index, normalize_heading(m.group(m.lastindex or 1))))
    return found


@dataclass
class Matching:
    """Resultado de emparejar la salida con los títulos esperados (índices sobre esperados)."""

    pairs: dict[int, int] = field(default_factory=dict)  # esperado -> índice de línea
    missing: list[int] = field(default_factory=list)
    out_of_order: list[int] = field(default_factory=list)
    empty: list[int] = field(default_factory=list)
    # Expected index -> line index of a heading the model wrote in another language (also in
    # `pairs`). Only filled with `positional=True` (B2d-fix).
    translated: dict[int, int] = field(default_factory=dict)


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


_ATX_LEVEL = re.compile(r"^\s{0,3}(#{1,6})\s")


def _pair_translated(output: str, expected: list[str], result: Matching) -> None:
    """Pairs a missing heading with the one the model wrote in its slot in another language.

    The prompt asks for every heading verbatim, but with a response language different from the
    document's the model sometimes translates one ("Introducción" -> "Introduction"). Text
    matching then sees an expected heading missing and an unknown one, and `complete` inserted the
    expected one again: the section came out twice, once summarized and once "(not summarized)"
    (live sample of B2d). The rescue is positional and narrow, so a heading the model invented is
    not taken for a section: between the same two paired neighbours there must be exactly ONE
    missing expected heading and exactly ONE unpaired ATX line, at the level of the paired ones
    (2 when nothing paired), that matches no expected heading. Bold lines never count.
    """
    lines = output.split("\n")
    normalized = [normalize_heading(e) for e in expected]
    level_of: dict[int, int] = {}
    for index, line in enumerate(lines):
        m = _ATX_LEVEL.match(line)
        if m:
            level_of[index] = len(m.group(1))
    paired_levels = {level_of[line] for line in result.pairs.values() if line in level_of}
    levels = paired_levels or {2}
    used = set(result.pairs.values())
    free = [
        (index, text)
        for index, text in heading_lines(output)
        if index not in used
        and level_of.get(index) in levels
        and not any(_matches(n, text) for n in normalized)
    ]
    for k in list(result.missing):
        before = max((line for e, line in result.pairs.items() if e < k), default=-1)
        after = min((line for e, line in result.pairs.items() if e > k), default=len(lines))
        low = max((e for e in result.pairs if e < k), default=-1)
        high = min((e for e in result.pairs if e > k), default=len(expected))
        missing_here = [e for e in result.missing if low < e < high]
        candidates = [index for index, _text in free if before < index < after]
        if missing_here == [k] and len(candidates) == 1:
            result.pairs[k] = result.translated[k] = candidates[0]
            result.missing.remove(k)


def match_headings(
    output: str, expected: list[str], *, min_content: int = 3, positional: bool = False
) -> Matching:
    """Subsecuencia común más larga entre los títulos esperados y las líneas de título.

    Uno a uno y en orden: un título duplicado necesita dos apariciones, y una mención en la prosa
    no cuenta. Un esperado sin pareja que sí aparece en una línea de título libre está **fuera de
    orden** (existe, pero no donde tocaba); si no aparece en ninguna, **falta**. Una sección
    emparejada es **vacía** si tiene menos de `min_content` palabras hasta la siguiente
    línea emparejada: los subtítulos y negritas que el modelo pone dentro cuentan como contenido.

    With `positional=True` (what `complete` uses) a missing heading is also paired with the one
    the model translated in its slot (`_pair_translated`). The measurement script keeps the
    default: it measures text matching, as when its baseline was frozen.
    """
    normalized = [normalize_heading(e) for e in expected]
    candidates = heading_lines(output)
    n, m = len(normalized), len(candidates)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if _matches(normalized[i], candidates[j][1]):
                table[i][j] = table[i + 1][j + 1] + 1
            else:
                table[i][j] = max(table[i + 1][j], table[i][j + 1])
    result = Matching()
    used: set[int] = set()
    i = j = 0
    while i < n and j < m:
        if _matches(normalized[i], candidates[j][1]) and table[i][j] == table[i + 1][j + 1] + 1:
            result.pairs[i] = candidates[j][0]
            used.add(j)
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    unused = [c for k, c in enumerate(candidates) if k not in used]
    for k in range(n):
        if k in result.pairs:
            continue
        if any(_matches(normalized[k], c[1]) for c in unused):
            result.out_of_order.append(k)
        else:
            result.missing.append(k)
    if positional:
        _pair_translated(output, expected, result)
    lines = output.split("\n")
    order = sorted(result.pairs.items(), key=lambda par: par[1])
    for pos, (k, line) in enumerate(order):
        end = order[pos + 1][1] if pos + 1 < len(order) else len(lines)
        body = "\n".join(lines[line + 1 : end])
        if _words(body) < min_content:
            result.empty.append(k)
    return result


# --- Completitud ---------------------------------------------------------------------------------


def not_summarized() -> str:
    """El texto que va bajo el título de una sección que el modelo no resumió, en el idioma vigente."""
    return i18n.t("mcp.sections.not_summarized")


#: Sus dos formas, para quien lee salidas ya escritas en cualquiera de los dos idiomas (REQ-033).
NOT_SUMMARIZED_FORMS = frozenset(
    i18n.t_lang(language, "mcp.sections.not_summarized") for language in i18n.LANGUAGES
)

#: El marcador de aviso (REQ-010, desde la 0.36.0; antes `[local-delegate aviso: `). Lo comparte
#: `server`: valor de máquina que no cambia con el idioma.
WARNING_MARKER = "[local-delegate warning: "


@dataclass
class Completion:
    text: str
    missing: int
    empty: int
    out_of_order: int


def complete(output: str, expected: list[str], *, truncated: bool = False) -> Completion:
    """Inserta en su sitio los títulos que el modelo no puso, y avisa de cuántos quedaron sin resumir.

    Con `truncated` (la salida acabó por `length`), una última línea de título es un título a medias:
    se quita antes de emparejar, y el título entero vuelve a entrar como faltante.
    """
    lines = output.rstrip("\n").split("\n")
    if truncated and lines and heading_lines(lines[-1]):
        lines = lines[:-1]
    text = "\n".join(lines)
    emp = match_headings(text, expected, positional=True)
    # A heading the model translated goes back to the document's wording, so it can be searched
    # in the document; its level (the `#`s) is kept.
    for k, index in emp.translated.items():
        hashes = _ATX_LEVEL.match(lines[index])
        lines[index] = f"{hashes.group(1) if hashes else '##'} {expected[k]}"
    insertions: dict[int, list[str]] = {}
    placeholder = not_summarized()
    for k in emp.missing:
        next_line = min((line for e, line in emp.pairs.items() if e > k), default=len(lines))
        insertions.setdefault(next_line, []).append(f"## {expected[k]}\n{placeholder}\n")
    if insertions:
        new_lines: list[str] = []
        for index in range(len(lines) + 1):
            for block in insertions.get(index, []):
                if new_lines and new_lines[-1].strip():
                    new_lines.append("")
                new_lines.extend(block.rstrip("\n").split("\n"))
                new_lines.append("")
            if index < len(lines):
                new_lines.append(lines[index])
        text = "\n".join(new_lines).rstrip("\n")
    elif emp.translated:
        text = "\n".join(lines)
    left_out = len(emp.missing) + len(emp.empty)
    if left_out:
        key = (
            "mcp.warning.sections_not_summarized_one"
            if left_out == 1
            else "mcp.warning.sections_not_summarized"
        )
        notice = i18n.t(key, n=left_out)
        text += f"\n\n{WARNING_MARKER}{notice}]"
    return Completion(text, len(emp.missing), len(emp.empty), len(emp.out_of_order))


# --- Secciones del resumen (v3: subsecciones, introducción y tamaño) -----------------------------
#
# La etapa 2 de la v2 dio 3/9: con el nivel `##` solo, un documento con subsecciones perdía justo
# esas partes (el modelo repartía el presupuesto a partes iguales y las `###` se quedaban fuera), y
# el texto anterior al primer título —la introducción— no estaba en la lista. Claude releía ambas.


def introduction() -> str:
    """El título de la sección sintética con el texto anterior al primer título.

    It is a heading the MODEL writes, not one of the document's, so it goes in the response
    language (REQ-028) when the catalog has it, and in the product language otherwise. In the
    B2d live sample it went in the product language ("Introducción") while the model was told to
    answer in English: it wrote "Introduction" and the server added "Introducción" again as not
    summarized.
    """
    response = i18n.response_language().value.lower().replace("_", "-").split("-")[0]
    if response in i18n.LANGUAGES:
        return i18n.t_lang(response, "mcp.sections.introduction")
    return i18n.t("mcp.sections.introduction")


#: Sus dos formas, para quien lee salidas o planes ya escritos (REQ-033).
INTRODUCTION_FORMS = frozenset(
    i18n.t_lang(language, "mcp.sections.introduction") for language in i18n.LANGUAGES
)
MIN_INTRO_WORDS = 20


@dataclass(frozen=True)
class Section:
    heading: str
    start: int
    end: int
    subheadings: tuple[str, ...] = ()
    synthetic: bool = False  # la «Introducción»: no es un título del documento

    @property
    def size(self) -> int:
        return self.end - self.start


def _words_outside_headings(text: str) -> int:
    return sum(_words(line) for _pos, line in _lines(text) if not _ATX.match(line))


def sections_for_summary(text: str, structure: Structure) -> list[Section]:
    """Las secciones que se piden al modelo, en orden, con su tramo del texto y sus subsecciones.

    Las subsecciones son los títulos del nivel siguiente al estructural que caen dentro de cada
    sección (fuera de vallas, porque salen de `markdown_headings`). La introducción es el texto
    anterior a la primera sección, si tiene contenido de verdad y no solo un título `#`.
    """
    all_headings = markdown_headings(text)
    top_level = list(structure.headings)
    next_level = [t.text for t in all_headings if t.level == structure.level + 1]
    # Si los subtítulos se repiten (menos de la mitad distintos) son categorías, no temas: el
    # CHANGELOG tiene 103 que son 5 etiquetas (`Added`, `Fixed`…). Listarlas duplicaba el
    # resumen (1124 palabras para un tope de 500) sin decir nada de cada versión.
    are_topics = len(set(next_level)) * 2 >= len(next_level)
    sections_: list[Section] = []
    first = top_level[0].start
    if _words_outside_headings(text[:first]) >= MIN_INTRO_WORDS:
        sections_.append(Section(introduction(), 0, first, synthetic=True))
    for i, heading in enumerate(top_level):
        end = top_level[i + 1].start if i + 1 < len(top_level) else len(text)
        subs = tuple(
            t.text
            for t in all_headings
            if are_topics and t.level == structure.level + 1 and heading.start < t.start < end
        )
        sections_.append(Section(heading.text, heading.start, end, subs))
    return sections_


def allocate_by_size(sizes: list[int], total: int, *, minimum: int) -> list[int]:
    """Reparte `total` en proporción a `sizes`, sin pasar nunca de `total`.

    El mínimo solo se aplica si cabe para todos (`minimum × n ≤ total`); si no, el reparto es
    proporcional puro (y al menos 1 a cada uno).
    """
    if not sizes:
        return []
    size_sum = sum(sizes) or 1
    base = minimum if minimum * len(sizes) <= total else 0
    remainder = total - base * len(sizes)
    return [max(1, base + (remainder * t) // size_sum) for t in sizes]


# --- Troceado por secciones ----------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    text: str
    start: int
    sections: tuple[Section, ...]  # las que EMPIEZAN dentro del trozo
    continues_from: str | None  # si el trozo empieza a mitad de una sección, su título
    words: int = 0

    @property
    def headings(self) -> tuple[str, ...]:
        return tuple(s.heading for s in self.sections)


def _section_at(sections_: list[Section], pos: int) -> str | None:
    """El título de la sección que contiene la posición `pos` (None: antes de la primera)."""
    inside = [s for s in sections_ if s.start <= pos]
    return inside[-1].heading if inside else None


def chunks_by_sections(
    text: str,
    sections_: list[Section],
    budget: int,
    split: Callable[[str, int], list[str]],
    *,
    from_pos: int = 0,
    to_pos: int | None = None,
) -> list[Chunk]:
    """Corta `text[from_pos:to_pos]` SOLO al principio de las secciones y empaqueta secciones enteras
    hasta el presupuesto.

    Cortar por las posiciones ya detectadas —y no por cualquier `#`— es lo que impide partir
    dentro de una valla de código o en un subtítulo. Una sección mayor que el presupuesto se parte
    con `split` (el troceado genérico); sus partes siguientes son continuaciones de esa sección.
    Las palabras se reparten después, con `allocate_words`.
    """
    to_pos = len(text) if to_pos is None else to_pos
    cuts = [s.start for s in sections_ if from_pos < s.start < to_pos]
    bounds = [from_pos, *cuts, to_pos]
    segments: list[tuple[int, str]] = [(a, text[a:b]) for a, b in pairwise(bounds) if b > a]
    starts = {s.start for s in sections_}

    def _chunk(start: int, chunk_text: str) -> Chunk:
        end = start + len(chunk_text)
        inside = tuple(s for s in sections_ if start <= s.start < end)
        continued = None if start in starts else _section_at(sections_, start)
        return Chunk(chunk_text, start, inside, continued)

    chunks: list[Chunk] = []
    current: tuple[int, str] | None = None
    for start, segment_text in segments:
        if len(segment_text) > budget:
            if current is not None:
                chunks.append(_chunk(*current))
                current = None
            pos = start
            for part in split(segment_text, budget):
                chunks.append(_chunk(pos, part))
                pos += len(part)
            continue
        if current is None:
            current = (start, segment_text)
        elif len(current[1]) + len(segment_text) <= budget:
            current = (current[0], current[1] + segment_text)
        else:
            chunks.append(_chunk(*current))
            current = (start, segment_text)
    if current is not None:
        chunks.append(_chunk(*current))
    return chunks


def allocate_words(chunks: list[Chunk], max_words: int, *, minimum: int = 40) -> list[Chunk]:
    """Reparte `max_words` entre trozos en proporción a su tamaño, sin pasar nunca del total."""
    allocation = allocate_by_size([len(t.text) for t in chunks], max_words, minimum=minimum)
    return [
        Chunk(t.text, t.start, t.sections, t.continues_from, words)
        for t, words in zip(chunks, allocation, strict=True)
    ]


def split_chunk(
    chunk: Chunk,
    text: str,
    sections_: list[Section],
    split: Callable[[str, int], list[str]],
) -> list[Chunk]:
    """Parte en dos (aprox.) un trozo que no cupo, con las posiciones del documento entero.

    Es el reintento por desborde en modo por secciones: usar aquí el troceado genérico volvería a
    cortar en los `#` de las vallas de código. Las palabras del trozo se reparten entre las partes.
    """
    budget = max(1, len(chunk.text) // 2)
    parts = chunks_by_sections(
        text,
        sections_,
        budget,
        split,
        from_pos=chunk.start,
        to_pos=chunk.start + len(chunk.text),
    )
    return allocate_words(parts, chunk.words, minimum=20)


# --- Enfoque --------------------------------------------------------------------------------------

FOCUS_MAX = 200
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitize_focus(focus: str | None) -> str | None:
    """Una línea, sin caracteres de control ni comillas angulares, 200 caracteres como mucho.

    `focus` va al prompt de sistema: un texto de varias líneas o con instrucciones ganaría
    autoridad de sistema. Colapsarlo a una línea y delimitarlo lo deja como un dato.
    """
    if focus is None:
        return None
    clean = " ".join(_CONTROL.sub(" ", focus).replace("«", '"').replace("»", '"').split())
    return clean[:FOCUS_MAX].rstrip() or None
