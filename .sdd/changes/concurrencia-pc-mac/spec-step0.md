# Spec (ligera) — Paso 0: instrumentar la concurrencia PC+Mac en el log de uso

Modo ligero, solo para el paso 0 (instrumentación). El diseño de la cola única (opciones A/B/C) es
el SDD completo de esta carpeta y espera a la medición del paso 1 (`research.md`, §6).

## Objetivo

Que cada entrada del log de uso permita contestar, sin cruzar transcripts: de qué máquina vino,
cuándo esperó turno, plaza y backend (en UTC, cruzable entre máquinas), qué modelo pidió, qué tenía
cargado llama-swap al empezar y si la llamada obligó a cambiar de modelo.

## Requisitos

- **REQ-S0-1 (`host`).** Toda entrada lleva `host`: `LOCAL_DELEGATE_MACHINE_NAME` si está puesta, si
  no el nombre corto del equipo (hasta el primer punto). Saneado a `[A-Za-z0-9._-]`, máx. 64; nunca
  vacío (`unknown`).
- **REQ-S0-2 (cabecera).** Toda petición del paquete al backend (`/chat/completions`, `/running`,
  `/models`, `/api/events`, `/api/metrics/*`) lleva `X-Local-Delegate-Host: <host>`. Las cabeceras
  hacia el daemon (`auth_headers`, `web_auth_headers`) no cambian.
- **REQ-S0-3 (fases).** Una operación que pasa por el backend escribe `concurrency.phases` con, por
  cada fase que hubo (`turn`, `slot`, `backend`): `start` (UTC ISO con ms, primer paso), `end` (UTC,
  último), `ms` (suma) y `n` (veces). Una fase que no hubo no aparece.
- **REQ-S0-4 (modelos).** `concurrency.requested_model` siempre; `backend_models` (`{modelo:
  estado}` de `/running` justo antes del primer POST) y `model_swap` (el primer POST fue a un modelo
  que no estaba `ready`) solo si `/running` respondió. La consulta lleva tope de 0,5 s y caché de
  2 s (también del fallo) y nunca rompe ni retrasa más de ese tope la llamada.
- **REQ-S0-5 (peticiones ajenas).** Donde el daemon ya lee la foto `inflight` de `/api/events` (la
  afinidad), la operación guarda `concurrency.inflight_seen` como `[{model, host}]` (máx. 20). De
  `req_headers` solo se lee `X-Local-Delegate-Host` (sin distinguir mayúsculas, valor `str` o
  `[str]`); nunca la credencial.
- **REQ-S0-9 (origen de una llamada por `/mcp`).** Una llamada que llega al `/mcp` del daemon desde
  otra máquina lleva en su entrada del log y en su entrada de `inflight` (`/api/inflight`) el `host`
  de ese cliente y `host_via`: `header` (cabecera `X-Local-Delegate-Host` de la petición MCP),
  `forwarded` (primer salto de `X-Forwarded-For` cuando quien conecta es loopback, el caso de
  `tailscale serve`) o `ip` (dirección remota no loopback). Stdio y loopback sin cabeceras: el
  `host` de la propia máquina, sin `host_via`; en `inflight` una llamada local no añade claves (las
  claves de una entrada local están fijadas por `tests/test_inflight_per_session.py`), así que «sin
  `host`» = la máquina del daemon. Es observación, no control de acceso. (Añadido tras
  la corrección de la sesión principal: parte del tráfico de la Mac del 2026-10-29 entró por el
  daemon.)
- **REQ-S0-6 (compatibilidad).** Campos aditivos: los existentes no cambian de nombre ni de
  significado (`model_requested` sigue apareciendo solo con salto o afinidad). El panel, `/api/stats`
  y `/api/events` leen igual logs viejos, nuevos y mezclados.
- **REQ-S0-7 (best-effort).** Ningún fallo de la observación llega a la tool: el evento se escribe
  sin el campo.
- **REQ-S0-8 (docs).** `docs/wiki/Savings-and-metrics.md` documenta los campos y cómo cruzar los
  logs; `Configuration.md` la variable; `Backend-versions.md` que de la foto se lee esa cabecera.

## Fuera de alcance

Cambiar el turno, la plaza o el panel; enviar progreso MCP durante las esperas; el endpoint de turno
(opción B). Las entradas de abortos (`ok:false`, Frente 1, #476) y el estado `running/queued` de
`/api/inflight` (Frente 2, #477).

## Revisión propia (gate spec, ligero)

Aprobada por el agente con revisión explícita: cada requisito tiene un test que lo distingue
(`tests/test_concurrency_log.py`, control positivo por mutante en `plan-step0.md`). Riesgo
aceptado: no se ha comprobado contra un llama-swap real que `req_headers` del `inflight` traiga
cabeceras propias; se comprueba en el paso 1 (si no, `inflight_seen.host` saldrá `null` y la spec no
inventa otra fuente).
