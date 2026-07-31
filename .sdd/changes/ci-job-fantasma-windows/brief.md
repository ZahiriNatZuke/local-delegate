# Brief (modo lite): el job de Windows puede colgarse y bloquear un merge sin límite

## Qué pasó

**Dos veces en dos días**, `test (windows-latest)` se quedó en `in_progress` y bloqueó el merge:
1954 s en el PR #77 y 651 s en el #86, hasta cancelarlo a mano. Lo normal en los 22 runs recientes
son 60–125 s, y **solo esos dos** pasan de 300 s.

El usuario lo señaló como prioridad uno con la razón exacta: *«no podemos tener esa inseguridad o
incógnita de cuándo ese paso va a colgarse y bloquear un merge o un release»*.

## Lo que se encontró

El cuelgue **no es del código**. La API del job devuelve los ocho pasos en `success` —incluido
`Complete job`— con `completed_at: null`: el runner terminó en ~86 s y falta que GitHub cierre el
job.

Se descartó **por ejecución** la causa clásica en Windows, un proceso hijo huérfano reteniendo los
handles: la suite corrida aquí no deja ni un proceso nuevo.

## Resultado deseado

Que un cuelgue de GitHub no se traduzca en una espera indefinida.

## En alcance

`timeout-minutes` en todos los jobs de `ci.yml`, `concurrency`, y el diagnóstico escrito.

## Fuera de alcance

Curar la causa raíz (no es nuestra), reintentos automáticos y tocar la matriz de sistemas.

## Restricciones y riesgos

- Una expresión mal puesta en `concurrency` **rompe el workflow entero**, no un job: hay que
  validar el YAML antes de empujar.
- Un `timeout` demasiado ajustado convertiría un día lento en un rojo que no es del código.
