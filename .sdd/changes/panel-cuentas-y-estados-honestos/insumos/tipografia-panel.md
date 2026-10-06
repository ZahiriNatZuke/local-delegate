# Auditoría tipográfica del panel web (local-delegate 0.32.0)

Fichero único del panel: `src/local_delegate/web/metrics.py` (HTML, CSS y JS en la constante `HTML`, líneas 799-1955). No hay `.html`/`.css`/`.js` sueltos; el único JS aparte es `resources/vendor/chart.umd.min.js`.

## Cómo se midió (y una limitación)

- **No se pudo abrir el panel vivo de 9393**: pide token (`LOCAL_DELEGATE_WEB_TOKEN`) y el clasificador de permisos bloqueó tanto materializar el token como levantar una copia sin token en otro puerto. No se insistió.
- En su lugar: se generó el HTML con el propio `render_index()` del repo (mismo código que la 0.32.0; `metrics.py` no cambia desde el release) y se sirvió en Playwright con `page.route`, con Chart.js del paquete, las fuentes reales de Google y **datos simulados** para todas las `/api/*`. Así se pudo forzar lo que con datos reales no sale: la tarjeta de sugerencias de hooks, «Quién delegó», una delegación en curso con troceo y salto, la paginación y todos los estados vacíos.
- Un `browser_evaluate` recorrió todos los elementos visibles con texto propio (más `button`, `select`, `option` e `input`) y los agrupó por `getComputedStyle().fontFamily`, peso y tamaño. Se repitió con el selector de rango en «Personalizado», el tooltip ⓘ, el diálogo «?» abierto, todo vacío y en tema claro.
- No quedó **ningún texto con la fuente por defecto del navegador**: todo cae en Inter o JetBrains Mono. El problema no es de fallback, sino de **rol**: textos con el mismo papel salen en familias distintas.
- No verificado: que el paquete instalado en `uv tool` sea idéntico byte a byte al del repo (también bloqueado). La captura del usuario cuadra con este código.

## 1. Sistema tipográfico

Dos variables, definidas en `metrics.py:821-822`; el tema claro (`824-830`) solo cambia colores (comprobado: 0 diferencias de familia al cambiar de tema).

| Variable | Pila | Rol que cumple en la práctica |
|---|---|---|
| `--sans` | `'Inter', system-ui, 'Segoe UI', Roboto, sans-serif` | Base del `body` (`833`). Títulos de tarjeta (`h2`, `h3`), etiquetas en versalitas (`.k-lbl`, `.subh`, `.meter-lbl`, `.bk`, `thead th`, `.brand-sub`), chips de estado o categoría con texto fijo (`.pill`, `.live`, `.mrole`, `.mstatus`, `.src`, `.org`), prosa (`.k-hint`, `.help-in p`, `.tt`) y controles (`.btn` `874`, `.pbtn` `1027`). |
| `--mono` | `'JetBrains Mono', ui-monospace, 'Cascadia Code', Consolas, monospace` | Cifras (`.num` `843`, `td.mono` `948`, `.bv`, `.meter-val`), identificadores (`.mname`, `.badge` tool/modelo, `.tchip`, `.ver`, `.chunkchip`, nombre de proceso), metadatos técnicos (`.panel-h .mut` `934`, `footer` `1061`, `.pinfo`, `.frm`) y estados vacíos (`.empty` `1058`, decidido a propósito según el comentario de `1054-1057`). |

En los gráficos (canvas): por defecto Inter (`applyDefaults`, `1253`); ejes, tooltips y la cifra central en mono (`1265-1266`, `1246`, `1791-1794`, `1818-1819`); leyendas y subtítulo del donut en Inter (`1247`, `1790`, `1846`, `1864`). Es coherente con el DOM.

**Regla implícita**: las etiquetas y la prosa van en Inter; los datos (cifras, ids, rutas) van en mono.

## 2. Desviaciones encontradas

