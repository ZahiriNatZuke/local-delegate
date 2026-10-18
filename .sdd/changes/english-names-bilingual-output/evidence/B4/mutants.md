# B4 — controles positivos y mutantes

Cada mutante se aplicó con una sustitución exacta, se corrieron sus tests y se deshizo el cambio
(guion `mutate.py` de la sesión, fuera del repo). Se anota **qué assert salta**, no solo que falla.

| # | Mutante | Tests | Qué salta |
|---|---|---|---|
| 1 | `is_backend_llamaswap` devuelve siempre `True` (antes de leer la línea de órdenes) | `test_the_backend_processes_leave_out_the_test_llamaswaps`, `test_a_real_test_llamaswap_is_not_listed` | unitario: `assert 202 not in [..., 202, 204, ...]`; real: la guarda «la línea de órdenes del llama-swap de prueba llegó a leerse» (el mutante ya no la pide) |
| 1b | `is_backend_llamaswap` ignora el puerto (`return True` en la comparación) | los mismos | unitario: `assert 202 not in [...]`; real: `assert 11480 not in {…, 1688: 'llama-swap.exe', 11480: 'llama-swap.exe'}` — el llama-swap de prueba (11480) aparece junto al real (1688) |
| 2 | `_probe_detail` devuelve `probe.detail` tal cual | `test_api_backend_writes_the_cause_in_the_visitor_language`, `test_api_backend_rewords_an_http_status_cause` | `'fallo de red con test-backend (ConnectError)' == 'network failure with test-backend (ConnectError)'` y `'test-backend responde HTTP 500' == 'test-backend answers HTTP 500'` |
| 3 | «Latencia» sin traducir en el catálogo inglés (`panel.kpi.latency.label`) | `test_one_word_left_in_spanish_is_caught_in_the_english_DOM` (test permanente: el mutante es el propio test) | `_spanish_leftovers(texts) == ['Latencia']` |
| 4 | `lbl:'Latencia'` literal en el JS en vez de `T('kpi.latency.label')` | `test_the_real_panel_with_one_word_left_untranslated_is_caught`, `test_the_panel_template_is_scanned_through_scan_source` (permanentes) | `scan_panel` y `scan_source` devuelven exactamente `['Latencia']`, en la línea del KPI |
| 5 | Navegador en `en-US` sin el `locale` del fixture | `test_without_the_spanish_locale_the_spanish_asserts_fail` (permanente) | `"Contexto conservado" not in kpi`, `"Pruebas" not in bar` y la primera etiqueta es `Context kept` |
| 6 | Escáner del panel contra la plantilla de `main` (`db384c3`) | ejecución puntual | 371 apariciones de texto fuera del catálogo en `metrics.py` (Python y plantilla); con la de la rama, 0 |

Controles de «esto llegó a comprobar algo» dentro de los tests:

- dos visitantes: el panel inglés tiene ≥ 150 textos leídos y el español da ≥ 40 restos españoles
  con la misma comprobación (la comprobación discrimina);
- el selector: el badge inglés y el español del mismo `cause` son distintos antes de comparar;
- `localStorage` bloqueado: se comprueba que de verdad estaba bloqueado (`localStorage` lanza);
- el escáner sintético: 7 plantillas que deben saltar y 7 que no (comentarios, regex con comillas,
  claves del catálogo, clases CSS en arrays).
