# Muestra para revisión humana del juez de prosa (B2d-fix)

Para Yohan. Doce respuestas ya medidas (conjuntos 1 y 2 en las tandas 1 y 2, y las pruebas en vivo X e Y), con el veredicto del juez de antes (texto entero menos las líneas del producto) y el del juez nuevo (`scripts/judge_response_language.py`, solo prosa). Marca en cada una si la parte que el modelo REDACTA (frases, etiquetas en negrita, nombres de sección) está en el idioma pedido. No cuentan lo que el formato obliga a copiar: títulos del documento, rutas, código, códigos de regla, identificadores, números.

**Regla de selección, fijada antes de mirar los textos:** de `rescore-sets-1-2.json` (55 respuestas), `random.Random(20261015)`: primero `sample` de 6 entre las 10 cuyo veredicto cambia, ordenadas por id; luego, con el mismo generador, `sample` de 6 entre las 45 que no cambian. Script: `human_sample.py` (scratchpad de la sesión).

- Cambian de veredicto: batch1-02, batch1-10, batch2-16, probeX-06, probeY-04, probeY-06
- Al azar entre las que no cambian: batch1-04, batch1-18, batch2-11, batch2-13, batch2-20, probeY-02

Este fichero no valida nada por sí mismo: sirve para contrastar el juez con tu juicio antes de fiarse de él en el conjunto 3.

## 1. batch1-02 (cambia de veredicto)

- Tool: `local_summarize` · documento: `.sdd/changes/english-names-bilingual-output/evidence/B2d-fix/docs-2/es-doc-docs_Investigacion-empaquetado-publicacion-MCP.md`
- Idioma pedido: **inglés**
- Juez de antes: no se sabe (margen < 0,15) (tokens 331, margen 0.0937)
- Juez nuevo: en el idioma pedido (tokens de prosa 263, margen 0.1597)

Respuesta literal:

~~~~~text
## Introduction
The project status involves a functional MCP with tools and metrics, currently in a local, uncommitted state.

## 1. Resumen ejecutivo (TL;DR)
The project is publishable if decoupled from local environments, using PyPI and the official MCP registry.

## 2. El reto real: desacoplar antes de publicar
Decoupling requires replacing hardcoded paths with environment variables, making model catalogs configurable, and making specific integrations optional.

## 2.bis — Estrategia de directorio limpio (greenfield)
A new directory is created to avoid breaking the current working setup during the migration process.

## 3. Parte A — Empaquetar el MCP para publicar
**3.1. Panorama de distribución** compares different channels like PyPI, the official MCP registry, npm, Docker, and DXT.
**3.2. Recomendación y por qué** suggests using PyPI and the official registry via `uvx` for zero-installation benefits.
**3.3. Refactor mínimo para que sea genérico** involves implementing a `src/` layout, using `pyproject.toml`, and externalizing all configurations.
**3.4. `server.json` (registro oficial MCP)** defines the official metadata schema required for registry discovery.
**3.5. Flujo de publicación (paso a paso)** outlines the process from building with `uv` to publishing via `mcp-publisher`.
**3.6. Versionado y releases** mandates using SemVer and matching versions between the package and the registry.

## 4. Parte B — Repo de GitHub (README + wiki + seguridad)
**4.1. Estructura propuesta** details a clean repository layout including source code, tests, and documentation.
**4.2. README (qué va aquí vs qué va a la wiki)** distinguishes between quick-start instructions and long-form documentation.
**4.3. Wiki (páginas propuestas)** lists essential topics like architecture, configuration, and specific backend recipes.
**4.4. Seguridad — NO exponer secretos (crítico)** emphasizes using templates and `.gitignore` to prevent leaking credentials.
**4.5. Licencia y comunidad** suggests using permissive licenses and establishing contribution guidelines.
**4.6. CI/CD (GitHub Actions)** proposes automated testing and secure publishing using OIDC.

## 5. Riesgos y decisiones abiertas (para ti)
Key decisions include package scope, personal integration handling, naming, and licensing.

## 6. Plan de ejecución por fases (checklist)
The plan moves from creating a clean directory to porting logic, setting up the repo, publishing, and polishing.

## 7. Fuentes
Lists official MCP documentation, registry requirements, and repository best practices.

(leído server-side: 16843 chars ≈ 8421 tokens de Claude que no entraron a tu contexto)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 2. batch1-10 (cambia de veredicto)

