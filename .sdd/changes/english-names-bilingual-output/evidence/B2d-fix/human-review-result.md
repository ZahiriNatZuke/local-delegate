# Resultado de la revisión humana del juez de prosa (B2d-fix)

Fuente: `human-review-sample.md` rellenado por Yohan (cambio sin commit sobre la versión fijada; 12
casillas marcadas, 12 notas escritas). Reglas del juez: `judge-rules.md`. Ninguna casilla vacía ni
ambigua: las 12 marcan «sí», ninguna «no».

## Respuestas

| # | Id | Pedido | Juez de antes | Juez nuevo | Yohan |
|---|---|---|---|---|---|
| 1 | batch1-02 | inglés | `unknown` (0.0937) | `requested` (0.1597) | sí |
| 2 | batch1-10 | inglés | `requested` (0.1786) | `not_judgeable` (19 tokens) | sí |
| 3 | batch2-16 | español | `unknown` (0.0811) | `not_judgeable` (18 tokens) | sí |
| 4 | probeX-06 | inglés | `unknown` (0.1462) | `requested` (0.2043) | sí |
| 5 | probeY-04 | inglés | `unknown` (0.0841) | `requested` (0.2364) | sí |
| 6 | probeY-06 | inglés | `unknown` (0.1222) | `requested` (0.2203) | sí |
| 7 | batch1-04 | inglés | `requested` (0.2672) | `requested` (0.3265) | sí |
| 8 | batch1-18 | inglés | `requested` (0.2364) | `requested` (0.3684) | sí |
| 9 | batch2-11 | español | `requested` (0.3) | `requested` (0.4242) | sí |
| 10 | batch2-13 | español | `requested` (0.3235) | `requested` (0.3743) | sí |
| 11 | batch2-20 | español | `requested` (0.2465) | `requested` (0.3397) | sí |
| 12 | probeY-02 | inglés | `unknown` (0.0731) | `unknown` (0.081) | sí |

## Concordancia con Yohan

| Juez | Aciertos / casillas juzgables | `not_judgeable` | `unknown` | `opposite` |
|---|---|---|---|---|
| Nuevo | **9 / 10** (90 %) | 2 (batch1-10, batch2-16: Yohan dice «sí» en ambas) | 1 (probeY-02) | 0 |
| De antes | **6 / 12** (50 %) | — | 6 | 0 |

`unknown` cuenta como desacuerdo (Yohan siempre decidió). Si se excluyen también los `unknown`, los dos
jueces aciertan todo lo que deciden (nuevo 9/9, antes 6/6): la diferencia está en cuántas veces se
abstienen.

## Desacuerdos

- **probeY-02, los dos jueces dicen `unknown`, Yohan «sí»**: la prosa está en inglés, pero los nombres
  de sección copiados del log («Entorno (el CLI y los clientes)», «Servicios», «Versiones (…)») son
  líneas de lista, no títulos `#`, así que R2 no los quita y el detector los cuenta como prosa española.
  Es una diferencia de **criterio**, no un fallo aleatorio: `judge-rules.md` dice que los nombres de
  sección se juzgan; la cabecera de la muestra dice que lo copiado del documento no cuenta. Se repetirá
  en todo `local_lint_summary` sobre logs en español con secciones como texto plano.
- **Juez de antes, cinco `unknown` que el nuevo resuelve** (batch1-02, batch2-16, probeX-06,
  probeY-04, probeY-06): títulos del documento, rutas, códigos (`I001`, `SIM102`) y marcas del log
  contaminaban el texto juzgado. Es justo lo que el juez nuevo quita (R2, R5, R8).
- **Abstenciones del juez nuevo** (batch1-10, batch2-16): 19 y 18 tokens de prosa, bajo el mínimo de 20.
  No son errores; Yohan las llama «abstención razonable» en batch1-10.

## Comentarios de Yohan (literales, campo «Notas»)

1. batch1-02: «Toda la prosa en inglés. Lo que queda en español son los títulos de sección del documento, copiados tal cual (las etiquetas en negrita también son títulos del documento).»
2. batch1-10: «Todo en inglés. Es corta: el «no juzgable» del juez nuevo es una abstención razonable, no un error.»
3. batch2-16: «Todo lo redactado en español («Importes» es un calco, lo correcto sería «Importaciones», pero el idioma es el pedido). Ojo aparte: la línea final del producto sale en inglés cuando se pidió español.»
4. probeX-06: «Todo en inglés.»
5. probeY-04: «Todo en inglés; «[FALT]» es una marca copiada del log. El modelo tradujo los nombres de sección («Scaffolding», «Environment»).»
6. probeY-06: «Todo en inglés; mismo caso que la anterior.»
7. batch1-04: «Todo en inglés (documento en inglés y respuesta en inglés).»
8. batch1-18: «Todo en inglés. (La fidelidad al contenido es dudosa, pero eso no es lo que se mide aquí).»
9. batch2-11: «Prosa en español. Los encabezados en inglés («Installation», «Usage»…) son títulos del documento copiados; solo «Introducción» la escribe el modelo y está en español.»
10. batch2-13: «Prosa en español; títulos de sección y etiquetas en negrita («Hate Type Annotations!?», «Backwards-incompatible Changes») son títulos del documento copiados.»
11. batch2-20: «Descripciones de las reglas en español; los códigos de regla y rutas no cuentan. Truncada por max_tokens, pero eso no afecta al idioma.»
12. probeY-02: «Caso límite. La prosa está en inglés, pero los nombres de sección («Entorno (el CLI y los clientes)», «Servicios», «Versiones (…)») salen en español, copiados del log. Por la regla del fichero (títulos copiados no cuentan) es «sí»; un lector que pidió inglés lo vería mezclado, y en probeY-04/06 el modelo sí los tradujo. El «no se sabe» del juez es defendible.»

## Lectura

- El juez nuevo concuerda con el juicio humano en 9 de 10 casos juzgables y no da ningún `opposite`
  falso. El único desacuerdo es sistemático y conocido (nombres de sección en texto plano copiados de
  un log) y Yohan lo considera defendible.
- **Límite de la muestra**: las 12 son «sí». No hay ningún caso negativo, así que esta revisión mide
  que el juez no condena respuestas buenas, pero **no** que detecte las malas (no hay control
  positivo de fallo). Para eso hace falta al menos una respuesta realmente en el idioma contrario,
  revisada a mano, o apoyarse en los tests sintéticos y mutantes del juez.
- Aparte (no es del juez): en varias respuestas la línea del producto «(leído server-side…)» sale en
  el idioma contrario al pedido (batch2-11, batch2-13, batch2-16, batch2-20 en inglés con español
  pedido; las de inglés pedido, en español). R1 la quita, así que no afecta al veredicto, pero Yohan lo
  señala en batch2-16.
