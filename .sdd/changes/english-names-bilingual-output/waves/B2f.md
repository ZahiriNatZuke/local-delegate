# Ola B2f: `local_lint_summary` conserva los códigos de regla con el rol largo

Rama `sdd/english-names-b2f` desde `main` (`2e25e60`). Ejecuta el lote «B2f» de `plan.md`. Sin
push ni PR. **Estado: LLEGA** con el inventario y la línea «sin mencionar» en la llamada única del
rol largo más el tope doble de esa llamada (regla (2) del usuario).

## Commits

| Commit | Qué |
|---|---|
| `fb75619` docs | sección del lote en el plan, criterio y conjunto de medición congelado |
| `30d6f9a` fix(i18n) | inventario de ficheros y códigos delante del log y línea «sin mencionar» en la llamada única del rol `long`; el mecánico, byte a byte; 7 tests y los mutantes 1–3 |
| `b2885ba` fix(i18n) | tope doble (1 456 tokens) solo en esa llamada; mutantes 4 y 5 |
| (siguiente) docs | medición, plan, frontera del corpus F2 (`user_template` de `lint-9k`), excepción del guardián, CHANGELOG, wiki y este registro |

## Medición

Detalle en `evidence/B2f/live.md`. Misma sesión (07:21–08:33 UTC), 3 repeticiones:

| Grupo | `main` códigos (modelo) | rama c2 códigos / del modelo | cortadas `main` → c2 |
|---|---|---|---|
| G, logs de 8–34 k, `es` | 0,33 | 1,00 / 0,49 | 2 → 0 |
| GE, ídem `en` | 0,93 | 1,00 / 1,00 | 4 → 0 |
| H, pequeños forzados al largo, `es` | 0,17 | 1,00 / 0,96 | 0 → 0 |
| HE, ídem `en` | 0,88 | 1,00 / 0,93 | 0 → 0 |
| M / ME, mecánico (prompt idéntico) | 0,92 / 0,93 | 0,95 / 0,86 (ruido) | 0 → 1 / 0 → 0 |

Ficheros 1,00 en los cuatro grupos largos; invenciones por respuesta 0,64 frente a 0,71 (ruido
0,12); A14/A15/B31/B32 sin invenciones ni cortes. El candidato 1 solo (`30d6f9a`) no llegó por las
cortadas (10 frente a 6).

## Mutantes (`evidence/B2f/mutants.json`)

Los cinco fallan por el assert que dicen: 1 «el prompt de antes» → el inventario no está; 2 «sin
respaldo» → falta la línea; 3 «también el mecánico» → el prompt del mecánico cambia; 4 «el tope de
antes» → 728 ≠ 1 456; 5 «también el mecánico con el tope doble» → 1 456 ≠ 728.

## Verificación

- Suite `-n 2` en `es` y en `en`: `evidence/B2f/suite-es.txt` y `suite-en.txt`.
- `ruff check .` y `ruff format --check .` limpios.
- Corpus: `corpus-f2-check.txt` y `corpus-affinity-check.txt`, `ok`; `lint-9k` cambia su
  `user_template`, declarado en `build_corpus.PROMPT_BOUNDARY_EXTRA_FIELDS` con su test.
- Afinidad: no hay celda de lint desde B2-affinity; la huella de las demás no cambia.
- Lanzador restaurado desde `launcher-backup.ps1` con la huella
  `c96f022aeb1b2570fc273419203f2f870d7a13022c373e35f7ae6af7ae69f69a`; 24 ventanas de prueba
  cerradas por id; árbol `D:/Projects/ld-wt-b2f-main` borrado; daemon con el código final de la
  rama.

## Llamadas `local_*`

**0.** El MCP `local-delegate` no conectó en esta sesión desde el principio (`ECONNREFUSED` al
cargar las tools, con el daemon vivo en el 9393), y un subagente no recupera el MCP. Las respuestas
de la medición no pasaron por el contexto: se puntuaron por programa.
