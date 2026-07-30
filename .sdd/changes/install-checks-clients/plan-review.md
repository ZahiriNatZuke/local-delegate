# Plan review (adversarial): install-checks-clients

Revisión del gate **plan** contra `brief.md`, `research.md`, `spec.md` y el código de `main`
(`7c48328`). Las afirmaciones del plan se comprobaron contra el proyecto, no se dieron por
buenas.

## 1. Gate y veredicto propuesto

- **Gate:** `plan`
- **Veredicto propuesto (antes de remediar):** *cambios requeridos* — **3 hallazgos bloqueantes**.
- **Veredicto tras aplicar las remediaciones de §5:** aprobable.
- **Estado: los 7 hallazgos fueron remediados** en `plan.md` (tareas 1, 2, 3, 4 y 5, y su
  sección *Plan review*) y en `spec.md` (REQ-002, REQ-005 y la tabla de casos límite). Sin
  hallazgos bloqueantes abiertos.

## 2. Hallazgos bloqueantes

### B-1. El plan no dice de dónde sale «cliente presente», y la fuente obvia no sirve

El plan y la spec (REQ-002) dicen que `auto` resuelve «con el mismo criterio que el check
`client.presence`». Pero ese check **no devuelve datos estructurados**: `_probe_clients`
(`checks.py:199-207`) devuelve `Result(OK, "detectados: Claude Code, Codex")` — texto libre, con
los nombres de presentación («Claude Code»), no los identificadores del CLI (`claude`).

Resolver `auto` parseando ese `detail` sería frágil y silenciosamente roto en cuanto alguien
reescriba el texto. El plan no lo menciona, así que la implementación lo improvisaría.

Existe ya la función correcta —`update._present_targets` (`update.py:167-174`)— pero vive en el
módulo equivocado para que la use `install`.

**Impacto:** alto. Es el requisito central del change (REQ-002) y la vía improvisada introduce
acoplamiento a un string de presentación.

### B-2. REQ-005 y REQ-012 se contradicen y el plan no lo resuelve

- REQ-005: con `auto` y ningún cliente, **no se escribe nada** y exit 0.
- REQ-012: el reporte final se imprime **siempre**.

¿Se imprime el reporte en ese camino? La spec dice «siempre» y el plan lo repite sin resolver el
cruce. Dos implementaciones razonables dan salidas distintas, y una de ellas —imprimir doce
líneas de `[ -- ]` tras decir «no hice nada»— es ruido puro.

**Impacto:** medio-alto. Ambigüedad en un requisito verificable: el test se escribiría contra lo
que hiciera el código, no contra lo especificado.

### B-3. `uninstall` está en REQ-001 pero fuera de la verificación del plan

REQ-001 obliga a `--clients` en `install` **y** `uninstall`. La tarea 3 toca
`_add_common_install_args`, que efectivamente comparten los dos subcomandos, pero **ningún caso
de verificación del plan ejercita `uninstall`** con el flag nuevo.

No es cosmético: `uninstall --clients auto` cambia qué se limpia. Hoy el default (`all`) limpia
los dos clientes; con `auto`, en una máquina donde `~/.codex` ya no existe, Codex no se toca —
correcto— pero nadie lo prueba. Y la tarea 2 (HOME simulado) tiene su caso más dañino
precisamente en `uninstall`, que **desregistra** el MCP real (`install.py:568`), como el propio
`research.md` señala.

**Impacto:** medio-alto. El camino destructivo es el menos cubierto.

## 3. Hallazgos no bloqueantes

### N-1. Doblar `Path.home()` por variable de entorno rompería el CI en Windows

El plan propone comparar byte a byte «un HOME real simulado con `monkeypatch` de `Path.home`».
La trampa: `Path.home()` lee `USERPROFILE` en Windows y `HOME` en POSIX. Un test que haga
`monkeypatch.setenv("HOME", ...)` pasa en Linux y macOS y **falla en Windows**, y el CI corre en
los tres. Confirmado: `Path.home()` es la única fuente en todo el repo (`cli.py:46`, `:130`,
`doctor.py:322`, `update.py:113`) y ningún test la dobla hoy.

