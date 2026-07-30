# Revisión del resultado

## Veredicto

`conforms`

## Comparación con la especificación

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 `install_claude_code_hooks_macos.sh` no existe | sí | sí | Borrado con `git rm`; sin sustituto, porque `local-delegate install` ya cubre la función |
| REQ-002 el sdist no contiene `scripts/` | sí | sí | 124 → 109 entradas, cero bajo `scripts/`, **nada añadido** |
| REQ-003 el wheel no cambia | sí | sí | 30 = 30 entradas idénticas, comparadas contra un `worktree` de `main`. No se dio por supuesto |
| REQ-004 los tests se saltan, no fallan | sí | sí | Probado en los dos sentidos (casos A y B de `verification.md`) |
| REQ-005 entrada en `Unreleased` | sí | sí | Sección `### Security`, CRLF preservado |

Mergeado en `main` como `372e4ad` (PR #69), con los doce checks en verde.

## Hallazgos

1. **El escenario de aceptación decía 109 y midió 109.** La primera medición dio 110 por un fichero
   espurio (`--out`) creado al invocar mal `extract_dashboard_js.py`. Se limpió y se remidió. Deja
   una lección que vale más que el número: **el sdist recoge lo que haya en el árbol**, así que
   cualquier residuo de trabajo se publica.
2. **La revisión adversarial del plan sirvió para algo**, que no siempre pasa: cazó una afirmación
   falsa en la investigación (H1 — el script no estaba roto, seguía funcionando desde el tag) y un
   fallo de diseño en el `skip` (H2) que habría convertido un borrado accidental de
   `check_vendor.py` o `bump_version.py` en un CI verde.
3. **Alcance respetado.** El blob de Chart.js, las nueve alertas de dependencias y la poda de
   `tests/`, `docs/` o `.github/` del sdist se declararon no objetivos y no se tocaron.

## Seguimiento requerido

Nada bloquea el cierre. Tres cosas quedan anotadas para el backlog, ninguna de este alcance:

- **Hooks duplicados** en máquinas donde se ejecutó el `.sh`: escribía en `~/.claude/hooks/*.py`
  mientras el CLI usa `~/.claude/hooks/local-delegate/`. Quien lo corrió los tiene por duplicado y
  registrados dos veces en `settings.json`. Candidato a comprobación del `doctor`.
- **`docs/wiki/Remote-backend.md:74-75`** sigue recomendando `./scripts/update_to_latest.sh`, que el
  PR #66 declaró sustituido por `local-delegate update`. Desfase anterior a este cambio, aún sin
  publicar.
- **La captura del README** enseña `v0.15.0` y el icono anterior a la marca única del PR #67. Se
  regenera después del bump de versión, según `Publishing.md:89`.
