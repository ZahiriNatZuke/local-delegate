# Revisión de `local_commit_msg` y `local_explain_code` (2026-10-14)

Ventana de prueba `w-20261014T182701Z` (18:27:01Z–18:31:17Z). Daemon 0.35.0; rol `code` = `qwen36-35b-a3b`, contexto 16 384 tokens. Llamadas: `local_commit_msg` ×3, `local_explain_code` ×1, `local_status` ×1.

## 1. `local_commit_msg` en inglés y de una línea — fallo del producto (dos causas)

**Idioma.** `LOCAL_DELEGATE_COMMIT_LANGUAGE` no está definida en ningún sitio (lanzador `start-local-delegate-secure.ps1`, entorno de usuario ni de máquina): nunca se configuró. El código la lee y aplica bien (`config.py:417`, `server.py:3219`, `tests/test_commit_language.py`). Sin ella, el prompt pide «el idioma predominante del diff»; en diffs del frente B (código en inglés + catálogos `en`/`es`) el modelo elige uno u otro. Reproducido: `b0a.diff` → inglés; `b1a.diff` y un diff pequeño → español.

**Una sola línea.** El formato dice «cuerpo opcional» (`server.py:3879-3887`) y el paso final del troceado no pide cuerpo; topes de 256 tokens (una llamada) y 244 (paso final, `max_words=90`). En el log todas las filas acaban en `stop`, `chars_out` 53–66 en 8 de 10; diff pequeño sin troceado: `tokens_out=19`. El modelo para por decisión propia; el troceado solo lo vuelve más genérico.

**Arreglo propuesto.** Sin la variable, por defecto el idioma de salida del producto (`resolve_language`); la regla del diff solo como opción explícita. Cuerpo obligatorio de 2–6 viñetas; topes ~700 tokens (una llamada) y `max_words≈250` (paso final). Tests con backend falso que capture prompt y tope; control positivo: con el código actual fallan por el assert de idioma o de truncado. Paliativo sin código: `LOCAL_DELEGATE_COMMIT_LANGUAGE=es` en el lanzador (solo idioma; exige reiniciar el daemon).

## 2. `local_explain_code` corta la entrada — fallo del producto

Trunca a 20 000 caracteres (`LOCAL_DELEGATE_MAX_CHARS_CODE`) en una sola llamada, sin trocear (`server.py:4033`). Este mes truncó en 10 de 24 llamadas (`hook_common.py` leyó el 79 %, `cli.py` el 32 %). Avisa con prefijo «[entrada truncada — procesados 20027 de 58875 chars]», pero la explicación presenta como completa una lista de subcomandos de `cli.py` a la que faltan `doctor`, `benchmark` y `llamaswap`. `local_summarize` y `local_lint_summary` sí trocean (0 de 20 entradas > 48 000 truncadas). `local_extract` trunca igual. El presupuesto en chars es conservador (20 027 chars = 5 357 tokens de 16 384) pero no es la causa: `cli.py` tiene 63 000.

**Arreglo propuesto.** `local_explain_code` y `local_extract` por `_chat_map_reduce`, partiendo por `def`/`class` de primer nivel y llevando la pregunta al paso final. Test: fichero de ~60 000 chars con `def ZZZ_marker` al final debe llegar al backend; control positivo: con el código actual falla en ese assert.

## Relación con B2

B2 toca en `server.py` `_truncation_prefix`, `_guard`, `_commit_language_instruction` y el aviso de alcance. El idioma del commit conviene resolverlo dentro de B2 (misma regla única de idioma); el troceado y los topes, en un lote aparte en serie con B2.
