"""update.py — `local-delegate update`: revisa, completa, actualiza y deja el daemon arriba.

Reparto de responsabilidades, que es lo que hace que este módulo sea corto:

- **Quién mira** es ``checks.run_all``. Aquí no hay ni un ``probe`` nuevo: el diagnóstico ya
  existe desde el change ``checks-andamiaje`` y duplicarlo sería tener dos definiciones de
  «estar a punto» que se separarían al primer cambio.
- **Quién arregla** es ``install.plan_install`` + ``install.apply``, que ya saben escribir de
  forma idempotente y con ``.bak``.
- **Lo que aporta este módulo** son las dos cosas que ``checks`` dejó deliberadamente fuera:
  decidir *qué* se repara (la tabla :data:`REPAIRS`) y controlar el ciclo de vida del daemon.

Tres reglas duras, todas por seguridad y ninguna negociable:

1. **``unknown`` no repara nunca.** Es la regla que trajo ``checks``: un cliente ausente, un
   fichero sin permisos o un JSON ilegible se reportan ``unknown``, y «arreglarlos» sería
   sobrescribir configuración ajena a ciegas.
2. **El pid sale solo de ``/api/daemon``.** No se lee ``daemon.json``. La forma más fuerte de
   no señalar a un pid reciclado no es leerlo y verificarlo: es no leerlo nunca.
3. **Con ``--home`` simulado no se toca ningún servicio.** El daemon y el backend no viven en
   el HOME, así que un flag documentado como «para pruebas» reiniciaría el daemon de verdad.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Collection
from dataclasses import dataclass
from importlib import (
    import_module,
    metadata,  # noqa: F401 -- tests double `update.metadata.Distribution`
)
from pathlib import Path

from . import (
    checks_plugin,
    claude_plugin,
    completion,
    config,
    deprecations,
    desktop_config,
    i18n,
    install,
    install_origin,
    install_state,
    plugin_migration,
    shell_profiles,
)
from .i18n import t

#: `checks` imports this module, inside two functions (`latest_version`, `upgrade_command`).
#: Resolved by name, like `install._sibling`, so the two modules do not import each other (CodeQL
#: `py/cyclic-import`); it is the same module object, so the tests double it as before.
checks = import_module(f"{__package__}.checks")

PACKAGE = install_origin.PACKAGE

# Nombres canónicos del servicio en cada sistema. Los mismos que documenta docs/wiki/Daemon.md:
# si estos tres strings y la wiki se separan, `update` buscará un servicio que nadie registró.
TASK_NAME = "LocalDelegateDaemon"  # Windows, tarea programada
LAUNCH_LABEL = "com.local-delegate.daemon"  # macOS, LaunchAgent
SYSTEMD_UNIT = "local-delegate.service"  # Linux, systemd --user

# Mecanismos de arranque, en el orden en que se prueban.
SCHTASKS = "schtasks"
LAUNCHCTL = "launchctl"
SYSTEMD = "systemd"
FALLBACK = "fallback"

#: Mecanismo → (clave del catálogo, nombre del servicio que va en el texto).
_MECHANISM_KEYS = {
    SCHTASKS: ("install.update.mechanism.schtasks", TASK_NAME),
    LAUNCHCTL: ("install.update.mechanism.launchctl", LAUNCH_LABEL),
    SYSTEMD: ("install.update.mechanism.systemd", SYSTEMD_UNIT),
    FALLBACK: ("install.update.mechanism.fallback", ""),
}


def mechanism_label(mechanism: str) -> str:
    """El mecanismo de arranque del daemon contado para una persona, en el idioma vigente."""
    key, name = _MECHANISM_KEYS[mechanism]
    return t(key, name=name)


# --- Ejecución de comandos, inyectable ---------------------------------------
def _default_runner(argv: list[str]) -> subprocess.CompletedProcess:
    """Ejecuta y captura. Nunca lanza: un binario ausente es un returncode, no una excepción."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, returncode=127, stdout="", stderr=str(exc))


Runner = Callable[[list[str]], subprocess.CompletedProcess]


@dataclass
class Options:
    """Lo que pidió el usuario, más los colaboradores que los tests doblan.

    Los colaboradores se declaran ``None`` y se resuelven en ``__post_init__`` en vez de poner
    la función directamente como valor por defecto. Escrito de la otra forma, un análisis
    estático lee ``Options.runner`` como un método y cuenta un ``self`` que en tiempo de
    ejecución no existe —el ``__init__`` del dataclass asigna el default a la instancia—, así
    que la llamada parece tener un argumento de más. Funciona igual, pero la ambigüedad es real
    y CodeQL la reporta como error: mejor no dejarla escrita.
    """

    home: Path
    dry_run: bool = False
    version: str | None = None
    restart_backend: bool = False
    no_restart: bool = False
    runner: Runner | None = None
    daemon_status: Callable[[str, int], dict | None] | None = None
    sleep: Callable[[float], None] | None = None
    clock: Callable[[], float] | None = None
    spawn: Callable[[list[str]], None] | None = None
    # Lo mismo que en `install.Options`: dónde va `language.json` y la regla del idioma (REQ-047).
    data_dir: Path | None = None
    language_probe: Callable | None = None
    # The Claude Code plugin delivery (SDD claude-plugin-and-mods, F1-update), injectable like in
    # `install.Options`: the `claude` runner and lookup, an `ld_bin` already resolved, the platform,
    # and where the Desktop config lives and which executable its bridge entry runs. `None` means
    # the real ones.
    claude_runner: Callable | None = None
    claude_which: Callable[[str], str | None] | None = None
    claude_ld_bin: object | None = None
    platform: str | None = None
    desktop_dir: Path | None = None
    desktop_executable: Path | None = None

    def __post_init__(self) -> None:
        if self.runner is None:
            self.runner = _default_runner
        if self.daemon_status is None:
            self.daemon_status = checks._default_daemon_status
        if self.sleep is None:
            self.sleep = time.sleep
        if self.clock is None:
            self.clock = time.monotonic

    @property
    def simulated_home(self) -> bool:
        """True si ``--home`` apunta fuera del HOME real: entonces no se toca ningún servicio.

        La regla vive en ``install`` desde el change ``install-checks-clients``, porque ahí la
        necesita también el instalador para no dejar que el binario ``claude`` escriba fuera del
        árbol simulado. Una sola definición, dos consumidores.
        """
        return install.is_simulated_home(self.home)


# Los checks que miran una entrada MCP. Se enumeran en dos sitios de este módulo —de qué modo
# es la máquina, y qué avisos se silencian—, y tenerlos escritos a mano en ambos es como se
# quedó fuera opencode del primero mientras entraba en el segundo.
_CHECKS_MCP = ("scaffold.mcp_claude", "scaffold.mcp_codex", "scaffold.mcp_opencode")

# --- La tabla de reparaciones -------------------------------------------------
# Marcador para `scaffold.memory`, que escribe en los clientes que existan en la máquina en vez
# de en un conjunto fijo: reinstalar el bloque de Codex en una máquina sin Codex crearía
# `~/.codex/AGENTS.md` de la nada.
PRESENT = "present"


