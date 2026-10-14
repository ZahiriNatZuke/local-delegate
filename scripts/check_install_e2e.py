#!/usr/bin/env python3
"""Ejercita `install`/`uninstall` de punta a punta contra un HOME temporal.

**Por qué existe.** La suite prueba las funciones del instalador; esto prueba el **comando**, con
su parser, su plan y su escritura real. La diferencia importa porque `install` decide rutas, monta
comandos de shell y elige intérprete **según la plataforma**, y de sus tres caminos el de macOS no
se había ejecutado nunca: el backlog lo daba por «no auditable sin un Mac». No hacía falta un Mac,
hacía falta un runner — y `test (macos-latest)` ya estaba en la matriz del CI desde hace tiempo.

**Por qué en Python y no en shell.** El paso corre en los tres sistemas, y un script de shell
tendría que sobrevivir a Git Bash en Windows, donde una ruta `/tmp/...` llega al binario nativo
traducida o sin traducir según el caso. Aquí las rutas las construye y las comprueba el mismo
Python que va a recibirlas.

Se instala **dos veces** a propósito: la idempotencia es la propiedad que más fácil se rompe en un
instalador, y una sola pasada no la vería.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from local_delegate import install

ROOT = Path(__file__).resolve().parents[1]

# Cuántas entradas de hook debe haber tras instalar. Se deriva de `_HOOK_EVENTS` en vez de llevar
# el número a mano: escrito a mano decía 2, y al retirar `suggest_lint_summary.py` este smoke se
# puso en rojo en las tres plataformas por un cambio que era correcto. Un número duplicado a mano
# es una segunda fuente para el mismo dato, que es el defecto recurrente de este repo.
#
# El de `Read` no cuenta porque es opt-in (`--enable-read-hook`). Reinstalar no puede cambiar este
# número — si sube, se están duplicando; si baja, se están perdiendo.
EXPECTED_HOOKS = len(install._HOOK_EVENTS)


def _run(*args: str) -> None:
    print(f"$ local-delegate {' '.join(args)}", flush=True)
    process = subprocess.run(
        [sys.executable, "-m", "local_delegate", *args], cwd=ROOT, text=True, capture_output=True
    )
    if process.returncode != 0:
        print(process.stdout)
        print(process.stderr, file=sys.stderr)
        raise SystemExit(f"falló `local-delegate {' '.join(args)}` con {process.returncode}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FALLO: {message}")


def _registered_hooks(home: Path) -> int:
    data = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return sum(len(g["hooks"]) for groups in data.get("hooks", {}).values() for g in groups)


def _opencode_entry(directory: Path) -> dict | None:
    """La entrada `local-delegate` en la config de opencode, mirando **los dos** ficheros.

    opencode lee `opencode.json` y `opencode.jsonc` y los fusiona, y `install` elige uno u otro
    según cuál exista: comprobar solo uno daría por ausente lo que está en el otro.
    """
    for name in ("opencode.json", "opencode.jsonc"):
        path = directory / name
        if not path.is_file():
            continue
        # Sin comentarios: los escribe `install` con un serializador de JSON, no una persona.
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = (data.get("mcp") or {}).get("local-delegate")
        if isinstance(entry, dict):
            return entry
    return None


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="ld-e2e-")) / "casa"
    # Los tres directorios de cliente se crean a mano: `install` configura los que **existen**, y
    # sin esto el paso probaría el camino de «no hay ningún cliente», que no es el que interesa.
    #
    # El de opencode se escribe como ruta literal a propósito, y no derivándolo de
    # `install.opencode_dir`: esto es una prueba de caja negra del **comando**, y comprobarlo con
    # la misma función que lo calcula no probaría que la ruta documentada es la que se usa. Con un
    # HOME simulado la variable `XDG_CONFIG_HOME` se ignora, así que es determinista.
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    opencode = home / ".config" / "opencode"
    opencode.mkdir(parents=True)
    print(f"HOME temporal: {home}", flush=True)

    common = ["--home", str(home), "--no-client-cli"]

    _run("install", *common, "--dry-run")
    _require(
        not (home / ".claude" / "hooks").exists(),
        "`--dry-run` escribió en disco; tiene que describir sin tocar nada",
    )

    _run("install", *common)
    _run("install", *common)  # idempotencia

    claude = home / ".claude"
    _require(
        (claude / "hooks" / "local-delegate" / "suggest_delegate_prompt.py").is_file(),
        "no se copiaron los scripts de hooks",
    )
    _require(
        (claude / "hooks" / "local-delegate" / "hook_common.py").is_file(),
        "falta hook_common.py, que los hooks importan por sys.path[0]",
    )
    _require(
        (claude / "skills" / "local-delegation" / "SKILL.md").is_file(), "no se instaló la skill"
    )
    _require(
        "local-delegate:begin" in (claude / "CLAUDE.md").read_text(encoding="utf-8"),
        "no se escribió el bloque de memoria de Claude Code",
    )
    _require(
        "local-delegate:begin" in (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8"),
        "no se escribió el bloque de memoria de Codex",
    )
    _require(
        "local-delegate:begin" in (opencode / "AGENTS.md").read_text(encoding="utf-8"),
        "no se escribió el bloque de memoria de opencode",
    )
    _require(
        (opencode / "skill" / "local-delegation" / "SKILL.md").is_file(),
        "no se instaló la skill en el directorio de opencode",
    )
    _require(
        _opencode_entry(opencode) is not None,
        "no se escribió la entrada MCP de opencode",
    )

    registered = _registered_hooks(home)
    _require(
        registered == EXPECTED_HOOKS,
        f"tras dos instalaciones hay {registered} hooks y deberían ser {EXPECTED_HOOKS}",
    )

    _run("uninstall", *common)
    _require(
        not (claude / "hooks" / "local-delegate").exists(),
        "`uninstall` dejó los scripts de hooks: el módulo promete ser reversible",
    )
    _require(not (claude / "skills" / "local-delegation").exists(), "`uninstall` dejó la skill")
    _require(
        not (opencode / "skill" / "local-delegation").exists(),
        "`uninstall` dejó la skill de opencode",
    )
    _require(
        _opencode_entry(opencode) is None,
        "`uninstall` dejó la entrada MCP en la configuración de opencode",
    )
    _require(
        _registered_hooks(home) == 0,
        "`uninstall` dejó hooks nuestros registrados en settings.json",
    )

    print(f"instalador OK en {sys.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
