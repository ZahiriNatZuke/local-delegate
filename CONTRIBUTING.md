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

`main` está protegida: todo entra por PR con la CI en verde, y no se admite `force-push` ni
borrado de la rama (ver [Configuración del repositorio](docs/wiki/Repo-hardening.md)).

1. Crea una rama desde `main` con **prefijo según el tipo de cambio** y un nombre que describa
   qué hace: `feat/…`, `fix/…`, `docs/…`, `refactor/…`, `chore/…`
   (p. ej. `fix/inflight-multiproceso`, `feat/chunking-traduccion`).
2. Usa el mismo prefijo en el título del PR y en los commits
   ([Conventional Commits](https://www.conventionalcommits.org/es/)): es lo que alimenta el
   `CHANGELOG.md`.
3. Asegúrate de que `ruff check`, `ruff format --check` y `pytest` pasan.
4. Actualiza `CHANGELOG.md` (sección *Unreleased*).
5. Describe el cambio con claridad en el PR.
6. **Después de mezclar**, comprueba `main` y no solo el PR:

   ```bash
   uv run python scripts/check_main.py
   ```

   Lista los checks del último commit de `main` que no estén en verde (también los que no son
   workflows: code scanning, Socket, GitGuardian) y **las alertas abiertas de CodeQL en `main`**,
   de cualquier gravedad. Sale con 0 solo si no hay nada; con 2 si algo sigue corriendo. Las
   alertas se arreglan, no se descartan.

### Tests que miden tiempo

Ningún test compara un reloj con un tope en el paso paralelo del CI (`-n auto`): bajo carga eso
mide la máquina, no el código. `tests/test_timing_marker_guard.py` lo hace cumplir.

- **Un coste** (que algo crezca lineal y no cuadrático) se mide con `tests/perf.py`
  (`perf.assert_linear(pequeño, grande, size_ratio=10)`) y lleva `@pytest.mark.perf`. Nunca segundos
  fijos ni `time.process_time`. Corre en el job `perf`, solo y sin `-n`.
- **Una espera real con tope** (un daemon, un socket, un plazo de verdad) lleva
  `@pytest.mark.real_io`: corre en los tres sistemas, en serie y con un reintento.

## pre-commit

```bash
uv run pre-commit install    # (o pipx run pre-commit install)
```

Corre `gitleaks` antes de cada commit para bloquear secretos, `ruff` y
`scripts/check_local.py --fix`: las huellas de los hooks (las une solo; vuelve a añadir
`scripts/data/hook_hashes_after.json`), la versión de la captura del README, los nombres en español
y los textos fuera del catálogo. Son cosas que el CI comprueba y que antes se descubrían diez
minutos después del push.
