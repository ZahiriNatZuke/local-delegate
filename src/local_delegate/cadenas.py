"""Cadenas de respaldo por rol (F3: REQ-003, REQ-004, REQ-014).

Una cadena es la lista ordenada de modelos a los que se puede saltar cuando falla el modelo principal
de un rol. Se declara **por rol y no por nombre de modelo**, y se resuelve al vuelo con la
configuración vigente: así sobrevive a un cambio de los modelos por defecto.

Defectos de la spec, con «residente» = el modelo del grupo `persistent` de llama-swap, que ya está
en memoria y no obliga a cargar nada:

- código   -> residente -> largo
- largo    -> residente -> código
- mecánico -> largo
- visión   -> ninguna

El rol `rápido` tenía su fila —`rápido -> residente -> largo`— y era **inalcanzable**, porque
ninguna tool enrutaba a él. Se retiró entero en la 0.30.0; ver `config.VARIABLES_ROL_RETIRADO`.

Al resolver se quitan los repetidos y el propio modelo principal, y lo que no sea un rol ni un modelo
del catálogo de texto se ignora (y `doctor` lo avisa). Este módulo solo resuelve: qué candidato es
válido para una petición concreta (tamaño, enfriamiento) y el salto en sí son de la tarea 28.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config

ROLES_DE_TEXTO = ("mechanical", "long", "code")
RESIDENTE = "residente"
_NOMBRES_DEL_RESIDENTE = {"residente", "resident"}
#: Valores de una variable que desactivan el respaldo del rol. `none` existe porque en Windows fijar
#: una variable a "" la borra, así que la cadena vacía no se puede expresar en el daemon real.
_SIN_RESPALDO = {"", "none"}

CADENAS_POR_DEFECTO: dict[str, tuple[str, ...]] = {
    "code": (RESIDENTE, "long"),
    "long": (RESIDENTE, "code"),
    "mechanical": ("long",),
}


@dataclass(frozen=True)
class Cadena:
    rol: str
    #: Candidatos en orden, sin repetidos y sin el modelo principal del rol.
    modelos: tuple[str, ...]
    #: Lo que la variable del rol nombraba y no es ni un rol ni un modelo del catálogo.
    ignorados: tuple[str, ...] = ()


def residente() -> tuple[str, str]:
    """(modelo, de dónde salió). El del grupo `persistent` de llama-swap, o el del rol mecánico.

    Con varios miembros gana el primero, en el orden del YAML, que esté en el catálogo de texto. Sin
    `LLAMASWAP_CONFIG`, sin el extra `pyyaml` o con un YAML ilegible, cae al mecánico y lo dice: en
    una máquina donde los dos son el mismo modelo, el origen es lo único que distingue un camino
    del otro.
    """
    ruta = config.llamaswap_config_path()
    if ruta:
        try:
            from . import llamaswap_config

            datos = llamaswap_config.load_config(Path(ruta))
        except Exception:  # sin pyyaml, fichero ilegible: el residente sale del mecánico
            datos = {}
        grupos = datos.get("groups") if isinstance(datos, dict) else None
        if isinstance(grupos, dict):
            for nombre, grupo in grupos.items():
                if not (isinstance(grupo, dict) and grupo.get("persistent")):
                    continue
                for miembro in grupo.get("members") or []:
                    if miembro in config.ALLOWED_MODELS:
                        return miembro, f"grupo persistent «{nombre}» de llama-swap"
    return config.MODEL_MECHANICAL, "defecto: el modelo del rol mecánico"


def _pasos(rol: str) -> tuple[str, ...]:
    crudo = config.FALLBACK_CHAINS.get(rol)
    if crudo is None:
        return CADENAS_POR_DEFECTO[rol]
    if crudo.strip().lower() in _SIN_RESPALDO:
        return ()
    return tuple(paso.strip() for paso in crudo.split(",") if paso.strip())


def resolver(rol: str) -> Cadena:
    """La cadena del rol con la configuración vigente. Visión y cualquier rol desconocido: vacía."""
    if rol not in ROLES_DE_TEXTO:
        return Cadena(rol, ())
    por_rol = config.modelos_por_rol()
    principal = por_rol[rol]
    modelos: list[str] = []
    ignorados: list[str] = []
    for paso in _pasos(rol):
        if paso.lower() in _NOMBRES_DEL_RESIDENTE:
            candidato = residente()[0]
        elif paso in por_rol:
            candidato = por_rol[paso]
        elif paso in config.ALLOWED_MODELS:
            candidato = paso
        else:
            ignorados.append(paso)
            continue
        if candidato != principal and candidato not in modelos:
            modelos.append(candidato)
    return Cadena(rol, tuple(modelos), tuple(ignorados))


def describir() -> list[str]:
    """Las líneas de `local_status`: si el respaldo está encendido, el residente y cada cadena."""
    modelo, origen = residente()
    estado = "encendido" if config.FALLBACK else "apagado"
    lineas = [
        f"Respaldo entre modelos: {estado} (hasta {config.FALLBACK_MAX_HOPS} saltos)",
        f"  residente: {modelo} ({origen})",
    ]
    for rol in ROLES_DE_TEXTO:
        cadena = resolver(rol)
        destino = " -> ".join(cadena.modelos) if cadena.modelos else "sin respaldo"
        lineas.append(f"  {rol}: {destino}")
    return lineas
