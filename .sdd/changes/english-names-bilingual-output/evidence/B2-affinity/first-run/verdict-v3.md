| Idioma | Rep. | Estado | Criterios que fallan | Calidad por caso (rol / 2B / 26B) | Latencia mediana 26B / rol (ms) |
| --- | --- | --- | --- | --- | --- |
| es | 1 | rejected | quality | tres-reglas 1.00 / 0.67 / 0.00; docstrings 0.75 / 0.00 / 0.00; un-solo-archivo 0.67 / 0.00 / 1.00; cinco-reglas 1.00 / 1.00 / 0.00 | 3207.5 / 1787.5 |
| es | 2 | rejected | quality | tres-reglas 1.00 / 0.00 / 0.00; docstrings 0.50 / 0.25 / 0.00; un-solo-archivo 0.67 / 0.00 / 1.00; cinco-reglas 1.00 / 0.75 / 0.00 | 3315.5 / 1406.5 |
| es | 3 | rejected | quality | tres-reglas 1.00 / 1.00 / 0.00; docstrings 0.75 / 0.00 / 0.00; un-solo-archivo 0.67 / 0.00 / 0.00; cinco-reglas 0.25 / 0.50 / 0.00 | 3284.5 / 1614.0 |
| es | — | **rechazada** | respuestas distintas de 12: {'gemma3-4b': 11, 'qwen35-2b': 12, 'gemma4-26b-a4b': 8} | | |
| en | 1 | approved | — | tres-reglas 1.00 / 0.33 / 1.00; docstrings 0.75 / 0.00 / 1.00; un-solo-archivo 0.67 / 0.67 / 1.00; cinco-reglas 1.00 / 0.25 / 1.00 | 3423.0 / 1931.0 |
| en | 2 | rejected | quality | tres-reglas 1.00 / 0.00 / 1.00; docstrings 0.50 / 0.00 / 1.00; un-solo-archivo 0.33 / 1.00 / 0.00; cinco-reglas 1.00 / 0.25 / 1.00 | 3703.5 / 1985.5 |
| en | 3 | approved | — | tres-reglas 1.00 / 0.33 / 1.00; docstrings 0.50 / 0.00 / 1.00; un-solo-archivo 0.33 / 0.00 / 1.00; cinco-reglas 1.00 / 0.75 / 1.00 | 3678.5 / 1941.0 |
| en | — | **rechazada** | respuestas distintas de 12: {'gemma3-4b': 12, 'qwen35-2b': 12, 'gemma4-26b-a4b': 7} | | |

Carga en frío mediana del rol: 3.2657347044803604 s
