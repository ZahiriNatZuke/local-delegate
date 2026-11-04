# Brief: local_extract: marcadores de sin dato a null y cuentas de listas vacías

## Problem

`local_extract` devolvía `"N/A"` (y otros marcadores) en vez de `null`, sin `missing_keys` ni
aviso, y daba la cuenta de otra lista para una lista vacía de la entrada JSON (issue #586).

## Desired outcome

Un marcador de sin dato vuelve como `null`, en `missing_keys` y con aviso; la cuenta de una lista
de primer nivel de una entrada JSON la pone el programa.

## In scope

- Normalización determinista en servidor y recuento de listas de primer nivel.

## Out of scope

- Detectar que un campo de texto libre copia otro (queda al prompt).
- El refuerzo del prompt: aplazado, ver REQ-005 de la spec.

## Constraints and risks

- Contrato de `warning` (#455), relleno troceado (#473), campos de ubicación (#568).
- El prompt de extract está congelado en la red del corpus y en fixtures de cuerpos de petición.

## Open questions

- ¿Se declara una frontera de prompt nueva para `local_extract` (REQ-005)? Decide la sesión principal.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-04 Original request, verbatim:

  > Arregla el issue #586 de `ZahiriNatZuke/local-delegate` (léelo con `gh issue view 586 -R ZahiriNatZuke/local-delegate --comments`): `local_extract` devuelve marcadores como `"N/A"` en vez de `null` (y no salen en `missing_keys` ni avisan), y rellena campos cuya fuente está vacía (`"comments": []`) con datos de otro campo o una cuenta copiada de otra lista.

- L2 2026-11-04 Implementado y revisado; PR abierto contra `main`; REQ-005 escalado.
