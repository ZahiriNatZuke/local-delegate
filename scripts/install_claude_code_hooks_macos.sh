#!/usr/bin/env bash
# Instala los hooks consultivos de local-delegate para Claude Code en macOS.
# Puede ejecutarse desde cualquier directorio: todas las rutas se basan en $HOME.

set -euo pipefail

readonly HOOK_DIR="${HOME}/.claude/hooks"
readonly SETTINGS="${HOME}/.claude/settings.json"
readonly VERSION="v0.10.0"
readonly BASE_URL="https://raw.githubusercontent.com/ZahiriNatZuke/local-delegate/${VERSION}/docs/recipes/hooks"

readonly FILES=(
  "hook_common.py"
  "suggest_delegate_prompt.py"
  "suggest_delegate_read.py"
  "suggest_lint_summary.py"
)

command -v curl >/dev/null 2>&1 || {
  echo "ERROR: curl no esta disponible." >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || {
  echo "ERROR: python3 no esta disponible." >&2
  exit 1
}

mkdir -p "${HOOK_DIR}" "${HOME}/.claude"

echo "Descargando hooks de local-delegate ${VERSION}..."
for file in "${FILES[@]}"; do
  curl --fail --silent --show-error \
    "${BASE_URL}/${file}" \
    --output "${HOOK_DIR}/${file}.new"
done

for file in "${FILES[@]}"; do
  mv "${HOOK_DIR}/${file}.new" "${HOOK_DIR}/${file}"
done

chmod 700 "${HOOK_DIR}"/*.py
python3 -m py_compile "${HOOK_DIR}"/*.py

if [[ -f "${SETTINGS}" ]]; then
  backup="${SETTINGS}.backup.$(date +%Y%m%d-%H%M%S)"
  cp -p "${SETTINGS}" "${backup}"
  echo "Backup creado: ${backup}"
fi

python3 - <<'PY'
import json
import os
import tempfile
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
hook_dir = Path.home() / ".claude" / "hooks"

if settings_path.exists():
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
else:
    settings = {}

if not isinstance(settings, dict):
    raise SystemExit("ERROR: ~/.claude/settings.json no contiene un objeto JSON.")

hooks = settings.setdefault("hooks", {})
if not isinstance(hooks, dict):
    raise SystemExit("ERROR: la propiedad 'hooks' existente no es un objeto JSON.")

managed_names = {
    "suggest_delegate_prompt.py",
    "suggest_delegate_read.py",
    "suggest_lint_summary.py",
}


def is_managed(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    configured_hooks = entry.get("hooks", [])
    if not isinstance(configured_hooks, list):
        return False
    for configured_hook in configured_hooks:
        if not isinstance(configured_hook, dict):
            continue
        values = [str(configured_hook.get("command", ""))]
        args = configured_hook.get("args", [])
        if isinstance(args, list):
            values.extend(str(value) for value in args)
        joined = " ".join(values)
        if any(name in joined for name in managed_names):
            return True
    return False


def existing_entries(event: str) -> list[object]:
    entries = hooks.get(event, [])
    if not isinstance(entries, list):
        raise SystemExit(f"ERROR: hooks.{event} no es una lista.")
    return [entry for entry in entries if not is_managed(entry)]


def command_hook(script: str) -> dict[str, object]:
    return {
        "type": "command",
        "command": "python3",
        "args": [str(hook_dir / script)],
    }


prompt_hook = {
    "hooks": [command_hook("suggest_delegate_prompt.py")],
}

read_hook = {
    "matcher": "Read",
    "hooks": [command_hook("suggest_delegate_read.py")],
}

bash_hook = {
    "matcher": "Bash",
    "hooks": [command_hook("suggest_lint_summary.py")],
}

hooks["UserPromptSubmit"] = existing_entries("UserPromptSubmit") + [prompt_hook]
hooks["PreToolUse"] = existing_entries("PreToolUse") + [read_hook, bash_hook]

settings_path.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile(
    mode="w",
    encoding="utf-8",
    dir=settings_path.parent,
    delete=False,
) as stream:
    json.dump(settings, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
    temporary_path = Path(stream.name)

os.replace(temporary_path, settings_path)
print(f"Configuracion actualizada: {settings_path}")
PY

echo
echo "Verificando UserPromptSubmit..."
printf '%s\n' '{"prompt":"resume este archivo en cinco viñetas"}' \
  | python3 "${HOOK_DIR}/suggest_delegate_prompt.py"

echo
echo "Verificando PreToolUse/Bash..."
printf '%s\n' '{"tool_input":{"command":"pytest"}}' \
  | python3 "${HOOK_DIR}/suggest_lint_summary.py"

echo
echo "Instalacion terminada. Cierra completamente Claude Code y abrelo de nuevo."
echo "El hook experimental de Read queda registrado pero apagado por defecto."
