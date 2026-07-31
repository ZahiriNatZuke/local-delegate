# Verification: Los PNG de la marca quedan atados al favicon.svg

## Environment

- Base tras el PR #112 (`main`); rama `feat/iconos-atados-al-svg`.
- Windows 11, `uv run`, playwright/chromium instalado fuera del proyecto.

## Evidence

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001 | `site/icons.json` generado | ✅ `source_sha256` = `8b26059a…` |
| REQ-002 | mutante: `favicon.svg` tocado | ✅ falla `test_los_png_se_generaron_*` |
| REQ-003 | mutante: PNG tocado a mano | ✅ falla `test_el_manifiesto_describe_*` |
| REQ-004 | mutante: icono fuera del manifiesto | ✅ fallan **dos** tests, uno el de conjuntos |
| REQ-005 | script ejecutado | ✅ dos PNG + manifiesto en un comando |
| REQ-006 | `except ImportError` con el comando de instalación | ✅ revisión |
| REQ-007 | `shutdown()` + `server_close()` en `finally` | ✅ revisión; el 9495 quedó libre tras las pruebas |

### Verificación al revés: un mutante por descuido posible

```
### MUTANTE 1: el SVG cambia y nadie regenera los PNG
  FAILED test_el_favicon_de_la_landing_es_el_mismo_del_dashboard
  FAILED test_los_png_se_generaron_con_el_favicon_svg_actual

### MUTANTE 2: un PNG se toca a mano (el sha del SVG cuadra igual)
  FAILED test_el_manifiesto_describe_los_png_que_hay_en_disco

### MUTANTE 3: el manifiesto olvida un icono
  FAILED test_el_manifiesto_describe_los_png_que_hay_en_disco
  FAILED test_el_manifiesto_cubre_todos_los_png_de_la_marca
```

**El mutante 2 es el que justifica registrar también el hash de cada PNG:** con solo el del SVG,
regenerar por fuera del script pasaría desapercibido.

**Y dejó una lección de método:** al restaurar el mutante 2 con `git checkout site/apple-touch-icon.png`
volvió el PNG **de `main`** —el viejo—, no el recién generado, y el repo quedó inconsistente. Lo
cazó el propio test que acababa de escribir, que es la mejor señal de que sirve. Se regeneró con
el script.

## Quality checks

- [x] `uv run pytest -q` → **655 passed, 1 skipped** (652 al empezar el change).
- [x] `uv run ruff check .` → `All checks passed!`
- [x] `uv run ruff format --check .` → `69 files already formatted`
- [x] Sin secretos.
- [x] Sin cambios ajenos.

## Deviations and residual risk

- **Los PNG regenerados no son byte a byte los anteriores** (1669→2116 y 424→488 bytes). Los
  originales se capturaron con otro navegador o versión; la marca es la misma y lo que cambia es
  la codificación. Se comprueba que siguen midiendo 180 y 32 y que la página los declara así.
- **El hash detecta «no salió de este SVG», no «dibuja otra cosa».** Regenerar con otro chromium
  producirá PNG distintos y habrá que commitearlos. Es ruido tolerable frente a meter un navegador
  en el CI, y queda escrito.
- **El script depende de playwright, que `uv sync` desinstala.** Falla con el comando de
  instalación en el mensaje, no con un `ImportError` crudo, pero es un tropiezo conocido del repo.
