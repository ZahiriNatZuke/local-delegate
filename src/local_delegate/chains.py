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
entero en la 0.30.0; ver `config.RETIRED_FAST_ROLE_VARIABLES`.

Al resolver se quitan los repetidos y el propio modelo principal, y lo que no sea un rol, un modelo
del catálogo de texto o `loaded` se ignora (y `doctor` lo avisa). Este módulo solo resuelve: qué
candidato es válido para una petición concreta (tamaño, enfriamiento) y el salto en sí viven en
`server._next_hop`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from . import config, topology

TEXT_ROLES = ("mechanical", "long", "code")
#: El paso de los modelos ya cargados (REQ-019). Se teclea: en inglés, como los roles.
LOADED = "loaded"
#: Nombres obsoletos del paso, que siguen valiendo con aviso de `doctor` (REQ-022).
_OBSOLETE_SYNONYMS = {"residente", "resident"}
#: Valores de una variable que desactivan el respaldo del rol. `none` existe porque en Windows fijar
#: una variable a "" la borra, así que la cadena vacía no se puede expresar en el daemon real.
_NO_FALLBACK_VALUES = {"", "none"}

DEFAULT_CHAINS: dict[str, tuple[str, ...]] = {
    "code": (LOADED, "long"),
    "long": (LOADED, "code"),
    "mechanical": (LOADED, "long"),
}

#: Firma del proveedor de miembros de `loaded`: (tool, has_failed, own_items, nobody_else, role) ->
#: modelos. `role` es el nombre del rol de la operación (`mechanical`…): las direcciones de REQ-011
#: dependen de él (T15).
LoadedProvider = Callable[[str | None, str, frozenset[str], bool, str | None], Sequence[str]]
_loaded_provider: LoadedProvider | None = None


@dataclass(frozen=True)
class Chain:
    role: str
    #: Pasos en orden: modelos del catálogo y `LOADED`, sin repetidos y sin el modelo principal.
    steps: tuple[str, ...]
    #: Lo que la variable del rol nombraba y no es ni un rol, ni un modelo del catálogo, ni `loaded`.
    ignored: tuple[str, ...] = ()
    #: Pasos escritos con un nombre obsoleto de `loaded` (`residente`, `resident`), para el aviso.
    obsolete: tuple[str, ...] = ()

    @property
    def models(self) -> tuple[str, ...]:
        """Los modelos concretos de la cadena, sin `loaded`: la cadena efectiva sin bloque B."""
        return tuple(step for step in self.steps if step != LOADED)


def register_loaded_provider(provider: LoadedProvider | None) -> None:
    """Registra (o quita, con `None`) quién sabe los miembros de `loaded`.

    T15 registra el de la afinidad (`server._affinity_loaded_provider`) al importar `server`.
    """
    global _loaded_provider
    _loaded_provider = provider


def loaded_members(
    tool: str | None,
    has_failed: str,
    own_items: frozenset[str],
    nobody_else: bool,
    role: str | None = None,
) -> tuple[str, ...]:
    """Los miembros de `loaded` en el momento del salto (REQ-019), en orden y sin `has_failed`.

    `own_items`: los modelos que ya usan las operaciones de este daemon; `nobody_else`: si no hay
    ninguna otra en `activos` (solo entonces cuentan los cargados con margen de REQ-013). **Sin
    proveedor registrado —sin bloque B— devuelve `()` sin tocar la red**: la matriz está vacía y
    `loaded` no tiene miembros.
    """
    provider = _loaded_provider
    if provider is None:
        return ()
    seen_set: list[str] = []
    for model in provider(tool, has_failed, own_items, nobody_else, role):
        if model != has_failed and model not in seen_set:
            seen_set.append(model)
    return tuple(seen_set)


def residents() -> tuple[str, ...] | None:
    """Los modelos con TTL efectivo 0 de la config de llama-swap (REQ-023), o `None` sin config.

    Sale de `topology.residents()`: sin `LLAMASWAP_CONFIG`, sin PyYAML o con una config que no
    se puede leer, no se sabe, y nunca se cae al modelo mecánico (el «residente fantasma»).
    """
    snapshot = topology.snapshot()
    if isinstance(snapshot, topology.Snapshot):
        return snapshot.residents()
    return None


def _steps(role: str) -> tuple[str, ...]:
    raw = config.FALLBACK_CHAINS.get(role)
    if raw is None:
        return DEFAULT_CHAINS[role]
    if raw.strip().lower() in _NO_FALLBACK_VALUES:
        return ()
    return tuple(step.strip() for step in raw.split(",") if step.strip())


def resolve(role: str) -> Chain:
    """La cadena del rol con la configuración vigente. Visión y cualquier rol desconocido: vacía.

    `loaded` queda como paso (sus miembros se resuelven al saltar, `loaded_members`); un rol o un
    modelo del catálogo, como su modelo concreto.
    """
    if role not in TEXT_ROLES:
        return Chain(role, ())
    by_role = config.modelos_por_rol()
    principal = by_role[role]
    steps: list[str] = []
    ignored: list[str] = []
    obsolete: list[str] = []
    for step in _steps(role):
        if step.lower() == LOADED:
            candidate = LOADED
        elif step.lower() in _OBSOLETE_SYNONYMS:
            obsolete.append(step)
            candidate = LOADED
        elif step in by_role:
            candidate = by_role[step]
        elif step in config.ALLOWED_MODELS:
            candidate = step
        else:
            ignored.append(step)
            continue
        if candidate != principal and candidate not in steps:
            steps.append(candidate)
    return Chain(role, tuple(steps), tuple(ignored), tuple(obsolete))


def describe() -> list[str]:
    """Las líneas de `local_status`: si el respaldo está encendido, el residente y cada cadena.

    Solo habla de «residente» si la config tiene un modelo con TTL efectivo 0 (REQ-023).
    """
    state = "encendido" if config.FALLBACK else "apagado"
    lines = [f"Respaldo entre modelos: {state} (hasta {config.FALLBACK_MAX_HOPS} saltos)"]
    lines.append(f"  {residents_text()}")
    for role in TEXT_ROLES:
        chain = resolve(role)
        target = " -> ".join(chain.steps) if chain.steps else "sin respaldo"
        lines.append(f"  {role}: {target}")
    return lines


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