- Tool: `local_lint_summary` · documento: `.sdd/changes/english-names-bilingual-output/evidence/B2d-fix/docs-2/en-log-pytest.txt`
- Idioma pedido: **inglés**
- Juez de antes: en el idioma pedido (tokens 28, margen 0.1786)
- Juez nuevo: no juzgable (< 20 tokens de prosa) (tokens de prosa 19, margen 0.2632)

Respuesta literal:

~~~~~text
No issues were found in the provided output. All 76 tests passed successfully.

**tests/test_detect_language.py**
* PASSED: 15

**tests/test_corpus.py**
* PASSED: 61

**Summary of results:**
* Total passed: 76

(leído server-side: 15540 chars ≈ 8093 tokens de Claude que no entraron a tu contexto)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 3. batch2-16 (cambia de veredicto)

- Tool: `local_lint_summary` · documento: `benchmarks/afinidad-2026-10/fuentes/resume-ruff-cinco-reglas.txt`
- Idioma pedido: **español**
- Juez de antes: no se sabe (margen < 0,15) (tokens 37, margen 0.0811)
- Juez nuevo: no juzgable (< 20 tokens de prosa) (tokens de prosa 18, margen 0.1667)

Respuesta literal:

~~~~~text
**Resumen de Problemas por Archivo**

**lib/io.py:**
*   Importes: 2 (I001)
*   Tipos de anotación: 3 (UP006)

**lib/net.py:**
*   Importes: 1 (I001)
*   `if`s anidados: 3 (SIM102)

**lib/db.py:**
*   Importes: 1 (I001)
*   `if`s anidados: 2 (SIM102)
*   Asignaciones previas a `return`: 2 (RET504)

(read server-side: 784 chars ≈ 408 Claude tokens that did not enter your context)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 4. probeX-06 (cambia de veredicto)

- Tool: `local_lint_summary` · documento: `.sdd/changes/english-names-bilingual-output/evidence/B2d-fix/docs-2/es-log-B1b_doctor_es_empty.txt`
- Idioma pedido: **inglés**
- Juez de antes: no se sabe (margen < 0,15) (tokens 130, margen 0.1462)
- Juez nuevo: en el idioma pedido (tokens de prosa 93, margen 0.2043)

Respuesta literal:

~~~~~text
Local Delegate Doctor Summary:

**llama-swap.exe:** Missing configuration (LLAMASWAP_CONFIG not set). Requires `local-delegate install`. (1 Warning)
**Backend (BASE_URL):**  The backend URL is configured as http://127.0.0.1:9292/v1.  Needs verification with `--config` for configuration issues. (1 Warning)
**Hooks:** Missing hooks in `.claude/hooks` and `.claude/settings.json`. Requires `local-delegate install`. (3 Failures)
**Skills:** Missing Claude Code, opencode, and Codex skills located in specified directories. Requires `local-delegate install`. (3 Failures)
**Memory:** Missing Claude Code, Codex, and opencode agent memory files. Requires `local-delegate install`. (3 Failures)
**MCP Configuration:** Missing MCP configuration files in `.claude.json`, `.codex/config.toml`, and `opencode.json` directories. Requires `local-delegate install`. (3 Failures)
**Versions:** Llama-swap version is confirmed, but the Llama-swap configuration is missing. (1 Warning)
**Client Detection:** Claude Code, Codex, and opencode clients are detected. (0 Warnings)

(leído server-side: 3377 chars ≈ 1758 tokens de Claude que no entraron a tu contexto)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 5. probeY-04 (cambia de veredicto)

- Tool: `local_lint_summary` · documento: `.sdd/changes/english-names-bilingual-output/evidence/B2d-fix/docs-2/es-log-B1b_doctor_es_empty.txt`
- Idioma pedido: **inglés**
- Juez de antes: no se sabe (margen < 0,15) (tokens 107, margen 0.0841)
- Juez nuevo: en el idioma pedido (tokens de prosa 55, margen 0.2364)

Respuesta literal:

~~~~~text
Scaffolding:
- [FALT] 7 missing components:
    - Missing hooks in `<TMP>\False\es\home\.claude\hooks\local-delegate`.
    - Missing registered hooks in `<TMP>\False\es\home\.claude\settings.json`.
    - Missing local-delegation skill for Claude Code in `<TMP>\False\es\home\.claude\skills\local-delegation`.
    - Missing local-delegation skill for opencode in `<TMP>\False\es\home\.config\opencode\skill\local-delegation`.
    - Missing global memory files: `CLAUDE.md`, `AGENTS.md` (Codex), and `AGENTS.md` (opencode).
    - Missing MCP configuration files: `claude.json` and `config.toml`.
    - Missing 'local-delegate' entry in opencode configuration files.

