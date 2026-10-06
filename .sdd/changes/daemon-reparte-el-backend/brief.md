# Brief: el daemon no se pelea por el modelo y la residencia es opcional

## Problem

La investigación de `insumos/llamaswap-grupos.md` (2026-10-06, sobre `metrics.db`, los logs de
uso y el código de llama-swap v255) concluye:

- **Cambiar de modelo es inevitable** en una GPU de 16 GB: caben «el pequeño + uno grande», pero
  no dos grandes. Los grupos de llama-swap están bien y no se tocan.
- **El daemon provoca bloqueos que podría evitar.** El 2026-10-01, `local_commit_msg` (modelo de
  código) y `local_lint_summary` (modelo largo) se lanzaron en paralelo y se quitaron el modelo 6
  veces (199 s). En llama-swap, quien pide el otro modelo espera a que el cargado termine todo lo
  que tiene en vuelo, y las peticiones nuevas al modelo cargado pasan delante.
- **Se carga un modelo cuando ya hay otro que podría servir.** El 2026-09-30, dos
  `local_commit_msg` de la Mac esperaron ~47 s cada una a que la PC soltara el 26B.
- **No se distingue la espera de la lentitud.** Ese día, lo que más pesó fue que qwen36 iba a
  6,8–20 tok/s (su mediana es 41,5), probablemente por presión de RAM. Nada lo registra, así que
  «esperó por el cambio de modelo» y «el modelo iba lento» se confunden.
- **Residencia.** El usuario **no quiere ningún modelo residente, nunca, ni siquiera con un TTL
  corto** (decisión del 2026-10-06). Ya se aplicó en esta PC: el grupo `resident` sale del
  config.yaml, gemma3-4b pasa al grupo `swap` con `ttl: 300` y la copia de seguridad es
  `config.yaml.pre-sin-residente-20261006.bak`. Ese mismo día el usuario bajó el TTL de los
  cuatro modelos de texto de 300 a **120 s** (el de visión sigue en 30 s); la copia de seguridad
  es `config.yaml.pre-ttl-120-20261006.bak`. Habrá más recargas: el research lo cuantifica, y el
  CLI tiene que dejar ajustar el TTL por modelo. Motivo: llama-swap está siempre
  corriendo, y un modelo fijo le quita VRAM que necesita, p. ej. para jugar. Hoy ninguno lo es de
  verdad: gemma3-4b está en un grupo `persistent` pero con `ttl: 600`, así que se descarga a los
  10 min, y `persistent` solo evita que lo echen otros grupos mientras está cargado. El usuario
  pide que la residencia quede como **opción configurable desde el CLI**, apagada por defecto.

## Desired outcome

El daemon no manda a la vez dos llamadas que obliguen a cambiar de modelo. Usa el modelo ya
cargado cuando la calidad está validada para esa tool. Registra cuándo una llamada fue lenta por
el modelo y no por la espera. Y el CLI permite ver y cambiar la residencia y los TTL sin editar
el YAML a mano, con «ningún residente» como valor recomendado.

## In scope

- La serialización en el daemon de las llamadas a modelos distintos del mismo grupo `swap`
  (leído de la config de llama-swap, sin dar por fijos los nombres).
- `local_commit_msg` (y quizá otras tools) con el modelo largo cuando ya esté cargado, **solo si**
  la evaluación con el corpus de commits de F2 lo aprueba con un criterio escrito de antemano.
- Registrar en el log de uso la velocidad relativa de cada llamada frente a la normal de su
  modelo, y exponerla en el panel.
- Comando del CLI para ver y cambiar la residencia y los TTL en el `config.yaml` de llama-swap
  (`LLAMASWAP_CONFIG`). Tiene que conservar los comentarios y el formato del YAML, hacer copia de
  seguridad antes de escribir y contar con que llama-swap corre con `-watch-config`.
- Revisar qué hace `cadenas.py` («residente» = el miembro del grupo `persistent`) cuando no hay
  ningún grupo persistente, y que el comportamiento siga siendo el correcto.

## Out of scope

- Cambiar la composición de los grupos de llama-swap o meter dos modelos grandes juntos (riesgo de
  OOM, descartado en la investigación).
