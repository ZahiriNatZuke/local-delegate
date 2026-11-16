# Brief: local_describe_image no mide: aviso por programa ante alineación, píxeles o saltos de línea (#663)

## Problem

`local_describe_image` afirmó desalineaciones de píxeles y un salto de línea que las medidas del DOM
desmintieron. Un agente que solo tuviera la imagen habría informado de defectos inexistentes. Ni
la descripción de la tool ni la skill advertían de que un modelo de visión no mide.

## Desired outcome

Quien llama sabe, antes y después de llamar, que la respuesta no es una medida: la descripción lo
dice y, cuando la pregunta o la respuesta hablan de alineación, píxeles, tamaños o saltos de línea,
la respuesta termina con un aviso.

## In scope

- Docstring de `local_describe_image`, guarda por programa en la respuesta, skill `local-delegation` (es/en), `docs/wiki/Tools.md`, CHANGELOG, catálogos es/en.

## Out of scope

- El prompt del sistema del rol `vision`: no se toca (un cambio de prompt ya rompió en vivo con tests en verde, y la prueba en vivo no se puede hacer desde un agente).

## Constraints and risks

- La expresión de términos se aplica a la respuesta del modelo (no confiable): solo literales alternados, sin cuantificadores anidados.
- Falsos avisos en descripciones generales que usen esas palabras: el aviso es una línea y no cambia la respuesta.

## Open questions

- Ninguna.

## Log

- L1 2026-11-16 Original request, verbatim:

  > **#663**: `local_describe_image` afirma desalineaciones de píxeles que las mediciones del DOM desmienten. Léelo con `gh issue view 663 --comments`. Arreglo esperado (decide con criterio y justifica): que la descripción de la tool (docstring visible por el cliente MCP, y la doc en `docs/wiki/`) avise de que no sirve para verificar alineación, tamaños ni distancias al píxel y que para eso hay que medir; y/o que el prompt del sistema del rol `vision` le pida no afirmar alineaciones/medidas de pocos píxeles como hechos. OJO: un cambio de prompt ya rompió en vivo con tests en verde; si tocas el prompt, deja escrito en el PR exactamente qué prueba en vivo hay que hacer (imagen, pregunta, qué esperar), porque tú no puedes hacerla.

- L2 2026-11-16 Implementado y verificado en local; PR abierto. Queda el CI y cerrar las puertas.
