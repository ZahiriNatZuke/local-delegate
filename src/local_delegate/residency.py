"""Residencia y TTL de llama-swap, editados sobre el `config.yaml` sin romperlo (REQ-029 a REQ-033).

`local-delegate llamaswap residency` (ver `cli.py`) muestra quién se queda cargado y cambia la
residencia y los TTL. Este módulo tiene la lógica; el CLI solo la presenta.

**Edición quirúrgica.** El fichero no se reescribe con `yaml.safe_dump`, que perdería comentarios,
comillas, el plegado de los `cmd`, el fin de línea y el BOM. `editar()` localiza cada nodo con las
marcas de `yaml.compose()` y toca solo sus bytes: reemplaza el tramo de un escalar, inserta líneas
con la sangría y el fin de línea de la anterior, o borra el bloque entero de un grupo o la línea de
un miembro. Todo lo demás queda byte a byte. Y se niega, con un mensaje, ante lo que no sabe editar
con garantías: nodos en estilo flujo (`{…}`, `[…]`), anclas, alias, `<<:`, claves duplicadas, el
router `matrix` y las dos sintaxis de grupos a la vez.

**Autocomprobación.** Antes de devolver nada, el resultado se vuelve a leer y tiene que ser
exactamente el original más el cambio pedido, y cumplir lo que exige `load.go` de v255
(`topology.validate_like_load_go`). Si no, `ResidencyError` y no se escribe nada.

**Escritura.** `dated_copy()` deja `<config>.<AAAAMMDD-HHMMSS>.bak` sin pisar ninguna anterior
(sufijo `-1`, `-2`… si ya existe) y `atomic_replace()` escribe un temporal en la misma carpeta y
lo cambia con `os.replace`, para que `-watch-config` nunca lea un fichero a medias. En Windows,
`os.replace` falla con una violación de compartición si alguien tiene el fichero abierto: se
reintenta hasta 5 veces con 200 ms entre intentos y, si sigue fallando, se borra el temporal y el
original queda intacto.

**TTL efectivo.** `load.go`: un `ttl` ausente o `-1` vale `globalTTL`, que por defecto es 0. Así que
**sin `globalTTL` ni `ttl` todos los modelos tienen TTL efectivo 0**: no se descargan nunca por TTL y
cuentan como residentes. `--none` exige entonces `--ttl` para todos.

**Antes y después de escribir (REQ-034, REQ-039).** Las negativas (delegaciones en curso, peticiones
en vuelo, modelos cargados) y la vigía de la recarga no viven aquí: las hace el CLI (`cli.py`) con
`llamaswap_api.py`. Este módulo no sabe nada de HTTP.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import llamaswap_config as lc
from . import topology

try:
    import yaml
except ImportError:  # pragma: no cover - depende del entorno de instalación
    yaml = None  # type: ignore[assignment]

BOM = b"\xef\xbb\xbf"
UNKNOWN = "no se sabe si hay delegaciones en curso"
# Campo de `GET /api/llamaswap/status` (T13) con la ruta de la config que usa el daemon. Lo
# escribe y lo lee `llamaswap_api.Status` (`to_json`/`from_json`), con esta misma constante.
CONFIG_PATH_FIELD = "config_path"
CHANGE_DURING_EDIT = "la config cambió mientras se editaba; vuelve a intentarlo"
DEFAULT_RESERVE_GB = 2.0
RESIDENT_GROUP = "residente"
REPLACE_ATTEMPTS = 5
REPLACE_WAIT_S = 0.2
TTL_ZERO_EXPLANATION = (
    "sin `globalTTL` ni `ttl`, el TTL efectivo es 0 (load.go: un `ttl` ausente o -1 vale "
    "`globalTTL`, que por defecto es 0): esos modelos no se descargan nunca por TTL y cuentan "
    "como residentes"
)


class ResidencyError(Exception):
    """La edición no se puede hacer con garantías. Nunca se escribe nada tras ella."""


# --- Cambios ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SetTTL:
    model: str
    seconds: int


@dataclass(frozen=True)
class RemoveMember:
    group: str
    member: str


@dataclass(frozen=True)
class AddMember:
    group: str
    member: str


@dataclass(frozen=True)
class DeleteGroup:
    group: str


@dataclass(frozen=True)
class CreateGroup:
    group: str
    persistent: bool
    swap: bool
    exclusive: bool
    members: tuple[str, ...]


Change = SetTTL | RemoveMember | AddMember | DeleteGroup | CreateGroup


# --- Lectura y negativas ---------------------------------------------------------------------


def _requires_yaml() -> None:
    if yaml is None:
        raise ResidencyError(lc._EXTRA_INSTALL_MSG)


def _decode(original: bytes) -> tuple[str, bool]:
    bom = original.startswith(BOM)
    try:
        return original[len(BOM) :].decode("utf-8") if bom else original.decode("utf-8"), bom
    except UnicodeDecodeError as e:
        raise ResidencyError(f"la config no es UTF-8: {e}") from e


def _line(mark: Any) -> int:
    return mark.line + 1


def error_yaml(who: str, e: Exception) -> ResidencyError:
    """Solo el problema y la línea. `str(e)` de PyYAML cita el fragmento del fichero, y ese
    fragmento puede ser una clave (una comilla sin cerrar en `apiKeys`, por ejemplo)."""
    problem = getattr(e, "problem", None) or type(e).__name__
    mark = getattr(e, "problem_mark", None)
    where = f" (línea {mark.line + 1})" if mark is not None else ""
    return ResidencyError(f"{who} no se puede leer: {problem}{where}")


def _no_flow_anchors_or_aliases(text: str) -> None:
    try:
        tokens = list(yaml.scan(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as e:
        raise error_yaml("el YAML", e) from None
    for token in tokens:
        if isinstance(token, (yaml.FlowMappingStartToken, yaml.FlowSequenceStartToken)):
            raise ResidencyError(
                f"nodo en estilo flujo (`{{…}}` o `[…]`) en la línea {_line(token.start_mark)}: "
                "no se edita; escríbelo en estilo bloque"
            )
        if isinstance(token, yaml.AnchorToken):
            raise ResidencyError(
                f"ancla `&{token.value}` en la línea {_line(token.start_mark)}: no se edita"
            )
        if isinstance(token, yaml.AliasToken):
            raise ResidencyError(
                f"alias `*{token.value}` en la línea {_line(token.start_mark)}: no se edita"
            )


def _walk(node: Any):
    yield node
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            yield from _walk(key)
            yield from _walk(value)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            yield from _walk(child)


def _no_merges(root: Any) -> None:
    for node in _walk(root):
        if isinstance(node, yaml.MappingNode):
            for key, _value in node.value:
                if key.tag == "tag:yaml.org,2002:merge":
                    raise ResidencyError(
                        f"`<<:` (fusión de mapas) en la línea {_line(key.start_mark)}: no se edita"
                    )


def _no_duplicate_keys(root: Any) -> None:
    for node in _walk(root):
        if isinstance(node, yaml.MappingNode):
            views: dict[tuple[str, str], int] = {}
            for key, _value in node.value:
                if not isinstance(key, yaml.ScalarNode):
                    continue
                if (key.tag, key.value) in views:
                    raise ResidencyError(
                        f"clave duplicada `{key.value}` en las líneas "
                        f"{views[(key.tag, key.value)]} y {_line(key.start_mark)}: llama-swap "
                        "y PyYAML se quedan con la última; arréglalo a mano antes de editar"
                    )
                views[(key.tag, key.value)] = _line(key.start_mark)


def _topology_refusal(data: Mapping[str, Any]) -> None:
    """Las mismas reglas que el lector de topología (forma, dos sintaxis, `matrix`, `load.go`),
    en el mismo orden: una forma inesperada (`routing: 5`) es una negativa, nunca una excepción."""
    read_one = topology.interpret(data, "", 1)
    if not isinstance(read_one, topology.NoTopology):
        return
    if read_one.reason == topology.TWO_SYNTAXES:
        raise ResidencyError(
            "la config usa las dos sintaxis a la vez (`groups`/`matrix` arriba y `routing.router`): "
            "llama-swap no la arrancaría"
        )
    if read_one.reason == topology.MATRIX:
        raise ResidencyError("la config usa el router `matrix`: la residencia por grupos no aplica")
    raise ResidencyError(f"la config no cumple load.go: {read_one.detail or read_one.reason}")


def _analyze(text: str) -> tuple[Any, dict[str, Any]]:
    """Nodo raíz y datos de un YAML que este módulo sabe editar. Si no, `ResidencyError`."""
    _requires_yaml()
    _no_flow_anchors_or_aliases(text)
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise error_yaml("el YAML", e) from None
    if root is None or not isinstance(root, yaml.MappingNode) or not isinstance(data, dict):
        raise ResidencyError("la raíz del YAML no es un mapa")
    _no_merges(root)
    _no_duplicate_keys(root)
    _topology_refusal(data)
    return root, data


# --- Localizar nodos -------------------------------------------------------------------------


def _par(mapping: Any, key: str) -> tuple[Any, Any] | None:
    """El PRIMER par con esa clave (con claves duplicadas, la negativa va antes)."""
    if not isinstance(mapping, yaml.MappingNode):
        return None
    for k, v in mapping.value:
        if isinstance(k, yaml.ScalarNode) and k.value == key:
            return k, v
    return None


def _groups_path(data: Mapping[str, Any]) -> tuple[str, ...]:
    """Dónde están los grupos, con el mismo criterio que `topology` (arriba o en `routing`)."""
    above, in_routing = topology.syntax(data)
    if in_routing and not above:
        return ("routing", "router", "settings", "groups")
    return ("groups",)


def _node_at(root: Any, path: Sequence[str]) -> tuple[Any, Any] | None:
    node, pair = root, None
    for key in path:
        pair = _par(node, key)
        if pair is None:
            return None
        node = pair[1]
    return pair


def _groups_in_data(data: dict[str, Any], create: bool = False) -> dict[str, Any]:
    target: Any = data
    path = _groups_path(data)
    for key in path[:-1]:
        target = target[key]
    if target.get(path[-1]) is None and create:
        target[path[-1]] = {}
    return target.get(path[-1]) or {}


# --- Texto -----------------------------------------------------------------------------------


def _line_start(t: str, i: int) -> int:
    return t.rfind("\n", 0, i) + 1


def _next_line(t: str, i: int) -> int:
    j = t.find("\n", i)
    return len(t) if j < 0 else j + 1


def _eol_before(t: str, pos: int) -> str:
    """Fin de línea de la línea que acaba justo antes de `pos` (o de la última que lo tenga)."""
    end = t.rfind("\n", 0, pos)
    if end < 0:
        return "\n"
    return "\r\n" if end > 0 and t[end - 1] == "\r" else "\n"


def _last_scalar(node: Any) -> Any:
    while isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and node.value:
        last = node.value[-1]
        node = last[1] if isinstance(node, yaml.MappingNode) else last
    return node


def _after(t: str, node: Any) -> int:
    """Posición donde empieza la línea siguiente al bloque de `node` (inserción o fin de borrado).

    Se mide desde su último escalar, no desde la marca de fin del contenedor: esa marca la pone el
    token siguiente, después de los comentarios y líneas en blanco que no son del bloque. Un escalar
    `|` o `>` deja su marca en la sangría de la línea siguiente (el escáner ya consumió los saltos).
    """
    scalar = _last_scalar(node)
    p = scalar.end_mark.index
    if p >= len(t):
        return len(t)
    if getattr(scalar, "style", None) in ("|", ">"):
        start_ts = _line_start(t, p)
        if t[start_ts:p].strip(" ") == "":
            return start_ts
    return _next_line(t, p)


def _line_block(t: str, pos: int, lines: Sequence[str]) -> str:
    eol = _eol_before(t, pos)
    if pos == len(t) and t and not t.endswith("\n"):
        # Fichero sin salto final: se conserva así (la línea nueva tampoco lo lleva).
        return eol + eol.join(lines)
    return "".join(line + eol for line in lines)


def _deletion_span(t: str, a: int, b: int) -> tuple[int, int]:
    """Si se borra la última línea de un fichero sin salto final, se lleva el salto anterior."""
    if b == len(t) and t and not t.endswith("\n") and a > 0:
        a = t.rfind("\n", 0, a)
        if a > 0 and t[a - 1] == "\r":
            a -= 1
    return a, b


def _yaml_scalar(value: str, style: str | None) -> str:
    if style == "'":
        return "'" + value.replace("'", "''") + "'"
    if style == '"' or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@/+-]*", value):
        return json.dumps(value, ensure_ascii=False)
    return value


Edit = tuple[int, int, str]


def _edit_ttl(t: str, root: Any, c: SetTTL) -> list[Edit]:
    pair = _node_at(root, ("models", c.model))
    if pair is None or not isinstance(pair[1], yaml.MappingNode) or not pair[1].value:
        raise ResidencyError(f"el modelo `{c.model}` no tiene un mapa en `models`")
    mapping = pair[1]
    ttl = _par(mapping, "ttl")
    if ttl is not None:
        node = ttl[1]
        return [(node.start_mark.index, node.end_mark.index, str(c.seconds))]
    sangria = mapping.value[0][0].start_mark.column
    pos = _after(t, mapping)
    return [(pos, pos, _line_block(t, pos, [" " * sangria + f"ttl: {c.seconds}"]))]


def _group_node(root: Any, data: Mapping[str, Any], group: str) -> tuple[Any, Any]:
    pair = _node_at(root, (*_groups_path(data), group))
    if pair is None:
        raise ResidencyError(f"no existe el grupo `{group}`")
    return pair


def _node_members(root: Any, data: Mapping[str, Any], group: str) -> Any:
    _k, value = _group_node(root, data, group)
    pair = _par(value, "members")
    if pair is None or not isinstance(pair[1], yaml.SequenceNode) or not pair[1].value:
        raise ResidencyError(f"el grupo `{group}` no tiene una lista `members` en estilo bloque")
    return pair[1]


def _edit_remove(t: str, root: Any, data: Mapping[str, Any], c: RemoveMember) -> list[Edit]:
    for item in _node_members(root, data, c.group).value:
        if isinstance(item, yaml.ScalarNode) and item.value == c.member:
            a = _line_start(t, item.start_mark.index)
            if not re.fullmatch(r"\s*-\s*", t[a : item.start_mark.index]):
                raise ResidencyError(f"el miembro `{c.member}` no está solo en su línea")
            a, b = _deletion_span(t, a, _after(t, item))
            return [(a, b, "")]
    raise ResidencyError(f"`{c.member}` no es miembro del grupo `{c.group}`")


def _edit_add(t: str, root: Any, data: Mapping[str, Any], c: AddMember) -> list[Edit]:
    last = _node_members(root, data, c.group).value[-1]
    prefix = t[_line_start(t, last.start_mark.index) : last.start_mark.index]
    if not re.fullmatch(r"\s*-\s*", prefix):
        raise ResidencyError(f"el último miembro del grupo `{c.group}` no está solo en su línea")
    pos = _after(t, last)
    line = prefix + _yaml_scalar(c.member, getattr(last, "style", None))
    return [(pos, pos, _line_block(t, pos, [line]))]


def _edit_delete(t: str, root: Any, data: Mapping[str, Any], c: DeleteGroup) -> list[Edit]:
    key, value = _group_node(root, data, c.group)
    a, b = _deletion_span(t, _line_start(t, key.start_mark.index), _after(t, value))
    return [(a, b, "")]


def _edit_create(t: str, root: Any, data: Mapping[str, Any], c: CreateGroup) -> list[Edit]:
    pair = _node_at(root, _groups_path(data))
    group_column, inner_column, dash = 2, 4, 0
    if pair is None:
        if _groups_path(data) != ("groups",):
            raise ResidencyError("no hay bloque de grupos donde crear el nuevo")
        pos, header = len(t), ["groups:"]
        group_column, inner_column = 2, 4
    elif isinstance(pair[1], yaml.MappingNode) and pair[1].value:
        groups = pair[1]
        header = []
        group_column = groups.value[0][0].start_mark.column
        inner_column = group_column + 2
        for _k, value in groups.value:
            if isinstance(value, yaml.MappingNode) and value.value:
                inner_column = value.value[0][0].start_mark.column
                members = _par(value, "members")
                if members and isinstance(members[1], yaml.SequenceNode) and members[1].value:
                    item = members[1].value[0]
                    start_ts = _line_start(t, item.start_mark.index)
                    dash = len(t[start_ts : item.start_mark.index].split("-")[0]) - inner_column
        pos = _after(t, groups)
    else:
        raise ResidencyError("el bloque de grupos está vacío o no es un mapa: créalo a mano")
    inside = " " * inner_column
    lines = [
        *header,
        " " * group_column + f"{c.group}:",
        inside + f"persistent: {str(c.persistent).lower()}",
        inside + f"swap: {str(c.swap).lower()}",
        inside + f"exclusive: {str(c.exclusive).lower()}",
        inside + "members:",
        *(" " * (inner_column + max(dash, 0)) + f"- {_yaml_scalar(m, None)}" for m in c.members),
    ]
    return [(pos, pos, _line_block(t, pos, lines))]


def _apply_edits(t: str, edits: Sequence[Edit]) -> str:
    # De atrás hacia delante, para que ninguna desplace a las que faltan. En la misma posición, el
    # borrado va antes que la inserción (si no, borraría lo insertado), y las inserciones quedan en
    # el orden en que se pidieron.
    order = sorted(enumerate(edits), key=lambda e: (e[1][0], e[1][1], e[0]), reverse=True)
    for _i, (a, b, new) in order:
        t = t[:a] + new + t[b:]
    return t


def _apply_to_data(data: dict[str, Any], changes: Sequence[Change]) -> dict[str, Any]:
    expected = copy.deepcopy(data)
    for c in changes:
        if isinstance(c, SetTTL):
            expected["models"][c.model]["ttl"] = c.seconds
        elif isinstance(c, RemoveMember):
            _groups_in_data(expected)[c.group]["members"].remove(c.member)
        elif isinstance(c, AddMember):
            _groups_in_data(expected)[c.group]["members"].append(c.member)
        elif isinstance(c, DeleteGroup):
            del _groups_in_data(expected)[c.group]
        elif isinstance(c, CreateGroup):
            _groups_in_data(expected, create=True)[c.group] = {
                "persistent": c.persistent,
                "swap": c.swap,
                "exclusive": c.exclusive,
                "members": list(c.members),
            }
    return expected


def _autocomprobar(result: str, expected: dict[str, Any]) -> None:
    try:
        _analyze(result)
    except ResidencyError as e:
        raise ResidencyError(f"la autocomprobación no cuadra: {e}") from e
    if yaml.safe_load(result) != expected:
        raise ResidencyError(
            "la autocomprobación no cuadra: el resultado no es el original más el cambio pedido; "
            "no se escribe nada"
        )


def _describe(c: Change) -> str:
    if isinstance(c, SetTTL):
        return f"`ttl` de {c.model}: {c.seconds}"
    if isinstance(c, RemoveMember):
        return f"{c.member} sale del grupo `{c.group}`"
    if isinstance(c, AddMember):
        return f"{c.member} entra en el grupo `{c.group}`"
    if isinstance(c, DeleteGroup):
        return f"se borra el grupo `{c.group}`"
    return (
        f"grupo nuevo `{c.group}` (persistent: {str(c.persistent).lower()}, swap: "
        f"{str(c.swap).lower()}, exclusive: {str(c.exclusive).lower()}) con {', '.join(c.members)}"
    )


def edit(original: bytes, changes: Sequence[Change]) -> bytes:
    """Los bytes de la config con `changes` aplicados, tocando solo sus líneas (REQ-033)."""
    return edit_with_diff(original, changes)[0]


def edit_with_diff(original: bytes, changes: Sequence[Change]) -> tuple[bytes, list[str]]:
    """Como `edit`, y además el diff para `--dry-run`: sale de la lista de ediciones (no de
    comparar los dos ficheros), con el número de línea y una cabecera que dice qué cambia."""
    text, bom = _decode(original)
    root, data = _analyze(text)
    try:
        expected = _apply_to_data(data, changes)
    except (KeyError, ValueError, TypeError) as e:
        raise ResidencyError(f"el cambio no encaja con la config: {e!r}") from e
    edits: list[Edit] = []
    reasons: list[str] = []
    for c in changes:
        if isinstance(c, SetTTL):
            new_ones = _edit_ttl(text, root, c)
        elif isinstance(c, RemoveMember):
            new_ones = _edit_remove(text, root, data, c)
        elif isinstance(c, AddMember):
            new_ones = _edit_add(text, root, data, c)
        elif isinstance(c, DeleteGroup):
            new_ones = _edit_delete(text, root, data, c)
        else:
            new_ones = _edit_create(text, root, data, c)
        edits += new_ones
        reasons += [_describe(c)] * len(new_ones)
    result = _apply_edits(text, edits)
    _autocomprobar(result, expected)
    diff = _edits_diff(text, result, edits, reasons)
    return (BOM if bom else b"") + result.encode("utf-8"), diff


# --- Diff para --dry-run ---------------------------------------------------------------------


# Qué se tapa (REQ-033, ampliado tras la revisión de la ola 5): el valor de toda línea cuya clave
# sea sensible y de todo lo que cuelga de ella (los elementos de `apiKeys:`, también comentados), el
# de cualquier línea que contenga `key` (el texto literal de la spec), y el valor de toda asignación
# `NOMBRE=...` cuyo nombre lleve token/key/secret/password (`- "HF_TOKEN=..."` en `env`).
_SENSITIVE_KEY = re.compile(r"(?i)key|token|secret|password|authorization|bearer")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:token|key|secret|password)[A-Za-z0-9_]*=)[^\s'\"]*"
)
_YAML_LINE = re.compile(
    r"^(\s*(?:#\s*)?(?:-\s+)?)((?:\"[^\"]*\"|'[^']*'|[^\s#'\"-][^:#]*?)\s*:(?=\s|$))?(.*)$"
)


def _sensitive_lines(text: str) -> set[int]:
    """Índices (desde 0) de las líneas cuyo valor hay que tapar."""
    sensitive: set[int] = set()
    block: int | None = None  # sangría de la clave sensible cuyo bloque estamos recorriendo
    for i, line in enumerate(text.splitlines()):
        body = line.lstrip("\ufeff")
        clean = body.strip()
        sangria = len(body) - len(body.lstrip(" "))
        if block is not None:
            if (
                not clean
                or clean.startswith("#")
                or sangria > block
                or (sangria == block and clean.startswith("-"))
            ):
                sensitive.add(i)
                continue
            block = None
        m = _YAML_LINE.match(body)
        key = m.group(2) if m else None
        if key and _SENSITIVE_KEY.search(key) and not clean.startswith("#"):
            sensitive.add(i)
            rest = m.group(3).strip()
            if not rest or rest.startswith("#") or rest[0] in "|>":
                block = sangria
        elif "key" in clean.lower():
            sensitive.add(i)
    return sensitive


def _mask(line: str, sensible: bool) -> str:
    if not sensible:
        return _SENSITIVE_ASSIGNMENT.sub(r"\1***", line)
    m = _YAML_LINE.match(line)
    if m is None:
        return "***"
    prefix, key, rest = m.group(1), m.group(2), m.group(3)
    if key:
        return prefix + key + (" ***" if rest.strip() else "")
    return prefix + ("***" if rest.strip() else "")


def _diff_line(sign: str, number: int, line: str, sensible: bool) -> str:
    return f"{sign} {number:>4} | {_mask(line.rstrip(chr(13) + chr(10)), sensible)}"


def _edits_diff(
    before: str, after: str, edits: Sequence[Edit], reasons: Sequence[str]
) -> list[str]:
    """Cada edición, llevada a líneas enteras: las que quita (con su número en el fichero de
    ahora) y las que pone (con su número en el resultado), bajo una cabecera con qué cambia."""
    sens_a, sens_b = _sensitive_lines(before), _sensitive_lines(after)
    aligned = []
    for i, (a, b, new) in enumerate(edits):
        start_ts = _line_start(before, a)
        end = b if b == len(before) or b == _line_start(before, b) else _next_line(before, b)
        aligned.append((start_ts, end, i))
    aligned.sort()
    groups: list[list[tuple[int, int, int]]] = []
    for span in aligned:
        if groups and span[0] < max(t[1] for t in groups[-1]):
            groups[-1].append(span)
        else:
            groups.append([span])
    output: list[str] = []
    offset = 0
    for group in groups:
        start_ts = min(t[0] for t in group)
        end = max(t[1] for t in group)
        relative = [
            (edits[i][0] - start_ts, edits[i][1] - start_ts, edits[i][2]) for _a, _b, i in group
        ]
        removed = before[start_ts:end].splitlines(keepends=True)
        set_ones = _apply_edits(before[start_ts:end], relative).splitlines(keepends=True)
        first_one = before.count("\n", 0, start_ts)
        what = []
        for _a, _b, i in group:
            if reasons[i] not in what:
                what.append(reasons[i])
        output.append(f"# {'; '.join(what)}")
        output += [
            _diff_line("-", first_one + k + 1, line, first_one + k in sens_a)
            for k, line in enumerate(removed)
        ]
        new_one = first_one + offset
        output += [
            _diff_line("+", new_one + k + 1, line, new_one + k in sens_b)
            for k, line in enumerate(set_ones)
        ]
        offset += len(set_ones) - len(removed)
    return output


def hidden_diff(before: bytes, after: bytes) -> list[str]:
    """Diff de dos ficheros enteros (`--restore --dry-run`), con número de línea y tapado."""
    text_a = before.decode("utf-8", errors="replace").lstrip("\ufeff")
    text_b = after.decode("utf-8", errors="replace").lstrip("\ufeff")
    a, b = text_a.splitlines(keepends=True), text_b.splitlines(keepends=True)
    sens_a, sens_b = _sensitive_lines(text_a), _sensitive_lines(text_b)
    output: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        output += [_diff_line("-", k + 1, a[k], k in sens_a) for k in range(i1, i2)]
        output += [_diff_line("+", k + 1, b[k], k in sens_b) for k in range(j1, j2)]
    return output


# --- Carga y vista ---------------------------------------------------------------------------


@dataclass
class Loaded:
    path: Path
    original: bytes
    data: dict[str, Any]
    snapshot: topology.Snapshot | topology.NoTopology


def load(path: Path) -> Loaded:
    """Lee la config UNA vez: los mismos bytes dan los datos, la topología y la edición."""
    _requires_yaml()
    original = path.read_bytes()
    text, _bom = _decode(original)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise error_yaml("la config", e) from None
    if data is None:
        data = {}
    snapshot = topology.interpret(data, str(path), 1)
    return Loaded(path, original, data if isinstance(data, dict) else {}, snapshot)


@dataclass
class ModelRow:
    model: str
    group: str
    swap: bool
    exclusive: bool
    persistent: bool
    ttl: int
    mmproj: bool
    preload: bool


@dataclass
class View:
    rows: list[ModelRow]
    residents: tuple[str, ...]
    warnings: list[str] = field(default_factory=list)
    explanation: str = ""

    @property
    def verdict(self) -> str:
        if not self.residents:
            return "sin residente (recomendado)"
        return "; ".join(f"residente: {m}" for m in self.residents)

    def text(self) -> str:
        yes = {True: "sí", False: "no"}
        cab = ("modelo", "grupo", "swap", "exclusive", "persistent", "TTL", "mmproj", "preload")
        rows = [cab] + [
            (
                f.model,
                f.group,
                yes[f.swap],
                yes[f.exclusive],
                yes[f.persistent],
                str(f.ttl),
                yes[f.mmproj],
                yes[f.preload],
            )
            for f in self.rows
        ]
        widths = [max(len(row[i]) for row in rows) for i in range(len(cab))]
        lines = ["  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip() for row in rows]
        lines += ["", f"Veredicto: {self.verdict}"]
        if self.explanation:
            lines.append(f"Nota: {self.explanation}.")
        lines += [f"aviso: {a}" for a in self.warnings]
        lines.append(
            "TTL efectivo: un `ttl` ausente o -1 vale `globalTTL` (0 si no está); TTL 0 = residente."
        )
        return "\n".join(lines)


def view(snapshot: topology.Snapshot, data: Mapping[str, Any]) -> View:
    """Lo que muestra `residency` sin opciones (REQ-029). Nunca lleva `cmd` ni claves."""
    preloaded = set(snapshot.preloaded())
    rows: list[ModelRow] = []
    warnings: list[str] = []
    for m in snapshot.models:
        g = snapshot.group(m) or topology.DEFAULT_GROUP
        cfg = snapshot.groups[g]
        ttl = snapshot.effective_ttl(m) or 0
        rows.append(
            ModelRow(
                m,
                g,
                cfg.swap,
                cfg.exclusive,
                cfg.persistent,
                ttl,
                bool(snapshot.mmproj(m)),
                m in preloaded,
            )
        )
        if cfg.persistent and ttl > 0:
            warnings.append(
                f"el grupo `{g}` es persistent pero `{m}` tiene TTL efectivo {ttl}: "
                "`persistent` no lo mantiene cargado"
            )
        if ttl == 0 and not cfg.persistent:
            warnings.append(
                f"`{m}` tiene TTL efectivo 0 fuera de un grupo persistent: se queda cargado hasta "
                "que otro lo desaloje"
            )
    cfg_models = data.get("models") or {}
    no_ttl = [
        m
        for m in snapshot.models
        if (cfg_models.get(m) or {}).get("ttl", topology.DEFAULT_TTL) == topology.DEFAULT_TTL
    ]
    explanation = ""
    if no_ttl and not data.get("globalTTL"):
        explanation = f"{TTL_ZERO_EXPLANATION} ({', '.join(no_ttl)})"
    return View(rows, snapshot.residents(), warnings, explanation)


# --- Planes de cambio ------------------------------------------------------------------------


def _written_ttl(data: Mapping[str, Any], model: str) -> Any:
    return ((data.get("models") or {}).get(model) or {}).get("ttl")


def validate_ttls(
    ttls: Mapping[str, int], data: Mapping[str, Any], snapshot: topology.Snapshot
) -> None:
    """REQ-032: entero >= 1; el 0 es residencia (`--pin`); el -1 solo con `globalTTL` > 0."""
    global_ttl = data.get("globalTTL", 0) or 0
    for model, seconds in ttls.items():
        if snapshot.resolve(model) != model:
            raise ResidencyError(f"`{model}` no es un id de modelo de la config")
        if seconds == 0:
            raise ResidencyError(
                f"--ttl {model}=0 es residencia (no se descarga nunca): usa --pin {model}"
            )
        if seconds == -1 and not (isinstance(global_ttl, int) and global_ttl > 0):
            raise ResidencyError(
                f"--ttl {model}=-1 vale `globalTTL`, que aquí es 0 (residencia): pon un TTL >= 1"
            )
        if seconds < -1:
            raise ResidencyError(f"--ttl {model}={seconds}: el TTL es un entero >= 1")


def plan_ttl(
    ttls: Mapping[str, int], data: Mapping[str, Any], snapshot: topology.Snapshot
) -> list[Change]:
    validate_ttls(ttls, data, snapshot)
    return [SetTTL(m, s) for m, s in ttls.items() if _written_ttl(data, m) != s]


def _suggested_ttl(snapshot: topology.Snapshot) -> int | None:
    candidates = [
        snapshot.effective_ttl(m)
        for m in snapshot.models
        if not snapshot.mmproj(m) and (snapshot.effective_ttl(m) or 0) > 0
    ]
    return Counter(candidates).most_common(1)[0][0] if candidates else None


def plan_none(
    data: Mapping[str, Any],
    snapshot: topology.Snapshot,
    ttls: Mapping[str, int],
    group: str | None,
) -> list[Change]:
    """REQ-030: sin grupos persistentes y sin TTL efectivo 0. Lista vacía = nada que cambiar."""
    validate_ttls(ttls, data, snapshot)
    residents = [m for m in snapshot.residents() if m not in ttls]
    if residents:
        suggested = _suggested_ttl(snapshot)
        if suggested is None:
            hint = (
                "no queda ningún TTL distinto de 0 que sugerir (sin `globalTTL` ni `ttl`, todos los "
                "modelos tienen TTL efectivo 0): pasa --ttl MODEL=SECONDS para cada uno"
            )
        else:
            hint = "sugerencia: " + " ".join(f"--ttl {m}={suggested}" for m in residents)
            hint += " (el TTL más frecuente entre los demás modelos sin --mmproj)"
        raise ResidencyError(
            f"--none necesita --ttl para los modelos con TTL efectivo 0: {', '.join(residents)}; "
            + hint
        )
    persistent_ones = [
        g for g, cfg in snapshot.groups.items() if g != topology.DEFAULT_GROUP and cfg.persistent
    ]
    move = [m for g in persistent_ones for m in snapshot.groups[g].members]
    changes: list[Change] = []
    if persistent_ones:
        if move:
            target = _target_group(snapshot, persistent_ones, group)
            changes += [AddMember(target, m) for m in move]
        changes = [DeleteGroup(g) for g in persistent_ones] + changes
    return changes + plan_ttl(ttls, data, snapshot)


def _target_group(
    snapshot: topology.Snapshot, persistent_ones: Sequence[str], group: str | None
) -> str:
    valid = [
        g
        for g, cfg in snapshot.groups.items()
        if g != topology.DEFAULT_GROUP and g not in persistent_ones
    ]
    if group is not None:
        if group not in valid:
            raise ResidencyError(
                f"--group {group}: no es un grupo de la config que no sea persistent "
                f"(válidos: {', '.join(valid) or 'ninguno'})"
            )
        return group
    with_swap = [g for g in valid if snapshot.groups[g].swap]
    if len(with_swap) != 1:
        raise ResidencyError(
            "--none mueve los miembros de los grupos persistent al único grupo con `swap: true`, "
            f"y hay {len(with_swap)} ({', '.join(with_swap) or 'ninguno'}): elige uno con --group"
        )
    return with_swap[0]


def _gib(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def vram_figures(
    data: Mapping[str, Any],
    models: Sequence[str],
    model_vram: Mapping[str, float],
) -> dict[str, float]:
    """REQ-031: `--vram-model`, luego el estimador si pasó su control; si falta alguno, se niega."""
    figures: dict[str, float] = {}
    for m in models:
        if m in model_vram:
            figures[m] = model_vram[m]
        elif lc.NCMOE_ESTIMATOR_VALIDATED:
            est = lc.estimate_model_vram(m, (data.get("models") or {}).get(m) or {})
            if not est.error:
                figures[m] = est.gb
    missing = [m for m in models if m not in figures]
    if missing:
        reason = (
            "el estimador no da cifra para ellos"
            if lc.NCMOE_ESTIMATOR_VALIDATED
            else "el estimador de VRAM no pasó su control con los modelos medidos"
        )
        raise ResidencyError(
            f"no hay cifra fiable de VRAM para: {', '.join(missing)} ({reason}); pásala con "
            + " ".join(f"--vram-model {m}=GiB" for m in missing)
        )
    return figures


def plan_pin(
    data: Mapping[str, Any],
    snapshot: topology.Snapshot,
    model: str,
    vram_gb: float,
    reserve_gb: float,
    model_vram: Mapping[str, float],
) -> tuple[list[Change], str]:
    """REQ-031: el modelo a un grupo persistent, sin swap, NO exclusivo y con `ttl: 0`.

    `exclusive: false` va **explícito**: el defecto de v255 es `true`, y un grupo residente sin la
    clave desalojaría a los demás grupos al cargar (aclarado el 2026-10-07).
    Devuelve los cambios y el aviso de VRAM retenida; lista vacía = nada que cambiar.
    """
    real = snapshot.resolve(model)
    if real is None:
        raise ResidencyError(f"`{model}` no es un modelo de la config")
    actual = snapshot.group(real) or topology.DEFAULT_GROUP
    cfg = snapshot.groups[actual]
    already_in_resident_group = (
        actual != topology.DEFAULT_GROUP and cfg.persistent and not cfg.swap and not cfg.exclusive
    )
    if already_in_resident_group and _written_ttl(data, real) == 0:
        return [], ""
    # Cabe si `vram(M) + residentes que ya hay + peor caso del resto por grupos` entra en la VRAM
    # menos la reserva (aclaración de REQ-031 tras la revisión de la ola 5): un residente ya fijado
    # está siempre cargado, y un grupo `swap: false` carga a todos sus miembros a la vez.
    residents = [m for m in snapshot.residents() if m != real]
    rest = [m for m in snapshot.models if m != real and m not in residents]
    figures = vram_figures(data, [real, *residents, *rest], model_vram)
    residents_sum = sum(figures[m] for m in residents)
    other_groups: dict[str, dict[str, Any]] = {}
    for gid, gcfg in snapshot.groups.items():
        members = [snapshot.resolve(m) for m in gcfg.members if snapshot.resolve(m) in rest]
        if members:
            other_groups[gid] = {"swap": gcfg.swap, "members": members}
    estimates = {m: lc.ResourceEstimate(m, figures[m], "figure", "") for m in rest}
    worst_rest, _breakdown = lc.worst_case_gb(other_groups, estimates)
    needs = figures[real] + residents_sum + worst_rest
    available = vram_gb - reserve_gb
    if needs > available:
        addends = [_gib(figures[real])]
        if residents:
            addends.append(f"{_gib(residents_sum)} (residentes que ya hay: {', '.join(residents)})")
        addends.append(f"{_gib(worst_rest)} (peor caso del resto por grupos)")
        raise ResidencyError(
            f"{real} no cabe como residente: {' + '.join(addends)} = {_gib(needs)} GiB > "
            f"{_gib(vram_gb)} - {_gib(reserve_gb)} de reserva = {_gib(available)} GiB; "
            f"faltan {_gib(needs - available)} GiB"
        )
    margin_warning = f"queda {_gib(available - needs)} GiB de margen en el peor caso"
    if already_in_resident_group:
        # Ya está en un grupo como el que se crearía: basta con el TTL (diff mínimo).
        warning = (
            f"{real} ocupará {_gib(figures[real])} GiB de VRAM de forma permanente (grupo "
            f"`{actual}`, persistent y ttl 0); {margin_warning}"
        )
        return [SetTTL(real, 0)], warning
    changes: list[Change] = []
    if actual != topology.DEFAULT_GROUP:
        written_one = next(m for m in cfg.members if snapshot.resolve(m) == real)
        if len(cfg.members) == 1:
            changes.append(DeleteGroup(actual))
        else:
            changes.append(RemoveMember(actual, written_one))
    name, n = RESIDENT_GROUP, 1
    while name in snapshot.groups:
        n += 1
        name = f"{RESIDENT_GROUP}-{n}"
    changes.append(CreateGroup(name, True, False, False, (real,)))
    if _written_ttl(data, real) != 0:
        changes.append(SetTTL(real, 0))
    warning = (
        f"{real} ocupará {_gib(figures[real])} GiB de VRAM de forma permanente (grupo `{name}`, "
        f"persistent y ttl 0); {margin_warning}"
    )
    return changes, warning


# --- Escritura -------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now().astimezone()


def dated_copy(path: Path, content: bytes | None = None) -> Path:
    """`<config>.<AAAAMMDD-HHMMSS>.bak` sin pisar ninguna (REQ-033). Con `content`, guarda esos
    bytes (los que se acaban de comprobar) en vez de volver a leer el fichero."""
    base = f"{path.name}.{_now():%Y%m%d-%H%M%S}"
    if content is None:
        content = path.read_bytes()
    n = 0
    while True:
        target = path.with_name(f"{base}-{n}.bak" if n else f"{base}.bak")
        try:
            with open(target, "xb") as f:
                f.write(content)
        except FileExistsError:
            n += 1
            continue
        shutil.copystat(path, target)
        return target


def _write_bytes(f: Any, data: bytes) -> None:
    f.write(data)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def atomic_replace(path: Path, data: bytes) -> None:
    """Temporal en la misma carpeta y `os.replace`, con reintentos ante violación de compartición.

    En Windows `os.replace` falla con `PermissionError` (winerror 32, o 5 si el otro no comparte el
    borrado) mientras alguien tiene el destino abierto. Si tras `REPLACE_ATTEMPTS` sigue fallando,
    se borra el temporal y el original queda intacto.
    """
    fd, tmp_dir = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            _write_bytes(f, data)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copymode(path, tmp_dir)
        last: OSError | None = None
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_dir, path)
                return
            except PermissionError as e:
                last = e
                if attempt + 1 < REPLACE_ATTEMPTS:
                    _sleep(REPLACE_WAIT_S)
        raise ResidencyError(
            f"no se pudo reemplazar {path} tras {REPLACE_ATTEMPTS} intentos ({last}): "
            "el original queda intacto"
        )
    except BaseException:
        try:
            os.unlink(tmp_dir)
        except FileNotFoundError:
            pass
        raise


def validate_copy(content: bytes) -> None:
    """REQ-038: la copia a restaurar parsea y cumple lo de `load.go`."""
    _requires_yaml()
    text, _bom = _decode(content)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise error_yaml("la copia", e) from None
    read_one = topology.interpret(data, "", 1)
    if isinstance(read_one, topology.NoTopology) and read_one.reason != topology.MATRIX:
        raise ResidencyError(f"la copia no cumple load.go: {read_one.detail or read_one.reason}")
