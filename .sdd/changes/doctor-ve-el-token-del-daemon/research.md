# Research: el 401 que `doctor` no ve

## La avería, vivida hoy

Tras publicar la 0.25.0 se reinstaló el andamiaje con:

    local-delegate install --mcp-mode http --enable-read-hook --agents

Falta `--web-token-env`. Sin él, `mcp_entry()` escribe la entrada **sin la cabecera
`Authorization`** (`install.py:398-405`), y como el daemon de esta máquina exige token, Claude
Code no puede autenticarse: cae al flujo OAuth y reporta *«Dynamic Client Registration rejected
(HTTP 401)»*. Las once tools `local_*` desaparecieron de la sesión.

Dos agravantes, los dos medidos:

1. **Reinstalar sin el flag BORRA la cabecera de una instalación que funcionaba.** La entrada
   quedó en `{"type": "http", "url": "..."}` a secas.
2. **`doctor` dijo «todo a punto»**, con `[ OK ] MCP en Claude Code: registrado`.

Comprobado a mano en ese estado:

| petición | código |
|---|---|
| `POST /mcp` sin cabecera | **401** |
| `POST /mcp` con `Authorization: Bearer $LOCAL_DELEGATE_WEB_TOKEN` | **200** |

## Por qué el check no lo ve

`_probe_mcp_claude` (`checks.py:776`) sólo comprueba que la entrada **exista** y devuelve `OK`:

```python
if not isinstance(entry, dict):
    return Result(MISSING, ...)
kind = _entry_mode(entry)
return Result(OK, f"registrado en {path} ({kind} ...)")
```

No mira si el daemon exige token ni si la entrada lleva con qué autenticarse. Y no puede: el
grupo `andamiaje` **no sale a la red por contrato** —es lo que permite a `install` correr su
reporte sin tocar nada externo—, así que preguntarle al daemon desde ahí rompería esa promesa.

## Es la tercera vez que el mismo patrón muerde

| fecha | avería | qué decía `doctor` |
|---|---|---|
| 2026-07-31 | Entradas MCP en `stdio` sin la API key; todas las tools en 401 | todo OK (preguntaba al daemon, que sí tenía credencial) |
| 2026-08-06 | Claude Desktop en 401 desde que se cerró el puerto con token | nada: ese cliente no está en el registro |
| **2026-08-18** | Entrada http sin cabecera contra un daemon que exige token | **todo a punto** |

De la primera nació `service.credential` (`_probe_mcp_credential`, `checks.py:852`), que pregunta
**«¿está el backend abierto para quien no lleva la key?»** en vez de «¿está sano el backend?».
Ese check es el modelo exacto de lo que falta: **es su hermano un piso más arriba**. Aquel mira
la credencial del **backend**; nadie mira la del **daemon**.

## Lo que ya existe y no hay que construir

- **`ctx.daemon_needs_token(host, port)`** (`checks.py:276`), con su default real y su doble
  `NO_TOKEN_PROBE` para los tests. Hoy sólo se consulta cuando `daemon_status` no responde.
- Los tres lectores de entradas MCP que `_probe_mcp_credential` ya usa: `_claude_mcp_entry`,
  `_codex_mcp_section` y `_opencode_mcp_entry`.
- El grupo `servicio`, que sí sale a la red y es donde vive `service.credential`.

## Las tres superficies, que no se escriben igual

`install` pone la autenticación de forma distinta en cada cliente, así que el check tiene que
saber leer las tres:

| cliente | cómo queda escrito | dónde |
|---|---|---|
| Claude Code | `headers = {"Authorization": "Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"}` | `install.py:405` |
| Codex | `bearer_token_env_var = "LOCAL_DELEGATE_WEB_TOKEN"` | `install.py:430` |
| opencode | `headers = {"Authorization": "Bearer {env:LOCAL_DELEGATE_WEB_TOKEN}"}` | `install.py:609` |

Contar mal aquí daría un falso OK en el cliente no contado, que es justo el defecto que se está
arreglando.

## El segundo camino al mismo 401

Ya anotado como gotcha del proyecto: la entrada puede llevar la cabecera **y aun así fallar** si
`${LOCAL_DELEGATE_WEB_TOKEN}` expande a vacío porque el cliente se lanzó desde un terminal
anterior a la variable. `_probe_mcp_credential` resuelve el mismo dilema usando el entorno del
propio proceso como **testigo** —no como prueba— y nombrando el síntoma comprobable en vez de
afirmar que la máquina está rota. Se copia ese criterio.

## Límite

`doctor` corre en el entorno de quien lo escribe, no en el del cliente MCP. Si alguien lanza
Claude Code desde una consola con la variable y `doctor` desde otra sin ella, el testigo miente.
Por eso ese caso es `warn` con el síntoma nombrado, y nunca `missing`.
