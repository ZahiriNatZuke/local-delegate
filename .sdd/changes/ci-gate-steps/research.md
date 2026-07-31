# Research: Un gate que mire los steps para que el job fantasma de Windows no bloquee un merge

## Current behavior

**La premisa del backlog se sostiene** — es la primera vez en cuatro intentos que un pendiente de esa
nota resulta exacto, así que conviene decirlo: el diagnóstico de la sesión anterior se reconfirma
punto por punto, y además se le añade el dato que faltaba (qué exige el ruleset).

Un run de `ci.yml` levanta **seis jobs**, ninguno con `needs`, todos en paralelo
(`.github/workflows/ci.yml:20-153`). Comprobado contra el run `30637271414` de `main`:

```
install-smoke        completed  success  10 steps
test (ubuntu-latest) completed  success   8 steps
test (windows-latest)completed  success   8 steps
secrets              completed  success   5 steps
test (macos-latest)  completed  success   8 steps
lint                 completed  success  13 steps
```

Es decir: **`GET /repos/{owner}/{repo}/actions/runs/{id}/jobs` devuelve cada job con su lista de
steps**, cada uno con su `conclusion`. Ese es el dato sobre el que puede decidir un gate.

En las tres ocurrencias del fallo (PR #77, #86 y #88), ese mismo endpoint mostró
`test (windows-latest)` con **`status: in_progress`, `completed_at: null` y los ocho steps en
`success`, incluido `Complete job`** (`docs/wiki/Repo-hardening.md:20-42`). El runner terminó en
~86 s; quien no cierra el job es el backend de GitHub.

**El dato nuevo, consultado por ejecución** (`gh api repos/.../rulesets/19859628`):

```json
{"required_status_checks": [
  {"context": "lint"}, {"context": "test (ubuntu-latest)"},
  {"context": "test (windows-latest)"}, {"context": "test (macos-latest)"},
  {"context": "secrets"}, {"context": "Analyze (python)"}],
 "strict_required_status_checks_policy": true}
```

Los contextos se exigen **por nombre**, así que mientras `test (windows-latest)` no reporte
`completed`, el merge está bloqueado. Esto convierte el trabajo en **dos cambios acoplados**: el job
nuevo y el ruleset. No se puede hacer solo uno.

Dos detalles que acotan el alcance:

- **`install-smoke` corre pero NO es requerido.** Coincide con lo anotado en el backlog («falta
  decidirlo»). El gate no debe cambiar eso por la puerta de atrás: si el gate exigiera
  `install-smoke`, lo estaría promoviendo a requerido sin decidirlo.
- **`Analyze (python)` no es de `ci.yml`**, es de `codeql.yml` — otro workflow y **otro run**. Un
  gate dentro de `ci.yml` no ve sus jobs. Sigue siendo check propio del ruleset.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `.github/workflows/ci.yml` | seis jobs en paralelo, `permissions: contents: read` global | job `gate` nuevo, con `actions: read` propio | `ci.yml:10-11,20-153` |
| Ruleset `protect-main` (id 19859628) | exige 6 contextos por nombre, `strict` | los cuatro de `ci.yml` se sustituyen por el gate; `Analyze (python)` se queda | `gh api .../rulesets/19859628` |
| `scripts/setup_repo_security.sh` | aplica el ruleset de forma idempotente | es quien tiene que llevar la lista nueva; el ruleset a mano se desincroniza | `docs/wiki/Repo-hardening.md:73-84` |
| `scripts/` (script del gate) | `check_vendor.py` es el precedente: solo stdlib, lo llama un workflow | script nuevo con la misma regla | `scripts/check_vendor.py` |
| `tests/` | sin tests de workflows hoy | test que ate la lista esperada a la matriz de `ci.yml`, y el caso «un step falló → gate falla» | `Get-ChildItem tests -Filter *workflow*` → vacío |
| `docs/wiki/Repo-hardening.md` | documenta el fallo y dice que el gate es «la vía por explorar» | pasa a documentar el mecanismo y su modo de fallo | `Repo-hardening.md:62-66` |

## Existing conventions

- **Lo que corre el repo o el CI vive en `scripts/`; lo que corre el usuario, en el CLI.** Criterio
  ya establecido (el wheel no empaqueta `scripts/`). El gate lo corre el CI → `scripts/`.
- **Un script de CI usa solo stdlib.** `check_vendor.py` habla con la red (OSV) sin dependencias, y
  así no obliga a un `uv sync` previo. El gate hace lo mismo con `urllib.request`.
- **Una sola fuente de verdad, y si la fuente puede mentir, atarla con un test.** Precedente
  directo: la tabla de tools de `SKILL.md` se ata a `server.mcp.list_tools()` **por conjuntos
  iguales, no por inclusión**. Aquí aplica igual a la lista de jobs esperados.
- **`permissions` mínimo por job**, no global (`ci.yml:8-11`, y `publish.yml` como ejemplo).
- Comentarios en `ci.yml` que explican **por qué**, incluida la historia de lo que no funcionó.

## Dependencies and integrations

- **API de GitHub Actions**, endpoint `runs/{id}/jobs`. Requiere permiso `actions: read`, que hoy no
  está concedido (el global es `contents: read`).
- **`GITHUB_TOKEN`** del propio run. En PRs desde forks el token es de solo lectura — suficiente,
  el gate solo lee. Este repo no recibe PRs de forks hoy.
- **PyYAML 6.0.3**, declarado en el grupo `dev` de `pyproject.toml:101` (no es transitiva): un test
  puede parsear `ci.yml` con seguridad. **El gate en ejecución no lo necesita.**
- **Repo público** (`visibility: public`): los minutos de Actions no se facturan, así que el polling
  del gate no tiene coste económico.

## Alternativas consideradas

| Opción | Por qué se descarta |
| --- | --- |
| `needs: [...]` + `if: always()` | **`needs` espera a que el job termine**, que es justo lo que no pasa. El gate quedaría `queued` para siempre y bloquearía igual. |
| Auto `cancel` + `rerun` desde un workflow | Exige **`actions: write`**, contra el mínimo privilegio del repo. Además `gh run rerun --job` responde «cannot be rerun» mientras el job siga `in_progress` (medido), y `workflow_run` **no dispara** con el run sin cerrar; quedaría un `schedule` con retraso propio. Más permisos, más piezas y más lento. |
| Quitar `test (windows-latest)` de los requeridos | Renuncia a la protección que justifica la matriz: la 0.11.0 arregló una fuga de handles **que solo ocurría en Windows** y que un CI de solo Ubuntu no veía (`ci.yml:56-59`). |
| Subir `timeout-minutes` | No aplica: ya está medido que no dispara sobre este fallo. |

## Risks and unknowns

**Confirmado:**

- El endpoint expone los steps de cada job con su `conclusion` (verificado contra un run real).
- El ruleset exige contextos por nombre y `test (windows-latest)` es uno.
- El gate y los demás jobs arrancan a la vez: **ningún job de `ci.yml` declara `needs`**.

**Por validar, y manda el diseño:**

- **¿Aparecen los seis jobs en la API desde el primer momento, o van apareciendo?** Si el gate
  consulta antes de que existan y decide con lo que ve, **pasa en verde sin haber comprobado nada**
  — el peor fallo posible aquí. Se mide en vivo en el PR de este change, pero el diseño **no puede
  depender de la respuesta**: la lista esperada tiene que ser explícita.
- **¿Muestra la API los steps ya concluidos de un job `in_progress`?** Las tres ocurrencias dicen
  que sí; se reconfirma en vivo durante la verificación.

**Riesgos asumidos:**

- **El gate puede ser víctima del mismo fallo.** Corre en `ubuntu-latest`, donde no se ha observado,
  pero no hay garantía. Si le pasa, el remedio vuelve a ser `cancel` + `rerun` — no se empeora nada
  respecto a hoy.
- **Ventana de un solo check requerido.** Al pasar de cuatro contextos de `ci.yml` a uno, un defecto
  en el gate desprotege los cuatro de golpe. De ahí que el test obligatorio no sea «el gate pasa»
  sino **«con un step fallido, el gate falla»** — verificar el test al revés.
- **Orden de aplicación.** Un contexto requerido que nadie reporta bloquea el repo para siempre: el
  job tiene que existir y haber reportado **antes** de tocar el ruleset.
