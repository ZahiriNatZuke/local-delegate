# Handoff

## Qué se cerró

El panel ya puede distinguir un mes de smoke tests de un mes de trabajo real: el log de uso firma
cada delegación con el cliente MCP que la pidió, `/api/stats` lo desglosa, y la tarjeta de hooks
muestra por qué el hook de lectura se calló en lo que se calló.

Mergeado en **PR #149** (`1c6998c`), con el CI en verde.

## Decisiones que sobreviven a este cambio

- **La identidad viaja en un `ContextVar` que el middleware fija antes de `call_next`.** Ese
  «antes» es el cambio entero: puesto después no firmaría nada. Y las tools son síncronas, así que
  el SDK las corre en el threadpool — que el `ContextVar` cruce ese salto se midió antes de
  diseñarlo.
- **Las líneas sin cliente caen en «desconocido», casilla propia.** Repartirlas entre los clientes
  conocidos inventaría de quién eran; descartarlas descuadraría la tarjeta con el KPI de arriba.
  Un test comprueba que la suma por cliente es el total.
- **Sigue sin haber ninguna tasa de conversión.** Nada enlaza una sugerencia con la delegación que
  vino después. La tarjeta muestra la **selectividad** del hook —de lo que vio, en qué avisó— que
  vive entera dentro de la telemetría y no necesita cruzarse con nada.
- **El desglose por motivo se acota a `category == "read"`.** `motivo` sólo lo escribe ese hook;
  recorrer todos los eventos metería `lint` y `summarize` en «sin registrar» y la tarjeta diría
  que el hook descarta sin motivo la mitad de las veces. Un número que se lee bien y significa otra
  cosa.

## Lo que se corrigió al medir

El SDK **del cliente** rellena `mcp` cuando no se le da `client_info`, así que «sin identidad»
casi no existe visto desde el servidor. El test lo dice ahora tal cual; el camino de omitir el
campo sigue vivo para cuando `client_info` llegue en `None` de verdad.

## Qué queda abierto

- **La captura del README no se regeneró aquí.** Los mocks ya traen `by_client`, `by_motivo`,
  `by_ext` y `read_total` con los números cuadrando, pero la imagen se regenera en la release,
  que es donde el manifiesto la ata a la versión.
- El desglose por cliente sólo tendrá datos hacia adelante: las delegaciones de antes de este
  cambio salen como desconocidas para siempre, que es lo correcto y también un límite.

## Estado del entorno

`local-delegate doctor`: todo a punto. Esta máquina sigue con la 0.24.0 instalada desde el repo;
se normaliza en la próxima release.
