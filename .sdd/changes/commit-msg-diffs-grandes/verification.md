# Verification: local_commit_msg deja de truncar diffs grandes

## Environment

- Revisión: rama `fix/commit-msg-diffs-grandes` sobre `main` (`e7deb0d`).
- Backend real: `http://127.0.0.1:9292/v1`, rol `code` = `qwen25-coder-14b`, contexto 8 192 tokens.
- `uv run pytest` / `uv run ruff` del propio repo.
- Diffs de referencia (generados, no versionados):
  - **grande**: `git diff 6a7959e HEAD` — 164 585 chars, 44 archivos, seis PRs mezclados.
  - **coherente**: `git diff main` de esta rama — 30 358 chars, 4 archivos, un solo cambio.

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | El diff entra entero, sin descartar nada | ✅ | Backend real: 44 archivos y 164 585 chars procesados, `chunks: 17`, sin aviso de truncado. Con mock, `chars_in == len(diff)` y `truncated_in` falso |
| REQ-002 | Los trozos cortan en frontera de archivo | ✅ | 12 de 13 trozos empiezan en `diff --git`; el 13.º es la segunda mitad de `uv.lock`, que solo ya excede el presupuesto (escenario previsto). Invariante `"".join(trozos) == diff` |
| REQ-003 | El reduce recibe el inventario completo | ✅ | El prompt del reduce contiene los 44 archivos y sus totales; contrastado contra `git diff --numstat`: **0 discrepancias en 44 archivos** |
| REQ-004 | El mensaje conserva el formato y sirve | ✅ con matices | Caso coherente: `feat(server): add diff processing functions and context handling`. Ver «Deviations» para el tipo y el cuerpo |
| REQ-005 | El diff pequeño no cambia de camino | ✅ | 1 sola llamada, sin nota de alcance, `chunks` ausente o 1 |
| REQ-006 | N llamadas → un evento con `chunks: N` | ✅ | `evento["chunks"] == len(seen)`, un solo evento en el log |
| REQ-007 | Se sabe sobre cuánto se redactó | ✅ | `(alcance: 44 archivos, 164,585 chars leídos enteros)` |

### Reproducción del defecto y su corrección, medidas

| Momento | Mensaje para el diff grande |
| --- | --- |
| Código de hoy (trunca a 20 027 de 164 585) | `chore: update GitHub Actions pages artifact version` |
| Control positivo (solo el `--stat`, 2 987 chars) | `feat: agregar cambios y pruebas para aislar entorno en tests y codeql alertas abiertas` |
| Con el cambio | `chore: actualizar versiones y agregar documentación SDD` |

| Momento | Mensaje para el diff coherente |
| --- | --- |
| Tareas 1-6 | `feat(server.py): add return statement for resultado` |
| Tras arreglar (a) y (b) del map | `feat(tests): agregar pruebas para procesamiento y manejo de diffs` |
| Con la tarea 7 completa | `feat(server): add diff processing functions and context handling` |

### El desborde de contexto, encontrado por la medida real

El presupuesto de troceado está en chars y el límite del modelo en tokens:

| Contenido | Densidad medida |
| --- | --- |
| Prosa de `.sdd/*.md` | 3,12 chars/token |
| `uv.lock` (hashes y URLs de PyPI) | 1,57 chars/token |

Once trozos pasaron y el doceavo mandó 15 750 chars = 10 193 tokens contra 8 192 de contexto
(400 `exceed_context_size_error`). Con el reintento: llamada 16 en 400, 17 en 200, resultado
completo. Estaba latente en `local_summarize` y `local_lint_summary` desde su propia migración.

### Diagnóstico de la calidad, por espía sobre `_run_chat`

La hipótesis inicial —«el reduce copia la estructura del map»— **era falsa**. Las cuatro llamadas
reales mostraron que el reduce hacía un trabajo fiel con material malo:

| Llamada | Qué devolvió |
| --- | --- |
| MAP 1 (`server.py`, el cambio principal) | `- ruta: qué cambió y para qué` — la plantilla del prompt, copiada literal |
| MAP 2 (continuación de `server.py`) | `- ruta: archivo.py …` — ruta inventada: la pieza no lleva cabecera |
| MAP 3 (los de tests) | correcto y detallado |
| REDUCE | `feat(tests): …` — fiel: 3 de 5 notas eran de tests |

## Quality checks

- [x] Tests del proyecto: **746 pasan, 2 skipped** (`uv run pytest`). Eran 725 antes del cambio.
- [x] Lint y formato: `uv run ruff check src/ tests/` y `ruff format --check` limpios.
- [x] Control positivo de **todos** los tests nuevos, mirando qué assert dispara:
  - Los 5 de comportamiento de `commit_msg` fallan sin el cambio por su propio assert
    (`assert 1 > 1` con `[...contenido truncado...]` en el payload, la marca del último archivo
    ausente, `'30 en total'` ausente, el aviso viejo de truncado, y el diff vacío devolviendo
    `RESUMEN`).
  - Los del reintento, con un mutante que anula `_es_desborde_de_contexto`.
  - Los del map, con un mutante que revierte los prompts a su versión anterior.
- [x] Dos tests corregidos por no medir lo que decían: el de desborde irrecuperable pasaba igual
      sin reintento (ahora exige más de una llamada y de tamaños distintos), y el del prompt del
      map buscaba una ruta que ya estaba dentro del propio diff (ahora mira solo el encabezado).
- [x] Sin secretos ni datos personales: los diffs de referencia se generan con `git diff` del
      propio repo y no se versionan. El cambio no toca autenticación, red ni rutas.
- [x] Sin cambios ajenos al alcance: `server.py`, `test_chunking.py`, `test_core.py`,
      `test_map_reduce.py` y el CHANGELOG.

## Deviations and residual risk

- **El tipo del commit no siempre acierta.** El caso coherente sale como `feat` cuando un humano
  pondría `fix`. La tool ya avisa en su propia descripción de que hay que revisar el mensaje antes
  de usarlo; esto no lo cambia.
- **El cuerpo con viñetas aparece de forma irregular.** El formato lo declara opcional y el titular
  —lo que de verdad se usa— ya es correcto.
- **Un rango de commits incoherente da mensajes genéricos**, y eso es inherente: seis PRs mezclados
  no tienen un buen mensaje de commit posible. Por eso la calidad se juzgó con el caso coherente,
  que es la forma del caso real reportado.
- **El reintento por desborde cubre el map, no el reduce.** El reduce trabaja sobre prosa generada
  por el propio modelo, de densidad predecible (~3 chars/token), y ya tiene el bucle de
  reagrupación por niveles. Queda anotado como límite conocido, no como cubierto.
- **Coste:** un diff grande pasa de 1 llamada a N+1 (17 para 164 585 chars, 122 s). Es el precio de
  leerlo entero y el mismo que ya pagan `local_summarize` y `local_lint_summary`.
