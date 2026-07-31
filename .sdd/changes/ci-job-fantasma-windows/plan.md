# Plan de implementación (modo lite): acotar el job fantasma de Windows

## Enfoque

La causa está en la infraestructura de GitHub y no es nuestra. Lo que sí es nuestro es que su
fallo se traduzca en una **espera indefinida**: se acota con `timeout-minutes` y se limpia con
`concurrency`. No se intenta curar lo que no se puede curar desde el repo, y eso queda escrito
para que nadie lo intente otra vez desde cero.

## Tareas, en orden

1. **`timeout-minutes` en los cuatro jobs**
   - Ficheros: `.github/workflows/ci.yml`
   - Requisitos: REQ-001, REQ-002
   - Verificación: el YAML parsea y los cuatro jobs lo declaran
   - Reversión: quitar las líneas

2. **`concurrency` que cancela el run anterior, salvo en `main`**
   - Ficheros: `.github/workflows/ci.yml`
   - Requisitos: REQ-003, REQ-004
   - Verificación: el YAML parsea con la expresión; comportamiento observable en el propio PR
   - Reversión: quitar el bloque

3. **El diagnóstico, escrito donde se busca**
   - Ficheros: `docs/wiki/Repo-hardening.md`, `CHANGELOG.md`
   - Requisitos: REQ-005

## Valores elegidos, con su razón

| Job | Duración real | Declarado | Por qué |
|---|---|---|---|
| `lint` | ~20 s | 5 min | 15x de margen |
| `test` | 1 m 23 s en el peor caso (Windows) | 8 min | el que se cuelga; ~5,5x sobre lo peor observado |
| `install-smoke` | ~13 s | 10 min | el más holgado: depende de **PyPI en vivo**, donde un índice lento es espera legítima |
| `secrets` | ~12 s | 5 min | 25x de margen |

**Los valores se ajustaron a la baja durante la implementación.** La primera versión ponía 15 min
en `test`, un número elegido mirando el cuelgue y no la duración real — o sea 10x de margen sin
motivo. Dos datos lo corrigen: el peor caso observado en Windows es **1 m 23 s**, y el reloj del
`timeout` corre sobre la **ejecución** del job, no sobre la espera en cola, así que todo el margen
es para ejecutar. Un timeout demasiado holgado no protege más: solo alarga la espera cada vez que
el job se cuelga, que es justo lo que este cambio ataca.

## Estrategia de pruebas

- **Validación del YAML** antes de empujar: una expresión mal puesta en `concurrency` no rompe un
  job, rompe **el workflow entero**.
- **Los cuatro pasos del CI** en local.
- **Observación en el propio PR:** los jobs deben seguir pasando en su tiempo normal.

## Revisión del plan

- [x] Cada requisito se mapea a una tarea y a una verificación.
- [x] Riesgos cubiertos: un timeout demasiado ajustado (margen 10x y valor justificado en el
      fichero) y perder el run de `main` por `cancel-in-progress` (se excluye `main`).
- [x] Sin dependencias nuevas.
- [x] No incluye trabajo ajeno: no se toca la matriz de sistemas ni se añaden reintentos.
