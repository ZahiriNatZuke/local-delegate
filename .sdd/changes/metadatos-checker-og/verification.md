# Verificación: cerrar los avisos del checker de OpenGraph en la landing

## Entorno

- Rama: `feat/iconos-manifest-y-datos-estructurados`, sobre `main` en `fcf462b`.
- Windows 11, Python 3.13 (`uv`), Playwright vía MCP para rasterizar, `python -m http.server` para
  servir `site/` (el navegador bloquea `file://`).

## Evidencia

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001 | Medida de las tres descripciones sobre el HTML | `description` 104, `og:description` **149** (era 213), `twitter:description` 149; las dos sociales son ahora **la misma cadena** |
| REQ-002 | Cabecera IHDR de cada PNG | `apple-touch-icon.png` 180×180 (1669 B), `favicon-32x32.png` 32×32 (424 B) |
| REQ-002 | Origen de los PNG | `icon.src.html` carga `favicon.svg` con `<img>`: los PNG son una rasterización del canónico, no otro dibujo |
| REQ-003 | Inspección visual del PNG de 180 | fondo `#0D1A1D` sólido hasta el borde, marca centrada al 68 % |
| REQ-004 | `twitter:site` y `twitter:creator` | ambos `@ZahiriNatZuke`, atados por test |
| REQ-005 | `json.loads` del bloque `application/ld+json` | parsea; `@type` = `SoftwareApplication`, `url` = la base del sitio |
| REQ-006 | Carga real en Chrome | manifest servido `200 application/manifest+json`, parseado **sin un solo aviso en consola**; sus tres iconos existen |
| REQ-007 | Búsqueda de `href`/`src` que empiecen por `/` | ninguna; test propio que lo vigila |
| REQ-008 | `softwareVersion` en el JSON-LD | `__LD_VERSION__`; lo sustituye `build_site.py`, que ahora también reconoce `.webmanifest` |

Comprobación de los cuatro recursos declarados, hecha con `fetch` desde la página ya cargada:

```
link[rel="manifest"]                    200 application/manifest+json  <- site.webmanifest
link[rel="apple-touch-icon"]            200 image/png                  <- apple-touch-icon.png
link[rel="icon"][type="image/png"]      200 image/png                  <- favicon-32x32.png
link[rel="icon"][type="image/svg+xml"]  200 image/svg+xml              <- favicon.svg
```

### Los tests, verificados al revés

Un test que no falla con el defecto puesto no prueba nada. Se metió cada defecto a mano y se
comprobó que su test lo caza; los seis fueron cazados:

| Defecto inyectado | Test que lo cazó |
| --- | --- |
| `sizes="181x181"` con el PNG de 180 | `..._miden_lo_que_declara_la_pagina` |
| `href="/favicon-32x32.png"` (la ruta absoluta del informe) | `..._ninguna_ruta_de_la_pagina_es_absoluta` |
| la `og:description` de 213 otra vez | `..._descripciones_sociales_caben...` |
| `twitter:creator` con otra cuenta | `..._declara_la_cuenta_de_x` |
| `"softwareVersion": "0.16.0"` escrita a mano | `..._datos_estructurados...` |
| manifest apuntando a un PNG que no existe | `..._manifest_es_json_valido...` |

## Comprobaciones de calidad

- [x] `uv run pytest -q` → **386 pasan**, 1 skip (eran 380 en `main`).
- [x] `uv run ruff check .` sin hallazgos; `uv run ruff format --check .` con 52 ficheros ya
      formateados.
- [x] `scripts/extract_dashboard_js.py` + `node --check` → OK.
- [x] Secretos: el hook de pre-commit pasa; aquí no hay credenciales de nada.
- [x] Sin cambios ajenos: el diff toca `site/`, `tests/test_site.py`, `scripts/build_site.py` y el
      `CHANGELOG`.

## Desviaciones y riesgo residual

- **Los PNG pueden quedarse viejos.** Derivan del SVG, y nada obliga a regenerarlos si alguien
  cambia la marca. El procedimiento va escrito dentro de `icon.src.html`, igual que se hizo con
  `og-image.png`; atarlo de verdad exigiría rasterizar dentro del CI.
- **Pendiente de comprobar tras el despliegue:** el `Content-Type` de `site.webmanifest` en
  GitHub Pages. En local sale `application/manifest+json`; si allí no fuera JSON, el fichero pasa
  a llamarse `manifest.json`.
- **Pendiente:** volver a pasar el checker. Deben quedar cerrados los seis avisos reales y seguir
  abierto solo el del `canonical`, que es su falso positivo documentado.