@dataclass(frozen=True)
class Repair:
    """Qué acción de ``install`` arregla un check, y bajo qué estados se aplica."""

    check_id: str
    states: tuple[str, ...]
    components: frozenset[str]
    targets: frozenset[str] | str


# Los checks que no aparecen aquí —`cli.path`, `client.presence`, `client.observed`,
# `service.backend`, `service.credential`, `backend.llamaswap`, `backend.llamaserver`— no se
# reparan escribiendo en el HOME: de ellos se imprime su `fix_hint` y ya. `service.daemon` tampoco
# está: lo atiende el control del daemon. `client.observed` además no tiene arreglo posible:
# informa de con qué clientes se ha hablado, y eso no se configura desde aquí.
#
# `service.credential` está fuera por una razón distinta y deliberada: **sí** se sabría reparar
# —reinstalar la entrada MCP en modo `http`, que `_infer_mcp_mode` ya sabe elegir—, pero eso
# cambiaría el **modo de transporte** que el usuario configuró, y eso es una decisión suya, no un
# trozo de andamiaje roto que haya que reponer. Es el mismo criterio que deja fuera el `warn` de
# `scaffold.mcp_codex`: no se pisa configuración escrita por una persona. El aviso dice qué pasa y
# qué comando lo arregla; ejecutarlo es del usuario.
#
# `scaffold.shell_completion` is not listed either, and not because it is not repaired: its refresh
# is a step of its own (`plan_completion_refresh`), because a `Repair` only acts on clients that are
# present and completion belongs to no client; on a machine without clients it would never have
# been regenerated. Its «block deleted» or «file missing» `warn` is not restored by `update`: its
# `fix_hint` says so (`install --shell-completion`), because rewriting a profile is the user's call.
REPAIRS: tuple[Repair, ...] = (
    Repair(
        "scaffold.hook_files",
        # `warn` aquí significa «faltan scripts» o «son de otra versión»: los dos son nuestros y
        # están viejos. Sin repararlo en `warn`, actualizar el paquete dejaba los hooks de la
        # versión anterior para siempre, porque nada más en `update` los reescribe.
        (checks.MISSING, checks.WARN),
        frozenset({"hooks"}),
        frozenset({"claude"}),
    ),
    Repair(
        "scaffold.hook_settings",
        # `warn` aquí significa «hooks de una instalación anterior»: son nuestros y están
        # viejos, así que reinstalarlos es exactamente lo correcto.
        (checks.MISSING, checks.WARN),
        frozenset({"hooks"}),
        frozenset({"claude"}),
    ),
    Repair(
        "scaffold.hook_orphans",
        # `warn` aquí significa «scripts nuestros de una instalación anterior, sueltos en la raíz
        # de ~/.claude/hooks/». Son nuestros y sobran, igual que los otros dos casos que reparan
        # en `warn`. `plan_install` con components={"hooks"} emite la copia del árbol **y** el
        # retirado; la deduplicación por (kind, target) evita que se dupliquen si `hook_files`
        # también pide reparación.
        (checks.WARN,),
        frozenset({"hooks"}),
        frozenset({"claude"}),
    ),
    Repair(
        "scaffold.skill",
        # `warn` = el directorio existe sin SKILL.md. También es nuestro y está incompleto.
        (checks.MISSING, checks.WARN),
        frozenset({"skill"}),
        # `PRESENT` y no `{"claude"}`: la skill se escribe en dos clientes, y fijar uno dejaba la
        # de opencode sin reponer aunque el check la viera faltar. Que `PRESENT` incluya también
        # Codex es inocuo —`plan_install` no emite acción de skill para él, porque no tiene
        # skills—, y es el mismo marcador que ya usa `scaffold.memory` por la misma razón: no
        # crearle a nadie el directorio de un cliente que no tiene instalado.
        PRESENT,
    ),
    # `warn` = el bloque está pero no es el empaquetado (D12): por ejemplo, el de la 0.34.0, que
    # nombra la skill ya retirada. Lo que se reescribe es solo lo de entre los marcadores.
    Repair("scaffold.memory", (checks.MISSING, checks.WARN), frozenset({"memory"}), PRESENT),
    Repair("scaffold.mcp_claude", (checks.MISSING,), frozenset({"mcp"}), frozenset({"claude"})),
    # `scaffold.mcp_codex` NO repara en `warn`, y es la excepción que ordena toda la tabla: ese
    # aviso dice «entrada puesta a mano, sin marcadores», o sea configuración escrita por el
    # usuario. Pisarla sería el fallo contra el que existe la regla de `unknown`.
    Repair("scaffold.mcp_codex", (checks.MISSING,), frozenset({"mcp"}), frozenset({"codex"})),
    # opencode NO tiene un `warn` equivalente al de Codex, y no es un olvido: su entrada se
    # identifica por la clave `mcp["local-delegate"]` y no por marcadores —no escribimos ninguna
    # clave de primer nivel ajena al esquema; ver el porqué, y su letra pequeña por versión, en
    # `install._scan_jsonc` y alrededores—, así que no hay forma de distinguir la nuestra de
    # una escrita a mano. Es la misma situación que con Claude Code, y se trata igual: solo se
    # repone si falta.
    Repair("scaffold.mcp_opencode", (checks.MISSING,), frozenset({"mcp"}), frozenset({"opencode"})),
)


def install_options(opts: Options) -> install.Options:
    """Las opciones de `install` con las que `update` decide el idioma (REQ-047)."""
    return install.Options(
        home=opts.home,
        components=set(),
        targets=set(),
        python_exe=install.default_python(),
        data_dir=opts.data_dir,
        language_probe=opts.language_probe,
    )


def language_actions(opts: Options) -> list[install.Action]:
    """La acción que escribe `language.json` con el idioma de esta sesión, si hay que escribirlo.

    Solo cuando escribe: lo que `install` cuenta sin escribir («ya guardado», «se conserva») aquí
    sería una acción en cada pasada, y `update` dejaría de poder decir «nada que reparar».
    """
    plan = install.plan_language(install_options(opts))
    action = install.language_action(plan) if plan.write is not None else None
    return [action] if action is not None else []


def _present_targets(home: Path) -> set[str]:
    """Clientes que existen en esta máquina. La definición vive en ``install`` (ver arriba)."""
    return install.present_targets(home)


def _infer_mcp_mode(results: list[tuple[checks.Check, checks.Result]]) -> str:
    """Modo de la entrada MCP que hay que escribir cuando falta en un cliente.

    ``update`` no tiene flag para elegirlo (la spec fija cinco y ninguna es esta), así que se
    deduce de lo que la máquina ya usa: si la entrada del otro cliente es HTTP, o si el daemon
    responde, la máquina trabaja contra el daemon. Si no hay ninguna señal, ``stdio``, que es
    el default de ``install`` y el modo que no depende de un servicio.
    """
    for check, result in results:
        if (
            check.id in _CHECKS_MCP
            and result.status == checks.OK
            # `remote` es como opencode llama a lo que los otros dos llaman `http`.
            and ("http" in result.detail or "remote" in result.detail)
        ):
            return "http"
    for check, result in results:
        if check.id == "service.daemon" and result.status in (checks.OK, checks.WARN):
            return "http"
    return "stdio"


