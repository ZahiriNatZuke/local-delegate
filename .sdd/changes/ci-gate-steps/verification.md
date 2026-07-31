# Verification: Un gate que mire los steps para que el job fantasma no bloquee un merge

## Environment

- Rama `ci/gate-por-steps`, sobre `main` en `537e612`.
- Windows 11, Python 3.11 (`uv`), ruff y pytest del proyecto, `gh` 2.x.
- **Ojo operativo:** el `bash` que resuelve desde PowerShell en esta máquina es **WSL**, y ahí
  `setup_repo_security.sh` no encuentra `gh` (existe como `gh.exe`). Hay que correrlo con **Git
  Bash**.

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | el job existe y lo declara `ci.yml` sin `needs` | **OK** | `test_el_gate_esta_declarado_en_ci_yml` |
| REQ-002 | los siete casos del veredicto | **OK** | 10 tests de `veredicto_de_job`, incluido el orden pasos-malos-antes-que-fantasma |
| REQ-003 | lista explícita, el gate no se espera a sí mismo | **OK** | `test_el_gate_no_se_espera_a_si_mismo` |
| REQ-004 | lista vs `ci.yml` por **conjuntos iguales** | **OK** | `test_los_jobs_esperados_son_exactamente_los_de_ci_yml` |
| REQ-005 | job ausente → plazo agotado → salida ≠ 0 | **OK** | `test_un_job_que_nunca_aparece_agota_el_plazo_y_suspende` |
| REQ-006 | API ilegible → salida ≠ 0 | **OK** | `test_si_la_api_no_se_puede_leer_el_gate_suspende` |
| REQ-007 | la salida nombra los fantasmas | **OK** | `test_el_fantasma_sale_en_verde_y_queda_nombrado` |
| REQ-008 | ruleset | **PENDIENTE**, es post-merge por diseño (T7) | ver abajo |
| REQ-009 | `setup_repo_security.sh` lleva la lista nueva | **OK** | `--dry-run`, JSON del ruleset con `ci-gate` y sin `test (windows-latest)` |
| REQ-010 | wiki | **OK** | `docs/wiki/Repo-hardening.md` |

## Los tests, verificados al revés

Regla del repo: un test que no falla con el bug puesto no prueba nada. Se metieron **los dos falsos
verdes** que el diseño dice evitar, y los dos fueron detectados:

1. **Criterio del fantasma relajado** a «todos los pasos en success», sin exigir `Complete job`:
   `test_un_job_a_medias_no_se_da_por_bueno` **falla** — `assert 'bien' == 'esperar'`. Ese es
   exactamente el falso verde: aprobar un job que va por la mitad.
2. **Orden invertido**, mirando el fantasma antes que los pasos malos:
   `test_un_paso_fallido_manda_sobre_el_complete_job` **falla** — `assert 'bien' == 'mal'`. O sea,
   un job con un test roto habría pasado el gate.

Los dos bugs se revirtieron y la suite volvió a verde.

## La red de seguridad del orden, comprobada por ejecución

`./scripts/setup_repo_security.sh --dry-run` **se niega** hoy:

```
ERROR: nadie reporta estos checks, y exigirlos bloquearía todos los PR:
  · ci-gate
```

Es el comportamiento buscado y la prueba de que el orden del plan (mergear primero, exigir después)
no era una precaución teórica.

## Quality checks

- [x] `uv run pytest -q` → **503 passed, 1 skipped** (eran 482 + 21 nuevos).
- [x] `uv run ruff check .` → All checks passed.
- [x] `uv run ruff format --check .` → 57 files already formatted.
- [x] `extract_dashboard_js.py` + `node --check` → OK.
- [x] Secretos: el cambio no añade ninguno; `gitleaks` corre en `pre-commit` y en el CI.
- [x] Sin cambios ajenos al alcance.

## La verificación en vivo, hecha (run 30640065930, PR #90)

Las dos incógnitas del research se cierran con datos, no con suposiciones:

**(a) ¿Aparecen todos los jobs desde el arranque?** **Sí.** `total_count: 7` en la primera consulta,
con el run recién empezado: los seis esperados más el gate. Aun así la lista sigue siendo explícita,
porque el diseño no debe depender de esto.

**(b) ¿Muestra la API los steps ya concluidos de un job `in_progress`?** **Sí, y el dato es mejor de
lo que se esperaba** — valida el criterio del fantasma directamente:

```
lint                  in_progress  11 steps  último: Post Run actions/checkout@v7
test (ubuntu-latest)  in_progress   7 steps  último: Post Run actions/checkout@v7
test (windows-latest) in_progress   7 steps  último: Post Run actions/checkout@v7
secrets               completed     5 steps  último: Complete job
install-smoke         completed    10 steps  último: Complete job
```

O sea: **mientras un job va por la mitad, los steps van apareciendo conforme se ejecutan y el último
listado NO es `Complete job`**. Solo lo es cuando el runner llegó al final. Esa es exactamente la
diferencia entre un job a medias —que el gate espera— y un fantasma —que aprueba—, y ahora está
medida, no supuesta.

### El gate en su estreno

Run `30640065930`, job `ci-gate`: **success**, tras esperar ~75 s (14:47:05 → 14:48:20).

```
Vigilando el run 30640065930 de ZahiriNatZuke/local-delegate; jobs esperados: lint,
test (ubuntu-latest), test (windows-latest), test (macos-latest), secrets, install-smoke
Todos los jobs esperados terminaron sus pasos:
  [OK   ] lint: conclusion=success
  [OK   ] test (ubuntu-latest): conclusion=success
  [OK   ] test (windows-latest): conclusion=success
  [OK   ] test (macos-latest): conclusion=success
  [OK   ] secrets: conclusion=success
  [OK   ] install-smoke: conclusion=success
```

Los seis jobs del run terminaron en `success`, así que **este run no ejerció la vía del fantasma**:
lo que queda probado en vivo es el camino normal y la espera. La vía del fantasma está cubierta por
los tests, y su premisa —los steps de un job abierto son visibles y su último no es `Complete job`
hasta el final— quedó medida arriba.

**REQ-008** sigue pendiente: es post-merge por diseño.

## Deviations and residual risk

- **El plan review se hizo sin subagente**, por indicación expresa del usuario en esta sesión. Se
  documentó en `plan.md` con tres hallazgos bloqueantes corregidos.
- **Riesgo residual asumido:** si el gate mismo cayera en el fallo de GitHub, el remedio vuelve a ser
  `cancel` + `rerun`. No se empeora nada respecto a hoy.
- **`install-smoke` pasa a bloquear de hecho.** Decisión explícita del usuario, no efecto colateral;
  documentada en la wiki y el CHANGELOG.
