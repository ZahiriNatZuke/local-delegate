# Brief: El puerto del daemon exige token cuando se configura uno

## Problem

El puerto del daemon (`9393` por defecto) sirve **tres cosas sin ninguna autenticación**: el
endpoint MCP, el dashboard y `/api/*`. Mientras solo escuche en loopback eso es aceptable y está
documentado. Deja de serlo en cuanto hay un proxy delante.

**Medido en la máquina de referencia, no supuesto** (`curl` contra el nombre publicado en la VPN):

| Petición | Resultado |
| --- | --- |
| `POST /mcp` | `421 Invalid Host header` |
| `POST /mcp` con `-H "Host: 127.0.0.1:9393"` | **`200`**, `initialize` completo con capabilities |
| `GET /` | `200`, el panel entero |
| `GET /api/status`, `/api/daemon`, `/api/backend` | `200` — `base_url`, modelos, pid, rutas |

Dos conclusiones, y la segunda tumbó el diseño que parecía obvio:

1. **El endpoint MCP corre dentro del daemon**, o sea con la credencial del backend ya cargada:
   quien alcance ese puerto puede delegar sin tener ninguna key.
2. **La protección anti-DNS-rebinding del SDK no es control de acceso.** Rechaza un `Host` ajeno,
   pero se salta con una cabecera a mano. Es defensa contra un navegador engañado —que no puede
   fijar el `Host`— y nunca pretendió otra cosa.

Y el proxy conecta contra `127.0.0.1`, así que **ni la IP de origen ni `LOCAL_DELEGATE_WEB_HOST`
delatan** que el daemon dejó de ser local. Hace falta un secreto.

## Desired outcome

Con una variable de entorno definida, todo el puerto exige token. Sin ella, nada cambia para nadie.
Y el token no acaba escrito en ningún fichero de configuración.

## In scope

- Middleware que exige el token en el endpoint MCP, el dashboard y `/api/*`.
- Que el propio CLI siga pudiendo hablar con su daemon cuando el token está puesto.
- Que `install` deje a Claude Code y a Codex autenticándose **por referencia** a la variable.
- Que `doctor` no mienta sobre el estado nuevo que este cambio introduce.
- `SECURITY.md`, wiki y CHANGELOG.

## Out of scope

- **Detectar si el puerto está publicado.** Descartado con el usuario: obligaría a atar el MCP a
  una herramienta externa concreta (una VPN, un proxy) que la mayoría de usuarios no usa. El MCP no
  infiere la topología de red de nadie.
- Quitar el puerto del proxy: decisión del usuario, y no es asunto del repo.
- Cualquier defensa basada en el `Host` o en la IP de origen: descartada **por medición**, no por
  criterio.
- OAuth, cuentas, sesiones o roles. Aquí no hay usuarios: hay un secreto.

## Constraints and risks

- **No romper a nadie.** Hoy ninguna instalación tiene token; exigirlo siempre dejaría sin daemon a
  todo el que actualice.
- **El navegador no manda `Authorization: Bearer`** por escribir una URL. Un diseño solo-Bearer
  dejaría el panel inalcanzable para su único usuario real, y acabaría desactivado.
- **El CLI habla con su propio daemon** (`query_daemon`, `query_backend`). Proteger el puerto sin
  darle credencial rompería el singleton y el diagnóstico a la vez.
- **La expansión de `${VAR}` es una premisa, no un hecho**: es el mismo mecanismo que ya falló con
  `--api-key-env`. Hay que medirla antes de construir encima.

## Open questions

Resueltas con el usuario antes de escribir código:

- **Por defecto, opt-in por variable** (no obligatorio con token autogenerado).
- **El token llega al cliente por referencia a una variable de entorno**, no como literal.
- **Sin detección de exposición**, por la regla de arriba.
