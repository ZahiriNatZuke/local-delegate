# Verificación (modo lite): vigilante de la captura del README

## Entorno

- Rama `feat/vigilante-captura-readme`, sobre `main` en `6d78ffc`.
- Windows 11, Python 3.13 (`uv`), Playwright ya instalado en el entorno.
- Dashboard servido **desde el repo** con uvicorn sobre `metrics.app` en el 9494.

## Evidencia

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001 | `docs/assets/dashboard.json` | existe, con `version`, `sha256`, `bytes` y `file`; generado **con el mismo código** que usa el script, no escrito a mano |
| REQ-002 | Ejecución real contra el 9494 | escribe PNG **y** manifiesto: «versión 0.17.0, la que sirvió el dashboard capturado» |
| REQ-002 | Borde: dashboard que no responde | `exit 3`, mensaje claro, y el manifiesto anterior **intacto** (comprobado por `mtime_ns`) |
| REQ-003 | Test de integridad | pasa; y **falla** si se altera un solo byte del PNG |
| REQ-004 | Test de actualidad | pasa; y **falla** si el manifiesto declara otra versión |
| REQ-005 | Mensaje de fallo | trae el comando exacto de arranque y de captura, y avisa de no usar el daemon del 9393 |
| REQ-006 | `docs/wiki/Publishing.md` | remite al test, corrige el comando de arranque y da el que sí funciona |
| REQ-003 | `git check-attr -a docs/assets/dashboard.png` | `text: unset`, o sea `-text` declarado |

### Ejecución real, no solo tests

```
…\prueba.png — 390 eventos, indicador «EN CURSO», 6 gráficos
…\prueba.json — versión 0.17.0, la que sirvió el dashboard capturado
```

Y el comando que la wiki documentaba se probó antes de sustituirlo: `python -m
local_delegate.web.metrics` **no arranca** con el daemon en el 9393 (`error while attempting to
bind on address ('127.0.0.1', 9393)`) y no acepta puerto. El sustituto —uvicorn sobre
`metrics.app` en el 9494— responde `200` y su `/api/status` da `version: 0.17.0` y 11 tools.

### Los tests, verificados al revés

Cuatro defectos inyectados, los cuatro cazados, y el estado restaurado después:

| Defecto inyectado | Resultado |
| --- | --- |
| El manifiesto declara `0.18.0` (simula el bump sin regenerar, que es el caso de la 0.16.0) | 1 falla, 2 pasan |
| Un byte del PNG cambiado y el manifiesto sin tocar | 1 falla, 2 pasan |
| El `_acerca_de` deja de explicar de dónde sale la versión | 1 falla, 2 pasan |
| No hay manifiesto | **3 fallan**, con el mensaje que dice cómo crearlo |
| *(restaurado)* | **3 pasan** |

## Comprobaciones de calidad

- [x] `uv run pytest -q` → **481 pasan**, 1 skip (eran 478 en `main`).
- [x] `uv run ruff check .` → *All checks passed!*
- [x] `uv run ruff format --check .` → 55 ficheros ya formateados.
- [x] `extract_dashboard_js.py` + `node --check` → OK.
- [x] `CHANGELOG.md` sigue siendo **CRLF puro** (948 CRLF, 0 LF sueltos), comprobado tras editarlo.
- [x] Secretos: el hook de pre-commit pasa; el manifiesto solo lleva un hash y un número.
- [x] Sin cambios ajenos: el diff toca `scripts/dev/capture_dashboard.py`, `tests/test_captura.py`,
      `docs/assets/dashboard.json`, `.gitattributes`, `docs/wiki/Publishing.md` y el `CHANGELOG`.

## Corrección de un hecho que llegué a dar por bueno

Al aprobar la spec quedó escrito que `python -m local_delegate.web.metrics` «sale con **exit 0**,
así que parece que arrancó». **Es falso: sale con exit 3.** El `0` que vi era el de `head` al otro
lado de una tubería. El motivo de REQ-006 se sostiene igual —no arranca y no acepta puerto— pero
el detalle no era cierto. Queda anotado también en `plan.md`.

## Desviaciones y riesgo residual

- **La captura no es reproducible entre días, y el docstring del script dice que sí.** Los datos
  llevan semilla fija, pero el eje temporal sale de `new Date()`, así que capturar mañana da otro
  PNG. No lo introduce este cambio y no lo arregla: queda anotado. En la práctica no molesta,
  porque el manifiesto se regenera junto al PNG.
- **El diseño del dashboard sigue sin vigilarse**, por decisión explícita de la especificación:
  hashear `web/metrics.py` daría falsos positivos constantes. Riesgo aceptado, igual que los PNG
  de marca y la `og-image`.
- **Efecto buscado, que hay que tener presente al publicar:** el PR que suba a 0.18.0 **fallará**
  hasta que se regenere la captura. Publicar pasa a incluir ese paso.
