# Revisión del resultado — `codex-config-local`

## Verdict

`conforms`

## Specification comparison

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 `codex mcp list` no aborta dentro del repo | sí | sí | exit 0; antes fallaba con `url is not supported for stdio` |
| REQ-002 los cinco MCP del repo + `local-delegate` | sí | sí | `MCP_DOCKER`, `codegraph`, `git`, `socket-mcp`, `jetbrains`, y `local-delegate` en `http://127.0.0.1:9393/mcp` |
| REQ-003 `github` una sola vez, HTTP, global | sí | sí | `https://api.githubcopilot.com/mcp/`, `Auth: Bearer token` |
| REQ-004 `rtk` resoluble en el sandbox | sí | sí | `Get-Command rtk` → `.local\bin\rtk.cmd`; `rtk 0.34.0`, exit 0 |
| REQ-005 sin duplicar el binario | sí | sí | shim de 1 línea a `%USERPROFILE%\rtk.exe`; ni copia ni hardlink |
| REQ-006 el repo no se ensucia | sí | sí | `git status --short` solo `?? .sdd/changes/codex-config-local/` |

## Findings

1. **La spec corrigió el diagnóstico heredado, y eso cambió la solución.** El backlog atribuía el
   fallo de `rtk` al PATH; la medición dentro del sandbox lo desmiente (el PATH estaba bien y el
   binario se ejecutaba por ruta absoluta). Las dos vías apuntadas de antemano no habrían arreglado
   nada. Sin la comprobación por ejecución se habría «arreglado» sin efecto.
2. **`codex sandbox` resultó ser la herramienta de diagnóstico correcta**, y vale para el futuro:
   reproduce el entorno restringido del agente **sin gastar cuota del modelo**. Todo el diagnóstico
   de `rtk` salió de ahí.
3. **REQ-002 comprueba resolución de configuración, no arranque de cada servidor.** `codex mcp list`
   demuestra que la config carga y qué entradas hay; no levanta los seis procesos. Es lo que pedía el
   requisito, pero conviene que quede dicho: si un stdio del repo estuviera roto por otra causa, esta
   evidencia no lo vería.
4. **Sin hallazgos de seguridad.** No se relajó el sandbox, no se tocó `auth.json`, y de las
   variables del bearer solo se leyó su existencia. Los dos ficheros modificados están fuera de git
   (`.gitignore:32` cubre `.codex/`, `.bak` incluido).
5. **Alcance respetado.** No se tocó código del proyecto, ni el `AGENTS.md` de Codex, ni la
   instalación de `rtk`. Los cuatro checks del CI se corrieron igual y siguen verdes (277 tests).

## Required follow-up

Nada bloqueante para cerrar. Para el backlog, sin urgencia:

- **Codex Desktop sin comprobar** (solo se probó el CLI bundled). Comparten `config.toml`, así que el
  arreglo de `github` debería aplicarle; queda junto al fleco ya conocido de probar `path`
  server-side desde Codex.
- **Anotar la regla en memoria**: redefinir en un `.codex/config.toml` de proyecto un servidor que ya
  existe en la global **con otro transporte** aborta la carga de MCP entera; la vía correcta es otro
  nombre de servidor.
