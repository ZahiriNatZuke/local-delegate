# Brief: Guard de Codex: escrituras de shell sobre ficheros resumidos

## Problem

En la prueba real de #670 (Codex CLI 0.171, Windows), Codex editó un `.md` guardado con `[System.IO.File]::WriteAllText` y la ruta en una variable `$p`; el guard solo veía `apply_patch` y las escrituras que ya contaba el clasificador (#724).

## Desired outcome

Las escrituras de shell (PowerShell, cmd, bash) sobre un fichero guardado se rechazan con el mismo aviso que `apply_patch`, sin falsos positivos.

## In scope

- `src/local_delegate/codex_reads.py`, tests nuevos, wiki, CHANGELOG, léxico de nombres.

## Out of scope

- `read_classifier` (compartido con Claude Code), borrados, `perl -i`/`python -c`.

## Log

- L1 2026-11-23 Original request, verbatim:

  > Issue #724 (de #670): el guard de escritura de codex-tool-guard no ve las escrituras de shell de PowerShell (.NET [IO.File]::WriteAllText/WriteAllLines/AppendAllText, rutas en variables $p, New-Item -Value, Clear-Content) ni las envueltas en cmd /c, bash -c o powershell -Command; que las bloquee con el mismo aviso que apply_patch, sin falsos positivos y sin bloquear lo que no se pueda analizar.
- L2 2026-11-23 18:20 (UTC-3) Spec y plan escritos tras localizar el guard (`codex_reads.write_targets`) y medir los huecos con una sonda.
- L3 2026-11-23 18:55 (UTC-3) Implementado; 50 tests rojos antes y verdes después; hook real por stdin con la orden de #724: `deny`.
