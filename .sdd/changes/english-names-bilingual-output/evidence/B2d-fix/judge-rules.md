# Juez de idioma «solo prosa» (B2d-fix)

Script: `scripts/judge_response_language.py` (sus reglas, también en su docstring). Tests:
`tests/test_judge_response_language.py` (23, casos sintéticos). Mutantes: `judge-mutants.md`.
Se fijó DESPUÉS del conjunto de control 3 (`lang-sample-docs-3.json`, commit `b3e9d08`) y ANTES de
puntuar nada con él. El detector (`scripts/detect_language.py`) y su umbral no se tocan.

## Por qué

El juez de antes pasaba al detector la respuesta entera menos las líneas del producto. En las
pruebas en vivo X e Y (`live-probe-X.json`, `live-probe-Y.json`) eso mezclaba dos cosas: lo que el
formato obliga a copiar (títulos del documento, rutas, códigos de regla como `I001`/`UP006`, que el
detector cuenta como palabras) y lo que el modelo redacta. Este juez quita solo lo primero.

## Reglas, en este orden

| Regla | Qué se quita | Ejemplo |
|---|---|---|
| R1 | Líneas del producto enteras | «(leído server-side: …)», «(read server-side: …)», «[local-delegate warning: …]», «(sin resumir)», «(not summarized)»; y la lista «Sin mencionar (…): …» / «Not mentioned (…): …» de `local_lint_summary` y `local_explain_code`, que va en el idioma de la interfaz: su texto sale de las claves `mcp.lint.not_mentioned` y `mcp.explain.not_mentioned` en todos los idiomas del catálogo (añadido el 2026-10-19, muestra fr de REQ-028) |
| R2 | Líneas de título `#`…`######` cuyo texto, normalizado con `sections.normalize_heading`, coincide con un título del documento ORIGINAL (`sections.markdown_headings`) | `## Configuración del sistema` copiado tal cual; también `### 2. CONFIGURACION DEL SISTEMA` |
| R3 | Código: bloques con valla (```` ``` ```` o `~~~`) y spans `` `…` `` | `` `return value` `` |
| R4 | URLs (`http://`, `https://`, `www.`); solo la URL, no el texto de un enlace Markdown | `[guía](https://…)` deja «guía» |
| R5 | Rutas: un trozo sin espacios que contiene `/` o `\` | `src/app/main.ts:3:8`, `C:\tools\bin`, también `y/o` |
| R6 | Nombres de regla en kebab-case | `no-unused-vars`, `no-console` (también `well-known`: no son palabras funcionales y solo bajan el denominador) |
| R7 | Identificadores: con `_`, camelCase/PascalCase con mayúscula interior, con punto entre letras, `--flags`, `nombre()` | `load_config`, `useState`, `AuditMetadata`, `sections.detect` |
| R8 | Números y nombres con código: todo trozo que contenga un dígito | `57`, `0.75s`, `12ms`, `v255`, `E501`, `I001`, `UP006`, `TS2345` |

**No se quita:** las etiquetas en negrita `**…**`, los nombres de sección y de chequeo, los títulos
que no están en el documento (traducidos o inventados), el texto de las listas. Todo eso tiene que ir
en el idioma pedido. La «Introducción»/«Introduction» sintética tampoco se quita: desde B2d-fix va en
el idioma de respuesta.

Los códigos con dígitos iban al principio en R6 con su propia expresión; el primer pase de mutantes
mostró que R8 ya los quitaba (el mutante de esa expresión no hacía fallar nada), así que se quitó la
expresión y R6 quedó solo para kebab-case. El test de códigos pasó a llamarse de R8.

## Veredicto

1. Se cuentan los tokens del detector (`[a-záéíóúüñ]+`) en lo que queda.
2. Menos de 20 (el `MIN_TOKENS` del detector): **`not_judgeable`**. No es aprobado ni fallo: se
   informa aparte.
3. Si no, `detect(texto, min_tokens=20, min_margin=0.15)` sin tocar: **`requested`** (el pedido),
   **`opposite`** (el otro) o **`unknown`** (margen menor que 0,15), con el margen anotado.

## Uso

```
python scripts/judge_response_language.py --document DOC --requested en RESPUESTA [RESPUESTA ...]
```

Una línea JSON por respuesta: `verdict`, `lang`, `tokens`, `es_ratio`, `en_ratio`, `margin`.
Desde Python: `judge(respuesta, documento, "en")` devuelve también `judged_text`.

## Límites conocidos

- R5 quita «y/o» y «and/or»; R6 quita compuestos con guion en minúscula. Ninguno es palabra
  funcional del detector: solo bajan el denominador.
- R2 compara con los títulos del documento, no con los de otra respuesta: un título traducido se
  juzga (y debe ir en el idioma pedido).
