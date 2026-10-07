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
(`topologia.validar_como_load_go`). Si no, `ErrorResidencia` y no se escribe nada.

**Escritura.** `copia_con_fecha()` deja `<config>.<AAAAMMDD-HHMMSS>.bak` sin pisar ninguna anterior
(sufijo `-1`, `-2`… si ya existe) y `reemplazar_atomico()` escribe un temporal en la misma carpeta y
lo cambia con `os.replace`, para que `-watch-config` nunca lea un fichero a medias. En Windows,
`os.replace` falla con una violación de compartición si alguien tiene el fichero abierto: se
reintenta hasta 5 veces con 200 ms entre intentos y, si sigue fallando, se borra el temporal y el
original queda intacto.

**TTL efectivo.** `load.go`: un `ttl` ausente o `-1` vale `globalTTL`, que por defecto es 0. Así que
**sin `globalTTL` ni `ttl` todos los modelos tienen TTL efectivo 0**: no se descargan nunca por TTL y
cuentan como residentes. `--none` exige entonces `--ttl` para todos.

**Antes de escribir (REQ-034).** Saber si hay delegaciones en curso es de T13. Hasta entonces
`comprobar_antes_de_escribir()` contesta siempre «no se sabe» y toda escritura exige `--now`.
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
from . import topologia

try:
    import yaml
except ImportError:  # pragma: no cover - depende del entorno de instalación
    yaml = None  # type: ignore[assignment]

BOM = b"\xef\xbb\xbf"
NO_SE_SABE = "no se sabe si hay delegaciones en curso"
# Campo de `GET /api/llamaswap/estado` (T13) con la ruta de la config que usa el daemon. Lo lee
# `cli._ruta_del_daemon`; el endpoint de T13 tiene que escribirlo con esta misma constante.
CAMPO_RUTA_CONFIG = "ruta_config"
CAMBIO_DURANTE_LA_EDICION = "la config cambió mientras se editaba; vuelve a intentarlo"
RESERVA_GB_POR_DEFECTO = 2.0
GRUPO_RESIDENTE = "residente"
INTENTOS_REEMPLAZO = 5
ESPERA_REEMPLAZO_S = 0.2
EXPLICACION_TTL_CERO = (
    "sin `globalTTL` ni `ttl`, el TTL efectivo es 0 (load.go: un `ttl` ausente o -1 vale "
    "`globalTTL`, que por defecto es 0): esos modelos no se descargan nunca por TTL y cuentan "
    "como residentes"
)


class ErrorResidencia(Exception):
    """La edición no se puede hacer con garantías. Nunca se escribe nada tras ella."""


# --- Cambios ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PonerTTL:
    modelo: str
    segundos: int


@dataclass(frozen=True)
class QuitarMiembro:
    grupo: str
    miembro: str


@dataclass(frozen=True)
class AnadirMiembro:
    grupo: str
    miembro: str


@dataclass(frozen=True)
class BorrarGrupo:
    grupo: str


@dataclass(frozen=True)
class CrearGrupo:
    grupo: str
    persistent: bool
    swap: bool
    exclusive: bool
    miembros: tuple[str, ...]


Cambio = PonerTTL | QuitarMiembro | AnadirMiembro | BorrarGrupo | CrearGrupo


# --- Lectura y negativas ---------------------------------------------------------------------


def _requiere_yaml() -> None:
    if yaml is None:
        raise ErrorResidencia(lc._EXTRA_INSTALL_MSG)


def _decodificar(original: bytes) -> tuple[str, bool]:
    bom = original.startswith(BOM)
    try:
        return original[len(BOM) :].decode("utf-8") if bom else original.decode("utf-8"), bom
    except UnicodeDecodeError as e:
        raise ErrorResidencia(f"la config no es UTF-8: {e}") from e


def _linea(marca: Any) -> int:
    return marca.line + 1


def error_yaml(quien: str, e: Exception) -> ErrorResidencia:
    """Solo el problema y la línea. `str(e)` de PyYAML cita el fragmento del fichero, y ese
    fragmento puede ser una clave (una comilla sin cerrar en `apiKeys`, por ejemplo)."""
    problema = getattr(e, "problem", None) or type(e).__name__
    marca = getattr(e, "problem_mark", None)
    donde = f" (línea {marca.line + 1})" if marca is not None else ""
    return ErrorResidencia(f"{quien} no se puede leer: {problema}{donde}")


def _sin_flujo_anclas_ni_alias(texto: str) -> None:
    try:
        tokens = list(yaml.scan(texto, Loader=yaml.SafeLoader))
    except yaml.YAMLError as e:
        raise error_yaml("el YAML", e) from None
    for token in tokens:
        if isinstance(token, (yaml.FlowMappingStartToken, yaml.FlowSequenceStartToken)):
            raise ErrorResidencia(
                f"nodo en estilo flujo (`{{…}}` o `[…]`) en la línea {_linea(token.start_mark)}: "
                "no se edita; escríbelo en estilo bloque"
            )
        if isinstance(token, yaml.AnchorToken):
            raise ErrorResidencia(
                f"ancla `&{token.value}` en la línea {_linea(token.start_mark)}: no se edita"
            )
        if isinstance(token, yaml.AliasToken):
            raise ErrorResidencia(
                f"alias `*{token.value}` en la línea {_linea(token.start_mark)}: no se edita"
            )


def _recorrer(nodo: Any):
    yield nodo
    if isinstance(nodo, yaml.MappingNode):
        for clave, valor in nodo.value:
            yield from _recorrer(clave)
            yield from _recorrer(valor)
    elif isinstance(nodo, yaml.SequenceNode):
        for hijo in nodo.value:
            yield from _recorrer(hijo)


