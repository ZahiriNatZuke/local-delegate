# Léxico del detector de nombres en español

`spanish_lexicon.json` es el léxico **congelado** que usa `scripts/detect_spanish_names.py`
(REQ-044). `reserved_words.json` es el control de sus heurísticas.

## Qué contiene

- `es`: palabras (plegadas: minúsculas y sin tildes) que en este repo son español.
- `en`: palabras que en este repo son inglés o neutras (abreviaturas técnicas como `cmd`, `gib`,
  `jsonrpc`; letras sueltas).
- `function_words`: palabras funcionales españolas cortas (`de`, `en`, `o`…). Cuentan como
  español, pero un nombre hecho de **una sola** no se marca.

Son **solo palabras que aparecen en el propio repo**: identificadores de Python, claves y valores
de máquina en cadenas, nombres del JS del panel, ids del DOM, claves y valores de los `.json` de
`src/**/resources` y nombres de fichero. No hay ningún dato de terceros: ni frecuencias, ni listas
de diccionario.

## Cómo se generó (2026-10-12, ola A0)

1. Universo de palabras, con el propio detector y sin red:

   ```
   python scripts/detect_spanish_names.py --dump-words palabras.json
   ```

   Dio 4 680 palabras.

2. Propuesta de clasificación **fuera del repo** con `wordfreq` 3.1.1 (Socket: 100 en las cinco
   puntuaciones el 2026-10-12), en un directorio temporal y sin tocar el entorno del proyecto:

   ```
   uv run --no-project --with wordfreq==3.1.1 python -I gen_lexicon.py palabras.json propuesta.json
   ```

   Regla (la de la investigación, `research-rename.md` §0): una palabra es española si su
   frecuencia Zipf en español es ≥ 1,8 y supera a la inglesa en más de 1,0. Antes de mirar
   frecuencias, una lista corta de términos técnicos (`id`, `url`, `gpu`, `llama`, `util`…) y de
   palabras que en código son inglés (`total`, `local`, `error`, `general`…) va a `en`, y las
   palabras de menos de tres letras también. De la propuesta solo se copia la **etiqueta** de cada
   palabra; las frecuencias no se guardan.

3. Revisión a mano de los dudosos: las 141 propuestas como español con frecuencia inglesa alta
   (todas se quedaron en español salvo `ver`, que en el repo es abreviatura de versión) y las 174
   propuestas como inglés con frecuencia española mayor. De estas, pasaron a español las que en el
   repo se usan en español (`cola`, `canal`, `coma`, `patron`, `sale`, `son`, `sea`, `pie`,
   `meter`, `favor`, `coincide`, `vigilante`, `subagentes`, `tam`, `rech`…); se quedaron en inglés
   las que se escriben igual en los dos idiomas y no piden renombre (`temporal`, `tension`,
   `dispersion`, `revision`, `social`, `personal`, `extension`…).

4. Auditoría por muestreo: 110 palabras con `random.Random(20261012)`, revisadas una a una. Un error
   (`actual`, que en el repo es el adjetivo español y se había quedado en inglés): 0,91 %, por
   debajo del 2 % que exige la spec. Se corrigió en el léxico. La muestra completa está en
   `.sdd/changes/english-names-bilingual-output/evidence/A0/lexicon-audit.csv`.

5. Al cerrar la ola A0, el detector informó de 85 palabras sin clasificar que traían los ficheros
   nuevos de la propia ola (`horizonte`, `sellado`, `overdue`, `removal`…). Se clasificaron a
   mano, sin `wordfreq`: 29 español y 56 inglés.

6. Al cerrar el frente A (2026-10-14, lote A-close-4), tras los renombres de las olas A1–A10 y
   del cierre, el detector informó de 794 palabras sin clasificar: las inglesas nuevas de los
   nombres renombrados (`attribution`, `voided`, `wildcard`…) y tres españolas, los valores viejos
   que lee `legacy_names.py` (`aprobada`, `congelado`, `reconstruido`). Se clasificaron a mano,
   una a una y sin `wordfreq`: 3 español y 791 inglés. Además `suspicion` pasó a `en` (el falso
   positivo del sufijo `-cion`, que ya sale en el repo). Dentro de las 791 están `comment` e
   `identity`, que eran palabras reservadas pero salen en el repo (y por eso quedaban sin
   clasificar para siempre): entraron en `en` y se cambiaron en `reserved_words.json` por `ornament` y `serenity`, que no
   salen en el repo y se parecen igual a los sufijos `-mente` e `-idad`. La lista está en
   `.sdd/changes/english-names-bilingual-output/evidence/A-close-4/lexicon-classification.csv`.

7. En el lote A-close-5 (2026-10-14) el detector informó de 2 palabras sin clasificar, a mano:
   `redactado` a español (valor viejo de `source_body` que lee `legacy_names.py`) y `they` a
   inglés (nombre de un test nuevo).

8. En el lote B2c (2026-10-14) el detector informó de 8 palabras sin clasificar, a mano, todas a
   inglés: `decorator`, `decorators`, `definitions`, `defs`, `partials`, `room` y `shortcut`
   (nombres del troceado de `local_explain_code`/`local_extract` y de sus tests) y `zzz` (el
   marcador `ZZZ_marker` del test del fichero de 60 000 caracteres, que pide el plan).

