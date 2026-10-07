# Ola de renombrado a inglés — evidencia (2026-10-07)

Decisión del usuario del 2026-10-07, fuera del plan: lo que es código o término de máquina va en
inglés; los textos para personas (mensajes, ayuda del CLI, `doctor`, `local_status`, panel) y la
prosa (comentarios, docstrings, documentos SDD), en español. Alcance: **solo lo que definió esta
rama** (base `git merge-base HEAD origin/main` = `4c7115b`); lo publicado antes queda para el SDD
siguiente. Un solo agente, escritor e integrador; sin commit.

## Cómo se hizo (por programa, por ámbito)

Los scripts viven en el scratchpad de la sesión (`ren/`), no en el repo: usan la lista de palabras
que sacó `wordfreq` (`inventario-ingles/es_candidates.tsv`) y no se añade ninguna dependencia.

1. **Módulos** con `git mv` (conservan el EOL): 5 de `src`, 13 de `tests`, 3 de `scripts`.
2. **Nombres del inventario del grupo A** (nombres que no existían en ninguna definición de la base):
   1 313 nombres más los 20 de módulo, con una tabla `viejo → nuevo` escrita a mano. Al no existir
   en la base, se renombran como token `NAME` en todo `src/`, `tests/` y `scripts/` sin tocar
   ninguna cadena (tokenizador de Python 3.14, que entra en las f-strings). En comentarios y
   docstrings solo se cambian los nombres inconfundibles (con `_` o CamelCase de dos mayúsculas) y
   los que van entre comillas invertidas. Antes de aplicar, un control de colisiones por fichero
   (el nombre nuevo ya existía): 12 casos, resueltos con otro nombre (`puntuar → score_fn`,
   `soltar → release_slot`, `compatibles → compatible_models`…).
3. **Nombres en español que coinciden con el grupo B y se definen en código nuevo** (`modelo`,
   `ruta`, `estado`…; 367 nombres en 2 061 definiciones): **por ámbito**, con `ast`. Locales y
   parámetros, solo dentro de su función; los `keyword=` de las llamadas, solo si la llamada es a
   esa función (si el nombre de la función es ambiguo, solo en el mismo fichero o en ficheros
   nuevos: así no se tocó `main(entorno=…)` de `test_vigilante.py`); los nombres de
   `@pytest.mark.parametrize` con su parámetro; las fixtures nuevas con sus usos; nunca las
   fixtures publicadas (`recargar_config`). Atributos, campos y métodos de clases nuevas, con las
   referencias que infiere **Jedi** (`uv run --with jedi`, sin añadirlo al proyecto), más las que
   Jedi no ve en módulos cargados con `importlib` (corregidas a mano, una por una).
4. **Cadenas de máquina** una a una con reemplazos literales que exigen el número exacto de
   apariciones: claves y valores de `/api/inflight`, del log y de `pace.py`; nombres en
   `monkeypatch.setattr`, `getattr`, `__all__` y `sys.modules`; nombres de logger; rutas de ficheros
   en los tests; opciones de los scripts con su atributo `args.X`.
5. **Variables de entorno**: en código, tests, `CHANGELOG.md` (`[Unreleased]`), `README.md`,
   `docs/wiki/Configuration.md`, `docs/wiki/Tools.md` y `examples/.env.example`. Se leen con los
   ayudantes `_env*`, así que los guardianes de `test_aislamiento_entorno.py` las siguen viendo.
6. **EOL**: un script compara, fichero a fichero, el CRLF/LF del árbol con el de `HEAD` (con el
   fichero de origen en los renombrados). Hubo un fallo y se corrigió: `sed -i` de Git Bash pasó
   `server.py` de CRLF a LF; se restauró y desde ahí todo se editó con Python sobre bytes. Al final:
   52 ficheros comprobados, ninguna diferencia.

## Equivalencias

Las principales están en `spec.md` («Renombrado a inglés del código de esta rama»). Además:

