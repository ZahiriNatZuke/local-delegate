# F4-band — banda de estado con diseño propio por superficie y refresco en vivo

Lote: rama `feat/plugin-band` (worktree `D:/Projects/ld-wt-band`), sobre `main` en `dc2e018`
(0.41.0). Va a la 0.41.1.

## Qué cambia

- `mod/status.js`: tres árboles según `e.surface` y `status_style`:
  - terminal, `bar` (por defecto): una fila, `Box row space-between backgroundColor:'userMessageBackground' paddingX:1 width:'100%'`;
    chip `Text inverse bold color:<estado>` (` ● LISTO `, ` ◐ DELEGANDO `, ` ○ CAÍDO `, ` ◌ SIN DATOS ` con `dimColor`, ` ○ SIN SERVICIO `);
  - terminal, `line`: raya `─` atenuada + la línea, dos filas, sin fila vacía entre ellas;
  - otra superficie (Desktop): una fila con `Link href:'http://localhost:9393'`, píldora `borderStyle:'round'`, tool `mono`, cifras `weight:'semibold' tabular`, lecturas `size:'caption'`.
- Refresco: `$.clock.every` a 1 s con delegaciones en curso o un modelo cargando (`running[].state !== 'ready'`), a 30 s si no; solo `/api/backend` y `/api/inflight`; las cifras de la sesión al acabar la última delegación. Un hook `tool.call` con matcher `/^mcp__local-delegate__/` pone el ritmo rápido al empezar la llamada y refresca todo al acabar. `session.end` para el temporizador. Solo se invalida la banda si el snapshot cambió.
- Tool en curso: `/api/inflight` sí trae `tool` y `elapsed_s` por entrada (`server.inflight_snapshot`); se muestra la más antigua, sus segundos y `+N`. El punto gira ◐◓◑◒ con `floor(elapsed_s) % 4`: no cuesta redibujos aparte, porque los segundos ya cambian en cada latido.
- Modo de lectura con `hasDialog()` de `common.js` (importado, sin tocarlo).
- `plugin.json`: opción `status_style` (`options: ["bar","line"]`, `default: "bar"`).
- `tests/test_mod_static.py`: el control de «solo loopback» admite `http://localhost:9393` solo en `status.js` y solo como `href` del `Link` (se comprueba que no va a `daemonFetch`).

## Las filas vacías (pedido del usuario)

- Arriba: eran nuestras (`marginTop:1` en la fila de la línea). Fuera en las dos variantes.
- Debajo: **no es nuestra**. El árbol del mod no tiene `marginBottom`/`paddingBottom` (lo vigila `expectNoEmptyRows` en los tests), y el contenedor del motor tampoco: en `claude.exe` 2.1.309, `AbovePromptSite` (`zb.AbovePromptSite`) dibuja `Box{flexDirection:"column",flexShrink:0,maxHeight,overflowY:"hidden"}` con nuestro árbol, la `OverflowCue` si hay desplazamiento y el `CollapseHandle` («[-]», en posición absoluta arriba a la derecha), sin margen. La banda va en un fragmento junto a otros elementos del motor (`D4`: encuesta, banda, `iwe`, `w4`, `Gtt`) antes del prompt; la fila que queda entre la banda y el borde del prompt sale de ahí o del propio prompt, no del mod. No se puede quitar desde el plugin.

## Pruebas

- `claude plugin test` (CLI 2.1.309): 101 pass, 0 fail (los 5 ficheros).
- Rojo antes del cambio: con los tests nuevos y el `status.js` viejo, 25 fallos; los de refresco fallan porque el reloj no pide nada (`Expected ["/api/backend","/api/inflight"] Received []`, `Expected 5 Received 3`).
- Mutantes (cada uno rompe el test que dice): `marginTop:1` en la barra o en la línea → `expectNoEmptyRows`; invalidar siempre → «redraws only when something changed» (`Expected 1 Received 2`); ritmo rápido = lento → 6 tests de refresco; no parar en `session.end` → «timer stops» (`Expected 5 Received 125`); ignorar `hasDialog` → «read mode follows»; sin arranque en `tool.call` → «a call to a local-delegate tool».
- `claude plugin validate --strict` en los tres destinos: sin errores ni avisos.
- pytest (`-n 2`): `test_mod_static`, `test_mod_i18n_parity`, `test_build_hook`, `test_plugin_package`, `test_bump_version`: 38 pass.

## Queda para la prueba en vivo

- Warp: que el fondo `userMessageBackground` llegue al ancho entero y contraste en tema claro y oscuro, que el chip `inverse` se lea, y que no parpadee con el refresco de 1 s.
- Desktop: que `e.surface` de la pestaña Code sea `desktop`, que se dibuje el borde redondeado de la píldora, que el `Link` abra fuera de la app y que el panel responda en `http://localhost:9393` (en Windows `localhost` puede resolver primero a `::1`, y el control de `Host` del daemon no debe rechazarlo).
- Que el temporizador creado desde `session.measure`/`tool.call` siga vivo tras acabar ese despacho (en el kit de pruebas sí).
- Que el modelo y la tool aparezcan durante la delegación, no al acabar el turno.
