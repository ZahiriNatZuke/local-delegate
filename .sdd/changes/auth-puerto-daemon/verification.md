# Verification: El puerto del daemon exige token cuando se configura uno

## Environment

- Base `5809003` (`main`, tras el PR #106); rama `feat/auth-puerto-daemon`.
- Windows 11, PowerShell 7, `uv run`. Claude Code 2.1.220 para la medición de expansión.
- El e2e corrió contra un **daemon real de esta rama** en el puerto `9494`, con `LOG_DIR` propio
  para no tocar el lock del daemon de la máquina.

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | e2e: 5 superficies sin credencial | ✅ | `/mcp`, `/`, `/api/daemon`, `/api/backend`, `/api/status` → **401** las cinco |
| REQ-001 | e2e: token equivocado | ✅ | `401` |
| REQ-002 | e2e: `Bearer` correcto | ✅ | `200` en las cuatro rutas + handshake MCP completo |
| REQ-002 | e2e: `Basic` correcto | ✅ | `200` en `/` |
| REQ-002 | unit: usuario indiferente, token con `:` | ✅ | `test_el_usuario_de_basic_da_igual`, `test_un_token_con_dos_puntos_dentro_sigue_valiendo` |
| REQ-003 | e2e: cabecera del `401` | ✅ | `www-authenticate: Basic realm="local-delegate", charset="UTF-8"` |
| REQ-004 | unit + mutante | ✅ | `proteger()` devuelve **el mismo objeto**; el mutante que envuelve siempre cae |
| REQ-005 | unit | ✅ | `test_el_lifespan_no_se_filtra` (assert propio, no `TypeError`) |
| REQ-006 | unit + e2e | ✅ | las dos `query_*` mandan la cabecera; `doctor` con token → `[ OK ] daemon` |
| REQ-007 | unit + medición | ✅ | Claude Code expande `${VAR}` en `headers` (medido); el TOML de Codex se parsea y no contiene `${` ni `bearer_token =` |
| REQ-008 | unit + e2e | ✅ | `doctor` sin token → «nuestro daemon escucha … pero este entorno no tiene su token» |
| REQ-009 | unit | ✅ | `test_el_diagnostico_del_token_no_imprime_el_secreto`, `test_el_rechazo_no_filtra_el_token` |

### La medición que sostiene el diseño

Servidor señuelo en el `9494` que apunta las cabeceras recibidas, con la variable **solo** en el
entorno del proceso. Claude Code 2.1.220 mandó:

```
"authorization": "Bearer token-de-prueba-123"
"user-agent": "claude-code/2.1.220 (sdk-cli)"
```

Expande. Si hubiera mandado la cadena literal, todo el enfoque elegido se cae — por eso se midió
antes de escribir el código y no después.

### Verificación al revés: 10 mutantes

**Sobre `auth.py`:**

| Mutante | Quién lo caza |
| --- | --- |
| `if scope != "http"` desactivado | `test_el_lifespan_no_se_filtra` |
| sin cabecera → pasa | `test_sin_cabecera_no_entra_por_ninguna_ruta[/mcp]` |
| `proteger` envuelve siempre | `test_sin_token_la_app_vuelve_intacta` |
| `Basic` parte por el **último** `:` | `test_un_token_con_dos_puntos_dentro_sigue_valiendo` |
| `compare_digest` → `==` | **NADIE** (ver desviaciones) |

**Sobre `daemon.py` y `checks.py`:**

| Mutante | Quién lo caza |
| --- | --- |
| la rama del token no existe | `test_el_puerto_protegido_no_se_confunde_con_un_proceso_ajeno` |
| el `401` se cree sin mirar el `realm` | `test_un_401_ajeno_no_se_atribuye_*` y `test_un_401_sin_cabecera_de_reto_*` |
| el CLI deja de autenticarse | `test_el_cli_se_autentica_contra_su_propio_daemon` |
| la puerta se pone **antes** del `Mount` | `test_con_token_el_puerto_entero_pide_credencial` |
| **preguntar CON cabecera** por el token | `test_la_pregunta_por_el_token_va_SIN_credencial` |

**El último merece detalle, porque en la primera pasada NO lo cazaba nadie.** El doble de `httpx2`
aceptaba `headers` y los ignoraba, así que el test no podía ver por qué camino se preguntaba — y
ese mutante *es* el error de diseño que ya costó un día entero en este repo: mirar por el camino
que sí lleva credencial tapa el fallo del que no la lleva. Se añadió un test que registra las
cabeceras **con `WEB_TOKEN` puesto** (con la variable vacía pasaría igual estando el código mal),
y ahora cae.

## Quality checks

- [x] `uv run pytest -q` → **611 passed, 1 skipped** (570 al empezar el change).
- [x] `uv run ruff check .` → `All checks passed!`
- [x] `uv run ruff format --check .` → `63 files already formatted`
- [x] `extract_dashboard_js.py` + `node --check` → OK
- [x] Sin secretos: `gitleaks` en pre-commit; tests explícitos de no-filtración.
- [x] Sin cambios ajenos.

## Deviations and residual risk

- **La propiedad de tiempo constante NO está cubierta.** Sustituir `secrets.compare_digest` por
  `==` deja los 24 tests de la puerta en verde. Es esperable —no es observable sin medir tiempos—
  pero se deja escrito en vez de dar por cubierto algo que no lo está. Se implementa porque es lo
  correcto, no porque haya un test que lo obligue.
- **«La variable existe en el entorno del cliente» no se puede verificar desde el repo.** Es el
  punto exacto donde esto se rompe en silencio, y es el mismo que ya falló con `--api-key-env`.
  Mitigado por documentación y por el mensaje del `doctor`, no por código.
- **Codex no se probó end-to-end**: se leyó su fuente (`mcp_types.rs`) y se comprobó que el TOML
  generado es válido y usa `bearer_token_env_var`. Falta arrancar Codex contra un daemon
  protegido. Riesgo bajo —la clave es la que su propio validador exige— pero **no está medido**,
  a diferencia de Claude Code.
- **Incidente durante la verificación:** al limpiar el daemon de pruebas, un filtro de procesos
  demasiado ancho mató también el daemon real de la máquina. Se restauró con su tarea programada y
  se comprobó por tres vías (proceso del paquete de `uv tool`, handshake MCP, backend con
  credencial). Sin efecto sobre el resultado, pero queda anotado.