def _sin_fusiones(raiz: Any) -> None:
    for nodo in _recorrer(raiz):
        if isinstance(nodo, yaml.MappingNode):
            for clave, _valor in nodo.value:
                if clave.tag == "tag:yaml.org,2002:merge":
                    raise ErrorResidencia(
                        f"`<<:` (fusión de mapas) en la línea {_linea(clave.start_mark)}: no se edita"
                    )


def _sin_claves_duplicadas(raiz: Any) -> None:
    for nodo in _recorrer(raiz):
        if isinstance(nodo, yaml.MappingNode):
            vistas: dict[tuple[str, str], int] = {}
            for clave, _valor in nodo.value:
                if not isinstance(clave, yaml.ScalarNode):
                    continue
                if (clave.tag, clave.value) in vistas:
                    raise ErrorResidencia(
                        f"clave duplicada `{clave.value}` en las líneas "
                        f"{vistas[(clave.tag, clave.value)]} y {_linea(clave.start_mark)}: llama-swap "
                        "y PyYAML se quedan con la última; arréglalo a mano antes de editar"
                    )
                vistas[(clave.tag, clave.value)] = _linea(clave.start_mark)


def _negativa_de_topologia(datos: Mapping[str, Any]) -> None:
    """Las mismas reglas que el lector de topología (forma, dos sintaxis, `matrix`, `load.go`),
    en el mismo orden: una forma inesperada (`routing: 5`) es una negativa, nunca una excepción."""
    leida = topologia.interpretar(datos, "", 1)
    if not isinstance(leida, topologia.SinTopologia):
        return
    if leida.motivo == topologia.DOS_SINTAXIS:
        raise ErrorResidencia(
            "la config usa las dos sintaxis a la vez (`groups`/`matrix` arriba y `routing.router`): "
            "llama-swap no la arrancaría"
        )
    if leida.motivo == topologia.MATRIX:
        raise ErrorResidencia(
            "la config usa el router `matrix`: la residencia por grupos no aplica"
        )
    raise ErrorResidencia(f"la config no cumple load.go: {leida.detalle or leida.motivo}")


def _analizar(texto: str) -> tuple[Any, dict[str, Any]]:
    """Nodo raíz y datos de un YAML que este módulo sabe editar. Si no, `ErrorResidencia`."""
    _requiere_yaml()
    _sin_flujo_anclas_ni_alias(texto)
    try:
        raiz = yaml.compose(texto, Loader=yaml.SafeLoader)
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        raise error_yaml("el YAML", e) from None
    if raiz is None or not isinstance(raiz, yaml.MappingNode) or not isinstance(datos, dict):
        raise ErrorResidencia("la raíz del YAML no es un mapa")
    _sin_fusiones(raiz)
    _sin_claves_duplicadas(raiz)
    _negativa_de_topologia(datos)
    return raiz, datos


# --- Localizar nodos -------------------------------------------------------------------------


def _par(mapa: Any, clave: str) -> tuple[Any, Any] | None:
    """El PRIMER par con esa clave (con claves duplicadas, la negativa va antes)."""
    if not isinstance(mapa, yaml.MappingNode):
        return None
    for k, v in mapa.value:
        if isinstance(k, yaml.ScalarNode) and k.value == clave:
            return k, v
    return None


def _ruta_grupos(datos: Mapping[str, Any]) -> tuple[str, ...]:
    """Dónde están los grupos, con el mismo criterio que `topologia` (arriba o en `routing`)."""
    arriba, en_routing = topologia.sintaxis(datos)
    if en_routing and not arriba:
        return ("routing", "router", "settings", "groups")
    return ("groups",)


def _nodo_en(raiz: Any, ruta: Sequence[str]) -> tuple[Any, Any] | None:
    nodo, par = raiz, None
    for clave in ruta:
        par = _par(nodo, clave)
        if par is None:
            return None
        nodo = par[1]
    return par


def _grupos_en_datos(datos: dict[str, Any], crear: bool = False) -> dict[str, Any]:
    destino: Any = datos
    ruta = _ruta_grupos(datos)
    for clave in ruta[:-1]:
        destino = destino[clave]
    if destino.get(ruta[-1]) is None and crear:
        destino[ruta[-1]] = {}
    return destino.get(ruta[-1]) or {}


# --- Texto -----------------------------------------------------------------------------------


def _inicio_linea(t: str, i: int) -> int:
    return t.rfind("\n", 0, i) + 1


def _siguiente_linea(t: str, i: int) -> int:
    j = t.find("\n", i)
    return len(t) if j < 0 else j + 1


def _eol_antes(t: str, pos: int) -> str:
    """Fin de línea de la línea que acaba justo antes de `pos` (o de la última que lo tenga)."""
    fin = t.rfind("\n", 0, pos)
    if fin < 0:
        return "\n"
    return "\r\n" if fin > 0 and t[fin - 1] == "\r" else "\n"


def _ultimo_escalar(nodo: Any) -> Any:
    while isinstance(nodo, (yaml.MappingNode, yaml.SequenceNode)) and nodo.value:
        ultimo = nodo.value[-1]
        nodo = ultimo[1] if isinstance(nodo, yaml.MappingNode) else ultimo
    return nodo


def _tras(t: str, nodo: Any) -> int:
    """Posición donde empieza la línea siguiente al bloque de `nodo` (inserción o fin de borrado).

    Se mide desde su último escalar, no desde la marca de fin del contenedor: esa marca la pone el
    token siguiente, después de los comentarios y líneas en blanco que no son del bloque. Un escalar
    `|` o `>` deja su marca en la sangría de la línea siguiente (el escáner ya consumió los saltos).
    """
    escalar = _ultimo_escalar(nodo)
    p = escalar.end_mark.index
    if p >= len(t):
        return len(t)
    if getattr(escalar, "style", None) in ("|", ">"):
        inicio = _inicio_linea(t, p)
        if t[inicio:p].strip(" ") == "":
            return inicio
    return _siguiente_linea(t, p)