def plan_repairs(
    results: list[tuple[checks.Check, checks.Result]],
    opts: Options,
    *,
    migrated: Collection[deprecations.DeprecatedName] = (),
) -> tuple[list[install.Action], list[str]]:
    """(acciones a ejecutar, avisos de lo que no se repara solo).

    Solo lee: no escribe en disco ni sale a la red. La idempotencia sale de aquí sin programarla — si la pasada
    anterior arregló todo, los probes responden ``ok``, ningún ``Repair`` casa y la lista de
    acciones queda vacía.
    """
    by_id = {check.id: result for check, result in results}
    mcp_mode = _infer_mcp_mode(results)
    present = _present_targets(opts.home)
    delivery = plan_claude_delivery(by_id, opts, present)

    actions: list[install.Action] = list(delivery.actions)
    for repair in REPAIRS:
        if delivery.skip_settings_hooks and repair.check_id in SETTINGS_HOOK_CHECKS:
            # With the plugin (or moving to it) these repairs would register our hooks in
            # `settings.json` again, next to the plugin's: every event would run twice (REQ-010).
            continue
        result = by_id.get(repair.check_id)
        if result is None or result.status not in repair.states:
            continue
        targets = present if repair.targets is PRESENT else set(repair.targets) & present
        if not targets:
            continue
        # Una llamada por par (componente, target): `plan_install` es puro y barato, y así
        # reparar Codex no arrastra a Claude.
        for target in sorted(targets):
            actions.extend(
                install.plan_install(
                    repair_install_options(
                        opts,
                        components=repair.components,
                        targets={target},
                        mcp_mode=mcp_mode,
                        # Reponer los hooks reescribe su registro, y `merge_hook_settings` retira
                        # antes todas nuestras entradas: sin esto, el hook de lectura desaparecía
                        # al actualizar y el bloqueo se apagaba sin que nadie lo pidiera.
                        enable_read_hook=install.read_hook_registered(opts.home / ".claude"),
                    )
                )
            )

    # Los subagentes con nuestro bloque de catálogo ya puesto (D12). No es un check, porque
    # `doctor` no mira `~/.claude/agents`, pero se informa como una reparación más: solo se
    # reescribe lo de entre los marcadores y solo si no es el catálogo empaquetado.
    if "claude" in present:
        language = install.plan_language(install_options(opts))
        actions.extend(install.plan_catalog_refresh(opts.home, language.lang))

    # Deduplicación por (kind, target), y no es cosmética: `plan_install` con
    # components={"hooks"} emite DOS acciones —copiar el árbol y registrar en settings.json— y
    # `_copy_tree_action` hace `shutil.rmtree(dst)` antes de copiar. Con `hook_files` y
    # `hook_settings` los dos en `missing` se planificarían dos borrados del mismo directorio.
    unique: list[install.Action] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        key = (action.kind, str(action.target))
        if key not in seen:
            seen.add(key)
            unique.append(action)

    notes = []
    for check, result in results:
        hint = result.fix_hint
        if check.id == DEPRECATED_NAMES_CHECK:
            hint = without_migrated_renames(hint, migrated)
        if (
            hint
            and check.id not in {r.check_id for r in REPAIRS}
            and check.id not in delivery.handled
            # «Run `update`» said from `update`: `plan_completion_refresh` takes care of it.
            and hint != checks.SHELL_COMPLETION_UPDATE_HINT
        ):
            notes.append(f"{check.title}: {hint}")
    notes.extend(delivery.notes)
    return unique, notes


def repair_install_options(
    opts: Options, *, components: Collection[str], targets: Collection[str], **overrides
) -> install.Options:
    """The `install` options of a repair: what `update` knows, plus ``overrides``."""
    values: dict = {
        "home": opts.home,
        "components": set(components),
        "targets": set(targets),
        "python_exe": install.default_python(),
        # Con un HOME simulado hay que escribir el fichero a mano: el camino por CLI (`claude mcp
        # add-json --scope user`) escribe SIEMPRE en el `~/.claude.json` del usuario real,
        # ignorando `home`. Se descubrió ejecutando `update --home <tmp>` dos veces: la segunda
        # pasada volvía a planificar la misma acción —el probe seguía viendo el árbol simulado
        # vacío— mientras la config de verdad sí se había reescrito.
        "use_cli": not opts.simulated_home,
        # La preferencia de idioma la escribe `run_update` una sola vez.
        "write_language": False,
        # La migración de nombres retirados la hace `run_update` antes (REQ-014).
        "migrate_retired_names": False,
        "data_dir": opts.data_dir,
        "language_probe": opts.language_probe,
        "claude_runner": opts.claude_runner,
        "claude_which": opts.claude_which,
        "claude_ld_bin": opts.claude_ld_bin,
        "platform": opts.platform,
        "desktop_dir": opts.desktop_dir,
        "desktop_executable": opts.desktop_executable,
    }
    if install_state.delivery_explicit(install_state.load(opts.home, opts.data_dir)):
        # `install --claude-delivery settings` was a choice: the repairs keep it, and so does
        # the migration of REQ-008 a, which `decide` turns down with this very option.
        values["claude_delivery"] = claude_plugin.SETTINGS
    values.update(overrides)
    return install.Options(**values)


# --- Claude Code by plugin (SDD claude-plugin-and-mods, F1-update) ---------------------------
#
# `update` repeats no step of the plugin delivery: the migration and the reinstall are the very
# action `install` plans (`install._plugin_delivery_action`, which runs the migration of
# `plugin_migration`), and the removal of duplicates is `plugin_migration.remove_settings_hooks`.
# What lives here is the decision of which one runs, and the two commands only `update` needs:
# `claude plugin marketplace update` and `claude plugin update`.

#: The checks whose repair is the settings delivery of the hooks (`plan_install` with
#: `components={"hooks"}`). Never planned while Claude Code gets the plugin (REQ-010).
SETTINGS_HOOK_CHECKS = frozenset(
    {"scaffold.hook_files", "scaffold.hook_settings", "scaffold.hook_orphans"}
)
#: The plugin checks `update` answers for; their `fix_hint` («run update») is not repeated.
PLUGIN_CHECKS = frozenset({"plugin.installed", "plugin.ld_bin", "hooks.duplicates"})


@dataclass(frozen=True)
class DeliveryPlan:
    """What `update` does about the Claude Code delivery, before the rest of the repairs."""

    actions: tuple[install.Action, ...] = ()
    #: Check ids whose `fix_hint` this plan answers, so it is not printed as a note.
    handled: frozenset[str] = frozenset()
    #: True with the plugin in (or about to be): the settings hook repairs are skipped.
    skip_settings_hooks: bool = False
    notes: tuple[str, ...] = ()


def _status(by_id: dict, check_id: str) -> str | None:
    result = by_id.get(check_id)
    return result.status if result is not None else None


