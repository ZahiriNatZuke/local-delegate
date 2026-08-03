# Brief (modo lite): el dashboard pide el token demasiadas veces

## Problema

Reportado por el usuario tras un día con `LOCAL_DELEGATE_WEB_TOKEN` puesto en las dos máquinas
(PR de la 0.22.1, cierre del puerto en la tailnet): *«es incómodo estar constantemente poniendo el
token; si al menos guardara la sesión, y si no es posible, mejor quitarlo»*.

La causa es la credencial elegida para el navegador. Basic es la única que un navegador sabe mandar
sin una pantalla de login, pero el navegador solo la recuerda **mientras la ventana vive** y **por
origen exacto**: reabrir el navegador la pierde, y `localhost:9393` y `127.0.0.1:9393` son dos
orígenes distintos que la piden por separado.

Lo que está en juego no es la comodidad. La alternativa que el propio usuario planteó —quitar el
token— deja `/api/stats` y `/api/hooks` sirviendo su log real de delegaciones a cualquiera en la
tailnet, que es exactamente el agujero que se cerró ayer. **Una protección que hay que teclear
varias veces al día es una protección que se termina desactivando**, así que la incomodidad es un
problema de seguridad, no de ergonomía.

## Resultado deseado

Entrar una vez con el token y que el navegador siga dentro, sin perder nada de lo que el token
protege hoy.

## En alcance

`src/local_delegate/web/auth.py` (la puerta del puerto), una variable de configuración para la
duración, y los tests de la puerta.

## Fuera de alcance

- El transporte de los clientes MCP y del CLI: siguen con `Authorization: Bearer` en cada llamada.
- Qué rutas protege el token: sigue siendo el puerto entero.
- El comportamiento sin token configurado: no cambia ni una comparación.

## Restricciones y riesgos

- **No puede haber estado en el servidor.** El daemon se reinicia con cada actualización y no tiene
  dónde guardar una tabla de sesiones que sobreviva.
- **Una cookie es una credencial nueva**: hay que impedir que se fabrique o se alargue sin el
  token, y que una página ajena consiga que el navegador la adjunte (CSRF).
- **El TLS lo pone un proxy delante** (`tailscale serve`), así que el daemon ve HTTP plano incluso
  cuando el navegador está en HTTPS: marcar la cookie `Secure` rompería el acceso directo por
  `http://<ip>:9393`, que el proyecto soporta.
- Decisión del usuario, tomada tras ver las cuatro opciones: sesión persistente de **un año**.
