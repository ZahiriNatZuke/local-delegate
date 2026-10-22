# Evidencia — F1-desktop-bridge (puente del chat de Claude Desktop, solo Windows)

Fecha: 2026-10-21. Worktree `D:/Projects/ld-wt-f1-desktop-bridge`, rama `feat/f1-desktop-bridge`.

## Qué se entrega (REQ-012, núcleo)

- `src/local_delegate/desktop_bridge.py`: MCP stdio → `/mcp` del daemon (HTTP *streamable*:
  `Mcp-Session-Id`, `Mcp-Protocol-Version`, respuestas JSON o SSE). `initialize`, notificaciones y
  respuestas en orden; las demás peticiones en paralelo. 401 → relee el token una vez y, si sigue,
  error MCP `-32002` que nombra la variable. Daemon caído → `-32001` con la URL. Sesión olvidada
  (404) → repite el `initialize` y la petición una vez. URL: `daemon.json` del daemon, si no la
  configurada. `main(["--url", URL])` para pruebas; sin cablear al CLI (lo hace F1-install).
- `src/local_delegate/token_source.py`: token de `HKCU\Environment` (con `REG_EXPAND_SZ`), luego el
  entorno del proceso. Fuera de Windows no lee el registro.
- `src/local_delegate/desktop_config.py`: `write_entry`, `remove_entry`, `check_entry`,
  `bridge_entry`, `config_path`, `backups`. Solo la clave `local-delegate`; copia previa rotada
  (`MAX_BACKUPS = 3`) en la misma carpeta; entrada ajena → `ForeignEntryError` salvo
  `replace_foreign=True`; `owned=True` para lo que el estado de `install` diga que escribió.
- Catálogo `resources/i18n/{es,en}/bridge.json`.

## Pruebas

- `tests/test_desktop_bridge.py` (11): contra la app real de `daemon.build_app` servida por uvicorn
  en un hilo (HTTP, sesión, SSE, 401). Incluye las cinco del plan.
- `tests/test_token_source.py` (8) con registro simulado; `tests/test_desktop_config.py` (18).
- Controles positivos (mutantes, cada uno falla en el test que debe):
  sin rehacer sesión → `test_lost_session_is_restored_and_retried`; token en el log de arranque →
  `test_never_logs_token`; token en el mensaje del 401 → `test_wrong_token_surfaces_401_as_mcp_error`
  y `test_never_logs_token`; sin releer el token → `test_rotated_token_is_reread_once_after_401`;
  sin cabecera de sesión → 4 tests. El mutante del log destapó un fallo real: el proveedor del token
  se ligaba al definir la función y el test leía el registro real; corregido (ligado al llamar).
- Suite completa con `pesado.sh` y `-n 2`: 4221 passed, 28 skipped. `ruff check` y
  `ruff format --check` limpios.

## Ficheros fuera de la lista «Posee»

- `tests/data/uncatalogued_exceptions.json`: el guardián de textos sin catálogo exige justificar
  `"Claude"` (segmento de ruta) y `"Environment"` (clave del registro) como nombres de máquina.
  Solo se añaden dos entradas.
- Palabras nuevas para el detector de nombres en español (`appdata`, `bridge`, `expand`, `hkey`,
  `initialized`, `instances`, `ping`, `unexpanded`, `winreg`): las añade al léxico el PR #394 de la
  sesión principal; este lote no toca el léxico. Doce nombres propios del lote se renombraron, y el
  texto es «encontrado» pasó a «presente».

## Llamadas `local_*`

- `local_summarize` ×2 (research r2 y r5), `local_commit_msg` ×1 (borrador del commit).
