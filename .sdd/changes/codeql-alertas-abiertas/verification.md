# Verification: Cerrar las 10 alertas abiertas de CodeQL: 6 arreglos y 4 descartes

## Environment

- Revision: rama `fix/codeql-alertas-abiertas`, partiendo de `17df173` (main).
- Plataforma: Windows 11, PowerShell/Git Bash; `uv run pytest`, `uv run ruff`, `node --check`.
- Herramienta de origen de las alertas: CodeQL v4, suite `security-and-quality`.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Extraer el JS antes y después del cambio y comparar | **OK, en tres vueltas** | `cmp` → idéntico byte a byte las tres veces (41 633 chars, sha256 `6e030c20…`); `node --check` pasa; 7 combinaciones de etiqueta probadas |
| REQ-002 | Comentario dentro de cada uno de los tres `except`; sin tocar flujo de control | **OK** | diff: solo líneas de comentario añadidas en `hook_common.py`, `daemon.py`, `server.py` |
| REQ-003 | **Mutante**: primera lectura de `config.WEB_FONTS` forzada a `True` | **OK, distingue** | el test falla exactamente en `assert hoja not in html`, mostrando el `<link>` de Google Fonts emitido |
| REQ-004 | **Mutante dirigido**: `with _chat_slots:` → `acquire()` sin release, con 2 hilos (sin deadlock) | **OK, distingue** | falla en `assert (estado_final, slots) == ((2,0), [True,True])` con `((2,0), [False,False])`, en 0.34 s |
| REQ-006 | Suite completa + linters | **OK** | `722 passed, 2 skipped`; `ruff check` limpio; `ruff format --check`: 74 ficheros ya formateados |
| REQ-005 | Descartes de #19, #13, #11, #12 | **PENDIENTE** | por diseño: van después del merge (decisión del usuario) |

### El arreglo de #20 tuvo que hacerse tres veces, y lo dijo el CI, no yo

La verificación local (salida idéntica byte a byte) daba REQ-001 por bueno desde la primera vuelta,
y era verdad — pero medía **la ausencia de regresión**, no la satisfacción de la regla. Quien
midió eso fue el job de CodeQL de la propia PR, en tres rondas: cada arreglo destapaba la siguiente
objeción de `py/bad-tag-filter` sobre el mismo patrón.

1. `re.IGNORECASE` → «no captura `</script >`» (cierre con espacio).
2. `</script\s*>` → «no captura `</script\t\n bar>`» (cierre con atributos sueltos).
3. `</script(?:\s[^>]*)?>` → **check en verde**.

Dos cosas que dejar dichas. La primera: **el `gh run list` daba los tres workflows en verde mientras
el check `CodeQL` de la PR estaba en rojo** — son cosas distintas, el job `Analyze (python)` pasa
siempre que el análisis corra, y el veredicto sobre las alertas vive en un check aparte. Sin mirar
`gh pr checks` completo esto se habría mergeado creyendo que estaba arreglado.

La segunda: la escalera es el comportamiento normal de esa regla, cuyo fondo es «no parsees HTML con
regex». El plan fijaba de antemano dónde parar —si aparecía una cuarta objeción, la alerta pasaba a
descarte por inaplicable— y no hizo falta usarlo.

### Lo que el control positivo dejó ver, y que conviene no maquillar

El primer mutante de REQ-004 (los 5 hilos originales con `_chat` sin liberar) **no lo atrapó el assert
nuevo, sino `assert not thread.is_alive()`, que ya existía**: con 5 hilos y 2 slots el deadlock llega
antes. Es decir, ese mutante no demostraba nada sobre el cambio.

Por eso se repitió con un mutante dirigido (2 hilos, sin deadlock posible), y ahí sí: `(peak, active)`
sigue valiendo `(2, 0)` —o sea, todos los asserts anteriores del test pasan— y lo único que delata el
filtrado de slots es la comprobación nueva. Ese es el escenario real que cubre: una delegación que se
come un slot sin colgar el proceso todavía.

## Quality checks

- [x] Project-native tests pass — `722 passed, 2 skipped`.
- [x] Lint, formatting, and build checks pass — `ruff check` y `ruff format --check` limpios;
      `node --check` sobre el JS extraído.
- [x] Secret scanning — sin secretos en el diff: los seis ficheros solo reciben comentarios, un flag
      de regex y dos asserts. `gh api .../secret-scanning/alerts?state=open` devolvía 0 antes de
      empezar.
- [x] No unrelated changes are present — `git diff --stat` = exactamente los 6 ficheros del plan.
- [ ] Type checking — no aplica: el proyecto no tiene comprobador de tipos configurado (consta como
      propuesta abierta en el backlog, no como deuda).

## Deviations and residual risk

- **Cuatro tests fallaban en esta máquina antes de tocar nada, y no son de este cambio.**
  `tests/test_daemon.py` da cuatro `401 == 200` cuando `LOCAL_DELEGATE_WEB_TOKEN` está definida en el
  entorno (aquí lo está, 48 caracteres, desde la 0.22.1). Verificado por control: con `git stash` los
  mismos cuatro fallan sin mis cambios, y con `LOCAL_DELEGATE_WEB_TOKEN=` pasan los 25. En CI no se
  ven porque allí la variable no existe. **Es un defecto real de aislamiento de esos tests —dependen
  del entorno— pero está fuera del alcance de este cambio**; queda anotado en el handoff.
- **REQ-005 sin verificar todavía**, por diseño: los descartes se aplican tras el merge y su
  comprobación (`?state=open` → `[]`) es el último paso.
- **El job de CodeQL sobre la PR es la comprobación definitiva** de REQ-001..REQ-004. Si alguna
  alerta sobreviviera al arreglo, el plan ya prevé moverla a la lista de descartes en vez de seguir
  retocando código para que la herramienta calle.
- **Riesgo residual del arreglo de #20:** ninguno medible. La salida es idéntica byte a byte; el
  `re.IGNORECASE` es defensa ante un HTML futuro, no corrección de un fallo actual.
