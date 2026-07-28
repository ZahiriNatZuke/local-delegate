# Brief: Acotar el SDK mcp por debajo del major 2 y cerrar el punto ciego de resolucion libre

## Problem

El SDK `mcp` publicó **2.0.0**, un breaking change que elimina `mcp.server.fastmcp`.
`local-delegate-mcp` declara `mcp>=1.2` **sin techo de major** (`pyproject.toml:22`), así que
`uvx` resuelve a 2.0.0 y el proceso muere en el import antes de poder hablar MCP:

```
File ".../local_delegate/server.py", line 32, in <module>
    from mcp.server.fastmcp import FastMCP
ModuleNotFoundError: No module named 'mcp.server.fastmcp'
```

Claude Code lo reporta como `MCP error -32000: Connection closed`, que es solo el síntoma del
proceso muerto al arrancar. El traceback real vive en el `Server stderr` del log del cliente.

Detectado por el usuario el **2026-07-28 en la Mac**, con 0.12.1 instalada vía el script
`update_to_latest.sh`. **La 0.12.1 publicada está rota para cualquier instalación nueva**, en
cualquier máquina: el techo ausente viaja dentro del wheel.

Punto ciego asociado: `uv.lock` fija `mcp 1.28.1`, así que el CI está **verde** y el daemon de
Windows (venv editable) sigue funcionando mientras el paquete publicado está roto. Ningún check
del repositorio instala el paquete resolviendo dependencias como lo hace `uvx`.

## Desired outcome

1. Una instalación nueva `uvx local-delegate-mcp` completa el handshake MCP sin pines manuales.
2. El repositorio detecta por sí solo el próximo major incompatible de una dependencia, en vez de
   enterarse por un usuario en otra máquina.

## In scope

- Techo de major para `mcp` en `pyproject.toml` y regeneración de `uv.lock`.
- Job de CI que instale el paquete construido con **resolución libre** (sin lock) y verifique un
  handshake `initialize` real.
- `CHANGELOG.md`, entrada de la versión de patch y bump con `scripts/bump_version.py`.
- Publicación de **0.12.2**, sujeta a confirmación explícita del usuario.

## Out of scope

- **Migrar a la API 2.x del SDK.** Es un cambio SDD propio: la superficie no es solo el import
  (ver `research.md`), incluye `settings.streamable_http_path` y `streamable_http_app()`, que son
  API de configuración del server y no está verificado cómo quedan en 2.x.
- Revisar el resto de dependencias en busca de techos ausentes (se anota como seguimiento).
- Arreglar los hooks rotos del `settings.json` del usuario: es su máquina, no el paquete.

## Constraints and risks

- **Regla dura del proyecto:** no se publica a PyPI sin confirmación explícita del usuario.
- `main` está protegida: todo entra por PR con los 6 checks en verde, solo squash.
- Convenciones: Conventional Commits, ramas `fix/…`, `CHANGELOG.md` en cada PR, todo en español.
- **Un check exigido que nadie reporta bloquea el repositorio para siempre.** El job nuevo se
  añade primero y solo se exige después de comprobar que publica su resultado.
- Riesgo de falso verde: un job que nunca ha fallado no prueba que detecte nada. Hay que
  demostrar que falla sin el techo.
- PyPI sirve el endpoint JSON con caché y anuncia la versión anterior justo tras publicar.

## Open questions

Ninguna bloqueante. La decisión pin-vs-migración ya está tomada: pin ahora, migración aparte.
