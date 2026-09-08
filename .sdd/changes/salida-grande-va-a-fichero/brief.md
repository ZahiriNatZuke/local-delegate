# Brief: La salida grande va a fichero, no al contexto

## Problem

`suggest_lint_summary` decide con una regex sobre el texto del comando, **antes de ejecutarlo**,
así que no puede saber si la salida va a ser grande. Medido sobre 21 días de uso real
(`research.md`): **366 disparos, 1 acierto — puntería 0,3 %**, mediana de salida **402 bytes**.
Se lleva el **88 % de los 411 avisos** del periodo y su conversión es **cero delegaciones**.

Es además el único hook encendido **por defecto** en toda instalación, mientras el de lectura
—el que sí se arregló en el PR #146— es opt-in. El peor es el que recibe todo el mundo.

Y hay un mercado real que no está cazando: 42 salidas de Bash superaron 8 KB en la ventana
(~137 000 tokens), de las cuales unos 40–70 K son genuinamente delegables. La regex caza 1 de
esas 42. El mercado está en **logs y documentos**, no en lint ni en tests.

## Desired outcome

Que una salida grande de un comando **deje de entrar al contexto caro**, y que el aviso
—si sigue existiendo— acierte lo bastante como para no enseñar a ignorarlo.

Observable y medible con los instrumentos que ya existen:

- La telemetría del hook registra puntería, y sube de 0,3 % a un valor defendible.
- Las llamadas a `local_lint_summary` en `usage-YYYYMM.jsonl` dejan de ser cero.
- Ninguna salida útil se pierde: lo que hoy se trunca a 30 000 caracteres queda entero en disco.

## In scope

- Rehacer el criterio de disparo de `suggest_lint_summary`, que deja de ser una regex de nombres.
- Semilla curada **por ecosistema** (no por el perfil de esta máquina), como candidatos, no como
  disparador ciego.
- Capa de aprendizaje local: registrar `ejecutable -> tamaño de salida` observado, para que cada
  máquina se calibre a su perfil sin lista cerrada.
- Evaluar la reescritura del comando vía `updatedInput` para mandar la salida a fichero.
- Las superficies que arrastra: `install.py` (registro), `checks.py` (los tres probes), tests,
  recipes y wiki.

## Out of scope

- El hook de lectura (`suggest_delegate_read`), arreglado en el PR #146.
- El hook de prompt (`suggest_delegate_prompt`).
- `server.py::local_lint_summary`: ya acepta `path` y no trunca. Es la pieza correcta tal cual.
- `local_boilerplate` con `reference`/`target`: es otro cambio, con su propio valor.

## Constraints and risks

- **`updatedInput` se salta el allowlist de permisos** (verificado por ejecución: un comando
  permitido se reescribió a otro que no lo estaba y se ejecutó). Si se usa, la reescritura debe
  ser mínima, mecánica, auditable y desactivable.
- **Multiplataforma**: la redirección difiere entre PowerShell y bash, y esta máquina usa las
  dos. El repo ya se quemó una vez con el quoting de hooks en Windows (2026-07-30).
- **Escapes obligatorios**: no tocar comandos que ya redirigen o pipean, interactivos, ni con
  heredoc. En los datos hay un `ssh … <<EOF` que es exactamente el caso a no tocar.
- **Preservar el exit code**, o se rompe cualquier encadenamiento con `&&`.
- El hook corre en cada Bash del usuario: un fallo suyo degrada la sesión entera.
- El repo mezcla LF y CRLF; `suggest_delegate_read.py` es LF.

## Decisiones tomadas (2026-09-08)

1. **Se reescribe el comando** vía `updatedInput`. Es lo único que no depende de obediencia
   —tres mediciones seguidas dan cero— y lo único que esquiva el truncado a 30 000 caracteres.
   Se acepta el coste: intrusivo, elude el allowlist, exige acertar con el shell.
2. **Se apaga por defecto** hasta que la telemetría demuestre puntería. Hoy va encendido en toda
   instalación con 0,3 % de acierto, mientras el hook de lectura —mejor— es opt-in. Se invierte.

## Open questions

Quedan tres, todas técnicas y a resolver en la especificación:

1. Sintaxis y garantías de la reescritura: preservar exit code, escapes, y qué pasa si el
   comando no es reconocible.
2. Dónde vive el fichero de salida, quién lo limpia y cuánto sobrevive para recuperar el crudo.
3. Umbral, ventana, mínimo de muestras y almacén de la capa de aprendizaje.
