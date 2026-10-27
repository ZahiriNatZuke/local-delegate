# Especificación (modo lite): la web stdio exige el token y una variable vacía toma el defecto

Dos tarjetas del backlog (revisión de seguridad del 2026-10-23, severidad media, verificadas):

- «La web que levanta el MCP stdio sirve todo el panel sin token aunque el token esté configurado».
- «Una variable de entorno vacía no usa el valor por defecto: con `LOCAL_DELEGATE_WEB_HOST` vacía,
  el panel y el MCP escuchan en todas las interfaces».

## Premisas, reproducidas

- `metrics.run_in_thread` (la web de un proceso `stdio` cuando el 9393 está libre) servía
  `host_guard.protect(metrics.app)` sin `auth.protect`: con `LOCAL_DELEGATE_WEB_TOKEN` puesta, `/`,
  `/api/events`, `/api/stats`, `/api/status`, `/api/system`, `/api/inflight` y `/api/hooks`
  respondían 200 sin credencial (los tests nuevos, con el `src` de `main`).
- `config._env` devolvía `""` si la variable existía vacía. `r7_variables_vacias.py`:
  `WEB_HOST=''`, escucha en `['0.0.0.0', '::']`, sin la guarda del `Host` ni la del SDK.

## Qué

1. `run_in_thread` envuelve la app igual que `daemon.build_app`: `auth.protect(app,
   token_source.daemon_token(), config.WEB_SESSION_SECONDS)` por dentro de `host_guard.protect`.
   Misma pieza y misma fuente del token que el daemon; sin token, nada cambia.
2. `config._env` trata una variable vacía o solo con espacios como no puesta. Afecta a las que
   tienen defecto no vacío: `WEB_HOST`, `BASE_URL`, `MODEL_*`, `BACKEND_ORIGIN`,
   `LLAMASWAP_LISTEN`, `JSON_SCHEMA`. Las de defecto `""` no cambian. Los interruptores
   (`_env_flag`) siguen leyendo la vacía como apagado, a propósito.
3. `install.daemon_mcp_url` aplica la misma regla (antes escribía `http://:9393/mcp`).

## Criterios de aceptación

1. Con token, la web stdio da 401 con `WWW-Authenticate` del realm en todas las rutas de arriba.
2. Con token, acepta Bearer, Basic (y deja la cookie de sesión) y la cookie; rechaza un token malo.
3. La guarda del `Host` sigue por fuera (421 con `Host` ajeno aunque lleve el token).
4. Sin token, la web stdio sigue abierta como antes.
5. Uso real: con un puerto de verdad, `config.web_auth_headers()` (CLI, `doctor`) y el `Bearer` del
   mod entran; `daemon.daemon_requires_token` reconoce el puerto protegido.
6. Vacía o con espacios → defecto en las variables del punto 2; un valor real se conserva; un token
   en blanco sigue siendo «sin token».
7. Con `WEB_HOST` vacía, `daemon.build_app` monta la guarda del `Host` (421 a un `Host` ajeno).
8. `install.daemon_mcp_url` con host/puerto vacíos → `http://127.0.0.1:9393/mcp`.

## Verificación

- `tests/test_panel_stdio_token_and_empty_host.py`; control positivo con el `src` de `main`.
- `r7_variables_vacias.py` de la revisión apuntado a la rama.
- Suite completa con el cerrojo; ruff.

## Fuera de alcance (anotado para el backlog)

- Aviso de `doctor`/`local_status` para un `WEB_HOST` fuera de loopback sin token y para números
  que no se pudieron leer (`LOCAL_DELEGATE_TIMEOUT=30s` cae al defecto sin aviso).
- `LOCAL_DELEGATE_ALLOWED_DIRS` vacía = sin restricción es el comportamiento documentado.
- Los hooks (`resources/hooks/hook_common.py`, stdlib pura) leen `LOCAL_DELEGATE_BASE_URL` con
  `os.environ.get` y una vacía no toma el defecto; no abre nada (el hook solo falla su sondeo).
- El arranque de desarrollo `python -m local_delegate.web.metrics` sigue sin token.
