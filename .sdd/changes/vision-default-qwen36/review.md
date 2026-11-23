# Result review: Modelo de visión por defecto: qwen36-35b-a3b-vision

## Review level

- Level: standard
- Judges: result-reviewer-1, autor-agente-vision
- Security reviewer: no — sin superficie nueva de entrada ni de red; el texto nuevo del panel pasa por `escHooks`
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | config.py, test_vision_default.py |
| REQ-002 | yes | yes | test añadido para quien ya fijó la ligera (H3) |
| REQ-003 | yes | yes | `:latest` y catálogo vacío arreglados (H1, H2) |
| REQ-004 | yes | yes | capturas claro/oscuro en evidence/ |
| REQ-005 | yes | yes | `.env.example` y receta Blackwell corregidos (H5) |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| H1 | El panel marcaba «sin rol» un modelo con rol listado como `id:latest` (Ollama) | yes | yes | confirmed | `roleLabels` aplica la regla de `_is_served`; test nuevo |
| H2 | Sin catálogo (antes de `/api/status`) todas las filas decían «sin rol» | yes | yes | confirmed | sin catálogo no se pone etiqueta; test nuevo |
| H3 | Faltaba test del caso «visión ya es la ligera» | yes | yes | confirmed | test añadido |
| H4 | Un modelo de visión propio no servido también recibe `warn` si se sirve la ligera | yes | yes | confirmed | aceptado: es lo que pide la spec y el remedio funciona |
| H5 | `.env.example` con el defecto viejo; receta decía que `init-llamaswap` genera el catálogo | yes | yes | confirmed | corregidos |
| H6 | `_frozen_models` renombra por id, no por rol; `production_config` se congela sin aviso | yes | yes | confirmed | aceptado: id único; los casos sí avisan, y un test de control prueba que sin la frontera vuelve a ser error |
| H7 | El remedio combinado no decía de qué modelo hablaba | yes | yes | confirmed | texto: «el modelo de visión» |

## Required follow-up

- Prueba contra el backend real pendiente (no se reinicia el daemon en este encargo).
