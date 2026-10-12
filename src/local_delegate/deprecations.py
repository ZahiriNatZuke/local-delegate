"""deprecations.py — registro único de nombres obsoletos (D1 del SDD english-names-bilingual-output).

Una sola tabla, `DEPRECATED_NAMES`, para todo nombre viejo que el paquete todavía reconoce:
subcomandos y opciones del CLI, variables de entorno, ficheros interruptor, ficheros que se siguen
escribiendo también con el nombre viejo (`legacy_write`) y nombres retirados.
La leen el CLI (aviso en `stderr`), `config` (variables), el check `config.deprecated_names` de
`doctor` y los tests de horizonte (`tests/test_deprecations.py`). Los hooks no importan el
paquete: llevan su copia mínima en `hook_common.py`, atada a esta por un test de igualdad.

Hay dos clases de entrada, y la regla es estricta:

- **Alias con sucesor** (`new` no es `None`, `kind` distinto de `retired`). El nombre viejo
  funciona con aviso en la versión que lo renombra (`introduced`) y en las dos menores siguientes,
  y se retira en la tercera: si se publica en 0.N, vive en 0.N, 0.N+1 y 0.N+2. Toda entrada nueva
  es de esta clase y nace con `introduced="UNRELEASED"`; `scripts/bump_version.py` cambia ese
  valor por la versión que se publica.
- **Nombre retirado sin sucesor** (`kind="retired"`, `new=None`). Ya **no** tiene efecto: el check
  solo avisa de que sigue puesto. Lleva siempre `warn_until`, la última serie menor en la que el
  check avisa de él (`"0.37.0"` cubre toda la 0.37.x), y el test de horizonte lo mide contra ella.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNRELEASED = "UNRELEASED"

KINDS = frozenset(
    {"cli_command", "cli_option", "env_var", "switch_file", "legacy_write", "retired"}
)
# Menores que vive un alias desde su versión de introducción (REQ-004): 0.N, 0.N+1 y 0.N+2.
ALIAS_MINOR_VERSIONS = 3


@dataclass(frozen=True)
class DeprecatedName:
    kind: str
    old: str
    new: str | None
    introduced: str
    warn_until: str | None = None
    # Lo lee también un hook instalado (`hook_common.py`), que lleva su propia copia.
    used_by_hooks: bool = False

    @property
    def is_retired(self) -> bool:
        return self.kind == "retired"


DEPRECATED_NAMES: tuple[DeprecatedName, ...] = (
    # El rol `fast`, retirado en la 0.30.0 (sección `[0.30.0]` del CHANGELOG). Antes lo cubría
    # `config.rol_retirado`; el check generalizado avisa igual y deja de hacerlo tras la 0.37.x.
    DeprecatedName("retired", "LOCAL_DELEGATE_MODEL_FAST", None, "0.30.0", "0.37.0"),
    DeprecatedName("retired", "LOCAL_DELEGATE_MAX_CHARS_FAST", None, "0.30.0", "0.37.0"),
    DeprecatedName("retired", "LOCAL_DELEGATE_FALLBACK_FAST", None, "0.30.0", "0.37.0"),
    # Ola A1: CLI y variables de entorno (REQ-001, REQ-002).
    DeprecatedName("cli_command", "recalcular-coste", "recompute-cost", "UNRELEASED"),
    DeprecatedName("cli_option", "--reiniciar-calibracion", "--reset-calibration", "UNRELEASED"),
    DeprecatedName(
        "env_var", "LD_HOOK_READ_BLOQUEAR", "LD_HOOK_READ_BLOCK", "UNRELEASED", used_by_hooks=True
    ),
    DeprecatedName(
        "env_var",
        "LD_HOOK_READ_INTERRUPTOR",
        "LD_HOOK_READ_SWITCH_FILE",
        "UNRELEASED",
        used_by_hooks=True,
    ),
    DeprecatedName(
        "env_var",
        "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO",
        "LOCAL_DELEGATE_STRUCTURED_SUMMARY",
        "UNRELEASED",
    ),
    DeprecatedName(
        "env_var", "LOCAL_DELEGATE_COSTE_RESPALDO", "LOCAL_DELEGATE_COST_FALLBACK", "UNRELEASED"
    ),
    # Ola A2: el fichero que apaga el bloqueo (REQ-012). Vive en `~/.claude/`; lo lee el hook.
    DeprecatedName(
        "switch_file",
        "local-delegate-bloqueo-apagado",
        "local-delegate-block-off",
        "UNRELEASED",
        used_by_hooks=True,
    ),
    # Ola A4: excepción de REQ-005. El daemon escribe también `enfriamiento.json` (claves viejas)
    # para que los hooks de versiones anteriores sigan viendo los modelos enfriados. Mientras esta
    # entrada exista, `cooldown.legacy_write_enabled()` es True; al retirarla, se deja de escribir.
    DeprecatedName("legacy_write", "enfriamiento.json", "cooldown.json", "UNRELEASED"),
)


def parse_version(version: str) -> tuple[int, int, int]:
    """`0.34.0` → `(0, 34, 0)`. Ignora sufijos de pre-release (`0.35.0rc1` → `(0, 35, 0)`)."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"versión no válida: {version!r}")
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def removal_version(entry: DeprecatedName) -> str | None:
    """Versión en la que el alias deja de existir: `introduced` + 3 menores.

    `None` mientras no se haya publicado (`UNRELEASED`) y para los retirados, que no tienen una
    retirada futura: ya no funcionan.
    """
    if entry.is_retired or entry.introduced == UNRELEASED:
        return None
    major, minor, _patch = parse_version(entry.introduced)
    return f"{major}.{minor + ALIAS_MINOR_VERSIONS}.0"


