# Evidencias — panel-coste-cuota-dashboard

El encargo creció en la misma tanda: tras las tres tarjetas de coste vinieron la unidad cortada del
KPI principal, las claves internas en las tablas, la simetría de la fila de KPIs, la tarjeta
Sistema, la flecha del selector de rango y la retirada del donut «Dónde corrió el cómputo».

## Cambios (`src/local_delegate/web/metrics.py` salvo que se diga)

### Coste, cuota e imágenes
- Coste: cifras «Cota baja», «Estimación» y «Tokens valorados» con las clases de los KPIs, más la
  tabla del desglose. La tabla sale de `valoracion.bloque_coste(rows, …)` con
  `rows = _load(range_from, range_to)`: cambia con el rango.
- Diálogo de información `#infoDlg` (patrón `dialog.help` de la ayuda «?»), con grupos de
  secciones (`data-group`): coste/cuota/imágenes y hooks. Cada tarjeta lleva un ⓘ (`.ibtn`); Esc
  lo cierra y el foco vuelve al botón. El texto de coste/cuota/imágenes sale de
  `textoCoste`/`textoCuota`/`textoImagenes`, las funciones que ya probaba node.
- Cuota: solo se pinta con al menos una ventana calibrada; por ventana, «A – B %» y un medidor de
  0 a 100 %. Imágenes: tres cifras; se oculta sin imágenes en el rango.
- Fila cuota+imágenes en `grid cols2` (16 px de hueco, como el resto).
- `color-scheme` según el tema: icono del calendario, lista del `<select>` y scroll en oscuro.

### KPIs
- La cifra del hero escala con su tarjeta (`container-type:inline-size`,
  `font-size:clamp(28px,13cqi,42px)`): «3.161.168 tok» ya no pierde la «k» entre 1320 y 1440 px.
- Simetría: bloque del título de 34 px en todas (ⓘ unido a la última palabra con `&nbsp;`), la
  cifra en una caja de 44 px apoyada abajo, la pista con dos líneas reservadas. La pista de
  «Delegaciones» es «N llamadas al backend»; «+N por trocear o saltar» y «N con salto» van al
  tooltip, igual que los «N estimados» de «Generado en local». Pistas cortas: «entrada leída por la
  GPU», «con la carga del modelo».
- Chart.js formatea ejes y tooltips con `locale='de-DE'` (punto de miles, coma decimal, como
  `fmtNum`); el centro del donut de origen del input dice «69 %» con espacio.

### Etiquetas legibles (mapa `LABELS` + `labelFor`, respaldo `humanLabel`)
Sitios cambiados: categorías de «Sugerencias de los hooks»; «Lecturas vistas» (motivos);
«Quién delegó» (clientes); columnas Hilo y Esfuerzo del desglose de coste; insignia de estado de
cada modelo del Backend (`loaded` → «Cargado», `unloaded` → «Sin cargar»); chip de origen de la
actividad («Local», «Remoto», «Sin dato»); motivos de descarte de la cuota en el diálogo
(`delta_pequeno` → «variación pequeña»…). El valor crudo queda en el `title` de la celda. Sin
cambiar: nombres de tools, modelos y procesos (nombres propios), y `path`/`inline` (término del
protocolo que el panel documenta: «path = ahorro real»).

### Sistema
- Fuera el «GPU N%» de la cabecera; nueva fila con barra «Carga de la GPU» entre RAM y VRAM, en
  violeta fijo (carga alta es trabajo, no aviso de memoria llena). Sin GPU (`vram` nulo) no hay
  fila, como la VRAM. CPU no se añade: `web/sysinfo.py` no la mide.
- Porcentajes de las barras con el formateador del panel y espacio antes de % («43 %»).
- Tabla de procesos con la tipografía de las demás (13 px celdas, 10,5 px cabeceras).

