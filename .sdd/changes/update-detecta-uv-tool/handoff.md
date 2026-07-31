# Handoff: update detecta el CLI instalado como uv tool y dice como actualizarlo

## Current state

- **SDD status:** cerrado.
- **Último gate:** `memory`.
- **Revisión:** PR **#78** mergeado el 2026-07-30, `main` en `02eb48c`. Los 12 checks del PR y el
  CI completo de `main` en verde. **En `Unreleased`, sin publicar.**

## What changed

`update` detecta que el CLI está instalado como `uv tool` y, si hay versión más nueva publicada,
lo dice y da el comando — sin ejecutarlo. «Cómo está instalado esto» pasa a tener una sola
definición (`install_kind()`), que consume también el `fix_hint` del check `cli.published`.
451 tests (+13).

## Decisions

1. **`update` no ejecuta el upgrade, y la razón está medida.** En Windows, reinstalar el entorno
   desde el que corre el proceso **falla y deja la instalación destruida**: borra el paquete y
   luego se estrella contra el `Scripts/` bloqueado. Decisión del usuario con ese dato delante.
2. **La detección es por `uv-receipt.toml` en `sys.prefix`**, no por `uv tool dir`, `UV_TOOL_DIR`
   ni rutas de plataforma. Es una lectura local que responde igual en los tres sistemas y no
   depende de que `uv` esté en el PATH del proceso.
3. **`install_kind()` responde por el proceso que corre**, no por «la instalación de la máquina»:
   en la de desarrollo conviven las dos y afirmar sobre la que no corre sería un falso
   diagnóstico.
4. **Editable gana** cuando se dan los dos: es lo que gobierna de dónde sale el código.
5. **`pip`/`pipx`/conda caen en `OTHER` con texto genérico.** Es mejor que sugerirles
   `uv tool upgrade`, que en esas instalaciones no hace nada.

## Gotchas que costaron tiempo aquí

- **El camino nuevo NO se recorre desde `uv run`**, que es como se prueba todo en este repo: ahí
  `sys.prefix` es el `.venv` del repo. Para verificarlo de verdad hay que ejecutar el Python del
  entorno de `uv tool` con el repo en `PYTHONPATH` — `sys.prefix` real, código nuevo. Sin eso, una
  verificación «real» daría por buena una ejecución que nunca tocó el código.
- **`sys.prefix` hay que leerlo en tiempo de llamada**, nunca en una constante del módulo: si se
  captura al importar, el `monkeypatch` de los tests no llega y estarían probando la máquina en la
  que corren. Es el primo del gotcha del change `doctor-version-publicada` con el default del
  dataclass.
- **Una función que devuelve maquetación rompe a quien la compara.** `uv_tool_lines` devolvía una
  línea vacía inicial de separación, y el test de «esto no cambia el plan» borraba con ella
  **todas** las vacías de la salida. Se arregló en el código: la función devuelve el aviso, la
  separación la pone quien imprime.

## Next action

Backlog: punto 4 (check de hooks duplicados en máquinas donde se ejecutó el instalador de macOS
retirado en el PR #69) y punto 5 (subir el `rev` de ruff en `.pre-commit-config.yaml`).

## Memory

- **Nota canónica:** pendiente de la nota de jornada en el vault (`projects/local-delegate/`).
- **Índices actualizados:** `CHANGELOG.md` y `docs/wiki/Remote-backend.md`.
- Sin secretos, credenciales ni datos personales.
