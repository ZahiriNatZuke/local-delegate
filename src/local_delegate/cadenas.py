"""Cadenas de respaldo por rol (F3: REQ-003, REQ-004, REQ-014; enmendado por
`daemon-reparte-el-backend`, REQ-019 a REQ-023 y REQ-037).

Una cadena es la lista ordenada de pasos a los que se puede saltar cuando falla el modelo principal
de un rol. Se declara **por rol y no por nombre de modelo**, y se resuelve al vuelo con la
configuración vigente: así sobrevive a un cambio de los modelos por defecto.

Defectos (REQ-020), con `loaded` = los alternativos con celda aprobada para la tool que ya están
cargados, resueltos **en el momento del salto** (REQ-019):

- código   -> loaded -> largo
- largo    -> loaded -> código
- mecánico -> loaded -> largo
- visión   -> ninguna

Ninguna lleva al modelo mecánico desde código o largo (D-4 de F3 revocada). Sin bloque B no hay
proveedor de miembros: `loaded` sale vacío, se salta sin gastar salto, y las cadenas efectivas son
`code -> long`, `long -> code` y `mechanical -> long`. El nombre del paso se teclea, así que va en
inglés como los roles; `residente` y `resident` se siguen aceptando como sinónimos obsoletos, y
`doctor` pide renombrarlos (REQ-022).

El rol `rápido` tenía su fila y era **inalcanzable**, porque ninguna tool enrutaba a él. Se retiró
entero en la 0.30.0; ver `config.VARIABLES_ROL_RETIRADO`.

Al resolver se quitan los repetidos y el propio modelo principal, y lo que no sea un rol, un modelo
del catálogo de texto o `loaded` se ignora (y `doctor` lo avisa). Este módulo solo resuelve: qué
candidato es válido para una petición concreta (tamaño, enfriamiento) y el salto en sí viven en
`server._next_hop`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from . import config, topology

ROLES_DE_TEXTO = ("mechanical", "long", "code")
#: El paso de los modelos ya cargados (REQ-019). Se teclea: en inglés, como los roles.
LOADED = "loaded"
#: Nombres obsoletos del paso, que siguen valiendo con aviso de `doctor` (REQ-022).
_OBSOLETE_SYNONYMS = {"residente", "resident"}
#: Valores de una variable que desactivan el respaldo del rol. `none` existe porque en Windows fijar
#: una variable a "" la borra, así que la cadena vacía no se puede expresar en el daemon real.
_SIN_RESPALDO = {"", "none"}

CADENAS_POR_DEFECTO: dict[str, tuple[str, ...]] = {
    "code": (LOADED, "long"),
    "long": (LOADED, "code"),
    "mechanical": (LOADED, "long"),
}

#: Firma del proveedor de miembros de `loaded`: (tool, fallido, propios, nobody_else) -> modelos.
LoadedProvider = Callable[[str | None, str, frozenset[str], bool], Sequence[str]]
_loaded_provider: LoadedProvider | None = None


@dataclass(frozen=True)
class Cadena:
    rol: str
    #: Pasos en orden: modelos del catálogo y `LOADED`, sin repetidos y sin el modelo principal.
    pasos: tuple[str, ...]
    #: Lo que la variable del rol nombraba y no es ni un rol, ni un modelo del catálogo, ni `loaded`.
    ignorados: tuple[str, ...] = ()
    #: Pasos escritos con un nombre obsoleto de `loaded` (`residente`, `resident`), para el aviso.
    obsolete: tuple[str, ...] = ()

    @property
    def modelos(self) -> tuple[str, ...]:
        """Los modelos concretos de la cadena, sin `loaded`: la cadena efectiva sin bloque B."""
        return tuple(step for step in self.pasos if step != LOADED)


def register_loaded_provider(provider: LoadedProvider | None) -> None:
    """Registra (o quita, con `None`) quién sabe los miembros de `loaded`. Lo pone T15."""
    global _loaded_provider
    _loaded_provider = provider


def loaded_members(
    tool: str | None, has_failed: str, own_items: frozenset[str], nobody_else: bool
) -> tuple[str, ...]:
    """Los miembros de `loaded` en el momento del salto (REQ-019), en orden y sin `fallido`.

    `propios`: los modelos que ya usan las operaciones de este daemon; `nobody_else`: si no hay
    ninguna otra en `activos` (solo entonces cuentan los cargados con margen de REQ-013). **Sin
    proveedor registrado —sin bloque B— devuelve `()` sin tocar la red**: la matriz está vacía y
    `loaded` no tiene miembros.
    """
    provider = _loaded_provider
    if provider is None:
        return ()
    seen_set: list[str] = []
    for model in provider(tool, has_failed, own_items, nobody_else):
        if model != has_failed and model not in seen_set:
            seen_set.append(model)
    return tuple(seen_set)


def residents() -> tuple[str, ...] | None:
    """Los modelos con TTL efectivo 0 de la config de llama-swap (REQ-023), o `None` sin config.

    Sale de `topologia.residentes()`: sin `LLAMASWAP_CONFIG`, sin PyYAML o con una config que no
    se puede leer, no se sabe, y nunca se cae al modelo mecánico (el «residente fantasma»).
    """
    snapshot = topology.snapshot()
    if isinstance(snapshot, topology.Snapshot):
        return snapshot.residents()
    return None


def _pasos(rol: str) -> tuple[str, ...]:
    crudo = config.FALLBACK_CHAINS.get(rol)
    if crudo is None:
        return CADENAS_POR_DEFECTO[rol]
    if crudo.strip().lower() in _SIN_RESPALDO:
        return ()
    return tuple(paso.strip() for paso in crudo.split(",") if paso.strip())


def resolver(rol: str) -> Cadena:
    """La cadena del rol con la configuración vigente. Visión y cualquier rol desconocido: vacía.

    `loaded` queda como paso (sus miembros se resuelven al saltar, `loaded_members`); un rol o un
    modelo del catálogo, como su modelo concreto.
    """
    if rol not in ROLES_DE_TEXTO:
        return Cadena(rol, ())
    por_rol = config.modelos_por_rol()
    principal = por_rol[rol]
    pasos: list[str] = []
    ignorados: list[str] = []
    obsolete: list[str] = []
    for paso in _pasos(rol):
        if paso.lower() == LOADED:
            candidato = LOADED
        elif paso.lower() in _OBSOLETE_SYNONYMS:
            obsolete.append(paso)
            candidato = LOADED
        elif paso in por_rol:
            candidato = por_rol[paso]
        elif paso in config.ALLOWED_MODELS:
            candidato = paso
        else:
            ignorados.append(paso)
            continue
        if candidato != principal and candidato not in pasos:
            pasos.append(candidato)
    return Cadena(rol, tuple(pasos), tuple(ignorados), tuple(obsolete))


def describir() -> list[str]:
    """Las líneas de `local_status`: si el respaldo está encendido, el residente y cada cadena.

    Solo habla de «residente» si la config tiene un modelo con TTL efectivo 0 (REQ-023).
    """
    estado = "encendido" if config.FALLBACK else "apagado"
    lineas = [f"Respaldo entre modelos: {estado} (hasta {config.FALLBACK_MAX_HOPS} saltos)"]
    lineas.append(f"  {residents_text()}")
    for rol in ROLES_DE_TEXTO:
        cadena = resolver(rol)
        destino = " -> ".join(cadena.pasos) if cadena.pasos else "sin respaldo"
        lineas.append(f"  {rol}: {destino}")
    return lineas


def residents_text() -> str:
    """«sin residente» o «residente: X», el mismo texto para `local_status` y `doctor`.

    Sin foto de topología no se sabe, y se dice con el motivo de `NoTopology`, las mismas palabras
    que el «Turno: no (<motivo>)» de `local_status` (REQ-002): «sin residente (no se sabe: matrix)».
    """
    snapshot = topology.snapshot()
    if not isinstance(snapshot, topology.Snapshot):
        return f"sin residente (no se sabe: {snapshot.reason})"
    models = snapshot.residents()
    if not models:
        return "sin residente"
    return f"residente: {', '.join(models)}"
