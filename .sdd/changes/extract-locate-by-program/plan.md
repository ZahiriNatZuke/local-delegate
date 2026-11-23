# Implementation plan: local_extract: las líneas las calcula el programa y el esquema tiene tipos por campo (#692, #694, #696, #697, #698)

## Approach

La lógica de localización sale de `server.py` y pasa a dos módulos de programa puro, sin red ni
modelo, que se prueban por separado. `server.py` solo los conecta. Así trabajan dos personas a la
vez: el **frente A** escribe los índices y las anclas sin tocar `server.py`, y el **frente B**
escribe el contrato tipado y la conexión sin tocar `locate*.py`. Se encuentran en un contrato de
interfaz fijado aquí abajo, que **no se cambia sin avisar al otro frente** (si hace falta, se anota
como desviación en `brief.md` y se avisa a la sesión coordinadora).

Flujo nuevo de un campo de ubicación en `local_extract` con `path`:

1. `locate.build_index(content, path)`: índice del fichero (Python, TS/JS, Markdown, diff, ids).
2. `locate.classify_field(name)`: categorías y resto (REQ-008).
3. `locate.answer_by_program(req, index)`: si contesta, el campo no va al modelo (REQ-009). Si
   todos contestan, no hay llamada y la fila de uso es `program_only`.
4. Si no, al modelo, con rol `code` o `long` (REQ-014), sin números (REQ-012), con el catálogo
   (`locate.catalogue`) y el esquema de `extract_schema` (REQ-015). Si hay elección (REQ-010), el
   `enum` sale de `locate.selectable_names`.
5. `extract_schema.validate`, y un reintento si no cuadra (REQ-016).
6. `locate.resolve(entries, index, content)`: líneas exactas, o null con motivo (REQ-011).
7. `locate.to_value(items)`: forma nueva (REQ-002). Después, `section_only` y los metadatos.

Lo que se retira de extract: la numeración del contenido, `_EXTRACT_LINES_CLAUSE`,
`_extract_outline_block` (con números), `_strip_extract_prefixes`, `_merge_location_values`,
`_extract_location_shortcut` en su forma de valores del modelo, la verificación `raw` de #666 y las
llamadas a `check_values` y `outline_copy`. `_number_lines` y `_numbered_code_pieces` se quedan:
los usa `local_explain_code` (`server.py:9770`, `10009-10012`).

### Contrato de interfaz entre frentes (`src/local_delegate/locate.py`)

```python
Category = Literal["files", "hunks", "declarations", "sections", "ids"]

@dataclass(frozen=True)
class Block:
    name: str                    # "Clase.metodo", ruta del diff, "## Título", "REQ-012"
    kind: str                    # "function" | "class" | "method" | "function_property" | "property"
                                 # | "variable" | "type"  (function_property: flecha, computed, signal, effect)
                                 # | "section" | "file" | "hunk" | "id" | "table" | "list_item" | "fence"
    start: int                   # 1-based, inclusive
    end: int                     # 1-based, inclusive
    hunks: tuple[tuple[int, int], ...] = ()
    top_level: bool = False      # para cortar trozos (REQ-013)

@dataclass(frozen=True)
class FileIndex:
    language: str | None         # "python" | "typescript" | "markdown" | "diff" | None
    blocks: tuple[Block, ...]    # en orden de fichero
    comment_lines: frozenset[int]  # líneas enteras de comentario (código)
    unavailable_reason: str | None = None  # "syntax_error" | "unbalanced" | None

@dataclass(frozen=True)
class FieldRequest:
    name: str
    categories: frozenset[Category]
    kinds: frozenset[str]        # subtipos de Block.kind que pide `declarations` (REQ-008); vacío = todos
    singular: bool               # la categoría apareció solo en singular (REQ-009/010)
    hunks: bool                  # el campo pide hunks (REQ-002)
    ids: tuple[str, ...]         # ids nombrados en el campo, normalizados "REQ-012"
    residual: tuple[str, ...]    # palabras que sobran (REQ-008)

@dataclass(frozen=True)
class Item:
    name: str
    start: int | None
    end: int | None
    hunks: tuple[tuple[int, int], ...] = ()
    reason: str | None = None    # "not_found" | "ambiguous" | "too_short" | "in_comment"
                                 # | "not_in_index" | None
    candidates: tuple[int, ...] = ()
    source: str = "program"      # "program" | "selection" | "anchor"  -> located[campo].by
    index: str | None = None     # "python" | "typescript" | "markdown" | "diff" | "ids" | None
    conflict: bool = False       # nombre y ancla en sitios distintos (REQ-011)
    anchor_end_ignored: bool = False

CODE_LANGUAGES: frozenset[str]   # {"python", "typescript"}
def build_index(content: str, path: str) -> FileIndex
def classify_field(name: str) -> FieldRequest           # solo para is_location_field(name)
def answer_by_program(req: FieldRequest, index: FileIndex, content: str) -> list[Item] | None
def selectable_names(req: FieldRequest, index: FileIndex) -> list[str]   # [] = no hay elección
def catalogue(index: FileIndex, budget_chars: int) -> str               # "" si no cabe; sin números
def resolve(req: FieldRequest, entries: list[dict], index: FileIndex, content: str,
            piece_range: tuple[int, int] | None = None) -> list[Item]    # REQ-011, REQ-013
def merge(items_lists: list[list[Item]]) -> list[Item]                   # unión de trozos (REQ-013)
def to_value(req: FieldRequest, items: list[Item]) -> list[dict] | None  # forma de REQ-002
def split_at_blocks(content: str, index: FileIndex, budget: int) -> list[tuple[str, tuple[int, int]]]
                                                                         # (texto, rango absoluto)
def section_only(req: FieldRequest, items: list[Item], index: FileIndex) -> bool
```

`extract_schema.py` (frente B) solo importa `locate.FieldRequest`, `classify_field` y los tipos, y
no depende de nada más. El `enum` de nombres (REQ-010) lo pasa `server.py` al construir el esquema
en T8; T5 solo acepta una lista de nombres opcional.

`located[campo]` lo arma B con los `Item`: `by` = la `source` de los elementos (la de más
elementos si se mezclan), `index` = el `index` de los ubicados (o `FileIndex.language`), `items`,
`unlocated`, `extra`, `conflicts` y `anchor_end_ignored`.

## Ordered tasks

<!-- One checklist item per task: "- [ ] T<n> — title (REQ-NNN, ...)". Close it with [x]; drop it with
"- [-] T<n> ... dropped: <reason>". Every requirement needs at least one task that is not dropped. -->

Frente A (implementador A). Ficheros propios: `src/local_delegate/locate.py`,
`src/local_delegate/locate_ts.py` y `tests/test_locate_*.py`. En T9, también
`src/local_delegate/line_check.py`.

- [x] T1 — Tipos del contrato, `classify_field` y `to_value` (REQ-002, REQ-008). **Fase 0**: se termina antes de que B empiece T5
  - Files or modules: `src/local_delegate/locate.py` (nuevo), `tests/test_locate_fields.py` (nuevo)
  - Verification: `tests/test_locate_fields.py` con los nombres de REQ-008, más un test de `to_value` (orden, nulls al final, `[]` → `None`, `hunks` solo si `req.hunks`); mutantes «todas las palabras del sujeto en el vocabulario» y «quitar las palabras cortas antes de buscar categorías» en rojo (con `lista_de_ficheros_con_sus_lineas` e `ids_con_lineas`), aplicados y revertidos en esta tarea
  - Depends on: none

