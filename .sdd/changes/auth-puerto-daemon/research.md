# Research: El puerto del daemon exige token cuando se configura uno

## Current behavior

- `daemon.build_app()` devuelve **una sola** app: la del transporte MCP (`streamable_http_app`),
  con `Route(/api/daemon)` insertada al principio y `Mount("/", metrics.app)` al final.
  Esto **corrige la premisa del backlog**, que hablaba de «cubrir dos apps»: hay una raíz y todo lo
  demás cuelga de ella, así que envolver esa raíz cubre el puerto entero de una vez.
- Ninguna de las tres superficies pide credencial.
- `config.py` lee todo por variables de entorno, con helpers `_env`/`_env_flag`/`_env_int` y un
  precedente exacto de lo que hace falta: `auth_headers()` para el backend (línea 59).
- El CLI habla con su propio daemon por `daemon.query_daemon` y `daemon.query_backend`, los dos
  sin cabecera. Sus dos consumidores son `checks.py:96` y `checks.py:115`.
- La entrada MCP real de Claude Code en esta máquina es
  `{"type": "http", "url": "http://127.0.0.1:9393/mcp"}` — **sin cabeceras**.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `config.py` | Configuración por entorno | Añade `WEB_TOKEN` y `web_auth_headers()` | `config.py:59` como precedente |
| `web/auth.py` | — (nuevo) | La puerta: Bearer + Basic, comparación timing-safe | — |
| `daemon.py` `build_app` | Compone MCP + dashboard | Envuelve la raíz **al final** | `daemon.py:158-164` |
| `daemon.py` `query_*` | Preguntan al daemon | Mandan la cabecera si hay token | `daemon.py:98,116` |
| `daemon.py` | — | Añade `daemon_requires_token` (pregunta **sin** cabecera) | patrón de `backend_requires_key` |
| `checks.py` `_probe_daemon` | «no es nuestro daemon» al no obtener respuesta | Separa las dos causas | `checks.py:831-833` |
| `checks.py` `Context` | 5 colaboradores inyectables | Añade `daemon_needs_token` | `checks.py:235-256` |
| `install.py` | Escribe la entrada MCP | `--web-token-env` para los dos clientes | `install.py:298-339` |

## Existing conventions

- **Dos funciones, no una con flag**, cuando la respuesta depende de quién pregunta. Es la lección
  que dejó escrita el check nº16: `backend_probe` (con credencial) y `backend_requires_key` (sin
  ella) son dos, porque *«un booleano cuyo significado dependiera del entorno de quien pregunta
  sería justo la clase de dato que engaña»*. `daemon_requires_token` sigue ese molde.
- **Todo colaborador del `Context` que hable con el exterior se dobla en los DOS arneses**
  (`make_ctx` de `test_checks.py` y `_stub_environment` de `test_doctor.py`). Olvidarlo deja la
  suite saliendo a la red: verde en CI, distinta en la máquina de quien desarrolla.
- **El diagnóstico degrada, nunca revienta**, y distingue `unknown` («no se pudo saber») de `warn`
  («sé lo que pasa y hay arreglo»). `_probe_backend_models:840` ya trata el 401 aparte por eso
  mismo.
- **Nunca se escribe un secreto**: `--api-key-env` referencia `${LOCAL_DELEGATE_API_KEY}`, y para
  Codex se usa `env_vars` porque *«`${VAR}` no se expande en TOML»* (`install.py:330`).

## Dependencies and integrations

- **Claude Code** — la doc lista `headers` entre los sitios donde expande `${VAR}`.
  **Verificado por ejecución** contra un servidor señuelo: la 2.1.220 manda
  `authorization: Bearer <valor resuelto>`, tomando la variable del entorno del proceso.
- **Codex** — su código fuente (`codex-rs/config/src/mcp_types.rs`) declara para
  `streamable_http`: `url`, `bearer_token_env_var`, `http_headers`, `env_http_headers`. Y en la
  línea 401 **prohíbe** `bearer_token` literal en ese transporte, así que la variable no es una
  preferencia: es el único camino.
- `secrets`, `base64`, `binascii` — todo de la stdlib.

## Risks and unknowns

- **Confirmado por medición:** el endpoint MCP es alcanzable desde fuera falsificando el `Host`;
  el dashboard y `/api/*` ni siquiera lo necesitan.
- **Confirmado por medición:** Claude Code expande `${VAR}` en `headers`.
- **Confirmado por lectura del fuente:** Codex resuelve lo mismo con `bearer_token_env_var`.
- **Asunción no medida:** que la variable exista en el entorno del cliente. Es responsabilidad del
  usuario y el punto exacto donde esto se rompe en silencio — va documentado en la wiki.
- **Limitación aceptada:** la propiedad de tiempo constante de `secrets.compare_digest` **no es
  observable** desde los tests. Se implementa porque es correcto, no porque esté cubierta.
