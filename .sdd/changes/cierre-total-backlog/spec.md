# Especificación — cierre total del backlog

## Resumen

El backlog de `local-delegate` queda **vacío de defectos**: cada punto vivo se arregla con prueba
que lo cubre, o se cierra como decisión escrita con su medición. Los cuatro defectos que destapó la
auditoría de esta sesión se arreglan igual. El resultado se publica como versión nueva y la máquina
del usuario queda con esa versión **instalada desde PyPI**, no desde el repo.

## Requisitos

- **REQ-001** — Ante `CTRL_BREAK_EVENT`, `local-delegate serve` termina con código **0** y
  `local-delegate` en modo stdio termina con código **0**. Hoy dan `3` y `0xC000013A`.
- **REQ-002** — Cuando el lock del daemon está tomado, el mensaje de `serve` dice **dónde está el
  daemon vivo** (host y puerto reales, y su pid), no el puerto que se pidió. El docstring deja de
  afirmar que el ámbito es «usuario/puerto».
- **REQ-003** — `local-delegate --version` imprime la versión instalada y sale con **0**.
- **REQ-004** — `install --enable-read-hook` deja el hook de `Read` **efectivamente activo**: tras
  instalar, invocar el hook tal y como queda registrado produce la sugerencia. La variable
  `LD_HOOK_READ_ENABLED` sigue funcionando para instalaciones a mano.
- **REQ-005** — `clients.jsonl` tiene techo de tamaño, y `checks.client.observed` **sigue viendo a
  los clientes ya registrados** después de que rote.
- **REQ-006** — La suite ejerce el panel **interactuado** en un navegador real: paginación de la
  tabla y filtros. El test se salta solo, con motivo visible, donde no haya navegador.
- **REQ-007** — Playwright está declarado en el proyecto, de forma que reinstalar el entorno no lo
  desaparezca en silencio.
- **REQ-008** — El CI ejerce el **instalador end-to-end en macOS** contra un HOME temporal, dentro
  del job `test (macos-latest)` que ya existe. No se añade ni se quita ningún job del ruleset.
- **REQ-009** — El backlog del vault queda sin ningún punto abierto: cada uno cerrado, o movido a
  «decisiones tomadas» con la medición que lo respalda.
- **REQ-010** — Se publica una versión nueva en PyPI y en el registro MCP, y el CLI y el daemon de
  la máquina del usuario quedan en esa versión **desde el paquete publicado**.

## Escenarios de aceptación

### Escenario: Ctrl+Break sobre el daemon

- **Dado** un `local-delegate serve` corriendo en su propio grupo de procesos
- **Cuando** el sistema le entrega `CTRL_BREAK_EVENT`
- **Entonces** el proceso cierra ordenado y devuelve `0`

### Escenario: Ctrl+Break sobre el MCP stdio

- **Dado** un `local-delegate` en modo stdio esperando por stdin
- **Cuando** el sistema le entrega `CTRL_BREAK_EVENT`
- **Entonces** el proceso devuelve `0` en vez de `0xC000013A`

### Escenario: segundo `serve` con el daemon vivo en otro puerto

- **Dado** un daemon activo en `127.0.0.1:9393`
- **Cuando** se lanza `local-delegate serve --port 9899`
- **Entonces** el mensaje nombra `127.0.0.1:9393` y el pid del daemon vivo

### Escenario: el hook de Read encendido por el instalador

- **Dado** un HOME limpio donde se corrió `install --enable-read-hook`
- **Y** un entorno **sin** `LD_HOOK_READ_ENABLED`
- **Cuando** se ejecuta el hook exactamente como quedó registrado en `settings.json`, con un
  archivo por encima de la banda
- **Entonces** emite la sugerencia
- **Y** el mismo hook, registrado **sin** la bandera, no emite nada (control negativo)

### Escenario: el panel interactuado

- **Dado** el dashboard servido con datos suficientes para más de una página
- **Cuando** se pulsa «siguiente» en la tabla y se aplica un filtro de tool
- **Entonces** las filas visibles cambian conforme a la página y al filtro

### Escenario: `clients.jsonl` rotado

- **Dado** un registro por encima del techo y un cliente anotado al principio del fichero
- **Cuando** rota
- **Entonces** `checks.client.observed` sigue reportando a ese cliente

## Casos límite y comportamiento ante fallo

- La rotación de `clients.jsonl` **nunca** puede tumbar el middleware: escribir es best-effort, y
  un fallo al rotar degrada a seguir anexando.
- Instalar el handler de `SIGBREAK` debe ser inofensivo donde `SIGBREAK` no existe (POSIX): el
  código pregunta por el atributo, no por la plataforma.
- El test de navegador **se salta con motivo** si falta Playwright o el navegador; no falla. Pero
  no puede pasar en silencio sin haber comprobado nada: lleva su control positivo.
- El paso de macOS en CI corre contra un HOME temporal y **jamás** toca el HOME del runner.

## Requisitos no funcionales

- Ningún cambio altera el contrato de las tools `local_*` ni el formato de `usage.jsonl`.
- No se añade dependencia de runtime nueva. Playwright entra como grupo **opt-in**, fuera del
  wheel.
- El paquete publicado no engorda.

## No objetivos

- No se implementa memoria entre trozos del chunking (A4): sin síntoma y con el arreglo obvio
  siendo incorrecto para el caso de uso.
- No se implementan las ideas de la sección 4 del backlog (recibo en el dashboard, vendorizar las
  fuentes web): decisión explícita del usuario en esta sesión.
- No se añade comprobador de tipos: se propone aparte.
- No se prueba Codex contra un daemon con token ni la UI de `elicitation` en un tty: no hay forma
  de responderlos aquí y una conclusión inventada sería peor que la ausencia.

## Trazabilidad

| Requisito | Trabajo | Evidencia |
|---|---|---|
| REQ-001 | `daemon.py`, `server.py`, `tests/test_ctrl_c.py` | medición de códigos de salida |
| REQ-002 | `daemon.py`, `tests/test_daemon.py` | test del mensaje |
| REQ-003 | `cli.py`, `tests/test_core.py` | `--version` con rc 0 |
| REQ-004 | `install.py`, hook de Read, test de la combinación | control positivo y negativo |
| REQ-005 | `clients.py`, `checks.py`, tests | test de rotación + check |
| REQ-006 | test de navegador, `ci.yml` | run del CI |
| REQ-007 | `pyproject.toml` | grupo declarado |
| REQ-008 | `ci.yml` | run del CI en macOS |
| REQ-009 | nota del vault | backlog sin puntos abiertos |
| REQ-010 | `scripts/release.py`, PyPI | `doctor` y una tool real |
