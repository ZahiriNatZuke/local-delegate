# Brief: Log de uso con proyecto (hash y tipo) y mediciones que apartan el propio repo

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

  > tarjetas de Base fiable del Project 3: guardar el proyecto en cada fila del log de uso (hash y tipo: el propio repo o ajeno); las mediciones de adopcion y el panel apartan el propio repo por defecto y separan hilo principal, subagente y mod

- L2 2026-11-10 Quién decidió (las cinco preguntas abiertas de `research.md`). Las decisiones D1 a
  D5 de `spec.md` las tomó la sesión coordinadora el 2026-11-10, siguiendo en las cinco la
  recomendación de la investigación, y se comunicaron al usuario: `self` por nombre del directorio
  de proyecto más una variable de extras (D1); hash con sal local en `LOG_DIR` (D2); lo que no se
  puede atribuir queda `unknown`, sin estimar por `path` (D3); la telemetría de hooks lleva
  proyecto de aquí en adelante y lo viejo lo resuelve el script (D4); el coste sigue el filtro y
  `local_status` solo añade un recuento (D5). D6 a D8 (mod primero, el respaldo no es un dato,
  `session=` no aparta) las impuso el encargo de redacción, por los hallazgos de la investigación.
  D9 (el filtro mira solo el tipo), D11 (lo `unknown` se queda en los totales) y D12 (la regla lee
  el entorno del proceso) las propuso quien redactó la spec; no consta visto bueno expreso del
  usuario.
- L3 2026-11-10 Revisión adversarial 1 (`plan-review-1.md`): aprobable con cambios, 12 hallazgos,
  todos comprobados contra el código y aplicados en `spec.md` y `plan.md`. D10 se invirtió por
  decisión de la sesión coordinadora: el relleno da proyecto también a las entradas `window` y
  `window+path` y, por `caller_session_key`, a las filas del mod. Lanzar `recompute-cost` de forma
  automática al actualizar queda fuera de alcance, anotado en la spec. Quedan pendientes las
  puertas `spec` y `plan`.
- L4 2026-11-10 Segunda pasada de la revisión 1: cinco bloqueantes resueltos y uno nuevo (A),
  más B a G, aplicados en `spec.md` y `plan.md`. A, según el revisor y aceptado por la sesión
  coordinadora: la línea del mod saca el proyecto de su `session_id` en `record_read` y no de
  `hook classify`, cuya respuesta no cambia (D13; una sesión en dos directorios no tiene proyecto,
  D14). B, según la sesión coordinadora: la lista de proyectos propios se lee igual en todos los
  caminos, así que deja de ser una variable de entorno y pasa a `LOG_DIR/self-projects.json` (D12;
  enmienda la forma de los extras de D1). Quedan pendientes las puertas `spec` y `plan`.
- L5 2026-11-10 Tercera pasada de la revisión 1: aprobable, sin bloqueantes; sus cuatro puntos
  aplicados. La raíz de proyectos de la búsqueda por sesión sale del entorno del proceso, nunca del
  `HOME`/`USERPROFILE` de la petición; la variable de contexto va en la copia suelta de
  `hook_common`; la búsqueda tiene tope de 50 ms y caché por `session_id`; `self-projects.json`
  casa por tramos entre guiones en vez de por subcadena, normaliza en ASCII las dos partes, tiene
  tope de 64 KiB y entra en el test de privacidad. Quedan pendientes las puertas `spec` y `plan`.