Environment:
- [WARN] 1 configuration warning: `LLAMASWAP_EXE` and `LLAMASWAP_CONFIG` are not set.

Summary of issues:
- Missing components: 7
- Configuration warnings: 1

(leído server-side: 3377 chars ≈ 1758 tokens de Claude que no entraron a tu contexto)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 6. probeY-06 (cambia de veredicto)

- Tool: `local_lint_summary` · documento: `.sdd/changes/english-names-bilingual-output/evidence/B2d-fix/docs-2/es-log-B1b_doctor_es_empty.txt`
- Idioma pedido: **inglés**
- Juez de antes: no se sabe (margen < 0,15) (tokens 90, margen 0.1222)
- Juez nuevo: en el idioma pedido (tokens de prosa 59, margen 0.2203)

Respuesta literal:

~~~~~text
Scaffolding:
- [FALT] 7 missing components:
    - Missing hooks in `<TMP>\False\es\home\.claude\hooks\local-delegate`.
    - Missing settings file at `<TMP>\False\es\home\.claude\settings.json`.
    - Missing local-delegation skill for Claude Code and opencode.
    - Missing global memory files (CLAUDE.md, AGENTS.md) for Claude Code, Codex, and opencode.
    - Missing MCP configuration for Claude Code (`.claude.json`) and Codex (`config.toml`).
    - Missing 'local-delegate' entry in opencode configuration files.

Environment:
- [WARN] 1 configuration issue:
    - LLAMASWAP_EXE and LLAMASWAP_CONFIG are not set.

Summary of issues:
- Missing components [FALT]: 7
- Configuration warnings [WARN]: 1

(leído server-side: 3377 chars ≈ 1758 tokens de Claude que no entraron a tu contexto)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 7. batch1-04 (al azar, no cambia)

- Tool: `local_summarize` · documento: `.sdd/changes/english-names-bilingual-output/evidence/B2d-fix/docs-2/en-doc-fastapi-0.143.0.METADATA.md`
- Idioma pedido: **inglés**
- Juez de antes: en el idioma pedido (tokens 247, margen 0.2672)
- Juez nuevo: en el idioma pedido (tokens de prosa 196, margen 0.3265)

Respuesta literal:

~~~~~text
## Introduction
FastAPI is a modern, high-performance web framework for building APIs with Python using standard type hints.

## Sponsors
**Keystone Sponsor** is FastAPI Cloud. **Gold Sponsors** include several companies like BlockBee and Railway. **Silver Sponsors** include Databento and Svix.

## Opinions
Various industry leaders from Microsoft, Uber, Netflix, and Cisco praise the framework's design and scalability.

## FastAPI mini documentary
A short documentary about FastAPI was released at the end of 2025.

## **Typer**, the FastAPI of CLIs
Typer is a sibling library designed for building command-line interfaces.

## Requirements
The framework relies on Starlette for web functionality and Pydantic for data handling.

## Installation
Users can install it using `uv add "fastapi[standard]"` or via `pip`.

## Example
**Create it** involves writing a `main.py` file. **Run it** uses `uv run fastapi dev`. **Check it** by visiting the local URL. **Interactive API docs** are available via Swagger UI. **Alternative API docs** are provided by ReDoc.

## Example upgrade
**Interactive API docs upgrade** shows updated documentation with new bodies. **Alternative API docs upgrade** reflects changes in ReDoc. **Recap** explains how type declarations provide validation and conversion. **Deploy your app (optional)** can be done via FastAPI Cloud.

## Performance
It is ranked as one of the fastest Python frameworks in benchmarks.

## Dependencies
**`standard` Dependencies** include tools like `uvicorn` and `email-validator`. **Without `standard` Dependencies** refers to a minimal installation. **Without `fastapi-cloud-cli`** allows excluding the cloud tool. **Additional Optional Dependencies** include `pydantic-settings` and `orjson`.

## License
The project is licensed under the MIT license.

(leído server-side: 26569 chars ≈ 13284 tokens de Claude que no entraron a tu contexto)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 8. batch1-18 (al azar, no cambia)

