#!/usr/bin/env bash
# setup_repo_security.sh — aplica la configuración mínima recomendada del repositorio.
#
# Lo que NO puede vivir en el repo (protección de rama, secret scanning, alertas) se aplica
# aquí, en un solo comando idempotente, en vez de en una lista de clics que nadie repite.
#
#   ./scripts/setup_repo_security.sh --dry-run      # enseña cada llamada, no cambia nada
#   ./scripts/setup_repo_security.sh                # aplica
#   ./scripts/setup_repo_security.sh --admin-bypass # deja que un admin salte la regla
#
# Requiere `gh` autenticado con permiso de administración sobre el repo.
#
# Decisiones (y por qué), para un proyecto público mantenido por una persona:
#
#  - Regla de rama sobre `main` que exige PR y CI en verde, y bloquea force-push y borrado.
#    Es lo que impide reescribir la historia de un paquete ya publicado en PyPI.
#  - **Cero aprobaciones requeridas** por defecto: con un solo mantenedor, exigir una
#    aprobación bloquea el repo (no puedes aprobar tu propio PR). La barrera útil aquí es
#    "todo pasa por un PR con CI verde", no el conteo de revisiones. Con `--reviews N` se
#    sube cuando haya más gente.
#  - Sin bypass de admin salvo que lo pidas: si el dueño puede saltarse la regla sin querer,
#    la regla no protege del descuido, que es justo el riesgo real en un repo de una persona.
#  - Secret scanning + push protection: el repo publica a PyPI y documenta setups con API
#    keys; que GitHub rechace el push de un secreto es más barato que rotarlo.

set -euo pipefail

OWNER="${OWNER:-ZahiriNatZuke}"
REPO="${REPO:-local-delegate}"
BRANCH="${BRANCH:-main}"
REVIEWS=0
ADMIN_BYPASS=0
DRY=0

# Nombres de los jobs de .github/workflows que deben estar en verde para poder mergear.
# OJO: tienen que coincidir EXACTAMENTE con el nombre que publica cada job. Un check exigido
# que nadie reporta deja los PR esperando para siempre, así que si se renombra un job o se
# cambia su matriz hay que actualizar esta lista y volver a aplicar el script. Los jobs en
# matriz publican un check por combinación, con el valor entre paréntesis.
REQUIRED_CHECKS=(
  "lint"
  "test (ubuntu-latest)"
  "test (windows-latest)"
  "test (macos-latest)"
  "secrets"
  "Analyze (python)"
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --admin-bypass) ADMIN_BYPASS=1 ;;
    --reviews) REVIEWS="$2"; shift ;;
    --repo) OWNER="${2%%/*}"; REPO="${2##*/}"; shift ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "opción desconocida: $1" >&2; exit 2 ;;
  esac
  shift
done

run() {
  if [[ $DRY -eq 1 ]]; then
    printf '[dry-run] gh %s\n' "$*"
  else
    gh "$@"
  fi
}

command -v gh >/dev/null || { echo "falta el CLI 'gh' (https://cli.github.com)" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "'gh' no está autenticado: corre 'gh auth login'" >&2; exit 1; }

echo "Repositorio: $OWNER/$REPO   ·   rama protegida: $BRANCH"
[[ $DRY -eq 1 ]] && echo "(dry-run: no se aplica nada)"
echo ""

# --- 1. Ajustes generales del repositorio -----------------------------------------------
# Merge de PR: solo squash, para que `main` tenga un commit por cambio y una historia legible.
# La rama se borra sola al mergear (no se acumulan ramas muertas).
echo "==> Ajustes del repositorio"
run api -X PATCH "repos/$OWNER/$REPO" \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true \
  -F allow_auto_merge=true \
  `# La wiki nativa SÍ se usa: Publishing.md documenta sincronizarla desde docs/wiki/ después` \
  `# de cada tag. Apagarla dejaría esas páginas inalcanzables aunque el contenido siga en el repo.` \
  -F has_wiki=true \
  -F web_commit_signoff_required=false

