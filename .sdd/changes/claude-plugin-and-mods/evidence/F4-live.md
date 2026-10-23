# F4-live — Sobrecarga del mod de lectura en las llamadas `Bash`

Windows 11, Claude Code 2.1.309, 0.40.0 instalada con el código de `main` en `77f4a07` (sin
reinstalar ni reiniciar el daemon). Ventana de prueba `w-20261022T235744Z`
(23:57:44Z–00:02:26Z), abierta antes de la primera corrida y cerrada al final.

## Criterio (el de F2-live, fijado antes de medir)

mediana(con) − mediana(sin) ≤ **+150 ms** **y** p95(con) − p95(sin) ≤ **+300 ms**, sobre las llamadas
`Bash` en caliente (la primera de cada sesión se descarta y se informa aparte). 3 repeticiones,
cada una con 2 sesiones por brazo intercaladas (con, sin, con, sin).

## Veredicto: NO CUMPLE

| Llamadas en caliente | n por brazo | Mediana con | Mediana sin | Δ mediana (tope +150) | p95 con | p95 sin | Δ p95 (tope +300) |
|---|---|---|---|---|---|---|---|
| **Total** | 60 | 1313,5 ms | 910 ms | **+403,5 ms** ✗ | 1841 ms | 1062 ms | **+779 ms** ✗ |
| Pasan el filtro (van a `classify`) | 30 | 1628,5 ms | 904,5 ms | **+724 ms** ✗ | 1865 ms | 1025 ms | **+840 ms** ✗ |
| No pasan el filtro | 30 | 900 ms | 913,5 ms | −13,5 ms ✓ | 985 ms | 1139 ms | −154 ms ✓ |
| Primera llamada de la sesión (aparte) | 6 | 1674,5 ms | 1659 ms | +15,5 ms | 1769 ms | 1812 ms | −43 ms |

La sobrecarga está entera en las llamadas que llegan a `hook classify` (unos +720 ms cada una);
el filtro barato no cuesta nada medible.

## Dónde se va el tiempo

- `classify` se lanza como `python -I -m local_delegate hook classify` (`READ_CLASSIFY` en
  `mod/read.js`). Esa vía entra por `local_delegate.entrypoint`, que importa `local_delegate.server`
  y con él el SDK de MCP: `-X importtime` da **654 ms** de importación, **528 ms** de ellos en
  `local_delegate.server` (450 ms en el paquete `mcp`). A mano, la llamada completa tarda
  **~745 ms** (3 de 3), lo mismo que la diferencia medida.
- El arranque de Python en sí cuesta poco: `python -I -c pass` ≈ 90 ms.
- Dato para quien lo arregle (no se ha tocado nada): la misma entrada por
  `python -I -m local_delegate.hook classify` devuelve la misma respuesta en **~190 ms** (3 de 3).
  `record-read` (`READ_RECORD`) usa la misma vía cara, pero en esta prueba no se lanzó (ficheros
  < 8 KB).
- Línea base de la configuración real, igual en los dos brazos (tiempos del motor en
  `--debug-file`): `PostToolUse` de warp ~615 ms, hook `shell` de local-delegate ~155 ms (p95
  ~315 ms), `pre-tool-use.mjs` del harness ~110 ms. Por eso una `Bash` en caliente ronda los 900 ms
  incluso sin el mod. El hook `shell` no bajó en el brazo «con» (153,5 frente a 157,5 ms).

## Montaje

- Config REAL (sin `CLAUDE_CONFIG_DIR`), plugin instalado `local-delegate@local-delegate`, opciones
  pasadas a cada brazo con `claude -p --settings`: `F4-live/settings-con.json` y
  `settings-sin.json` copian las cinco opciones de `~/.claude/settings.json` y solo cambian
  `read_mod_enabled`. La capa de lectura está encendida, como en esta PC (`classify` da
  `read_switch: on`). `~/.claude/settings.json` no se tocó.
- `--strict-mcp-config` sin servidores (las lecturas pequeñas nunca llaman a `local_summarize`),
  `--allowedTools Bash`, `--max-turns 1`, stdin cerrado; corridas de una en una, en
  `D:\Projects\local-delegate`.
- Conductor: copia adaptada del de F2-live (`F4-live/drv/`, comando `/f4bash`), sin turno del
  modelo. Cada sesión hace 1 llamada en frío (`pwd`) y 10 en caliente alternando
  pasa/no pasa: pasan `cat LICENSE`, `head -5 .gitignore`, `sed -n 1,5p LICENSE`, `cat .gitignore`,
  `head -n 3 LICENSE`; no pasan `git status --short`, `pwd`, `ls`, `git log -1 --oneline`, `date`.
  (`echo` no sirve como «no pasa»: no está en `READ_HARMLESS_FIRST`, así que llega a `classify`).
  Diseño: 1 llamada en frío + 10 en caliente por sesión (F2-live usaba 10 en total), para tener
  5 + 5 por mitad: 30 muestras por mitad y brazo.
