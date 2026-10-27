# Spec — `record-read` solo escribe en la telemetría del daemon, y el panel no pinta HTML del log

Modo: lite. Origen: revisión de seguridad del 2026-10-23 (0.41.1, `eb079a9`), dos hallazgos
encadenados del board privado:

- «Cualquier web que abras puede escribir una línea en cualquier `.jsonl` del disco a través de
  `record-read`» (Alta).
- «El panel pinta sin escapar campos del log, y una línea inyectada se convierte en XSS al abrirlo»
  (Media; Alta encadenado).

## Qué

1. `POST /api/hook/record-read` deja de escribir donde diga la petición: el destino
   (`LD_HOOK_TELEMETRY_LOG` del cuerpo) solo se acepta si es la telemetría que conoce el daemon
   (`config.HOOK_TELEMETRY_LOG`, misma ruta normalizada). Otro destino, o un daemon sin telemetría,
   es 403 sin escribir nada; el mod ya trata un 403 como «esta vía no» y registra por el proceso.
2. Los tres `POST /api/hook/*` exigen `Content-Type: application/json` (415 si no) y rechazan
   cualquier cabecera `Origin` (403), haya token o no. El mod (fetch del motor, sin `Origin`) y los
   tests mandan JSON; un navegador no puede mandar JSON a otro origen sin preflight.
3. Los textos de la entrada de `record-read` tienen tope (256; `path`, 4096): por encima, 400.
4. El panel escapa todo campo del servidor que pinta en `innerHTML`, también en atributos
   (`class="src …"`, `org …`): tabla de actividad, «En curso», última delegación, tools, roles,
   procesos.
5. `GET /` sirve una `Content-Security-Policy` con `script-src 'self'` más el hash de cada
   `<script>` en línea de la página servida, `connect-src 'self'`, `object-src 'none'`,
   `base-uri 'none'`, `form-action 'none'`.

## Fuera

Comprobación de `Host`, `/api/inflight` por sesión y contador del mod (otros agentes); el oráculo
de `classify` (otro hallazgo). Los hooks Python y el CLI `hook record-read` no cambian: escriben en
su propio proceso.

## Criterios de aceptación

- El repro `repro.py notoken` de la revisión deja de escribir (`text/plain` + `Origin` → 415/403;
  sin fichero creado) y `/api/events` no trae la línea.
- Los tests de `record-read` cubren: destino ajeno (`usage-AAAAMM.jsonl`, carpeta nueva) → 403 sin
  escribir; mismo fichero escrito de otra forma (`..`, mayúsculas en Windows) → 204; daemon sin
  telemetría → 403; textos largos → 400; petición de navegador con y sin token → 415/403.
- Una guarda estática recorre todas las `${…}` del script del panel y falla con un campo de registro
  sin `escHooks`/formateador numérico; en `main` marca 18.
- En Chromium, una línea hostil en el log sale como texto y no corre, con y sin CSP, en claro y
  oscuro; con CSP no hay violaciones al cargar el panel.

## Verificación

`tests/test_hook_record_read_endpoint.py`, `tests/test_panel_escaping.py`,
`tests/test_panel_xss_ui.py`, suite completa con el cerrojo, ruff, y el repro de la revisión antes
y después.
