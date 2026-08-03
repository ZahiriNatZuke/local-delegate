# Implementation plan: opencode como tercer cliente de `install`

## Approach

El eje «cliente» ya existe: `Options.targets` es un `set[str]`, `apply()` es agnóstico y el
registro de checks es una tupla. Este change **ensancha** ese eje; no abre uno. El trabajo real
está en cuatro decisiones de diseño, cada una con su alternativa descartada y su porqué.

**1. «Dónde está el config de opencode» es una función, no una propiedad.**
Medido (research R2-A): `XDG_CONFIG_HOME` gana sobre `HOME`. Un `home / ".config" / "opencode"`
escrito en `install` y otro en `checks` sería la clase de verdad repartida que ya costó caro tres
veces en este repo, y además **mentiría** en cualquier máquina con la variable puesta: `install`
escribiría un fichero que opencode nunca lee y `doctor` diría que falta la entrada que acaba de
escribirse. Vive en `install.py` —el módulo más bajo de los tres que la necesitan— junto a
`is_simulated_home` y `present_targets`, por el mismo motivo que aquellas.

Con `--home` simulado se ignora la variable: si no se ignorara, un `--home` dejaría de ser un
sandbox en cuanto el usuario tuviera `XDG_CONFIG_HOME` exportada.

**2. La identidad de «lo nuestro» es la clave `mcp["local-delegate"]`, sin marcadores.**
No es una preferencia: una clave de primer nivel desconocida **impide arrancar opencode**
(research R6). O sea, el modelo de Codex —bloque delimitado por comentarios— no se puede copiar, y
el que aplica es el de Claude Code: la entrada se identifica por su nombre y se reemplaza entera.

Consecuencia que conviene decir en voz alta: **no se puede distinguir una entrada nuestra de una
que escribió el usuario a mano**, así que aquí **no hay pregunta previa** como la de
`--force-mcp-codex`. Es exactamente lo que ya pasa con Claude Code, y es coherente: lo que
protege el `warn` de Codex es el *bloque sin marcadores*, y aquí no hay marcadores que mirar.

**3. Se escribe con la CLI del cliente, y el camino propio es el de socorro.**
`opencode mcp add` está medido (R4): no interactivo, idempotente por reemplazo, respeta `HOME`,
conserva comentarios y claves ajenas, y elige el fichero con la misma regla que necesitamos. Es el
mismo criterio por el que Claude Code se registra con su CLI, y aquí pesa **más**, porque el
fichero puede llevar comentarios que un `json.dumps` de ida y vuelta borraría (R6-A).

A diferencia de Claude Code, **la CLI no obliga a apagar el camino con `--home` simulado**: no hay
nada como `--scope user`, y se midió que escribe bajo el `HOME` que se le pase.

**4. Sin CLI, se escribe solo si eso no destruye nada; si no, no se escribe y se dice.**
El fallback aplica cuando el fichero no existe, o cuando parsea como JSON estricto **y** no tiene
comentarios fuera de cadenas. En cualquier otro caso —comentarios, comas finales, fichero roto— la
entrada MCP de opencode **no se escribe** y se avisa con la ruta y el arreglo. Es la misma regla
que ya gobierna el Codex ajeno: *no se pisa configuración escrita por una persona*.

> **Trampa a no pisar:** detectar comentarios con `"//" in texto` es **falso**. Una entrada HTTP
> legítima contiene `http://127.0.0.1:9393/mcp`, y cualquier config con una URL quedaría marcada
> como comentada. Hace falta un escáner que recorra el texto sabiendo cuándo está dentro de una
> cadena y cuándo hay un escape. Son ~20 líneas y su test es obligatorio.

Descartado **reescribir JSONC quirúrgicamente** (localizar la clave y recortar el texto con
emparejado de llaves) para no perder comentarios: es un parser a medias sobre un fichero cuyo
formato mal escrito **deja al usuario sin cliente**, y el beneficio —que funcione el camino sin
CLI en un config comentado— lo cubre instalar la CLI de opencode, que el usuario ya tiene si tiene
opencode. Si algún día se demuestra que el caso es común, es un change aparte con su medición.

Descartado también **depender de una librería JSONC**: este paquete tiene una política de techos y
auditoría de dependencias (`docs/wiki/Repo-hardening.md`); añadir una para un camino de socorro no
sale a cuenta.

## Decisiones que pide el usuario

Tres, con recomendación. Ninguna cambia el tamaño del change de forma drástica, pero las tres
cambian lo que se promete.

**D1 — ¿Instalar la skill en `~/.config/opencode/skill/`, o confiar en la lectura de
`~/.claude/skills/`?** Medido (R8): opencode carga nuestra skill desde `~/.claude/skills/` sin
tocar nada. *Recomendación: instalarla en su sitio propio.* El atajo es apagable
(`OPENCODE_DISABLE_EXTERNAL_SKILLS=1`) y **no existe** en una máquina sin Claude Code, donde
`plan_install` ni siquiera emitiría la acción. Coste: una acción `copy` más.