def _session_language(opts: Options) -> str:
    """The language `install` would give the plugin (`--config language=…`)."""
    return install.plan_language(install_options(opts)).lang


def plan_claude_delivery(by_id: dict, opts: Options, present: Collection[str]) -> DeliveryPlan:
    """REQ-008 a and REQ-010. Only reads (and asks `claude --version` when it has to decide).

    - The plugin is the delivery (the state says so, or `settings.json` has it enabled, the
      downgrade case of REQ-008 c): `_plan_plugin`.
    - A settings install that meets REQ-005: the migration `install` would run, unless the
      state says the user chose settings (`repair_install_options` passes that choice on).
    - Anything else: nothing, and the settings repairs stay as they were.

    An unreadable `settings.json` plans nothing: `unknown` never repairs.
    """
    if "claude" not in present:
        return DeliveryPlan()
    claude_dir = opts.home / ".claude"
    settings, reason = checks.read_json(claude_dir / "settings.json")
    if reason:
        return DeliveryPlan()
    recorded = install_state.delivery(install_state.load(opts.home, opts.data_dir))
    if recorded == claude_plugin.PLUGIN or checks_plugin.plugin_enabled(settings):
        return _plan_plugin(
            by_id, opts, settings, claude_dir, recorded=recorded == claude_plugin.PLUGIN
        )
    return _plan_migration(by_id, opts, settings, claude_dir)


def _plugin_decision(opts: Options):
    """`(install options, decision)`: the same `claude_plugin.decide` that `install` runs."""
    install_opts = repair_install_options(opts, components={"hooks"}, targets={"claude"})
    return install_opts, install.claude_delivery_decision(install_opts)


def _plan_migration(
    by_id: dict, opts: Options, settings: dict | None, claude_dir: Path
) -> DeliveryPlan:
    hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
    ours = checks_plugin.our_settings_hooks(settings, hooks_dir)
    failing = any(
        _status(by_id, check_id) in (checks.MISSING, checks.WARN)
        for check_id in SETTINGS_HOOK_CHECKS
    )
    if not ours and not failing:
        return DeliveryPlan()
    install_opts, decision = _plugin_decision(opts)
    if decision.delivery != claude_plugin.PLUGIN:
        # Settings as until 0.39: the repairs of `REPAIRS` take care of it.
        return DeliveryPlan()
    action = install._plugin_delivery_action(install_opts, decision, _session_language(opts))
    return DeliveryPlan(
        (_with_restart(action),),
        handled=SETTINGS_HOOK_CHECKS,
        skip_settings_hooks=True,
        notes=(t("plugin_update.migration"),),
    )


def _plan_plugin(
    by_id: dict, opts: Options, settings: dict | None, claude_dir: Path, *, recorded: bool
) -> DeliveryPlan:
    installed = _status(by_id, "plugin.installed")
    listed = installed in (checks.OK, checks.WARN)
    language = checks_plugin.plugin_options(settings).get("language")
    lang = _session_language(opts)
    reinstall = (
        installed == checks.MISSING
        or (listed and isinstance(language, str) and language != lang)
        or _status(by_id, "plugin.ld_bin") in (checks.MISSING, checks.WARN)
        # Enabled in `settings.json` without a state that says so (a downgrade without
        # `uninstall`): the reinstall records the delivery, and retires the duplicates with it.
        or (listed and not recorded)
    )
    refresh = installed == checks.WARN

    actions: list[install.Action] = []
    notes: list[str] = []
    reinstalled = False
    if reinstall or refresh:
        install_opts, decision = _plugin_decision(opts)
        if decision.delivery != claude_plugin.PLUGIN:
            notes.append(t("plugin_update.cannot_repair", warning=decision.warning or ""))
        else:
            if refresh:
                actions.extend(_refresh_actions(opts, decision))
            if reinstall:
                actions.append(install._plugin_delivery_action(install_opts, decision, lang))
                reinstalled = True
            actions[-1] = _with_restart(actions[-1])

    hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
    leftovers = checks_plugin.our_settings_hooks(settings, hooks_dir) or hooks_dir.exists()
    if leftovers and not reinstalled:
        # The reinstall already removes them; without it, only the removal runs.
        actions.append(_retire_action(claude_dir))
    if install.orphan_hook_scripts(claude_dir):
        actions.append(install._prune_orphans_action(claude_dir))
    return DeliveryPlan(
        tuple(actions),
        handled=SETTINGS_HOOK_CHECKS | PLUGIN_CHECKS,
        skip_settings_hooks=True,
        notes=tuple(notes),
    )


def _with_restart(action: install.Action) -> install.Action:
    """The same action, saying after it ran that open sessions need a restart (REQ-008 a)."""
    inner = action.run

    def _run() -> str:
        result = inner() if callable(inner) else None
        restart = t("plugin_update.restart_sessions")
        return f"{result}\n    {restart}" if result else restart

    return install.Action(action.kind, action.target, action.detail, _run, literal=action.literal)


def _refresh_actions(opts: Options, decision) -> list[install.Action]:
    """REQ-010: `claude plugin marketplace update`, then `claude plugin update`, in that order."""
    from .version import get_version

    runner = opts.claude_runner or claude_plugin.run_subprocess
    claude_bin = decision.claude_bin
    name, plugin = claude_plugin.MARKETPLACE_NAME, claude_plugin.PLUGIN_ID
    steps = (
        (
            "marketplace",
            [claude_bin, "plugin", "marketplace", "update", name],
            t("plugin_update.marketplace_plan", name=name),
            t("plugin_update.marketplace_done", name=name),
        ),
        (
            "plugin",
            [claude_bin, "plugin", "update", plugin],
            t("plugin_update.update_plan", plugin=plugin, version=get_version()),
            t("plugin_update.update_done", plugin=plugin),
        ),
    )
    prefix = " ".join(f"{key}={value}" for key, value in (decision.env or {}).items())
    actions = []
    for kind, argv, plan, done in steps:
        shown = claude_plugin._display(argv)

        def _run(argv=argv, done=done, shown=shown) -> str:
            result = runner(argv, decision.env)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip() or str(result.returncode)
                raise RuntimeError(t("plugin_update.step_failed", command=shown, detail=detail))
            return done

        literal = f"{prefix} {shown}" if prefix else shown
        # The target tells the two apart: `plan_repairs` deduplicates by `(kind, target)`.
        actions.append(install.Action(kind, f"claude {argv[2]}", plan, _run, literal=literal))
    return actions


def _retire_action(claude_dir: Path) -> install.Action:
    """Our hooks out of `settings.json` and their folder away: the plugin runs them (REQ-010)."""
    hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR

    def _run() -> str:
        removed = plugin_migration.remove_settings_hooks(claude_dir)
        return t("plugin_update.retire_done", n=i18n.format_number(removed), path=hooks_dir)

    detail = t("plugin_update.retire_plan", plugin=claude_plugin.PLUGIN_ID, path=hooks_dir)
    return install.Action("retire", claude_dir / "settings.json", detail, _run)


