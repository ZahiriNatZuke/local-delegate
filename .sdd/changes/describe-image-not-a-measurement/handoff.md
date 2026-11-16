# Handoff: local_describe_image no mide: aviso por programa ante alineación, píxeles o saltos de línea (#663)

## Current state

- SDD status: verificando; las puertas quality, conformance y memory se pasan con el CI en verde
- Last completed gate: plan
- Current revision: rama `fix/describe-image-not-a-measurement`

## What changed

- Docstring de `local_describe_image`: no mide; para alineación, tamaños, distancias o saltos de línea hay que medir en el DOM.
- `_MEASUREMENT_TERMS` + `postprocess`: aviso detrás de la respuesta del modelo cuando la pregunta o la respuesta usan esas palabras (es/en).
- Skill `local-delegation` (es/en), `docs/wiki/Tools.md`, CHANGELOG, catálogos.

## Decisions

- No se toca el prompt del rol `vision`: un cambio de prompt ya rompió en vivo con tests en verde y desde un agente no se puede probar contra el backend; una guarda por programa no depende de que el modelo obedezca.
- Falsos avisos aceptados: una línea, la respuesta no cambia.

## Next action

- Esperar el CI del PR y cerrar las puertas.

## Memory

- Canonical note: este handoff y el Log del brief
- Indexes updated: ninguno
