# Brief (modo ligero): el comando del hook se rompe en Windows y bloquea cada prompt

## Qué pasó

`local-delegate install` dejó el cliente **inutilizable** en Windows. `hook_command` registraba:

```
python C:\Users\Yohan\.claude\hooks\local-delegate\suggest_delegate_prompt.py
```

Claude Code entrega ese `command` a un **shell**, y el shell interpreta cada `\` como escape y lo
borra. Lo que le llega al intérprete es:

```
python.exe: can't open file 'C:\\UsersYohan.claudehookslocal-delegatesuggest_delegate_prompt.py'
```

Y como el hook es `UserPromptSubmit`, no degrada nada: **bloquea todos los prompts del usuario**
(«UserPromptSubmit operation blocked by hook»). Hubo que borrar los hooks a mano para poder
escribir.

Reproducción mínima, sin adivinar:

```
$ sh -c 'echo python C:\Users\Yohan\.claude\hooks\x.py'
python C:UsersYohan.claudehooksx.py          # ← se comió las barras
$ sh -c 'echo python "C:/Users/Yohan/.claude/hooks/x.py"'
python C:/Users/Yohan/.claude/hooks/x.py     # ← intacto
```

`_quote` solo ponía comillas si la ruta tenía **espacios**, y una ruta de Windows normalmente no
los tiene. El hook de otro producto que el usuario ya tenía registrado —`node "C:/Users/.../
pre-tool-use.js"`— sí funcionaba: comillas y barras `/`.

## Ironía a registrar

El PR #55 corrigió la afirmación «el formato con `args` no se ejecuta». Este bug la remata desde el
otro lado: **el formato heredado era el que funcionaba** (exec form, sin shell) y el «moderno» con
string de shell es el que estaba roto en Windows. Dos veces seguidas, el repo afirmaba lo contrario
de la realidad sobre el mismo tema.

## El fix

`hook_command` cita **siempre** y usa `as_posix()`. Python abre rutas con `/` en Windows sin
problema, y la forma citada funciona en sh, cmd y PowerShell, en los tres sistemas.

De paso, un segundo falso positivo encontrado el mismo día: `doctor` decía **CAÍDO** sobre un
llama-swap vivo que respondía **401** por falta de credencial en ese entorno. `backend_probe()`
ahora distingue «no responde» de «responde 401/403», y el check lo reporta `[ -- ]` con el motivo
en vez de mandar a arrancar un servicio que ya corre.

## Verificación

- `tests/test_install.py::test_hook_command_survives_a_windows_path` — la ruta exacta del bug, sin
  un solo `\` en el resultado, y `shlex.split` devolviendo la ruta entera.
- `tests/test_checks.py::test_backend_401_is_unknown_not_down`.
- **Por ejecución en la máquina donde falló:** el comando arreglado corre y emite su
  `additionalContext` con exit 0; el `doctor` pasa a decir «arriba (rechaza la credencial de este
  entorno)».
- 312 tests, lint, formato y `node --check` verdes.

## Qué queda

- El usuario tuvo que borrar sus hooks para desbloquearse; hay que volver a registrarlos (el
  clasificador del harness impide que el agente escriba en `~/.claude/settings.json`).
- Un `install` con esta versión ya los deja bien; conviene probarlo end-to-end en Windows antes de
  publicar.
