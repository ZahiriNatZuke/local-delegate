# Research: Renombrado a inglés de lo publicado y salidas en español e inglés

Consolidación de las dos investigaciones del 2026-10-12 sobre `main` en `8ec2f1d` (0.34.0). El
detalle, las tablas y los `fichero:línea` están en:

- [`research-rename.md`](research-rename.md): frente A, renombrado (inventario público, datos
  persistidos, superficie interna, acoplamientos, mecanismos de compatibilidad, olas posibles).
- [`research-i18n.md`](research-i18n.md): frente B, idioma (inventario de cadenas por superficie,
  cómo se elegiría el idioma, opciones de catálogo, tests que afirman texto).
- `evidence/`: inventarios completos fila a fila (`rename-inventory-public.csv`, 38 filas;
  `rename-inventory-internal.csv`, 4 640; `i18n-inventory.csv`, 3 066; `persisted-data-scan.json`;
  `internal-scan-summary.json`).

Aquí solo van las cifras que deciden la spec y los riesgos; no se repiten las tablas.

## Current behavior

**Cómo se midió.** Todo por programa (AST de Python, `tokenize`, `esprima` para el JS del panel),
con controles positivos y negativos documentados en cada research. El detector de «nombre en
español» (`esdet.py`, basado en `wordfreq`) acierta 29 de 30 nombres españoles conocidos, da 0
falsos positivos en 54 nombres ingleses y tiene una exhaustividad estimada del ≈99 %. Ese detector
y sus escáneres estaban **fuera del repo** (en el scratchpad de la sesión); se conservaron sin
rutas privadas en `tools/research-scanners/` como insumo, y la ola A0 los convierte en una pieza
versionada sin `wordfreq` en ejecución (`spec.md`, REQ-044). El detector **no ve etiquetas de una o
dos palabras** (i18n, «Cómo se midió»): para el frente B el control es otro (REQ-045).

> Nota 2026-10-12: tras la ola A0, `tools/research-scanners/` se retiró de la carpeta del cambio; lo sustituye `scripts/detect_spanish_names.py` (ver `waves/A0.md`).

### Frente A: lo que está en español (cifras clave)

| Superficie | Cifra | Detalle |
| --- | --- | --- |
| CLI | 2 de 15 subcomandos/101 opciones | `recalcular-coste`, `--reiniciar-calibracion` (rename §1a) |
| Variables de entorno | 4 de 60 | `LD_HOOK_READ_BLOQUEAR`, `LD_HOOK_READ_INTERRUPTOR`, `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`, `LOCAL_DELEGATE_COSTE_RESPALDO`; las dos primeras las leen también los **hooks instalados** (`hook_common.py`) (rename §1b) |
| Datos persistidos | 14 formatos | claves y valores en español en `usage-*.jsonl`, `enfriamiento*.json[l]`, `atribucion-*.json`, `coste-agregados.json`, telemetría de hooks (31 691 líneas aquí), temporales de hooks, `precios.json`/`densidad.json`, salida de `benchmark`; 57 valores de enumeración en español (rename §1c) |
| API del panel | 81 campos de respuesta, 65 identificadores JS, 20 ids del DOM | más diccionarios JS de etiquetas indexados por valores persistidos (rename §1d) |
| Contrato MCP | subclaves de `_local_delegate` y 3 marcadores | `truncado`, `aviso`, `leido_server_side`, `respaldo`, `crudo`; `[local-delegate aviso: …]`, `[local-delegate respaldo: …]`, `[local-delegate: entrada truncada …]`. Nombres de tools y parámetros ya en inglés (rename §1e) |
| `doctor` | 2 ids y 3 grupos | `config.rol_retirado`, `config.coste`; grupos `entorno`, `andamiaje`, `servicio` (rename §1f) |
| Disco del usuario | 7 nombres | interruptor `local-delegate-bloqueo-apagado`, hook `anotar_llamada.py`, skill `delegacion-local`, 3 temporales, `cuota-statusline.jsonl` (rename §1g) |
| Módulos | 14 en `src`, 41 en `tests`, 14 en `scripts` | ninguno es API pública, pero `scripts/` y `hook_common` los atan por nombre (rename §1h) |
| Interno | 3 621 nombres, 25 908 apariciones, 143 ficheros | 78 % en `tests/` y `scripts/`; más 557 claves de cadena (3 057 apariciones) (rename §2) |

### Frente B: lo que solo existe en español

| Superficie | Cadenas aprox. |
| --- | --- |
| CLI (`print`, errores, `--help`) | 210 |
| `doctor` y checks | 173 |
| Salidas de tools MCP y `local_status` | 196 (17 errores con prefijo `[local-delegate error]`, que es contrato) |
| Descripciones de tools | 11 docstrings (8 771 caracteres) + 11 títulos + descripción del servidor |
| Hooks | 7 mensajes, en ASCII sin tildes a propósito |
| Panel | ~440 (89 nodos HTML, 30 atributos, ~339 cadenas JS, `lang`, `title`, `meta`) |
| `install`, `update`, `test-window`, `recalcular-coste`, llama-swap | ~220 |
| **Total** | **≈1 380** + descripciones (la estimación del brief, ~1 100, se quedaba corta) |

No hay ningún mecanismo de i18n (cero `gettext`, cero catálogos). 431 cadenas interpolan y ~200
se arman por trozos, que obliga a reescribir la frase entera. El chrome de `argparse` («usage:»,
«options:») ya sale en inglés, mezclado con la ayuda en español. 567 asserts afirman texto en
español (~450 son del frente B); siguen valiendo si el español no cambia (i18n §3).

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| CLI y variables | subcomandos, opciones, 60 variables | 2 nombres y 4 variables con alias + aviso; ayuda y salidas en dos idiomas | rename §1a-b, i18n §1a |
| Hooks instalados | escriben telemetría y temporales; leen `enfriamiento.json` y variables | claves, valores, ficheros y variables nuevos con lectura dual; mensajes en dos idiomas sin importar el paquete | rename §1c, §3.3-4; i18n §1e |
| Daemon y log de uso | escribe `usage-*.jsonl`, `enfriamiento*` | escritura en inglés, lectura dual; clases de fallo y causas renombradas | rename §1c, §3.2 |
| Coste, cuota, atribución | cachés no regenerables | lectura dual para siempre | rename §3.1 |
| Panel | API JSON + JS con espejo de `_accounting` | campos y JS en inglés en el mismo cambio; selector de idioma; textos del servidor en el idioma del panel | rename §1d, §3.5; i18n §1f |
| Contrato MCP | `_local_delegate`, marcadores, descripciones | cambio único anunciado; descripciones solo en inglés | rename §1e; i18n §1d |
| `doctor` y wiki | 25 checks; `test_wiki.py` compara títulos y número | ids y grupos en inglés; check único de nombres obsoletos que sustituye a `config.rol_retirado` (mismo número de checks, 25); títulos traducidos | rename §1f, §3.7; i18n §3 |
| `install` | copia hooks, skill y bloque gestionado | retirada de skills (no existe); bloque detectado sin depender del título | rename §1g, §4; i18n «Otras superficies» |
| Mediciones (`scripts/medir_*.py`) | leen log, telemetría y eventos de enfriamiento | leer los dos formatos (P-4 abierta hasta ~2026-12-14; la Mac escribe el viejo) | rename §3.2, §3.8 |
| Prompts al modelo local | en español, sin orden de idioma salvo `local_commit_msg` | piden responder en el idioma elegido | i18n §1h |

## Existing conventions

Mecanismos que ya existen y se reutilizan (tabla completa en rename §4):

- Opción histórica equivalente (`--target` = `--clients`): patrón para el alias de opción.
- Sinónimos obsoletos de un valor con aviso de `doctor` (`residente` → `loaded`).
- Variables retiradas leídas aparte y nombradas por `doctor` (`RETIRED_FAST_ROLE_VARIABLES`,
  `config.py:244`, check `config.rol_retirado`): base del check único de nombres obsoletos.
