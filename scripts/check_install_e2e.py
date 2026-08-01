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

RAIZ = Path(__file__).resolve().parents[1]

# Cuántas entradas de hook debe haber tras instalar: `UserPromptSubmit` y `PreToolUse/Bash`. El de
# `Read` no cuenta porque es opt-in (`--enable-read-hook`). Reinstalar no puede cambiar este número
# — si sube, se están duplicando; si baja, se están perdiendo.
HOOKS_ESPERADOS = 2


def _correr(*args: str) -> None:
    print(f"$ local-delegate {' '.join(args)}", flush=True)
    proceso = subprocess.run(
        [sys.executable, "-m", "local_delegate", *args], cwd=RAIZ, text=True, capture_output=True
    )
    if proceso.returncode != 0:
        print(proceso.stdout)
        print(proceso.stderr, file=sys.stderr)
        raise SystemExit(f"falló `local-delegate {' '.join(args)}` con {proceso.returncode}")


def _exigir(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise SystemExit(f"FALLO: {mensaje}")


def _hooks_registrados(casa: Path) -> int:
    datos = json.loads((casa / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return sum(len(g["hooks"]) for grupos in datos.get("hooks", {}).values() for g in grupos)


def main() -> int:
    casa = Path(tempfile.mkdtemp(prefix="ld-e2e-")) / "casa"
    # Los dos directorios de cliente se crean a mano: `install` configura los que **existen**, y
    # sin esto el paso probaría el camino de «no hay ningún cliente», que no es el que interesa.
    (casa / ".claude").mkdir(parents=True)
    (casa / ".codex").mkdir(parents=True)
    print(f"HOME temporal: {casa}", flush=True)

    comunes = ["--home", str(casa), "--no-client-cli"]

    _correr("install", *comunes, "--dry-run")
    _exigir(
        not (casa / ".claude" / "hooks").exists(),
        "`--dry-run` escribió en disco; tiene que describir sin tocar nada",
    )

    _correr("install", *comunes)
    _correr("install", *comunes)  # idempotencia

    claude = casa / ".claude"
    _exigir(
        (claude / "hooks" / "local-delegate" / "suggest_delegate_prompt.py").is_file(),
        "no se copiaron los scripts de hooks",
    )
    _exigir(
        (claude / "hooks" / "local-delegate" / "hook_common.py").is_file(),
        "falta hook_common.py, que los hooks importan por sys.path[0]",
    )
    _exigir(
        (claude / "skills" / "delegacion-local" / "SKILL.md").is_file(), "no se instaló la skill"
    )
    _exigir(
        "local-delegate:begin" in (claude / "CLAUDE.md").read_text(encoding="utf-8"),
        "no se escribió el bloque de memoria de Claude Code",
    )
    _exigir(
        "local-delegate:begin" in (casa / ".codex" / "AGENTS.md").read_text(encoding="utf-8"),
        "no se escribió el bloque de memoria de Codex",
    )

    registrados = _hooks_registrados(casa)
    _exigir(
        registrados == HOOKS_ESPERADOS,
        f"tras dos instalaciones hay {registrados} hooks y deberían ser {HOOKS_ESPERADOS}",
    )

    _correr("uninstall", *comunes)
    _exigir(
        not (claude / "hooks" / "local-delegate").exists(),
        "`uninstall` dejó los scripts de hooks: el módulo promete ser reversible",
    )
    _exigir(not (claude / "skills" / "delegacion-local").exists(), "`uninstall` dejó la skill")
    _exigir(
        _hooks_registrados(casa) == 0,
        "`uninstall` dejó hooks nuestros registrados en settings.json",
    )

    print(f"instalador OK en {sys.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
