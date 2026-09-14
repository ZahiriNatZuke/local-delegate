# Corpus de la tanda de F2 (catálogo de modelos, 2026-09)

Tareas **reales** del log de uso del MCP, no sintéticas como las de `benchmarks/moe/`. El protocolo
completo —de dónde sale cada caso, qué mide y cómo se decide— está en
`.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md` (§4).

| Fichero | Qué es |
| --- | --- |
| `cases.json` | `schema_version: 2`: 15 casos de calidad, 2 sondeos de techo y la imagen de control de CP-3 |
| `fuentes/` | copias congeladas de cada fuente; el cargador **falla** si un hash no cuadra |
| `conteos-log.json` | conteos agregados del log real (§4.2), sin ninguna ruta de fuera del repo |

**No se edita a mano.** Todo sale de `scripts/construir_corpus.py`:

```powershell
uv run python scripts/construir_corpus.py              # congela, captura, comprueba y escribe
uv run python scripts/construir_corpus.py --comprobar  # recaptura contra lo versionado
```

El constructor no copia el rol ni el prompt de una tabla: **llama a la tool real de `server.py`**
con el backend interceptado y guarda qué modelo eligió producción, cuántas llamadas hizo y con qué
`system` y `user_template`. Si un caso de calidad no cabe en una sola llamada, si su rol no es el
que elegiría producción, si el modelo no ve la entrada entera o si el id promete un tamaño que la
fuente no tiene, **el corpus no se escribe**. `tests/test_corpus.py` repite esa recaptura contra el
código de cada commit: cambiar un `MAX_CHARS`, el enrutado o un prompt lo pone en rojo.

La captura no toca el backend, no escribe en el log de uso y corre sin las variables
`LOCAL_DELEGATE_*` del entorno.

Las fuentes van con `-text` en `.gitattributes`: se comparan por SHA-256 y un checkout de Windows
les cambiaría los fines de línea. Los fragmentos de código se guardan como `.py.txt` porque están
cortados a mitad de fichero y no deben pasar por ruff.