### Cuarta vuelta
- Línea del hero: 24 px de alto en la franja de abajo; ya no cruza «bruto … − devuelto …».
- Backend: estados de cada modelo con mayúscula («Frío», «Montado», «Procesando»; el valor
  interno no cambia), «Trozo 9/14», «13,4 s · 39.110 car.», «1.284 peticiones», «caché» y
  rótulos «Generación tok/s», «Entrada tok/s», «Tokens entrada/salida».
- Origen del input: leyenda «Por ruta (path)» / «Texto en línea (inline)», centro «por ruta» y
  cabecera «por ruta = ahorro real».
- Títulos de KPI en una línea a 1366 px: «Generado» (pista «salida de los modelos locales»),
  «Latencia», «Errores». La wiki nombra los KPIs nuevos.

### Otros
- `.btn:hover` usa `background-color`, no el atajo: la flecha del `<select>` ya no se va.
- Hooks: el párrafo «Los hooks sugieren…» pasa al diálogo, con otro que explica categorías y
  motivos.
- Fuera el donut «Dónde corrió el cómputo» (canvas, `drawOriginDonut`, su llamada); la fila queda
  en dos columnas. Los campos `backend`/`backend_host` no se tocan.
- `scripts/dev/capture_dashboard.py`: umbral de gráficos de 6 a 5 (se quitó un donut).
- `tests/test_hooks_telemetry_api.py`: extrae también `LABELS`/`humanLabel`/`labelFor`, espera
  «Shell» y busca la nota en el diálogo.
- `docs/wiki/Savings-and-metrics.md` y `CHANGELOG.md` (`[Unreleased]` → `Changed`, una línea).

## Verificación

- Tests del panel (`test_panel_estados`, `test_dashboard_js`, `test_metrics`, `test_captura`,
  `test_dashboard_ui`, `test_panel_coste`): `169 passed, 1 skipped, 1 warning in 25.80s`.
- Suite completa: `2259 passed, 2 skipped, 1 warning in 226.77s (0:03:46)` (base 2245).
- `uv run ruff check .` → `All checks passed!`; `uv run ruff format --check .` →
  `179 files already formatted`; `node --check` del `<script>` del panel: `exit=0`.
- Controles positivos (cada mutación, su test, fallo en el assert que toca):
  - fila en `grid duo` → `assert 0 == 16`; sin `color-scheme:dark` → `'normal' == 'dark'`;
  - CSS viejo del hero → «3.161.168tok: unidad cortada» a 1366 px;
  - `labelFor` devuelve la clave → lista con `read`, `clave_rara_nueva`…; respaldo crudo →
    `['clave_rara_nueva', 'motivo_que_no_existe', 'cliente_nuevo']`;
  - `.proc` a 12 px → tipografía distinta en `procTable`; nota otra vez en la tarjeta →
    `'sugieren' not in …`;
  - sin alto del título → `titulo: 26` frente a 34; tasa de error con punto → la tarjeta de error;
  - línea del hero a 52 px → `canvasTop 712 < textoBottom 729`; «Latencia media» → dos líneas;
    estado crudo → `['frío', …]`; «chars» y «req» → sus asserts; leyenda cruda → `['path']`;
  - `pct+'%'` → `'68 %' in 'CARGA DE LA GPU\n68%'`; `.btn:hover` con atajo → `'none' == 'linear-gradi…'`.
- Fin de línea: `metrics.py`, `test_dashboard_ui.py` y `CHANGELOG.md` en CRLF; wiki,
  `capture_dashboard.py` y `test_hooks_telemetry_api.py` en LF.
- Capturas (datos de ejemplo de `capture_dashboard.py`, app de métricas en el puerto 9487 con
  `LOG_DIR` temporal y backend en un puerto cerrado) en el scratchpad de la sesión: `antes-*`,
  `despues-*`, `despues2-*` (KPIs a tres anchos) y `despues3-*` (KPIs a 1280/1366/1440/400 px,
  hooks, clientes, Sistema, fila de donuts, actividad, selector en reposo y hover, diálogo de
  hooks, tarjetas de coste), en claro y oscuro.