def _bloque_de_lineas(t: str, pos: int, lineas: Sequence[str]) -> str:
    eol = _eol_antes(t, pos)
    if pos == len(t) and t and not t.endswith("\n"):
        # Fichero sin salto final: se conserva así (la línea nueva tampoco lo lleva).
        return eol + eol.join(lineas)
    return "".join(linea + eol for linea in lineas)


def _tramo_de_borrado(t: str, a: int, b: int) -> tuple[int, int]:
    """Si se borra la última línea de un fichero sin salto final, se lleva el salto anterior."""
    if b == len(t) and t and not t.endswith("\n") and a > 0:
        a = t.rfind("\n", 0, a)
        if a > 0 and t[a - 1] == "\r":
            a -= 1
    return a, b


def _escalar_yaml(valor: str, estilo: str | None) -> str:
    if estilo == "'":
        return "'" + valor.replace("'", "''") + "'"
    if estilo == '"' or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@/+-]*", valor):
        return json.dumps(valor, ensure_ascii=False)
    return valor


Edicion = tuple[int, int, str]


def _edicion_ttl(t: str, raiz: Any, c: PonerTTL) -> list[Edicion]:
    par = _nodo_en(raiz, ("models", c.modelo))
    if par is None or not isinstance(par[1], yaml.MappingNode) or not par[1].value:
        raise ErrorResidencia(f"el modelo `{c.modelo}` no tiene un mapa en `models`")
    mapa = par[1]
    ttl = _par(mapa, "ttl")
    if ttl is not None:
        nodo = ttl[1]
        return [(nodo.start_mark.index, nodo.end_mark.index, str(c.segundos))]
    sangria = mapa.value[0][0].start_mark.column
    pos = _tras(t, mapa)
    return [(pos, pos, _bloque_de_lineas(t, pos, [" " * sangria + f"ttl: {c.segundos}"]))]


def _grupo_nodo(raiz: Any, datos: Mapping[str, Any], grupo: str) -> tuple[Any, Any]:
    par = _nodo_en(raiz, (*_ruta_grupos(datos), grupo))
    if par is None:
        raise ErrorResidencia(f"no existe el grupo `{grupo}`")
    return par


def _miembros_nodo(raiz: Any, datos: Mapping[str, Any], grupo: str) -> Any:
    _k, valor = _grupo_nodo(raiz, datos, grupo)
    par = _par(valor, "members")
    if par is None or not isinstance(par[1], yaml.SequenceNode) or not par[1].value:
        raise ErrorResidencia(f"el grupo `{grupo}` no tiene una lista `members` en estilo bloque")
    return par[1]


def _edicion_quitar(t: str, raiz: Any, datos: Mapping[str, Any], c: QuitarMiembro) -> list[Edicion]:
    for item in _miembros_nodo(raiz, datos, c.grupo).value:
        if isinstance(item, yaml.ScalarNode) and item.value == c.miembro:
            a = _inicio_linea(t, item.start_mark.index)
            if not re.fullmatch(r"\s*-\s*", t[a : item.start_mark.index]):
                raise ErrorResidencia(f"el miembro `{c.miembro}` no está solo en su línea")
            a, b = _tramo_de_borrado(t, a, _tras(t, item))
            return [(a, b, "")]
    raise ErrorResidencia(f"`{c.miembro}` no es miembro del grupo `{c.grupo}`")


def _edicion_anadir(t: str, raiz: Any, datos: Mapping[str, Any], c: AnadirMiembro) -> list[Edicion]:
    ultimo = _miembros_nodo(raiz, datos, c.grupo).value[-1]
    prefijo = t[_inicio_linea(t, ultimo.start_mark.index) : ultimo.start_mark.index]
    if not re.fullmatch(r"\s*-\s*", prefijo):
        raise ErrorResidencia(f"el último miembro del grupo `{c.grupo}` no está solo en su línea")
    pos = _tras(t, ultimo)
    linea = prefijo + _escalar_yaml(c.miembro, getattr(ultimo, "style", None))
    return [(pos, pos, _bloque_de_lineas(t, pos, [linea]))]


def _edicion_borrar(t: str, raiz: Any, datos: Mapping[str, Any], c: BorrarGrupo) -> list[Edicion]:
    clave, valor = _grupo_nodo(raiz, datos, c.grupo)
    a, b = _tramo_de_borrado(t, _inicio_linea(t, clave.start_mark.index), _tras(t, valor))
    return [(a, b, "")]


def _edicion_crear(t: str, raiz: Any, datos: Mapping[str, Any], c: CrearGrupo) -> list[Edicion]:
    par = _nodo_en(raiz, _ruta_grupos(datos))
    columna_grupo, columna_dentro, guion = 2, 4, 0
    if par is None:
        if _ruta_grupos(datos) != ("groups",):
            raise ErrorResidencia("no hay bloque de grupos donde crear el nuevo")
        pos, cabecera = len(t), ["groups:"]
        columna_grupo, columna_dentro = 2, 4
    elif isinstance(par[1], yaml.MappingNode) and par[1].value:
        grupos = par[1]
        cabecera = []
        columna_grupo = grupos.value[0][0].start_mark.column
        columna_dentro = columna_grupo + 2
        for _k, valor in grupos.value:
            if isinstance(valor, yaml.MappingNode) and valor.value:
                columna_dentro = valor.value[0][0].start_mark.column
                miembros = _par(valor, "members")
                if miembros and isinstance(miembros[1], yaml.SequenceNode) and miembros[1].value:
                    item = miembros[1].value[0]
                    inicio = _inicio_linea(t, item.start_mark.index)
                    guion = len(t[inicio : item.start_mark.index].split("-")[0]) - columna_dentro
        pos = _tras(t, grupos)
    else:
        raise ErrorResidencia("el bloque de grupos está vacío o no es un mapa: créalo a mano")
    dentro = " " * columna_dentro
    lineas = [
        *cabecera,
        " " * columna_grupo + f"{c.grupo}:",
        dentro + f"persistent: {str(c.persistent).lower()}",
        dentro + f"swap: {str(c.swap).lower()}",
        dentro + f"exclusive: {str(c.exclusive).lower()}",
        dentro + "members:",
        *(
            " " * (columna_dentro + max(guion, 0)) + f"- {_escalar_yaml(m, None)}"
            for m in c.miembros
        ),
    ]
    return [(pos, pos, _bloque_de_lineas(t, pos, lineas))]


