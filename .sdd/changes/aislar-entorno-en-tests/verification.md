# Verification: La suite no puede heredar el entorno de quien la corre

## Environment

- Revision: rama `fix/aislar-entorno-en-tests`, partiendo de `ccddeea` (main).
- Máquina con **cuatro** variables del paquete definidas: `LD_HOOK_TELEMETRY_LOG`,
  `LOCAL_DELEGATE_WEB_TOKEN`, `LOCAL_DELEGATE_AUTOSTART`, `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS`.
  Ese es justamente el entorno que hacía falta para poder medir esto.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Importar `config` y contar el inventario | **OK** | 34 variables registradas solas (una enumeración manual previa se había quedado en 14) |
| REQ-002 | `grep os.environ\|os.getenv` sobre `config.py` | **OK** | única aparición: dentro de `_leer` |
| REQ-003 | Guardián de entorno limpio durante la suite | **OK** | `test_la_suite_corre_sin_variables_del_paquete_definidas` |
| REQ-004 | `pytest tests/test_daemon.py` con la variable **puesta** | **OK** | `25 passed` (antes: 4 fallos `401 == 200`) |
| REQ-005 | Dos mutantes, uno por guardián | **OK, distinguen** | ver abajo |
| REQ-006 | Suite completa en los dos entornos | **OK** | `725 passed, 2 skipped` en ambos, mismo número |

### Los controles positivos, y lo que destaparon

- **Mutante A** — `os.environ.get("LOCAL_DELEGATE_COSA_NUEVA")` añadido a `config.py` saltándose
  `_leer`: el guardián del AST falla nombrando la línea exacta (`nivel de módulo (línea 290)`).
- **Mutante B** — la fixture de aislamiento desactivada, con el entorno real: el guardián falla
  listando las variables que se cuelan. **Y ahí salió lo que la enumeración manual no vio**: no eran
  dos variables contaminando esta máquina, eran **cuatro** — `LOCAL_DELEGATE_AUTOSTART` y
  `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS` también estaban definidas. El inventario automático las
  cubrió sin que nadie tuviera que acordarse de ellas; eso es exactamente lo que se compraba con
  REQ-001.
- **Control positivo del propio inventario** — `test_el_inventario_de_variables_no_esta_vacio`.
  Sin él, un registro roto dejaría el inventario vacío y los otros dos guardianes pasarían
  comprobando la lista vacía. Es la trampa que este repo ya conoce, puesta antes de que muerda.

## Quality checks

- [x] Project-native tests pass — `725 passed, 2 skipped` con el entorno real **y** con el limpio.
- [x] Lint, formatting, build — `ruff check` limpio (hubo un `SIM102` en el guardián nuevo,
      corregido), `ruff format --check`: 75 ficheros; `node --check` sobre el JS extraído.
- [x] Secret scanning — el diff no toca autenticación ni añade dependencias; `gitleaks` del
      pre-commit en verde. El token se sigue leyendo igual en producción: lo único que cambia es que
      la **suite** ya no lo hereda.
- [x] No unrelated changes — tres ficheros: `config.py`, `conftest.py` y el test nuevo.
- [ ] Type checking — no aplica: el proyecto no tiene comprobador de tipos configurado.

## Deviations and residual risk

- **Lo capturado por otros módulos en tiempo de import sigue sin cubrirse**, y es una limitación
  real, no un olvido: `server._chat_slots` fija `MAX_CONCURRENT_REQUESTS` al importar `server`, y
  recargar `config` después no lo cambia. Está declarado fuera de alcance en el brief **y medido**:
  esa variable está definida en esta máquina y la suite pasa entera igual, porque los tests que
  dependen del semáforo hacen su propio `monkeypatch`. Si algún día un test empezara a depender del
  valor por defecto sin parchearlo, saldría como fallo, no como falso verde.
- **El guardián del AST detecta `os.environ` / `os.getenv` con receptor `os`.** Un alias exótico
  (`from os import environ`) se le escaparía; el guardián de entorno limpio lo pillaría igual, así
  que el peor caso es un mensaje de error menos preciso, no un defecto que pase.
