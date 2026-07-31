# Implementation plan: El puerto del daemon exige token cuando se configura uno

## Approach

**Middleware ASGI puro envolviendo la app raíz, y envolviéndola al final.**

- **ASGI y no `add_middleware` de Starlette**, porque un middleware de Starlette depende de a qué
  app se lo añadas y no alcanza lo montado por debajo. Envolver el callable ASGI no admite esa duda.
- **Al final de `build_app`, después del `Mount`**, para que una ruta nueva quede protegida *por
  existir* y no por acordarse de protegerla. El mutante que mueve la línea antes del `Mount`
  deja el dashboard abierto, y hay un test que lo caza.
- **Dos esquemas de credencial**, porque hay dos clases de cliente y ninguna se puede sacrificar:
  `Bearer` para clientes MCP y CLI, `Basic` para el navegador —que no manda `Bearer` por escribir
  una URL—. Basic evita cookies, login, sesión y CSRF: el navegador pregunta solo al ver el `401`.
- **`daemon_requires_token` es función aparte**, no un flag de `query_daemon`, siguiendo el molde
  ya probado de `backend_probe`/`backend_requires_key`: pregunta **sin** cabecera, que es la única
  forma de ver lo que encuentra quien no lleva el token.

## Ordered tasks

1. **La variable y el helper**
   - Ficheros: `config.py`
   - Requisitos: REQ-004, REQ-006
   - Verificación: import del módulo; `web_auth_headers()` vacío sin token.
   - Rollback: revertir el bloque.

2. **La puerta**
   - Ficheros: `web/auth.py` (nuevo), `tests/test_web_auth.py`
   - Requisitos: REQ-001, REQ-002, REQ-003, REQ-005
   - Verificación: tests propios + mutantes sobre `auth.py`.
   - Rollback: borrar el módulo; `build_app` deja de importarlo.

3. **Enchufarla, y no dejar fuera al CLI**
   - Ficheros: `daemon.py`, `tests/test_daemon.py`
   - Requisitos: REQ-001, REQ-004, REQ-006
   - Verificación: `build_app` con y sin token; las dos `query_*` doblando `httpx2` por separado.
   - Rollback: revertir; sin la envoltura el puerto vuelve a estar abierto.

4. **Los clientes**
   - Ficheros: `install.py`, `cli.py`, `tests/test_install.py`
   - Requisitos: REQ-007, REQ-009
   - Verificación: el TOML de Codex se parsea y no contiene `${` ni `bearer_token =`.
   - Rollback: revertir; sin el flag la entrada es la de siempre.

5. **Que el diagnóstico no mienta sobre el estado nuevo**
   - Ficheros: `daemon.py` (`daemon_requires_token`), `checks.py`, los **dos** arneses de test
   - Requisitos: REQ-008, REQ-009
   - Verificación: tests del `realm`; mutantes; e2e contra un daemon real protegido.
   - Rollback: revertir; el mensaje vuelve al anterior, que a partir de la tarea 3 sería falso —
     por eso esta tarea **no es opcional**.

6. **Documentación**
   - Ficheros: `SECURITY.md`, `docs/wiki/Daemon.md`, `docs/wiki/Configuration.md`, `CHANGELOG.md`
   - Verificación: la wiki nombra el punto donde esto se rompe en silencio (la variable ausente
     en el entorno del cliente).

## Test strategy

- **Unit:** la puerta sobre una app de juguete con otra montada debajo; el reconocimiento del
  `realm`; la entrada MCP de los dos clientes.
- **Integración:** `build_app` real, con el dashboard montado, con y sin token. Es una pregunta
  distinta de la unitaria —«¿está enchufada?» y no «¿funciona?»— y es la que se olvida.
- **End-to-end:** un daemon de la rama en un puerto aparte, con token, y `curl` contra las cinco
  superficies; el handshake MCP autenticado; y `doctor` con y sin la variable.
- **Verificación al revés:** mutantes sobre `auth.py`, `daemon.py` y `checks.py`. Se exige saber
  **qué** test cae y **con qué mensaje**, no solo que la suite se ponga roja.
- **Secretos:** `gitleaks` en el pre-commit; y tests que comprueban que el token no sale por
  pantalla ni acaba en un fichero de configuración.

## Migration and compatibility

Sin `LOCAL_DELEGATE_WEB_TOKEN` no cambia nada: `proteger()` devuelve la misma app, `install` no
escribe cabeceras y el diagnóstico da el mensaje de siempre. Quien active el token debe
**exportarlo también en el entorno de sus clientes y del CLI**; si no lo hace, el `doctor` se lo
dice con el arreglo concreto en vez de dejarlo adivinando.

## Plan review

- [x] Cada requisito mapea a tarea y verificación (tabla de `spec.md`).
- [x] Nada destructivo; cada tarea revierte por fichero. La única dependencia de orden real es que
      la tarea 5 **debe** ir con la 3: sin ella, el diagnóstico queda mintiendo.
- [x] Sin dependencias nuevas: todo es stdlib.
- [x] Sin trabajo ajeno: la detección de exposición queda explícitamente fuera en `brief.md` y
      `spec.md` por decisión del usuario.
