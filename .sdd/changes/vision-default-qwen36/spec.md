# Specification: Modelo de visión por defecto: qwen36-35b-a3b-vision

## Summary

El rol `vision` (`local_describe_image`) pasa a usar por defecto `qwen36-35b-a3b-vision`
(Qwen3.6 35B-A3B con `--mmproj`). Medición del 2026-11-23 en #699: inventó 0 de 9 defectos de
layout, frente a 5 de 9 de `gemma4-12b`. `gemma4-12b` queda como **alternativa ligera
documentada** para máquinas con menos VRAM, elegible con `LOCAL_DELEGATE_MODEL_VISION`.

`doctor` avisa, con el remedio, cuando el backend no sirve el modelo de visión pero sí la
alternativa ligera (el caso de quien actualiza con su catálogo de siempre). En el panel, un
modelo del catálogo del backend que no sirve a ningún rol lleva la etiqueta apagada «SIN ROL» /
«NO ROLE» en vez de no llevar nada.

**Decisión sobre `doctor`:** el rol de visión sigue siendo opcional (un backend en la nube o
una GPU pequeña sin modelo de imagen es una configuración válida, y el test que lo fija no se
toca). Se pasa a `warn` solo cuando el backend sirve la alternativa ligera: ahí se sabe que el
remedio funciona y que, sin él, `local_describe_image` falla tras la actualización. Sin la
alternativa servida, sigue `ok` con la nota, que ahora nombra también el remedio.

**`init-llamaswap` no genera un catálogo:** agrupa modelos que ya están en el `config.yaml`
(`--add-model` añade un `cmd` mínimo sin `--mmproj`). No se le añade generación de catálogo;
la entrada de visión nueva se documenta en la receta de visión. `check-llamaswap` y `benchmark`
no fijan ningún id de modelo (leen el `config.yaml` y `config.MODEL_*`), así que no cambian.

## Requirements

- **REQ-001** — Sin `LOCAL_DELEGATE_MODEL_VISION`, `config.MODEL_VISION` es
  `qwen36-35b-a3b-vision`; la alternativa ligera `gemma4-12b` existe como constante única
  (`config.MODEL_VISION_LIGHT`) que usa `doctor`.
  - Request: "Modelo de visión por defecto → Qwen3.6 35B-A3B con mmproj"; "gemma4-12b se queda como alternativa ligera documentada"
  - Verify: test tests/test_vision_default.py
- **REQ-002** — `doctor` (`service.role_models`) da `warn` con el remedio
  `LOCAL_DELEGATE_MODEL_VISION=gemma4-12b` cuando el modelo de visión no está en `/models` y
  `gemma4-12b` sí; sin la alternativa servida, sigue `ok` y la nota nombra el mismo remedio.
  Los roles de texto se comportan como antes.
  - Request: "Que doctor avise con ese remedio si el rol de visión apunta a un modelo que el backend no sirve; si ya lo hace, compruébalo con un test."
  - Verify: test tests/test_checks_role_models.py
- **REQ-003** — En la tarjeta «Backend» del panel, un modelo sin rol lleva una etiqueta
  `mrole none` con el texto `panel.role.none` («sin rol» / «no role», en mayúsculas por CSS) y
  un `title` `panel.role.none_title`; los modelos con rol no la llevan.
  - Request: "que muestre una etiqueta discreta «SIN ROL» (es) / «NO ROLE» (en), con el mismo estilo que las de rol pero apagada, y un title que diga que llama-swap lo tiene pero ninguna tool lo usa"
  - Verify: test tests/test_dashboard_states.py
- **REQ-004** — La etiqueta apagada se ve bien en claro y en oscuro.
  - Request: "hay que comprobarlo con capturas en claro y oscuro"
  - Verify: manual capturas en evidence/ con scripts/dev/capture_dashboard.py
- **REQ-005** — README, `docs/wiki/` (Configuration, Tools, Troubleshooting), las recetas de
  llama-swap, la skill `local-delegation` (es y en) y el CHANGELOG («Sin publicar», con nota de
  migración) nombran el nuevo defecto y la alternativa ligera con cómo elegirla.
  - Request: "la documentación (README, docs/wiki/, la skill local-delegation del repo, CHANGELOG en «Sin publicar» con una nota de migración"
  - Verify: test tests/test_vision_default.py

## Acceptance scenarios

### Scenario: actualización con el catálogo viejo

- **Given** un backend que sirve `gemma4-12b` pero no `qwen36-35b-a3b-vision`, sin variable
- **When** se corre `doctor`
- **Then** `service.role_models` da `warn` y el remedio dice `LOCAL_DELEGATE_MODEL_VISION=gemma4-12b`

### Scenario: backend sin modelo de imagen

- **Given** un backend que no sirve ningún modelo de visión
- **When** se corre `doctor`
- **Then** `service.role_models` sigue `ok`, con la nota de opcional y el remedio

### Scenario: modelo sin rol en el panel

- **Given** el backend expone `qwen35-2b`, que ningún rol usa
- **When** se pinta la tarjeta «Backend»
- **Then** su fila lleva «SIN ROL» apagada con su `title`, y las demás sus roles

## Edge cases and failure behavior

- Si el usuario fija `LOCAL_DELEGATE_MODEL_VISION=gemma4-12b`, el modelo de visión ES la
  alternativa: no hay nada que sugerir y el caso es el de siempre.
- Ollama: `gemma4-12b:latest` cuenta como `gemma4-12b` (misma regla `_is_served`).

## Non-functional requirements

- Textos de salida en es y en; nombres de código en inglés.
- Sin dependencias nuevas; la config de llama-swap de la PC no se toca.

## Non-goals

- Generar entradas de catálogo con `--mmproj` desde `init-llamaswap`.
- Regenerar las fijaciones de `tests/fixtures/request_bodies` (su entorno fija los modelos a mano).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
