# Handoff

## Lo que no se deduce del código

**El token es la clave del HMAC a propósito, y eso es una decisión, no un atajo.** Se podría haber
generado una clave de firma aparte. No se hizo porque atar la firma al token da gratis la propiedad
que importa: **rotar el token invalida todas las sesiones vivas**, sin lista que purgar ni fichero
de secreto que mantener entre reinicios del daemon. Si alguien separa esas dos cosas en el futuro,
pierde eso y probablemente no se entere hasta que rote el token y las sesiones antiguas sigan
entrando.

**La cookie no lleva `Secure` y no es un olvido.** El daemon ve HTTP plano incluso cuando el
navegador está en HTTPS, porque el TLS lo pone `tailscale serve` delante. Con `Secure` la cookie
seguiría funcionando por la tailnet pero se rompería el acceso directo por `http://<ip>:9393`, que
el proyecto soporta. Quien lo «arregle» añadiéndolo romperá un escenario que hoy funciona.

**La sesión es una medida de seguridad, no de ergonomía.** El origen fue un reporte de incomodidad
cuya alternativa era quitar el token y volver a publicar `/api/stats` en la tailnet. El razonamiento
—una protección que se teclea varias veces al día se termina desactivando— es el que justifica el
coste de la cookie, y conviene tenerlo a mano si algún día se plantea simplificarla.

**Solo Basic recibe cookie.** No es una optimización: es no repartir un secreto derivado a procesos
(clientes MCP, CLI) que ya mandan el token en cada llamada y no tienen dónde guardarla.

## Trampas encontradas por el camino

- **El singleton bloquea probar el daemon del repo** si ya hay uno instalado corriendo, y el
  mensaje de error no lo dice así («lock ocupado y no responde ningún daemon nuestro» aparece
  también cuando el daemon vivo responde `401` porque tu proceso lleva otro token). La salida es
  `LOCAL_DELEGATE_LOG_DIR` a un directorio propio y otro puerto, sin tocar el daemon instalado.
- **El `TestClient` de Starlette guarda cookies en un jar** y se come los controles negativos: hay
  que llamar a `cliente.cookies.clear()` y comprobar que sin la cookie da `401`, o el test pasa por
  la razón equivocada.
- **`Write` puede dejar un fichero en CRLF sobre un repo en LF.** Se ve comparando
  `git diff --numstat` con `git diff --ignore-cr-at-eol --numstat`: si no coinciden, hay ruido.

## Estado

Implementado, verificado y documentado. Sin publicar: entra en `[Unreleased]` del CHANGELOG.
