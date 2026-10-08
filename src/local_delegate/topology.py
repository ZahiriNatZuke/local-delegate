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
Sin topologia (`NoTopology`) el daemon no usa turno y se comporta como hoy. Este modulo no conoce
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

from . import config, footprint

try:
    import yaml
except ImportError:  # pragma: no cover - depende del entorno de instalacion
    yaml = None  # type: ignore[assignment]

DEFAULT_GROUP = "(default)"
DEFAULT_TTL = -1  # MODEL_CONFIG_DEFAULT_TTL de v255: «usa globalTTL»

# Motivos de REQ-002 por los que no hay turno.
NO_CONFIG = "sin LLAMASWAP_CONFIG"
NO_PYYAML = "sin PyYAML"
UNREADABLE = "ilegible"
MATRIX = "matrix"
TWO_SYNTAXES = "dos sintaxis"
FAILS_LOAD_GO = "no cumple load.go"


@dataclass(frozen=True)
class NoTopology:
    """No hay topologia: el daemon no usa turno. `reason` es uno de los de REQ-002."""

    reason: str
    detail: str = field(default="", compare=False)


@dataclass(frozen=True)
class Group:
    swap: bool
    exclusive: bool
    persistent: bool
    members: tuple[str, ...]


def _bool(value: Any, default: bool) -> bool:
    return default if value is None else bool(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_map(value: Any) -> bool:
    return value is None or isinstance(value, Mapping)


def _is_list(value: Any) -> bool:
    return value is None or isinstance(value, list)


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _shape_errors(data: Mapping[str, Any]) -> list[str]:
    """Tipos que `load.go` no puede ni deserializar (un mapa escrito como lista o al reves).

    Va antes que todo lo demas: el resto del modulo da por buena esta forma. Lista vacia = la
    forma es la que espera el `Config` de v255. Una lista de `members` escrita como cadena se
    rechaza aunque en Python se pueda recorrer: Go no la convierte a `[]string`.
    """
    errors: list[str] = []
    models = data.get("models")
    if not _is_map(models):
        return ["`models` no es un mapa"]
    for mid, cfg in (models or {}).items():
        if not _is_map(cfg):
            errors.append(f"modelo {mid}: no es un mapa")
            continue
        cfg = cfg or {}
        if not _is_list(cfg.get("aliases")):
            errors.append(f"modelo {mid}: `aliases` no es una lista")
        elif any(not _is_scalar(a) for a in cfg.get("aliases") or []):
            errors.append(f"modelo {mid}: un alias no es un texto")
        if cfg.get("cmd") is not None and not _is_scalar(cfg.get("cmd")):
            errors.append(f"modelo {mid}: `cmd` no es un texto")
    group_blocks = [("groups", data.get("groups"))]
    routing = data.get("routing")
    if not _is_map(routing):
        errors.append("`routing` no es un mapa")
    else:
        router = (routing or {}).get("router")
        if not _is_map(router):
            errors.append("`routing.router` no es un mapa")
        else:
            router = router or {}
            if router.get("use") is not None and not isinstance(router.get("use"), str):
                errors.append("`routing.router.use` no es un texto")
            adjustments = router.get("settings")
            if not _is_map(adjustments):
                errors.append("`routing.router.settings` no es un mapa")
            else:
                groups = (adjustments or {}).get("groups")
                group_blocks.append(("routing.router.settings.groups", groups))
    for name, groups in group_blocks:
        if not _is_map(groups):
            errors.append(f"`{name}` no es un mapa")
            continue
        for gid, gcfg in (groups or {}).items():
            if not _is_map(gcfg):
                errors.append(f"grupo {gid}: no es un mapa")
                continue
            members = (gcfg or {}).get("members")
            if not _is_list(members):
                errors.append(f"grupo {gid}: `members` no es una lista")
            elif any(not _is_scalar(m) for m in members or []):
                errors.append(f"grupo {gid}: un miembro no es un texto")
    hooks = data.get("hooks")
    if not _is_map(hooks):
        errors.append("`hooks` no es un mapa")
    else:
        startup = (hooks or {}).get("on_startup")
        if not _is_map(startup):
            errors.append("`hooks.on_startup` no es un mapa")
        else:
            preload = (startup or {}).get("preload")
            if not _is_list(preload):
                errors.append("`hooks.on_startup.preload` no es una lista")
            elif any(not _is_scalar(p) for p in preload or []):
                errors.append("`hooks.on_startup.preload`: un elemento no es un texto")
    return errors


def _syntax(data: Mapping[str, Any]) -> tuple[bool, bool]:
    """(usa las claves de arriba, usa `routing.router`), con el mismo criterio que `load.go`."""
    above = data.get("matrix") is not None or bool(data.get("groups"))
    router = ((data.get("routing") or {}).get("router")) or {}
    adjustments = router.get("settings") or {}
    in_routing = (
        bool(router.get("use"))
        or adjustments.get("matrix") is not None
        or bool(adjustments.get("groups"))
    )
    return above, in_routing


def _raw_groups(data: Mapping[str, Any]) -> Mapping[str, Any]:
    above, _ = _syntax(data)
    if above:
        return data.get("groups") or {}
    router = ((data.get("routing") or {}).get("router")) or {}
    return (router.get("settings") or {}).get("groups") or {}


def _usa_matrix(data: Mapping[str, Any]) -> bool:
    above, _ = _syntax(data)
    if above:
        return data.get("matrix") is not None
    router = ((data.get("routing") or {}).get("router")) or {}
    return router.get("use") == "matrix"


def _alias(models: Mapping[str, Any]) -> dict[str, str]:
    alias: dict[str, str] = {}
    for mid, cfg in models.items():
        for name in (cfg or {}).get("aliases") or []:
            alias.setdefault(str(name), str(mid))
    return alias


def validate_like_load_go(data: Any) -> list[str]:
    """Lo que `load.go` de v255 rechazaria, para las reglas de REQ-033. Lista vacia = valida.

    Reglas: raiz y `models` son mapas; no las dos sintaxis a la vez; `routing.router.use` conocido;
    `globalTTL` entero >= 0; cada `ttl` entero y con TTL efectivo >= 0; alias sin repetir; cada
    miembro existe (id o alias), no se repite en su grupo y esta en un solo grupo.
    """
    if not isinstance(data, Mapping):
        return ["la raiz del YAML no es un mapa"]
    errors: list[str] = []
    models = data.get("models") or {}
    if not isinstance(models, Mapping):
        return ["`models` no es un mapa"]
    shape = _shape_errors(data)
    if shape:
        return shape
    above, in_routing = _syntax(data)
    if above and in_routing:
        errors.append("usa a la vez `groups`/`matrix` de arriba y `routing.router`")
    router = ((data.get("routing") or {}).get("router")) or {}
    use = router.get("use") or ""
    if not above and use not in ("", "group", "matrix"):
        errors.append(f"`routing.router.use` desconocido: {use!r} (validos: group, matrix)")
    if not above and use == "matrix" and (router.get("settings") or {}).get("matrix") is None:
        errors.append("`routing.router.use` es matrix pero no hay `routing.router.settings.matrix`")
    global_ttl = data.get("globalTTL", 0)
    if not _is_int(global_ttl) or global_ttl < 0:
        errors.append("`globalTTL` debe ser un entero >= 0")
        global_ttl = 0
    seen_aliases: dict[str, str] = {}
    for mid, cfg in models.items():
        cfg = cfg or {}
        if not isinstance(cfg, Mapping):
            errors.append(f"modelo {mid}: no es un mapa")
            continue
        ttl = cfg.get("ttl", DEFAULT_TTL)
        if not _is_int(ttl):
            errors.append(f"modelo {mid}: `ttl` debe ser un entero")
        elif (global_ttl if ttl == DEFAULT_TTL else ttl) < 0:
            errors.append(f"modelo {mid}: TTL no valido {ttl}")
        for name in cfg.get("aliases") or []:
            if name in seen_aliases:
                errors.append(f"alias repetido {name} en el modelo {mid}")
            seen_aliases[name] = str(mid)
    if _usa_matrix(data):
        return errors
    groups = _raw_groups(data)
    if not isinstance(groups, Mapping):
        return [*errors, "`groups` no es un mapa"]
    member_use: dict[str, str] = {}
    for gid, gcfg in groups.items():
        members = (gcfg or {}).get("members") or []
        in_group: set[str] = set()
        for member in members:
            member = str(member)
            if member in in_group:
                errors.append(f"miembro {member} repetido en el grupo {gid}")
            in_group.add(member)
            if member in member_use:
                errors.append(f"miembro {member} en dos grupos: {member_use[member]} y {gid}")
            member_use[member] = str(gid)
            if member not in models and member not in seen_aliases:
                errors.append(f"miembro {member} del grupo {gid} no es ningun modelo")
    return errors


@dataclass(frozen=True)
class Snapshot:
    """La topologia leida de una config en un momento dado. Inmutable."""

    path: str
    version: int
    models: tuple[str, ...]
    groups: Mapping[str, Group]
    alias: Mapping[str, str]
    _group_of: Mapping[str, str] = field(repr=False)
    _ttl: Mapping[str, int] = field(repr=False)
    _cmd: Mapping[str, str] = field(repr=False)
    _preloaded: tuple[str, ...] = field(repr=False)

    def resolve(self, model: str) -> str | None:
        """Id real de un id o alias (`RealModelName`); `None` si no esta en la config."""
        if model in self._ttl:
            return model
        return self.alias.get(model)

    def group(self, model: str) -> str | None:
        real = self.resolve(model)
        return None if real is None else self._group_of.get(real)

    def _evicts(self, goal: str, other: str) -> bool:
        """`other` sale en `EvictionFor(objetivo, [otro])`. Ids reales."""
        if goal == other:
            return False
        tg = self._group_of.get(goal)
        og = self._group_of.get(other)
        cfg_t = self.groups.get(tg) if tg is not None else None
        if cfg_t is None:
            return False
        if og == tg:
            return cfg_t.swap
        if cfg_t.exclusive:
            cfg_o = self.groups.get(og) if og is not None else None
            return not (cfg_o is not None and cfg_o.persistent)
        return False

    def clashes(self, a: str, b: str) -> bool:
        """Cargar uno desaloja al otro, en cualquiera de los dos sentidos (REQ-001)."""
        ra, rb = self.resolve(a), self.resolve(b)
        if ra is None or rb is None or ra == rb:
            return False
        return self._evicts(ra, rb) or self._evicts(rb, ra)

    def effective_ttl(self, model: str) -> int | None:
        real = self.resolve(model)
        return None if real is None else self._ttl[real]

    def cmd(self, model: str) -> str | None:
        """El `cmd` de un modelo (id o alias) tal como está en la config; `None` si no tiene."""
        real = self.resolve(model)
        return None if real is None else self._cmd.get(real)

    def mmproj(self, model: str) -> str | None:
        """Ruta del `--mmproj` del `cmd` (via `footprint.cmd_flags`), o `None`."""
        real = self.resolve(model)
        if real is None or not self._cmd.get(real):
            return None
        return footprint.cmd_flags(self._cmd[real]).get("mmproj")

    def preloaded(self) -> tuple[str, ...]:
        """`hooks.on_startup.preload` resuelto a ids reales, como lo limpia `load.go`."""
        return self._preloaded

    def residents(self) -> tuple[str, ...]:
        """Modelos con TTL efectivo 0: no se descargan nunca por TTL (REQ-023, REQ-029)."""
        return tuple(m for m in self.models if self._ttl[m] == 0)


def _build(data: Mapping[str, Any], path: str, version: int) -> Snapshot:
    cfg_models: Mapping[str, Any] = data.get("models") or {}
    models = tuple(str(m) for m in cfg_models)
    global_ttl = data.get("globalTTL", 0)
    ttl: dict[str, int] = {}
    cmd: dict[str, str] = {}
    for mid in models:
        cfg = cfg_models[mid] or {}
        value = cfg.get("ttl", DEFAULT_TTL)
        ttl[mid] = global_ttl if value == DEFAULT_TTL else value
        if cfg.get("cmd"):
            cmd[mid] = str(cfg["cmd"])
    alias = _alias(cfg_models)
    groups: dict[str, Group] = {}
    group_of: dict[str, str] = {}
    for gid, gcfg in _raw_groups(data).items():
        gcfg = gcfg or {}
        members = tuple(str(m) for m in gcfg.get("members") or [])
        groups[str(gid)] = Group(
            swap=_bool(gcfg.get("swap"), True),
            exclusive=_bool(gcfg.get("exclusive"), True),
            persistent=_bool(gcfg.get("persistent"), False),
            members=members,
        )
        for member in members:
            group_of[member] = str(gid)
    loose = tuple(sorted(m for m in models if m not in group_of))
    groups[DEFAULT_GROUP] = Group(swap=True, exclusive=True, persistent=False, members=loose)
    for member in loose:
        group_of[member] = DEFAULT_GROUP
    preload = ((data.get("hooks") or {}).get("on_startup") or {}).get("preload") or []
    preloaded: list[str] = []
    for name in preload:
        name = str(name).strip()
        real = name if name in ttl else alias.get(name)
        if name and real is not None:
            preloaded.append(real)
    return Snapshot(
        path=path,
        version=version,
        models=models,
        groups=MappingProxyType(groups),
        alias=MappingProxyType(alias),
        _group_of=MappingProxyType(group_of),
        _ttl=MappingProxyType(ttl),
        _cmd=MappingProxyType(cmd),
        _preloaded=tuple(preloaded),
    )


_reads = 0


def reads() -> int:
    """Cuantas veces se ha leido una config del disco en este proceso (para los tests)."""
    return _reads


def read(path: str | os.PathLike[str], *, version: int = 1) -> Snapshot | NoTopology:
    """Lee una config de llama-swap. Nunca lanza: cualquier fallo es un `NoTopology`."""
    return _read(path, version)[0]


def _read(path: str | os.PathLike[str], version: int) -> tuple[Snapshot | NoTopology, bool]:
    """Como `read`, y ademas si el fallo es pasajero (un `OSError` al abrir o leer el fichero,
    p. ej. una violacion de comparticion en Windows): ese no se debe cachear (REQ-033)."""
    global _reads
    if yaml is None:
        return NoTopology(NO_PYYAML, 'pip install "local-delegate-mcp[llamaswap]"'), False
    _reads += 1
    try:
        with Path(path).open(encoding="utf-8-sig") as f:
            data = yaml.safe_load(f)
    except OSError as e:
        return NoTopology(UNREADABLE, f"{type(e).__name__}: {e}"), True
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        return NoTopology(UNREADABLE, f"{type(e).__name__}: {e}"), False
    return _interpret(data, str(path), version), False


def _interpret(data: Any, path: str, version: int) -> Snapshot | NoTopology:
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        return NoTopology(UNREADABLE, "la raiz del YAML no es un mapa")
    shape = _shape_errors(data)
    if shape:
        return NoTopology(FAILS_LOAD_GO, "; ".join(shape))
    above, in_routing = _syntax(data)
    if above and in_routing:
        return NoTopology(TWO_SYNTAXES, "`groups`/`matrix` arriba y `routing.router` a la vez")
    if _usa_matrix(data):
        return NoTopology(MATRIX, "el router `matrix` no se reparte por grupos")
    errors = validate_like_load_go(data)
    if errors:
        return NoTopology(FAILS_LOAD_GO, "; ".join(errors))
    return _build(data, path, version)


_lock = threading.Lock()
_cache: tuple[tuple[str, int, int], Snapshot | NoTopology] | None = None
_version = 0


def snapshot() -> Snapshot | NoTopology:
    """La topologia de `LLAMASWAP_CONFIG`, leida en caliente y cacheada por (ruta, mtime, tamano).

    Cada relectura que cambia la clave sube `version` (REQ-009). Sin la variable, o si el fichero
    no se puede consultar o abrir (un `OSError` pasajero), no se cachea nada: la proxima llamada
    lo vuelve a intentar aunque la `mtime` no haya cambiado. Un YAML mal escrito si se cachea:
    no cambia hasta que cambie el fichero.
    """
    global _cache, _version
    path = config.llamaswap_config_path()
    if not path:
        return NoTopology(NO_CONFIG)
    if yaml is None:
        return NoTopology(NO_PYYAML, 'pip install "local-delegate-mcp[llamaswap]"')
    path = str(Path(path).expanduser())
    try:
        st = os.stat(path)
    except OSError as e:
        return NoTopology(UNREADABLE, f"{type(e).__name__}: {e}")
    key = (path, st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache is not None and _cache[0] == key:
            return _cache[1]
        result, transient = _read(path, _version + 1)
        if transient:
            return result
        _version += 1
        _cache = (key, result)
        return result


def _forget() -> None:
    """Vacia la cache de `foto()` (para los tests)."""
    global _cache
    with _lock:
        _cache = None


# Nombres públicos de las mismas funciones, para `residency` (T11), que edita la config con las
# mismas reglas que este lector: así no hay una segunda copia que se desincronice. Sin cambio de
# comportamiento.
shape_errors = _shape_errors
syntax = _syntax
usa_matrix = _usa_matrix
interpret = _interpret
