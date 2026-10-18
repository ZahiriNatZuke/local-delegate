# Nota de backlog (pasada en vivo de la 0.36.0 candidata, 2026-10-18)

Para `projects/local-delegate/backlog.md` del vault. Ninguno bloquea la 0.36.0.

1. **`local_lint_summary` en español todavía inventa alguna cifra.** Con el mismo log de `ruff`
   (`--select ALL` sobre `sections.py`, 14 237 caracteres, rol largo en llamada única), el resumen
   en inglés dio las 15 cifras exactas y el español dos mal (D101 6 en vez de 5, D400 4 en vez de
   3). Todos los códigos nombrados en los dos idiomas (B2f cumple). Es el residuo ya medido en
   B2d-3 (media 3,67 por tanda). Siguiente palanca posible: dar por programa el recuento por
   código en el inventario de la llamada única (hoy va «sin recuentos» a propósito, para no
   arrastrar cifras al troceado); medir antes con `--repeat 3` y el juez de fidelidad.
2. **Guardián del detector de nombres (REQ-016) en la suite.** Hasta el cierre no había test que
   corriera el detector sobre el árbol: entre B2d-3 y B5 entraron 23 hallazgos (falsos positivos
   del léxico y numerales españoles de `score_lint_fidelity.py`) que solo se vieron al cerrar.
   Se arregló en la rama de release (`test_repo_has_no_spanish_name_outside_the_exception_list`).
   Queda decidir si, cuando se archive la carpeta del cambio, la lista de excepciones se muda a
   `scripts/data/` para que el guardián no se salte.
3. **RAM entre llamadas con el 35B o el 26B cargados:** 0,4–1,4 GB libres mientras el modelo
   espera su TTL, con la PC en uso normal. Las llamadas no bajaron de 1,5 GB, pero una corrida
   larga con otra app pesada abierta puede rozar el OOM (memoria «config para máquina
   compartida»).