- Cambiar los modelos por defecto de los roles.

## Constraints and risks

- **Este cambio va después de `panel-cuentas-y-estados-honestos`**: los dos tocan `server.py` y el
  panel. Spec y plan pueden escribirse ya, pero la implementación espera a que aquel se mezcle.
- La config de modelos se dimensiona para una PC **compartida** (navegador, video, juegos), no la
  del benchmark. Con el perfil del driver «Prefer No Sysmem Fallback», una config al límite da OOM.
- Nunca fijar `--gpu-luid`: reiniciar Windows reasigna el LUID de la GPU.
- Que la serialización no cree un cuello de botella para la Mac: las llamadas remotas también
  pasan por el mismo llama-swap. Un daemon solo ve las suyas, así que hay que decidir si basta con
  coordinar las de una máquina.
- Los mismos del repo: el espejo JS y el test de paridad, el mock de `tests/test_captura.py`, los
  helpers `_env*`, LF/CRLF, el control positivo, probar el uso y no la pieza, el cerrojo de
  comandos pesados, y que una release toca tres sitios (CHANGELOG, README y `docs/wiki/`).

## Decisiones del usuario (2026-10-06)

- El modelo de código y el largo **nunca** caen al mecánico (revierte D-4 de F3).
- Valores por defecto: espera máxima del turno 600 s y umbral de lentitud 0,5. El margen antes de
  la descarga se ajusta al TTL de 120 s (el de 60 s de la primera spec deja el modelo cargado
  inservible pasado su primer minuto).
- **Evaluación de `commit_msg` a ciegas** con cuatro modelos: 30 pares más 3 trampa, mezclados. El
  usuario pidió criterios definidos por caso. Por cada mensaje: **fiel** (sí/no: describe lo que
  hace el diff, sin inventar), **lo principal** (sí/parcial/no: nombra el cambio más importante),
  **específico** (sí/no: se entiende sin abrir el diff) y **formato** (sí/no: una línea de 72
  caracteres como máximo, prefijo convencional y sin adornos). Por par: preferencia A/B/empate.
  Regla de aprobación, fijada antes de ver datos: la casilla se aprueba si «fiel = no» sale en
  menos del 10 % de los mensajes del modelo y, en la preferencia, no pierde contra el modelo de
  código (empates incluidos). Los pares trampa validan que la prueba discrimina; si el usuario no
  marca como peores al menos 2 de los 3, la tanda no es válida y se repite.
- **Regla de aprobación confirmada por el usuario** (2026-10-06, tras explicársela con un
  ejemplo): el modelo cargado vale para `commit_msg` si (1) el usuario elige su mensaje al menos
  tantas veces como el del modelo de código (los «me da igual» no suman a ninguno) y (2) inventa
  algo en menos de 1 de cada 10 mensajes. Si no pasa, `commit_msg` sigue siempre en el modelo de
  código.
- **Dos condiciones más, confirmadas por el usuario** (2026-10-06): el 26B también se descarta si
  falla en alguna de las 3 peticiones del mensaje de un cambio enorme (~156 000 caracteres), o si
  da error o no termina en alguno de los 30 commits en los que el modelo de código sí terminó bien.
- `local_summarize` queda **fuera** de la tabla «usar el modelo cargado» (confirmado por el
  usuario): siempre usa su propio modelo.
- **Confirmado: fuera de alcance** las llamadas que no pasan por el daemon, es decir, la Mac
  contra el llama-swap de la PC (el `/mcp` por tailnet da 421) y Claude Desktop en stdio. Queda
  para un cambio aparte: en 30 días solo hubo 2 peticiones de la Mac bloqueadas.

## Open questions

- ¿La serialización se hace en el daemon (un cerrojo por grupo `swap`) o hay algo en llama-swap
  v255 que ya lo resuelva?
- ¿Cuál es el criterio de calidad para aceptar el modelo largo en `local_commit_msg`, y con qué
  corpus?
- ¿Qué velocidad «normal» se toma por modelo (la mediana histórica de `metrics.db`, o una
  declarada)?
