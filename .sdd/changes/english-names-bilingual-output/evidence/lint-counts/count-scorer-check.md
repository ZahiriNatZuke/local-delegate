# Control del lector de cifras (`score_counts.py`), antes de medir

Sobre las dos respuestas reales de la pasada de la 0.36.0 (`../live-036/answers/*/local_lint_summary.txt`),
revisadas a mano en su día (español: D101 y D400 mal; inglés: 15/15):

| Lector | Español | Inglés |
|---|---|---|
| v3 tal cual (cifras detrás del código) | 5 mal + 4 sin cifra: atribuye a D101 el 3 de D102 | 0 mal |
| v3 + cifra delante cuando la frase empieza con número, y suma aceptada | **D101 6≠5, D400 4≠3** (igual que la revisión a mano) | 0 mal |

El formato español «6 errores de … (D101) y 3 errores de … (D102)» pone la cifra delante del
código en una frase con varios códigos; v3 solo leía la cifra de detrás. El arreglo: si hay cifra
antes del primer código de la frase, cada código toma las cifras entre el código anterior y él.
Además se acepta la suma (RUF002 dado en dos entradas «1» y «1» con 2 en el log).

Control negativo: sobre la respuesta inglesa, D101 5→6 y D415 2→7 salen como cifras mal; «three
functions» (C901, 3) sigue bien (número en palabras).