def plan_desktop_bridge(opts: Options) -> list[install.Action]:
    """REQ-012: the bridge entry `install --desktop` wrote follows the executable when it moves.

    Only an entry the state records and that still has the bridge's shape: a foreign or edited one
    is the user's, and one already pointing at this executable needs nothing. The write is
    `install`'s own Desktop action.
    """
    state = install_state.load(opts.home, opts.data_dir)
    if install_state.piece(state, "desktop_entry") is None:
        return []
    install_opts = repair_install_options(opts, components=(), targets=())
    path = install.desktop_config_path(install_opts)
    try:
        data = desktop_config._load(path)
    except desktop_config.DesktopConfigError:
        return []
    current = ((data or {}).get("mcpServers") or {}).get(desktop_config.ENTRY_KEY)
    executable = install.desktop_executable(install_opts)
    if not desktop_config.is_bridge_entry(current) or not executable.is_file():
        return []
    if current == desktop_config.bridge_entry(executable):
        return []
    return [install._desktop_action(install_opts)]


#: El check cuya pista pide «renombra» los nombres viejos (REQ-012).
DEPRECATED_NAMES_CHECK = "config.deprecated_names"


def without_migrated_renames(hint: str, migrated: Collection[deprecations.DeprecatedName]) -> str:
    """La pista del check sin el «renombra» que la migración de esta corrida cubre (REQ-014).

    Solo lo de `settings.json` y el interruptor, que es lo que se migra: si el nombre está además
    puesto en la **shell** (que no se migra), su pista se conserva.
    """
    in_shell = {name for name, value in config.DEPRECATED_ENV_VALUES.items() if value is not None}
    covered = {
        t("doctor.probe.deprecated_names.rename", old=e.old, new=e.new)
        for e in migrated
        if e.old not in in_shell
    }
    if not covered:
        return hint
    return "; ".join(part for part in hint.split("; ") if part not in covered)


def plan_completion_refresh(opts: Options) -> list[install.Action]:
    """Regenerates the listed completion files that are stale (REQ-034).

    In the **configured** language (the one of `plan_language`, like `plan_catalog_refresh`), so
    it handles a new version and also a language change; the manifest then states that language
    and the installed version. A step of its own, outside `REPAIRS`: `run_update` always calls it,
    whether or not there are clients on the machine. A listed file that is missing or unreadable is
    left alone (the `doctor` check sends it to `install --shell-completion`), no unlisted files are
    created and no profiles are touched, and without a manifest (or with an unreadable one) there
    is nothing to do. It only reads: `install.apply` writes.

    It lives here and not in `completion`: there it would have to import `install` and
    `shell_profiles`, which import `completion`, and CodeQL flags that cycle (`py/cyclic-import`).
    """
    from .version import get_version

    lang = install.plan_language(install_options(opts)).lang
    directory = shell_profiles.completion_dir(opts.home, opts.data_dir)
    try:
        manifest = completion.read_manifest(directory)
    except completion.ManifestUnreadableError:
        return []
    if not manifest:
        return []
    actions: list[install.Action] = []
    for entry in manifest["shells"]:
        path = Path(entry["file"])
        try:
            current = path.read_bytes()
        except OSError:
            continue
        content = completion.render(entry["shell"], lang=lang).encode("utf-8")
        if current != content:
            detail = t("install.completion.refresh_plan", shell=entry["shell"], lang=lang)
            actions.append(install._owned_file_action("completion", path, content, detail))
    updated = {**manifest, "lang": lang, "generator": get_version()}
    if updated != manifest:
        text = completion.manifest_bytes(updated)
        detail = t("install.completion.manifest_plan")
        path = completion.manifest_path(directory)
        literal = text.decode("utf-8")
        actions.append(install._owned_file_action("manifest", path, text, detail, literal=literal))
    return actions