# --- 2. Seguridad: alertas, secret scanning y push protection ---------------------------
echo "==> Seguridad y análisis"
run api -X PATCH "repos/$OWNER/$REPO" \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_non_provider_patterns][status]=enabled'

# Dependabot: alertas de vulnerabilidades + PRs automáticos de parche de seguridad.
run api -X PUT "repos/$OWNER/$REPO/vulnerability-alerts"
run api -X PUT "repos/$OWNER/$REPO/automated-security-fixes"

# Private vulnerability reporting: el canal que anuncia SECURITY.md.
run api -X PUT "repos/$OWNER/$REPO/private-vulnerability-reporting"

# --- 3. Regla de protección de `main` ----------------------------------------------------
echo "==> Ruleset sobre '$BRANCH'"
checks_json=$(printf '%s\n' "${REQUIRED_CHECKS[@]}" \
  | python3 -c 'import json,sys; print(json.dumps([{"context": c.strip()} for c in sys.stdin if c.strip()]))')
bypass_json="[]"
[[ $ADMIN_BYPASS -eq 1 ]] && bypass_json='[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}]'

ruleset=$(python3 - "$BRANCH" "$REVIEWS" "$checks_json" "$bypass_json" <<'PY'
import json, sys
branch, reviews, checks, bypass = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3]), json.loads(sys.argv[4])
print(json.dumps({
    "name": "protect-" + branch,
    "target": "branch",
    "enforcement": "active",
    "bypass_actors": bypass,
    # `~DEFAULT_BRANCH` en vez de la rama literal: la regla sigue a la rama por defecto y no se
    # queda protegiendo un nombre viejo si algún día se renombra.
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": [
        {"type": "deletion"},          # nadie borra main
        {"type": "non_fast_forward"},  # nadie reescribe la historia publicada
        {"type": "pull_request", "parameters": {
            "required_approving_review_count": reviews,
            "dismiss_stale_reviews_on_push": True,
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "required_review_thread_resolution": True,  # no se mergea con hilos abiertos
            "allowed_merge_methods": ["squash"],
        }},
        {"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": True,  # la rama debe estar al día con main
            "do_not_enforce_on_create": False,
            "required_status_checks": checks,
        }},
        # Que el job de CodeQL termine en verde no basta: puede acabar bien y haber encontrado
        # una alerta. Esta regla mira las alertas, no el resultado del job.
        {"type": "code_scanning", "parameters": {"code_scanning_tools": [
            {"tool": "CodeQL",
             "security_alerts_threshold": "high_or_higher",
             "alerts_threshold": "errors"},
        ]}},
    ],
}))
PY
)

existing=$(gh api "repos/$OWNER/$REPO/rulesets" --jq ".[] | select(.name==\"protect-$BRANCH\") | .id" 2>/dev/null || true)
if [[ -n "$existing" ]]; then
  echo "    (actualizando ruleset existente id=$existing)"
  if [[ $DRY -eq 1 ]]; then
    printf '[dry-run] gh api -X PUT repos/%s/%s/rulesets/%s --input -\n%s\n' "$OWNER" "$REPO" "$existing" "$ruleset"
  else
    printf '%s' "$ruleset" | gh api -X PUT "repos/$OWNER/$REPO/rulesets/$existing" --input -
  fi
else
  if [[ $DRY -eq 1 ]]; then
    printf '[dry-run] gh api -X POST repos/%s/%s/rulesets --input -\n%s\n' "$OWNER" "$REPO" "$ruleset"
  else
    printf '%s' "$ruleset" | gh api -X POST "repos/$OWNER/$REPO/rulesets" --input -
  fi
fi

echo ""
echo "Listo."
echo ""
echo "Queda por hacer a mano (no hay API):"
echo "  · Environment 'pypi': marca 'Required reviewers' o restringe a tags v* para que un"
echo "    push accidental de tag no publique solo (Settings > Environments > pypi)."
echo "  · Revisa Settings > Actions > 'Workflow permissions' = read-only y desmarca"
echo "    'Allow GitHub Actions to create and approve pull requests'."
