# Plan

## Decisión de diseño: cookie firmada, sin estado

El valor es `<expiración>.<firma>`, donde la firma es
`HMAC-SHA256(clave=token, mensaje="ld-sesion|v1|<expiración>")` en base64url.

Por qué **el token como clave del HMAC** y no una clave de firma aparte generada al arrancar:

- No hay nada que guardar ni que sincronizar. Una clave por proceso moriría en cada reinicio del
  daemon —o sea en cada actualización—, y persistirla obligaría a un fichero de secreto con sus
  permisos, que es infraestructura nueva para no ganar nada.
- **Rotar el token invalida todas las sesiones vivas** como efecto secundario de rotarlo. Con una
  clave aparte, cambiar el token dejaría a las sesiones antiguas entrando: exactamente el fallo que
  nadie prueba y que hace inútil rotar el secreto.
- La cookie no es un secreto *más débil* que el token: quien la tenga puede entrar, igual que quien
  tenga el token, pero no puede deducir el token de ella ni fabricar otra.

Por qué la expiración va **dentro** del mensaje firmado y no al lado: si se firmara solo un
identificador, una cookie legítima recién caducada se volvería eterna cambiándole el número. Es el
único ataque que esta cookie tiene que aguantar y sale gratis defenderlo.

Por qué **sin `Secure`**: el daemon habla HTTP plano incluso cuando el navegador está en HTTPS,
porque el TLS lo pone `tailscale serve` delante. Con `Secure` la cookie seguiría funcionando ahí
pero rompería el acceso directo por `http://<ip>:9393`, que el proyecto soporta. En ese escenario
la cookie viaja en claro igual que viajaría hoy el token en la cabecera Basic: no se pierde nada
que se tuviera.

Por qué `SameSite=Lax` en vez de un token CSRF: es lo que impide que una página ajena consiga que
el navegador adjunte la cookie a un `fetch`, un XHR o un POST contra el puerto. Un token CSRF aquí
exigiría plantilla, estado y una segunda cosa que mantener para cubrir lo mismo.

Por qué **solo Basic recibe cookie**: un cliente MCP o el CLI mandan Bearer en cada llamada y no
tienen dónde guardarla. Dársela sería repartir un secreto derivado a procesos que no lo necesitan.

Por qué la renovación es a **media vida** y no en cada respuesta: renovar siempre pondría una
`Set-Cookie` en cada carga de página sin ganar nada; no renovar nunca haría caducar una sesión en
uso activo.

## Pasos

1. `web/auth.py`: `crear_sesion`, `sesion_valida`, `es_basic`, parser de cookies y emisión de la
   cabecera; `TokenPuerto` acepta la duración y envuelve `send` para colgar la cookie.
2. `config.py`: `LOCAL_DELEGATE_WEB_SESSION_DAYS` (365 por defecto, `0` desactiva).
3. `daemon.py`: pasar la duración a `proteger`.
4. Tests de la puerta, escritos al revés: cada rechazo con su control positivo al lado.
5. Verificación por mutantes, contra el daemon real y con un navegador real.
6. Documentación: `SECURITY.md`, `docs/wiki/Daemon.md`, `docs/wiki/Configuration.md`, `CHANGELOG.md`.

## Riesgo residual aceptado

Quien robe la cookie del disco del navegador entra sin conocer el token, hasta que el token se
rote. Es el mismo modelo de amenaza que un gestor de contraseñas guardando el token, y la máquina
donde vive esa cookie es la misma que tiene la key del backend en el entorno del daemon.