# --- El pin de versión (paridad con el bash) ----------------------------------
def latest_version(timeout: float = 30.0) -> tuple[str | None, str | None]:
    """(última versión publicada, motivo si no se pudo saber).

    Se consulta el **índice simple** y no ``/pypi/<pkg>/json``: ese endpoint se sirve con
    caché y puede tardar en reflejar una release recién publicada — se vio en vivo con la
    0.12.0. Portado tal cual del bash, incluido el porqué.

    Medido el 2026-07-30, por si alguien vuelve a proponer el cambio: el índice simple responde
    con ``cache-control: max-age=600`` y el JSON con ``max-age=900``. O sea que el que ya se usa
    es **el más fresco de los dos**, y cambiar de endpoint empeoraría el síntoma en vez de
    arreglarlo. Los dos se sirven con caché; ninguno da un header ``Age`` con el que saber si lo
    servido está desfasado, y de ahí que la salida de ``update`` lo diga en vez de adivinarlo.
    """
    request = urllib.request.Request(
        f"https://pypi.org/simple/{PACKAGE}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, t("install.update.pypi_unreachable", reason=exc)

    versions = [v for v in data.get("versions", []) if re.fullmatch(r"\d+(\.\d+)*", v)]
    if not versions:
        return None, t("install.update.pypi_no_versions")
    # Ordena por número y no alfabéticamente: "0.9.0" es MENOR que "0.11.0".
    return max(versions, key=lambda v: [int(p) for p in re.findall(r"\d+", v)]), None


def pypi_source() -> str:
    """De dónde sale la «última versión publicada», y que puede ir con retraso."""
    return t("install.update.pypi_source")


def version_lines(version: str | None, reason: str | None, *, from_user: bool) -> list[str]:
    """Las líneas que `update` imprime sobre la versión, con su procedencia.

    Antes esto era un ``if/else`` de dos ramas que decía *«Última versión publicada: X»* incluso
    cuando la X la había escrito el usuario en ``--version``: el mensaje afirmaba algo que nadie
    había comprobado.

    Y añade el aviso que da nombre a este cambio. Justo después de publicar, ``update`` anuncia
    como «última» la **anterior**, y el usuario no tiene forma de saber si es que PyPI todavía
    sirve caché o si la publicación no terminó. No se puede distinguir desde aquí — pero sí se
    puede detectar la **firma** del caso, que es exacta y no una heurística: al publicar la
    0.17.0 desde el repo, la instalación local **es** 0.17.0 y PyPI todavía dice 0.16.0. O sea,
    la instalada más nueva que la publicada.
    """
    if from_user:
        return [t("install.update.version_requested", version=version)]
    if version is None:
        # Sin red no se puede resolver el pin, pero completar y reiniciar sí se puede: se avisa
        # y se sigue. No es un error (edge case de la spec).
        return [t("install.update.version_unknown", reason=reason)]

    lines = [t("install.update.version_latest", version=version, source=pypi_source())]
    installed = checks._installed_version()
    # `_compare_versions` devuelve None si alguna no es comparable; ahí se calla en vez de
    # inventarse un aviso, que es la misma regla que gobierna todo el registro de checks.
    if installed and checks._compare_versions(installed, version) == 1:
        lines += [
            t("install.update.newer_installed", installed=installed),
            t("install.update.newer_installed_why"),
            t("install.update.newer_installed_hint", installed=installed),
        ]
    return lines


_PIN_RE = re.compile(re.escape(PACKAGE) + r"==[\d.]+")
#: Valor de máquina de `current_pin` para una entrada sin `==` (antes `sin-pin`).
UNPINNED = "unpinned"


def _claude_entry_args(data: dict) -> list | None:
    """The ``args`` of our user-scope entry in `~/.claude.json`, or None if there are none."""
    servers = data.get("mcpServers")
    entry = servers.get(install.SERVER_NAME) if isinstance(servers, dict) else None
    args = entry.get("args") if isinstance(entry, dict) else None
    return args if isinstance(args, list) else None


def _entry_text(path: Path) -> str | None:
    """Only the text of our entry: the pin is looked for there and nowhere else.

    Searching the whole file found `local-delegate-mcp==…` in other projects' entries or in the
    history of `~/.claude.json`, and the substitution rewrote those too.
    """
    if path.name == ".claude.json":
        args = _claude_entry_args(install._read_json(path))
        return None if args is None else "\n".join(a for a in args if isinstance(a, str))
    text, _reason = checks.read_text(path)
    section = install._CODEX_SECTION_RE.search(text) if text else None
    return section.group(0) if section else None


def current_pin(path: Path) -> str | None:
    """Versión fijada en nuestra entrada, ``UNPINNED`` si está la entrada sin ``==``, o None."""
    text = _entry_text(path)
    if text is None or PACKAGE not in text:
        return None
    match = re.search(re.escape(PACKAGE) + r"==([\d.]+)", text)
    return match.group(1) if match else UNPINNED


def _set_pin_in_claude_json(path: Path, pin: str) -> bool:
    """Changes the pin only in ``mcpServers.local-delegate.args``, through JSON and atomically.

    An unreadable file (not UTF-8, not JSON, cannot be opened) raises `UnreadableConfigError` and
    is left untouched; before, it was rewritten as ``""`` and `~/.claude.json` ended up empty.
    """

    def _change_pin(data: dict) -> tuple[dict, bool]:
        args = _claude_entry_args(data)
        if args is None:
            return data, False
        updated = [_PIN_RE.sub(pin, a) if isinstance(a, str) else a for a in args]
        if updated == args:
            return data, False
        args[:] = updated
        return data, True

    return install.update_config_json(path, _change_pin)


def _set_pin_in_codex_toml(path: Path, pin: str) -> bool:
    """Changes the pin only inside ``[mcp_servers.local-delegate]``; the rest, byte for byte.

    Strict UTF-8 reading: a comment in cp1252 used to be saved back as U+FFFD without a word.
    """
    text = install._read_text_for_rewrite(path)
    section = install._CODEX_SECTION_RE.search(text)
    if section is None:
        return False
    body = _PIN_RE.sub(pin, section.group(0))
    if body == section.group(0):
        return False
    # `install._write_text` deja `.bak`, conserva el terminador de línea y el BOM del fichero.
    install._write_text(path, text[: section.start()] + body + text[section.end() :])
    return True


def plan_pin(opts: Options, version: str) -> list[install.Action]:
    """Acciones que cambian el pin donde exista. Sin pin no hay nada que cambiar."""
    actions: list[install.Action] = []
    pin = f"{PACKAGE}=={version}"
    for path in (opts.home / ".claude.json", opts.home / ".codex" / "config.toml"):
        current = current_pin(path)
        if current is None or current == UNPINNED or current == version:
            continue
        rewrite_pin = (
            _set_pin_in_claude_json if path.name == ".claude.json" else _set_pin_in_codex_toml
        )

        def _run(path=path, current=current, rewrite_pin=rewrite_pin) -> str:
            if not rewrite_pin(path, pin):
                return t("install.update.pin_missing", name=path.name)
            return t("install.update.pin_done", current=current, version=version, name=path.name)

        plan = t("install.update.pin_plan", pin=pin)
        actions.append(install.Action("pin", path, plan, _run))
    return actions


# --- Cómo está instalado esto -------------------------------------------------
# Lives in the leaf module `install_origin` (no import cycle through `checks`); re-exported here.
EDITABLE = install_origin.EDITABLE
UV_TOOL = install_origin.UV_TOOL
OTHER = install_origin.OTHER


def editable_origin() -> Path | None:
    """`install_origin.editable_origin`: the folder an editable install serves from, or None."""
    return install_origin.editable_origin()


UV_TOOL_UPGRADE = f"uv tool upgrade {PACKAGE}"


def generic_upgrade() -> str:
    """El consejo de actualizar cuando no se sabe con qué gestor se instaló."""
    return t("install.update.generic_upgrade", package=PACKAGE)


def install_kind() -> str:
    """How the running package is installed (`install_origin.install_kind`).

    It passes this module's `editable_origin`, looked up when called, so doubling
    `update.editable_origin` still changes the answer.
    """
    return install_origin.install_kind(editable=editable_origin)


def upgrade_command() -> str:
    """El comando que actualiza **esta** instalación, o el genérico si no se reconoce."""
    kind = install_kind()
    if kind == EDITABLE:
        origin = editable_origin()
        return f"git -C {origin} pull && uv sync --project {origin}"
    return UV_TOOL_UPGRADE if kind == UV_TOOL else generic_upgrade()


def uv_tool_lines(version: str | None) -> list[str]:
    """Aviso de que el CLI de ``uv tool`` se queda atrás, y qué hacer.

    ``update`` actualiza el pin, el andamiaje y el daemon, pero **no** el ejecutable de
    ``uv tool``: son dos pasos donde el usuario espera uno y el segundo no lo decía nadie.

    Y no lo ejecuta él a propósito. Probado en Windows el 2026-07-30 con un paquete de prueba:
    ``uv tool install <pkg>@latest --force`` lanzado desde el Python de ese mismo entorno falla
    con ``Acceso denegado`` al borrar ``Scripts/`` —el proceso lo tiene bloqueado— pero **ya ha
    borrado el paquete**, así que deja la instalación destruida: ``uv tool list`` pasa a decir
    «Failed find package» y el ejecutable revienta con ``ModuleNotFoundError``.
    """
    installed = checks._installed_version()
    if not version or not installed or install_kind() != UV_TOOL:
        return []
    if checks._compare_versions(installed, version) != -1:
        # Al día (o por delante): un aviso que sale siempre deja de leerse.
        return []
    # Sin línea en blanco delante: esto devuelve **el aviso**, no su maquetación. La separación
    # la pone quien imprime, que es el que sabe qué hay encima.
    return [
        t("install.update.uv_tool.installed", installed=installed),
        t("install.update.uv_tool.cannot_1"),
        t("install.update.uv_tool.cannot_2"),
        f"    {UV_TOOL_UPGRADE}",
    ]


# --- Control del daemon -------------------------------------------------------
def _launch_target() -> str:
    """Dominio del LaunchAgent. ``os.getuid`` no existe en Windows, y el camino de macOS
    tiene que poder **probarse** desde cualquier sistema: sin esto, doblar el runner no
    alcanza porque la excepción salta antes de llegar a él."""
    uid = getattr(os, "getuid", lambda: 0)()
    return f"gui/{uid}/{LAUNCH_LABEL}"


def detect_mechanism(opts: Options) -> str:
    """Mecanismo registrado en ESTA máquina.

    No basta con ``sys.platform``: estar en Windows no implica que la tarea exista. Se pregunta
    de verdad, y si nadie la tiene registrada se cae al fallback.
    """
    if sys.platform == "win32":
        done = opts.runner(["schtasks", "/Query", "/TN", TASK_NAME])
        return SCHTASKS if done.returncode == 0 else FALLBACK
    if sys.platform == "darwin":
        done = opts.runner(["launchctl", "print", _launch_target()])
        return LAUNCHCTL if done.returncode == 0 else FALLBACK
    done = opts.runner(["systemctl", "--user", "cat", SYSTEMD_UNIT])
    return SYSTEMD if done.returncode == 0 else FALLBACK


def _stop_start_commands(mechanism: str) -> tuple[list[list[str]], list[list[str]]]:
    """(comandos para parar, comandos para arrancar) de cada mecanismo.

    Están separados porque el de Windows lo necesita: entre parar y arrancar hay que comprobar
    que el proceso murió de verdad. `launchctl kickstart -k` y `systemctl restart` hacen las dos
    cosas en un solo comando y por eso no tienen fase de parada.
    """
    if mechanism == SCHTASKS:
        return ([["schtasks", "/End", "/TN", TASK_NAME]], [["schtasks", "/Run", "/TN", TASK_NAME]])
    if mechanism == LAUNCHCTL:
        return ([], [["launchctl", "kickstart", "-k", _launch_target()]])
    if mechanism == SYSTEMD:
        return ([], [["systemctl", "--user", "restart", SYSTEMD_UNIT]])
    return ([], [])


def _spawn_detached(opts: Options, argv: list[str]) -> None:
    """Relanza ``serve`` sin quedarse atado al proceso actual."""
    if opts.spawn is not None:
        opts.spawn(argv)
        return
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def _serve_argv() -> list[str]:
    return [sys.executable, "-m", "local_delegate", "serve", "--log-level", "warning"]


def wait_until_up(
    opts: Options, *, other_than: int | None = None, timeout: float = 20.0
) -> dict | None:
    """Espera a que ``/api/daemon`` responda. Con ``other_than`` exige que el pid sea distinto.

    El reloj y el ``sleep`` son inyectables porque si no los tests esperarían de verdad.
    """
    host, port = checks.daemon_host_port()
    deadline = opts.clock() + timeout
    while True:
        status = opts.daemon_status(host, port)
        if status and (other_than is None or status.get("pid") != other_than):
            return status
        if opts.clock() >= deadline:
            return None
        opts.sleep(0.5)


def _terminate(opts: Options, pid: int | None, out) -> None:
    """Señal al pid **confirmado por /api/daemon**. Nunca a un pid leído de un fichero."""
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        out(t("install.update.terminate_failed", pid=pid, reason=exc))
    opts.sleep(1.0)


def _still_serving(opts: Options, pid: int, wait: float = 6.0) -> bool:
    """True si tras parar el servicio ese mismo pid **sigue** respondiendo en el puerto."""
    host, port = checks.daemon_host_port()
    deadline = opts.clock() + wait
    while opts.clock() < deadline:
        status = opts.daemon_status(host, port)
        if status is None or status.get("pid") != pid:
            return False
        opts.sleep(0.5)
    return True


def restart_daemon(opts: Options, out=print) -> int:
    """Reinicia (o levanta) el daemon y **verifica** que quedó arriba. Devuelve fallos."""
    host, port = checks.daemon_host_port()
    before = opts.daemon_status(host, port)
    # REQ-008: el único pid que se maneja es el que devuelve /api/daemon en ESTA ejecución. Un
    # pid reciclado no puede llegar aquí, porque nunca se lee `daemon.json`.
    previous_pid = before.get("pid") if before else None
    mechanism = detect_mechanism(opts)

    if before:
        out(t("install.update.restarting", pid=previous_pid, mechanism=mechanism_label(mechanism)))
    else:
        out(t("install.update.starting", mechanism=mechanism_label(mechanism)))

    if mechanism == FALLBACK:
        _terminate(opts, previous_pid, out)
        _spawn_detached(opts, _serve_argv())
    else:
        stop_commands, start_commands = _stop_start_commands(mechanism)
        for argv in stop_commands:
            done = opts.runner(argv)
            if done.returncode != 0:
                detail = done.stderr.strip() or t("install.update.no_detail")
                out(t("install.update.command_failed", command=" ".join(argv), detail=detail))

        # Parar el SERVICIO no siempre para el PROCESO, y esto se descubrió ejecutándolo: en
        # Windows la tarea lanza `conhost -> powershell -> launcher`, y el launcher crea el
        # daemon con `Start-Process`, o sea **desacoplado**. `schtasks /End` termina la cadena
        # de la tarea y el nieto sobrevive con el puerto tomado; el `/Run` siguiente arranca una
        # instancia que no puede escuchar, y el reinicio se da por fallido con el daemon viejo
        # todavía sirviendo. Por eso, si el mismo pid sigue ahí, se le manda la señal — y es
        # legítimo porque ese pid lo confirmó `/api/daemon`, no un fichero de estado.
        if stop_commands and previous_pid and _still_serving(opts, previous_pid):
            out(t("install.update.still_serving_1", pid=previous_pid))
            out(t("install.update.still_serving_2"))
            _terminate(opts, previous_pid, out)

        for argv in start_commands:
            done = opts.runner(argv)
            if done.returncode != 0:
                detail = done.stderr.strip() or done.returncode
                out(t("install.update.command_failed", command=" ".join(argv), detail=detail))
                out(t("install.update.falling_back"))
                _terminate(opts, previous_pid, out)
                _spawn_detached(opts, _serve_argv())
                break

    status = wait_until_up(opts, other_than=previous_pid)
    if status is None:
        out(t("install.update.daemon_down"))
        return 1
    out(t("install.update.daemon_up", version=status.get("version"), pid=status.get("pid")))
    # REQ-013: el backend es un proceso aparte y no se ha tocado.
    out(t("install.update.backend_untouched"))
    return 0


# --- El backend, solo bajo petición explícita ---------------------------------
_PORT_OWNER_RE = re.compile(r"\s(\d+)\s*$")


def _port_owner(opts: Options, port: int) -> int | None:
    """Pid de quien escucha en el puerto, por el mecanismo de cada sistema."""
    if sys.platform == "win32":
        done = opts.runner(["netstat", "-ano", "-p", "TCP"])
        for line in done.stdout.splitlines():
            if (
                f":{port} " in line
                and "LISTENING" in line
                and (match := _PORT_OWNER_RE.search(line.rstrip()))
            ):
                return int(match.group(1))
        return None
    done = opts.runner(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"])
    first = done.stdout.strip().splitlines()
    return int(first[0]) if first and first[0].strip().isdigit() else None


def _process_name(opts: Options, pid: int) -> str:
    if sys.platform == "win32":
        done = opts.runner(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"])
        return done.stdout.strip().strip('"').split('","')[0] if done.stdout.strip() else ""
    done = opts.runner(["ps", "-p", str(pid), "-o", "comm="])
    return done.stdout.strip()


def restart_backend(opts: Options, out=print) -> int:
    """Reinicia llama-swap. Solo con ``--restart-backend`` explícito (REQ-012)."""
    origin = config.backend_origin()
    if origin != "local":
        # El caso de la Mac apuntando a la PC por Tailscale: el backend no corre aquí y no hay
        # nada que reiniciar. No es un error.
        out(t("install.update.backend_remote", host=config.backend_host()))
        return 0

    _host, port = config._split_host_port(config.BASE_URL)
    port_number = int(str(port).lstrip(":") or 0)
    if not port_number:
        out(t("install.update.backend_no_port", url=config.BASE_URL))
        return 1
    pid = _port_owner(opts, port_number)
    if not pid:
        out(t("install.update.port_free", port=port_number))
    else:
        name = _process_name(opts, pid)
        # Dos confirmaciones antes de señalar, igual que con el daemon: el propio docstring de
        # `backend_origin` avisa de que la heurística del host falla con un túnel.
        if "llama-swap" not in name.lower():
            out(t("install.update.port_taken", port=port_number, name=name, pid=pid))
            out(t("install.update.port_taken_hint"))
            return 1
        out(t("install.update.stopping_llamaswap", pid=pid))
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            out(t("install.update.kill_failed", pid=pid, reason=exc))
            return 1
        opts.sleep(2.0)

    from . import autostart

    if autostart.ensure_backend(wait=15.0):
        out(t("install.update.backend_up"))
        return 0
    out(t("install.update.backend_down"))
    return 1


# --- Orquestación --------------------------------------------------------------
def run_update(opts: Options, out=print) -> int:
    """Ejecuta el subcomando completo. Devuelve el código de salida."""
    out(t("install.update.header", home=opts.home))
    if opts.simulated_home:
        out(t("install.update.simulated_home_note"))
    out("")

    # 0. Migración de los nombres retirados, SIEMPRE antes de diagnosticar (REQ-014): así los checks
    # ven el resultado y las notas no piden «renombra» lo que ya se migró. Va fuera de
    # `plan_repairs` (su deduplicación por `(kind, target)` la juntaría con la reparación de hooks)
    # y relee `settings.json` al aplicarse. En `--dry-run` solo se muestra.
    migrated = install.retired_names_to_migrate(opts.home)
    migration = install.plan_retired_name_migration(opts.home, opts.data_dir)
    failures = 0
    if migration:
        out(t("install.update.migration"))
        failures += install.apply(migration, dry_run=opts.dry_run, out=out)
        out("")

    # 1. Diagnóstico: el mismo que ve `doctor`, sin lógica propia. Con `SKIP_PYPI` porque la
    # última versión publicada la pregunta el paso 2 unas líneas más abajo, y dejar que el check
    # la preguntase otra vez sería consultar dos veces lo mismo en un solo comando.
    ctx = checks.Context(
        home=opts.home,
        daemon_status=opts.daemon_status,
        latest_release=checks.SKIP_PYPI,
        **_claude_collaborators(opts),
    )
    results = checks.run_all(ctx)

    # 2. La versión: la que pidió el usuario, o la última publicada. Las líneas dicen de dónde
    # salió el dato; el aviso de desfase que puedan traer es informativo y no toca el plan.
    version, reason = (opts.version, None) if opts.version else latest_version()
    for line in version_lines(version, reason, from_user=bool(opts.version)):
        out(line)

    editable = editable_origin()
    if editable:
        out("")
        out(t("install.update.editable", path=editable))
        out(t("install.update.editable_hint"))
        out(f"    git -C {editable} pull")
        out(f"    uv sync --project {editable}")

    # El hermano del bloque de arriba para el otro modo de instalación: `update` tampoco cambia
    # la versión del ejecutable de `uv tool`, y hasta ahora no lo decía nadie.
    if notice := uv_tool_lines(version):
        out("")
        for line in notice:
            out(line)

    # 3. Plan: la preferencia de idioma (REQ-047), pines y reparaciones del andamiaje.
    language = language_actions(opts)
    actions = plan_pin(opts, version) if version else []
    repairs, notes = plan_repairs(results, opts, migrated=migrated)
    actions.extend(repairs)
    actions.extend(plan_completion_refresh(opts))
    actions.extend(plan_desktop_bridge(opts))

    out("")
    # La preferencia va aparte: guardarla no es reparar el andamiaje.
    if language:
        failures += install.apply(language, dry_run=opts.dry_run, out=out)
    if actions:
        failures += install.apply(actions, dry_run=opts.dry_run, out=out)
    else:
        out(t("install.update.nothing_to_repair"))

    for note in notes:
        out(t("install.update.note", note=note))

    # 4. El daemon, al final de todo.
    if opts.dry_run:
        out("")
        out(t("install.update.dry_run"))
        return 0
    if failures:
        out(t("install.update.failures", n=failures))
        return 1

    out("")
    if opts.no_restart:
        out(t("install.update.no_restart"))
        return 0
    if opts.simulated_home:
        out(t("install.update.simulated_home"))
        return 0

    daemon_result = _daemon_status_of(results)
    if daemon_result is None or not _daemon_applies(results):
        # El caso `stdio` + `uvx` de la Mac: no hay daemon que reiniciar y no es un error.
        out(t("install.update.no_daemon"))
        out(t("install.update.no_daemon_hint"))
        return 0

    code = restart_daemon(opts, out=out)
    if opts.restart_backend:
        out("")
        code = max(code, restart_backend(opts, out=out))
    return code


def _claude_collaborators(opts: Options) -> dict:
    """The `claude` doubles of ``opts`` for ``checks.Context``; the real ones when not given."""
    found: dict = {}
    if opts.claude_which is not None:
        found["claude_which"] = opts.claude_which
    if opts.claude_runner is not None:
        found["claude_runner"] = opts.claude_runner
    if opts.claude_ld_bin is not None:
        found["expected_ld_bin"] = lambda ld=opts.claude_ld_bin: ld
    if opts.data_dir is not None:
        found["log_dir"] = opts.data_dir
    return found


def _daemon_status_of(results: list[tuple[checks.Check, checks.Result]]) -> checks.Result | None:
    for check, result in results:
        if check.id == "service.daemon":
            return result
    return None


def _daemon_applies(results: list[tuple[checks.Check, checks.Result]]) -> bool:
    """¿La configuración de algún cliente usa el daemon (entrada HTTP), o ya está vivo?"""
    for check, result in results:
        if check.id == "service.daemon" and result.status in (checks.OK, checks.WARN):
            return True
        if (
            check.id in _CHECKS_MCP
            and result.status == checks.OK
            and ("http" in result.detail or "remote" in result.detail)
        ):
            return True
    return False
