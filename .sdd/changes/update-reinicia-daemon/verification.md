# Verification: `local-delegate update` revisa, completa y deja el daemon arriba

## Environment

- Revision: rama `feat/update-reinicia-daemon`, sobre `19a84ee` (main, 0.16.0 publicada)
- Relevant runtime and tool versions: Windows 11, Python 3.11.15 (venv del repo), pytest 9.1.1,
  ruff via `uv run`, Node para `node --check`. Daemon real por tarea programada
  `LocalDelegateDaemon`; backend `llama-swap` v238 en 127.0.0.1:9292.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `update --help` y las cinco flags | OK | `usage: local-delegate update [-h] [--dry-run] [--home HOME] [--version VERSION] [--restart-backend] [--no-restart]` |
| REQ-002 | Tests del pin con LF y CRLF, `.bak`, sin-pin, ya-al-dia, sin entrada | OK | `test_el_pin_conserva_el_terminador_de_linea` (parametrizado) + 3 tests |
| REQ-003 | Dos pasadas reales sobre HOME simulado | OK | pasada 1: 5 acciones; pasada 2: «Nada que reparar» |
| REQ-004 | `--dry-run` con snapshot byte a byte y runner registrado | OK | `test_dry_run_deja_el_arbol_byte_a_byte_igual`, `test_dry_run_no_reinicia_el_daemon` |
| REQ-005 | Ejecución real: exigir pid distinto | OK | `50952 -> 47380` confirmado por `/api/daemon` |
| REQ-006 | Daemon caído se levanta | OK | test + ejecución real (se levantó por la tarea tras quedar caído) |
| REQ-007 | Detección por consulta real en los tres sistemas + fallback | OK | 3 tests parametrizados de detección, 3 de fallback |
| REQ-008 | El pid solo de `/api/daemon`; nunca se lee `daemon.json` | OK | `test_sin_daemon_vivo_no_se_envia_ninguna_senal` |
| REQ-009 | Sin daemon aplicable: se dice y sale 0 | OK | camino `stdio` en `run_update`, exit 0 |
| REQ-010 | `--no-restart` solo informa | OK | usado en dos tests; no toca el runner |
| REQ-011 | `install --mcp-mode http` deja el daemon arriba | OK | `_deja_el_daemon_arriba` en `cli.py`; con `stdio` no hace nada |
| REQ-012 | Backend intacto al reiniciar el daemon | OK | `llama-swap` pid `46912` antes y después; `test_sin_la_flag_no_hay_ni_una_invocacion_al_backend` |
| REQ-013 | El mensaje lo dice | OK | «el backend de inferencia no se ha tocado: los modelos siguen en VRAM» |
| REQ-014 | Detección de instalación editable (PEP 610) | OK | ejecución real + 6 casos parametrizados |
| REQ-015 | Sin pin que cambiar, igual repara y reinicia | OK | ejecución real en esta PC (no hay pin y reinició) |
| REQ-016 | Recetas de macOS y Linux en la wiki | OK | `test_los_nombres_del_servicio_coinciden_con_la_wiki` |
| REQ-017 | El script queda como envoltorio | OK | delega en `local-delegate update "$@"`; modo `100755` conservado |

## Quality checks

- [x] Project-native tests pass. **370 passed, 1 skipped** (328 antes del change).
- [x] Lint, formatting, type checking, and build checks pass where applicable.
      `ruff check` → All checks passed; `ruff format --check` → 52 files already formatted;
      `extract_dashboard_js.py` + `node --check` → exit 0.
- [x] Secret scanning passes. El change no lee ni escribe ninguna API key; el secreto DPAPI no
      se toca (lo usa el launcher de la tarea, que es previo y ajeno a este código).
- [x] No unrelated changes are present.

## Deviations and residual risk

### Hallazgos de la ejecución que el plan no había previsto

1. **`schtasks /End` no mata el daemon** *(bloqueante, corregido)*. La tarea lanza
   `conhost -> powershell -> start-local-delegate-secure.ps1`, y ese launcher crea el daemon con
   `Start-Process`, o sea **desacoplado**: `/End` termina la cadena de la tarea y el nieto
   sobrevive con el puerto tomado, así que el `/Run` siguiente arranca una instancia que no puede
   escuchar. La primera ejecución real terminó en `ERROR: el daemon no volvió a responder` con el
   daemon viejo todavía sirviendo. Corrección: separar parada y arranque, y entre medias
   comprobar si el mismo pid sigue respondiendo; si sigue, mandarle la señal — legítimo porque
   ese pid lo confirmó `/api/daemon`. Test propio, **verificado al revés**: sin el fix no se
   señala ningún pid y el test falla.

2. **`update --home <simulado>` escribía en la configuración real** *(corregido)*.
   `install._register_claude_mcp` usa `claude mcp add-json --scope user`, que escribe siempre en
   el `~/.claude.json` de verdad ignorando `home`. Se descubrió comprobando la idempotencia: la
   segunda pasada replanificaba la misma acción —el probe seguía viendo vacío el árbol simulado—
   mientras la configuración real sí se había reescrito. Corrección:
   `use_cli=not opts.simulated_home`, con test.

3. **`os.getuid` no existe en Windows**: el camino de macOS no se podía ni probar, porque la
   excepción saltaba antes de llegar al runner doblado.

4. **El caso de prueba que el plan daba por servido ya no existe.** El plan contaba con
   `service.daemon` en `warn` (daemon 0.15.0 con 0.16.0 instalada); esa desincronización se
   arregló al principio de esta sesión, así que la rama se cubrió con test unitario.

5. **`len(checks.CHECKS)` es 12 y el módulo decía «once» en cuatro sitios.** Corregido y atado
   con un test.

### Riesgo residual

- **macOS y Linux no se ejercitan por ejecución.** Se cubren con el runner doblado (detección,
  fallback y comandos de cada mecanismo) y con un test que exige que los tres nombres canónicos
  aparezcan en `docs/wiki/Daemon.md`. Sigue en pie el pendiente conocido de que el instalador
  nunca corrió en macOS.
- **`--restart-backend` no se ejecutó de verdad en esta máquina, a propósito**: `llama-swap`
  exige `LOCAL_DELEGATE_REMOTE_API_KEY` para arrancar y `autostart.ensure_backend()` lo lanzaría
  heredando el entorno del comando, que no la tiene. Aquí hay que reiniciarlo por la tarea o por
  el script que descifra el secreto. Cubierto por tests: camino remoto, puerto ocupado por otro
  proceso y cero invocaciones sin la flag.
- **`install --home <simulado>` tiene el mismo agujero del punto 2** y es previo a este change.
  Queda anotado en el backlog como change propio; tocarlo aquí sería trabajo ajeno.
