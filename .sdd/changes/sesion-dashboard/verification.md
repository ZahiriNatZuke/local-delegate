# Verificación

## Suite y calidad

- `pytest`: **722 pasados, 2 saltados** (eran 722 con 35 en `test_web_auth.py`, antes 22).
- `ruff check` y `ruff format --check`: limpios sobre `src` y `tests`.
- Finales de línea comprobados: `git diff --numstat` y `git diff --ignore-cr-at-eol --numstat` dan
  **lo mismo** (147/10 en `auth.py`). No había forma de darlo por bueno a ojo: la primera escritura
  del fichero salió en CRLF sobre un repo en LF e inflaba el diff a 261/124, que es el mismo ruido
  que apareció en la jornada del 2026-08-02.

## Los tests pueden fallar (mutantes)

Siete mutaciones aplicadas al módulo, cada una revirtiendo una propiedad de la especificación.
**Siete muertas, ninguna superviviente:**

| Mutante | Resultado |
| --- | --- |
| no comprueba la caducidad | MATADO |
| firma que no cubre la expiración | MATADO |
| entrega cookie también con Bearer | MATADO |
| duración `0` no desactiva la sesión | MATADO |
| cookie sin `HttpOnly` ni `SameSite` | MATADO |
| nunca renueva | MATADO |
| la cookie se ignora del todo | MATADO |

## Contra el daemon real

Daemon del repo levantado en el puerto 9394 con `LOCAL_DELEGATE_LOG_DIR` propio —el lock es por
usuario, así que sin eso el singleton se niega a arrancar y **habría habido que tocar el daemon
instalado del usuario**, que no se tocó en ningún momento—:

| Petición | Resultado |
| --- | --- |
| sin credencial | `401` con `WWW-Authenticate: Basic realm="local-delegate"` |
| `Basic` correcto | `200` + `ld_sesion=…; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax` |
| solo la cookie, sin `Authorization` → `/api/status`, `/`, `/api/stats` | `200`, `200`, `200` |
| **control positivo** (la cookie buena) | `200` |
| un byte cambiado en la firma | `401` |
| expiración alargada un año a mano | `401` |
| el token pelado como cookie | `401` |

Caducidad emitida: **2027-08-03**, un año exacto.

El primer intento de este bloque **no probaba nada** y se rehízo: un error de sintaxis de
PowerShell dejó la variable vacía, así que el `401` del control negativo venía de mandar una cookie
vacía y no de una firma inválida. Es el mismo patrón que el repo ya tiene registrado —un test que
falla por la guarda equivocada— y solo se vio por mirar el mensaje de error en vez del código de
estado.

## Con un navegador real (Chromium por Playwright)

Lo que ninguna prueba HTTP puede ver: que los atributos de la cookie sean tales que un navegador la
**acepte, la persista y la reenvíe**. Marcarla `Secure` habría pasado todos los tests anteriores y
roto esto en silencio.

1. contexto sin credenciales → `401` (control: la puerta estaba puesta)
2. primera visita con la clave → `200`
3. cookies `ld_sesion` guardadas por el navegador → **1**, con `httpOnly=True`, `sameSite=Lax`,
   `secure=False`
4. contexto nuevo con ese `storage_state` y **sin credenciales** → `200`
5. `fetch('/api/stats')` desde la página cargada → `200`

El paso 5 importa aparte del 4: el HTML podría entrar y las peticiones de datos del panel caerse,
que es donde una cookie mal puesta se rompería sin que la página lo delate.

## Guardas del propio test

- `test_basic_entrega_sesion_y_la_segunda_visita_ya_no_pide_nada` vacía el jar del `TestClient`
  antes del control negativo y **comprueba que sin la cookie da 401**. La primera versión no lo
  hacía y pasaba en falso: httpx reenviaba la cookie él solo, así que el `200` que se atribuía a la
  sesión podía venir del jar.
- Cada bloque de rechazos lleva su control positivo fabricado con la **misma** función, para que un
  fallo en cómo el test construye la cookie no se disfrace de «todo se rechaza correctamente».
