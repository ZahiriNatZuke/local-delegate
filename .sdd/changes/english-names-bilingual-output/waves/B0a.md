# Ola B0a — Base de idioma, catálogo, paridad, fixtures y `test-lang-es`

Primera mitad de B0 (frente B), tras partir la ola el 2026-10-14 (`waves/B0-proposal.md`,
«Decisiones aprobadas»; plan, «#### B0» → «##### B0a»). Rama `sdd/english-names-b0`, sobre
`origin/main` `a5c150e`. Sin commit ni push: los hace la sesión principal.

- **REQ:** 018 (entera), 019 (gramática y aviso como código), 047 (lectura de `language.json`),
  028 (enmienda del 2026-10-14: lectura y validación de `LOCAL_DELEGATE_OUTPUT_LANGUAGE`), 030,
  031 y 043 (fixtures de variable, de directorio de datos y de `locale` de Playwright).
- **Resultado:** suite **2704 passed, 2 skipped** con `LANG=en_US.UTF-8` y **2704 passed,
  2 skipped** con `LANG=es_ES.UTF-8` (antes 2627 tests en `main`); `ruff check` y
  `ruff format --check` limpios; detector de nombres del frente A **0 fuera de la lista y 0 palabras
  sin clasificar**; 25 controles positivos, los 25 disparan el assert esperado.

## 1. Qué se hizo

| Fichero | EOL | Cambio |
| --- | --- | --- |
| `src/local_delegate/resources/hooks/hook_common.py` | LF | `LANGUAGES`, `LANGUAGE_GRAMMAR`, `UNDECLARED_LOCALE_NAMES`, `HOOK_TEXTS` vacío, `LanguageResolution`, `parse_language`, `resolve_language(data_dir, env, platform, ui_lang)` y sus dos piezas privadas `_system_language` y `_windows_ui_language(kernel32=None)` (+113) |
| `src/local_delegate/i18n.py` (nuevo) | LF | `current()` cacheado con `config.LOG_DIR`, `lang`, `reset`, `catalog`, `t`, `t_lang` (traducción ausente → español; clave ausente → la clave), `argparse_gettext`, `argparse_ngettext` (D8; el parche en `cli.py` es de B1) |
| `src/local_delegate/resources/i18n/{es,en}/common.json` (nuevos) | LF | 10 claves: orígenes del idioma (`variable`, `preferencia`, `sistema`, `reserva`), avisos de variable o preferencia no válida o ilegible, y origen y avisos de `LOCAL_DELEGATE_OUTPUT_LANGUAGE`; las usan B1 (`doctor`) y B2b (`local_status`) |
| `src/local_delegate/config.py` | LF | `language_variable()` (solo registro de `LOCAL_DELEGATE_LANG`) y `output_language() -> OutputLanguage(value, problem, raw)`: se lee al llamar; vacía o solo espacios = sin poner; rechaza `Cc`, `Cf`, `Zl` y `Zp` (`control_chars`) y más de 40 caracteres (`too_long`); las dos en el bucle de registro, así que entran en `ENVIRONMENT_VARIABLES` (+39) |
| `tests/conftest.py` | LF | `SUITE_LANGUAGE = "es"` fijada en `env_without_package_variables`; `isolate_runtime_logs` fija `LOCAL_DELEGATE_LOG_DIR=<tmp>` y llama a `i18n.reset()` antes y después; fixtures `browser_locale` (`es-ES`) y `new_page` (los usa B4) |
| `tests/test_environment_isolation.py` | LF | inventario con las dos variables nuevas; `test_the_suite_runs_without_package_variables_defined` admite las dos fijadas y exige su valor; el escáner de hooks ve `env.get("LOCAL_DELEGATE_…")` y lo comprueba; nuevo `test_only_resolve_language_reads_the_system_language` (constantes `LANG`, `LANGUAGE`, `LC_*` y atributos `GetUserDefaultUILanguage`, `getlocale`, `getdefaultlocale`, `windows_locale` solo en la lista blanca de `hook_common.py`) |
| `tests/test_language.py` (nuevo) | LF | 33 tests (con parametrizaciones, 63 casos): gramática, los nueve casos de REQ-018 afirmando idioma y origen, extras (`LC_MESSAGES`, vacía, preferencia rota o no válida, ruta devuelta, fallo de la API, LANGID fuera de la tabla, estonio), `i18n`, `output_language`, REQ-043 a y b, y el fixture de `locale` |
| `tests/test_i18n_parity.py` (nuevo) | LF | `check_pair` y `check_surfaces` con 8 tests sintéticos permanentes; paridad real por superficie, claves en su fichero, `HOOK_TEXTS` con paridad y solo ASCII, y toda clave literal de `t`/`t_lang` existe |
| `.github/workflows/ci.yml` | LF | trabajo `test-lang-es`: ubuntu, Python 3.11, `LANG=es_ES.UTF-8`, `locale-gen`, grupo `ui` y Chromium, guarda de entorno y la suite entera con `-n auto --dist loadgroup` |
| `scripts/ci_gate.py` | LF | `test-lang-es` en `EXPECTED_JOBS` |

Tamaño: 698 líneas nuevas en 5 ficheros; en los existentes, +480/−54 en 9 (incluidos el plan,
`rename-exceptions.md` y el léxico). La estimación enmendada era ~650 nuevas y ~275 en 6.

## 2. Controles positivos

Cada mutante se aplicó sobre el fichero, se corrió su test, se anotó el assert que dispara y se
restauró el fichero byte a byte (`git diff --stat` igual antes y después). Salida completa en
`evidence/B0a/mutants.txt`.

| Mutante | Test | Assert que dispara |
| --- | --- | --- |
| M1 pasos 1↔2 (la preferencia gana a la variable) | caso 8 | `('es', 'preference') == ('en', 'variable')` |
| M2 pasos 2↔3 (el sistema gana a la preferencia) | caso 7 | `('en', 'system') == ('es', 'preference')` |
| M3 se ignora `LANGUAGE` | caso 1 | `('en', 'system') == ('es', 'system')` |
| M4 `LANGUAGE` manda con el locale no declarado | caso 2 | `('es', 'system') == ('en', 'fallback')` |
| M5 `LANG` antes que `LC_ALL` | caso 3 | `('es', 'system') == ('en', 'system')` |
| M6 `c` fuera de los no declarados | caso 4 | `('en', 'system') == ('en', 'fallback')` en `C.UTF-8`, `C.utf8` y `C` (`POSIX` sigue en verde, como debe) |
| M7 Windows mira el formato regional (`GetUserDefaultLCID`) | caso 5 | `'es_ES' == 'en_US'` |
| M8 Windows lee `LANG` | caso 6 | `('en', 'system') == ('es', 'system')` |
| M9 variable no válida tomada como inglés | caso 9 | `('en', 'variable') == ('es', 'system')` |
| M10 gramática sin región numérica | gramática | `parse_language('es-419')` da `None` |
| M11 «empieza por es» literal | estonio | `('es', 'system') == ('en', 'system')` |
| M12 `current()` con el directorio del hook | `test_current_reads_the_preference_of_config_log_dir` | `('es', 'system') == ('en', 'preference')` |
| M13 `reset()` no olvida el idioma | caché | `'es' == 'en'` |
| M14 `ngettext` siempre en singular | `argparse_ngettext` | `'un argumento' == 'varios argumentos'` |
| M15 `OUTPUT_LANGUAGE` admite 41 | `output_language` | `('xxx…', None) == ('', 'too_long')` |
| M16 `OUTPUT_LANGUAGE` admite `Cf` | `output_language` | `('fr​', None) == ('', 'control_chars')` |
| M17 sin registro de `LOCAL_DELEGATE_LANG` | inventario | `'LOCAL_DELEGATE_LANG' in frozenset(...)` |
| M18 el fixture fija `en` | `test_the_suite_runs_without_package_variables_defined` | `{'LOCAL_DELEGATE_LANG': 'en'} != {'LOCAL_DELEGATE_LANG': 'es'}` |
| M19 lectura de `LANG` en `cli.py` (fichero CRLF; el mutante se aplicó con `\r\n`) | implementación única | `['cli.py:23 LANG'] == []` |
| M20 sin `LOCAL_DELEGATE_LOG_DIR` en el fixture (REQ-043 b) | hook como subproceso | `'en' == 'es'` |
| M21 traducción borrada de `en/common.json` | paridad `common` | `common.language.source.system: falta en en` |
| M22 `new_page` sin `locale` | fixture de `locale` | falta `{'locale': 'es-ES'}` |
| M23 el escáner de hooks no ve `env.get` | hooks declarados | `'LOCAL_DELEGATE_LANG' in {…}` |
| M24 `test-lang-es` en `ci.yml` y no en el gate | `test_the_expected_jobs_are_exactly_those_of_ci_yml` | sobra `'test-lang-es'` |

Control registrado en verde (REQ-043 a): con `LOCALAPPDATA`, `XDG_DATA_HOME`, `HOME` y
`USERPROFILE` falsos que contienen `language.json` = `en`,
`test_a_fake_user_preference_does_not_leak_in_process` sigue en verde. Además, la guarda de entorno
del trabajo de CI se probó en las dos direcciones (pasa con `LANG=es_ES.UTF-8` y falla con
`AssertionError: en_US.UTF-8`).

Dos tests se reforzaron al preparar los mutantes, porque el primer intento no podía fallar:
`test_current_reads_the_preference_of_config_log_dir` separa ahora `config.LOG_DIR` del directorio
del entorno (con los dos iguales, M12 sobrevivía), y el test de variables de los hooks afirma que el
escáner ve `LOCAL_DELEGATE_LANG` en `hook_common.py` (sin eso, M23 sobrevivía, porque la variable ya
está declarada en `config.py`).

## 3. Corridas

| Corrida | Resultado | Log |
| --- | --- | --- |
| Suite, `LANG=en_US.UTF-8`, `-n 4 --dist loadgroup`, bajo `pesado.sh` | 2704 passed, 2 skipped, 4 warnings (`DeprecationWarning` de starlette, ya existente) | `evidence/B0a/pytest-en.log` |
| Suite, `LANG=es_ES.UTF-8`, igual | 2704 passed, 2 skipped, 4 warnings | `evidence/B0a/pytest-es.log` |
| Tests nuevos y tocados (`test_language`, `test_i18n_parity`, `test_environment_isolation`, `test_ci_gate`, `test_detect_spanish_names`) | verdes | — |
| `ruff check .` y `ruff format --check .` | limpios (201 ficheros) | — |
| Detector de nombres con `rename-exceptions.md` | 0 fuera de la lista, 0 sin clasificar | `evidence/B0a/detector.txt` |

**Limitación (plan §4.2):** en Windows `LANG` no decide el idioma, así que las dos corridas de esta
PC no discriminan. La corrida que sí discrimina es el trabajo `test-lang-es` del CI del PR. En WSL
no se pudo correr: Ubuntu-24.04 no tiene `uv` ni el locale `es_ES` generado, e instalarlos cambiaba
el entorno del usuario. El control «sin el fixture de la variable fallan los asserts en español»
no discrimina todavía: en B0a no hay asserts en español que dependan del idioma; llega con B1.

## 4. Desviaciones

- **Excepciones del detector y léxico, adelantados de B0b a B0a.** El catálogo español nace en
  B0a y el detector lo marcaba (`preferencia`, `sistema` como `json_value`), igual que los códigos
  de idioma de los tests (`es-ES`, `es_ES`, `es_ES.UTF-8`). Se añadió la sección «Catálogo de textos
  (frente B)» a `rename-exceptions.md` (una fila comodín para `resources/i18n/es/*.json` y dos para
  los códigos de idioma), y 23 palabras al léxico congelado (`scripts/data/spanish_lexicon.json`:
  22 en inglés y `reserva` en español; el JSON se reescribió con el mismo formato, comprobado por
  ida y vuelta idéntica). El plan y la propuesta quedan ajustados.
- **`UNDECLARED_LOCALES` → `UNDECLARED_LOCALE_NAMES`.** El léxico clasifica `locales` como español
  (plural de «local»); se renombró la constante en vez de excepcionarla.
- **Separador de línea al final.** `"fr ".strip()` quita el separador (es espacio para
  Python), así que ese valor es válido; el caso de prueba usa `"fr en"`. Coincide con REQ-028
  («tras recortar espacios»).

## 5. Pendientes para B0b y siguientes

- B0b: `test_no_uncatalogued_text` con pendientes (con los ocho módulos asignados) y excepciones
  (`scripts/medir_enfriamiento.py`), red por tildes y detector de D10 con 20 + 20 frases y
  `min_tokens=8`.
- B1: el parche de argparse en `cli.py`, `argparse.json`, y mostrar en `doctor` el idioma, el
  origen (con `common.language.source.*`), la ruta y los avisos.
- B2b: usar `config.output_language()` y `common.output_language.*`.
- B4: pasar las 17 llamadas `browser.new_page` de `test_dashboard_ui.py` al fixture `new_page`.

## 6. Llamadas `local_*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B0 (fase 1) | `local_summarize(path=research-i18n.md)` | §4–§5 y preguntas abiertas sin leer el fichero |
| Agente B0 (fase 1) | `local_explain_code(path=hook_common.py)` | `log_dir`, variables leídas y canales de `emit`/`deny` (truncó a 20 027 de 25 416 caracteres; lo necesario estaba dentro) |
| Agente B0a (fase 2) | `local_lint_summary(path=pytest-es.log)` | resumen de la corrida en español: solo las 4 `DeprecationWarning` de starlette |
| Agente B0a (fase 2) | `local_commit_msg(path=b0a.diff)` | borrador del commit; salió en inglés y de una línea («feat(i18n): add language resolution, config and tests»), así que el mensaje final se redactó a mano |

No se usaron tools de PyCharm: no hubo renombrados de símbolos (el único, `UNDECLARED_LOCALE_NAMES`,
estaba en un solo fichero).