def _aplicar_ediciones(t: str, ediciones: Sequence[Edicion]) -> str:
    # De atrás hacia delante, para que ninguna desplace a las que faltan. En la misma posición, el
    # borrado va antes que la inserción (si no, borraría lo insertado), y las inserciones quedan en
    # el orden en que se pidieron.
    orden = sorted(enumerate(ediciones), key=lambda e: (e[1][0], e[1][1], e[0]), reverse=True)
    for _i, (a, b, nuevo) in orden:
        t = t[:a] + nuevo + t[b:]
    return t


def _aplicar_a_datos(datos: dict[str, Any], cambios: Sequence[Cambio]) -> dict[str, Any]:
    esperado = copy.deepcopy(datos)
    for c in cambios:
        if isinstance(c, PonerTTL):
            esperado["models"][c.modelo]["ttl"] = c.segundos
        elif isinstance(c, QuitarMiembro):
            _grupos_en_datos(esperado)[c.grupo]["members"].remove(c.miembro)
        elif isinstance(c, AnadirMiembro):
            _grupos_en_datos(esperado)[c.grupo]["members"].append(c.miembro)
        elif isinstance(c, BorrarGrupo):
            del _grupos_en_datos(esperado)[c.grupo]
        elif isinstance(c, CrearGrupo):
            _grupos_en_datos(esperado, crear=True)[c.grupo] = {
                "persistent": c.persistent,
                "swap": c.swap,
                "exclusive": c.exclusive,
                "members": list(c.miembros),
            }
    return esperado


def _autocomprobar(resultado: str, esperado: dict[str, Any]) -> None:
    try:
        _analizar(resultado)
    except ErrorResidencia as e:
        raise ErrorResidencia(f"la autocomprobación no cuadra: {e}") from e
    if yaml.safe_load(resultado) != esperado:
        raise ErrorResidencia(
            "la autocomprobación no cuadra: el resultado no es el original más el cambio pedido; "
            "no se escribe nada"
        )


def _describir(c: Cambio) -> str:
    if isinstance(c, PonerTTL):
        return f"`ttl` de {c.modelo}: {c.segundos}"
    if isinstance(c, QuitarMiembro):
        return f"{c.miembro} sale del grupo `{c.grupo}`"
    if isinstance(c, AnadirMiembro):
        return f"{c.miembro} entra en el grupo `{c.grupo}`"
    if isinstance(c, BorrarGrupo):
        return f"se borra el grupo `{c.grupo}`"
    return (
        f"grupo nuevo `{c.grupo}` (persistent: {str(c.persistent).lower()}, swap: "
        f"{str(c.swap).lower()}, exclusive: {str(c.exclusive).lower()}) con {', '.join(c.miembros)}"
    )


def editar(original: bytes, cambios: Sequence[Cambio]) -> bytes:
    """Los bytes de la config con `cambios` aplicados, tocando solo sus líneas (REQ-033)."""
    return editar_con_diff(original, cambios)[0]


def editar_con_diff(original: bytes, cambios: Sequence[Cambio]) -> tuple[bytes, list[str]]:
    """Como `editar`, y además el diff para `--dry-run`: sale de la lista de ediciones (no de
    comparar los dos ficheros), con el número de línea y una cabecera que dice qué cambia."""
    texto, bom = _decodificar(original)
    raiz, datos = _analizar(texto)
    try:
        esperado = _aplicar_a_datos(datos, cambios)
    except (KeyError, ValueError, TypeError) as e:
        raise ErrorResidencia(f"el cambio no encaja con la config: {e!r}") from e
    ediciones: list[Edicion] = []
    motivos: list[str] = []
    for c in cambios:
        if isinstance(c, PonerTTL):
            nuevas = _edicion_ttl(texto, raiz, c)
        elif isinstance(c, QuitarMiembro):
            nuevas = _edicion_quitar(texto, raiz, datos, c)
        elif isinstance(c, AnadirMiembro):
            nuevas = _edicion_anadir(texto, raiz, datos, c)
        elif isinstance(c, BorrarGrupo):
            nuevas = _edicion_borrar(texto, raiz, datos, c)
        else:
            nuevas = _edicion_crear(texto, raiz, datos, c)
        ediciones += nuevas
        motivos += [_describir(c)] * len(nuevas)
    resultado = _aplicar_ediciones(texto, ediciones)
    _autocomprobar(resultado, esperado)
    diff = _diff_de_ediciones(texto, resultado, ediciones, motivos)
    return (BOM if bom else b"") + resultado.encode("utf-8"), diff


# --- Diff para --dry-run ---------------------------------------------------------------------


