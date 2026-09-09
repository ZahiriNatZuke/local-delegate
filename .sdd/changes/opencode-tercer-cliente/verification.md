# Verification: opencode como tercer cliente de `install`

Todo lo de aquí está **ejecutado**, no razonado. Fecha: 2026-08-02.

## Suite y estática

```
uv run pytest -q          → 701 passed, 4 skipped, 1 failed
uv run ruff check .       → All checks passed!
uv run ruff format --check → 74 files already formatted
scripts/extract_dashboard_js.py → exit 0
scripts/check_install_e2e.py    → instalador OK en linux
```

El `1 failed` es **anterior a este change** y ambiental, no una regresión:
`test_unreadable_file_is_unknown_not_missing` hace `chmod 000` sobre un fichero y espera no poder
leerlo; este entorno corre como **root**, y root lo lee igual. Medido en el baseline **antes** de
tocar nada: `1 failed, 667 passed`. Después: `1 failed, 701 passed` — el mismo fallo y **34 tests
nuevos**.

## Verificación al revés (mutación dirigida)

Ocho mutantes, uno por invariante nueva. Cada uno se introdujo, se corrió la suite y se revirtió.
**Los ocho rompen su propio test**, y ninguno pasó desapercibido:

| Mutante | Resultado |
|---|---|
| `tiene_comentarios` → `"//" in texto` (el atajo ingenuo) | CAZADO |
| `opencode_config_target` → siempre `.jsonc` | CAZADO |
| `opencode_dir` → respeta `XDG_CONFIG_HOME` también con HOME simulado | CAZADO |
| `_register_opencode_mcp` → se fía solo del `returncode` | CAZADO |
| `_motivo_para_no_escribir` → deja de proteger los comentarios | CAZADO |
| entrada de opencode → escribe `${VAR}` en vez de `{env:VAR}` | CAZADO |
| `_opencode_mcp_entry` → mira solo el primer fichero | CAZADO |
| lectura tolerante (`_read_text`) en vez de `_leer_config_opencode` | CAZADO |

## Un defecto encontrado en la propia revisión

El octavo mutante no es hipotético: **es el código que había escrito**. Al releer el diff antes de
cerrar, `_register_opencode_mcp` leía el fichero con `_read_text`, que devuelve `""` tanto para un
fichero **vacío** como para uno que **no se pudo abrir**. Con ese `""`, la comprobación de
seguridad daba vía libre y se escribía un config nuevo **encima del que no se pudo leer** — justo
la destrucción que este camino existe para evitar, y en el único caso en el que el usuario no
podría ni ver qué pasó.

Arreglado con `_leer_config_opencode`, que distingue las dos cosas, y con un test que **simula** el
fallo de lectura en vez de hacer `chmod 000`: el `chmod` no quita la lectura ni en Windows ni como
root, así que un test escrito así habría pasado sin reproducir el caso — que es exactamente cómo
este defecto llegó a existir.

## Un segundo defecto, encontrado revisando el diff desde Windows (2026-08-02)

**El probe de la skill miraba solo `~/.claude/skills/` mientras `plan_install` la escribía en los
dos clientes.** Con Claude Code presente eso no era un hueco de cobertura: era un **falso OK**.
Medido por ejecución, con la skill de opencode borrada a mano:

```
[ OK ] skill delegacion-local: instalada en <sim>\.claude\skills\delegacion-local
Nada que reparar: el andamiaje está completo y los pines al día.
```

`doctor` daba por buena la de Claude Code y `update` no tenía a quién reponerle nada, porque
`Repair("scaffold.skill", …)` seguía fijando `frozenset({"claude"})`. Para la **memoria** sí se
había hecho el trabajo equivalente —`_probe_memory` pasó a recorrer `_clientes()`— y el comentario
que se escribió en esa misma función dice que tener la lista dos veces «es como se cuela un cliente
que se detecta pero al que nadie le comprueba la memoria». A la skill le pasó exactamente eso.

Arreglado: `_probe_skill` recorre `_clientes()` con el mapa de dónde vive la skill en cada uno
(Codex no está: no tiene skills y `plan_install` no se la escribe), y el `Repair` pasa a `PRESENT`,
el mismo marcador que ya usaba `scaffold.memory` por la misma razón.

**Un test pasaba por la guarda equivocada.** `test_only_codex_installed_leaves_claude_checks_unknown`
se llama «solo Codex» pero usaba el default `opencode=True` de `make_home`: el HOME tenía dos
clientes. Pasaba porque el probe no miraba opencode; en cuanto empezó a mirarlo, la skill de
opencode lo puso en `ok` y el nombre del test quedó desmentido. Ahora pasa `opencode=False`
explícito.

Tres mutantes nuevos, cada uno cazado por su propio test:

| Mutante | Resultado |
|---|---|
| `_probe_skill` vuelve a mirar solo Claude Code | CAZADO (2 tests) |
| `Repair("scaffold.skill")` vuelve a fijar `{"claude"}` | CAZADO |
| Codex entra en el mapa de skills | CAZADO |

**Ruido de fin de línea.** Cuatro ficheros (`README.md`, `docs/wiki/Integration-install.md`,
`cli.py`, `install.py`) pasaron de CRLF a LF al editarse desde un runner Linux, lo que inflaba el
diff de 2 213 a 4 340 líneas y habría roto el `git blame` de los dos módulos más grandes del repo.
Devueltos a CRLF. Normalizar el repo entero con `* text=auto` es una decisión aparte, no un efecto
colateral de este change.

## Verificación en Windows (2026-08-02)

Lo que la sección «lo que NO se ha verificado» daba por pendiente, ejecutado:

```
uv run pytest -q            → 710 passed, 2 skipped
uv run ruff check .         → All checks passed!
uv run ruff format --check  → 74 files already formatted
scripts/check_install_e2e.py → instalador OK en win32
```

Sin el `1 failed` de Linux: ese fallo era el `chmod 000` que no quita lectura al root, y en Windows
el test está marcado `skipif`. Los 710 incluyen los tres nuevos de la skill.

## Contra el cliente real (opencode 1.18.11)

Esto es lo que distingue la verificación de este change de una de papel: no se comprueba que
escribimos un fichero con la forma que **creemos** correcta, sino que **el cliente lo acepta**.

**1. De punta a punta, instalando con el comando de verdad:**

```
$ uv run local-delegate install --home <sim> --clients opencode
  [ OK ] MCP en opencode: registrado en <sim>/.config/opencode/opencode.jsonc (local [...])

$ HOME=<sim> opencode mcp list
  ✓ local-delegate connected
      uvx --from local-delegate-mcp local-delegate-mcp
```

**2. El camino por la CLI del cliente, con el binario real en el PATH**, en los dos transportes y
sobre un config con comentarios y una clave `theme` del usuario:

```
stdio -> registrado con `opencode mcp add`
http  -> registrado con `opencode mcp add`
```

Resultado en disco: **una sola** entrada (la segunda pasada reemplazó a la primera — idempotencia),
el `// comentario que la CLI debe conservar` intacto y `"theme": "mio"` intacto.

**3. Lo que se aprendió midiendo y cambió el diseño:** la CLI **no** escribe `"enabled": true`.
Nuestra entrada lo llevaba, así que el `literal` del `--dry-run` prometía una clave que por el
camino de la CLI no aparecía. Se quitó: `enabled` en `true` es el default y no dice nada, y ahora
los dos caminos dejan exactamente la misma forma.

**4. El `--dry-run` dice la verdad**, que es lo único revisable antes de tocar disco:

```
[dry-run] [mcp] opencode — registra el servidor MCP 'local-delegate' (stdio)
          {"local-delegate": {"type": "local", "command": ["uvx", ...],
           "environment": {"LOCAL_DELEGATE_API_KEY": "{env:LOCAL_DELEGATE_API_KEY}"}}}
```

byte a byte igual a lo que acaba en el fichero.

