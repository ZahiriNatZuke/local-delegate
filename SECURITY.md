# Política de seguridad

## Versiones con soporte

Se dan parches de seguridad para la **última versión publicada** en PyPI
(`local-delegate-mcp`). El proyecto está en serie 0.x: no se mantienen ramas de versiones
anteriores.

| Versión | Soporte |
|---|---|
| última `0.x` publicada | ✅ |
| anteriores | ❌ (actualiza) |

## Cómo reportar una vulnerabilidad

Usa **[Private vulnerability reporting](https://github.com/ZahiriNatZuke/local-delegate/security/advisories/new)**
de GitHub (pestaña *Security* → *Report a vulnerability*). No abras un issue público ni un PR
con el detalle del fallo.

Incluye, en la medida de lo posible: versión del paquete, sistema operativo, backend usado
(llama-swap, Ollama…), configuración relevante **sin secretos**, y pasos para reproducir.

Respuesta esperada: acuse en unos días y una evaluación inicial en cuanto se pueda reproducir.
Es un proyecto mantenido por una persona en su tiempo libre; no hay SLA ni programa de
recompensas.

## Superficie a tener en cuenta

`local-delegate` corre en tu máquina y no es un servicio expuesto, pero hay tres cosas que
conviene tener presentes al reportar o al desplegar:

- **Lectura de archivos.** Las tools aceptan un `path` que el servidor lee *server-side* — ese
  es justo el mecanismo que ahorra contexto. Si el MCP queda accesible a algo que no controlas,
  eso es lectura arbitraria de archivos con los permisos del usuario. Limita las raíces
  permitidas con `LOCAL_DELEGATE_ALLOWED_DIRS`.
- **Puertos de escucha.** El dashboard y el daemon escuchan en `127.0.0.1` por defecto, **sin
  autenticación**. Cambiar `LOCAL_DELEGATE_WEB_HOST` a `0.0.0.0` publica en la red local un panel
  con tu actividad y las rutas de los archivos delegados.

  **Y `127.0.0.1` no basta como garantía:** cualquier proxy que pongas delante lo publica igual sin
  tocar esa variable — un túnel, un nginx, un reenvío de puerto de una VPN. El puerto expone el
  panel **y** el endpoint MCP, y ese endpoint corre dentro del daemon, o sea **con la credencial
  del backend ya cargada**: quien lo alcance puede delegar sin tener ninguna key.

  **La protección anti-DNS-rebinding del SDK no sirve para esto**, y conviene decirlo porque
  induce a error: rechaza con `421` una petición cuyo `Host` no sea loopback, pero eso solo frena a
  un navegador engañado. Se salta mandando `Host: 127.0.0.1:9393` a mano — comprobado.

  **Cómo se cierra:** define `LOCAL_DELEGATE_WEB_TOKEN` en el entorno del daemon. Con esa variable,
  todo el puerto exige el token —el endpoint MCP, el dashboard y `/api/*`— por `Authorization:
  Bearer <token>` o por `Basic` (cualquier usuario, el token como contraseña, que es lo que permite
  abrir el panel desde un navegador). Sin la variable no cambia nada, para no romper instalaciones
  existentes. Ver [Daemon](docs/wiki/Daemon.md#autenticación-del-puerto).

  Tras entrar una vez con Basic, el navegador recibe una **cookie de sesión** y no vuelve a pedir el
  token durante un año. No hay estado en el servidor: la cookie lleva su caducidad firmada con
  HMAC-SHA256 usando el token como clave, así que no se puede fabricar ni alargar sin conocerlo, y
  **rotar el token invalida todas las sesiones vivas**. Es `HttpOnly` y `SameSite=Lax` —lo que aquí
  sustituye a un token CSRF— y solo la recibe quien se autentica por Basic, nunca un cliente MCP.
  Está por una razón de seguridad y no de comodidad: una protección que pide el secreto varias veces
  al día es una protección que se termina desactivando.

  El token **no se escribe en ningún fichero de configuración**: `local-delegate install
  --mcp-mode http --web-token-env` deja a los clientes referenciando la variable de entorno
  (`${LOCAL_DELEGATE_WEB_TOKEN}` en Claude Code, `bearer_token_env_var` en Codex).
- **Backend remoto.** `LOCAL_DELEGATE_BASE_URL` puede apuntar a otra máquina; el contenido
  delegado viaja hasta ahí. Usa HTTPS y una red privada (ver
  [Backend remoto](docs/wiki/Remote-backend.md)), nunca un puerto abierto a internet.

Los secretos (`LOCAL_DELEGATE_API_KEY`) nunca se escriben en el log de uso, en la configuración
que genera `local-delegate install` ni en los mensajes de error: se referencian por variable de
entorno.

## Dependencias

La política del proyecto es no añadir una dependencia directa cuyo *depscore* de Socket baje de
**0.7** en cualquiera de sus cinco dimensiones. Las directas se mantienen al mínimo, y esa
ligereza es parte del argumento del paquete.

### `pywin32`: heredada, no elegida

Desde la migración al SDK `mcp` 2.x, una instalación **en Windows** arrastra `pywin32`, que el SDK
declara obligatoria para `sys_platform == "win32"`. Sus puntuaciones rozan el umbral:

| Paquete | license | maintenance | quality | supplyChain | vulnerability |
|---|---|---|---|---|---|
| `pywin32` 312 | **70** | 100 | 100 | **73** | 100 |

Se documenta en vez de silenciarse, y con tres precisiones:

- **El proyecto no la eligió y no la usa.** Ninguna línea de `local_delegate` la importa. De hecho
  se evitó a propósito: `_pid_alive` comprueba procesos con `ctypes` justo para no depender de
  ella. Entra por el árbol del SDK, por debajo.
- **No es evitable sin renunciar al SDK 2.x.** No es un extra opcional ni tiene alternativa
  declarable desde aquí; excluirla rompería la instalación del propio `mcp`.
- **Solo afecta a Windows.** En Linux y macOS no entra.

Si en el futuro el SDK la hiciera opcional, o sus puntuaciones cayeran por debajo del umbral, es
motivo para reevaluar la dependencia del SDK, no para asumirlo en silencio.
