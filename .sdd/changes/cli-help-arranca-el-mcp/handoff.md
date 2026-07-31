# Handoff: `local-delegate --help` arranca el servidor MCP en vez de imprimir la ayuda

## Estado actual

- SDD status: `closed`
- Último gate completado: `memory`
- Revisión: mergeado en `main` con el PR **#63**, con sus 12 checks verdes, y publicado en la
  **0.15.0**. Verificado de nuevo por ejecución el **2026-07-31**.

## Qué cambió

`local-delegate --help` no imprimía nada: salía con código 0 y cero bytes de ayuda, porque había
arrancado el servidor MCP. El despacho decidía si era un subcomando comparando contra una **lista
literal de nombres** escrita a mano, y `--help` no estaba en ella, así que caía al camino del
servidor. El arreglo es quitar una condición: en vez de preguntar *cuál* es el argumento, se
pregunta *si hay* argumentos. Sin argumentos arranca el MCP —que es como lo lanzan Claude Code y
Codex—; con cualquier argumento, manda `argparse`.

De paso se borraron **las dos copias** de la lista de subcomandos, que eran la misma verdad
duplicada: una de ellas (`cli.KNOWN_COMMANDS`) ya era código muerto y no la leía nadie.

## Decisiones que no se deducen del código

1. **La condición correcta es «¿hay argumentos?», no «¿es un subcomando conocido?».** Una lista
   literal de nombres se separa del parser en cuanto alguien añade un subcomando y se olvida de
   la lista — que es exactamente lo que había pasado. Con la pregunta nueva, dar de alta un
   subcomando en `build_parser` basta, y hay un test que recorre el parser y despacha todos sus
   subcomandos para que nadie tenga que acordarse de un segundo sitio.

2. **El aviso de arranque solo se emite si hay terminal, y solo por `stderr`.** Un host MCP
   habla por `stdout` en `stdio`: escribir ahí una línea de cortesía rompería el protocolo.

3. **El import de `cli` es incondicional y es seguro sin el extra `[llamaswap]`**, verificado
   antes de planificar: `llamaswap_config.py` deja `yaml=None` en un `try/except`.

## Gotcha registrado

**En Git Bash, `/dev/null` es `NUL` y hace que `isatty()` devuelva `True`.** O sea que redirigir a
`/dev/null` **no** simula «sin terminal» en Windows, y el caso del host MCP hubo que verificarlo
con una tubería real.

## Verificación fresca (2026-07-31)

- `local-delegate --help` imprime `usage:` con los ocho subcomandos y sale **0**.
- Un subcomando inexistente (`doctro`) sale **2**.
- `KNOWN_COMMANDS` no aparece en `src/`, `docs/` ni `scripts/`: su única mención es el test que
  asevera que el atributo **no existe**.

## Siguiente acción

Ninguna. El cambio está mergeado, publicado y verificado.

## Memoria

- Nota canónica: `projects/local-delegate/jornada-2026-07-30-checks-y-el-cli-que-no-existia.md`.
- Índices actualizados: la memoria de proyecto de Claude Code ya apunta a esa nota.
- Sin secretos ni datos personales.