- [x] T2 — Índices de Python, Markdown, diff e ids (REQ-003, REQ-005, REQ-006, REQ-007, REQ-022)
  - Files or modules: `src/local_delegate/locate.py`, `tests/test_locate_index_python.py`, `tests/test_locate_markdown_ids.py` (nuevos)
  - Verification: tests de REQ-003, REQ-005, REQ-007 y `test_syntax_error_gives_no_index`; el diff reutiliza `line_check.diff_file_hunks` (un test compara contra él sobre un patch propio, copiado como fixture en `tests/test_locate_markdown_ids.py`, nunca importado de los ficheros que reescribe B)
  - Depends on: T1

- [x] T3 — Analizador de TS/JS y troceado por bloques (REQ-004, REQ-013, REQ-022)
  - Files or modules: `src/local_delegate/locate_ts.py` (nuevo; `locate.build_index` lo llama), `tests/test_locate_index_ts.py` (nuevo)
  - Verification: tests (a) (b) (c) de REQ-004, `test_pieces_cut_at_top_level_blocks`, `test_unbalanced_braces_drop_the_index`; tiempo < 1 s sobre 1 MB sintético
  - Depends on: T1

- [x] T4 — Resolución por nombre y por ancla, respuesta del programa, catálogo, unión y `section_only` (REQ-009, REQ-010, REQ-011, REQ-013, REQ-018, REQ-022)
  - Files or modules: `src/local_delegate/locate.py`, `tests/test_locate_anchor.py` (nuevo)
  - Verification: casos de REQ-011 (mayúsculas que no casan, tabla que contiene la línea, `anchor_end` repetido o solo antes, conflicto nombre/ancla, `\r` suelto), `piece_range` primero (REQ-013), `answer_by_program` por categoría y subtipo (funciones sin clases ni constantes) y `None` en singular, `selectable_names` con y sin resto, `catalogue` sin dígitos de línea y con tope, `merge` sin duplicados, `section_only` sobre `Item`, `test_index_and_anchors_cost_grows_linearly` (crecimiento lineal, REQ-022 cambiado el 2026-11-23)
  - Depends on: T2, T3

Frente B (implementador B). Ficheros propios: `src/local_delegate/extract_schema.py`,
`src/local_delegate/server.py`, `src/local_delegate/resources/i18n/{es,en}/mcp.json`,
`tests/test_core.py`, `tests/test_extract_schema.py`, `tests/test_extract_locate_server.py`,
`tests/test_extract_locate_docs.py` y los cinco ficheros que se reescriben:
`tests/test_extract_line_numbers.py`, `tests/test_extract_section_lines.py`,
`tests/test_extract_field_fidelity.py`, `tests/test_extract_diff_files_and_cut.py` y
`tests/test_extract_diff_files_names.py`. En T8 también las docs.

- [x] T5 — `field_kind` y esquema por campo (REQ-015)
  - Files or modules: `src/local_delegate/extract_schema.py` (nuevo), `server._json_schema_payload` (6509) delega en él; `tests/test_extract_schema.py`, `tests/test_core.py::test_json_schema_payload_*` (cambia)
  - Verification: `test_field_kinds`; `test_json_schema_payload_types_each_field` (ni `list` ni `location` admiten `boolean`; ningún `items` admite objetos libres); mutante «boolean en `list`» en rojo. Para `location`, el esquema usa un `FieldRequest` real de T1 y una lista de nombres opcional (el `enum`)
  - Depends on: T1

- [x] T6 — Validación, un reintento y `type_mismatch_keys`, con avisos es/en (REQ-016)
  - Files or modules: `src/local_delegate/extract_schema.py` (`validate`, `retry_message`), `server.py` (llamada única de `local_extract`, 8888-8914, y filtro de parciales), i18n `mcp.warning.extract_type_mismatch`
  - Verification: los cinco tests de REQ-016; la fila del reintento se pliega (`_fold_retried_row`); y `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_extract_*.py tests/test_core.py` en verde sin tocar los tests «conserva» (incluidos `test_extract_placeholder_values.py`, `test_extract_cross_fill.py` y `test_extract_failed_usage_row.py`)
  - Depends on: T5

