# Revisión contra la especificación

| Req | Cómo se comprobó | Estado |
| --- | --- | --- |
| R1 — entrar una vez basta | `test_basic_entrega_sesion_…` (con el jar vaciado) + navegador real, pasos 2 y 4 | conforme |
| R2 — no se puede fabricar | `test_la_cookie_buena_entra_y_las_de_alrededor_no`, 10 formas + daemon real (firma alterada, token pelado) | conforme |
| R3 — no se puede alargar | `test_alargar_la_sesion_no_es_posible_sin_el_token` + daemon real (`401` con la expiración subida un año) | conforme |
| R4 — caduca | mismo test parametrizado; mutante «no comprueba la caducidad» MATADO | conforme |
| R5 — rotar el token echa a todos | `test_rotar_el_token_invalida_las_sesiones_vivas` | conforme |
| R6 — cubre el puerto entero | `test_la_sesion_tambien_alcanza_la_app_montada` (`/mcp`, `/api/status`, `/`) + daemon real | conforme |
| R7 — solo el navegador la recibe | `test_bearer_no_recibe_cookie`; mutante «cookie también con Bearer» MATADO | conforme |
| R8 — `HttpOnly`, `SameSite=Lax`, `Path=/` | aserciones sobre la cabecera + **leído del navegador** en el paso 3 | conforme |
| R9 — renueva a media vida, no siempre | dos tests (fresca sin `Set-Cookie`, gastada con una nueva más larga); mutante «nunca renueva» MATADO | conforme |
| R10 — se puede desactivar | `test_con_duracion_cero_no_hay_sesion_ninguna`, con las **dos** mitades: ni emite ni acepta | conforme |
| R11 — sin token nada cambia | `test_sin_token_configurado_la_sesion_no_existe` (identidad del objeto) | conforme |
| R12 — un navegador real la guarda | Chromium por Playwright, 5 pasos con control negativo | conforme |

## Hallazgos

**El reporte del usuario ofrecía dos salidas y la segunda era peor de lo que parecía.** «Si no se
puede guardar la sesión, mejor quitarlo» habría reabierto el agujero cerrado el día anterior:
`/api/stats` y `/api/hooks` sirviendo el log real de delegaciones a cualquiera en la tailnet. La
sesión no es un adorno de comodidad sobre la protección; es lo que permite que la protección siga
puesta.

**Dos pruebas que no probaban lo que decían**, las dos cazadas por mirar el resultado y no el
código de estado: el control negativo del test entraba por el jar de httpx, y el control negativo
contra el daemon real mandaba una cookie vacía por un error de sintaxis de PowerShell. Ambas daban
el veredicto correcto por la razón equivocada. Van al registro del repo como quinta y sexta
aparición del mismo patrón.

**Ruido de CRLF detectado antes de commitear**, no después: el diff de `auth.py` era 261/124 y
bajaba a 147/10 al ignorar los CR. Comparar los dos `--numstat` es la comprobación barata que la
jornada del 2026-08-02 pagó cara.

## Seguimiento

Ninguno abierto. Nada que retocar en `install.py` ni en `checks.py`: el check `service.credential`
sigue preguntando **sin** cabecera de autorización y sin cookie, así que lo que ve es exactamente
lo que ve quien no tiene el token.
