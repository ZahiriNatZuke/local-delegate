#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Uso: $0 <COMMIT_SHA> <BASE_URL>" >&2
  echo "Ejemplo: $0 abc123... https://mi-pc.tailnet.ts.net:9292/v1" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage

commit_sha="$1"
base_url="${2%/}"
repo_url="https://github.com/ZahiriNatZuke/local-delegate.git"

[[ "$commit_sha" =~ ^[0-9a-fA-F]{40}$ ]] || {
  echo "ERROR: usa el SHA completo de 40 caracteres." >&2
  exit 2
}
[[ "$base_url" == https://*/v1 ]] || {
  echo "ERROR: BASE_URL debe usar HTTPS y terminar en /v1." >&2
  exit 2
}

for command in curl git python3 uvx; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "ERROR: falta '$command' en PATH." >&2
    exit 1
  }
done

if [[ -z "${LOCAL_DELEGATE_API_KEY:-}" ]]; then
  read -r -s -p "API key de local-delegate: " LOCAL_DELEGATE_API_KEY
  echo
  export LOCAL_DELEGATE_API_KEY
fi

echo "[1/4] Comprobando backend autenticado..."
curl --fail --silent --show-error --max-time 10 \
  -H "Authorization: Bearer ${LOCAL_DELEGATE_API_KEY}" \
  "${base_url}/models" >/dev/null

echo "[2/4] Preparando checkout temporal seguro..."
temp_root="${TMPDIR:-/tmp}"
temp_dir="$(mktemp -d "${temp_root%/}/local-delegate-canary.XXXXXX")"
cleanup() {
  case "$temp_dir" in
    "${temp_root%/}/local-delegate-canary."*) rm -rf -- "$temp_dir" ;;
    *) echo "AVISO: no se elimina un temporal fuera del prefijo esperado: $temp_dir" >&2 ;;
  esac
}
trap cleanup EXIT
git -C "$temp_dir" init --quiet
git -C "$temp_dir" remote add origin "$repo_url"

echo "[3/4] Descargando el commit exacto desde GitHub..."
git -C "$temp_dir" fetch --quiet --depth 1 origin "$commit_sha"
git -C "$temp_dir" checkout --quiet --detach FETCH_HEAD

echo "[4/4] Ejecutando canary MCP Mac -> PC..."
export LOCAL_DELEGATE_BASE_URL="$base_url"
python3 "$temp_dir/scripts/macos_mcp_canary.py" \
  --package-source "git+${repo_url}@${commit_sha}" \
  --expect-auth
