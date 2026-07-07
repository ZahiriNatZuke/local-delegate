# Contribuir a local-delegate

¡Gracias por tu interés! Este proyecto es un MCP stdio en Python gestionado con [`uv`](https://docs.astral.sh/uv/).

## Entorno de desarrollo

```bash
uv sync --group dev        # crea .venv e instala deps + dev tools
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # formato
```

Python **≥ 3.11**. Usa siempre `uv` (no el `python` del sistema).

## Ejecutar el MCP localmente

```bash
uv run local-delegate      # arranca el server stdio (necesita un endpoint OpenAI-compatible)
```

La web de métricas queda en `http://127.0.0.1:9393` (desactiva con `LOCAL_DELEGATE_WEB=0`).

## Reglas del proyecto

- **Cliente genérico:** el paquete solo asume "un endpoint OpenAI-compatible en una URL". Nada
  específico de un backend, hardware o máquina debe entrar al código: va a `docs/recipes/`.
- **Sin rutas hardcodeadas:** todo configurable por variables de entorno (ver README).
- **Nunca subas secretos** ni tus configs reales de Claude. Solo plantillas `*.example`.
  `gitleaks` corre en pre-commit y CI.

## Pull requests

1. Crea una rama desde `main`.
2. Asegúrate de que `ruff check`, `ruff format --check` y `pytest` pasan.
3. Actualiza `CHANGELOG.md` (sección *Unreleased*).
4. Describe el cambio con claridad en el PR.

## pre-commit

```bash
uv run pre-commit install    # (o pipx run pre-commit install)
```

Corre `gitleaks` antes de cada commit para bloquear secretos.