**Remediación:** doblar el atributo, no el entorno —
`monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_real))`.

### N-2. `uninstall` también borra una entrada de Codex puesta a mano, y eso queda sin explicar

`remove_codex_mcp` (`install.py:319-321`) aplica `_CODEX_SECTION_RE` igual que el `upsert`: se
lleva por delante la sección aunque no tenga marcadores. La spec protege ese caso solo en
`install`.

Es **defendible** no ampliar el alcance —la sección se llama `[mcp_servers.local-delegate]`, o
sea nuestra por definición, y `uninstall` es la orden explícita de quitarla, no de sustituirla
por otra cosa— pero si no queda escrito se leerá como olvido en la próxima revisión.

**Remediación:** una línea de comentario en el código y una fila en la tabla de casos límite.

### N-3. El plan no aprovecha el precedente de tty que ya existe

REQ-009 (sin terminal, no se pregunta) tiene molde hecho en
`tests/test_smoke.py:139-174`: `test_el_aviso_de_terminal_solo_sale_con_tty_y_por_stderr` y
`test_el_aviso_no_revienta_con_un_stdin_raro`. Citarlos evita reinventar el doblaje de `stdin` y
—más importante— recuerda cubrir el *stdin raro*, que es un caso que ya mordió aquí.

### N-4. Riesgo de lectura: dos pasadas de `checks`

El diseño corre el registro dos veces (antes, para resolver; después, para reportar). Es
correcto y barato en los grupos `entorno`/`andamiaje` (solo `shutil.which`, `metadata.version` y
lecturas de fichero), pero conviene que quede escrito en el código, o el próximo lector lo tomará
por un descuido y «optimizará» reutilizando la primera pasada — que ya no reflejaría lo escrito.

## 4. Evidencia que falta

Ninguna que impida aprobar. Dos comprobaciones quedan explícitamente diferidas a la fase de
verificación, y está bien que así sea:

- Que el binario `claude` **no** se invoque con `--home` simulado: solo es demostrable ejecutando,
  y la prueba debe correrse **también al revés** (revertir el arreglo y ver fallar el test).
- El end-to-end en Windows en `sh`, `cmd` y PowerShell.

## 5. Remediación exacta requerida

1. **B-1:** añadir a la tarea 1 la extracción de `present_targets(home) -> set[str]` a
   `install.py`, junto a `is_simulated_home`, y hacer que `update._present_targets` la consuma.
   Corregir REQ-002 para que diga «el mismo criterio **y la misma función**» en vez de referirse
   al `detail` del check. Prohibir explícitamente parsear `Result.detail`.
2. **B-2:** decidir y escribir el cruce. Recomendación: **sí se imprime**, porque el valor del
   reporte en ese caso es justamente enseñar los `[ -- ]` que explican por qué no se hizo nada;
   pero precedido de la línea de aviso, no de un «Listo».
3. **B-3:** añadir a la tarea 3 la verificación de `uninstall --clients auto` y a la tarea 2 el
   caso de `uninstall` con HOME simulado (cero invocaciones del binario `claude`).
4. **N-1:** fijar en el plan que el doble es `Path.home`, no la variable de entorno.
5. **N-2:** anotar la asimetría `install`/`uninstall` en el código y en los casos límite.
6. **N-3:** citar `tests/test_smoke.py:139-174` como molde en la estrategia de pruebas.
7. **N-4:** exigir un comentario que explique por qué son dos pasadas.

## 6. Evidencia recomendada para aprobar el gate

> Revisión adversarial completa con 3 hallazgos bloqueantes (fuente de la presencia de clientes,
> contradicción REQ-005/REQ-012, `uninstall` sin verificación) y 4 no bloqueantes, todos
> remediados en `plan.md` y `spec.md`; afirmaciones del plan verificadas contra `checks.py:199`,
> `update.py:167`, `install.py:319`, `install.py:568` y `tests/test_smoke.py:139`.