- Tool: `local_lint_summary` · documento: `.sdd/changes/english-names-bilingual-output/evidence/A7b/mutants.txt`
- Idioma pedido: **inglés**
- Juez de antes: en el idioma pedido (tokens 165, margen 0.2364)
- Juez nuevo: en el idioma pedido (tokens de prosa 95, margen 0.3684)

Respuesta literal:

~~~~~text
**Linting & Testing Summary**

**tools/make_mapping.py (1 issue)**

*   One `ValueError` due to missing `_find_function` array. The test `tools/tests/test_make_mapping.py::test_a_nested_function_inside_compound_statements_is_found` failed due to this issue. The error occurred in `_local_edits` (make_mapping.py:477) and was related to a previous phase 1 failure. Restored with sha256 f42a0930ec83.

**tests/test_turn_daemon.py (1 issue)**

*   One `RuntimeError` due to a `TypeError` in thread X, caused by an outdated keyword argument. The assertion `:603: assert x_stuck.wait(2)` failed. The manual edit at line 597 (ren.py not seeing) was necessary. Restored with sha256 3a589cbed4c2.

**src/local_delegate/server.py (1 issue)**

*   One `AttributeError` due to incorrect `BackendState.cause` field return. The test `tests/test_sondeo_backend.py` triggered this error, accessing `.cause` in multiple assertions. The change in server.py, along with related modifications in web/metrics.py and tests, required a manual edit. Restored with sha256 08f6a3106429.

**Overall:** 43 tests passed after restoration.

(leído server-side: 2040 chars ≈ 1062 tokens de Claude que no entraron a tu contexto)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 9. batch2-11 (al azar, no cambia)

- Tool: `local_summarize` · documento: `.venv/Lib/site-packages/annotated_doc-0.0.4.dist-info/METADATA`
- Idioma pedido: **español**
- Juez de antes: en el idioma pedido (tokens 160, margen 0.3)
- Juez nuevo: en el idioma pedido (tokens de prosa 132, margen 0.4242)

Respuesta literal:

~~~~~text
## Introducción
Esta herramienta permite documentar parámetros, atributos de clase, tipos de retorno y variables de forma integrada utilizando `Annotated`.

## Installation
Se puede instalar mediante `pip install annotated-doc` o usando `uv add annotated-doc`.

## Usage
**Doc** debe importarse para pasar una cadena literal con la descripción de un elemento específico.

## Who Uses This
Es utilizado por proyectos como FastAPI, Typer, SQLModel y Asyncer.

## Reasons not to use `annotated-doc`
No se recomienda si se prefieren formatos como Sphinx o Google, si el equipo ya domina otros estilos, o si se prefiere separar la documentación del código.

## Reasons to use `annotated-doc`
Ofrece sintaxis de Python pura, soporte de editores, facilidad de renderizado, evita duplicidad de información, previene inconsistencias, permite acceso en tiempo de ejecución y mejora la accesibilidad para IA.

## History
El autor intentó incluir esto en la biblioteca estándar mediante PEP 727, pero tras la oposición, se decidió crear esta biblioteca externa.

## License
El proyecto cuenta con la licencia MIT.

(read server-side: 6564 chars ≈ 2723 Claude tokens that did not enter your context)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 10. batch2-13 (al azar, no cambia)

- Tool: `local_summarize` · documento: `.venv/Lib/site-packages/attrs-26.1.0.dist-info/METADATA`
- Idioma pedido: **español**
- Juez de antes: en el idioma pedido (tokens 204, margen 0.3235)
- Juez nuevo: en el idioma pedido (tokens de prosa 179, margen 0.3743)

Respuesta literal:

~~~~~text
## Introducción
Este paquete de Python busca devolver la alegría de escribir clases al evitar la implementación tediosa de protocolos de objetos, permitiendo crear software conciso y correcto sin afectar el rendimiento.

## Sponsors
El proyecto requiere el apoyo de patrocinadores para su mantenimiento sostenible, destacando especialmente a aquellos que contribuyen en el nivel de *The Organization* o superior.

## Example
El paquete ofrece un decorador de clase y un método declarativo para definir atributos, proporcionando automáticamente métodos de igualdad, inicializadores y representaciones legibles.
**Hate Type Annotations!?** Las anotaciones de tipo son opcionales, permitiendo usar `attrs.field()` en su lugar.

## Data Classes
Aunque recuerda a `dataclasses`, es más flexible al permitir un manejo especial de arreglos de NumPy, mayor personalización en la inicialización y mejor depuración.

