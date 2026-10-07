"""Topologia de llama-swap: que modelos chocan, su TTL efectivo y quien es residente (REQ-001).

El daemon reparte el backend por turnos de modelos compatibles. Para saber si dos modelos pueden
estar cargados a la vez lee los grupos de `LLAMASWAP_CONFIG` y aplica la MISMA regla que llama-swap
v255 usa para desalojar. Esa regla es `groupSwapper.EvictionFor`, en `internal/router/group.go`
(lineas 70-104 del tag v255; el plan la cita como `src_group.go`, que en v255 ya no existe con ese
nombre). Copiada literal:

```go
func (p *groupSwapper) EvictionFor(target string, running []string) []string {
        tg := p.modelToGroup[target]
        tgCfg := p.config.Routing.Router.Settings.Groups[tg]

        seen := make(map[string]struct{})
        var result []string
        consider := func(mID string) {
                if mID == target {
                        return
                }
                if _, dup := seen[mID]; dup {
                        return
                }
                og := p.modelToGroup[mID]
                switch {
                case og == tg && tgCfg.Swap:
                        seen[mID] = struct{}{}
                        result = append(result, mID)
                // the previous ProcessGroup behaviour did not unload exclusive groups
                // when loading a non-exclusive model. This maintains that gotcha
                // for backwards compatibility. The newer swap matrix approach does not
                // have this issue.
                case og != tg && tgCfg.Exclusive:
                        if ogCfg := p.config.Routing.Router.Settings.Groups[og]; !ogCfg.Persistent {
                                seen[mID] = struct{}{}
                                result = append(result, mID)
                        }
                }
        }

        for _, mID := range running {
                consider(mID)
        }
        return result
}
```

Lo demas sale de `internal/config` de v255:

- `GroupConfig.UnmarshalYAML`: una clave ausente vale `swap: true`, `exclusive: true`,
  `persistent: false`.
- `AddDefaultGroupToConfig`: los modelos que no son miembro literal de ningun grupo van a
  `(default)`, con `swap: true, exclusive: true` (pisa un grupo que ya se llamara asi).
- `load.go`: `ttl` ausente o `-1` (`MODEL_CONFIG_DEFAULT_TTL`) vale `globalTTL`, que por defecto es
  0; un TTL efectivo menor que 0 es error. Las claves `groups`/`matrix` de arriba y el bloque
  `routing.router` se excluyen; `routing.router.use` es `group` (o vacio) o `matrix`. Los alias van
  al id real con `RealModelName`, y `hooks.on_startup.preload` se limpia igual.
- `NewGroup` mapea cada miembro TAL CUAL esta escrito: un miembro escrito con un alias no mueve al
  id real, que acaba tambien en `(default)`. Aqui se reproduce, no se corrige.

Dos modelos **chocan** si cargar uno desaloja al otro en cualquiera de los dos sentidos; un modelo
nunca choca consigo mismo, y un modelo que no esta en la config es compatible con todos (REQ-002).
Sin topologia (`SinTopologia`) el daemon no usa turno y se comporta como hoy. Este modulo no conoce
el backend: decidir que un backend remoto va sin turno es cosa de quien lo llama.

`foto()` lee la config en caliente (REQ-009): la vuelve a leer cuando cambia la `mtime` o el
tamano, y si no, devuelve la misma foto sin tocar el disco. Ningun nombre de modelo ni de grupo
esta fijo en el codigo.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from . import config, huella

try:
    import yaml
except ImportError:  # pragma: no cover - depende del entorno de instalacion
    yaml = None  # type: ignore[assignment]

GRUPO_POR_DEFECTO = "(default)"
TTL_POR_DEFECTO = -1  # MODEL_CONFIG_DEFAULT_TTL de v255: «usa globalTTL»

# Motivos de REQ-002 por los que no hay turno.
SIN_CONFIG = "sin LLAMASWAP_CONFIG"
SIN_PYYAML = "sin PyYAML"
ILEGIBLE = "ilegible"
MATRIX = "matrix"
DOS_SINTAXIS = "dos sintaxis"
NO_CUMPLE_LOAD_GO = "no cumple load.go"


@dataclass(frozen=True)
class SinTopologia:
    """No hay topologia: el daemon no usa turno. `motivo` es uno de los de REQ-002."""

    motivo: str
    detalle: str = field(default="", compare=False)


@dataclass(frozen=True)
class Grupo:
    swap: bool
    exclusive: bool
    persistent: bool
    miembros: tuple[str, ...]


def _bool(valor: Any, defecto: bool) -> bool:
    return defecto if valor is None else bool(valor)


def _es_entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _es_mapa(valor: Any) -> bool:
    return valor is None or isinstance(valor, Mapping)


def _es_lista(valor: Any) -> bool:
    return valor is None or isinstance(valor, list)


def _es_escalar(valor: Any) -> bool:
    return isinstance(valor, (str, int, float)) and not isinstance(valor, bool)


def _errores_de_forma(datos: Mapping[str, Any]) -> list[str]:
    """Tipos que `load.go` no puede ni deserializar (un mapa escrito como lista o al reves).

    Va antes que todo lo demas: el resto del modulo da por buena esta forma. Lista vacia = la
    forma es la que espera el `Config` de v255. Una lista de `members` escrita como cadena se
    rechaza aunque en Python se pueda recorrer: Go no la convierte a `[]string`.
    """
    errores: list[str] = []
    modelos = datos.get("models")
    if not _es_mapa(modelos):
        return ["`models` no es un mapa"]
    for mid, cfg in (modelos or {}).items():
        if not _es_mapa(cfg):
            errores.append(f"modelo {mid}: no es un mapa")
            continue
        cfg = cfg or {}
        if not _es_lista(cfg.get("aliases")):
            errores.append(f"modelo {mid}: `aliases` no es una lista")
        elif any(not _es_escalar(a) for a in cfg.get("aliases") or []):
            errores.append(f"modelo {mid}: un alias no es un texto")
        if cfg.get("cmd") is not None and not _es_escalar(cfg.get("cmd")):
            errores.append(f"modelo {mid}: `cmd` no es un texto")
    bloques_de_grupos = [("groups", datos.get("groups"))]
    routing = datos.get("routing")
    if not _es_mapa(routing):
        errores.append("`routing` no es un mapa")
    else:
        router = (routing or {}).get("router")
        if not _es_mapa(router):
            errores.append("`routing.router` no es un mapa")
        else:
            router = router or {}
            if router.get("use") is not None and not isinstance(router.get("use"), str):
                errores.append("`routing.router.use` no es un texto")
            ajustes = router.get("settings")
            if not _es_mapa(ajustes):
                errores.append("`routing.router.settings` no es un mapa")
            else:
                grupos = (ajustes or {}).get("groups")
                bloques_de_grupos.append(("routing.router.settings.groups", grupos))
    for nombre, grupos in bloques_de_grupos:
        if not _es_mapa(grupos):
            errores.append(f"`{nombre}` no es un mapa")
            continue
        for gid, gcfg in (grupos or {}).items():
            if not _es_mapa(gcfg):
                errores.append(f"grupo {gid}: no es un mapa")
                continue
            miembros = (gcfg or {}).get("members")
            if not _es_lista(miembros):
                errores.append(f"grupo {gid}: `members` no es una lista")
            elif any(not _es_escalar(m) for m in miembros or []):
                errores.append(f"grupo {gid}: un miembro no es un texto")
    hooks = datos.get("hooks")
    if not _es_mapa(hooks):
        errores.append("`hooks` no es un mapa")
    else:
        arranque = (hooks or {}).get("on_startup")
        if not _es_mapa(arranque):
            errores.append("`hooks.on_startup` no es un mapa")
        else:
            precarga = (arranque or {}).get("preload")
            if not _es_lista(precarga):
                errores.append("`hooks.on_startup.preload` no es una lista")
            elif any(not _es_escalar(p) for p in precarga or []):
                errores.append("`hooks.on_startup.preload`: un elemento no es un texto")
    return errores


def _sintaxis(datos: Mapping[str, Any]) -> tuple[bool, bool]:
    """(usa las claves de arriba, usa `routing.router`), con el mismo criterio que `load.go`."""
    arriba = datos.get("matrix") is not None or bool(datos.get("groups"))
    router = ((datos.get("routing") or {}).get("router")) or {}
    ajustes = router.get("settings") or {}
    en_routing = (
        bool(router.get("use")) or ajustes.get("matrix") is not None or bool(ajustes.get("groups"))
    )
    return arriba, en_routing


def _grupos_crudos(datos: Mapping[str, Any]) -> Mapping[str, Any]:
    arriba, _ = _sintaxis(datos)
    if arriba:
        return datos.get("groups") or {}
    router = ((datos.get("routing") or {}).get("router")) or {}
    return (router.get("settings") or {}).get("groups") or {}


def _usa_matrix(datos: Mapping[str, Any]) -> bool:
    arriba, _ = _sintaxis(datos)
    if arriba:
        return datos.get("matrix") is not None
    router = ((datos.get("routing") or {}).get("router")) or {}
    return router.get("use") == "matrix"


def _alias(modelos: Mapping[str, Any]) -> dict[str, str]:
    alias: dict[str, str] = {}
    for mid, cfg in modelos.items():
        for nombre in (cfg or {}).get("aliases") or []:
            alias.setdefault(str(nombre), str(mid))
    return alias


def validar_como_load_go(datos: Any) -> list[str]:
    """Lo que `load.go` de v255 rechazaria, para las reglas de REQ-033. Lista vacia = valida.

    Reglas: raiz y `models` son mapas; no las dos sintaxis a la vez; `routing.router.use` conocido;
    `globalTTL` entero >= 0; cada `ttl` entero y con TTL efectivo >= 0; alias sin repetir; cada
    miembro existe (id o alias), no se repite en su grupo y esta en un solo grupo.
    """
    if not isinstance(datos, Mapping):
        return ["la raiz del YAML no es un mapa"]
    errores: list[str] = []
    modelos = datos.get("models") or {}
    if not isinstance(modelos, Mapping):
        return ["`models` no es un mapa"]
    forma = _errores_de_forma(datos)
    if forma:
        return forma
    arriba, en_routing = _sintaxis(datos)
    if arriba and en_routing:
        errores.append("usa a la vez `groups`/`matrix` de arriba y `routing.router`")
    router = ((datos.get("routing") or {}).get("router")) or {}
    uso = router.get("use") or ""
    if not arriba and uso not in ("", "group", "matrix"):
        errores.append(f"`routing.router.use` desconocido: {uso!r} (validos: group, matrix)")
    if not arriba and uso == "matrix" and (router.get("settings") or {}).get("matrix") is None:
        errores.append(
            "`routing.router.use` es matrix pero no hay `routing.router.settings.matrix`"
        )
    global_ttl = datos.get("globalTTL", 0)
    if not _es_entero(global_ttl) or global_ttl < 0:
        errores.append("`globalTTL` debe ser un entero >= 0")
        global_ttl = 0
    vistos_alias: dict[str, str] = {}
    for mid, cfg in modelos.items():
        cfg = cfg or {}
        if not isinstance(cfg, Mapping):
            errores.append(f"modelo {mid}: no es un mapa")
            continue
        ttl = cfg.get("ttl", TTL_POR_DEFECTO)
        if not _es_entero(ttl):
            errores.append(f"modelo {mid}: `ttl` debe ser un entero")
        elif (global_ttl if ttl == TTL_POR_DEFECTO else ttl) < 0:
            errores.append(f"modelo {mid}: TTL no valido {ttl}")
        for nombre in cfg.get("aliases") or []:
            if nombre in vistos_alias:
                errores.append(f"alias repetido {nombre} en el modelo {mid}")
            vistos_alias[nombre] = str(mid)
    if _usa_matrix(datos):
        return errores
    grupos = _grupos_crudos(datos)
    if not isinstance(grupos, Mapping):
        return [*errores, "`groups` no es un mapa"]
    uso_miembro: dict[str, str] = {}
    for gid, gcfg in grupos.items():
        miembros = (gcfg or {}).get("members") or []
        en_grupo: set[str] = set()
        for miembro in miembros:
            miembro = str(miembro)
            if miembro in en_grupo:
                errores.append(f"miembro {miembro} repetido en el grupo {gid}")
            en_grupo.add(miembro)
            if miembro in uso_miembro:
                errores.append(f"miembro {miembro} en dos grupos: {uso_miembro[miembro]} y {gid}")
            uso_miembro[miembro] = str(gid)
            if miembro not in modelos and miembro not in vistos_alias:
                errores.append(f"miembro {miembro} del grupo {gid} no es ningun modelo")
    return errores


@dataclass(frozen=True)
class Foto:
    """La topologia leida de una config en un momento dado. Inmutable."""

    ruta: str
    version: int
    modelos: tuple[str, ...]
    grupos: Mapping[str, Grupo]
    alias: Mapping[str, str]
    _grupo_de: Mapping[str, str] = field(repr=False)
    _ttl: Mapping[str, int] = field(repr=False)
    _cmd: Mapping[str, str] = field(repr=False)
    _precargados: tuple[str, ...] = field(repr=False)

    def resolver(self, modelo: str) -> str | None:
        """Id real de un id o alias (`RealModelName`); `None` si no esta en la config."""
        if modelo in self._ttl:
            return modelo
        return self.alias.get(modelo)

    def grupo(self, modelo: str) -> str | None:
        real = self.resolver(modelo)
        return None if real is None else self._grupo_de.get(real)

    def _desaloja(self, objetivo: str, otro: str) -> bool:
        """`otro` sale en `EvictionFor(objetivo, [otro])`. Ids reales."""
        if objetivo == otro:
            return False
        tg = self._grupo_de.get(objetivo)
        og = self._grupo_de.get(otro)
        cfg_t = self.grupos.get(tg) if tg is not None else None
        if cfg_t is None:
            return False
        if og == tg:
            return cfg_t.swap
        if cfg_t.exclusive:
            cfg_o = self.grupos.get(og) if og is not None else None
            return not (cfg_o is not None and cfg_o.persistent)
        return False

    def choca(self, a: str, b: str) -> bool:
        """Cargar uno desaloja al otro, en cualquiera de los dos sentidos (REQ-001)."""
        ra, rb = self.resolver(a), self.resolver(b)
        if ra is None or rb is None or ra == rb:
            return False
        return self._desaloja(ra, rb) or self._desaloja(rb, ra)

    def ttl_efectivo(self, modelo: str) -> int | None:
        real = self.resolver(modelo)
        return None if real is None else self._ttl[real]

    def mmproj(self, modelo: str) -> str | None:
        """Ruta del `--mmproj` del `cmd` (via `huella.flags_del_cmd`), o `None`."""
        real = self.resolver(modelo)
        if real is None or not self._cmd.get(real):
            return None
        return huella.flags_del_cmd(self._cmd[real]).get("mmproj")

    def precargados(self) -> tuple[str, ...]:
        """`hooks.on_startup.preload` resuelto a ids reales, como lo limpia `load.go`."""
        return self._precargados

    def residentes(self) -> tuple[str, ...]:
        """Modelos con TTL efectivo 0: no se descargan nunca por TTL (REQ-023, REQ-029)."""
        return tuple(m for m in self.modelos if self._ttl[m] == 0)


def _construir(datos: Mapping[str, Any], ruta: str, version: int) -> Foto:
    modelos_cfg: Mapping[str, Any] = datos.get("models") or {}
    modelos = tuple(str(m) for m in modelos_cfg)
    global_ttl = datos.get("globalTTL", 0)
    ttl: dict[str, int] = {}
    cmd: dict[str, str] = {}
    for mid in modelos:
        cfg = modelos_cfg[mid] or {}
        valor = cfg.get("ttl", TTL_POR_DEFECTO)
        ttl[mid] = global_ttl if valor == TTL_POR_DEFECTO else valor
        if cfg.get("cmd"):
            cmd[mid] = str(cfg["cmd"])
    alias = _alias(modelos_cfg)
    grupos: dict[str, Grupo] = {}
    grupo_de: dict[str, str] = {}
    for gid, gcfg in _grupos_crudos(datos).items():
        gcfg = gcfg or {}
        miembros = tuple(str(m) for m in gcfg.get("members") or [])
        grupos[str(gid)] = Grupo(
            swap=_bool(gcfg.get("swap"), True),
            exclusive=_bool(gcfg.get("exclusive"), True),
            persistent=_bool(gcfg.get("persistent"), False),
            miembros=miembros,
        )
        for miembro in miembros:
            grupo_de[miembro] = str(gid)
    sueltos = tuple(sorted(m for m in modelos if m not in grupo_de))
    grupos[GRUPO_POR_DEFECTO] = Grupo(swap=True, exclusive=True, persistent=False, miembros=sueltos)
    for miembro in sueltos:
        grupo_de[miembro] = GRUPO_POR_DEFECTO
    precarga = ((datos.get("hooks") or {}).get("on_startup") or {}).get("preload") or []
    precargados: list[str] = []
    for nombre in precarga:
        nombre = str(nombre).strip()
        real = nombre if nombre in ttl else alias.get(nombre)
        if nombre and real is not None:
            precargados.append(real)
    return Foto(
        ruta=ruta,
        version=version,
        modelos=modelos,
        grupos=MappingProxyType(grupos),
        alias=MappingProxyType(alias),
        _grupo_de=MappingProxyType(grupo_de),
        _ttl=MappingProxyType(ttl),
        _cmd=MappingProxyType(cmd),
        _precargados=tuple(precargados),
    )


_lecturas = 0


def lecturas() -> int:
    """Cuantas veces se ha leido una config del disco en este proceso (para los tests)."""
    return _lecturas


def leer(ruta: str | os.PathLike[str], *, version: int = 1) -> Foto | SinTopologia:
    """Lee una config de llama-swap. Nunca lanza: cualquier fallo es un `SinTopologia`."""
    return _leer(ruta, version)[0]


def _leer(ruta: str | os.PathLike[str], version: int) -> tuple[Foto | SinTopologia, bool]:
    """Como `leer`, y ademas si el fallo es pasajero (un `OSError` al abrir o leer el fichero,
    p. ej. una violacion de comparticion en Windows): ese no se debe cachear (REQ-033)."""
    global _lecturas
    if yaml is None:
        return SinTopologia(SIN_PYYAML, 'pip install "local-delegate-mcp[llamaswap]"'), False
    _lecturas += 1
    try:
        with Path(ruta).open(encoding="utf-8-sig") as f:
            datos = yaml.safe_load(f)
    except OSError as e:
        return SinTopologia(ILEGIBLE, f"{type(e).__name__}: {e}"), True
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        return SinTopologia(ILEGIBLE, f"{type(e).__name__}: {e}"), False
    return _interpretar(datos, str(ruta), version), False


def _interpretar(datos: Any, ruta: str, version: int) -> Foto | SinTopologia:
    if datos is None:
        datos = {}
    if not isinstance(datos, Mapping):
        return SinTopologia(ILEGIBLE, "la raiz del YAML no es un mapa")
    forma = _errores_de_forma(datos)
    if forma:
        return SinTopologia(NO_CUMPLE_LOAD_GO, "; ".join(forma))
    arriba, en_routing = _sintaxis(datos)
    if arriba and en_routing:
        return SinTopologia(DOS_SINTAXIS, "`groups`/`matrix` arriba y `routing.router` a la vez")
    if _usa_matrix(datos):
        return SinTopologia(MATRIX, "el router `matrix` no se reparte por grupos")
    errores = validar_como_load_go(datos)
    if errores:
        return SinTopologia(NO_CUMPLE_LOAD_GO, "; ".join(errores))
    return _construir(datos, ruta, version)


_cerrojo = threading.Lock()
_cache: tuple[tuple[str, int, int], Foto | SinTopologia] | None = None
_version = 0


def foto() -> Foto | SinTopologia:
    """La topologia de `LLAMASWAP_CONFIG`, leida en caliente y cacheada por (ruta, mtime, tamano).

    Cada relectura que cambia la clave sube `version` (REQ-009). Sin la variable, o si el fichero
    no se puede consultar o abrir (un `OSError` pasajero), no se cachea nada: la proxima llamada
    lo vuelve a intentar aunque la `mtime` no haya cambiado. Un YAML mal escrito si se cachea:
    no cambia hasta que cambie el fichero.
    """
    global _cache, _version
    ruta = config.llamaswap_config_path()
    if not ruta:
        return SinTopologia(SIN_CONFIG)
    if yaml is None:
        return SinTopologia(SIN_PYYAML, 'pip install "local-delegate-mcp[llamaswap]"')
    ruta = str(Path(ruta).expanduser())
    try:
        st = os.stat(ruta)
    except OSError as e:
        return SinTopologia(ILEGIBLE, f"{type(e).__name__}: {e}")
    clave = (ruta, st.st_mtime_ns, st.st_size)
    with _cerrojo:
        if _cache is not None and _cache[0] == clave:
            return _cache[1]
        resultado, pasajero = _leer(ruta, _version + 1)
        if pasajero:
            return resultado
        _version += 1
        _cache = (clave, resultado)
        return resultado


def _olvidar() -> None:
    """Vacia la cache de `foto()` (para los tests)."""
    global _cache
    with _cerrojo:
        _cache = None
