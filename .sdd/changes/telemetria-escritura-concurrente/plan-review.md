# Revisión adversarial del plan

**Limitación declarada: la revisión no es independiente** — la hace el mismo agente que escribió el
plan. Sirve para cazar premisas sin verificar; no sustituye a un revisor ajeno.

## F1 (CORREGIDO EN EL PLAN) — un error del cerrojo que no es «ocupado» no debe hacer esperar

En un sistema de ficheros que no admita cerrojos de rango (red, FAT) `msvcrt.locking` o `flock`
pueden fallar con otro `errno` (EINVAL, ENOLCK, EOPNOTSUPP). Reintentarlo durante todo el plazo
haría esperar al hook ~1 s en cada línea sin ganar nada. Decisión: solo se reintenta con los errores
de «ocupado» (EACCES/EDEADLK en Windows, EAGAIN/EWOULDBLOCK/EACCES en POSIX); con cualquier otro se
escribe en el acto sin cerrojo, como hoy.

## F2 (VERIFICADO) — el byte del cerrojo no puede estar en los datos

En Windows el cerrojo de rango es obligatorio: si se cerrara el byte 0, un lector (panel,
`already_recorded`) fallaría al leer el principio. Se cierra un byte en 2**62, que ningún fichero
alcanza. Probado en esta PC: el segundo handle recibe errno 13, la escritura cae al final y la
lectura no se ve afectada.

## F3 (VERIFICADO) — hilos del mismo proceso también se excluyen

El daemon escribe desde varios hilos. Cada `append_line` abre su propio descriptor: en Windows el
cerrojo es por handle y en POSIX `flock` es por descripción de fichero abierta, así que dos hilos se
excluyen igual que dos procesos. REQ-002 lo prueba.

## F4 (IMPORTANTE) — el test tiene que fallar sin el arreglo, no por suerte

Con 6x300 la pérdida medida fue 10-16 % en tres corridas; el test usa 6x400 con barrera de inicio y
exige igualdad exacta. Antes del arreglo se corre tres veces y se anota el assert que dispara. En
POSIX (CI ubuntu/macos) el `write` con `O_APPEND` del texto ya suele ser atómico y el test puede
pasar también sin el arreglo: allí el test es de no regresión, y el control positivo es el de
Windows. Queda dicho, no vendido como discriminante en todas las plataformas.

## F5 (LÍMITE CONOCIDO) — copias viejas de los hooks sin cerrojo

La entrega por settings copia `hook_common.py`; una copia vieja sigue escribiendo sin cerrojo hasta
reinstalar. Su línea puede partirse contra una nueva; la reparación del `\n` final (REQ-006) evita
que una línea partida se trague la siguiente.

## F6 (ACEPTADO) — el recorte de las notas de bloqueo se reescribe en el sitio

Con el cerrojo, `record_block` añade mientras haya sitio y, al llegar a `MAX_NOTES`, reescribe la
mitad más reciente. Un lector que lea justo durante esa reescritura (1 de cada 100 notas) puede ver
el fichero a medias y perder una correlación ese instante; la nota sigue en disco para la siguiente
lectura. Hoy pasa en cada escritura una vez lleno.

## F7 (VERIFICADO) — `mod/read.js` fuera de alcance, con motivo

La API del mod no tiene `append` (`$.fs.read|write|stat`), y ese camino solo se usa cuando el daemon
y el proceso ya fallaron. Otro agente toca hoy hooks y mod. Se informa como riesgo residual y
seguimiento; no se toca.

Veredicto: sin hallazgos bloqueantes tras F1.