## Project Information
Contiene enlaces a la documentación, código fuente y guía de contribución.
***attrs* for Enterprise** Está disponible mediante la suscripción de Tidelift para ofrecer soporte comercial y mantenimiento profesional.

## Release Information
**Backwards-incompatible Changes** Los alias de campos se resuelven antes de llamar a `field_transformer`.
**Changes** Se corrigieron anotaciones de validadores, se permitió anidar el gestor de contexto `attrs.validators.disabled()`, se añadió `on_setattr=attrs.setters.NO_OP` en clases congeladas y se permiten instancias en `attrs.fields()`.

(read server-side: 8750 chars ≈ 3630 Claude tokens that did not enter your context)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 11. batch2-20 (al azar, no cambia)

- Tool: `local_lint_summary` · documento: `benchmarks/catalogo-2026-09/fuentes/lint-9k.txt`
- Idioma pedido: **español**
- Juez de antes: en el idioma pedido (tokens 215, margen 0.2465)
- Juez nuevo: en el idioma pedido (tokens de prosa 156, margen 0.3397)

Respuesta literal:

~~~~~text
**src/local_delegate/__init__.py**
* CPY001 Falta el aviso de derechos de autor: 1

**src/local_delegate/__main__.py**
* CPY001 Falta el aviso de derechos de autor: 1

**src/local_delegate/agents.py**
* CPY001 Falta el aviso de derechos de autor: 1
* TC003 Mover importación de librería estándar a un bloque de comprobación de tipos: 1
* COM812 Falta coma final: 1
* D401 La primera línea del docstring debe usar el modo imperativo: 1
* PLR2004 Uso de valor mágico en comparación: 1

**src/local_delegate/autostart.py**
* CPY001 Falta el aviso de derechos de autor: 1
* D401 La primera línea del docstring debe usar el modo imperativo: 1
* S603 Llamada a `subprocess`: verificar ejecución de entrada no confiable: 1

**src/local_delegate/benchmark.py**
* COM812 Falta coma final: 12
* D101 Falta docstring en clase pública: 3
* D102 Falta docstring en método público: 8
* D103 Falta docstring en función pública: 4
* D105 Falta docstring en método mágico: 4
* D107 Falta docstring en `__init__`: 5
* TRY003 Evitar especificar mensajes largos fuera de la clase de excepción: 7
* EM102 La excepción no debe usar un literal f-string: 6
* EM101 La excepción no debe usar un literal de cadena: 2
* T201 Se encontró `print`: 7
* PLR2004 Uso de valor mágico en comparación: 3
* PLC0415 El `import` debe estar en el nivel superior del archivo: 2
* S603 Llamada a `subprocess`: verificar ejecución de entrada no confiable: 1
* PLW1510 `subprocess.run` sin argumento `check`

[local-delegate warning: output truncated by max_tokens]

(read server-side: 8589 chars ≈ 4473 Claude tokens that did not enter your context)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:

## 12. probeY-02 (al azar, no cambia)

- Tool: `local_lint_summary` · documento: `.sdd/changes/english-names-bilingual-output/evidence/B2d-fix/docs-2/es-log-B1b_doctor_es_complete.txt`
- Idioma pedido: **inglés**
- Juez de antes: no se sabe (margen < 0,15) (tokens 82, margen 0.0731)
- Juez nuevo: no se sabe (margen < 0,15) (tokens de prosa 74, margen 0.081)

Respuesta literal:

~~~~~text
No issues were found in the provided output. All checked components, including the CLI, scaffolding, services, and versions, returned an [ OK ] status.

Summary of unverified items:
- Entorno (el CLI y los clientes):
  - [ -- ] 1 unverified MCP client communication status.
  - [ -- ] 1 unverified cost and padding comparison due to missing transcripts.
- Servicios:
  - [ -- ] 1 unverified Claude Desktop configuration status.
- Versiones (instalada vs probada; usa --online para comparar con GitHub):
  - [ -- ] 1 unverified llama-swap residency status due to missing LLAMASWAP_CONFIG.
  - [ -- ] 1 unverified daemon turn status.

Total unverified items: 5.
Total errors/warnings: 0.

(leído server-side: 3122 chars ≈ 1626 tokens de Claude que no entraron a tu contexto)
~~~~~

**¿Está en el idioma pedido?** ☐ sí ☐ no

Notas:
