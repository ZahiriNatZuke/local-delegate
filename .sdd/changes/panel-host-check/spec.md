# Especificación (modo lite): el puerto del daemon comprueba el `Host`

Tarjeta del backlog: «Los endpoints del panel no comprueban el `Host`: con la configuración por
defecto, el DNS rebinding lee todo y además sirve de oráculo de ficheros» (revisión de seguridad del
2026-10-23, severidad media, verificada).

## Premisa, reproducida

`repro.py notoken` de la revisión, sobre `main` (`eb079a9`): `GET /api/events` y `GET /api/system`
con `Host: evil.example:9393` → **200** (con `log_dir`); `POST /api/hook/classify` → 200 con `path` y
`bytes` del fichero pedido. La protección del SDK (`streamable_http_app(host=…)`) cubre solo `/mcp`;
el panel va en `Mount("/", metrics.app)`, fuera de su alcance. La web del modo stdio
(`metrics.run_in_thread`) sirve el mismo panel sin ninguna comprobación.

## Qué

Un middleware ASGI propio (`web/host_guard.py`) envuelve la raíz del daemon (por fuera del token) y
la web del modo stdio:

- `Host` fuera de la lista → **421** `Invalid Host header`, igual que el SDK; el cuerpo no dice qué
  hosts valen.
- `Origin` de otra web (`http(s)` de otro host, o `null`) → **403** `Invalid Origin header`.
- Lista: `127.0.0.1`, `localhost`, `::1` (cualquier puerto) + `LOCAL_DELEGATE_WEB_HOST` si es una
  interfaz concreta + `LOCAL_DELEGATE_WEB_ALLOWED_HOSTS` (comas; `*` desactiva).
- Escucha en todas las interfaces sin hosts extra → sin comprobación (criterio del SDK).
- El SDK recibe la **misma** lista (`transport_security`), para que `/mcp` y el panel no discrepen.

## Criterios de aceptación

1. Todo endpoint de lectura del panel, `/daemon/status`, `/` y `/mcp` dan 421 con `Host` ajeno, sin
   filtrar datos; `classify` deja de ser oráculo.
2. Loopback (`127.0.0.1`, `localhost`, `[::1]`, con y sin puerto) sigue dando 200.
3. Con token, un `Host` ajeno da 421 antes del 401.
4. `LOCAL_DELEGATE_WEB_ALLOWED_HOSTS` abre panel y `/mcp` a la vez (caso `tailscale serve`).
5. `WEB_HOST` con una IP concreta: esa IP vale y el rebinding sigue fallando, también en `/mcp`.
6. `0.0.0.0` sin extras: la LAN sigue entrando; con extras se aplica la lista.
7. POST con `Origin` ajeno o `null` → 403; mismo origen o esquema no web → pasa.
8. La web del modo stdio va envuelta igual.
9. Documentado en README y `docs/wiki/` (Configuration, Daemon, Troubleshooting).

## Verificación

`tests/test_host_guard.py` (20 tests, contra la app real `daemon.build_app`). Control positivo: con
`daemon.py` y `metrics.py` de `main` fallan 9 (los de 421/403/stdio/extra hosts) por el assert que
dicen. `repro.py notoken` de la revisión: antes 200 y fugas, ahora 421 en todo. Suite completa en
local con cerrojo.

## Fuera de alcance

- La web del MCP stdio sin token aunque esté configurado (tarjeta vecina).
- `LOCAL_DELEGATE_WEB_HOST` vacía escucha en todas las interfaces (tarjeta vecina): aquí la vacía se
  trata como «todas las interfaces» y deja la guarda sin aplicar, igual que antes hacía el SDK.