**Opciones y subcomandos de los scripts nuevos** (con el atributo `args.X` correspondiente):

| Script | Antes | Ahora |
| --- | --- | --- |
| `analizar_benchmark.py` | `veredicto-afinidad`, `--reglas`, `--huellas`, `--juicio`, `--solo-mecanicas`, `--tabla` | `affinity-verdict`, `--rules`, `--footprints`, `--judgement`, `--mechanical-only`, `--table` |
| `hoja_pares.py` | `generar-commit`, `leer-commit`, `--trampas`, `--reglas`, `--juego`, `--numero`, `--hoja-dir`, `--clave-dir`, `--respuestas`, `--parcial` | `generate-commit`, `read-commit`, `--traps`, `--rules`, `--trap-set`, `--number`, `--sheet-dir`, `--key-dir`, `--answers`, `--partial` |
| `construir_corpus.py` | `afinidad`, `--privacidad`, `--en-seco`, `--refrescar-fuentes` | `affinity`, `--privacy`, `--dry-run`, `--refresh-sources` |
| `dev/measure_ttl_race.py` | `--decisiones`, `--concurrencia`, `--margen`, `--directorio` | `--decisions`, `--concurrency`, `--margin`, `--directory` |
| `dev/affinity_batch.py` | `--resultados`, `--huellas`, `--ventanas`, `--trabajo`, `--solo`, `--seco`, `--semilla`, `--timeout-techo`, `--sin-sonda`, `--reintentar-errores`, `--rehacer-huellas`, `--una-corrida-de-techo`, `--fuente` | `--results`, `--footprints`, `--windows`, `--work-dir`, `--only`, `--dry`, `--seed`, `--ceiling-timeout`, `--no-probe`, `--retry-errors`, `--redo-footprints`, `--one-ceiling-run`, `--source` |
| `measure_slowness.py` | `--copia`, `--origen`, `--desde`, `--hasta` | `--copy`, `--source`, `--since`, `--until` |
| `tests/fake_llama_server.py` | `--retraso`, `--registro`; JSONL `evento` (`llegada`/`fin`), `modelo`, `marca`, `ruta`; cuerpo `retraso_s` | `--delay`, `--record`; `event` (`arrival`/`end`), `model`, `mark`, `path`; `delay_s` |

**Panel (JS)**: `palabrasTurno → turnWords`, `turnoTxt → turnText`, `turno → turnChip`,
`turnos → turnParts`, `partes → parts`, `lista → bucket` (dentro del `forEach` nuevo); claves
`it.espera_local → it.local_wait`, `it.turno_en_uso → it.turn_in_use`; valores `'turno' → 'turn'`,
`PALABRAS_ESPERA.plaza → PALABRAS_ESPERA.slot`. El test de paridad del panel
(`test_panel_estados.py`) extrae `turnWords` con el nombre nuevo y sigue en verde.

**Cuántos**: unos 1 700 nombres distintos (1 330 de la tabla del grupo A con los módulos, 366 por
ámbito y 8 que el clasificador no veía: `cola`, `concedible`, `par`, `pico`, `temporal`,
`comilla`, `registrar` y `tic`), más 4 variables de entorno, 17 campos o valores de máquina del producto (y 7 del servidor falso
de los tests), 43 opciones o subcomandos de scripts, y 6 identificadores y 4 claves o valores del
panel.

`espera_local` (excepción acordada): antes de cambiarlo se comprobó que no se persiste. Solo lo
escriben `_inflight_espera_local` y `inflight_snapshot` (`server.py`) en la entrada en vuelo
(`inflight.json`, que se reescribe sin historial, y `/api/inflight`); `_log_event` no lo copia, y
el inventario de claves en disco (`claves_en_disco.out`: `usage-202609/202610.jsonl`, telemetría de
hooks, enfriamiento, coste, atribución) no lo contiene. Se cambió también en
`docs/wiki/Savings-and-metrics.md`, que lo documentaba.

## Control «no queda español en el grupo A»