## Requisitos cubiertos

Los 34 de `spec.md`. Los que no tienen test unitario propio están cubiertos por el e2e o por
inspección directa del artefacto:

- REQ-011 (ninguna clave fuera de `mcp`) → `test_nunca_se_escribe_una_clave_de_primer_nivel_ajena_al_esquema`,
  y medido aparte que una clave desconocida tumba el arranque del cliente.
- REQ-020 (no crear `~/.claude` instalando solo opencode) → `test_instalar_solo_opencode_no_crea_los_otros_dos`.
- REQ-028 (el probe no escribe) → `test_el_probe_de_opencode_no_escribe_nada`, con el árbol del
  HOME comparado byte a byte.
- REQ-029 (frases de tamaño) → `test_el_docstring_dice_cuantos_checks_hay_de_verdad`, con
  `17: "diecisiete"` en `_NUMERO`.
- REQ-031 (cp1252) → la salida nueva es ASCII salvo acentos, que sí están en cp1252.
- REQ-032/033/034 (documentación) → `tests/test_wiki.py` y `tests/test_site.py` en verde.

## Lo que NO se ha verificado, y por qué

- ~~**Windows y macOS.**~~ Windows queda verificado arriba (suite, estática y e2e). macOS sigue
  cubierto solo por el runner del CI. Lo específico de plataforma en este change es una ruta
  (`~/.config/opencode`) que opencode resuelve igual en los tres —usa XDG también en Windows, que
  es un comportamiento suyo conocido y algo que ellos mismos tratan como bug abierto—, así que el
  riesgo restante está acotado.
- **El camino por CLI bajo `--home`.** Está apagado a propósito (`use_cli=False` con HOME simulado)
  para que la suite no dependa de qué binarios haya en la máquina. Se ejercitó a mano, con el
  binario real, llamando a `_register_opencode_mcp` directamente (punto 2 de arriba).

## Revalidación para el cierre (2026-09-08)

El código lleva en `main` desde el PR #123 y la evidencia de arriba es del 2 de agosto. Antes de
cerrar los gates se **volvió a medir todo**, contra el árbol de hoy y contra el binario de hoy. No
se reutilizó ni una línea de la evidencia anterior.

### Suite y estática, hoy

```
uv run pytest -q             → 794 passed, 2 skipped
uv run pytest tests/test_install_opencode.py -q → 36 passed
uv run ruff check .          → All checks passed!
uv run ruff format --check   → 77 files already formatted
scripts/extract_dashboard_js.py → exit 0
scripts/check_install_e2e.py    → instalador OK en win32
```

Los `710 passed` de agosto eran de un árbol con 84 tests menos. Los 36 propios de este change
siguen todos en verde.

### Los ocho escenarios de aceptación, reejecutados

Corridos con el CLI de verdad sobre HOMEs simulados, comprobando el artefacto en disco:
**26 de 26 comprobaciones en verde**. Cubren los siete escenarios de `spec.md` que no dependen del
binario del cliente: solo-opencode (sin crear `.claude` ni `.codex`), idempotencia con `theme` y
entrada MCP ajena, comentarios sin CLI (fichero intacto byte a byte, exit code sin subir, y el
aviso con ruta + motivo + qué hacer), HTTP con `{env:LOCAL_DELEGATE_WEB_TOKEN}` y **sin** el valor
del token en disco, desinstalación que deja la entrada ajena y el `theme`, config roto que no se
toca, y `--home` con `XDG_CONFIG_HOME` puesta escribiendo dentro del árbol simulado.

**Control positivo:** con `--no-mcp --no-skill` el fichero de config no llega a existir, así que
una comprobación que diera `ok` sin haberse escrito nada se caería sola. Se verificó.

**REQ-030, medido y no razonado:** con la entrada MCP y la skill borradas a mano, `doctor` las da
las dos por `[FALT]` y `update` las repone; el `doctor` posterior las da por `[ OK ]`. De paso se
observó que `update` repone en el transporte que corresponde a **la máquina** (aquí `http`, con el
daemon levantado) aunque la instalación original fuera `stdio`. **No es de este change**: se
comprobó que hace exactamente lo mismo con la entrada de Claude Code.

