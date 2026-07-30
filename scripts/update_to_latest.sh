#!/usr/bin/env bash
# Envoltorio fino de `local-delegate update`.
#
# Este script hacía el trabajo de verdad —consultar PyPI, cambiar el pin de ~/.claude.json y
# ~/.codex/config.toml— y por eso vivía aquí. Ya no: todo eso es un subcomando del CLI, que
# además completa el andamiaje que falte y deja el daemon arriba.
#
# El fichero sigue existiendo por una razón concreta: en la Mac el hábito es correr
# `./scripts/update_to_latest.sh`, y romper ese hábito no aporta nada. Pero ojo con la trampa
# que lo hacía inútil, que fue lo que originó el cambio: **el wheel NO empaqueta `scripts/`**
# (28 entradas, 0 coincidencias), así que este fichero nunca llegaba a la máquina que tenía que
# actualizarse. Solo existe en un clon del repo. Lo que viaja en el paquete es el CLI.
#
# Regla del repo que salió de aquí: lo que corre el usuario va al CLI; lo que corre el repo se
# queda en `scripts/`.
#
# Uso (los mismos argumentos que el subcomando):
#   ./scripts/update_to_latest.sh
#   ./scripts/update_to_latest.sh --dry-run
#   ./scripts/update_to_latest.sh --version 0.16.0
#   ./scripts/update_to_latest.sh --home /tmp/prueba

set -euo pipefail

if command -v local-delegate >/dev/null 2>&1; then
  exec local-delegate update "$@"
fi

# Sin el comando en el PATH (instalación con `uvx`, que borra su entorno al terminar) se intenta
# el módulo, que funciona desde un clon del repo.
if command -v python3 >/dev/null 2>&1; then
  exec python3 -m local_delegate update "$@"
fi

echo "error: no se encontró 'local-delegate' ni 'python3' en el PATH" >&2
echo "       instálalo con: uv tool install local-delegate-mcp" >&2
exit 1