| # | Elemento / sección | Fuente actual | Debería | Causa (`fichero:línea`) |
|---|---|---|---|---|
| 1 | **Chip «DAEMON MCP»** (Sistema › Procesos del backend) | JetBrains Mono 700/9,5px | Inter, igual que sus gemelos `.mrole` «MECÁNICO» y `.mstatus` «UNLOADED» (mismo 9,5px/700/versalitas) | `.selfchip` no declara familia (`metrics.py:1021-1022`) y hereda la mono que el JS pone *inline* a la celda: `<td style="font-family:var(--mono)">` (`metrics.py:1634`) |
| 2 | **Fila vacía «Ningún proceso del backend detectado.»** (Procesos del backend) | Inter 400/12px | Mono, como los otros 8 estados vacíos del panel (todos `.empty` o `.ifrow`/`.tchip` en mono) | La `<td>` se escribe sin clase ni familia (`metrics.py:1631`) y hereda Inter del `body` |
| 3 | **Cabeceras de columnas numéricas**: «SUGERIDAS / VISTAS / TASA» y «EVENTOS / REPARTO» (Sugerencias de los hooks); «DELEGACIONES / LLAMADAS AL BACKEND / TOKENS AHORRADOS / REPARTO» (Quién delegó); «CHARS IN→OUT / LATENCIA» (Actividad reciente) | JetBrains Mono 700/10,5px | Inter, como el resto de cabeceras: «CATEGORÍA», «LECTURAS VISTAS», «CLIENTE», «HORA», «TOOL» y **toda** la cabecera de Procesos (PROCESO/PID/RAM/VRAM) | La utilidad de cifras `.num` (`metrics.py:843`) y `th.mono` (`metrics.py:948`) se aplican a `<th>`: el JS genera `<th class="num">` (`1377-1379`, `1419-1420`, `1431-1432`) y `<th class="mono">` (`1878`). `.num` (especificidad 0,1,0) gana a `thead th` (0,0,2, línea `944`). Resultado: **una misma fila de cabecera mezcla dos familias**, y Procesos no se parece a Hooks |
| 4 | **Nota explicativa de la tarjeta de hooks** («Los hooks *sugieren*; delegar lo decides tú…») | JetBrains Mono 400/12,5px | Inter (es prosa, igual que `.k-hint`, `.help-in p` y el tooltip) | Reutiliza la clase de estado vacío: `<div class="empty" style="…text-align:left">` (`metrics.py:1435`), y `.empty` es mono (`1058-1059`) |
| 5 | **Primera columna de «Sugerencias de los hooks» y «Quién delegó»** (categoría `read`, motivo, cliente `claude-code`) | Inter 400/13px | Mono (decisión de criterio): son identificadores que escribe la telemetría, como `python.exe`, los nombres de modelo o las tools, que sí van en mono | `<td>` sin clase en `metrics.py:1368`, `1406` y `1423`; en cambio Procesos (`1634`) y Actividad (`1887`) sí la marcan |
| 6 | **Peso 400 de JetBrains Mono no se descarga** (afecta a todas las cifras y textos mono de peso normal: celdas `td.mono`, `.bsub`, `.mstate`, `.tchip`, `.empty`, `footer`, `.frm`, `.ifrow`) | Se pide 400 y se pinta la cara 500 (comprobado en `document.fonts`: solo hay JetBrains Mono 500/600/700) | JetBrains Mono 400 de verdad | La URL de Google Fonts pide `JetBrains+Mono:wght@500;600;700` (`metrics.py:758`); falta el 400 |
| 7 | Botón de cerrar del diálogo de ayuda (`.help-x`) | Arial 13,3px (fuente por defecto de `<button>`) | Inter | `.help-x` no declara familia (`metrics.py:1044-1045`). **Latente**: hoy solo contiene un SVG, así que no se ve |
| 8 | Inputs de fecha del rango «Personalizado» | Inter 600/13px | Inter vale (son controles, igual que `.btn`); si se quiere tratar la fecha como dato, mono. Menor | `.btn` en `metrics.py:874` |

Revisado y **correcto**: la barra superior, el selector de rango y sus `<option>` (heredan Inter de `.btn`), los botones Auto/Refrescar/Tema/Ayuda y la paginación, los KPI (cifra mono, etiqueta y pista en Inter), el panel Backend (nombres de modelo en mono, roles y estado en Inter), «En curso» con troceo y salto, la tabla de actividad (salvo la cabecera, punto 3), el diálogo de ayuda, los tooltips ⓘ, el pie, los estados vacíos (salvo el punto 2), el tema claro y los gráficos.

Riesgo sin comprobar en vivo: los gráficos de canvas se dibujan sin esperar a `document.fonts.ready`. Si Inter o JetBrains Mono tardan en llegar, el primer dibujo usa el fallback (Consolas, Segoe UI) hasta el siguiente auto-refresco (15 s). En la prueba ya estaban cargadas, así que no se observó.

## 3. Causa común y arreglo mínimo

**Causa común**: la familia no la fija el **rol** del texto, sino la clase que el componente tenga a mano. Hay tres variantes del mismo fallo:
- una utilidad pensada para cifras (`.num`, `.mono`) que se aplica también a etiquetas (`<th>`);
- elementos sin familia propia que heredan la del contenedor, y el contenedor la tiene por otro motivo (la `td` mono *inline* arrastra al chip; la `td` vacía sin clase cae en Inter);
- una clase reutilizada fuera de su rol (`.empty` usada para prosa).

No son los controles de formulario: `.btn` y `.pbtn` ya fijan Inter. El único que no lo hace, `.help-x`, no tiene texto.

**Arreglo mínimo propuesto** (todo en `src/local_delegate/web/metrics.py`):

1. **Cabeceras siempre en Inter**: tras la línea 948 añadir `thead th.num, thead th.mono{font-family:var(--sans)}` (especificidad 0,1,2, gana a `.num`). Alternativa más limpia: quitar `class="num"` / `class="mono"` de los `<th>` en `1377-1379`, `1419-1420`, `1431-1432` y `1878`, y `th.mono` del selector de `948`.
2. **Chip DAEMON MCP**: añadir `font-family:var(--sans);text-transform:uppercase` a `.selfchip` (`1021`). Mejor aún, cambiar la `td` de `1634` a `<td class="mono">` y quitar el estilo *inline*.
3. **Fila vacía de procesos** (`1631`): `<td class="mono" …>` o reutilizar `.empty`, para que sea mono como los demás estados vacíos.
4. **Nota de hooks** (`1435`): sacarla de `.empty`, con una clase de nota en Inter (p. ej. `.note{color:var(--mut);font-size:12.5px;padding:10px 12px}`) o, como mínimo, añadir `font-family:var(--sans)` a su estilo *inline*.
5. **(Criterio)** Identificadores de la telemetría en mono: `<td class="mono">` en `1368`, `1406` y `1423`.
6. **Fuente**: pedir `JetBrains+Mono:wght@400;500;600;700` en `758`.
7. **Red de seguridad** para que no vuelva a pasar con controles: tras `*{box-sizing:border-box}` (`831`), `button,input,select,textarea{font-family:inherit}`. Esto cubre `.help-x` y cualquier botón futuro sin clase.
8. (Opcional) Volver a pintar los gráficos con `document.fonts.ready.then(render)` para evitar el primer dibujo con la fuente de reserva.

Guardián sugerido para el test: el `browser_evaluate` de esta auditoría convertido en un test de Playwright que falle si un `th` tiene distinta familia que otro `th`, o si un `.selfchip`, `.mrole`, `.mstatus` o `.pill` no comparten familia.
