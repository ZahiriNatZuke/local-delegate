# F4-desktop-spacing — separación y recorte de la banda en Claude Desktop

Lote para la 0.41.1. Dos defectos vistos en vivo el 2026-10-23 (capturas 17 y 18 de la sesión):
textos casi pegados en Desktop, y la banda perdía las cifras y el modo de lectura mientras delegaba.

## Qué ancho recibe Desktop (deducido del motor, sin medir en vivo)

- En la terminal, `AbovePrompt` recibe `bodyColumns = columnas de la terminal − 5` (motor 2.1.308/309).
- Desktop no pasa por ahí: manda una petición `ui_render` con sus propios `props` («the component's
  plain-data props as the asking surface holds them») y un `viewport` cuyo ancho el esquema del motor
  define en **celdas de la fuente monoespaciada** de la superficie («its width ... over the code
  font's advance»). El código de Desktop que rellena `props.bodyColumns` vive en el cliente web, no en
  `app.asar` ni en el motor, así que su valor exacto no se pudo leer.
- La captura acota el valor: el recorte viejo (1 carácter = 1 celda) dejó la tarea y el modelo
  (78 celdas) y quitó las delegaciones (96), así que `78 ≤ bodyColumns < 96`. La banda mide unos
  766 px y la letra proporcional unos 6,1 px por carácter (478 px para 78 caracteres): la celda mide
  entre 8 y 9,8 px y un carácter ocupa entre 0,63 y 0,77 celdas.
- Conclusión: el recorte contaba de más. Factor elegido: **0,75 celdas por carácter** (borde alto del
  intervalo, prudente) y 1 celda para el espacio ancho. Con 96 celdas caben delegaciones y tokens; con
  100, también el coste; con ~120, el modo de lectura. El contenido completo de la captura (≈930 px)
  no cabía de verdad en 766 px, así que el modo de lectura se va primero, como su rango manda. Lo que
  sobre lo corta `truncate-end`, en una sola fila.

## Separadores

- `·` entre dos U+2002 (espacio de medio cuadratín): ancho fijo de 0,5 em sea cual sea el espacio de
  la fuente, y CSS no lo colapsa (solo colapsa espacio, tabulador y saltos), así que sobrevive en el
  borde de un `Text` anidado. U+2009 se descartó: es más estrecho que el espacio normal.
- Punto de estado y palabra, y verbo y tool: U+00A0 (mismo ancho que un espacio, no se parte).
- Dos tonos: mientras delega, «Delegando» atenuado (el punto que gira ya lo dice) y la tool en color
  normal. Sin tool, el verbo sigue en color normal.
- La terminal no cambia: sus tests no se tocaron.

## Tests (antes del cambio fallaban 5, por la razón que dicen)

- `desktop: each state` — «Delegando» no estaba atenuado (`undefined` en vez de `true`).
- `desktop: a narrow band drops ...` — con 45 celdas el recorte viejo quitaba las delegaciones.
- `desktop: the separators are wide spaces ...` — el texto tenía ` · ` con espacios normales.
- `desktop: delegating in a band of about 100 cells keeps the figures` — faltaban tokens y coste.
- `desktop: with room for it, the read mode stays on the right ...` — faltaban coste y lado derecho.

Después: `claude plugin test` 120 pass, 0 fail; pytest del mod (38) y `ruff` en verde.

## Pendiente para la prueba en vivo

- Ver en Desktop que el `·` respira y que, delegando, salen las cifras sin partirse en dos filas.
- Si Desktop resultara mandar en `bodyColumns` otra cosa que celdas monoespaciadas, recalibrar
  `STATUS_DESKTOP_CELL` con una captura nueva.
