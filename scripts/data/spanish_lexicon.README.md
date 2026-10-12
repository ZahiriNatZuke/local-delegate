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
