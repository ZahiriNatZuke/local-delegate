#!/usr/bin/env python3
"""Ejercita la entrega por plugin de `install`/`uninstall` contra la CLI real de Claude Code.

SDD claude-plugin-and-mods, F1-install (REQ-005, 006, 008 b, 011). Corre en el job `plugin` del CI,
en los tres sistemas, con un HOME simulado y `CLAUDE_CONFIG_DIR` dentro de él: la config real del
runner no se toca. Usa las funciones de `install` y no el comando, por una sola razón: el comando
solo elige el plugin desde una instalación de `uv tool` (plan, N-2), y aquí el paquete corre desde
el entorno del proyecto; `ld_bin` se le pasa explícito con el intérprete que ejecuta el script.

Secuencia (plan, lote F1-install):

1. Siembra una 0.39 por settings, con el bloqueo de lectura **encendido** y un hook ajeno.
2. `install`: plugin listado, sin hooks nuestros en settings.json, interruptor encendido,
   scripts de `~/.claude/hooks/local-delegate/` borrados, hook ajeno intacto.
3. La orden que declara el `hooks.json` **instalado** para `prompt`, leída de él y no escrita a
   mano, con una muestra por stdin: sale con 0 y da JSON o nada.
4. Segunda pasada idéntica: settings.json igual que tras la primera.
5. `--claude-delivery settings`: el plugin se va y vuelven los hooks, con el de lectura.
6. `uninstall`: ni plugin ni hooks nuestros; el hook ajeno, intacto.

Uso: ``uv run python scripts/check_plugin_install.py <ruta del binario claude>``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from local_delegate import claude_plugin, install, install_state, plugin_migration

FOREIGN = {"type": "command", "command": "node /opt/mine/notify.js"}
PROMPT_SAMPLE = {
    "session_id": "ci-plugin-check",
    "hook_event_name": "UserPromptSubmit",
    "prompt": "Reply OK",
    "cwd": ".",
}


def fail(message: str) -> None:
    print(f"FALLO: {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def step(message: str) -> None:
    print(f"== {message}", flush=True)


def settings(home: Path) -> dict:
    path = home / ".claude" / "settings.json"
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def ours(home: Path) -> list[dict]:
    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
    return [
        hook
        for groups in settings(home).get("hooks", {}).values()
        for group in groups
        for hook in group.get("hooks", [])
        if install._is_ours(hook, hooks_dir)
    ]


def has_foreign(home: Path) -> bool:
    return any(
        hook == FOREIGN
        for group in settings(home).get("hooks", {}).get("Stop", [])
        for hook in group.get("hooks", [])
    )


def switch_active(home: Path, data_dir: Path) -> bool | None:
    path = plugin_migration.read_switch_path(home, data_dir)
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("active")


def listed(claude_bin: str, home: Path) -> dict | None:
    done = claude_plugin.run_subprocess(
        claude_plugin.list_argv(claude_bin), claude_plugin.child_env(home)
    )
    return claude_plugin.listed_entry(done.stdout)


def options(home: Path, claude_bin: str, **kwargs) -> install.Options:
    kwargs.setdefault("components", {"hooks"})
    return install.Options(
        home=home,
        data_dir=home.parent / "data",
        # Never the client CLI for the MCP entry: `claude mcp add-json/remove --scope user` ignores
        # the simulated HOME and writes the runner's real `~/.claude.json` (the CLI turns this off
        # for a simulated HOME; these options are built by hand, so it is said here).
        use_cli=False,
        targets={"claude"},
        python_exe=sys.executable,
        claude_which=lambda name: claude_bin if name == "claude" else None,
        claude_ld_bin=claude_plugin.LdBin(sys.executable, None),
        **kwargs,
    )


def run(actions: list[install.Action]) -> None:
    failures = install.apply(actions, dry_run=False)
    if failures:
        fail(f"{failures} acción(es) fallaron")


def installed_hooks_json(home: Path) -> Path:
    found = sorted((home / ".claude" / "plugins").rglob("hooks.json"))
    found = [p for p in found if "local-delegate" in p.as_posix()]
    if not found:
        fail("no está el hooks.json del plugin instalado")
    return found[-1]


def prompt_command(hooks_json: Path) -> list[str]:
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    hook = data["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    command = hook["command"].replace("${user_config.ld_bin}", sys.executable)
    if "${" in command or any("${" in arg for arg in hook.get("args", [])):
        fail(f"quedan variables sin sustituir: {hook}")
    return [command, *hook.get("args", [])]


def main() -> int:
    if len(sys.argv) != 2:
        fail("uso: check_plugin_install.py <binario claude>")
    claude_bin = sys.argv[1]
    root = Path(tempfile.mkdtemp(prefix="ld-plugin-"))
    home = root / "home"
    (home / ".claude").mkdir(parents=True)
    # Los datos del instalador (estado, interruptor) también fuera del runner: `data_dir` en las
    # opciones y, para el hook que se lanza en el paso 3, la variable que lee `read_switch`.
    data_dir = root / "data"
    data_dir.mkdir()
    os.environ["LOCAL_DELEGATE_LOG_DIR"] = str(data_dir)
    os.environ.pop("CLAUDE_CONFIG_DIR", None)  # `child_env` pone el del HOME simulado

    step("1. Siembra una 0.39 por settings con el bloqueo encendido y un hook ajeno")
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [FOREIGN]}]}}), encoding="utf-8"
    )
    run(
        install.plan_install(
            options(home, claude_bin, claude_delivery="settings", enable_read_hook=True)
        )
    )
    if not install.read_hook_registered(home / ".claude"):
        fail("la siembra no dejó el hook de lectura registrado")

    step("2. install: entrega por plugin")
    run(install.plan_install(options(home, claude_bin)))
    entry = listed(claude_bin, home)
    if not claude_plugin.entry_is_current(entry, install_state.load(home, data_dir)["version"]):
        fail(f"el plugin no quedó instalado y habilitado: {entry}")
    if ours(home):
        fail(f"quedan hooks nuestros en settings.json: {ours(home)}")
    if switch_active(home, data_dir) is not True:
        fail("el interruptor de lectura no quedó encendido tras migrar")
    if (home / ".claude" / "hooks" / install.HOOKS_SUBDIR).exists():
        fail("no se borraron los scripts de la entrega por settings")
    if not has_foreign(home):
        fail("se perdió el hook ajeno")

    step("3. La orden de prompt del hooks.json instalado, con una muestra")
    argv = prompt_command(installed_hooks_json(home))
    done = subprocess.run(
        argv,
        input=json.dumps(PROMPT_SAMPLE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    if done.returncode != 0:
        fail(f"{argv} salió con {done.returncode}: {done.stderr}")
    if done.stdout.strip():
        try:
            json.loads(done.stdout)
        except ValueError:
            fail(f"la salida del hook no es JSON: {done.stdout[:300]}")
    print(f"   {' '.join(argv)} -> 0", flush=True)

    step("4. Segunda pasada idéntica")
    before = settings(home)
    run(install.plan_install(options(home, claude_bin)))
    if settings(home) != before or ours(home):
        fail("la segunda pasada cambió settings.json")

    step("5. --claude-delivery settings: vuelta atrás")
    run(install.plan_install(options(home, claude_bin, claude_delivery="settings")))
    if listed(claude_bin, home) is not None:
        fail("el plugin sigue instalado tras volver a settings")
    if not install.read_hook_registered(home / ".claude"):
        fail("la vuelta atrás no repuso el hook de lectura")

    step("6. uninstall")
    run(install.plan_uninstall(options(home, claude_bin, components=set(install.FULL_COMPONENTS))))
    if listed(claude_bin, home) is not None or ours(home):
        fail("uninstall dejó el plugin o hooks nuestros")
    if not has_foreign(home):
        fail("uninstall tocó el hook ajeno")
    print("OK: entrega por plugin, idempotencia, vuelta atrás y uninstall", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
