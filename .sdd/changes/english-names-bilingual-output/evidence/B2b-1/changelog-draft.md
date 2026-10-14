# Borrador para el CHANGELOG de la 0.36.0 (lo usa el PR de release; B2b-1)

### Cambiado — incompatible

- **Contrato de las tools MCP en inglés (REQ-010).** Las subclaves de `_local_delegate` y los
  marcadores de aviso, respaldo y entrada truncada pasan a inglés y ya no dependen del idioma. Se
  emite solo la forma nueva:

  | Hasta la 0.35 | Desde la 0.36.0 |
  |---|---|
  | `truncado` | `truncated` |
  | `aviso` | `warning` |
  | `leido_server_side.{chars, tokens_aprox}` | `read_server_side.{chars, approx_tokens}` |
  | `respaldo.{respondio, en_lugar_de, motivo, clase}` | `fallback.{answered_by, instead_of, reason, class}` |
  | `crudo` | `raw` |
  | `[local-delegate aviso: …]` | `[local-delegate warning: …]` |
  | `[local-delegate respaldo: …]` | `[local-delegate fallback: …]` |
  | `[local-delegate: entrada truncada — …]` | `[local-delegate: input truncated — …]` |
  | `[local-delegate error]` | sin cambio |

  `truncated`/`warning` significan ahora «salida truncada en un trozo» (`local_extract` lee la
  entrada entera y la trocea, B2c). El `reason` de un salto por enfriamiento es `cooldown`.
- **Descripciones de las tools solo en inglés (REQ-027):** docstrings, títulos y la descripción del
  servidor, iguales con `LOCAL_DELEGATE_LANG=es` y `=en`. Nombres de tool y parámetros no cambian.
  El cliente MCP cachea la lista de tools por sesión: hay que reconectar (`/mcp`) para verla.
