# Verification: `doctor` pregunta al daemon por el backend

## Environment

- Base: `main` en `1182a92`. Rama `fix/doctor-backend-via-daemon`.
- Windows 11, Python 3.11 (uv). Daemon local en 0.18.0, backend llama-swap vivo en el 9292.
- La consola donde se ejecutó `doctor` **no** tiene `LOCAL_DELEGATE_API_KEY` — el caso reportado.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `query_backend` devuelve el dict del daemon | OK | `test_query_backend_devuelve_lo_que_ve_el_daemon` |
| REQ-002 | respuesta sin `available` → `None` | OK | `test_query_backend_sin_el_campo_available_es_none`, `…con_respuesta_que_no_es_un_objeto…` |
| REQ-003, REQ-004 | se pregunta al daemon y desaparece el 401 | OK | `test_el_daemon_responde_por_el_backend_y_se_acabo_el_401` + **ejecución real** |
| REQ-005 | `available: false` cuenta como aviso | OK | `test_si_el_daemon_dice_que_el_backend_esta_caido_eso_no_es_una_duda` (exit 1) |
| REQ-006 | sin daemon, el camino de antes intacto | OK | `test_sin_daemon_el_backend_se_prueba_directo_como_siempre`, `test_run_doctor_keeps_the_previous_output` |
| REQ-007 | la clave no se toca | OK | `git diff -- src/ \| grep -c 'API_KEY\|auth_headers'` → **0** |

### Antes y después, en la máquina del usuario

```
# antes
Backend BASE_URL: http://127.0.0.1:9292/v1 — arriba (rechaza la credencial de este entorno)
  [ -- ] backend: … responde 401: está arriba pero rechaza la credencial (¿falta …?)

# después
Backend BASE_URL: http://127.0.0.1:9292/v1 — arriba
  [ OK ] backend: http://127.0.0.1:9292/v1/models responde
Resultado: todo a punto (andamiaje, servicios y versiones probadas).   exit=0
```

### Verificación de los tests al revés

Tres defectos, **los tres rompen el test que dice cubrirlos**:

| Defecto introducido | Test que se pone rojo |
| --- | --- |
| no preguntar al daemon (probar directo como antes) | `test_el_daemon_responde_por_el_backend_y_se_acabo_el_401` (+ el de `available: false`) |
| dar por bueno un backend que el daemon ve caído | `test_si_el_daemon_dice_que_el_backend_esta_caido_eso_no_es_una_duda` |
| aceptar una respuesta sin `available` | `test_query_backend_sin_el_campo_available_es_none` (+ el de respuesta no-objeto) |

**El script de mutación falló primero y hay que recordarlo:** `subprocess.run(text=True)` decodifica
en **cp1252** en esta consola, y la salida de pytest trae UTF-8 → `proc.stdout` llegaba como `None`
y el veredicto habría sido un falso «nadie se entera». Se fija `encoding="utf-8"`. Es la **segunda
vez hoy** que el arnés de verificación miente antes que el código.

## Quality checks

- [x] Project-native tests pass — **562 passed, 1 skipped** (eran 559).
- [x] Lint y formato — `ruff check .` y `ruff format --check .` en verde.
- [x] Secret scanning — REQ-007 comprobado sobre el diff; `gitleaks` del pre-commit en verde.
- [x] No unrelated changes — `daemon.py`, `checks.py`, dos ficheros de test y el `CHANGELOG`.

## Deviations and residual risk

- **Un hallazgo colateral, y no menor:** al implementar esto, `test_run_doctor_keeps_the_previous_output`
  falló porque **estaba saliendo a la red de verdad** — el colaborador nuevo no estaba doblado, así
  que consultaba el daemon real de la máquina. Habría dado verde en CI (donde no hay daemon) y otra
  cosa en la máquina de quien desarrolla. Es el **mismo patrón** que apareció hoy con
  `clients.jsonl`. Corregido doblándolo en `_stub_environment`.
- **El peor caso hace dos llamadas HTTP** (1 s al daemon + 2 s al backend). Solo ocurre cuando no
  hay daemon, y el diagnóstico no es un camino caliente.
- **No se probó con el daemon caído y el backend vivo** en la máquina real; está cubierto por test
  (`backend_via_daemon=None`).
