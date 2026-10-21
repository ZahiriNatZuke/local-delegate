"""deprecations.py — registro único de nombres obsoletos (D1 del SDD english-names-bilingual-output).

Una sola tabla, `DEPRECATED_NAMES`, para todo nombre viejo que el paquete todavía reconoce:
subcomandos y opciones del CLI, variables de entorno, ficheros interruptor y nombres retirados.
La leen el CLI (aviso en `stderr`), `config` (variables), el check `config.deprecated_names` de
`doctor` y los tests de horizonte (`tests/test_deprecations.py`). Los hooks no importan el
paquete: llevan su copia mínima en `hook_common.py`, atada a esta por un test de igualdad.

Hay tres clases de entrada, y la regla es estricta (`class_problems` la comprueba):

- **Alias con sucesor** (`kind` en `ALIAS_KINDS`, `new` no es `None`, sin `warn_until` ni
  `retired_from`). El nombre viejo funciona con aviso en la versión que lo renombra
  (`introduced`) y en las dos menores siguientes, y se retira en la tercera: si se publica en 0.N,
  vive en 0.N, 0.N+1 y 0.N+2. Toda entrada nueva es de esta clase y nace con
  `introduced="UNRELEASED"`; `scripts/bump_version.py` cambia ese valor por la versión que se
  publica.
- **Nombre retirado sin sucesor** (`kind="retired"`, `new=None`, sin `retired_from`). Ya **no**
  tiene efecto: el check solo avisa de que sigue puesto. Lleva siempre `warn_until`, la última
  serie menor en la que el check avisa de él (`"0.37.0"` cubre toda la 0.37.x), y el test de
  horizonte lo mide contra ella.
- **Nombre retirado con sucesor** (`kind="retired"`, `new` no es `None`, `retired_from` en
  `ALIAS_KINDS`). Era un alias y ya **no** tiene efecto: existe solo para avisar (y migrar) hasta
  la serie de `warn_until`, que es obligatorio y vence como el de un retirado. `retired_from` dice
  qué superficie tenía; con ella, `effective_kind` decide en qué lector sale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNRELEASED = "UNRELEASED"

# Superficies de un nombre: las de un alias y, para un retirado con sucesor, su `retired_from`.
ALIAS_KINDS = frozenset({"cli_command", "cli_option", "env_var", "switch_file"})
KINDS = ALIAS_KINDS | {"retired"}
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
    # Solo para un retirado con sucesor: la superficie que tenía cuando era alias.
    retired_from: str | None = None

    @property
    def is_retired(self) -> bool:
        return self.kind == "retired"


DEPRECATED_NAMES: tuple[DeprecatedName, ...] = (
    # Ola A1: CLI y variables de entorno (REQ-001, REQ-002).
    DeprecatedName("cli_command", "recalcular-coste", "recompute-cost", "0.35.0"),
    DeprecatedName("cli_option", "--reiniciar-calibracion", "--reset-calibration", "0.35.0"),
    DeprecatedName(
        "env_var", "LD_HOOK_READ_BLOQUEAR", "LD_HOOK_READ_BLOCK", "0.35.0", used_by_hooks=True
    ),
    DeprecatedName(
        "env_var",
        "LD_HOOK_READ_INTERRUPTOR",
        "LD_HOOK_READ_SWITCH_FILE",
        "0.35.0",
        used_by_hooks=True,
    ),
    DeprecatedName(
        "env_var",
        "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO",
        "LOCAL_DELEGATE_STRUCTURED_SUMMARY",
        "0.35.0",
    ),
    DeprecatedName(
        "env_var", "LOCAL_DELEGATE_COSTE_RESPALDO", "LOCAL_DELEGATE_COST_FALLBACK", "0.35.0"
    ),
    # Ola A2: el fichero que apaga el bloqueo (REQ-012). Vive en `~/.claude/`; lo lee el hook.
    DeprecatedName(
        "switch_file",
        "local-delegate-bloqueo-apagado",
        "local-delegate-block-off",
        "0.35.0",
        used_by_hooks=True,
    ),
)


def parse_version(version: str) -> tuple[int, int, int]:
    """`0.34.0` → `(0, 34, 0)`. Ignora sufijos de pre-release (`0.35.0rc1` → `(0, 35, 0)`)."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        # Sin prosa a propósito: es un error de programación (las versiones son constantes del
        # paquete) y este módulo no puede importar `i18n` (`config` lo importa, e `i18n` importa
        # `config`: sería un ciclo).
        raise ValueError(repr(version))
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


def effective_kind(entry: DeprecatedName) -> str:
    """La superficie de la entrada: `retired_from` para un retirado con sucesor, `kind` si no."""
    if entry.is_retired and entry.new is not None and entry.retired_from is not None:
        return entry.retired_from
    return entry.kind


def class_problems(entries: tuple[DeprecatedName, ...] = DEPRECATED_NAMES) -> list[str]:
    """Entradas que rompen la regla de su clase, como `"<old>: <regla>"` (vacía si todo cumple)."""
    problems: list[str] = []
    for e in entries:
        if e.kind not in KINDS:
            problems.append(f"{e.old}: kind")
        if e.introduced != UNRELEASED and not re.fullmatch(r"\d+\.\d+\.\d+", e.introduced):
            problems.append(f"{e.old}: introduced")
        if not e.is_retired:
            if not e.new:
                problems.append(f"{e.old}: alias_without_new")
            if e.warn_until is not None:
                problems.append(f"{e.old}: alias_with_warn_until")
            if e.retired_from is not None:
                problems.append(f"{e.old}: alias_with_retired_from")
            continue
        if not e.warn_until:
            problems.append(f"{e.old}: retired_without_warn_until")
        if e.new is None:
            if e.retired_from is not None:
                problems.append(f"{e.old}: retired_from_without_new")
        elif e.retired_from not in ALIAS_KINDS:
            problems.append(f"{e.old}: retired_from")
    return problems


def env_vars() -> tuple[DeprecatedName, ...]:
    """Variables de entorno obsoletas: alias y retiradas con sucesor cuya superficie es el entorno."""
    return tuple(e for e in DEPRECATED_NAMES if effective_kind(e) == "env_var")


def switch_files() -> tuple[DeprecatedName, ...]:
    """Ficheros interruptor con nombre viejo, relativos a `~/.claude/` (alias o retirados)."""
    return tuple(e for e in DEPRECATED_NAMES if effective_kind(e) == "switch_file")


def cli_entries() -> tuple[DeprecatedName, ...]:
    """Subcomandos y opciones del CLI con nombre viejo (alias o retirados)."""
    return tuple(e for e in DEPRECATED_NAMES if effective_kind(e) in ("cli_command", "cli_option"))


def hook_names() -> tuple[tuple[str, str, str | None], ...]:
    """El subconjunto que copian los hooks, en la forma de su tabla: `(kind, old, new)`."""
    return tuple((e.kind, e.old, e.new) for e in DEPRECATED_NAMES if e.used_by_hooks)


def find(old: str) -> DeprecatedName | None:
    return next((e for e in DEPRECATED_NAMES if e.old == old), None)
