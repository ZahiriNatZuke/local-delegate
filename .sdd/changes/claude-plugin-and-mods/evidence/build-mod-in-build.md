# Evidencia — build-mod-in-build

Lote corto de corrección tras F2-mod-core (#403): `register.js` no se versiona y solo lo generaba
el job `plugin` del CI, así que `publish.yml`, `uv build` y `uv tool install .` daban una rueda sin
mod.

## Qué se hizo

- **Hook de hatchling** `hatch_build.py` (`[tool.hatch.build.targets.wheel.hooks.custom]`): carga
  `build_mod.py` por ruta (`scripts/build_mod.py` en el repo, `_build_mod.py` en el sdist) y escribe
  `register.js` con el mismo `build()` en todo build de la rueda, también en el editable de
  `uv sync`. Sin dependencias nuevas: la interfaz viene con hatchling.
- **Rueda**: `artifacts = [".../register.js"]`, porque `.gitignore` lo saca de la selección.
- **sdist**: `force-include` de `scripts/build_mod.py` como `_build_mod.py` en la raíz. Se descartó
  meterlo en `scripts/`: `test_bump_version.py`, `test_ci_gate.py`, `test_vendor.py` y
  `test_mod_static.py` se saltan solo si `scripts/` no existe, y con un `scripts/` parcial
  fallarían en quien corra la suite desde el sdist.
- **`.gitignore`** ignora `src/local_delegate/resources/claude-plugin/local-delegate/register.js`.
- **`[tool.uv] cache-keys`**: `pyproject.toml`, `hatch_build.py`, `scripts/build_mod.py`, el
  `plugin.json` del plugin, `mod/**/*.js` y `mod/i18n/*.json`. Medido: sin ellas, borrar
  `register.js` y `uv sync` no lo regenera (editable de la caché); con ellas, tocar `mod/common.js`
  y `uv sync` lo regenera con el cambio. Borrarlo a mano sigue sin notarse (uv no mira salidas).
- **CI `plugin`**: se mantiene el paso explícito «Construir register.js del mod» para el árbol de
  fuentes (`validate`/`plugin test` no pasan por build y el editable puede venir de la caché de
  uv); el script y el hook llaman al mismo `build()`, así que no hay dos versiones. «La rueda
  contiene el plugin» pasa a `uv build` (sdist y rueda desde el sdist), exige que el sdist NO
  lleve `register.js` y que el de la rueda tenga `register_commands` y `register_pinned_tools`.
- **`publish.yml`**: tras `uv build`, paso «La rueda lleva el mod del plugin» antes de subir a PyPI.
- **`docs/wiki/Publishing.md`**: sección del mod generado en el build y fila del job `plugin`.

## Pruebas

`tests/test_build_hook.py` (2 tests, ~4 s): `uv build` del repo a un temporal, y

- `test_sdist_carries_what_regenerates_the_mod`: el sdist trae `hatch_build.py`, `_build_mod.py` y
  `mod/{common,commands,pinned-tools}.js` + `i18n/es.json`, no trae `register.js` ni `scripts/`;
- `test_wheel_built_from_sdist_carries_register_js_with_its_pieces`: la rueda (construida desde el
  sdist) lleva `register.js` con `mod/commands.js`, `mod/pinned-tools.js`,
  `register_commands(on, options)` y `register_pinned_tools(on, options)`.

| Paso | Resultado |
|---|---|
| Antes del cambio | 2 fallan: «la rueda salió sin el mod» y falta `_build_mod.py` en el sdist |
| Con el cambio | 2 pasan |
| Mutante 1: tabla `hooks.custom` renombrada | falla `test_wheel_…` en `assert …/register.js in names` («la rueda salió sin el mod»); el del sdist pasa |
| Mutante 2: sin el `force-include` | la rueda desde el sdist no se construye: `RuntimeError: build_mod.py is missing under …` y el fixture falla en `assert result.returncode == 0` |

Comprobados también a mano: `uv build --wheel` desde el árbol (sin `register.js` previo) lleva el
mod; el script del paso del CI y el de `publish.yml`, extraídos del YAML, pasan sobre la rueda
local; `yaml.safe_load` de los dos workflows.

## Suite

`uv run pytest -n 2 -q`: 4373 pasados, 28 saltados, 1 fallo, el detector de nombres en español
con cinco palabras inglesas sin clasificar del test nuevo (`hatch`, `regenerates`, `sdist`, `tar`,
`wheel`). Se añadieron a `en` de `scripts/data/spanish_lexicon.json` (fuera de la lista de ficheros
del lote, permitido por el brief común) y el detector pasa. `ruff check` y `ruff format --check`
limpios.