`ren/control_es.py` recorre el código del grupo A —los ficheros nuevos enteros y las funciones y
clases nuevas de los ficheros modificados— y sale con código 1 si queda algún nombre **definido**
(función, clase, método, parámetro, local, constante, atributo, campo, alias) con una palabra
española del mismo clasificador del inventario. Permitido: `recargar_config`, fixture publicada que
estos tests usan como parámetro.

Árbol final:

```
control: 0 nombres en español definidos en código del grupo A (21 permitidos)
exit=0
```

Control positivo (puede fallar): se plantan nombres en español y se ve caer; después se restaura.

```
# en un fichero nuevo (src/local_delegate/turn.py), def planted_check(modelo_plantado): ventana_de_prueba = …
ESPAÑOL  src/local_delegate/turn.py  planted_check  local  ventana_de_prueba  593
ESPAÑOL  src/local_delegate/turn.py  planted_check  param  modelo_plantado    592
control: 2 nombres en español definidos en código del grupo A (21 permitidos)
exit=1
# en una función nueva de un fichero modificado (tests/test_cadenas.py), resultado_plantado = 1
ESPAÑOL  tests/test_cadenas.py  test_planted_in_b_file  local  resultado_plantado  500
control: 1 nombres en español definidos en código del grupo A (21 permitidos)
exit=1
```

Restaurados los dos ficheros, el control vuelve a `exit=0` y `git diff` no tiene `planted`.

Además, una pasada con `wordfreq` sobre **todos** los nombres definidos en código del grupo A
(1 811 nombres) con un umbral más laxo encontró los 8 que el clasificador no veía (arriba); tras
renombrarlos solo quedan `arg`, `meta`, `topo`, `buf`, `FakeLlamaSwap` (`llama`) y
`recargar_config`, que no son español.

## Comprobaciones

- Suite completa (`bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider`):
  `2180 passed, 2 skipped, 1 warning in 211.20s (0:03:31)` — el mismo número que antes. El aviso
  es la deprecación de `anyio` en `starlette`, de antes. Una pasada intermedia dio 4 avisos: la
  clase `ModeloPrueba` traducida como `TestModel` la quería recolectar pytest; quedó `FakeModel`.
- `uv run ruff check .` → `All checks passed!`; `uv run ruff format --check .` →
  `176 files already formatted`.
- `node --check` del `<script>` de `metrics.HTML` extraído a `<scratchpad>/panel.js`: sin errores.
- Config real de llama-swap: `sha256` =
  `7F763F8538FD719FD3C8DD4FC3C1F6BFBF6C2543FEF3E67C2D8EBAD3A5FB68F0`, sin tocar. No se habló con
  `9292` ni con el daemon instalado.
- EOL: igual que en `HEAD` en los 52 ficheros tocados.

Fallos que la suite encontró por el camino y su causa (todos corregidos):

- `keyword=` que eran **claves de datos**: el paso global renombró `asunto=` en `entry.update(...)`
  y `discriminante=`/`rol_en_hoja=`/`puntuador=` en `_affinity_entry(**extra)` de
  `construir_corpus.py`, que escriben `cases.json`; se devolvieron al español. Un script lista todos
  los `keyword=` renombrados que van a `dict`, `update` o funciones con `**kwargs`, contra el texto
  de `HEAD`: no queda ninguno.
- Referencias que Jedi no infiere (módulos cargados con `importlib`, `isinstance` previo):
  `topology.leer`, `References.medir`, `FakeLlamaSwap.puerto`, `Loaded.datos`, `State.cola`,
  `photo.motivo`… corregidas una a una.
- Un método publicado del mismo nombre: `_ModeloVigente.campos_de_log` (grupo B) se había
  renombrado junto con el nuevo `_OperationTurn.campos_de_log`; se devolvió.
- Traducciones que el contexto desmentía: `_siguiente_salto` es el siguiente **salto** de la cadena
  (`_next_hop`, no `_next_newline`) y `Decision.para(op_id)` es «la concesión **para**»
  (`grant_for`, no `stop_server`).

