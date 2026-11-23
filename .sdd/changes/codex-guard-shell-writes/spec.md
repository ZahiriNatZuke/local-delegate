# Specification: Guard de Codex: escrituras de shell sobre ficheros resumidos

## Summary

El guard de escritura de `codex-tool-guard` (#670) rechaza un `apply_patch` sobre un fichero que
el agente solo leyó resumido, pero no ve varias formas de escribir desde la shell que Codex usa en
Windows (#724): la API de .NET desde PowerShell (`[System.IO.File]::WriteAllText(...)`), la ruta
guardada antes en una variable (`$p = 'x.md'`), `New-Item -Value`, `Clear-Content`, y las órdenes
envueltas en `cmd /c`, `bash -c` o `powershell -Command`. Tras el cambio, esas escrituras sobre un
fichero guardado se rechazan con el mismo aviso que `apply_patch`; una lectura, o una escritura a
otro fichero, pasan; y lo que no se puede analizar con seguridad pasa como hoy.

Lo nuevo vive en `codex_reads.py` y reutiliza el analizador de `read_classifier` (`tokenize`,
`segments`, `_verb`, `_operands`, `_flag_value`, `resolve`) sin cambiarlo: el clasificador lo
comparten los hooks de Claude Code y su comportamiento no se toca.

## Requirements

- **REQ-001** — Una llamada de .NET de escritura (`WriteAllText`, `WriteAllLines`,
  `WriteAllBytes`, `AppendAllText`, `AppendAllLines`, `Create`, `CreateText`, `AppendText`,
  `OpenWrite` sobre su primer argumento; `Copy`, `Move`, `Replace` sobre el destino) de
  `[System.IO.File]`, `[IO.File]` o `[File]` sobre un fichero guardado se rechaza con
  `codex.guard.refused`. La ruta vale como literal entre comillas, variable o
  `(Resolve-Path [-LiteralPath|-Path] …)` (también con `.Path`/`.ProviderPath`).
  - Request: "visto: `[System.IO.File]::WriteAllText(...)`; probables: ... `[IO.File]::WriteAllLines`/`AppendAllText`"
  - Verify: test tests/test_codex_guard_shell_writes.py
- **REQ-002** — Una ruta en una variable asignada en la misma orden a un literal
  (`$p = 'x.md'` en PowerShell, `p=x.md` en bash) se resuelve para las escrituras de shell
  (`Set-Content $p`, `> $p`, .NET) y para las lecturas literales que levantan el guard
  (`Get-Content $p -TotalCount 40`). Una variable asignada a algo que no es un literal, a dos
  valores distintos, ligada por un bucle, `read`, `param`, `Set-Variable`, `-OutVariable` o `[ref]`
  no se resuelve.
  - Request: "la ruta en una variable (`$p`)" (#724, hueco 2)
  - Verify: test tests/test_codex_guard_shell_writes.py
- **REQ-003** — `New-Item` con `-Value` (o `-Force` sin `-ItemType` de directorio),
  `Clear-Content` y `Tee-Object -FilePath` sobre un fichero guardado se rechazan; las formas que ya
  se veían (`Set-Content`, `Add-Content`, `Out-File`, `>`, `>>`, `tee`, `sed -i`, `cp`, `mv`,
  `Copy-Item`, `Move-Item`, `copy`, `move`) siguen rechazándose.
  - Request: "`Set-Content`, `Out-File`, `Add-Content`, `>`/`>>`, ... `New-Item -Value`, `Copy-Item`/`Move-Item` sobre el fichero"
  - Verify: test tests/test_codex_guard_shell_writes.py
- **REQ-004** — Una orden envuelta en `cmd /c`/`cmd /k`, `bash -c`/`sh -c` (también `-lc`) o
  `powershell`/`pwsh` `-Command`/`-c` se analiza por dentro: sus escrituras se rechazan y sus
  lecturas literales levantan el guard. `-EncodedCommand` no se analiza.
  - Request: "Que el guard reconozca las escrituras de shell (PowerShell, cmd y bash ...)"
  - Verify: test tests/test_codex_guard_shell_writes.py
- **REQ-005** — Sin falsos positivos: una lectura del fichero guardado (incluida `ReadAllText`),
  una escritura a otro fichero, un nombre de método de escritura dentro de una cadena entre
  comillas simples, y una ruta que no se puede saber (expresión, `Join-Path`, `"$dir\x.md"`,
  variable sin literal, ruta relativa de .NET tras un `cd`/`Set-Location`) no se rechazan.
  - Request: "Sin falsos positivos: una lectura o una escritura a OTRO fichero no se bloquean; ante una orden que no se puede analizar con seguridad, no bloquear"
  - Verify: test tests/test_codex_guard_shell_writes.py
- **REQ-006** — El análisis es lineal en la longitud de la orden (sin expresiones regulares con
  retroceso catastrófico): una orden hostil de 200 000 caracteres se decide en menos de 2 s.
  - Request: "nada de expresiones regulares con retroceso catastrófico sobre la orden"
  - Verify: test tests/test_codex_guard_shell_writes.py
- **REQ-007** — Con el JSON de evento `PreToolUse` real de Codex (forma de la fixture
  `pre_tool_use_bash`, `tool_name: Bash`) y la orden de #724 (`$p` + `ReadAllText` +
  `WriteAllText`), el proceso del hook (`codex_reads.run` por stdin) imprime la denegación.
  - Request: "prueba el hook a mano alimentándolo con el JSON de evento real que Codex manda ... con una orden `WriteAllText` real"
  - Verify: cmd hook alimentado por stdin, salida en evidence/
- **REQ-008** — La docstring del módulo, la wiki de Codex y el CHANGELOG («Sin publicar») dicen
  qué formas ve el guard y cuáles no (límites documentados).
  - Request: "ante una orden que no se puede analizar con seguridad, no bloquear (mismo criterio que hoy) y documentarlo"
  - Verify: review diff de docs y CHANGELOG

## Acceptance scenarios

### Scenario: escritura de .NET con la ruta en una variable

- **Given** `notes.md` (prosa grande) leído solo resumido en la sesión
- **When** Codex manda `$p = 'notes.md'` + `[System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $p), $s)`
- **Then** el hook responde `deny` con el aviso de leer un tramo literal

### Scenario: control

- **Given** el mismo estado
- **When** la orden escribe `other.md` o solo lee `notes.md`
- **Then** el hook no la rechaza

## Edge cases and failure behavior

- Paréntesis sin cerrar, comillas sin cerrar o argumentos raros: la llamada no se cuenta (pasa).
- Una ruta relativa de .NET con un `cd` en la misma orden: .NET resuelve contra el directorio del
  proceso, no la ubicación de PowerShell; no se sabe y pasa.
- Cualquier excepción del análisis la recoge `run`, que ya deja pasar la llamada.

## Non-functional requirements

- Sin regresiones: los tests existentes de `tests/test_codex_reads.py` y del clasificador no cambian.
- Sin contenido de ficheros en el estado ni en los avisos.

## Non-goals

- Borrados (`rm`, `Remove-Item`): no editan a partir del resumen; no se tocan.
- `perl -i`, `python -c "open(..., 'w')"`, `dd of=`, `truncate`, `[IO.File]::Open(...)` con modo,
  `StreamWriter`/`New-Object`, rutas compuestas: no se analizan (documentado).
- Cambiar lo que `read_classifier` (Claude Code) clasifica. Solo se reescribe, con el mismo resultado, la búsqueda de here-strings, que era cuadrática (revisión de #724; ver REQ-006).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