- Antes de medir, una sesión de prueba por brazo (`runs/trial/`, fuera del análisis).

## Comprobación de los latidos: VÁLIDA

Los 12 latidos (`~/.claude/plugins/data/local-delegate-local-delegate/heartbeats/<sid>.json`):
las 6 sesiones «con» dicen `read_mod_active: true` (y `pieces.read: on`); las 6 «sin» no tienen
`read_mod_active` (y `pieces.read: off`, `read_mod_enabled: false`). Detalle en `heartbeats` de
`overhead-result.json`.

## Ficheros

`F4-live/run_overhead.ps1` (`-Repeat 3 -Pairs 2`), `F4-live/analyze_overhead.py <runs>`,
`F4-live/overhead-result.json` (resultado), `F4-live/runs/overhead/` (salidas y `--debug-file`).

## Restos

Quedan en el `~/.claude` real los 14 latidos de estas sesiones y sus transcripts de `-p`. No queda
ningún proceso de la prueba ni ninguna ventana abierta.

## Segunda medición, tras el #426

`main` en `986635e` (PR #426), paquete reinstalado y daemon reiniciado por la sesión principal (aquí
no se tocó nada de eso). El motor carga el mod desde el paquete de `uv tool` (`Read hooks.json for
plugin local-delegate … site-packages\local_delegate\resources\claude-plugin\…` en `--debug-file`),
que ya trae el prefiltro (`readWorthClassifying`); la copia vieja de `~/.claude/plugins/cache/…/0.40.0`
no se usa. Ventana de prueba `w-20261023T003811Z` (00:38:11Z–00:47:03Z), abierta y cerrada.

**Mismo método y criterio** (+150 ms en la mediana y +300 ms en el p95, en caliente, 3 repeticiones ×
2 sesiones por brazo intercaladas con, sin, con, sin), con el conductor `F4-live/drv2/`
(`/f4bash3`): 1 llamada en frío (`pwd`) + 15 en caliente que rotan tres mitades, 30 muestras por
mitad y brazo:

1. **No pasan el filtro**: `git status --short`, `pwd`, `ls`, `date`, `echo hi`.
2. **Ficheros pequeños que no son prosa** (el prefiltro debe descartarlos sin proceso): `cat`/`head`/
   `sed -n` sobre `src/local_delegate/__main__.py` (180 B), `hook.py` (1,5 KB), `__init__.py`
   (1,7 KB) y `.claude-plugin/marketplace.json` (456 B).
3. **Prosa pequeña** (< 8 KB; llega a `classify` pero no se resume): `.github/ISSUE_TEMPLATE/bug_report.md`
   (402 B), `feature_request.md` (388 B), `.github/PULL_REQUEST_TEMPLATE.md` (402 B).

No se usó ningún fichero de prosa de 8 KB o más ni ninguna tool `local_*`: ninguna llamada pidió
`local_summarize` (la GPU estaba ocupada con un juego).

**Ruido: alto.** La PC tenía un juego en marcha. La misma `Bash` sin el mod pasó de ~910 ms a ~1650 ms
de mediana, y todos los hooks de la línea base se doblaron (warp ~1170 ms, `shell` ~285 ms,
harness ~210 ms). Los brazos van intercalados, pero las sesiones varían entre sí hasta 500 ms en la
misma mitad, así que las diferencias de menos de ~200 ms no se distinguen bien del ruido.

### Veredicto: NO CUMPLE (por 15 ms en la mediana del total, con ruido alto)

| Llamadas en caliente | n por brazo | Mediana con | Mediana sin | Δ mediana (tope +150) | p95 con | p95 sin | Δ p95 (tope +300) |
|---|---|---|---|---|---|---|---|
| **Total** | 90 | 1799 ms | 1634 ms | **+165 ms** ✗ | 2337 ms | 2344 ms | **−7 ms** ✓ |
| 1. No pasan el filtro | 30 | 1690,5 ms | 1667,5 ms | +23 ms ✓ | 2133 ms | 2126 ms | +7 ms ✓ |
| 2. Pequeños que no son prosa | 30 | 1783 ms | 1590,5 ms | **+192,5 ms** ✗ | 2335 ms | 2071 ms | +264 ms ✓ |
| 3. Prosa pequeña | 30 | 1994,5 ms | 1656 ms | **+338,5 ms** ✗ | 2401 ms | 2647 ms | −246 ms ✓ |
| Primera de cada sesión (aparte) | 6 | 3585,5 ms | 3435,5 ms | +150 ms | 4464 ms | 3960 ms | +504 ms |

