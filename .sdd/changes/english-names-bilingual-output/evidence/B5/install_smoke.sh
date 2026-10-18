#!/usr/bin/env bash
# Humo de `install`/`doctor`/`uninstall` con el idioma (ola B5, REQ-047/REQ-034).
#
# Uso:
#   bash install_smoke.sh <dir-temporal>          # HOME y datos simulados: no toca nada real
#   bash install_smoke.sh --real                  # contra el HOME y el LOG_DIR reales (PENDIENTE:
#                                                 # lo corre el usuario antes de la release)
#
# En modo temporal, `--home` apunta a <dir>/home y `LOCAL_DELEGATE_LOG_DIR` a <dir>/data, así que
# `language.json` se escribe ahí y la CLI de los clientes no se invoca (HOME simulado).
set -u
LD=(uv run --no-sync local-delegate)

if [ "${1:-}" = "--real" ]; then
  echo "== install real con LOCAL_DELEGATE_LANG=es (la preferencia queda en es/variable)"
  LOCAL_DELEGATE_LANG=es "${LD[@]}" install --mcp-mode http --web-token-env --enable-read-hook --agents
  echo "== doctor sin la variable: debe decir «Idioma: es (preferencia; …language.json)»"
  env -u LOCAL_DELEGATE_LANG "${LD[@]}" doctor | head -5
  echo "== y local_status (por MCP) debe mostrar el mismo idioma, origen y ruta tras reiniciar el daemon"
  exit 0
fi

base="${1:?falta el directorio temporal}"
rm -rf "$base" && mkdir -p "$base/home/.claude/agents" "$base/home/.codex" "$base/data"
printf -- '---\nname: probe\ntools: Read, mcp__local-delegate__local_delegate\n---\n\n## Delegation to local models\n\nText.\n\n## Other\n' \
  > "$base/home/.claude/agents/probe.md"
export LOCAL_DELEGATE_LOG_DIR="$base/data"
common=(--home "$base/home" --clients claude --clients codex)

for lang in en es; do
  echo "################ LOCAL_DELEGATE_LANG=$lang"
  LOCAL_DELEGATE_LANG=$lang "${LD[@]}" install "${common[@]}" --agents
  echo "== language.json: $(cat "$base/data/language.json")"
  echo "== SKILL.md: $(sed -n 6p "$base/home/.claude/skills/local-delegation/SKILL.md")"
  echo "== bloques en CLAUDE.md: $(grep -c 'local-delegate:begin' "$base/home/.claude/CLAUDE.md")"
  grep -m1 '^## ' "$base/home/.claude/CLAUDE.md"
  grep -m1 -o '\*\*Cat[a-zá]* [a-z ]*`local_\*`[^:]*' "$base/home/.claude/agents/probe.md"
done

echo "################ doctor sin la variable (lee la preferencia es/variable)"
env -u LOCAL_DELEGATE_LANG "${LD[@]}" doctor --home "$base/home" 2>&1 | grep -A2 -E "^(Idioma|Language):"
echo "################ uninstall"
LOCAL_DELEGATE_LANG=en "${LD[@]}" uninstall "${common[@]}" | tail -4
echo "== language.json tras uninstall: $(ls "$base/data" | grep -c language.json) fichero(s)"
