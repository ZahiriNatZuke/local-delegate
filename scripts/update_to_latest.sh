#!/usr/bin/env bash
# Actualiza este cliente a la última versión publicada de local-delegate-mcp en PyPI.
#
# Pensado para la máquina donde el MCP se ejecuta con `uvx` y un pin de versión —el caso de la
# Mac, que apunta al backend de la PC—: abres el portátil después de una release, corres esto y
# ya. No hay que acordarse de qué versión tocaba ni editar dos archivos de configuración a mano.
#
# Qué hace, en orden:
#   1. Pregunta a PyPI cuál es la última versión.
#   2. Mira el pin que tienen ahora ~/.claude.json y ~/.codex/config.toml.
#   3. Si ya coinciden, no toca nada (es idempotente: correrlo dos veces da igual).
#   4. Si no, hace copia .bak y cambia SOLO el número de versión de la entrada local-delegate.
#   5. Descarga la versión nueva a la caché de uvx y comprueba que arranca.
#
# Lo que NO hace, a propósito:
#   · No toca la API key ni ninguna otra variable de entorno de la entrada.
#   · No reinicia Claude ni Codex: eso lo decides tú (te lo recuerda al final).
#   · No instala hooks, skill ni memoria. Para eso está `local-delegate install`.
#
# Uso:
#   ./scripts/update_to_latest.sh              # actualiza a la última de PyPI
#   ./scripts/update_to_latest.sh --dry-run    # enseña qué haría
#   ./scripts/update_to_latest.sh --version 0.12.0
#   ./scripts/update_to_latest.sh --home /tmp/prueba   # contra un HOME de mentira

set -euo pipefail

PACKAGE="local-delegate-mcp"
HOME_DIR="${HOME}"
VERSION=""
DRY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --version) VERSION="${2:?falta el valor de --version}"; shift ;;
    --home) HOME_DIR="${2:?falta el valor de --home}"; shift ;;
    -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac
  shift
done

PYTHON="$(command -v python3 || command -v python || true)"
[[ -n "$PYTHON" ]] || { echo "error: hace falta python3 en el PATH" >&2; exit 1; }

CLAUDE_JSON="${HOME_DIR}/.claude.json"
CODEX_TOML="${HOME_DIR}/.codex/config.toml"

# --- 1. Última versión publicada --------------------------------------------------------
if [[ -z "$VERSION" ]]; then
  # Se usa el índice simple y no /pypi/<pkg>/json: ese endpoint se sirve con caché y puede
  # tardar en reflejar una release recién publicada (visto en vivo con la 0.12.0).
  VERSION="$("$PYTHON" - "$PACKAGE" <<'PY'
import json, re, sys, urllib.request

pkg = sys.argv[1]
req = urllib.request.Request(
    f"https://pypi.org/simple/{pkg}/",
    headers={"Accept": "application/vnd.pypi.simple.v1+json"},
)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.load(resp)

def key(v):
    # Ordena por número, no alfabéticamente: "0.9.0" es MENOR que "0.11.0".
    return [int(p) for p in re.findall(r"\d+", v)]

versions = [v for v in data.get("versions", []) if re.fullmatch(r"\d+(\.\d+)*", v)]
if not versions:
    raise SystemExit("no se pudo determinar la última versión en PyPI")
print(max(versions, key=key))
PY
)"
fi
echo "Última versión publicada: ${VERSION}"

# --- 2. Estado actual --------------------------------------------------------------------
current_of() {  # imprime la versión fijada en un archivo, "sin-pin" o "" si no hay entrada
  "$PYTHON" - "$1" "$PACKAGE" <<'PY'
import re, sys
from pathlib import Path

path, pkg = Path(sys.argv[1]), sys.argv[2]
if not path.is_file():
    print("")
    raise SystemExit
text = path.read_text(encoding="utf-8", errors="replace")
if pkg not in text:
    print("")
elif (m := re.search(rf"{re.escape(pkg)}==([\d.]+)", text)):
    print(m.group(1))
else:
    print("sin-pin")
PY
}

# --- 3. Reemplazo del pin ----------------------------------------------------------------
bump_file() {  # $1 archivo, $2 versión nueva; conserva el terminador de línea original
  "$PYTHON" - "$1" "$PACKAGE" "$2" <<'PY'
import re, shutil, sys
from pathlib import Path

path, pkg, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
raw = path.read_bytes().decode("utf-8")
newline = "\r\n" if "\r\n" in raw else "\n"
updated = re.sub(rf"{re.escape(pkg)}==[\d.]+", f"{pkg}=={version}", raw)
if updated == raw:
    raise SystemExit(1)
shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
path.write_bytes(updated.replace("\r\n", "\n").replace("\n", newline).encode("utf-8"))
PY
}

changed=0
for target in "$CLAUDE_JSON" "$CODEX_TOML"; do
  # Las comillas son necesarias: sin ellas la `~` se expande al HOME real y el mensaje diría
  # que se tocó un archivo que no es el que se está tocando.
  label="~/${target#"${HOME_DIR}"/}"
  current="$(current_of "$target")"

  if [[ -z "$current" ]]; then
    echo "  ${label}: sin entrada de ${PACKAGE} — no se toca"
    continue
  fi
  if [[ "$current" == "sin-pin" ]]; then
    # Sin `==X.Y.Z`, uvx ya resuelve la última en cada arranque: no hay nada que cambiar.
    echo "  ${label}: sin pin de versión (uvx ya usa la última) — no se toca"
    continue
  fi
  if [[ "$current" == "$VERSION" ]]; then
    echo "  ${label}: ya está en ${VERSION}"
    continue
  fi

  if [[ $DRY -eq 1 ]]; then
    echo "  [dry-run] ${label}: ${current} -> ${VERSION} (con copia .bak)"
  else
    bump_file "$target" "$VERSION"
    echo "  ${label}: ${current} -> ${VERSION} (copia en ${label}.bak)"
  fi
  changed=1
done

# --- 4. Caché de uvx y comprobación ------------------------------------------------------
if [[ $DRY -eq 1 ]]; then
  echo
  echo "--dry-run: no se escribió nada."
  exit 0
fi

if command -v uvx >/dev/null 2>&1; then
  echo
  echo "Descargando ${PACKAGE}==${VERSION} a la caché de uvx…"
  # Se comprueba la metadata en vez de lanzar el servidor: `--version` intenta hablar con el
  # backend y en esta máquina puede no estar accesible, lo que confundiría el diagnóstico.
  installed="$(uvx --from "${PACKAGE}==${VERSION}" python -c \
    "import importlib.metadata as m; print(m.version('${PACKAGE}'))" 2>/dev/null || true)"
  if [[ "$installed" == "$VERSION" ]]; then
    echo "  OK: uvx ejecuta ${PACKAGE} ${installed}"
  else
    echo "  AVISO: no se pudo confirmar la versión con uvx (¿sin red?). Los archivos ya están" >&2
    echo "         actualizados; se resolverá en el próximo arranque." >&2
  fi
else
  echo "aviso: no hay uvx en el PATH; instala uv para que la entrada MCP funcione" >&2
fi

echo
if [[ $changed -eq 1 ]]; then
  echo "Listo. Reinicia Claude Code y Codex para que tomen ${VERSION}."
else
  echo "Nada que actualizar: ya estabas en ${VERSION}."
fi