### Procesos que lanza el mod (`$.process.run` en `--debug-file`, `count_processes.py`)

| Mitad (brazo «con») | Llamadas | Procesos | Duración del proceso (mediana / máx) |
|---|---|---|---|
| 1. No pasan el filtro | 30 | **0** | — |
| 2. Pequeños que no son prosa | 30 | **0** | — |
| 3. Prosa pequeña | 30 | **30** (uno por llamada) | **248 ms** / 561 ms |

El prefiltro hace lo que promete: la mitad 2 no lanza ningún proceso, y la mitad 3 lanza un solo
`classify` por llamada, por la vía ligera (`-m local_delegate.hook`), sin `record-read`. Al
inicio de cada sesión el mod lanza además `classify --config` (~305 ms) y `--list-tools`
(~160 ms), que no caen dentro de las llamadas cronometradas. Con la máquina cargada, `classify`
a mano tarda 360–470 ms (sin carga, ~123 ms según el #426).

**Dónde queda la diferencia.** En la mitad 3, el proceso explica unos 250 ms de los +338,5. La
mitad 2 no lanza procesos, así que sus +192,5 ms son ruido o las llamadas al motor que hace el mod
antes de descartar (`$.session.id`, `$.session.cwd`, `$.fs.stat` y el salto al worker). El log no
deja separar esas partes. Comparando dentro de cada sesión con la mitad 1 (lo que quita el ruido
entre sesiones), la mitad 2 sale +73,5 ms en «con» y −108 ms en «sin» (unos +180 ms netos), y la
mitad 3 sale +226,5 ms en «con» y +47,5 ms en «sin» (unos +180 ms netos). Para separar el coste de
las llamadas al motor del ruido haría falta repetir la medición sin el juego.

### Latidos: VÁLIDA

Las 6 sesiones «con» dicen `read_mod_active: true`; las 6 «sin» no tienen el campo
(`read_mod_enabled: false`). Detalle en `heartbeats` de `overhead2-result.json`.

### Ficheros (segunda medición)

`F4-live/drv2/` (conductor), `run_overhead.ps1 -Sub overhead2 -Drv drv2 -Cmd /f4bash3` (el script
acepta ahora `-Drv` y `-Cmd`; los valores por defecto repiten la primera medición),
`analyze_overhead.py` (ahora admite cualquier conjunto de mitades; regenera igual el resultado de
la primera, comprobado), `count_processes.py`, `overhead2-result.json`, `processes2-result.json`,
`runs/overhead2/` y `runs/trial2/` (prueba del montaje, fuera del análisis). `settings-con.json` y
`settings-sin.json` se regeneraron desde las opciones actuales de `~/.claude/settings.json`, que
ahora trae `read_mod_enabled: false`. Cada brazo lo fija igual con `--settings`.

## Tercera medición, PC en reposo

Mismo código (`main` en `8732158`, el del #426 más la evidencia del #427), sin reinstalar ni tocar el
daemon. Ventana de prueba `w-20261023T015443Z` (01:54:43Z–01:59:05Z), abierta y cerrada; corridas
de 01:55:03Z a 01:58:55Z, de una en una y con stdin cerrado. Mismo conductor (`drv2/`, `/f4bash3`),
mismas tres mitades y comandos, 3 repeticiones × 2 sesiones por brazo intercaladas (con, sin, con,
sin), primera llamada descartada. `settings-con.json` y `settings-sin.json` se regeneraron desde
las opciones actuales de `~/.claude/settings.json` y salieron idénticos a los de la segunda
(solo cambia `read_mod_enabled`). No se usó ningún fichero de prosa de 8 KB o más.

**Reposo comprobado antes de empezar**: CPU 3–17 % (cinco muestras cada 2 s), GPU 0–5 % con
1,47 GB de VRAM ocupados (el modelo residente de `llama-swap`), 15,6 GB de RAM libres de 31,1, sin
juego ni otra aplicación con carga. La línea base volvió a la de la primera medición: una `Bash` sin
el mod ronda los 960 ms (warp ~675 ms, hook `shell` ~145 ms, harness ~126 ms, iguales en los dos
brazos).

### Veredicto: CUMPLE

| Llamadas en caliente | n por brazo | Mediana con | Mediana sin | Δ mediana (tope +150) | p95 con | p95 sin | Δ p95 (tope +300) |
|---|---|---|---|---|---|---|---|
| **Total** | 90 | 1010,5 ms | 961 ms | **+49,5 ms** ✓ | 1278 ms | 1186 ms | **+92 ms** ✓ |
| 1. No pasan el filtro | 30 | 978 ms | 966,5 ms | +11,5 ms ✓ | 1140 ms | 1186 ms | −46 ms ✓ |
| 2. Pequeños que no son prosa | 30 | 962 ms | 956 ms | +6 ms ✓ | 1278 ms | 1146 ms | +132 ms ✓ |
| 3. Prosa pequeña | 30 | 1112,5 ms | 956,5 ms | +156 ms (6 ms sobre el tope) | 1568 ms | 1246 ms | +322 ms (22 ms sobre el tope) |
| Primera de cada sesión (aparte) | 6 | 1849 ms | 1801,5 ms | +47,5 ms | 2065 ms | 1987 ms | +78 ms |

El criterio se fijó sobre el total y lo cumple con margen. Sin ruido, la mitad 2 queda en +6 ms: los
+192,5 ms de la segunda medición eran ruido del juego, no las llamadas al motor que hace el mod antes
de descartar. Lo que cuesta es la mitad 3, la única que lanza un proceso: unos +156 ms por llamada,
justo el tope si se mirara sola. Eso solo pasa con ficheros de prosa, que es donde el mod tiene algo
que decidir.

### Procesos que lanza el mod (`count_processes.py`)

| Mitad (brazo «con») | Llamadas | Procesos | Duración del proceso (mediana / máx) |
|---|---|---|---|
| 1. No pasan el filtro | 30 | **0** | — |
| 2. Pequeños que no son prosa | 30 | **0** | — |
| 3. Prosa pequeña | 30 | **30** (uno por llamada) | **136,5 ms** / 342 ms |

El brazo «sin» no lanza ningún proceso del mod. En reposo, `classify` por la vía ligera tarda la
mitad que con el juego (136,5 frente a 248 ms) y explica casi toda la diferencia de la mitad 3.

### Latidos: VÁLIDA

Las 6 sesiones «con» dicen `read_mod_active: true`; las 6 «sin» no tienen el campo. Detalle en
`heartbeats` de `overhead3-result.json`.

### Ficheros (tercera medición)

`run_overhead.ps1 -Repeat 3 -Sub overhead3 -Drv drv2 -Cmd /f4bash3`, `overhead3-result.json`,
`processes3-result.json` y `runs/overhead3/` (salidas y `--debug-file`). No queda ningún proceso de
la prueba ni ninguna ventana abierta; quedan en el `~/.claude` real los 12 latidos y los transcripts
de `-p` de estas sesiones.

## Cuarta medición, clasificación por el daemon (#428)

El **después** de la mejora: `main` en `c8c0910` (#428, ya instalado y con el daemon reiniciado), sin
reinstalar ni tocar nada. Ahora el mod pregunta al daemon por HTTP (`POST /api/hook/classify` y
`/api/hook/classify-config`) y el proceso de Python queda solo de respaldo. Ventana de prueba
`w-20261023T023820Z` (02:38:20Z–02:41:46Z), abierta y cerrada; corridas de 02:38:27Z a 02:41:35Z, de
una en una y con stdin cerrado. Montaje idéntico al de la tercera: `drv2/`, `/f4bash3`, las mismas
tres mitades y comandos, 3 repeticiones × 2 sesiones por brazo intercaladas, primera llamada
descartada. `settings-con.json` y `settings-sin.json` siguen iguales a las opciones actuales de
`~/.claude/settings.json` (solo cambia `read_mod_enabled`), así que no hubo que regenerarlos. Sin
ficheros de prosa de 8 KB o más.

**Reposo comprobado antes de empezar**: CPU 4–13 % (cinco muestras cada 2 s), GPU 0 % con 1,5 GB de
VRAM ocupados (el modelo residente de `llama-swap`), 15,6 GB de RAM libres de 31,1, sin juego ni otra
aplicación con carga. La línea base salió más rápida que en la tercera **en los dos brazos por
igual** (una `Bash` sin el mod ronda los 790 ms frente a 960: warp ~555 ms frente a ~675, hook `shell`
~116 frente a ~145, harness ~101 frente a ~126). Es la máquina, no el mod; por eso la comparación
justa es la diferencia con/sin de cada medición, no los valores absolutos.

### Veredicto: CUMPLE

| Llamadas en caliente | n por brazo | Medición | Mediana con | Mediana sin | Δ mediana (tope +150) | p95 con | p95 sin | Δ p95 (tope +300) | Procesos `classify` |
|---|---|---|---|---|---|---|---|---|---|
| **Total** | 90 | antes (3.ª) | 1010,5 ms | 961 ms | +49,5 ms | 1278 ms | 1186 ms | +92 ms | 30 |
| **Total** | 90 | **después (4.ª)** | 781 ms | 790 ms | **−9 ms** ✓ | 942 ms | 991 ms | **−49 ms** ✓ | **0** |
| 1. No pasan el filtro | 30 | antes | 978 ms | 966,5 ms | +11,5 ms | 1140 ms | 1186 ms | −46 ms | 0 |
| 1. No pasan el filtro | 30 | después | 778 ms | 779,5 ms | −1,5 ms ✓ | 1030 ms | 950 ms | +80 ms ✓ | 0 |
| 2. Pequeños que no son prosa | 30 | antes | 962 ms | 956 ms | +6 ms | 1278 ms | 1146 ms | +132 ms | 0 |
| 2. Pequeños que no son prosa | 30 | después | 787 ms | 786,5 ms | +0,5 ms ✓ | 931 ms | 1076 ms | −145 ms ✓ | 0 |
| 3. Prosa pequeña | 30 | antes | 1112,5 ms | 956,5 ms | +156 ms ✗ | 1568 ms | 1246 ms | +322 ms ✗ | 30 |
| 3. Prosa pequeña | 30 | después | 776 ms | 803,5 ms | **−27,5 ms** ✓ | 910 ms | 996 ms | **−86 ms** ✓ | **0** |
| Primera de cada sesión (aparte) | 6 | antes | 1849 ms | 1801,5 ms | +47,5 ms | 2065 ms | 1987 ms | +78 ms | — |
| Primera de cada sesión (aparte) | 6 | después | 1455,5 ms | 1557 ms | −101,5 ms | 1526 ms | 1618 ms | −92 ms | — |

La sobrecarga del mod desaparece dentro del ruido: el total queda en −9 ms de mediana y −49 de p95
(los valores negativos son ruido, el mod no puede acelerar la llamada). La mitad 3, la única que
quedaba en el tope (+156 y +322), baja a −27,5 y −86: lo que costaba era arrancar Python en cada
consulta, y la consulta al daemon tarda **2 ms de mediana (máx. 3 ms)**.

### Procesos que lanza el mod (`count_processes.py`)

| Mitad (brazo «con») | Llamadas | Procesos antes (3.ª) | Procesos después (4.ª) |
|---|---|---|---|
| 1. No pasan el filtro | 30 | 0 | **0** |
| 2. Pequeños que no son prosa | 30 | 0 | **0** |
| 3. Prosa pequeña | 30 | 30 (136,5 ms de mediana) | **0** |

El brazo «sin» tampoco lanza ninguno durante las llamadas medidas. Fuera de ellas, cada sesión de
los **dos** brazos lanza 2 procesos del plugin (uno al empezar y otro al terminar, ~58 ms, 0 bytes de
salida): no son del mod de lectura, porque salen igual con `read_mod_enabled: false`, y quedan fuera
del tiempo medido.

### Las consultas fueron por HTTP, no por el respaldo

Comprobado en los `--debug-file`, que registran cada `$.http.fetch` y cada `$.process.run` del plugin:

- Cada sesión «con» tiene **1** `POST http://127.0.0.1:9393/api/hook/classify-config` (la primera
  vez que hace falta la configuración) y **5** `POST .../api/hook/classify`, una por cada llamada de
  prosa; las 6 respuestas de cada sesión son `200` (36 de 36 en total, ninguna con error ni sin
  respuesta). Las 30 consultas de `classify` tardaron 2 ms de mediana y 3 ms como máximo, muy lejos
  del límite de 300 ms que activa el respaldo.
- Ninguna sesión «con» tiene un `$.process.run` dentro de las llamadas medidas (`count_processes.py`
  da 0), así que ninguna cayó al respaldo. Las sesiones «sin» no tienen ninguna petición
  `/api/hook/classify*`.

### Latidos: VÁLIDA

Las 6 sesiones «con» dicen `read_mod_active: true`; las 6 «sin» no tienen el campo
(`heartbeats_all_ok: true` en `overhead4-result.json`).

### Ficheros (cuarta medición)

`run_overhead.ps1 -Repeat 3 -Sub overhead4 -Drv drv2 -Cmd /f4bash3`, `overhead4-result.json`,
`processes4-result.json` y `runs/overhead4/` (salidas y `--debug-file`). No queda ningún proceso de
la prueba ni ninguna ventana abierta; quedan en el `~/.claude` real los 12 latidos y los transcripts
de `-p` de estas sesiones.
