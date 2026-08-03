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
