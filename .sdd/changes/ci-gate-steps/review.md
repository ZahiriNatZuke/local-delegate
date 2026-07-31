# Result review: Un gate que mire los steps para que el job fantasma no bloquee un merge

## Verdict

`conforms`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 job `ci-gate` sin `needs` | sí | sí | corrió en paralelo en los runs de los PRs #90 y #91 |
| REQ-002 veredicto por steps, en ese orden | sí | sí | 10 tests + los dos falsos verdes provocados a propósito |
| REQ-003 lista explícita de seis jobs | sí | sí | `install-smoke` incluido por decisión del usuario |
| REQ-004 lista atada a `ci.yml` por conjuntos iguales | sí | sí | el parser falla ruidosamente ante una matriz que no entiende |
| REQ-005 plazo agotado → suspende | sí | sí | test con job ausente |
| REQ-006 API ilegible → suspende | sí | sí | test con la API lanzando |
| REQ-007 salida legible con fantasmas nombrados | sí | sí | log del run 30640065930 |
| REQ-008 ruleset | sí | sí | releído por API: `ci-gate` dentro, `test (windows-latest)` fuera |
| REQ-009 `setup_repo_security.sh` | sí | sí | `--dry-run` y aplicación real |
| REQ-010 wiki | sí | sí | mecanismo, límites y lo que deja de estar cubierto |

## Findings

- **Ninguno bloqueante.**
- **Lo que este trabajo NO probó en vivo, y conviene no confundir:** el run del PR #90 salió con los
  seis jobs en `success`, así que **la vía del fantasma no se ejerció contra GitHub real**. Lo
  probado en vivo es el camino normal, la espera y el veredicto; la vía del fantasma está cubierta
  por tests y su premisa quedó **medida** (un job `in_progress` muestra sus steps, y su último no es
  `Complete job` hasta el final). La prueba definitiva llegará la próxima vez que GitHub cuelgue un
  job — y si no vuelve a colgarse, mejor.
- **Riesgo residual conocido:** si el propio gate cayera en el fallo, el remedio vuelve a ser
  `cancel` + `rerun`. No se empeora nada respecto a antes.
- **Cambio de contrato asumido:** `install-smoke` pasa a bloquear un merge. Decisión explícita del
  usuario, documentada en el CHANGELOG y en la wiki, con su pero (depende de PyPI en vivo).

## Required follow-up

- Nada bloqueante para cerrar.
- **Para la próxima vez que aparezca un job fantasma:** comprobar que `ci-gate` lo nombra en su
  salida y que el merge no se bloquea. Es la confirmación que falta y solo puede darla el fallo real.
