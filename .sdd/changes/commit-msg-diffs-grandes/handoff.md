# Handoff: local_commit_msg deja de truncar diffs grandes

## Current state

- SDD status: `closed` (modo lite). Los cinco gates aprobados.
- **PR #137 mergeado** (squash) como `ed2db74` en `main`, con los 13 checks en verde — incluidos
  `CodeQL` y `ci-gate`, que llegan tarde. Rama borrada.

## What changed

`local_commit_msg` procesa el diff entero en vez de sus primeros 20 000 caracteres. Siete tareas,
de las que **dos no estaban en el plan original** y salieron de medir contra el backend real:

1-3. Splitter de diff por archivo, inventario calculado sin modelo, y `_chat_map_reduce`
     parametrizable con un reduce propio.
4. Nota de alcance en la salida y error explícito para el diff vacío.
5. La medida contra el backend real.
6. **Reintento cuando un trozo no cabe en el contexto** — el presupuesto está en chars y el límite
   en tokens.
7. **Prompts del map que dan las rutas reales** y declaran qué trozo continúa un archivo.

## Decisions

- **El splitter de diff es global pero se autoinhibe.** Va como nivel 0 de `_SPLITTERS`, y
  devuelve el texto entero si no empieza por una cabecera de diff. Así un Markdown con un diff
  dentro de un fence se sigue partiendo por headers y no puede degradar `local_translate`.
- **El respaldo `--- `/`+++ ` solo se usa si no hay ningún `diff --git`.** En un diff `--git` cada
  archivo trae también su `--- a/x`: cortar por ambas cabeceras partiría cada archivo en dos.
- **El inventario se calcula sin modelo** porque es un conteo, no un juicio, y así no cuesta una
  llamada. Se colapsa por directorio si pasa del 25 % del presupuesto.
- **La nota de alcance va siempre, no bajo `FEEDBACK_ENABLED`**: no es contabilidad de ahorro, es
  lo que impide que procesar de menos vuelva a ser invisible.
- **El reintento por desborde cubre el map y no el reduce**, y eso está anotado como límite
  conocido en `verification.md`, no como cubierto.
- **La calidad se juzga con un diff coherente, no con el grande.** Un rango de seis PRs mezclados
  no tiene un buen mensaje de commit posible; sirve para medir que entra entero, no calidad.

## Next action

Nada pendiente de este cambio. Lo que quedó fuera a propósito y ahora es evaluable sobre una base medida: **filtrar el ruido del
diff** —lockfiles, generados, líneas de contexto sin cambiar—. Reduciría el número de trozos y el
coste; el caso grande son hoy 17 llamadas y 122 s.

## Memory

- Nota canónica: `projects/local-delegate/jornada-2026-08-04-el-diff-que-no-cabia.md`.
- Memoria nueva del proyecto: `presupuesto-en-chars-limite-en-tokens.md`.
- Índices actualizados: memoria de Claude Code del proyecto (jornada, gotcha nuevo, y los
  contadores de `probar-la-pieza-no-es-probar-el-uso` y `un-pendiente-es-una-hipotesis`).
