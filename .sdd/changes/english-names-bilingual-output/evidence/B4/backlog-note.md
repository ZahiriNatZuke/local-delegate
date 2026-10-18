# Nota de backlog (B4)

- **Los datos de ejemplo de `scripts/dev/capture_dashboard.py` llevan prosa en español**
  (`reason: 'faltan 2 puntos del statusline'` en el mock de la cuota). Con el panel en inglés, el
  diálogo de la cuota de la captura enseña esa frase en español (se ve en
  `evidence/B4/screenshots/dialog-cost-en-*.png`). Con el servidor de verdad no pasa: el motivo lo
  redacta `quota.status` en el idioma del `?lang=`. Arreglo propuesto: que el mock pida `/api/stats`
  real para la cuota, o que redacte el motivo con el catálogo del idioma de la captura.
- **Humo del panel contra el daemon instalado (pendiente tras mezclar):** abrir
  `http://127.0.0.1:9393/` en un navegador en inglés y en otro en español, comprobar el selector,
  que los roles y la causa del backend salen en el idioma del visitante y que «Procesos del
  backend» lista solo el `llama-swap` de `:9292` mientras corre la suite con `fake_llamaswap`.
