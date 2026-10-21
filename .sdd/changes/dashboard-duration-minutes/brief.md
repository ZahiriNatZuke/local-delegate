# Brief — SDD ligero `dashboard-duration-minutes`

## Objetivo

Pedido del usuario el 2026-10-21, con captura: en el panel (`http://127.0.0.1:9393`) el tiempo de
una delegación larga sale solo en segundos («947.2 s» en la tarea en curso). Debe manejar minutos
(y horas). Pasa en el indicador de la tarea en curso y en el listado de delegaciones. Entra en la
0.38.0.

Causa: una sola función JS dentro de `src/local_delegate/web/metrics.py`, `fmtSec(ms)` (~línea
1869), que usan la tarea en curso (~2686), los eventos de hooks (~2700), la tarjeta KPI de latencia
(~2988), el desglose espera/inferencia (~3120) y la tabla de actividad (~3225). Tests en
`tests/test_dashboard_js.py` (~401–490; ejecutan la definición real con node).

## Formato decidido (sesión principal)

- `< 50 ms` → «< 0,1 s» (como hoy). Menos de 60 s → un decimal, como hoy («45,3 s» / «45.3 s»).
- De 60 s a menos de 1 h → minutos y segundos enteros: «15 min 47 s». Segundos 0 → «2 min 0 s»
  no: «2 min».
- 1 h o más → horas y minutos: «1 h 5 min» (minutos 0 → «1 h»).
- Unidades iguales en es y en (`s`, `min`, `h`); el separador decimal sigue el idioma, como hoy.
- Redondeo coherente: 59,96 s no puede salir «60,0 s» ni «0 min 60 s» (frontera exacta en el test).
- Un solo formateador para todos los sitios: también cambia la tarjeta de latencia y el desglose.
  Donde hoy hay `title` con el valor, que conserve los segundos exactos.

## Reglas

- Usa las `local_*` del MCP `local-delegate` donde ahorren contexto (resumir ficheros grandes con
  `path`, salida de tests con `local_lint_summary`, borrador de commit) y lista las llamadas.
- Código y comentarios nuevos en inglés; textos al usuario por el catálogo i18n si hiciera falta
  alguno nuevo (aquí no debería: las unidades son símbolos).
- El panel es un dashboard: nada de prosa nueva. Verifica con **capturas en claro y en oscuro**
  (el tema se cambia con su botón; `localStorage` `ld-theme`), con datos sembrados en un `LOG_DIR`
  temporal y la app de métricas servida aparte en otro puerto (p. ej. `:9494`, ver
  `docs/wiki/Publishing.md` «Captura contra el repo»), nunca contra el daemon del 9393. Incluye una
  delegación en curso de > 15 min y filas de > 1 min y > 1 h.
- Comandos pesados (suite, navegador headless) con `bash ~/.claude/scripts/pesado.sh …` desde la
  tool Bash; pytest `-n 2`. Hay otro agente trabajando en paralelo en la documentación (otro SDD):
  no toques `CHANGELOG.md` salvo una línea en `[Unreleased]` › «Corrige», ni `README.md` ni
  `docs/wiki/` (si chocáis en `CHANGELOG.md`, rebasa y junta).
- `metrics.py`: comprueba su fin de línea con `git ls-files --eol`. Commits firmados SIN coautoría
  de Claude. CodeQL a 0 incluido `note`. No toques el daemon ni `~/.claude`.
- Nada huérfano: para el servidor de métricas y el navegador al acabar; esperas con tope.
