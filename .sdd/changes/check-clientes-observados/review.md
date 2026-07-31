# Result review: Check de doctor sobre los clientes MCP observados

## Verdict

`conforms-with-notes` — los catorce requisitos están implementados y verificados. Las notas son
dos hallazgos que salieron **durante** la revisión y ya están corregidos, más una limitación
declarada en la spec.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 `client.observed` en `entorno` | sí | sí | tras `client.presence`, como pedía el plan |
| REQ-002 fuente `clients.jsonl` | sí | sí | comprobado en ejecución con `LOCAL_DELEGATE_LOG_DIR` |
| REQ-003 colaborador inyectable | sí | sí | `clients_seen`, patrón `(valor, motivo)` |
| REQ-004 el probe no escribe | sí | sí | dos tests, uno específico del directorio |
| REQ-005 sin datos → `unknown` | sí | sí | también por ejecución real, `exit=0` |
| REQ-006 ilegible → `unknown` + motivo | sí | sí | el motivo trae la ruta vía `read_text` |
| REQ-007 con datos → `ok` siempre | sí | sí | mutante «WARN si falta elicitation» rompe su test |
| REQ-008 uno por nombre, el más reciente | sí | sí | tres mutantes distintos lo cubren |
| REQ-009 líneas inválidas se saltan | sí | sí | blanco, truncada y no-objeto |
| REQ-010 sin `fix_hint` | sí | sí | atado también desde `update` |
| REQ-011 cp1252 | sí | sí | saneado, porque el nombre es texto de terceros |
| REQ-012 el módulo no miente sobre su tamaño | sí | sí | `_NUMERO[15]`, cinco frases |
| REQ-013 no se repara | sí | sí | `REPAIRS` intacto + test |
| REQ-014 wiki | sí | sí | «quince piezas» + fila nueva en la tabla |

## Findings

1. **(corregido, alto) El test de deduplicación pasaba por la guarda equivocada.** Con la
   observación vieja al principio de la lista, cubría «agrupa por nombre» pero no «escoge la más
   reciente»: un check que se quedara con la última observación vista pasaba igual. Se movió al
   final y se añadieron dos mutantes que separan las dos mitades. Es el mismo patrón que la sesión
   anterior encontró dos veces; aquí lo destapó exigir que cada mutante rompa **su** test.
2. **(corregido, medio) `checks.py` quedó convertido de LF a CRLF** por el script de mutación
   (`Path.write_text` traduce `\n` a `\r\n` en Windows). El diff pasaba de 150 a **1418** líneas y
   habría entrado en el PR como una reescritura del fichero entero. Revertido a LF; el resto del
   repo no se tocó.
3. **(corregido, bajo) Un comentario preexistente decía «cuatro sitios»** donde el test compara
   **cinco** afirmaciones. Se corrigió por coherencia con la regla que ese mismo test defiende: un
   comentario que miente sobre el propio registro es lo que hace planificar sobre un dato falso.
4. **(aceptado) `doctor --home` no aísla el registro.** `LOG_DIR` no deriva de `HOME`. Es
   deliberado, está en la spec y es el comportamiento que ya tienen los checks de servicio. No es
   el defecto del change C: aquí solo se lee, nunca se escribe.
5. **(fuera de alcance, anotado) `clients.jsonl` crece sin límite.** Una línea por arranque de
   proceso. El check lo tolera agrupando, pero la rotación es otro cambio.

## Required follow-up

Nada bloquea el cierre. Para el backlog:

- **Rotar o deduplicar `clients.jsonl`**, que hoy crece sin techo.
- **Medir el check con dos clientes a la vez** (Claude Code y Codex en el mismo `LOG_DIR`): está
  cubierto por tests, no por observación en vivo.
- **El transporte `streamable_http` sigue sin medirse** con el observador de clientes.