## Lo que quedó fuera a propósito

- **Grupo B** (lo hará el SDD siguiente): módulos publicados (`cadenas.py`, `fallos.py`,
  `enfriamiento.py`…), sus nombres aunque los use código nuevo (`_inflight_espera_local`,
  `cadenas.resolver(...).modelos`, `fallos.Clase.MODELO`), la fixture `recargar_config` y las
  opciones viejas que el subcomando nuevo de `construir_corpus.py` repite para ser coherente
  (`--destino`, `--comprobar`).
- **Funciones viejas modificadas por la rama**: el control mira funciones y clases **nuevas**; una
  local nueva dentro de una función publicada no entra (por ejemplo, `_ModeloVigente.campos_de_log`
  conserva su `campos`).
- **Datos guardados en el repo y sus claves**: las de `benchmarks/afinidad-2026-10/` (`asunto`,
  `discriminante`, `rol_en_hoja`, `puntuador`, `huella`, `privacidad` con sus valores `fallar` y
  `excluir`, `latencia_ms`…), las de la huella (`modelo`, `ruta`, `tamano_bytes` en `huellas.json`)
  y la clave `modelo` de los eventos de `pace.py`, que copia las filas de `metrics.db`.
- **Fixtures de datos**: `tests/fixtures/residencia/` y `tests/fixtures/topologia/` (y sus
  `hoy.yaml`, `pre-sin-residente-*.yaml`) conservan nombre y ruta: son datos, y las evidencias de
  T7 y T11 los citan.
- **Las claves del informe de `measure_slowness.py`** (`marcados`, `esperadas`, `ventana`,
  `falsos_positivos_largos`…): son la salida que cita la evidencia de T3; se renombraron solo las
  que vienen de `pace.py` (`pace_rel`, `slow`).
- **Motivos de `NoTopology` que se enseñan tal cual** (`ilegible`, `sin LLAMASWAP_CONFIG`,
  `dos sintaxis`…): salen en `doctor` y en `local_status` («Turno: no (ilegible)»), así que cuentan
  como texto para personas.
- **Evidencias y secciones cerradas** de `verification.md`, `review.md` y `evidencias/T*.md`: son
  historia y citan los nombres viejos.

## Decisiones propias

- `para` del inventario tenía dos sentidos; aquí era «la concesión para `op_id`»: `grant_for`.
- Nombres en inglés para lo que T14 y T15 todavía tienen que crear, escritos en `plan.md` para que
  las olas siguientes no nazcan en español: `SLOW_THRESHOLD` (`LOCAL_DELEGATE_SLOW_THRESHOLD`),
  campos `inference_ms`, `wait_ms`, `free_ram_mb`, `slowMark` en el panel, `matrix.py`,
  `tests/test_slowness.py`, `tests/test_affinity.py`, `Cell(...)`, `is_current`,
  `choose_without_waiting`, `wait_for_grant`, `routing: "affinity"`, `affinity_foreign_flight`,
  `affinity_failed`.
- Las claves de la huella se quedan en español aunque `footprint.py` sea nuevo: están en
  `benchmarks/afinidad-2026-10/huellas.json`, cuyo `sha256` citan las evidencias.
- Las opciones de los scripts B nuevas en esta rama sí se pasaron a inglés (son interfaz nueva);
  las que repiten opciones publicadas del mismo script, no.
- Colisiones con nombres que ya existían en la función se resolvieron con un `_` final
  (`model_`, `server_`, `request_`, `cases_`, `pair_`), igual que hace Python con los reservados.

## Llamadas `local_*`

Ninguna. Motivo: todo el trabajo fue mecánico **sobre código** (renombrar con `ast`, `tokenize` y
Jedi, comprobar con la suite) y la salida que había que leer era corta o había que citarla literal
(la línea de pytest, el control); no hubo prosa larga que resumir.
