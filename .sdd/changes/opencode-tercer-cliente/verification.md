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

- **Windows y macOS.** El e2e de `scripts/check_install_e2e.py` ya cubre opencode y corre en los
  tres runners del CI, pero aquí solo se ha ejecutado en Linux. Lo específico de plataforma en este
  change es una ruta (`~/.config/opencode`) que opencode resuelve igual en los tres —usa XDG
  también en Windows, que es un comportamiento suyo conocido y algo que ellos mismos tratan como
  bug abierto—, así que el riesgo está acotado y el CI lo cerrará.
- **El camino por CLI bajo `--home`.** Está apagado a propósito (`use_cli=False` con HOME simulado)
  para que la suite no dependa de qué binarios haya en la máquina. Se ejercitó a mano, con el
  binario real, llamando a `_register_opencode_mcp` directamente (punto 2 de arriba).
