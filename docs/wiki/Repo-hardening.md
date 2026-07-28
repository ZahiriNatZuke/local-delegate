# Configuración del repositorio

`local-delegate` es un paquete público que se instala con `uvx` y publica en PyPI: quien lo
usa confía en que lo que hay en `main` es lo que se publicó. Esta página recoge la
configuración mínima que sostiene esa confianza, separada en lo que vive **en el repo** (y por
tanto se revisa en un PR) y lo que solo existe en los **ajustes de GitHub**.

## En el repo

| Archivo | Qué aporta |
|---|---|
| `.github/workflows/ci.yml` | tests, ruff, formato, validación del JS del dashboard y escaneo de secretos en cada PR. `permissions: contents: read` (mínimo privilegio) |
| `.github/workflows/codeql.yml` | análisis estático de seguridad (semanal + en cada PR) |
| `.github/workflows/publish.yml` | publicación por OIDC/Trusted Publishing: **sin tokens en secrets**. `permissions: {}` global, ampliado solo en el job |
| `.github/dependabot.yml` | PRs semanales de dependencias Python y de GitHub Actions |
| `.github/CODEOWNERS` | asignación automática de revisión |
| `SECURITY.md` | canal privado de reporte y superficie a tener en cuenta |
| `.pre-commit-config.yaml` | gitleaks + ruff antes de cada commit local |

## En los ajustes de GitHub

No se pueden versionar, así que van en un script idempotente:

```bash
./scripts/setup_repo_security.sh --dry-run   # enseña cada llamada
./scripts/setup_repo_security.sh             # aplica
```

Aplica:

- **Regla sobre la rama por defecto** (`~DEFAULT_BRANCH`, así sigue a la rama y no a su nombre):
  exige PR, prohíbe `force-push` y el borrado, exige la CI en verde con la rama al día, y no deja
  mergear con hilos de revisión sin resolver. Solo squash merge.
- **`code_scanning`**: que el job de CodeQL acabe en verde no basta —puede terminar bien habiendo
  encontrado una alerta—, así que la regla mira las alertas. Se omite con `--no-code-scanning`.
- **Secret scanning** con *push protection*: GitHub rechaza el push que contenga un secreto.
- **Dependabot**: alertas de vulnerabilidades y parches de seguridad automáticos.
- **Private vulnerability reporting**: el canal que anuncia `SECURITY.md`.
- **Ajustes de merge**: solo squash, borrado automático de la rama, auto-merge disponible.

### Usarlo en otro repositorio

Los checks requeridos son los nombres de los jobs de *su* CI, así que se pasan por parámetro:

```bash
./scripts/setup_repo_security.sh --repo OWNER/REPO \
  --checks "Lint, typecheck and unit tests|End-to-end tests" --no-code-scanning
```

El separador es `|` y no la coma **a propósito**: los nombres de job llevan comas
(`Lint, typecheck and unit tests`) y paréntesis (`test (ubuntu-latest)`) con toda naturalidad.
`--check "X"` es la forma repetible para nombres con cualquier cosa rara.

**Antes de aplicar, el script comprueba que alguien reporta cada check pedido** y aborta si no.
Es el error más caro de este script: un check exigido que nadie publica —una errata, un job
renombrado, una matriz que cambió— deja **todos** los PR esperando para siempre. La comprobación
mira la rama por defecto y el PR más reciente, y consulta *check-runs* **y** *commit statuses*:
Actions publica lo primero, pero integraciones como Vercel publican lo segundo. Con
`--skip-verify` se salta, para el caso de un repo cuyo CI todavía no ha corrido nunca.

### Dos decisiones que no son las de por defecto

**Cero aprobaciones requeridas.** Con un único mantenedor, exigir una aprobación bloquea el
repositorio: no puedes aprobar tu propio PR. La barrera que sí aporta aquí es *"todo entra por
un PR con la CI en verde"*, no el conteo de revisiones. Cuando haya más gente:
`./scripts/setup_repo_security.sh --reviews 1`.

**Sin bypass de administrador.** Si el dueño puede saltarse la regla sin darse cuenta, la regla
no protege del descuido — que es exactamente el riesgo en un repo de una persona. Si en algún
momento necesitas la vía de escape: `--admin-bypass`.

### Lo que queda a mano

- **Environment `pypi`**: añade *required reviewers* o restringe el despliegue a tags `v*`, para
  que un push accidental de tag no publique en PyPI sin confirmación
  (*Settings → Environments → pypi*).
- **Settings → Actions**: *Workflow permissions* en **read-only** y desmarcar *Allow GitHub
  Actions to create and approve pull requests*.

## Convención de ramas

Rama por cambio, con prefijo según lo que hace y un nombre que describa el cambio:

```
feat/<qué-añade>      fix/<qué-arregla>      docs/<qué-documenta>
chore/<mantenimiento> refactor/<qué-reordena>
```

El prefijo del PR y del commit sigue [Conventional Commits](https://www.conventionalcommits.org/es/),
que es lo que alimenta el `CHANGELOG.md`.
