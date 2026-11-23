# Brief: Modelo de visión por defecto: qwen36-35b-a3b-vision

## Problem

`gemma4-12b`, el modelo de visión por defecto, inventó 5 de 9 defectos de layout en la medición
de #699; un modelo del backend sin rol sale en el panel sin etiqueta y parece un error.

## Desired outcome

Visión por defecto `qwen36-35b-a3b-vision`, `gemma4-12b` como alternativa ligera documentada,
`doctor` con el remedio de migración y etiqueta «SIN ROL» en el panel.

## In scope

- config, doctor, panel, documentación, CHANGELOG y tests (ver `spec.md`).
- Fuera: `lint_patterns.py` y `sections.py` (otro PR de la 0.54.1), la config de llama-swap.

## Log

- L1 2026-11-23 Original request, verbatim:

  > 0.54.1: el rol vision pasa por defecto a qwen36-35b-a3b-vision (mmproj), gemma4-12b queda como alternativa ligera documentada; doctor avisa con el remedio si el backend no sirve el modelo de vision; el panel marca SIN ROL / NO ROLE los modelos del catalogo que no sirven a ningun rol. Medicion en #699.
- L2 2026-11-23 15:31 (UTC-3) Spec y plan escritos tras localizar los sitios.
