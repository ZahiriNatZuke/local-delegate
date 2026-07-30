# Research: install consume checks.CHECKS y anade --clients auto|claude,codex

Base: `main` en `7c48328` (0.17.0 publicada, `Unreleased` vacío). Todo lo de abajo está
verificado por lectura del código citado o por ejecución en esta máquina (Windows 11, CLI
0.17.0).

## Current behavior

`install` es el único de los tres verbos del andamiaje que no consume el registro de
comprobaciones: planifica un conjunto fijo de acciones a partir de los flags y las escribe.
`doctor` (change A) y `update` (change B) ya salen de `checks.run_all`.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `src/local_delegate/install.py` | planifica y escribe a ciegas | `Options` gana HOME simulado y lanzador inyectable; respeta la entrada ajena de Codex | `install.py:311-316`, `:451-476`, `:568` |
| `src/local_delegate/cli.py` | arma `Options` desde los flags | `--clients` (default `auto`), `--target` como alias, resolución por presencia, reporte final | `cli.py:39-56`, `:74-86`, `:579-586` |
| `tests/test_install.py` | 20 pruebas, todas con `use_cli=False` | casos nuevos y hay que romper el molde actual (ver *Risks*) | `tests/test_install.py:16-25` |
| `tests/test_smoke.py` | ejercita el CLI de punta a punta | caso del flag nuevo | — |
| `docs/wiki/Integration-install.md` | documenta `--target` y el doctor | tabla de flags; y el «once piezas» con doce en la tabla | `:45`, `:79`, `:97-110` |
| `README.md`, `docs/recipes/claude-code-integration.md` | mencionan `--target` | mención al flag nuevo | `README.md:231`, recipe `:10` |
| `CHANGELOG.md` (`Unreleased`) | vacío | cambio de comportamiento del default | — |

**No se toca** `checks.py`: el registro se consume, no se amplía. Tampoco `doctor.py` ni
`update.py`.

## Existing conventions

### El ciclo de importación es real y ya tiene solución en el repo

`checks.py:33` hace `from . import config, install` **a nivel superior**. Un `import checks` a
nivel superior en `install.py` cerraría el ciclo. El repo ya resuelve esto en dos sitios por el
mismo motivo, documentado en `checks.py:80-83`: `_default_daemon_status` y
`_default_backend_models` importan `daemon` y `doctor` **dentro de la función**. `cli.py:116`
hace lo mismo con `checks`.

**Conclusión:** el consumo se resuelve en `cli.py` —que ya importa los dos sin ciclo— y a
`install.Options` le llega el dato ya calculado. Mantiene `install.py` como el módulo que
escribe y no le añade una dependencia nueva.

### El lanzador inyectable ya tiene forma canónica

`update.py:65-73` define `_default_runner` y el tipo `Runner`, con `Options.runner` resuelto en
`__post_init__` (`update.py:99-107`) y no como default de campo — con el porqué escrito: puesto
como valor por defecto, CodeQL lo lee como método y cuenta un `self` que no existe.

### El renderizado de checks ya existe

`doctor._print_group` (`doctor.py:302-310`) imprime `STATUS_LABEL[...] título: detalle` y, si es
aviso, la línea `arréglalo con:`. Ojo con `doctor.py:308-309`: **sin caracteres fuera de
cp1252**, porque una flecha `→` mata la consola de Windows.

### El precedente de «no escribir en clientes ausentes»

`update._present_targets` (`update.py:167-174`) y el marcador `PRESENT` (`update.py:122`,
`:158`), con el porqué escrito: «reinstalar el bloque de Codex en una máquina sin Codex crearía
`~/.codex/AGENTS.md` de la nada».

## Dependencies and integrations

Ninguna dependencia nueva. Todo el cambio se apoya en módulos internos (`checks`, `install`,
`cli`) y en la stdlib (`argparse`, `subprocess`, `pathlib`). No toca el SDK `mcp`, ni el
daemon, ni el backend, ni la red.

Frontera de configuración relevante: `claude mcp add-json --scope user` escribe en el
`~/.claude.json` del usuario que ejecuta, **fuera** de cualquier `--home` que se le pase.

## Los cuatro defectos, con su línea

### 1. El default escribe en clientes ausentes

`cli.py:43-44`:

```python
selected = args.target or ["all"]
targets = set(_ALL_TARGETS) if "all" in selected else set(selected)
```

Con eso, `plan_install` entra en `install.py:401-441` y crea `~/.codex/AGENTS.md` y
`~/.codex/config.toml` aunque `~/.codex` no exista — `_write_text` hace
`path.parent.mkdir(parents=True, exist_ok=True)` (`install.py:107`). No es hipotético: es lo
que pasa hoy en cualquier máquina con un solo cliente.

### 2. `install --home` escribe en el HOME real — **confirmado en esta máquina**

`install.py:451`: `if opts.use_cli and shutil.which("claude"):` → `claude mcp add-json --scope
user`. El flag `--scope user` es global por definición.

Comprobado por ejecución aquí:

```
> (Get-Command claude).Source
C:\Users\Yohan\.local\bin\claude.exe
```

O sea que en esta máquina el camino de la CLI **se toma**, y `local-delegate install --home
C:\tmp\x` escribiría en el `~/.claude.json` de verdad. `cli.py:55` solo mira `--no-client-cli`;
`--home` no interviene.

`update` ya lo arregló (`update.py:230-237`) y dejó escrito cómo se descubrió: ejecutándolo dos
veces contra un HOME temporal y viendo que la segunda pasada volvía a planificar la misma
acción mientras la config real sí se había reescrito.

`uninstall` tiene el mismo defecto en `_unregister_claude_mcp` (`install.py:568`): con `--home`
simulado desregistraría el MCP **de verdad**. Es el más dañino de los dos, porque destruye
configuración en vez de duplicarla.

### 3. `install` pisa la entrada de Codex puesta a mano

`upsert_codex_mcp` (`install.py:311-316`) empieza por `remove_block(...)` y sigue con
`_CODEX_SECTION_RE.sub("", text)`: borra **cualquier** `[mcp_servers.local-delegate]`, tenga
marcadores o no. Ese es justo el caso que `checks._probe_mcp_codex` reporta `warn`
(`checks.py:392`) y por el que `update` se niega a reparar en `warn` — la única excepción de su
tabla, comentada en `update.py:160-163` como «el fallo contra el que existe la regla de
`unknown`».

Matiz que la spec tiene que resolver, y que separa a `install` de `update`: aquí el usuario
**pidió instalar explícitamente**, mientras que `update` repara por iniciativa propia. Que
`install` se niegue en seco sería obstinado; que pise sin avisar es el fallo.

### 4. `install` no verifica nada al terminar

`cli.py:74-86` cuenta `failures` de `inst.apply` y, si es cero, imprime «Listo. Reinicia el
cliente…». Una acción puede «no fallar» y aun así dejar el andamiaje incompleto (el caso claro:
el MCP registrado por CLI en otro HOME del que se pidió). Hoy hay que ejecutar `doctor` aparte.

## Risks and unknowns

### Confirmado: la suite no puede ver el bug del HOME

`tests/test_install.py:16-25`, el helper que usan **todas** las pruebas del fichero:

```python
def _opts(home: Path, **kw) -> inst.Options:
    base = dict(
        ...
        use_cli=False,  # jamás invocar el binario `claude` real desde la suite
    )
```

La precaución es correcta —la suite no debe lanzar `claude.exe`— pero tiene una consecuencia que
nadie anotó: **el camino de la CLI no se prueba nunca**, y es exactamente donde vive el defecto.
Las 20 pruebas del fichero pasarían igual con el bug puesto o quitado. Mismo patrón que ya costó
caro con `local_extract` (seis tests, todos con `text=`, mientras el bug vivía en `path=`).

La forma de cubrirlo sin ejecutar nada real es **inyectar el lanzador**: hoy `install.py` llama
a `subprocess.run` directamente (`install.py:453`, `:459`, `:571`), sin punto de doblaje.

### Confirmado: dos desfases de documentación

1. **`tests/test_install.py:270-273`** repite el comentario que ya se demostró **falso**: «la
   recipe vieja documentaba `{"command":"python","args":[…]}`, formato que Claude Code no
   ejecuta: esas entradas quedaban muertas». Está corregido en `install.py:173-177` y en
   `checks.py:296-299` (es el *exec form*, se ejecuta, verificado en vivo dos veces), pero el
   docstring del test sobrevivió. Es la clase de comentario que ya provocó un falso positivo en
   el change A (PR #55).
2. **`docs/wiki/Integration-install.md:79`** dice «comprueba de una vez las **once** piezas» y la
   tabla de abajo lista **doce**. `tests/test_checks.py:418-438` cubre los cuatro sitios donde el
   módulo dice su tamaño, pero no la wiki.

Los dos son de una línea y caen dentro del alcance natural del change.

### Riesgos de diseño y su acotación

| Riesgo | Acotación |
|---|---|
| `install` degenera en un segundo `update` | `checks` decide **a quién** se escribe y **qué no se pisa**; nunca **si** se escribe. Un `install` sobre un andamiaje sano lo reescribe entero igual |
| Ciclo de importación | el consumo se resuelve en `cli.py`; `install.py` no gana dependencia nueva |
| Romper a quien use `--target` | se conserva como alias funcional, con prueba propia |
| El default nuevo sorprende | se imprime siempre qué clientes se resolvieron y por qué |
| Escribir fuera del HOME simulado | `Runner` inyectable + prueba que afirma que **no** se invoca el binario con `--home` simulado, verificada al revés |
| Consola de Windows | ni un carácter fuera de cp1252 en la salida nueva |

### Queda para la especificación

- Nombre y semántica exacta del flag de escape para el caso «puesto a mano».
- Si `--clients auto` sin ningún cliente presente es error (exit 2) o aviso con exit 0.
- Si el reporte final es incondicional o solo cuando algo no quedó `ok`.
