# Handoff: El puerto del daemon exige token cuando se configura uno

## Current state

- Estado SDD: `verifying` → pasa a `result-review`/`closing` con el CI del PR en verde.
- Último gate aprobado: `quality`.
- Base `5809003`; rama `feat/auth-puerto-daemon`.

## What changed

- `web/auth.py` (nuevo): la puerta del puerto, middleware ASGI con `Bearer` y `Basic`.
- `config.py`: `WEB_TOKEN` y `web_auth_headers()`.
- `daemon.py`: envuelve la raíz **después** del `Mount`; las dos `query_*` se autentican; nace
  `daemon_requires_token`, que pregunta **sin** cabecera.
- `checks.py`: `_probe_daemon` separa «otro proceso» de «falta el token»; colaborador
  `daemon_needs_token` en el `Context`, doblado en los **dos** arneses.
- `install.py` / `cli.py`: `--web-token-env`.
- Docs: `SECURITY.md`, `docs/wiki/Daemon.md`, `docs/wiki/Configuration.md`, `CHANGELOG.md`.

## Decisions

- **Opt-in por variable, no obligatorio.** Exigir token siempre rompería toda instalación
  existente al actualizar. Decidido con el usuario.
- **Sin detección de exposición.** Detectarla obligaría a atar el MCP a una herramienta externa
  concreta (una VPN, un proxy) que la mayoría de usuarios no tiene. Decisión explícita del
  usuario: *el MCP no infiere la topología de red de nadie*. Por eso **no** hay check nº17.
- **`Basic` además de `Bearer`** porque el navegador no manda `Bearer` por escribir una URL, y un
  panel inalcanzable acaba con el token desactivado. Evita cookies, login, sesión y CSRF.
- **La puerta se envuelve al final de `build_app`**, después del `Mount`: así una ruta nueva queda
  protegida por existir. Hay un mutante y un test para esto.
- **`daemon_requires_token` es función aparte y pregunta sin cabecera**, siguiendo el molde de
  `backend_probe`/`backend_requires_key`. Y se apoya en el `realm` para no atribuirse un `401`
  ajeno.
- **Nada basado en `Host` o IP de origen**: descartado **por medición**, no por criterio. Un proxy
  delante conecta desde loopback, y la guarda anti-DNS-rebinding del SDK se salta con una cabecera
  a mano.

## Next action

Merge del PR. Después, decidir si entran los puntos 3 (sincronizar la wiki nativa) y 4 (el
`cancelled` del CI) o se dejan para la próxima sesión.

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` (borrar el punto al cerrar) y la jornada del
  2026-07-31.
- Índices actualizados: al cierre de la sesión.
