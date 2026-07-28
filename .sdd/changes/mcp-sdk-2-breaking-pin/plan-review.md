# Plan review: Acotar el SDK mcp por debajo del major 2 y cerrar el punto ciego de resolucion libre

Revisión adversarial del plan, previa al gate `plan`. Fecha: 2026-07-28.

## Limitación declarada

La revisión **no es independiente**: la hizo el mismo agente que redactó el plan, por una
instrucción de sesión que impide lanzar subagentes sin petición explícita del usuario. El
`personal-sdd-plan-reviewer` no se ejecutó. Se deja constancia para que el gate se lea con ese
descuento.

## Findings

### F1 — Bloqueante · La caché de `uv` puede dar un falso verde

El job instala el wheel con `uv pip install` en un entorno limpio, pero **el entorno limpio no
implica caché limpia**. Si el runner tiene `mcp` 1.x en caché, `uv` puede satisfacer `mcp>=1.2`
con esa copia sin consultar PyPI, y el check pasaría **aunque el techo no estuviera puesto**.

Eso destruye el propósito del job: sería un check que no puede fallar, que es exactamente el
problema que este cambio intenta resolver a otro nivel.

**Corrección aplicada al plan:** el paso de instalación fuerza `--refresh` y
`--resolution highest` de forma explícita, para que resuelva contra el índice y tome siempre la
versión más alta admisible. Y la prueba negativa (REQ-005) deja de ser opcional: es la única
evidencia de que el job muerde de verdad.

### F2 — Menor · Falta rollback si `mcp` 1.29.0 rompe la suite

El plan regenera el lock y acepta que la versión suba de 1.28.1 a 1.29.0, pero no dice qué hacer
si la suite falla contra 1.29.0.

**Corrección aplicada al plan:** si ocurre, se estrecha el techo a la última versión buena y se
anota como hallazgo aparte. No se mezcla la investigación de una regresión de 1.x con este fix.

### F3 — Menor · La prueba negativa no queda reproducible

Ejecutarla en local y pegar la salida demuestra el hecho, pero no deja forma de repetirlo.

**Corrección aplicada al plan:** el comando exacto se documenta en `verification.md`, con la
constraint que fuerza `mcp>=2`.

### F4 — Aceptado sin cambio · El job depende de PyPI en vivo

Un PyPI degradado pondría el job en rojo por una causa ajena al cambio. Se acepta: el job **no**
va a ser check requerido (REQ-008), así que un falso rojo no bloquea ningún PR, y el script
distingue en su mensaje un fallo de import de un fallo de red.

### F5 — Fuera de alcance, anotado · Las otras cinco dependencias siguen sin techo

`httpx`, `platformdirs`, `fastapi`, `uvicorn` y `filelock` tienen el mismo patrón que causó este
incidente. No se tocan aquí —mezclarlo convertiría un arreglo urgente en una discusión de política
de dependencias— pero el job `install-smoke` **sí** las cubre indirectamente: si cualquiera de
ellas publica un major que rompa el import, el check lo detecta. Es el argumento más fuerte a
favor de la segunda pieza del plan.

## Verdict

**Sin hallazgos bloqueantes pendientes.** F1 era bloqueante y quedó corregido en el plan antes de
aprobar el gate. F2 y F3 corregidos. F4 aceptado con razón. F5 anotado como seguimiento.
