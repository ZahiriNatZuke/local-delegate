# Result review: El puerto del daemon exige token cuando se configura uno

## Verdict

`conforms-with-notes`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 `401` sin credencial | Sí | Sí, e2e | Las 5 superficies del puerto |
| REQ-002 Bearer y Basic | Sí | Sí, e2e + unit | Usuario indiferente; token con `:` soportado |
| REQ-003 `WWW-Authenticate` | Sí | Sí, e2e | `realm="local-delegate"` |
| REQ-004 sin token, nada cambia | Sí | Sí, mutante | `proteger()` devuelve el mismo objeto |
| REQ-005 `lifespan` intacto | Sí | Sí, unit | Falla con assert propio |
| REQ-006 el CLI se autentica | Sí | Sí, unit + e2e | Las dos `query_*` doblada cada una por separado |
| REQ-007 el secreto no se escribe | Sí | Sí | Claude Code medido; Codex por lectura de su fuente |
| REQ-008 diagnóstico honesto | Sí | Sí, e2e | Se apoya en el `realm`, no en el código de estado |
| REQ-009 no imprime el token | Sí | Sí, unit | Detalle y `fix_hint` |

## Findings

1. **Menor — la propiedad de tiempo constante no está cubierta por ningún test.** El mutante
   `compare_digest` → `==` deja la suite verde. Se documenta como limitación en `verification.md`
   en vez de darla por probada. No bloquea: el código correcto está puesto.
2. **Menor — Codex no se ejerció end-to-end.** El bloque TOML es válido y usa la clave que su
   propio validador exige (`bearer_token_env_var`, con `bearer_token` literal prohibido en ese
   transporte), pero no se arrancó Codex contra un daemon protegido. Claude Code sí se midió.
3. **Informativo — el change creció respecto al plan inicial**, y con razón: el e2e destapó que
   proteger el puerto convertía un mensaje correcto del `doctor` en uno falso («no es nuestro
   daemon» sobre el propio daemon). Corregirlo entró en alcance porque era un defecto **causado
   por este cambio**, no una mejora aparte.
4. **Informativo — la premisa del backlog sobre «dos apps que cubrir» era inexacta.** Hay una sola
   raíz con el dashboard montado; una puerta las cubre. Abarató el trabajo y está anotado en
   `research.md`.

## Required follow-up

- Ninguno para cerrar.
- Para el backlog, no para este change: **probar Codex contra un daemon protegido** cuando toque.