9. Tras la 0.36.0 (2026-10-18) el detector informó de 111 palabras sin clasificar, revisadas a
   mano una a una: 16 a español y 95 a inglés. Las españolas son los numerales que reconoce
   `scripts/score_lint_fidelity.py` (`seis`, `diez`, `trece`…`diecinueve`, con su fila en
   `name_exceptions.json` igual que `cero`…`veinte`) y textos del catálogo `i18n/es`
   (`eliminada`, `eliminado`, `estimado`, `estimados`, `insertado`, `listo`, `reemplazado`). Las
   inglesas son palabras de nombres de tests, del panel y de los scripts de medición (`asserts`,
   `counterfactual`, `judgeable`, `unpinned`…) y abreviaturas técnicas (`ast`, `tsc`, `https`,
   `nav`, `cols`). Desde entonces el guardián
   `test_repo_has_no_spanish_name_outside_the_exception_list` exige también 0 sin clasificar.

10. Al mezclar las tarjetas de ancho fijo del panel (2026-10-19) el detector informó de 3 palabras
    sin clasificar, a mano, todas a inglés: `kfit` (el ajuste de la cifra de las tarjetas,
    `KFIT_MIN` y `kfitObserver`), `disconnect` (método del `ResizeObserver`) y `frames` (`_FRAMES`,
    espera de fotogramas en `tests/test_dashboard_ui.py`).

11. En la ola lint-large-logs (2026-10-19) el detector informó de 4 palabras sin clasificar, a
    mano, todas a inglés: `countable`, `eslint`, `forbids` (nombres de tests de
    `tests/test_lint_large_logs.py`) y `ranked` (variable de `lint_patterns.per_file_code_counts`).

12. Al alinear la fila de KPIs con los paneles (2026-10-19) el detector informó de 5 palabras sin
    clasificar, a mano, todas a inglés: `edges`, `gaps`, `panels`, `straddling` y `tight` (medidas
    y nombres de los tests de bordes de `tests/test_dashboard_ui.py`).

13. En el lote L0 del SDD `backend-extra-params` (2026-10-20) el detector informó de 14 palabras
    sin clasificar, a mano, todas a inglés: las claves de llama-server que la guarda de
    `tests/test_tool_signatures.py` copia de la spec (`cmpl`, `eta`, `mirostat`, `multiplier`,
    `penalty`, `predict`, `probability`, `probs`, `tau`, `typical`, `xtc`) y nombres de ese test y
    de `tests/test_request_body_compat.py` (`indirect`, `offenders`, `want`).

14. En el lote E de backend-extra-params (2026-10-20, marcas y diálogo de detalle del panel) el
    detector informó de 6 palabras sin clasificar, a mano: `rechazados` a español (texto del
    catálogo `i18n/es/panel.json`) y 5 a inglés: `paramschip` (clase de la marca de parámetros),
    `closest`, `prevent` y `stringify` (métodos del DOM y de `JSON` en el JS del panel) y
    `reasoned` (variable de `tests/test_dashboard_states.py`).

15. Con las reglas de los parámetros por rol al backend (lote A1 del mismo SDD, 2026-10-20) el
    detector informó de 13 palabras más sin clasificar, a mano, todas a inglés: las claves
    aplazadas de la spec (`adaptive`, `breakers`, `decay`, `dynatemp`, `exponent`) y palabras de
    `src/local_delegate/backend_params.py` y de sus tests (`finite`, `hide`, `hostile`, `inf`,
    `nan`, `sentinel`, `sentinels`, `validation`).

16. Con el fichero, la caché y la resolución por rol (lote A2 del mismo SDD, 2026-10-20) el
    detector informó de 9 palabras más sin clasificar, a mano, todas a inglés: `anyway`, `foo`,
    `got`, `holder`, `loss`, `mutator`, `needed`, `refuse` y `temporaries` (de
    `src/local_delegate/backend_params.py` y de sus tests).

18. Con la fusión de los parámetros por rol en el embudo de `server.py` (lote C1 del mismo SDD,
    2026-10-20) el detector informó de 1 palabra más sin clasificar, a mano, a inglés: `survive`
    (de `tests/test_backend_params_server.py`). La entrada 17 es la del lote B, que se trabajó en
    paralelo; al rebasar se unen las listas.

## Heurísticas (no usan datos ajenos)

En `detect_spanish_names.classify_word`, en este orden:

1. tilde o eñe → español;
2. léxico (`es`, `function_words` → español; `en` → inglés);
3. sufijo español sobre la palabra plegada, con seis letras o más: `-cion(es)`, `-miento(s)`,
   `-idad(es)`, `-iendo`, `-mente`, `-aje(s)`;
4. menos de tres letras → neutra;
5. el resto → **sin clasificar**.

Falsos positivos conocidos del sufijo: `suspicion` y `coercion`. Si salen en el repo, el léxico
los fija como inglés, y el léxico manda sobre la heurística.

## Cuándo se actualiza

Cuando el detector informa de palabras **sin clasificar** (salen en el repo y no están en el
léxico). Esas palabras bloquean el cierre de REQ-016 hasta que alguien las clasifica a mano y las
añade a `es` o `en`. Ninguna palabra de `reserved_words.json` puede entrar en el léxico: lo
comprueba `tests/test_detect_spanish_names.py`.