def overdue(version: str, entries: tuple[DeprecatedName, ...] = DEPRECATED_NAMES) -> list[str]:
    """Nombres que ya deberían haber salido del registro en `version` (el test de horizonte).

    Un alias vence al llegar a su versión de retirada; un retirado, al pasar de `warn_until`.
    """
    current = parse_version(version)
    late: list[str] = []
    for entry in entries:
        if entry.is_retired:
            # `warn_until="0.37.0"` cubre toda la serie 0.37.x: se compara hasta la menor.
            if entry.warn_until is None or current[:2] > parse_version(entry.warn_until)[:2]:
                late.append(entry.old)
            continue
        removal = removal_version(entry)
        if removal is not None and current >= parse_version(removal):
            late.append(entry.old)
    return late


def env_vars() -> tuple[DeprecatedName, ...]:
    """Variables de entorno obsoletas: alias con sucesor y retiradas."""
    return tuple(
        e for e in DEPRECATED_NAMES if e.kind == "env_var" or (e.is_retired and _looks_env(e.old))
    )


def switch_files() -> tuple[DeprecatedName, ...]:
    """Ficheros interruptor con nombre viejo, relativos a `~/.claude/`."""
    return tuple(e for e in DEPRECATED_NAMES if e.kind == "switch_file")


def hook_names() -> tuple[tuple[str, str, str | None], ...]:
    """El subconjunto que copian los hooks, en la forma de su tabla: `(kind, old, new)`."""
    return tuple((e.kind, e.old, e.new) for e in DEPRECATED_NAMES if e.used_by_hooks)


def find(old: str) -> DeprecatedName | None:
    return next((e for e in DEPRECATED_NAMES if e.old == old), None)


def warning_text(entry: DeprecatedName) -> str:
    """El aviso de un nombre obsoleto: nombra el viejo, el nuevo y la versión de retirada."""
    if entry.is_retired:
        return f"{entry.old} ya no tiene efecto desde la {entry.introduced}"
    removal = removal_version(entry)
    when = f"se retira en la {removal}" if removal else "se retirará tres versiones menores después"
    return f"{entry.old} está obsoleto: usa {entry.new} ({when})"


def _looks_env(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]+", name))
