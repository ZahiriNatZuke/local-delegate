# Brief: local_extract: aviso de valor cruzado entre claves y subida al rol long en tablas (#586)

## Problem

TBD

## Desired outcome

TBD

## In scope

- TBD

## Out of scope

- TBD

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-10 Original request, verbatim:

  > resolver los issues abiertos (#586) y las tareas del proyecto de github para el dia de hoy: avisar cuando un valor viene de la fila de otra clave pedida, y mandar al rol long las tablas y los extract con muchos campos parecidos; medir antes de decidir
- L2 2026-11-10 Spec y plan redactados; revisión adversarial en `plan-review-1.md` (aprobable con
  cambios). Decisiones tomadas por la sesión coordinadora tras esa revisión, registradas en
  `spec.md` como D6 a D9: la puerta va por un segundo proceso unido al turno real (lanzarlo con la
  credencial exige el visto bueno del usuario; si no, reinicio del daemon avisando antes); el
  conjunto nuevo lo escribe un agente que no ha visto el detector, con cupos de formas; el
  detector tiene interruptor (`LOCAL_DELEGATE_EXTRACT_CROSS_FILL`) y campo `cross_fill` solo en el
  log; el #586 se cierra solo si pasan la puerta y la prueba en vivo, diciendo en la primera línea
  que el caso reportado no queda arreglado, y con un issue público de seguimiento; la regla de la
  tabla sigue encendida por defecto (D1). Queda: aprobar las puertas `spec` y `plan`, y T1.
- L3 2026-11-10 Segunda pasada de la revisión (sin bloqueantes), aplicada con decisiones de la
  sesión coordinadora: puertas separadas para el enrutado y el aviso, con la bifurcación escrita
  antes de medir (si pasa el enrutado y falla el aviso, el enrutado se publica y el aviso vuelve a
  diseño); el detector pasa también sobre las respuestas anotadas a mano (0 avisos); presupuesto
  del detector con constantes y test que cuenta comparaciones; fallos fuera del daemon a stderr;
  identidad de la lista de marcadores en el test; la copia del lanzador borra `LLAMASWAP_CONFIG`.
  Queda: aprobar las puertas `spec` y `plan`, y T1.
- L4 2026-11-10 T1 medida (`verification.md`, «Puerta (T1)»). Enrutado: pasa (0 de 8 cruces con
  el modelo grande por el producto, 0 de 44 claves falladas, ni `error` ni `raw`, mediana 2,944 s,
  `extraer-toml-2k` sin tabla); con una sola clave 7 de 8 cruzan, así que no hay mínimo de campos.
  Aviso: falla (1 aviso en falso en cada pasada, `c01/price`). La sesión coordinadora aplicó la
  rama «el enrutado pasa y el aviso falla»: los requisitos del aviso pasan a «Non-goals», T4 y el
  commit del aviso quedan `[-]`, el detector se congeló sin la corrección de plurales, y `c20` y
  `c19` van al issue de seguimiento. Queda: T2, T3, T5, T6, T7 y T8; la transición en
  `state.json` la anota la sesión coordinadora.
- L5 2026-11-10 Cierre. T2, T3, T5, T6, T7 y T8 hechas; el PR #643 se mezcló en `main` a las 16:44
  (hora de Uruguay), después de la prueba en vivo (ventana `w-20261110T190517Z`, 26 llamadas,
  `gate/score_live.py` → `pass: true`, 0 cruces de 8, mediana 3,09 s). #586 cerrado con comentario
  y seguimiento público #650. Revisión de resultado de nivel `deep` (dos jueces y revisor de
  seguridad, `review.md`): `conforms-with-notes`, sin bloqueantes; los arreglos de registro (CI,
  enlaces, inferencia caso a caso) ya están en `verification.md`. Queda: las puertas `quality`,
  `conformance` y `memory`, y mover la tarjeta del tablero del enrutado a «Hecho».