- [x] T7 — Tope de salida a la medida (REQ-017)
  - Files or modules: `extract_schema.output_budget`, `server.py` (8893 y los `max_words`/`partial_max_words` del map de extract, 8830-8864), `tests/test_extract_schema.py::test_output_budget`
  - Verification: `test_output_budget`; `tests/test_extract_locate_server.py::test_the_real_max_tokens` (el `max_tokens` que recibe el doble del backend en la llamada única y en un trozo; mutante «512 fijo» en rojo); `tests/test_summarize_word_budget.py` intacto; `tests/test_extract_diff_files_and_cut.py` de #666 sigue rehaciendo en mitades con un doble que corta
  - Depends on: T5

- [x] T8 — Conectar `locate` en `local_extract`, rol de ubicación y metadatos; reescribir los cinco ficheros de tests (REQ-001, REQ-002, REQ-006, REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-018, REQ-019, REQ-022)
  - Files or modules: `server.py` 8560-9247 (sustituye la rama `numbered` y lo que retira el Approach, y deja de usar `_DIFF_LINES_CLAUSE` (5261, uso en 8807) en extract), `_extract_role` (8081) con la razón `location` (`_ROLE_REASON_LOCATION`) y caída a `long` si falta `code`, el `enum` de `selectable_names` al construir el esquema, i18n (`extract_unlocated`, `extract_role_reason_location`, `extract_index_unavailable`; se retiran `extract_lines_unverified`, `extract_outline_copies` y `mcp.extract.diff_files_by_program` si quedan sin uso), `tests/test_extract_locate_server.py` (nuevo) y los cinco ficheros según el inventario de `research.md`
  - Verification: tests de servidor de REQ-001, 002, 006, 009 (con el patch literal de #697), 010, 011 (#694, #696), 012, 013, 014, 018 y el aviso de índice no disponible de REQ-022; los tests «conserva» de `research.md`, sin tocar
  - Depends on: T4, T6, T7

- [x] T9 — Retirar de `line_check.py` lo que extract ya no usa (REQ-018, REQ-019)
  - Files or modules: `src/local_delegate/line_check.py` (frente A): `asks_for_diff_files`, `asks_for_diff_hunks`, `check_values`, `outline_copy`, `section_only` y los auxiliares que queden sin ningún uso (`_items`, `_text_items`, `_text_cites`, `_BOUND_KEYS`… comprobado con `grep` en `src/` y `tests/`). `is_location_field`, `markdown_outline`, `diff_file_hunks`, `check` y `citations` se quedan
  - Verification: `grep -rn` de `asks_for_diff_files`, `asks_for_diff_hunks`, `check_values`, `outline_copy`, `line_check\.section_only` y `def section_only` (este último en `line_check.py`) sin resultados en `src/` y `tests/`; `ruff check .`; tests de explain_code en verde
  - Depends on: T8

- [x] T10 — Documentación y versión (REQ-020)
  - Files or modules (frente B): docstring de `local_extract`, `CHANGELOG.md` (`[Unreleased]`), `README.md`, `docs/wiki/Tools.md` (210-242), `src/local_delegate/resources/skills/local-delegation/SKILL.md` (104-110), `src/local_delegate/resources/memory/local-delegate.md` (21), `tests/test_extract_locate_docs.py` (nuevo)
  - Verification: `test_extract_locate_docs.py`; los tests de docstring que existen (`cross_filled_keys`, `polarity_flipped_keys`, regla de tabla) siguen en verde
  - Depends on: T8

- [ ] T11 — Control positivo y suite completa (REQ-019, REQ-021)
  - Files or modules: `verification.md` de este cambio (tabla de mutantes: mutante, test que falla, assert que dispara); sin cambios de código
  - Verification: cada mutante de REQ-021 aplicado a mano en un árbol de trabajo temporal y revertido (los de clasificación, sobre `locate.py`); `git diff --stat origin/main -- <tests marcados «conserva» en research.md>` vacío; suite completa con `bash ~/.claude/scripts/pesado.sh uv run pytest -n 2` en verde; `uv run ruff check .` y `uv run ruff format --check .`
  - Depends on: T9, T10

### Reparto y orden

| Fase | Frente A | Frente B |
| --- | --- | --- |
| 0 | T1 (B espera) | |
| 1 (en paralelo) | T2 y T3 → T4 | T5 → T6 y T7 |
| 2 | (espera) | T8 |
| 3 (en paralelo) | T9 | T10 |
| 4 | T11 (una sola persona, con la máquina tranquila) | |

Los dos frentes no comparten ningún fichero en la misma fase. `line_check.py` solo lo toca A, en la
fase 3, cuando B ya quitó de los tests y de `server.py` todo uso de lo que se borra. `CHANGELOG.md`
solo lo toca B. Comandos pesados (pytest, ruff sobre todo el repo), siempre con
`bash ~/.claude/scripts/pesado.sh …` y de uno en uno. Durante las fases 1 a 3, cada frente corre
solo sus ficheros de tests.

## Test strategy

- Unit: los índices, la clasificación, las anclas y los tipos son funciones puras, con ficheros
  sintéticos que reproducen la **forma** de cada issue: el `.ts` de 906 líneas y 60 funciones, el
  componente con JSDoc de viñetas, el Markdown de 55 K con 60 requisitos y una tabla, el patch de
  26 ficheros y el Markdown de 6 K con tres reglas. Cada línea esperada se calcula en el test
  buscando el texto (`_line_of`), nunca con un número escrito a mano.
- Integration: `local_extract` con el backend doblado (`_run_chat` sustituido, como en los tests
  actuales). Se cuentan las llamadas (0 en las de solo programa), se mira el rol de cada una y se
  comprueban el prompt (sin números) y la fila de uso.
- Datos que distinguen (memoria `probar-la-pieza-no-es-probar-el-uso`): cada fixture tiene
  elementos parecidos que hay que separar, para que un parecido por palabras falle. Ejemplos:
  - `onSaveOrder` en el JSDoc y en el código;
  - un requisito citado por otro;
  - dos líneas casi iguales para `ambiguous`.
- Control positivo: T11 (REQ-021).
- End-to-end or manual: una sola prueba en vivo al final, **fuera de este encargo**. Se hace con
  `test-window`, la máquina con al menos 8 GB libres y las entradas sintéticas de la causa común
  (§8, A a D) más la de #692. Mide si el modelo copia anclas literales y si llama-server acepta el
  `enum`.
- Security and secret scanning: `personal-security-check` antes de cualquier commit; el analizador
  no ejecuta código (`ast.parse` sin `compile`) y sus regex son lineales (REQ-022).

## Migration and compatibility

- Incompatible a propósito (D3): un valor de ubicación pasa de cadena o forma libre a la lista de
  REQ-002. Va en la 0.54.0, en «Cambiado (incompatible)», con el ejemplo antes y después.
- Claves retiradas de extract: `lines_unverified`, `outline_copies` y `diff_files`. Claves nuevas:
  `located`, `unlocated` y `type_mismatch_keys`. `role_reason` gana la razón `location`.
- Usage log: las filas no cambian de forma. `program_only` sale en más casos y `role_reason`
  puede valer `location`; el panel ya cuenta las dos (#687, #586).
- Vuelta atrás: revertir el PR. No hay datos persistidos con la forma nueva.
- Dependencia: el rechazo de binarios del SDD `text-tools-binary-and-lint-paths` ya está en `main`
  (`ce09fc5a`, #709); las ramas de los dos frentes salen de `origin/main` con ese commit.

## Plan review

- [ ] Every requirement maps to at least one task and verification step.
- [ ] Risky or destructive operations have safeguards and rollback.
- [ ] Dependencies and configuration changes are explicit.
- [ ] The plan does not include unrelated work.
