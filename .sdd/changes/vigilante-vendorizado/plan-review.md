# Revisión adversarial del plan

**Limitación declarada: la revisión no es independiente** — la hace el mismo agente que escribió el
plan, sin subagentes. Sirve para cazar premisas sin verificar; no sustituye a un revisor ajeno.

## F1 (CORREGIDO ANTES DE ESCRIBIR EL PLAN) — el `schedule` no puede ir en `ci.yml`

La spec pide cron semanal (REQ-007). La forma obvia sería añadir `schedule` a `ci.yml`, y sería un
error: **dispararía todos sus jobs** —`test` en ubuntu, macOS y Windows, `lint`, `secrets`,
`install-smoke`— cada semana, solo para mirar el hash de un fichero. Minutos de Actions y ruido a
cambio de nada.

Corregido en el plan: **workflow propio** `vendor-audit.yml`. `codeql.yml` ya tiene su cron aparte,
así que es la convención de la casa.

## F2 (IMPORTANTE) — el test tiene que probar que la detección detecta

Un test que compruebe «con el fichero bueno pasa» no prueba nada: pasaría igual con un script que
devolviera `0` siempre. **El test que importa es el inverso**: alterar una copia del blob y exigir
que el script **falle**. Ya está en la tarea 4 y no se puede recortar.

Corolario: hacerlo **sobre copias en `tmp_path`**. Un test que toque
`src/local_delegate/resources/vendor/chart.umd.min.js` de verdad puede dejar el repo sucio si falla a
mitad — justo el fichero cuya integridad estamos protegiendo.

## F3 (IMPORTANTE) — «que avise» no sirve si nadie lo lee

REQ-004 dice que una versión nueva **avisa sin fallar**. Bien, pero un aviso en el log de un job
verde **no lo lee nadie**: es exactamente por lo que Chart.js lleva dos minors atrasado sin que nadie
se enterara.

Mitigación asumida y honesta: el aviso va al **summary del job**, no solo al log, para que se vea sin
abrir la corrida. No se construye nada más (ni issues automáticos ni notificaciones) porque sería
alcance nuevo. **Queda anotado como límite conocido**, no vendido como resuelto.

## F4 (verificado, sin acción) — el manifiesto sí entra en el wheel

`pyproject.toml` declara `packages = ["src/local_delegate"]`, así que todo lo que cuelga del paquete
se empaqueta — por eso el blob de Chart.js ya viaja hoy. El manifiesto irá con él. Comprobado en el
`pyproject.toml`, no supuesto.

## F5 (aceptado) — el vigilante no valida la *procedencia* en cada corrida

El script compara contra el hash **del manifiesto**, no contra jsDelivr. O sea: detecta que el blob
cambió, pero no volvería a demostrar que el blob es el 4.4.1 auténtico. Esa demostración se hizo una
vez, byte a byte, y queda escrita en el `research.md`.

Es lo correcto: comparar contra la red en cada corrida haría la comprobación **no determinista** —
justo lo que el criterio del usuario descarta— y encima chocaría con el banner de jsDelivr. La
procedencia se verifica **al actualizar la versión**, que es cuando cambia, y por eso la tarea 5
exige documentar ese procedimiento.

## F6 (MENOR) — dos fuentes para la versión mientras dure el cambio

Hoy la versión vive en un comentario de `metrics.py:472`. Si se añade el manifiesto y se deja el
comentario, hay dos sitios que pueden contradecirse. La tarea 5 lo resuelve haciendo que el
comentario **remita** al manifiesto en vez de repetir el número.

## Veredicto

F1 ya está corregido en el plan. F2 y F3 refuerzan tareas existentes sin cambiar el alcance. F4
verificado. F5 y F6 aceptados con su razón escrita. **El plan puede aprobarse.**