**D2 — ¿Escribir el bloque de memoria en `~/.config/opencode/AGENTS.md`?** Medido (R9): opencode
lee **también** `~/.claude/CLAUDE.md`. *Recomendación: sí, escribirlo.* Mismo argumento que D1:
apagable (`OPENCODE_DISABLE_CLAUDE_CODE_PROMPT`) e inexistente sin Claude Code. Coste: una acción
`markdown` más, con el mismo bloque.

**D3 — ¿Se acepta que sin CLI y con un config comentado la entrada MCP no se escriba?**
*Recomendación: sí.* La alternativa es un reescritor de JSONC propio cuyo fallo deja al usuario sin
cliente. La salida avisa y ofrece las dos formas de arreglarlo.

Si D1 y D2 se responden que **no**, desaparecen las tareas 6 y 7 y el change se queda en la entrada
MCP más el diagnóstico — sigue siendo coherente, pero una máquina solo con opencode se queda sin
regla ni skill, que es justo lo que este paquete existe para no dejar a medias.

## Ordered tasks

1. **Dónde vive opencode**
   - Files: `src/local_delegate/install.py`
   - `opencode_dir(home: Path) -> Path`, con la regla de REQ-003/REQ-004; `present_targets` pasa a
     tres pares y usa la función.
   - Requirements: REQ-002, REQ-003, REQ-004
   - Verification: tests unitarios con y sin `XDG_CONFIG_HOME`, y con `home` simulado.
   - Rollback: revertir la función; `present_targets` vuelve a dos pares.

2. **La forma de la entrada**
   - Files: `src/local_delegate/install.py`
   - `opencode_mcp_entry(mode, base_url, api_key_env, version, web_token_env) -> dict`, con las dos
     formas medidas en R5. Se deriva de la misma información que `mcp_entry`, **no** se traduce
     desde su salida: la traducción ataría la forma de opencode a la de Claude Code y el próximo
     cambio en una rompería la otra en silencio.
   - Requirements: REQ-007, REQ-008, REQ-009, REQ-010, REQ-011
   - Verification: tests de las dos formas, y uno que afirma que el JSON serializado **no contiene**
     el valor de `LOCAL_DELEGATE_API_KEY` ni el de `LOCAL_DELEGATE_WEB_TOKEN` con las variables
     puestas en el entorno del test.
   - Rollback: quitar la función; nadie más la usa.

3. **Leer el config de opencode sin romperlo**
   - Files: `src/local_delegate/install.py`
   - `opencode_config_paths(home)` (los dos ficheros, en el orden de R3), `opencode_config_target(home)`
     (a cuál escribir, regla de REQ-005) y `tiene_comentarios(texto) -> bool` con el escáner que
     respeta cadenas y escapes.
   - Requirements: REQ-005, REQ-006, REQ-014, REQ-017
   - Verification: caso `http://` dentro de una URL (**no** es comentario), `//` dentro de una
     cadena, `/* */`, comentario real, cadena con comilla escapada, fichero vacío.
   - Rollback: aditivo.

4. **Escribir la entrada: CLI primero, fichero después, y a veces nada**
   - Files: `src/local_delegate/install.py`
   - `_register_opencode_mcp(opts, entry)`: si hay binario `opencode` y `use_cli`, invoca
     `opencode mcp add` con `--url`/`--header` o `--env` + `-- comando…` según el modo, con
     `timeout=30` y capturando salida, igual que `_register_claude_mcp`. Si no, el camino de
     fichero de la decisión 4 del *Approach*. Si tampoco, devuelve el aviso de REQ-015.
   - **Ojo:** el binario devuelve `0` para subcomandos que no existen (medido en R4 con
     `mcp remove`), así que el éxito **no** se puede deducir solo del `returncode`; hay que
     comprobar además que la entrada esté en el fichero después.
   - Requirements: REQ-012, REQ-013, REQ-014, REQ-015, REQ-016
   - Verification: test con un `opencode` de pega en el PATH que escribe lo que se le pide; test
     sin binario y fichero limpio; test sin binario y fichero comentado (no escribe, avisa, exit 0);
     test de reinstalación (una sola entrada, `theme` y comentario intactos).
   - Rollback: la acción es una sola entrada del plan; quitarla no afecta al resto.

5. **La entrada MCP en `plan_install` / `plan_uninstall`**
   - Files: `src/local_delegate/install.py`
   - Rama `"opencode" in opts.targets` en el componente `mcp`, con `literal=` (el JSON de la
     entrada) para que `--dry-run` enseñe **qué** se escribe, no cuánto. En `plan_uninstall`,
     `remove_opencode_mcp`, con la misma regla de seguridad de la tarea 4.
   - Requirements: REQ-021, REQ-022, REQ-023
   - Verification: test de desinstalación con una entrada ajena al lado; test de que el fichero
     resultante lo acepta `json.loads`.
   - Rollback: quitar las dos ramas.

6. **Memoria en `AGENTS.md` de opencode** *(depende de D2)*
   - Files: `src/local_delegate/install.py`
   - Añadir `opencode_dir(home) / "AGENTS.md"` a `memory_files` y a la lista de `plan_uninstall`.
   - Requirements: REQ-018
   - Verification: test del bloque puesto, reemplazado y quitado, con el resto del fichero intacto.
   - Rollback: quitar la ruta de las dos listas.

