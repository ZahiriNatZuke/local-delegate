# Implementation plan: El hook de ruff usa el del proyecto y gitleaks sube a la ultima

## Approach

Un solo fichero, `.pre-commit-config.yaml`. El bloque de ruff pasa de `repo:
https://github.com/astral-sh/ruff-pre-commit` con `rev` a `repo: local` con
`language: system` y `entry: uv run ruff …`.

`gitleaks` **se queda como está**, con su `rev` remoto: ahí sí tiene sentido, porque es un binario
que no forma parte del entorno del proyecto. Solo se le sube la versión. La asimetría entre los dos
bloques es deliberada y merece quedar escrita en el fichero: uno se fija porque no es nuestro, el
otro no se fija porque sí lo es.

## Ordered tasks

### 1. El bloque de ruff, local

- **Ficheros:** `.pre-commit-config.yaml`
- **Requisitos:** REQ-001..REQ-003, REQ-005
- **Qué:** dos hooks locales (`ruff` y `ruff-format`) con `language: system`,
  `types_or: [python, pyi]` y `entry: uv run ruff check --fix` / `uv run ruff format`, más el
  comentario que explica por qué son locales.
- **Cuidado:** `pass_filenames` queda en su valor por defecto (verdadero), así que `pre-commit` le
  pasa los ficheros staged y el hook actúa solo sobre ellos — igual que hacía el hook remoto. **Hay
  que comprobarlo por ejecución**, no suponerlo.
- **Verificación:** tarea 3.
- **Rollback:** el fichero anterior está en git.

### 2. `gitleaks` al día

- **Ficheros:** `.pre-commit-config.yaml`
- **Requisitos:** REQ-004
- **Qué:** `rev: v8.18.4` → `v8.30.1`.
- **Verificación:** el hook corre y pasa sobre todo el repositorio.

### 3. Ejecución real

- **Requisitos:** REQ-006 y los tres escenarios
- **Qué:**
  - `pre-commit run --all-files` → todos verdes **y `git status` limpio** (AC-1);
  - comprobar que el ruff del hook es el mismo binario que `uv run ruff` (AC-2);
  - un `git commit` de verdad, que es el escenario que falla hoy (AC-3);
  - y los cuatro pasos del CI, para descartar que el cambio afecte a otra cosa.

## Test strategy

- **Unit / Integration:** no aplica — es configuración de herramientas, no código. No hay nada que
  importar ni que doblar.
- **End-to-end:** `pre-commit run --all-files` y un commit real. Es la única verificación que
  significa algo aquí.
- **Verificación al revés:** no aplica en el sentido habitual (no hay rama de código que romper),
  **pero sí hay una comprobación equivalente y vale la pena**: el `git status` limpio tras
  `run --all-files` es justo lo que fallaría si las versiones estuvieran desalineadas. Es la
  prueba de que el arreglo funciona, no una formalidad.
- **Seguridad:** gitleaks corre sobre todo el repositorio con la versión nueva. Si detectara algo
  que la vieja no veía, se atiende antes de commitear.

## Migration and compatibility

- **Quien tenga los hooks instalados** no necesita hacer nada: `pre-commit` lee el config en cada
  ejecución. La primera con `repo: local` ni siquiera descarga nada.
- **El entorno cacheado del ruff viejo** queda huérfano en `~/.cache/pre-commit`. Inofensivo; lo
  limpia `pre-commit gc` si alguien quiere.
- **El CI no cambia:** sigue con `ruff check .` y `ruff format --check .`.

## Revisión adversarial del plan

Tres hallazgos, todos incorporados.

- **R-1 — `uv run` dentro de un hook de git puede no encontrar `uv`.** Los hooks de git no siempre
  heredan el PATH interactivo (el caso clásico es un cliente gráfico). Aquí es aceptable —este
  repositorio se trabaja desde terminal y `uv` está en el PATH del sistema, no en el del shell—,
  pero el fallo sería «uv: command not found» al commitear, que al menos **dice qué pasa**, frente
  al fallo actual, que reformatea en silencio y aborta el commit por un motivo que no explica.
  Queda anotado.
- **R-2 — `types_or: [python, pyi]` debe cubrir lo mismo que cubría el hook remoto.** Es
  exactamente lo que declara `ruff-pre-commit` en su propio `.pre-commit-hooks.yaml`, así que se
  conserva el alcance. Si se omitiera, el hook correría sobre **todos** los ficheros y ruff se
  quejaría de los que no son Python.
- **R-3 — `pre-commit run --all-files` pasa TODOS los ficheros al hook**, mientras que en un commit
  pasa solo los staged. Los dos caminos hay que ejercitarlos: el primero en la tarea 3, y el
  segundo con un commit real. Probar solo uno dejaría el otro sin cubrir.

## Plan review

- [x] Cada requisito mapea a una tarea y a una verificación.
- [x] Sin operaciones destructivas: se edita un fichero de configuración versionado.
- [x] Dependencias explícitas: ninguna nueva; ruff ya está en el grupo de desarrollo.
- [x] Sin trabajo ajeno: no se tocan reglas de ruff, ni el CI, ni se añaden hooks.