# Qué se tapa (REQ-033, ampliado tras la revisión de la ola 5): el valor de toda línea cuya clave
# sea sensible y de todo lo que cuelga de ella (los elementos de `apiKeys:`, también comentados), el
# de cualquier línea que contenga `key` (el texto literal de la spec), y el valor de toda asignación
# `NOMBRE=...` cuyo nombre lleve token/key/secret/password (`- "HF_TOKEN=..."` en `env`).
_CLAVE_SENSIBLE = re.compile(r"(?i)key|token|secret|password|authorization|bearer")
_ASIGNACION_SENSIBLE = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:token|key|secret|password)[A-Za-z0-9_]*=)[^\s'\"]*"
)
_LINEA_YAML = re.compile(
    r"^(\s*(?:#\s*)?(?:-\s+)?)((?:\"[^\"]*\"|'[^']*'|[^\s#'\"-][^:#]*?)\s*:(?=\s|$))?(.*)$"
)


def _lineas_sensibles(texto: str) -> set[int]:
    """Índices (desde 0) de las líneas cuyo valor hay que tapar."""
    sensibles: set[int] = set()
    bloque: int | None = None  # sangría de la clave sensible cuyo bloque estamos recorriendo
    for i, linea in enumerate(texto.splitlines()):
        cuerpo = linea.lstrip("\ufeff")
        limpio = cuerpo.strip()
        sangria = len(cuerpo) - len(cuerpo.lstrip(" "))
        if bloque is not None:
            if (
                not limpio
                or limpio.startswith("#")
                or sangria > bloque
                or (sangria == bloque and limpio.startswith("-"))
            ):
                sensibles.add(i)
                continue
            bloque = None
        m = _LINEA_YAML.match(cuerpo)
        clave = m.group(2) if m else None
        if clave and _CLAVE_SENSIBLE.search(clave) and not limpio.startswith("#"):
            sensibles.add(i)
            resto = m.group(3).strip()
            if not resto or resto.startswith("#") or resto[0] in "|>":
                bloque = sangria
        elif "key" in limpio.lower():
            sensibles.add(i)
    return sensibles


def _tapar(linea: str, sensible: bool) -> str:
    if not sensible:
        return _ASIGNACION_SENSIBLE.sub(r"\1***", linea)
    m = _LINEA_YAML.match(linea)
    if m is None:
        return "***"
    prefijo, clave, resto = m.group(1), m.group(2), m.group(3)
    if clave:
        return prefijo + clave + (" ***" if resto.strip() else "")
    return prefijo + ("***" if resto.strip() else "")


def _linea_de_diff(signo: str, numero: int, linea: str, sensible: bool) -> str:
    return f"{signo} {numero:>4} | {_tapar(linea.rstrip(chr(13) + chr(10)), sensible)}"


def _diff_de_ediciones(
    antes: str, despues: str, ediciones: Sequence[Edicion], motivos: Sequence[str]
) -> list[str]:
    """Cada edición, llevada a líneas enteras: las que quita (con su número en el fichero de
    ahora) y las que pone (con su número en el resultado), bajo una cabecera con qué cambia."""
    sens_a, sens_b = _lineas_sensibles(antes), _lineas_sensibles(despues)
    alineadas = []
    for i, (a, b, nuevo) in enumerate(ediciones):
        inicio = _inicio_linea(antes, a)
        fin = b if b == len(antes) or b == _inicio_linea(antes, b) else _siguiente_linea(antes, b)
        alineadas.append((inicio, fin, i))
    alineadas.sort()
    grupos: list[list[tuple[int, int, int]]] = []
    for tramo in alineadas:
        if grupos and tramo[0] < max(t[1] for t in grupos[-1]):
            grupos[-1].append(tramo)
        else:
            grupos.append([tramo])
    salida: list[str] = []
    desplazamiento = 0
    for grupo in grupos:
        inicio = min(t[0] for t in grupo)
        fin = max(t[1] for t in grupo)
        relativas = [
            (ediciones[i][0] - inicio, ediciones[i][1] - inicio, ediciones[i][2])
            for _a, _b, i in grupo
        ]
        quitadas = antes[inicio:fin].splitlines(keepends=True)
        puestas = _aplicar_ediciones(antes[inicio:fin], relativas).splitlines(keepends=True)
        primera = antes.count("\n", 0, inicio)
        que = []
        for _a, _b, i in grupo:
            if motivos[i] not in que:
                que.append(motivos[i])
        salida.append(f"# {'; '.join(que)}")
        salida += [
            _linea_de_diff("-", primera + k + 1, linea, primera + k in sens_a)
            for k, linea in enumerate(quitadas)
        ]
        nueva = primera + desplazamiento
        salida += [
            _linea_de_diff("+", nueva + k + 1, linea, nueva + k in sens_b)
            for k, linea in enumerate(puestas)
        ]
        desplazamiento += len(puestas) - len(quitadas)
    return salida


def diff_oculto(antes: bytes, despues: bytes) -> list[str]:
    """Diff de dos ficheros enteros (`--restore --dry-run`), con número de línea y tapado."""
    texto_a = antes.decode("utf-8", errors="replace").lstrip("\ufeff")
    texto_b = despues.decode("utf-8", errors="replace").lstrip("\ufeff")
    a, b = texto_a.splitlines(keepends=True), texto_b.splitlines(keepends=True)
    sens_a, sens_b = _lineas_sensibles(texto_a), _lineas_sensibles(texto_b)
    salida: list[str] = []
    for etiqueta, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        if etiqueta == "equal":
            continue
        salida += [_linea_de_diff("-", k + 1, a[k], k in sens_a) for k in range(i1, i2)]
        salida += [_linea_de_diff("+", k + 1, b[k], k in sens_b) for k in range(j1, j2)]
    return salida


# --- Carga y vista ---------------------------------------------------------------------------


@dataclass
class Cargada:
    ruta: Path
    original: bytes
    datos: dict[str, Any]
    foto: topologia.Foto | topologia.SinTopologia


