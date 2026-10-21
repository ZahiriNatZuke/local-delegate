# Verificación L9 — retirada de los nombres viejos (0.38.0)

## Entorno

- Revisión: `main` en `5f3a227` (L1–L8 mezclados, #370–#377), árbol limpio salvo `.sdd/`.
- Ejecutables del `.venv` en modo editable (`.venv/Scripts/local-delegate`, `.venv/Scripts/local-delegate-mcp`), sin `uv sync`.
- Una sola shell de la tool Bash con el guion `live.sh` (scratchpad de la sesión). En todos los pasos:
  `LOCAL_DELEGATE_LOG_DIR=<scratchpad>/live-logs` exportada, `LD_HOOK_TELEMETRY_LOG=` vacía,
  `PYTHONIOENCODING=utf-8`, `LOCAL_DELEGATE_LANG` sin definir (salvo el caso en inglés).
- Python 3.11 del `.venv`, ruff 0.17.1, Windows 11.
- No se tocó el daemon, la tarea programada, el `~/.claude` real, `~/.codex`, variables ni perfiles.

**Valores sembrados.** En lugar de `a` y `b` (REQ-025) se usaron valores inventados distintivos
(`sentinelA-…` para `LOCAL_DELEGATE_COST_FALLBACK`, `sentinelB-…` para `LOCAL_DELEGATE_COSTE_RESPALDO`,
`sentinelC-…` para la clave ajena `OTHER_TOOL_FLAG`), para que el `grep -c` de «ningún valor en la
salida» pueda dar distinto de 0 si se filtrara uno: con `a` o `b` el conteo no discrimina. Son de
prueba, no secretos.

## Pasos

Salidas completas en [evidence/live/](evidence/live/); resumen línea a línea en
[evidence/live/summary.txt](evidence/live/summary.txt).

| Paso | Comando | Esperado | Obtenido | Estado |
|---|---|---|---|---|
| 0 | `env \| cut -d= -f1` contra los 4 nombres de variable retirados y las 3 `_FAST` | ninguno presente; `LOG_DIR` exportada; telemetría vacía | 0 presentes; las dos variables fijadas | OK |
| 1 | `sha256sum ~/.claude/settings.json` | hash inicial | `07315718a7dc56d587d95dad98279a6cf9cde91426e4d9a41883b72913453bb6` | OK |
| 2 | sembrar `$H/.claude/settings.json` (`env` con `LD_HOOK_READ_BLOQUEAR=1`, `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO=1`, `LOCAL_DELEGATE_COST_FALLBACK`, `LOCAL_DELEGATE_COSTE_RESPALDO`, `OTHER_TOOL_FLAG`; `theme` fuera de `env`) y `$H/.claude/local-delegate-bloqueo-apagado` | ficheros creados | hash sembrado `5f767d6fc15dfdffeb39e0b49aa7fce0b1865b1144b60b810749399dd2ccb3fe` | OK |
| 3 | `local-delegate doctor --home "$H"` | `WARN` en «nombres obsoletos» con los 4 nombres y pista de renombrar; sin valores | `[WARN] nombres obsoletos` con los 4 nombres («ya no tiene efecto: usa …») y «arréglalo con: renombra X a Y» ×4; 0 valores. Código 1 por los `FAIL` del andamiaje vacío del HOME simulado, ajenos al check | OK |
| 3-en | `LOCAL_DELEGATE_LANG=en local-delegate doctor --home "$H"` (la CLI no tiene `--lang`; su regla de idioma es `LOCAL_DELEGATE_LANG` > `language.json` > sistema) | la misma línea en inglés | `[WARN] deprecated names: … has no effect: use …` y `fix it with: rename X to Y` ×4 | OK |
| 4 | `local-delegate update --home "$H" --no-restart --version 0.37.0 --dry-run` | acciones `[migrate]` listadas; hashes de `$H/.claude/*` iguales; 0 valores; ni `retired-names-migration.json` ni `.bak` | dos `[dry-run] [migrate]` (env con los 3 renombres; interruptor); hashes iguales ([antes](evidence/live/step4-hashes-before.txt) / [después](evidence/live/step4-hashes-after.txt)); 0 valores; ni registro ni `.bak` | OK |
| 5 | `local-delegate update --home "$H" --no-restart --version 0.37.0` | `env` con `LD_HOOK_READ_BLOCK=1`, `LOCAL_DELEGATE_STRUCTURED_SUMMARY=1`, `LOCAL_DELEGATE_COST_FALLBACK` con su valor, sin viejos; clave ajena intacta; `.bak` = sembrado; interruptor renombrado; registro con nombres y sin valores | todo True; viejos presentes `[]`; `OTHER_TOOL_FLAG` y `theme` intactos; `settings.json.retired-names.bak` con hash `5f767d6f…b3fe` (= sembrado); `local-delegate-block-off` existe y el viejo no; [registro](evidence/live/step5-retired-names-migration.json) con los 4 nombres y 0 valores; la salida avisa de que la copia lleva el env completo | OK |
| 6 | `doctor --home "$H"` y segunda `update … --dry-run` | sin avisos de esos nombres; sin migración | 0 apariciones de los 4 nombres; la cabecera «Nombres retirados: se migran…» no sale | OK |
| 7 | `local-delegate recalcular-coste --claude-dir "$H/.claude"` y `local-delegate-mcp recalcular-coste --claude-dir "$H/.claude"` | código 2 y nombran `recompute-cost`; no escriben | los dos con código 2 y `recompute-cost` en la salida; en `LOG_DIR` solo `language.json` y `retired-names-migration.json` (de `update`), ningún artefacto de coste | OK |
| BOM | `settings.json` sembrado con BOM UTF-8 y `LD_HOOK_READ_BLOQUEAR`; `update --home … --no-restart --version 0.37.0` | la migración lo lee y conserva el BOM | **la migración sí**: su resultado (guardado por la reparación de hooks en `settings.json.bak`) empieza por `EF BB BF` y lleva `LD_HOOK_READ_BLOCK=1` con la clave ajena. **Pero el fichero final no**: la reparación de hooks que corre después lo reescribe sin BOM y sin `env` (ver defecto 1) | OK la migración; FALLO del resultado final (defecto previo, fuera de alcance) |
| Inválido | `settings.json` con JSON roto; `update` con y sin `--dry-run` | la migración no escribe y lo dice | `[migrate] … no se migra el env de settings.json: no es JSON válido; no se toca`; sin `.bak` de la migración ni registro. El hash del fichero cambia por la reparación de hooks posterior, que lo sustituye (deja `settings.json.bak`) | OK la migración; ver defecto 1 |
| 9 | los dos `git grep` de REQ-024; `pyproject.toml` | 0 y 0; `0.37.0` | 0 y 0; `version = "0.37.0"` | OK |
| 8 | hash final de `~/.claude/settings.json`; borrar `$H` y logs | igual al del paso 1 | `07315718…53bb6`, igual; `live-home`, `live-home-bom`, `live-home-bad` y `live-logs` borrados | OK |

## Calidad (REQ-024)

| Comprobación | Comando | Resultado |
|---|---|---|
| Suite completa | `bash ~/.claude/scripts/pesado.sh .venv/Scripts/python -m pytest -n 2 -q -p no:cacheprovider` | `4187 passed, 28 skipped, 2 warnings in 202.38s`, código 0 ([salida](evidence/live/suite.txt)); los 2 avisos son `DeprecationWarning` de `anyio.abc.BlockingPortal` en `starlette/testclient.py:53`, de terceros |
| Lint | `uv run --no-sync ruff check .` | `All checks passed!` |
| Formato | `uv run --no-sync ruff format --check .` | `318 files already formatted` |
| CodeQL de `main` | `gh api "repos/ZahiriNatZuke/local-delegate/code-scanning/alerts?ref=refs/heads/main&state=open" --jq length` | `0` |
| Código muerto | los dos `git grep` de REQ-024 | 0 y 0 |
| Versión | `pyproject.toml` | `0.37.0` |
| Árbol | `git status --short` | solo `.sdd/` sin seguimiento; fin de línea sin cambios |

## Defectos encontrados

1. **La reparación de hooks de `update` borra el `env` de un `settings.json` con BOM o inválido**
   (previo a este SDD; la spec lo deja fuera: «I6» y «m18», «los fallos previos van al backlog»).
   Reproducción: HOME simulado con `.claude/settings.json` = BOM UTF-8 + `{"env": {"LD_HOOK_READ_BLOQUEAR": "1", "OTHER_TOOL_FLAG": "x"}}`;
   `local-delegate update --home "$H" --no-restart --version 0.37.0`. La migración escribe bien (con
   BOM, `LD_HOOK_READ_BLOCK=1`, clave ajena intacta), pero el paso `[settings] registra 2 hook(s)`
   no entiende el BOM (`src/local_delegate/install.py:263-268`: `_read_json` lee con
   `encoding="utf-8"` y devuelve `{}` ante cualquier error), trata el fichero como vacío y lo
   reescribe solo con `hooks` (`_write_json`, `:271-276`): se pierden el
   BOM, el `env` migrado y la clave ajena. Queda copia en `settings.json.bak` (y el original en
   `settings.json.retired-names.bak`), así que es recuperable, pero el usuario se queda sin el
   bloqueo de lectura encendido. Con JSON inválido pasa lo mismo (la migración no toca, la reparación
   sustituye). Hay que confirmar que está en el backlog; su gravedad sube porque ahora `update`
   migra justo antes y el usuario de Windows con un `settings.json` guardado con BOM pierde lo que
   se acaba de migrar.

Ningún defecto en lo que este SDD entrega: los pasos 0–9 de L9 y los casos extra pasan.

## Llamadas `local_*`

1 llamada: `local_lint_summary(path=<scratchpad>/suite.txt)` para resumir la salida de la suite. El resto no se delegó: las salidas en vivo se comprobaron con `grep`/`sha256sum` dentro del guion (conteos exactos que un resumen no garantiza), y los ficheros leídos (plan, spec, código de la migración) eran tramos cortos que había que leer literalmente.

## Limpieza

- Borrados `live-home`, `live-home-bom`, `live-home-bad`, `live-logs` y los ficheros de hashes temporales del scratchpad.
- Hash del `~/.claude/settings.json` real igual antes y después (`07315718…53bb6`).
- Sin shells, servidores ni esperas vivas al terminar.

## Después de la verificación en vivo

- **El defecto 1 quedó arreglado dentro del SDD** (lote L10, PR #379, `7603bb0`; REQ-026 y REQ-027
  en «Cambios tras la verificación» de `spec.md`): `install`/`update` leen `settings.json` y
  `~/.claude.json` con BOM y lo conservan al reescribir; si un fichero existe y no se puede leer,
  el paso no escribe, avisa (es/en) y el comando sale con código ≠ 0; `doctor` acepta el BOM.
  16 tests en `tests/test_config_json_safety.py`, en rojo en `main` antes del arreglo; mutantes
  cazados. Suite tras L10: 4141 pasados, 28 saltados; CI de la PR en verde y CodeQL a 0.
- **Revisión de conformidad** (`review.md`): un bloqueante, el test del registro exigía
  `UNRELEASED` y el bump real a 0.38.0 lo sella. Arreglado en la PR #380 (el test acepta las dos
  formas). Comprobado simulando el bump real y la sección `[0.38.0]` del CHANGELOG:
  `tests/test_deprecations.py` pasa entero (34).
- **Repetición en vivo sobre `main` tras L10 (sesión principal)**: el caso BOM con la salida de
  `update` redirigida a fichero reventó con `UnicodeEncodeError` (flecha `→` en cp1252) y la
  migración quedó a medias. Arreglado en L11 (PR #381, `a9f84e7`; REQ-028). Repetido sobre
  `a9f84e7` con la salida redirigida y sin `PYTHONUTF8`: `update` sale con 0, BOM conservado, `env`
  migrado (`LD_HOOK_READ_BLOCK`), clave ajena intacta, hooks registrados, copia
  `settings.json.retired-names.bak` creada, ningún valor sembrado en la salida, y `doctor` da
  «sin nombres obsoletos en uso». El caso de JSON inválido (sobre `70b4e2f`): fichero idéntico
  (hash), aviso y código 1. Hash del `~/.claude/settings.json` real igual antes y después.