### Contra el binario real, hoy y en Windows

En agosto esto se midió en Linux contra opencode **1.18.11**. Se repitió contra **1.18.29**, que es
lo que instala hoy `npm i opencode-ai@latest`, y en Windows, que en agosto era justo lo que faltaba:

| Comprobación | Resultado |
|---|---|
| `debug paths` apunta a `<home>/.config/opencode` | OK |
| `opencode mcp add` con nuestros args registra la entrada | OK |
| el comentario y la clave `theme` del usuario sobreviven | OK |
| reejecutar deja **una sola** entrada | OK |
| nuestra entrada escrita a mano == la que escribe la CLI | OK (mismas claves y mismo contenido) |
| `opencode mcp list` → `✓ local-delegate connected` | OK |

La quinta fila es la que sostiene la decisión de **no escribir `"enabled": true`**: los dos caminos
siguen dejando exactamente la misma forma en disco.

**REQ-034 remedido:** el `initialize` de 1.18.29 declara `capabilities {"roots":{}}`, protocolo
`2025-11-25`, `clientInfo {"name":"opencode","version":"1.18.29"}`. Sigue **sin** `elicitation`, así
que la documentación no promete nada falso.

### Un hallazgo: la justificación de REQ-011 caducó con la versión del cliente

`spec.md` (REQ-011), el docstring de `install.py` y `docs/wiki/Integration-install.md` dicen que una
clave de primer nivel desconocida hace que opencode **no arranque** (`ConfigInvalidError`), y que
por eso no existe un `--force-mcp-opencode`. Medido hoy con los dos binarios, mismo config y mismos
subcomandos:

| opencode | `{"clave_que_no_existe": true}` |
|---|---|
| **1.18.11** (el de agosto) | `exit=1`, «Unrecognized key» en `mcp list`, `debug config` y `models` |
| **1.18.29** (hoy) | `exit=0`, sin queja: la tolera |

La medición de agosto **era correcta**; el cliente relajó la validación entre las dos versiones.

Dos avisos sobre cómo se midió, porque la primera pasada no discriminaba:

- **El `exit code` no sirve de señal**: con un JSON sintácticamente roto, opencode imprime
  `Error: Config file ... is not valid JSON(C)` y aun así **devuelve 0**. Hay que mirar la salida.
  (Es el mismo aprendizaje que ya está en el código para `_register_opencode_mcp`.)
- **Con un control positivo que tampoco discriminaba** —`{"theme": 12345}`, tipo equivocado en una
  clave que sí existe— **ninguna** de las dos versiones se queja. La validación que existía en
  1.18.11 era específica de claves desconocidas, no del esquema entero.

**Qué cambia y qué no.** El comportamiento del paquete **no cambia**: no escribir ninguna clave
ajena a `mcp` sigue siendo lo correcto, ahora por prudencia en vez de por obligación, y la ausencia
de `--force-mcp-opencode` se sostiene igual por el otro motivo, que sigue en pie: sin marcadores no
hay forma de distinguir nuestra entrada de una escrita a mano. Lo que queda desactualizado es la
**justificación escrita**, atada a una versión concreta del cliente. Corregir esas tres frases es un
cambio de documentación independiente, no un defecto de este change.

### Deriva respecto a la spec, ya conocida y deliberada

- **`enabled`** (REQ-007/008): la spec lo pedía; se quitó al medir que la CLI del cliente tampoco lo
  escribe. Reconfirmado hoy: las dos formas coinciden.
- **«diecisiete»** (REQ-029/032): hoy el `doctor` tiene **dieciocho** checks porque después de este
  change entró uno más. El requisito de fondo —que las frases de tamaño digan el número de verdad—
  lo guarda `test_el_docstring_dice_cuantos_checks_hay_de_verdad`, que está en verde.