def cargar(ruta: Path) -> Cargada:
    """Lee la config UNA vez: los mismos bytes dan los datos, la topología y la edición."""
    _requiere_yaml()
    original = ruta.read_bytes()
    texto, _bom = _decodificar(original)
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        raise error_yaml("la config", e) from None
    if datos is None:
        datos = {}
    foto = topologia.interpretar(datos, str(ruta), 1)
    return Cargada(ruta, original, datos if isinstance(datos, dict) else {}, foto)


@dataclass
class FilaModelo:
    modelo: str
    grupo: str
    swap: bool
    exclusive: bool
    persistent: bool
    ttl: int
    mmproj: bool
    precarga: bool


@dataclass
class Vista:
    filas: list[FilaModelo]
    residentes: tuple[str, ...]
    avisos: list[str] = field(default_factory=list)
    explicacion: str = ""

    @property
    def veredicto(self) -> str:
        if not self.residentes:
            return "sin residente (recomendado)"
        return "; ".join(f"residente: {m}" for m in self.residentes)

    def texto(self) -> str:
        si = {True: "sí", False: "no"}
        cab = ("modelo", "grupo", "swap", "exclusive", "persistent", "TTL", "mmproj", "preload")
        filas = [cab] + [
            (
                f.modelo,
                f.grupo,
                si[f.swap],
                si[f.exclusive],
                si[f.persistent],
                str(f.ttl),
                si[f.mmproj],
                si[f.precarga],
            )
            for f in self.filas
        ]
        anchos = [max(len(fila[i]) for fila in filas) for i in range(len(cab))]
        lineas = [
            "  ".join(c.ljust(anchos[i]) for i, c in enumerate(fila)).rstrip() for fila in filas
        ]
        lineas += ["", f"Veredicto: {self.veredicto}"]
        if self.explicacion:
            lineas.append(f"Nota: {self.explicacion}.")
        lineas += [f"aviso: {a}" for a in self.avisos]
        lineas.append(
            "TTL efectivo: un `ttl` ausente o -1 vale `globalTTL` (0 si no está); TTL 0 = residente."
        )
        return "\n".join(lineas)


def vista(foto: topologia.Foto, datos: Mapping[str, Any]) -> Vista:
    """Lo que muestra `residencia` sin opciones (REQ-029). Nunca lleva `cmd` ni claves."""
    precargados = set(foto.precargados())
    filas: list[FilaModelo] = []
    avisos: list[str] = []
    for m in foto.modelos:
        g = foto.grupo(m) or topologia.GRUPO_POR_DEFECTO
        cfg = foto.grupos[g]
        ttl = foto.ttl_efectivo(m) or 0
        filas.append(
            FilaModelo(
                m,
                g,
                cfg.swap,
                cfg.exclusive,
                cfg.persistent,
                ttl,
                bool(foto.mmproj(m)),
                m in precargados,
            )
        )
        if cfg.persistent and ttl > 0:
            avisos.append(
                f"el grupo `{g}` es persistent pero `{m}` tiene TTL efectivo {ttl}: "
                "`persistent` no lo mantiene cargado"
            )
        if ttl == 0 and not cfg.persistent:
            avisos.append(
                f"`{m}` tiene TTL efectivo 0 fuera de un grupo persistent: se queda cargado hasta "
                "que otro lo desaloje"
            )
    modelos_cfg = datos.get("models") or {}
    sin_ttl = [
        m
        for m in foto.modelos
        if (modelos_cfg.get(m) or {}).get("ttl", topologia.TTL_POR_DEFECTO)
        == topologia.TTL_POR_DEFECTO
    ]
    explicacion = ""
    if sin_ttl and not datos.get("globalTTL"):
        explicacion = f"{EXPLICACION_TTL_CERO} ({', '.join(sin_ttl)})"
    return Vista(filas, foto.residentes(), avisos, explicacion)


# --- Planes de cambio ------------------------------------------------------------------------


def _ttl_escrito(datos: Mapping[str, Any], modelo: str) -> Any:
    return ((datos.get("models") or {}).get(modelo) or {}).get("ttl")


def validar_ttls(ttls: Mapping[str, int], datos: Mapping[str, Any], foto: topologia.Foto) -> None:
    """REQ-032: entero >= 1; el 0 es residencia (`--pin`); el -1 solo con `globalTTL` > 0."""
    global_ttl = datos.get("globalTTL", 0) or 0
    for modelo, segundos in ttls.items():
        if foto.resolver(modelo) != modelo:
            raise ErrorResidencia(f"`{modelo}` no es un id de modelo de la config")
        if segundos == 0:
            raise ErrorResidencia(
                f"--ttl {modelo}=0 es residencia (no se descarga nunca): usa --pin {modelo}"
            )
        if segundos == -1 and not (isinstance(global_ttl, int) and global_ttl > 0):
            raise ErrorResidencia(
                f"--ttl {modelo}=-1 vale `globalTTL`, que aquí es 0 (residencia): pon un TTL >= 1"
            )
        if segundos < -1:
            raise ErrorResidencia(f"--ttl {modelo}={segundos}: el TTL es un entero >= 1")


def plan_ttl(
    ttls: Mapping[str, int], datos: Mapping[str, Any], foto: topologia.Foto
) -> list[Cambio]:
    validar_ttls(ttls, datos, foto)
    return [PonerTTL(m, s) for m, s in ttls.items() if _ttl_escrito(datos, m) != s]


def _ttl_sugerido(foto: topologia.Foto) -> int | None:
    candidatos = [
        foto.ttl_efectivo(m)
        for m in foto.modelos
        if not foto.mmproj(m) and (foto.ttl_efectivo(m) or 0) > 0
    ]
    return Counter(candidatos).most_common(1)[0][0] if candidatos else None


