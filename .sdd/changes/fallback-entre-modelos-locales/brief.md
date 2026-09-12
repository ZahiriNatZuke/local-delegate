# Brief: cadena de respaldo entre modelos locales y enfriamiento temporal por modelo

## Problem

Cada tool usa un solo modelo local. Si ese modelo falla (5xx del backend, respuesta rota, un modelo que
se cuelga), la tool devuelve `[local-delegate error]` y el trabajo recae en el agente principal: se gasta
justo la cuota que local-delegate existe para ahorrar. Y si el modelo sigue roto, cada petición siguiente
vuelve a chocar con él, a veces tras esperar hasta 180 s de timeout.

La idea viene de analizar OmniRoute (2026-09-11): sus «combos» de respaldo y su circuit breaker por
conexión. Se toma el diseño, no el código, y **sin salir de la máquina**: el respaldo es otro modelo del
mismo endpoint local, nunca un proveedor externo.

## Desired outcome

- Cuando un modelo falla por un motivo **del modelo**, la tool reintenta una vez con un modelo local
  compatible y avisa de que respondió el respaldo.
- Un modelo que falla N veces seguidas se aparta durante un tiempo acotado y luego se le da una
  oportunidad de prueba. Nunca queda apartado para siempre.
- Cuando no hay alternativa válida, el resultado es **exactamente el de hoy**.

## In scope

- Clasificar los fallos en: del endpoint, de la petición y del modelo.
- Respaldo de un salto por llamada, con cadenas por rol configurables y valores por defecto conservadores.
- Enfriamiento por modelo compartido entre procesos, con espera creciente y tope.
- Observabilidad: qué modelo respondió, en el log, en el panel y en `local_status`.
- Arreglar los dos defectos de clasificación que el respaldo necesita: `content: null` y `ConnectTimeout`.

## Out of scope

- Proveedores remotos o cualquier destino fuera de `LOCAL_DELEGATE_BASE_URL`.
- Tocar la configuración de llama-swap o decidir qué modelos se cargan en la VRAM.
- Respaldo para visión (no hay modelo compatible).
- Enrutado por carga o por VRAM libre (idea 3 del análisis; cambio aparte).

## Constraints and risks

- Un respaldo del grupo `swap` de llama-swap puede expulsar el modelo que usa otra petición u otra sesión:
  por defecto solo se salta al modelo residente.
- Confundir un fallo del endpoint con uno del modelo enfriaría todos los modelos a la vez.
- El respaldo no puede duplicar el peor caso de latencia (180 s por intento).
- Compatibilidad: sin cambios de schema en ninguna tool y sin dependencias nuevas.

## Open questions

Resueltas en la spec, pendientes de confirmar por el usuario en el gate (sección «Decisiones a confirmar»
de `spec.md`):

- ¿Activado por defecto?
- ¿Los timeouts cuentan para el enfriamiento?
- ¿Solo se salta al residente por defecto?
- ¿El rol de código también tiene respaldo por defecto?
