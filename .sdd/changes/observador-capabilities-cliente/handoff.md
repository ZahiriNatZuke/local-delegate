# Handoff: observador de capabilities del cliente

## Current state

- SDD status: `result-review`, listo para cerrar.
- Último gate aprobado: `conformance`.
- Revisión: PR **#95**, rama `feat/observador-capabilities-cliente`, los 13 checks en verde.

## What changed

`clients.py`: un `ServerMiddleware` que observa cada conexión MCP y registra qué cliente hay al
otro lado —nombre, versión, capabilities— y **qué revisión de protocolo negoció de verdad**. El dato
va a `clients.jsonl` (una línea por identidad y ejecución) y a `GET /api/status` (estado en vivo).
16 tests nuevos; la suite queda en 519 passed, 1 skipped.

## Decisions

Lo que una sesión futura no puede deducir del código:

- **En `initialize` no hay nada que leer, y está medido.** El middleware corre antes del commit del
  handshake y ve `None` en capabilities y en identidad. El trabajo entró con el enunciado
  «registrar en `initialize`» y ese enunciado **no habría registrado nada**. Por eso el observador
  se salta ese método a propósito: no es una optimización, es la condición para que funcione.
- **El dedupe es por identidad declarada, no por conexión.** `ServerRequestContext` solo expone
  `session`, y `ServerSession` no publica ni `session_id` ni `connection`: usar
  `session._connection` sería atarse a un privado del SDK. Consecuencia asumida: **dos instancias
  idénticas del mismo cliente cuentan como una**.
- **El lock no es decorativo y su alcance importa.** `/api/status` es un endpoint **síncrono** de
  FastAPI, así que lo lee el threadpool de uvicorn desde otro hilo. El lock cubre comprobar,
  escribir y anotar como una sola operación —si no, dos mensajes concurrentes dejan dos líneas— y
  `snapshot()` devuelve una copia construida **dentro** del lock.
- **Es `ServerMiddleware`, no el `Extension`/`intercept_tool_call` descartado.** Parecen lo mismo y
  no lo son: aquel se descartó porque la telemetría de coste vive en los caminos al backend; la
  identidad del cliente, al revés, **solo** existe en el borde MCP.

## Lo que la medición dio, y que decide lo siguiente

```
claude-code        2.1.220              protocolo 2025-11-25   caps: elicitation, roots
codex-mcp-client   0.146.0-alpha.3.1    protocolo 2025-06-18   caps: elicitation
```

- **Los dos declaran `elicitation`**: la decisión que estaba bloqueada queda desbloqueada, en
  sentido afirmativo.
- **Cada uno negocia una revisión distinta, y ninguna es la de las constantes del SDK.**
- Ninguno declara `sampling`.

### Logística de la medición, por si hay que repetirla

- **Claude Code y Codex hablan con local-delegate por *stdio*, no con el daemon del 9393**: cada uno
  lanza su propio proceso. Por eso se pudo medir sin parar nada del usuario.
- Claude Code: `claude -p ... --mcp-config <fichero> --strict-mcp-config`.
- Codex: **no lee un `config.toml` del directorio de trabajo**, solo el global. Hay que usar
  overrides `-c`. Y `codex.cmd` pasa por `cmd.exe`, **que se come las comillas dobles**: un
  `args=["a","b"]` llega como `[a,b]` y falla con *expected a sequence*; con comillas simples de
  TOML (`args=['a','b']`) sobrevive.

## Next action

Evaluar **`elicitation`** en su propio change, ya con el dato: los dos clientes la soportan. Después,
el **check de `doctor`** sobre los clientes observados, que el usuario dejó encolado a propósito
para atacarlo cuando hubiera datos con los que decidir qué cuenta como fallo.

## Memory

- Nota canónica: `projects/local-delegate/overview.md` (vault).
- Índices actualizados: `docs/wiki/Architecture.md` (módulo `clients.py` y sección de descartes),
  `README.md` (`LOCAL_DELEGATE_LOG_DIR`), `CHANGELOG.md` (`Unreleased`).