def plan_ninguno(
    datos: Mapping[str, Any],
    foto: topologia.Foto,
    ttls: Mapping[str, int],
    grupo: str | None,
) -> list[Cambio]:
    """REQ-030: sin grupos persistentes y sin TTL efectivo 0. Lista vacía = nada que cambiar."""
    validar_ttls(ttls, datos, foto)
    residentes = [m for m in foto.residentes() if m not in ttls]
    if residentes:
        sugerido = _ttl_sugerido(foto)
        if sugerido is None:
            pista = (
                "no queda ningún TTL distinto de 0 que sugerir (sin `globalTTL` ni `ttl`, todos los "
                "modelos tienen TTL efectivo 0): pasa --ttl MODEL=SECONDS para cada uno"
            )
        else:
            pista = "sugerencia: " + " ".join(f"--ttl {m}={sugerido}" for m in residentes)
            pista += " (el TTL más frecuente entre los demás modelos sin --mmproj)"
        raise ErrorResidencia(
            f"--none necesita --ttl para los modelos con TTL efectivo 0: {', '.join(residentes)}; "
            + pista
        )
    persistentes = [
        g for g, cfg in foto.grupos.items() if g != topologia.GRUPO_POR_DEFECTO and cfg.persistent
    ]
    mover = [m for g in persistentes for m in foto.grupos[g].miembros]
    cambios: list[Cambio] = []
    if persistentes:
        if mover:
            destino = _grupo_destino(foto, persistentes, grupo)
            cambios += [AnadirMiembro(destino, m) for m in mover]
        cambios = [BorrarGrupo(g) for g in persistentes] + cambios
    return cambios + plan_ttl(ttls, datos, foto)


def _grupo_destino(foto: topologia.Foto, persistentes: Sequence[str], grupo: str | None) -> str:
    validos = [
        g
        for g, cfg in foto.grupos.items()
        if g != topologia.GRUPO_POR_DEFECTO and g not in persistentes
    ]
    if grupo is not None:
        if grupo not in validos:
            raise ErrorResidencia(
                f"--group {grupo}: no es un grupo de la config que no sea persistent "
                f"(válidos: {', '.join(validos) or 'ninguno'})"
            )
        return grupo
    con_swap = [g for g in validos if foto.grupos[g].swap]
    if len(con_swap) != 1:
        raise ErrorResidencia(
            "--none mueve los miembros de los grupos persistent al único grupo con `swap: true`, "
            f"y hay {len(con_swap)} ({', '.join(con_swap) or 'ninguno'}): elige uno con --group"
        )
    return con_swap[0]


def _gib(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",")


def cifras_de_vram(
    datos: Mapping[str, Any],
    modelos: Sequence[str],
    vram_modelo: Mapping[str, float],
) -> dict[str, float]:
    """REQ-031: `--vram-model`, luego el estimador si pasó su control; si falta alguno, se niega."""
    cifras: dict[str, float] = {}
    for m in modelos:
        if m in vram_modelo:
            cifras[m] = vram_modelo[m]
        elif lc.ESTIMADOR_NCMOE_VALIDADO:
            est = lc.estimate_model_vram(m, (datos.get("models") or {}).get(m) or {})
            if not est.error:
                cifras[m] = est.gb
    faltan = [m for m in modelos if m not in cifras]
    if faltan:
        motivo = (
            "el estimador no da cifra para ellos"
            if lc.ESTIMADOR_NCMOE_VALIDADO
            else "el estimador de VRAM no pasó su control con los modelos medidos"
        )
        raise ErrorResidencia(
            f"no hay cifra fiable de VRAM para: {', '.join(faltan)} ({motivo}); pásala con "
            + " ".join(f"--vram-model {m}=GiB" for m in faltan)
        )
    return cifras


