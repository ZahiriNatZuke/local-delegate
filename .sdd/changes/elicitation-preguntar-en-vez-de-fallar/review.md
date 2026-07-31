# Result review: preguntar en vez de fallar seco

## Verdict

`conforms-with-notes` — los diez requisitos implementados y verificados; las notas son límites de
cobertura declarados, no incumplimientos.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 backend caído | sí | sí | en `_post_chat`, sin tocar el texto del error |
| REQ-002 acepta/declina | sí | sí | tres respuestas cubiertas |
| REQ-003 modelo inválido | sí | sí | acotado a `model` por la revisión del plan |
| REQ-003b sin respuesta, sin backend | sí | sí | el test asevera que no hubo llamada |
| REQ-004 `output_format` en blanco | sí | sí | |
| REQ-005 capability y canal | sí | sí | dos condiciones, tres tests |
| REQ-006 plazo | sí | sí | medido, no cortado desde fuera |
| REQ-007 degradación | sí | sí | |
| REQ-008 configurable | sí | sí | |
| REQ-009 schema intacto | sí | sí | por construcción: no se tocó ninguna firma |

## Findings

1. **El diseño cambió de tamaño gracias a dos mediciones.** El enfoque obvio —convertir la cadena a
   `async` y pasar el contexto por parámetro— habría tocado 15 firmas y cambiado el schema de las
   tools. Medir que `anyio.from_thread.run` funciona desde el hilo, y que un `ContextVar` del
   middleware llega a la capa profunda, lo dejó en **un módulo nuevo y tres puntos de uso**.

2. **La revisión adversarial del plan evitó un fallo silencioso.** El plazo puesto de la forma
   intuitiva lanza `NoEventLoopError`, que el `except` se habría tragado: el síntoma sería «nunca se
   pregunta», sin error visible y con los tests en verde. Se cazó antes de escribir código y se
   confirmó midiendo.

3. **Verificar al revés encontró un hueco real**, no teórico: `decline` tratado como aceptación
   pasaba los 19 tests porque el rechazo lo hacía la validación del esquema, no la comprobación de
   `action`. Con un modelo de campos opcionales, un «no» se habría leído como un «sí».

4. **Un test cazó un defecto de implementación de los caros**: `ServerRequestContext` no tiene
   `.elicit`, así que el mecanismo no habría funcionado nunca y en silencio.

5. **La premisa original del segundo caso era falsa** y se corrigió antes de implementar:
   `output_format` es obligatorio, así que «delegación sin formato» no puede ocurrir; lo que sí
   ocurre es que venga vacío.

6. **El cambio de comportamiento visible está acotado y escrito** (REQ-003b): con respuesta, una
   llamada con el modelo mal escrito pasa a consumir backend. Sin respuesta, falla igual de rápido
   y gratis.

## Required follow-up

- **Nada bloquea el cierre.**
- Pendiente de uso real: ver **cómo presenta cada cliente la pregunta**. Es lo único que no se puede
  saber sin usarlo.
