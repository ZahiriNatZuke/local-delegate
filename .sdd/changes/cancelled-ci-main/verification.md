# Verification: El cancelled del CI en main tiene causa conocida y firma reconocible

## Environment

- Base `9c6cb47` (`main`); rama `fix/cancelled-ci-main`.
- La evidencia principal sale de la **API de Actions del repo real**, no de un doble.

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | Los tres sitios corregidos | ✅ | `ci.yml`, `ci_gate.py`, `Repo-hardening.md` |
| REQ-002 | El paso declara su límite | ✅ | `timeout-minutes: 5` (job en 8) |
| REQ-003 | Mutante: límite del job a 12 | ✅ | cae `test_el_limite_del_job_*` |
| REQ-004 | Mutante: paso sin límite / con 9 | ✅ | cae `test_el_paso_de_tests_*` en los dos |
| REQ-005 | Tabla de lectura | ✅ | clasifica los tres casos observados |

### La medición, que es lo que sostiene todo el change

`gh api repos/…/actions/runs/{id}/jobs` sobre los tres `cancelled` de `main`:

| Run | Estado interno al morir | Duración del job |
| --- | --- | --- |
| `30652987094` | `Tests (pytest)` **in_progress** | 17:53:57 → 18:06:57 = **13:00** |
| `30654961990` | **todos** los pasos `success`, `Complete job` incluido | 18:23:33 → 18:36:33 = **13:00** |
| `30660878897` | `Tests (pytest)` **in_progress** | 19:54:43 → 20:07:43 = **13:00** |

Y lo que descarta lo demás: `cancel-in-progress` es **false en `main`** (`ci.yml:18`), así que no
es la concurrencia; y trece minutos clavados al segundo en tres runs no lo hace una persona.

### Verificación al revés: 4 mutantes, 3 cazados

| Mutante | Quién lo caza |
| --- | --- |
| límite del job a 12 (el texto se queda viejo) | `test_el_limite_del_job_de_tests_es_el_que_explica_la_firma_de_13_minutos` |
| el paso pierde su límite | `test_el_paso_de_tests_tiene_su_propio_limite_*` |
| el límite del paso sube a 9 (≥ el del job) | `test_el_paso_de_tests_tiene_su_propio_limite_*` |
| borrar «13:00 EXACTOS» del comentario | **no cae** |

**El cuarto no cae, y el motivo es del mutante, no del test:** el comentario menciona la firma en
dos sitios y el mutante solo tocó uno, así que la cadena `13:00` seguía presente. El escenario que
importa —cambiar el límite y dejar el texto viejo— sí cae, que es el primero.

## Quality checks

- [x] `uv run pytest -q` → suite completa en verde (`test_ci_gate.py`: 23 passed).
- [x] `uv run ruff check .` / `ruff format --check .` → limpios.
- [x] Sin secretos.
- [x] Sin cambios ajenos.

## Deviations and residual risk

- **Que la gracia sean 5 minutos es inferido, no medido directamente.** Lo medido es el total de
  13:00 con el límite en 8. Si GitHub la cambiara, la firma dejaría de ser 13 y **el test no lo
  detectaría**: mide contra el número declarado en el repo, no contra la realidad de GitHub.
- **No se puede reproducir el cuelgue a demanda**, así que el efecto del límite del paso no está
  ejercitado. La evidencia es la de los tres runs ya ocurridos.
- **No se investiga por qué pytest se cuelga en Windows:** el runner no subió log en ninguno de los
  tres casos (`BlobNotFound`). Cualquier causa sería inventada, y este repo ya pagó caro eso.