def plan_fijar(
    datos: Mapping[str, Any],
    foto: topologia.Foto,
    modelo: str,
    vram_gb: float,
    reserva_gb: float,
    vram_modelo: Mapping[str, float],
) -> tuple[list[Cambio], str]:
    """REQ-031: el modelo a un grupo persistent, sin swap, NO exclusivo y con `ttl: 0`.

    `exclusive: false` va **explícito**: el defecto de v255 es `true`, y un grupo residente sin la
    clave desalojaría a los demás grupos al cargar (aclarado el 2026-10-07).
    Devuelve los cambios y el aviso de VRAM retenida; lista vacía = nada que cambiar.
    """
    real = foto.resolver(modelo)
    if real is None:
        raise ErrorResidencia(f"`{modelo}` no es un modelo de la config")
    actual = foto.grupo(real) or topologia.GRUPO_POR_DEFECTO
    cfg = foto.grupos[actual]
    ya_en_grupo_residente = (
        actual != topologia.GRUPO_POR_DEFECTO
        and cfg.persistent
        and not cfg.swap
        and not cfg.exclusive
    )
    if ya_en_grupo_residente and _ttl_escrito(datos, real) == 0:
        return [], ""
    # Cabe si `vram(M) + residentes que ya hay + peor caso del resto por grupos` entra en la VRAM
    # menos la reserva (aclaración de REQ-031 tras la revisión de la ola 5): un residente ya fijado
    # está siempre cargado, y un grupo `swap: false` carga a todos sus miembros a la vez.
    residentes = [m for m in foto.residentes() if m != real]
    resto = [m for m in foto.modelos if m != real and m not in residentes]
    cifras = cifras_de_vram(datos, [real, *residentes, *resto], vram_modelo)
    suma_residentes = sum(cifras[m] for m in residentes)
    grupos_resto: dict[str, dict[str, Any]] = {}
    for gid, gcfg in foto.grupos.items():
        miembros = [foto.resolver(m) for m in gcfg.miembros if foto.resolver(m) in resto]
        if miembros:
            grupos_resto[gid] = {"swap": gcfg.swap, "members": miembros}
    estimaciones = {m: lc.ResourceEstimate(m, cifras[m], "cifra", "") for m in resto}
    peor_resto, _desglose = lc.worst_case_gb(grupos_resto, estimaciones)
    necesita = cifras[real] + suma_residentes + peor_resto
    disponible = vram_gb - reserva_gb
    if necesita > disponible:
        sumandos = [_gib(cifras[real])]
        if residentes:
            sumandos.append(
                f"{_gib(suma_residentes)} (residentes que ya hay: {', '.join(residentes)})"
            )
        sumandos.append(f"{_gib(peor_resto)} (peor caso del resto por grupos)")
        raise ErrorResidencia(
            f"{real} no cabe como residente: {' + '.join(sumandos)} = {_gib(necesita)} GiB > "
            f"{_gib(vram_gb)} - {_gib(reserva_gb)} de reserva = {_gib(disponible)} GiB; "
            f"faltan {_gib(necesita - disponible)} GiB"
        )
    aviso_margen = f"queda {_gib(disponible - necesita)} GiB de margen en el peor caso"
    if ya_en_grupo_residente:
        # Ya está en un grupo como el que se crearía: basta con el TTL (diff mínimo).
        aviso = (
            f"{real} ocupará {_gib(cifras[real])} GiB de VRAM de forma permanente (grupo "
            f"`{actual}`, persistent y ttl 0); {aviso_margen}"
        )
        return [PonerTTL(real, 0)], aviso
    cambios: list[Cambio] = []
    if actual != topologia.GRUPO_POR_DEFECTO:
        escrito = next(m for m in cfg.miembros if foto.resolver(m) == real)
        if len(cfg.miembros) == 1:
            cambios.append(BorrarGrupo(actual))
        else:
            cambios.append(QuitarMiembro(actual, escrito))
    nombre, n = GRUPO_RESIDENTE, 1
    while nombre in foto.grupos:
        n += 1
        nombre = f"{GRUPO_RESIDENTE}-{n}"
    cambios.append(CrearGrupo(nombre, True, False, False, (real,)))
    if _ttl_escrito(datos, real) != 0:
        cambios.append(PonerTTL(real, 0))
    aviso = (
        f"{real} ocupará {_gib(cifras[real])} GiB de VRAM de forma permanente (grupo `{nombre}`, "
        f"persistent y ttl 0); {aviso_margen}"
    )
    return cambios, aviso


# --- Comprobación previa (REQ-034, de T13) ----------------------------------------------------


def comprobar_antes_de_escribir() -> str | None:
    """`None` si se puede escribir; si no, el motivo. Hasta T13, siempre «no se sabe»."""
    return NO_SE_SABE


# --- Escritura -------------------------------------------------------------------------------


def _ahora() -> datetime:
    return datetime.now().astimezone()


def copia_con_fecha(ruta: Path, contenido: bytes | None = None) -> Path:
    """`<config>.<AAAAMMDD-HHMMSS>.bak` sin pisar ninguna (REQ-033). Con `contenido`, guarda esos
    bytes (los que se acaban de comprobar) en vez de volver a leer el fichero."""
    base = f"{ruta.name}.{_ahora():%Y%m%d-%H%M%S}"
    if contenido is None:
        contenido = ruta.read_bytes()
    n = 0
    while True:
        destino = ruta.with_name(f"{base}-{n}.bak" if n else f"{base}.bak")
        try:
            with open(destino, "xb") as f:
                f.write(contenido)
        except FileExistsError:
            n += 1
            continue
        shutil.copystat(ruta, destino)
        return destino


def _escribir_bytes(f: Any, datos: bytes) -> None:
    f.write(datos)


def _dormir(segundos: float) -> None:
    time.sleep(segundos)


def reemplazar_atomico(ruta: Path, datos: bytes) -> None:
    """Temporal en la misma carpeta y `os.replace`, con reintentos ante violación de compartición.

    En Windows `os.replace` falla con `PermissionError` (winerror 32, o 5 si el otro no comparte el
    borrado) mientras alguien tiene el destino abierto. Si tras `INTENTOS_REEMPLAZO` sigue fallando,
    se borra el temporal y el original queda intacto.
    """
    fd, temporal = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            _escribir_bytes(f, datos)
            f.flush()
            os.fsync(f.fileno())
        if ruta.exists():
            shutil.copymode(ruta, temporal)
        ultimo: OSError | None = None
        for intento in range(INTENTOS_REEMPLAZO):
            try:
                os.replace(temporal, ruta)
                return
            except PermissionError as e:
                ultimo = e
                if intento + 1 < INTENTOS_REEMPLAZO:
                    _dormir(ESPERA_REEMPLAZO_S)
        raise ErrorResidencia(
            f"no se pudo reemplazar {ruta} tras {INTENTOS_REEMPLAZO} intentos ({ultimo}): "
            "el original queda intacto"
        )
    except BaseException:
        try:
            os.unlink(temporal)
        except FileNotFoundError:
            pass
        raise


def validar_copia(contenido: bytes) -> None:
    """REQ-038: la copia a restaurar parsea y cumple lo de `load.go`."""
    _requiere_yaml()
    texto, _bom = _decodificar(contenido)
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as e:
        raise error_yaml("la copia", e) from None
    leida = topologia.interpretar(datos, "", 1)
    if isinstance(leida, topologia.SinTopologia) and leida.motivo != topologia.MATRIX:
        raise ErrorResidencia(f"la copia no cumple load.go: {leida.detalle or leida.motivo}")