- `_SCRIPTS_RETIRADOS` en `install.py:102`: borra y desregistra hooks retirados.
- Lectura de dos campos con prioridad (`error_class` o `fallback_class`) y de un fichero heredado
  junto a los rotados (`usage.jsonl`).
- Precedente bilingüe: `site/index.html` (diccionarios `es`/`en`, botones ES/EN, `localStorage`,
  idioma inicial por `navigator.language`, guardián de paridad de claves en `tests/test_site.py`).
- La suite se aísla del entorno vía `config.VARIABLES_DE_ENTORNO` y los helpers `_env*`; un alias
  tiene que leerse por esa puerta con los dos nombres (rename §3.6).

No existe: retirada de skills instaladas, helper común «clave nueva o vieja» para JSON, aviso
genérico de nombre obsoleto, ni nada de i18n.

## Dependencies and integrations

- **Hooks ↔ daemon:** conviven versiones distintas durante una ventana (los hooks solo se reponen
  con `install`/`update`); comparten `enfriamiento.json`, los temporales y la telemetría.
- **`hook_common`** es script instalado y módulo del paquete a la vez.
- **Paridad Python/JS** del panel: `tests/test_dashboard_js.py` extrae funciones JS por su cabecera
  literal; renombrar un lado solo lo rompe en rojo.
- **`precios.json`** lo regenera un workflow (`vigilante-precios.yml`) con `scripts/vigilante_precios.py`.
- **`cuota-statusline.jsonl`** lo escribe código del usuario (contrato documentado en la wiki).
- **Clientes MCP** cachean el esquema de la sesión; el daemon HTTP sirve a varios clientes (PC y
  Mac) con un solo entorno, así que tiene un solo idioma.
- **`argparse`** usa su propio dominio `gettext` para el chrome.
- `agents.py:41` detecta el bloque de delegación por su título en español
  (`Delegaci[oó]n a modelos locales`).

## Risks and unknowns

Confirmados:

- **Pérdida irreversible de historia** si un lector nuevo ignora claves viejas de cachés no
  regenerables (`atribucion-*.json`, puntos de `coste-agregados.json`).
- **P-4** lee `enfriamiento-eventos.jsonl` y valores de `fallos.Clase`; abierta hasta ~2026-12-14.
- **La Mac** escribe el formato viejo hasta que se actualice; sus logs se miden en la PC.
- **Variables vistas por otro proceso:** `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` la fija el lanzador
  del daemon, no la shell del usuario; un aviso que solo mire la shell no la ve.
- **LF/CRLF mezclados** (16 ficheros CRLF, entre ellos `server.py`, `cli.py`, `install.py`,
  `web/metrics.py`); un renombrado masivo con `write_text` los convierte.
- **Guardianes del panel por longitud** (`test_dashboard_ui.py`: «sin prosa», ≥6 palabras) solo
  corren hoy en español; una traducción puede pasar el límite.
- **`test_wiki.py`** compara títulos de checks en español y el número de checks.
- **Adopción:** las descripciones de tools y el texto de los hooks se midieron en español;
  cambiarlos invalida la comparación entre tramos si no se marca la frontera.
- **Prompts del modelo local:** cambiarlos toca calidad medida (afinidad, F2).

Supuestos por validar en el plan:

- (Resuelto en la spec, REQ-044.) Que el detector `esdet.py` se pueda versionar y re-ejecutar sin añadir `wordfreq` como
  dependencia del paquete (solo de desarrollo o con `uv run --with`, con auditoría de Socket).
- (Resuelto en la spec, REQ-018: en Windows manda el idioma de la interfaz.) Cómo obtener el idioma del sistema en Windows (`locale.getlocale()` devuelve `Spanish_Spain`):
  hay que mapearlo, y el idioma de la interfaz puede no coincidir con el del formato regional.