7. **Skill en el directorio de opencode** *(depende de D1)*
   - Files: `src/local_delegate/install.py`
   - `_copy_tree_action` hacia `opencode_dir(home) / "skill" / SKILL_NAME`, y su `remove`.
   - Requirements: REQ-019
   - Verification: test de que instalar solo para opencode **no** crea `~/.claude` (REQ-020).
   - Rollback: quitar las dos acciones.

8. **CLI**
   - Files: `src/local_delegate/cli.py`
   - `_ALL_TARGETS`, `_CLIENT_DIR`, los `choices` de `--clients` y `--target`, el texto de «no se
     encontró ningún cliente» y el «Reinicia el cliente (Claude Code / Codex)» del final.
   - Requirements: REQ-001
   - Verification: `--help` menciona opencode; test de `_resolve_clients` con `--clients opencode`
     y con `--target all`.
   - Rollback: revertir las constantes.

9. **Comprobaciones**
   - Files: `src/local_delegate/checks.py`
   - `Context.opencode_dir` (propiedad que llama a `install.opencode_dir`), `_probe_clients` a tres,
     `_probe_memory` a tres, `_probe_mcp_opencode` nuevo, `_probe_mcp_credential` contando
     `local`/`remote`, `CHECKS` de 16 a 17 y **las cinco frases de tamaño**.
   - Requirements: REQ-006, REQ-024, REQ-025, REQ-026, REQ-027, REQ-028, REQ-029, REQ-031
   - Verification: `test_el_docstring_dice_cuantos_checks_hay_de_verdad` en verde tras añadir
     `17: "diecisiete"` a `_NUMERO`; test de que el probe no escribe (el arnés que compara el árbol
     del HOME byte a byte ya existe); test del caso «los dos ficheros, entrada en el `.jsonc`».
   - Rollback: quitar la entrada del registro y revertir las frases.

10. **Reparación**
    - Files: `src/local_delegate/update.py`
    - `Repair("scaffold.mcp_opencode", (MISSING,), {"mcp"}, {"opencode"})`; `scaffold.memory` ya usa
      `PRESENT` y no necesita cambio. Actualizar el comentario que enumera los no reparables y
      `_infer_mcp_mode`, que hoy solo mira los dos checks viejos.
    - Requirements: REQ-030
    - Verification: test de reparación en un HOME con opencode y sin entrada; test de idempotencia
      (segunda pasada, cero acciones).
    - Rollback: quitar la entrada de la tabla.

11. **Documentación y CHANGELOG**
    - Files: `docs/wiki/Integration-install.md`, `docs/wiki/Daemon.md`, `README.md`, `CHANGELOG.md`
    - Requirements: REQ-032, REQ-033, REQ-034
    - Verification: `scripts/sync_wiki.py` y `tests/test_wiki.py` en verde; revisión de que el
      número de comprobaciones del doctor coincide con `len(CHECKS)`.
    - Rollback: revertir los ficheros.

## Verification

Además de lo de cada tarea, antes del gate de calidad:

- `pytest` completo, `ruff check`, `ruff format --check`, `scripts/extract_dashboard_js.py` +
  `node --check`, y `scripts/ci_gate.py`.
- **Verificación contra el cliente real**, que es lo que distingue este change de uno de papel:
  instalar en un HOME simulado y ejecutar `opencode mcp list` con ese `HOME`; la salida tiene que
  decir `✓ local-delegate connected`. Es la misma clase de prueba que el
  `scripts/check_install_handshake.py` que ya existe, y conviene mirar si cabe ahí en vez de en un
  script nuevo.
- Mutación dirigida: romper a mano cada invariante nueva (el escáner de comentarios, la elección de
  fichero, la regla de `XDG_CONFIG_HOME`) y comprobar que **cada una rompe su propio test**.

## Risks

| Riesgo | Mitigación |
|---|---|
| Una escritura mal formada deja al usuario sin poder abrir opencode | CLI del cliente por defecto; `.bak`; el camino propio solo sobre ficheros que parsean y no tienen comentarios; nunca claves fuera de `mcp` |
| El detector de comentarios da falso positivo con `http://` | Escáner con estado de cadena y test explícito de ese caso |
| `XDG_CONFIG_HOME` rompe el sandbox de `--home` | La función la ignora con HOME simulado, y hay test |
| La forma de la entrada de opencode cambia entre versiones | La verificación contra el binario real deja constancia de la versión medida (1.18.11); el `research.md` dice cómo repetirla |
| El change crece y se mezcla con los hooks | Los hooks están fuera de alcance por escrito, con el motivo medido (R10) |

## Estimated size

Cuatro ficheros de código, cinco de tests, cuatro de documentación. Comparable a
`install-checks-clients`. Si el gate de plan decide partirlo, el corte natural es: **A)** entrada
MCP + CLI + `scaffold.mcp_opencode`; **B)** memoria + skill + reparación. `A` sola ya es útil.
