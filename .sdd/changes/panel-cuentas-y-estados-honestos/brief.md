# Brief: el panel cuenta bien, dice la causa real y se presenta coherente

## Problem

El usuario mandó cuatro capturas del panel el 2026-09-30 (tres desde una Mac con cómputo remoto y
una desde la PC). Las auditorías de `insumos/` las contrastaron con el código:

- **Las cuentas inflan el ahorro.** Una llamada fallida suma a «Contexto conservado» (en la Mac
  pasó de 8003 a 13.726 solo con fallos), y «Generado en local» suma el texto del mensaje de
  error como si fuera salida del modelo. El «N estimado(s)» cuenta exactamente esos fallos. El log
  real de la Mac lo confirma: las cinco líneas `ok: false` llevan `chars_out: 144`, que es el
  mensaje de error.
- **«Contexto conservado» es bruto.** No resta la respuesta de la tool, que sí entra al contexto
  (septiembre: ~976 k frente a 72 k tokens; ver `../coste-api-y-cuota/insumos/viabilidad-cuota.md`
  §1).
- **Los estados no dicen la causa.** El badge dice «CAÍDO» a secas, y ni el panel, ni
  `local_status`, ni `doctor` distinguen «no se resuelve el nombre», «no hay ruta / timeout de
  conexión», «conexión rechazada», «token rechazado (401)» y «el backend responde con error».
  `doctor` llega a ofrecer arrancar el backend en una máquina con cómputo remoto. El caso real: la
  Mac tenía una VPN corporativa y sus cinco fallos son `connect_error` con `error_class:
  endpoint` y unos 75 s de latencia. Ojo: 75 s es el timeout de conexión TCP de macOS, así que la
  causa puede ser la **ruta** secuestrada y no el DNS (un fallo de DNS es inmediato). Es una
  hipótesis; el clasificador tiene que distinguirlas con pruebas, no suponerla.
- **Mensajes y estados engañosos.** «sin datos (requiere llama-swap ≥ v236)» sale ante cualquier
  fallo (la PC corre la v255). La lista de modelos cambia de contenido y de orden según haya
  conexión. «procesando» tapa el estado real, sea esperar turno en el grupo `swap` o cargar.
  «EN CURSO» enseña una tarea terminada. Con cómputo remoto, el panel Sistema dice «Ningún proceso
  del backend detectado». El sondeo de 2 s puede solaparse consigo mismo.
- **Presentación incoherente.** Tipografía por rol y no por clase (`insumos/tipografia-panel.md`).
  Los números de 4 cifras salen sin separador junto a otros con separador, y los decimales con
  punto. La latencia se muestra en ms con separador de miles («116.948 ms»). El plural sale como
  «estimado(s)».

## Desired outcome

Las cifras del panel solo cuentan trabajo que salió bien y descuentan lo que sí entró al contexto.
Cuando el backend no está disponible, el panel, `local_status` y `doctor` dicen **qué** falla y
**dónde** (host). La presentación sigue un sistema tipográfico y numérico único.

## In scope

- La contabilidad (Python `_accounting` y su espejo JS, atados por el test de paridad): excluir
  los fallos del ahorro y de lo generado, y definir la cifra neta de contexto conservado. Los logs
  históricos se recalculan solos, porque el panel calcula desde el log.
- Clasificar el fallo de conexión al backend (DNS, timeout o sin ruta, rechazo, 401, error HTTP)
  de forma compartida por el panel, `local_status` y `doctor`, con el host en el mensaje.
  `doctor` no ofrece arrancar un backend remoto.
- Estados del panel: mensaje de versión solo si falta versión, lista de modelos estable (mismo
  contenido y orden con y sin conexión), estado del modelo que distinga cargando de esperando
  turno, «Última» en vez de «EN CURSO» cuando ya terminó, textos del panel Sistema con cómputo
  remoto y en macOS, y sin solape del sondeo.
- Presentación: arreglos de tipografía de la auditoría, agrupación de miles siempre, coma decimal,
  latencia en segundos y plural correcto.
- Docs: `docs/wiki/` del panel y `[Unreleased]` del CHANGELOG. **Sin release.**

## Out of scope

- Coste a precio de API y % de cuota: es el cambio `coste-api-y-cuota`, que depende de la
  definición de contabilidad de este.
- Corregir la conversión chars/4 a tokens: depende de un experimento del otro cambio.
- La configuración de grupos de llama-swap: es una investigación aparte.
- Publicar versión.

## Constraints and risks

- **Dos fuentes para el mismo dato**: toda regla de contabilidad va en Python **y** en el espejo
  JS, y el test de paridad (corre el JS con node) tiene que cubrir los casos nuevos: fallo, neto.
- `tests/test_captura.py` compara los `/api/*` que pide la página con los que intercepta el
  script de captura del README: un endpoint nuevo necesita su mock.
- Las opciones nuevas usan los helpers `_env*` (guardianes en `tests/test_aislamiento_entorno.py`).
- El repo mezcla LF y CRLF fichero a fichero: compruébalo con `git ls-files --eol` y no conviertas
  ficheros sin querer.
- Control positivo: cada test nuevo tiene que fallar con el código viejo, y por el assert que dice.
- Probar el uso, no la pieza: el clasificador se prueba con fallos reales (nombre que no resuelve,
  puerto cerrado, IP sin ruta con timeout corto), no solo con excepciones simuladas.
- Comandos pesados (pytest, navegador) siempre con `bash ~/.claude/scripts/pesado.sh <comando>`,
  uno a la vez en toda la máquina.

## Decisiones del usuario (2026-10-06)

- Acepta que las cifras históricas de ahorro bajen (septiembre −11 %, agosto −32 %) al dejar de
  contar los fallos.
- **Entran en el alcance** dos cosas que la primera spec dejaba fuera: (a) el plazo de **conexión**
  de las delegaciones baja de 180 s a 10 s (solo conectar; el de lectura de la respuesta no
  cambia); (b) el badge solo pasa a «CAÍDO» tras **dos sondeos fallidos seguidos**.
- Autoriza reinstalar y reiniciar el daemon en la verificación final, y correr `doctor` y
  `local_status` contra él.

## Open questions

- ¿El neto descuenta también las relecturas del mismo fichero, o solo la respuesta de la tool?
- ¿Cómo se distingue en la práctica «esperando turno» de «cargando» con lo que expone llama-swap
  v255 (`/running`, estados `starting`/`ready`)?
- ¿`doctor` y `local_status` comparten el clasificador con el panel sin duplicarlo?
