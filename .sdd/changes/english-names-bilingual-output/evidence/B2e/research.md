# B2e: investigación previa (2026-10-17)

Sin cambios de código. `main` = `e0bcf97`. Sección del lote en `plan.md` («B2e — …»).

## De dónde nace

- `git log -1 4d81646` (B2d): «local_explain_code sobre cli.py: lee la entrada entera, pero al
  trocear pierde los subcomandos doctor y benchmark (va al lote B2e)».
- `evidence/B2d/live.md` §3 y `waves/B2d.md` («`explain_code` mejora pero no llega»): 4 trozos,
  9 subcomandos nombrados, faltan `doctor` (`cli.py:1343`) y `benchmark` (`cli.py:1231`,
  `benchmark.add_parser(sub)`, sin el literal en el fichero). Omisión selectiva en el map-reduce,
  no pérdida de entrada; sin las salidas parciales no se separa map de reduce. Una sola llamada.
- Vault `projects/local-delegate/jornada-2026-10-14-noche-frente-b-hasta-b2d.md`: «pierde
  subcomandos al combinar → lote B2e con medición (decisión del usuario)».
- `plan.md`, final de B2d-4: el falso positivo del contador con `build\_corpus.py`.

## Lo que la investigación del troceado dejó y ya está resuelto

`evidence/B2d-fix/investigation-tests/test_chunking_language_investigation.py` sobre `main`:
**12 passed** (A1–A4, la orden de idioma en cada paso; B1, sección vacía; B2, corte por tope). Lo
de B1/B2 lo cerró B2d-2. No entra nada de ahí.

## Comprobación en `main` (sonda con backend falso, `probes/test_b2e_probe.py`, salida en `probes/probe-out.txt`)

Cada test pasa cuando la pérdida está arreglada; hoy **fallan los dos**:

1. `test_lint_reduce_keeps_the_lint_format`: log de ruff de 12 ficheros × 6 diagnósticos con el
   tope a 1 200. El último paso (reduce) lleva `system` = «un ÚNICO resumen global en prosa clara,
   sin repetir ni enumerar los fragmentos» + regla de la cantidad + idioma; **no** lleva «agrupados
   por archivo». Falla en `assert "agrupados por archivo" in reduce_step["system"]`.
2. `test_explain_reduce_inventory_names_the_registered_subcommands`: fichero de 220 `def` de relleno
   y un `build_parser` que registra 14 subcomandos. El inventario del reduce trae `build_parser`
   pero ninguno de los `cmd-zz*`. Tope del reduce: 564 tokens; de cada parcial: 764.

Sonda directa sobre `cli.py` de hoy (`probes/probe_explain.py`): 58 875 chars, tope del rol
`code` 20 000, presupuesto 16 000, **4 trozos**; `build_parser` y `benchmark.add_parser` caen
enteros en el trozo 4 (12 343 chars); el inventario (955 chars) no contiene `doctor` ni
`benchmark`; el fichero registra 16 nombres con literal (`add_parser("…")`) más `benchmark` sin él.

Respuestas en vivo del lint troceado de B2d-2 (tanda C, `LOCAL_DELEGATE_MAX_CHARS_LONG=8000`):
`evidence/B2d-2/live-answers/C43.txt` (biome, 3 trozos) y `C44.txt` (ruff `lint-9k.txt`, 2 trozos)
son dos párrafos de prosa general: ningún código de regla (el log de C44 trae CPY001, D401, S603,
TC003, COM812, PLR2004…), ningún recuento ni línea de total, ningún diagnóstico por fichero en el
formato de la tool. La llamada única de esos mismos logs sí agrupa por fichero: `A09.txt` y
`A14.txt` (biome) y `B25.txt` (ruff `lint-9k.txt`, con COM812, TRY003, T201, PLR2004… y recuentos
por fichero) en `evidence/B2d-2/live-answers/`.

## Contador `scripts/score_lint_fidelity.py` (sonda `probes/probe_counter.py`)

| Caso | Respuesta | Log | Hoy |
|---|---|---|---|
| guion bajo escapado | `scripts/build\_corpus.py` | `scripts/build_corpus.py` | fichero inventado ✗ |
| control | `scripts/build_corpus.py` | ídem | 0 ✓ |
| posición de `tsc` | «posición 52» | `login.page.ts(52,24)` | 52 inventado ✗ |
| versión | «versión 255» | `llama-swap: v255` | 255 inventado ✗ |
| cifra en palabras | «nine instances of T201» | `a.py:3:9: T201 …` | respaldada ✗ (laxo) |

## Entradas que trocean de verdad

`LONG_INPUT_CHARS` = 6 000 (`config.py:300`): por encima, rol `long`, tope 48 000. El lint solo
trocea por encima de 48 000 chars; el conjunto de B2d-2/B2d-3/B2d-4 (10 logs de 0,6–10 k) no
trocea nunca. `explain_code` trocea por encima de 20 000: en `src/` hay 14 ficheros así; con
registros `add_parser`: `cli.py` (17) y `benchmark.py` (2).
