# Result review: install consume checks.CHECKS y anade --clients auto|claude,codex

Revisión en frío del diff completo contra los 18 requisitos aprobados, leyendo el código como si
lo hubiera escrito otro. Un hallazgo se encontró **en esta revisión** y se corrigió antes de
cerrar el gate.

## Verdict

`conforms-with-notes` — los 18 requisitos están implementados y verificados; queda una limitación
declarada (la respuesta afirmativa por teclado, §*Findings* N-1) que no impide el cierre.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 `--clients` en los dos verbos | `cli.py` `_add_common_install_args` (compartida) | sí | `uninstall --clients auto` con prueba propia |
| REQ-002 `auto` por presencia | `install.present_targets` | sí | definición única; `update._present_targets` delega |
| REQ-003 se imprime la resolución | `_run_install`, antes de escribir | sí | visto en las tres ejecuciones reales |
| REQ-004 `--target` vivo; combinar es error | `_resolve_clients` | sí | exit 2 sin escribir nada |
| REQ-005 sin clientes: nada, exit 0 | `_run_install` | sí | `snapshot(home) == {}`; el reporte sale igual |
| REQ-006 sin binario con HOME simulado | `_install_options` + `install.is_simulated_home` | sí | **verificado al revés** |
| REQ-007 HOME real intacto | idem | sí | SHA-256 idéntico tras `install` y `uninstall` |
| REQ-008 pregunta antes de reemplazar | `_decide_sobre_el_codex_ajeno` + `Options.skip_codex_mcp` | parcial | ver N-1 |
| REQ-009 sin tty no pregunta | `_hay_terminal` | sí | ejecutado de verdad en sh (camino EOF) |
| REQ-010 `--force-mcp-codex` | `_decide_sobre_el_codex_ajeno` | sí | ejecutado de verdad en cmd |
| REQ-011 `--dry-run` no pregunta | idem | sí | y lo anuncia |
| REQ-012 reporte siempre | `_reporte_del_andamiaje` | sí | **corregido en esta revisión**, ver F-1 |
| REQ-013 sin red ni binarios | `checks.run_all(groups=…)` | sí | dobles que revientan si se llaman |
| REQ-014 no altera el exit code | `_run_install` | sí | prueba propia |
| REQ-015 rótulo en `--dry-run` | `_reporte_del_andamiaje(dry_run=True)` | sí | prueba propia |
| REQ-016 garantías vigentes | sin cambios de comportamiento | sí | 20 pruebas previas verdes, aserciones intactas |
| REQ-017 documentación | README, wiki, recipe, CHANGELOG | sí | CRLF del CHANGELOG conservado (876/0) |
| REQ-018 dos textos falsos | `test_install.py`, wiki | sí | «doce piezas»; docstring reescrito con el porqué |

## Findings

### F-1 (corregido) — el reporte no salía cuando una acción fallaba

REQ-012 dice que el estado se imprime **siempre**, y el primer corte hacía
`if failures: return 1` **antes** de llamar al reporte. O sea que el único caso en que el usuario
no veía qué había quedado escrito era justo aquel en que algo se quedó a medias.

Corregido moviendo el reporte delante del código de salida, con prueba nueva
(`test_el_reporte_sale_tambien_cuando_una_accion_falla`, que dobla `plan_install` por una acción
que lanza `OSError` y afirma exit 1 **con** el reporte impreso). 416 tests verdes.

### N-1 (aceptado) — la respuesta «sí» por teclado no se ejecutó contra una terminal real

El agente no dispone de tty. Cubierto con `builtins.input` doblado en dos pruebas, y los tres
caminos que sí se ejecutaron de verdad (EOF en sh, `--force` en cmd, `--dry-run`) son los que
escriben o conservan sin intervención humana. El camino sin ejecutar es el menos peligroso: exige
confirmación explícita y su default es no tocar nada. Queda escrito en `verification.md`.

### N-2 (deliberado) — `uninstall` también imprime el reporte

REQ-012 habla de `install`, pero el código llega igual al reporte al desinstalar. Es un extra
coherente —enseña que el andamiaje quedó retirado— y no contradice ningún requisito.

### N-3 (deliberado) — `--dry-run` combinado con `--force-mcp-codex` anuncia el reemplazo

El orden de `_decide_sobre_el_codex_ajeno` mira `--force` antes que `--dry-run`, así que la salida
dice «se reemplaza». Es correcto: `--dry-run` describe lo que **haría**, y `install.apply` no
escribe nada en ese modo.

### N-4 (alcance) — dos ficheros del backlog siguen mal colocados

`scripts/update_to_latest.sh` (huérfano desde el PR #70) y `docs/recipes/update_agents.py`. Fuera
del alcance declarado de este change; siguen en el backlog.

## Required follow-up

Nada bloqueante para cerrar. Para la sesión, ya anotado fuera de este change:

- El icono de marca del header del **dashboard** (`web/metrics.py:900-914`) es un SVG inline
  anterior a la marca única; el favicon canónico vive en `resources/brand/favicon.svg` y ya se
  sirve en `/favicon.svg`. Change propio.
- Publicar esto es decisión del usuario: el change entra en `Unreleased`.
