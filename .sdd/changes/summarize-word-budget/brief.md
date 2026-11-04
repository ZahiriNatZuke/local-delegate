# Brief: local_summarize corta el resumen a mitad de frase con el max_words por defecto (#580)

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

- L1 2026-11-04 Original request, verbatim:

  > Tarea: issue #580 — `local_summarize` corta el resumen a mitad de frase con el `max_words` por defecto (siempre 364 tokens de salida). 1. Causa con evidencia (cómo se calcula `max_tokens` a partir de `max_words`; ratio tokens/palabra real del español con gemma; ¿afecta al resumen por secciones, al map/reduce y a otras tools con `max_words`?). 2. Arreglo: (a) margen de tokens suficiente sobre `max_words` medido con datos reales; (b) si aun así sale `length`, recortar la salida en el último final de frase completo (sin perder estructura Markdown, sin dejar listas o bloques abiertos) y conservar el aviso de truncado con texto que diga que se recortó; valora un reintento solo si es barato y acotado. No cambies el contrato de `max_words` ni la salida de las llamadas que hoy acaban bien. 3. Tests con backend falso, control positivo, tests existentes intactos. Revisa los tests de resumen existentes que fijen `max_tokens`.
- 2026-11-04: implementado y probado; PR abierto contra main; queda la puerta memory para la sesión principal.
