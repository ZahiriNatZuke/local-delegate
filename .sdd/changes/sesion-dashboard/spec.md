# Especificación: sesión del navegador para el puerto del daemon

## Contexto medido

Antes de escribir nada se leyó `src/local_delegate/web/auth.py` completo. La puerta actual acepta
dos credenciales (`Bearer` y `Basic`), envuelve la raíz ASGI —por lo que cubre el endpoint MCP, el
dashboard y `/api/*` de una vez— y no se instala si no hay token. Nada de eso puede cambiar.

La premisa del reporte se sostiene sin necesidad de reproducirla con una medición nueva: es
comportamiento documentado de HTTP Basic (RFC 7617), no una hipótesis sobre este código. El
navegador no persiste la credencial entre sesiones ni la comparte entre orígenes.

## Requisitos observables

1. **R1 — Entrar una vez basta.** Tras una petición autorizada con `Basic`, la respuesta lleva una
   cookie de sesión, y una petición posterior **sin `Authorization`** que solo lleve esa cookie
   entra.
2. **R2 — La sesión no se puede fabricar.** Una cookie con la firma alterada, firmada con otro
   token, sin firma, sin separador, con el token dentro tal cual, o con la expiración no numérica,
   se rechaza con 401.
3. **R3 — La sesión no se puede alargar.** Tomar una cookie legítima y subirle la expiración a mano
   la invalida: la fecha va dentro del mensaje firmado.
4. **R4 — Caduca.** Una cookie con expiración pasada se rechaza aunque su firma sea auténtica.
5. **R5 — Rotar el token echa a todo el mundo.** Una sesión emitida con un token no vale contra
   otro, sin que haya ninguna lista que purgar.
6. **R6 — La sesión cubre el puerto entero.** Igual que la cabecera: endpoint MCP, dashboard y la
   app montada debajo.
7. **R7 — Solo el navegador la recibe.** Una petición autorizada con `Bearer` no lleva `Set-Cookie`.
8. **R8 — Defensa CSRF sin token CSRF.** La cookie sale `HttpOnly`, `SameSite=Lax` y `Path=/`.
9. **R9 — La sesión en uso no caduca.** Se renueva cuando ya se gastó media vida, y **no** en cada
   respuesta.
10. **R10 — Se puede desactivar.** Con duración `0` no se emite cookie y una cookie perfectamente
    firmada tampoco abre nada.
11. **R11 — Sin token no cambia nada.** `proteger(app, "")` sigue devolviendo la misma app.
12. **R12 — Un navegador real la guarda y vuelve a entrar solo.** No basta con que el servidor la
    emita: los atributos tienen que ser tales que el navegador la persista y la reenvíe.

## Fuera de alcance

Pantalla de login, endpoint de cierre de sesión, y cualquier cambio en qué protege el token.
