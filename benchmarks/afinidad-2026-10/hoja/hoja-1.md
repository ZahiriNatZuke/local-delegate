# Hoja 1: mensajes de commit, a ciegas

Hoja: cbbb971e5dbe694cc5c999460972e2c42aff9a42afd6e7eaa52d5523d8b19893

En cada par hay dos mensajes de commit para el mismo cambio. Tiempo estimado: unos 45–60 minutos (solo «inventa» y la preferencia son obligatorias).
Puedes hacerlo en varias sentadas. Escribe la respuesta detrás de los dos puntos de cada línea.

- **Inventa (si/no)**: ¿El mensaje dice algo que el diff no hace? Lo que el mensaje se deja fuera no se marca aquí, sino en «lo principal».
- **Lo principal (si/parcial/no)**: ¿Nombra el cambio más importante del diff?
- **Específico (si/no)**: ¿Se entiende sin abrir el diff?
- **Preferencia**: A, B o empate, después de marcar los dos mensajes.

## Par 01

Diff: 6 ficheros, +114 −13

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index c8c1c7c..5aea716 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,6 +4,34 @@ Todos los cambios notables de este proyecto se documentan aquí.
 El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
 y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
+## [Unreleased]
+
+### Fixed
+- **La wiki llevaba cuatro versiones sin actualizarse, y ahora hay quien lo note.** `docs/wiki/`
+  no se tocaba desde la 0.23.0: la tabla de comprobaciones de `doctor` tenía **diecisiete** filas
+  con dieciocho checks en el registro —faltaba `service.daemon_auth`, el «token del puerto del
+  daemon» que nació en la 0.26.0— y el texto seguía prometiendo «las dieciséis piezas». La fila de
+  la skill también describía solo la de Claude Code, cuando desde la 0.19.0 se escribe también en
+  opencode.
+
+  Lo que lo dejó pasar es que `checks.py` **sí** tenía guardián (sus frases de tamaño estaban al
+  día) y la wiki no. Ahora `tests/test_wiki.py` compara la tabla contra `checks.CHECKS` fila por
+  fila y comprueba el número escrito con letra: añadir un check sin documentarlo pone el CI en
+  rojo en el mismo PR que lo introduce.
+
+- **Una justificación medida también caduca, y esta caducó.** El código, la wiki y el docstring de
+  su test decían que una clave de primer nivel desconocida hace que opencode **no arranque**
+  (`ConfigInvalidError`). Medido el 2026-09-08 con los dos binarios el mismo día: `1.18.11`
+  rechaza el config entero (`Unrecognized key`, exit 1) y **`1.18.29` ya la tolera**. La medición
+  original era correcta; el cliente relajó la validación.
+
+  **No cambia el comportamiento del paquete**: se sigue escribiendo solo dentro de `mcp`, ahora
+  por prudencia —la versión la elige el usuario— y porque lo que **no** ha cambiado en ninguna de
+  las dos versiones es que una entrada mal formada *dentro* de `mcp` (sin `type`, sin `command`, o
+  con `command` que no sea un array) sí impide arrancar. Tampoco cambia la ausencia de
+  `--force-mcp-opencode`, que se sostiene por el otro motivo, intacto: sin marcadores no hay forma
+  de distinguir nuestra entrada de una escrita a mano.
+
 ## [0.27.0] - 2026-09-08
 
 ### Changed
diff --git a/docs/wiki/Integration-install.md b/docs/wiki/Integration-install.md
index ec447ed..2373ec0 100644
--- a/docs/wiki/Integration-install.md
+++ b/docs/wiki/Integration-install.md
@@ -72,11 +72,16 @@ Si no hay ninguno, no se escribe nada, se dice qué se buscó y el comando termi
   (`opencode mcp add`, que los conserva), y cuando esa CLI no está y el fichero tiene comentarios
   —o no se puede parsear— la entrada MCP **no se escribe**: se avisa con la ruta y se sigue con el
   resto de componentes. Instalar la CLI de opencode y repetir el `install` lo resuelve.
-- **En opencode nunca se escribe una clave que no sea `mcp`.** Una clave de primer nivel
-  desconocida hace que opencode **no arranque** (`ConfigInvalidError`), así que ahí no hay
-  marcadores `local-delegate:begin/end`: la entrada se identifica por su nombre, como en Claude
-  Code. Consecuencia: en opencode no hay pregunta previa equivalente a `--force-mcp-codex`, porque
-  no hay forma de distinguir una entrada nuestra de una que escribiste tú.
+- **En opencode nunca se escribe una clave que no sea `mcp`.** Una clave de primer nivel ajena al
+  esquema puede dejar el cliente sin arrancar, y **cuánto** depende de su versión: medido el
+  2026-09-08 con los dos binarios a la vez, opencode `1.18.11` rechaza el config entero
+  (`Unrecognized key`) y `1.18.29` ya tolera esa clave. Como la versión la eliges tú y no nosotros,
+  la regla se mantiene en su forma estricta; lo que **no** ha cambiado en ninguna versión es que
+  una entrada mal formada *dentro* de `mcp` —sin `type`, sin `command`, o con `command` que no sea
+  un array— sí impide arrancar. Por eso ahí no hay marcadores `local-delegate:begin/end`: la
+  entrada se identifica por su nombre, como en Claude Code. Consecuencia: en opencode no hay
+  pregunta previa equivalente a `--force-mcp-codex`, porque no hay forma de distinguir una entrada
+  nuestra de una que escribiste tú.
 - **Reversible.** `uninstall` borra los directorios propios y quita solo sus entradas.
 
 ## Comprobarlo desde el propio cliente
@@ -167,7 +172,7 @@ legítimos (el CLI fuera del PATH si se instaló con `uvx`, o un cliente que no
 
 Reinicia el cliente. Verifica con:
 
-- `local-delegate doctor` → comprueba de una vez las dieciséis piezas (ver abajo), incluidos el
+- `local-delegate doctor` → comprueba de una vez las dieciocho piezas (ver abajo), incluidos el
   daemon y el backend, que el reporte de `install` no mira a propósito.
 - `local_status` → backend, catálogo y si el cómputo es local o remoto.
 - Un prompt tipo "resume este archivo en cinco viñetas" → debe aparecer la sugerencia del hook.
@@ -195,7 +200,7 @@ local-delegate doctor --home /tmp/x  # diagnostica contra un HOME simulado (solo
 | Andamiaje | hooks copiados | los scripts en `~/.claude/hooks/local-delegate/` |
 | Andamiaje | hooks huérfanos | scripts nuestros sueltos en `~/.claude/hooks/` que dejó una instalación anterior; `install` los retira |
 | Andamiaje | hooks registrados | entradas **nuestras** en `~/.claude/settings.json` (las ajenas no se cuentan) |
-| Andamiaje | skill | `~/.claude/skills/delegacion-local/SKILL.md` |
+| Andamiaje | skill delegacion-local | la skill **en cada cliente al que se le escribe**: `~/.claude/skills/delegacion-local/SKILL.md` y `~/.config/opencode/skill/delegacion-local/`. Mirar solo la de Claude Code daba un `[ OK ]` con la de opencode borrada |
 | Andamiaje | memoria global | el bloque entre marcadores en `CLAUDE.md` y `AGENTS.md` |
 | Andamiaje | MCP en Claude Code | la entrada `local-delegate` en `~/.claude.json` |
 | Andamiaje | MCP en Codex | la sección `[mcp_servers.local-delegate]` de `~/.codex/config.toml` |
@@ -203,6 +208,7 @@ local-delegate doctor --home /tmp/x  # diagnostica contra un HOME simulado (solo
 | Servicios | daemon | `http://127.0.0.1:9393/api/daemon` (versión y pid), y si sirve una versión **distinta de la instalada** |
 | Servicios | backend | `BASE_URL/models` |
 | Servicios | credencial del backend | si el proceso MCP que arranca **tu cliente** podrá autenticarse. Pregunta al backend **sin** credencial: si lo rechaza y alguna entrada MCP está en modo `stdio`, ese proceso no la tendrá y sus tools `local_*` responderán `401` — aunque el daemon vea el backend perfectamente |
+| Servicios | token del puerto del daemon | la **otra** puerta del mismo camino: si el puerto del daemon exige token, si las entradas MCP en modo `http` lo llevan. Pregunta al puerto y compara con lo que llevan las entradas de los tres clientes; sin cabecera, `warn` nombrando al cliente. Existe porque `install` sin `--web-token-env` deja la entrada sin `Authorization` y el cliente en `401` sin que nada lo dijera |
 | Backend | llama-swap | versión instalada vs probada |
 | Backend | llama-server | versión instalada vs probada |
 
diff --git a/src/local_delegate/install.py b/src/local_delegate/install.py
index 1f801a5..bdffd9c 100644
--- a/src/local_delegate/install.py
+++ b/src/local_delegate/install.py
@@ -484,8 +484,13 @@ def remove_codex_mcp(text: str) -> str:
 # --- Entrada del servidor MCP en opencode ------------------------------------
 # opencode se parece a Claude Code y NO a Codex en lo único que aquí importa: la entrada se
 # identifica por su **clave** (`mcp["local-delegate"]`) y no por marcadores. No es una preferencia:
-# está medido que una clave de primer nivel desconocida hace que opencode **no arranque**
-# (`ConfigInvalidError`), así que un `# local-delegate:begin` propio dejaría al usuario sin cliente.
+# un `# local-delegate:begin` propio sería una clave de primer nivel ajena al esquema, y eso puede
+# dejar al usuario sin cliente. Cuidado con la fuerza de esa afirmación, porque **depende de la
+# versión**: medido el 2026-09-08 con los dos binarios a la vez, 1.18.11 rechaza una clave de
+# primer nivel desconocida (`Unrecognized key`) y 1.18.29 ya la tolera. La regla se mantiene
+# igualmente —escribir solo dentro de `mcp` es lo que no depende de qué versión tenga el usuario—
+# y lo que NO ha cambiado es el castigo por una entrada mal formada DENTRO de `mcp`: las dos
+# versiones se niegan a arrancar si le falta `type` o `command`, o si `command` no es un array.
 #
 # Consecuencia que conviene decir en voz alta: aquí NO se puede distinguir una entrada nuestra de
 # una que escribió el usuario a mano, así que tampoco hay pregunta previa como la de
diff --git a/src/local_delegate/update.py b/src/local_delegate/update.py
index 54ede03..2872cfe 100644
--- a/src/local_delegate/update.py
+++ b/src/local_delegate/update.py
@@ -195,9 +195,11 @@ REPAIRS: tuple[Repair, ...] = (
     # usuario. Pisarla sería el fallo contra el que existe la regla de `unknown`.
     Repair("scaffold.mcp_codex", (checks.MISSING,), frozenset({"mcp"}), frozenset({"codex"})),
     # opencode NO tiene un `warn` equivalente al de Codex, y no es un olvido: su entrada se
-    # identifica por la clave `mcp["local-delegate"]` y no por marcadores —una clave desconocida
-    # impide arrancar el cliente—, así que no hay forma de distinguir la nuestra de una escrita a
-    # mano. Es la misma situación que con Claude Code, y se trata igual: solo se repone si falta.
+    # identifica por la clave `mcp["local-delegate"]` y no por marcadores —no escribimos ninguna
+    # clave de primer nivel ajena al esquema; ver el porqué, y su letra pequeña por versión, en
+    # `install._escanear_jsonc` y alrededores—, así que no hay forma de distinguir la nuestra de
+    # una escrita a mano. Es la misma situación que con Claude Code, y se trata igual: solo se
+    # repone si falta.
     Repair("scaffold.mcp_opencode", (checks.MISSING,), frozenset({"mcp"}), frozenset({"opencode"})),
 )
 
diff --git a/tests/test_install_opencode.py b/tests/test_install_opencode.py
index d44d116..cd6ec9a 100644
--- a/tests/test_install_opencode.py
+++ b/tests/test_install_opencode.py
@@ -199,7 +199,12 @@ def test_reinstalar_es_idempotente_y_conserva_lo_ajeno(tmp_path):
 
 
 def test_nunca_se_escribe_una_clave_de_primer_nivel_ajena_al_esquema(tmp_path):
-    """Una clave desconocida hace que opencode **no arranque** (`ConfigInvalidError`, medido)."""
+    """Escribir fuera de `mcp` puede dejar al usuario sin cliente, y cuánto depende de la versión.
+
+    Medido el 2026-09-08 con los dos binarios el mismo día: opencode 1.18.11 rechaza el config
+    entero ante una clave de primer nivel desconocida (`Unrecognized key`) y 1.18.29 ya la tolera.
+    La invariante se queda en su forma estricta porque la versión la elige el usuario.
+    """
     home = tmp_path / "home"
     d = _oc(home)
     assert _install(home) == 0
diff --git a/tests/test_wiki.py b/tests/test_wiki.py
index 1c9b978..78c7ead 100644
--- a/tests/test_wiki.py
+++ b/tests/test_wiki.py
@@ -25,6 +25,20 @@ _spec.loader.exec_module(sync_wiki)
 WIKI = RAIZ / "docs" / "wiki"
 WORKFLOW = RAIZ / ".github" / "workflows" / "wiki.yml"
 
+# La tabla del doctor de `Integration-install.md` se compara contra el registro real de
+# comprobaciones, así que este módulo importa `checks`. Los grupos son la primera columna.
+from local_delegate import checks
+
+_GRUPOS_DE_LA_TABLA = {"Entorno", "Andamiaje", "Servicios", "Backend"}
+_NUMERO_DE_CHECKS = {
+    15: "quince",
+    16: "dieciséis",
+    17: "diecisiete",
+    18: "dieciocho",
+    19: "diecinueve",
+    20: "veinte",
+}
+
 # `[texto](destino)`, quedándose con el destino.
 ENLACE_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
 
@@ -173,3 +187,44 @@ def test_los_enlaces_entre_paginas_apuntan_a_paginas_que_existen():
                 rotos.append(f"{pagina.name} -> {destino}")
 
     assert not rotos, f"enlaces a páginas que no existen: {rotos}"
+
+
+def _filas_de_la_tabla_de_checks() -> list[tuple[str, str]]:
+    """`(grupo, comprobación)` de la tabla del doctor en `Integration-install.md`."""
+    texto = (WIKI / "Integration-install.md").read_text(encoding="utf-8")
+    filas = []
+    for linea in texto.splitlines():
+        if not linea.startswith("|"):
+            continue
+        celdas = [c.strip() for c in linea.strip("|").split("|")]
+        if len(celdas) >= 2 and celdas[0] in _GRUPOS_DE_LA_TABLA:
+            filas.append((celdas[0], celdas[1]))
+    return filas
+
+
+def test_la_tabla_del_doctor_lista_todas_las_comprobaciones():
+    """La wiki es la única superficie del doctor que no tenía guardián, y se desfasó.
+
+    `checks.py` sí lo tiene —`test_el_docstring_dice_cuantos_checks_hay_de_verdad`— y por eso sus
+    frases de tamaño estaban al día. La wiki no, así que el check `service.daemon_auth` de la
+    0.26.0 nunca llegó a la tabla y el texto siguió diciendo «dieciséis» con dieciocho checks en
+    el registro. Medido el 2026-09-08: la tabla tenía diecisiete filas.
+
+    Este test compara la tabla contra el registro **real**, que es la única fuente: añadir un
+    check y no documentarlo pone la wiki en rojo en el mismo PR que lo introduce.
+    """
+    titulos_wiki = [titulo for _grupo, titulo in _filas_de_la_tabla_de_checks()]
+    titulos_codigo = [c.title for c in checks.CHECKS]
+
+    faltan = [t for t in titulos_codigo if t not in titulos_wiki]
+    sobran = [t for t in titulos_wiki if t not in titulos_codigo]
+    assert not faltan, f"comprobaciones sin fila en la wiki: {faltan}"
+    assert not sobran, f"filas de la wiki que ya no existen en checks.py: {sobran}"
+
+
+def test_la_wiki_dice_cuantas_comprobaciones_hay_de_verdad():
+    """El número escrito con letra envejece solo; que lo cuente el programa."""
+    cuantas = _NUMERO_DE_CHECKS[len(checks.CHECKS)]
+    texto = (WIKI / "Integration-install.md").read_text(encoding="utf-8")
+    frase = f"las {cuantas} piezas"
+    assert frase in texto, f"la wiki no dice «{frase}»; hay {len(checks.CHECKS)} comprobaciones"
```

### Mensaje A

```
docs(wiki): actualizar documentación y añadir validación de la wiki

- Actualiza la tabla de comprobaciones del `doctor` en la wiki para reflejar los nuevos checks.
- Corrige la descripción sobre la validación de claves en `opencode` para reflejar la tolerancia según la versión.
- Añade `tests/test_wiki.py` para asegurar que la tabla de la wiki coincida siempre con los checks reales y el número de piezas sea correcto.
- Actualiza el CHANGELOG.md con los cambios realizados.
```

### Mensaje B

```
docs(wiki): sincronizar tabla de checks y ajustar validación opencode

- Actualizar Integration-install.md con los dieciocho checks actuales
- Añadir check service.daemon_auth y corregir referencia a skill opencode
- Actualizar test_wiki.py para validar tabla contra checks.CHECKS
- Aclarar que opencode 1.18.29 tolera claves desconocidas de primer nivel
- Mantener restricción estricta para entradas mal formadas dentro de mcp
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 02

Diff: 6 ficheros, +10 −9

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 35d1493..5331580 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -4,7 +4,7 @@ Todos los cambios notables de este proyecto se documentan aquí.
 El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
 y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
-## [Unreleased]
+## [0.27.0] - 2026-09-08
 
 ### Changed
 - **BREAKING — `local_boilerplate` escribe el código en disco y ya no lo devuelve.** La firma pasa
@@ -1708,7 +1708,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 - Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
   registro oficial de MCP.
 
-[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.26.0...HEAD
+[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.27.0...HEAD
+[0.27.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.26.0...v0.27.0
 [0.26.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.25.0...v0.26.0
 [0.25.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.24.0...v0.25.0
 [0.24.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.23.0...v0.24.0
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index 0c7e09c..adc5b3f 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.26.0",
-  "sha256": "cd9e0127566d67e71b5e7335b3694a2c30825558fbdfe2a4f029c49ed0c81827",
-  "bytes": 721419
+  "version": "0.27.0",
+  "sha256": "fa6f9f4ce80dd90d52889c915ee6fc02f0a05a41435e7f58d68b9d548d37758a",
+  "bytes": 718456
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index eec2443..5f1f848 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index 50d51c0..8947ba7 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.26.0"
+version = "0.27.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/server.json b/server.json
index d61e60c..dac12a7 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.26.0",
+  "version": "0.27.0",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.26.0",
+      "version": "0.27.0",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/uv.lock b/uv.lock
index 2bbf194..1479111 100644
--- a/uv.lock
+++ b/uv.lock
@@ -448,7 +448,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.26.0"
+version = "0.27.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
chore(release): actualizar versión a 0.27.0

- Actualizar versión en pyproject.toml, server.json y uv.lock
- Actualizar CHANGELOG.md con la nueva versión y fecha
- Actualizar metadatos de dashboard.json y el asset dashboard.png
```

### Mensaje B

```
feat: lanzamiento v0.27.0 con cambios BREAKING
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 03

Diff: 2 ficheros, +77 −56

```diff
diff --git a/.sdd/changes/commit-msg-diffs-grandes/handoff.md b/.sdd/changes/commit-msg-diffs-grandes/handoff.md
index a8faf79..540fd99 100644
--- a/.sdd/changes/commit-msg-diffs-grandes/handoff.md
+++ b/.sdd/changes/commit-msg-diffs-grandes/handoff.md
@@ -1,50 +1,49 @@
-# Handoff: local_commit_msg deja de truncar diffs grandes
-
-## Current state
-
-- SDD status: `result-review` (modo lite), gates `spec`, `plan`, `quality` y `conformance`
-  aprobados. Falta `memory` y el cierre.
-- Rama `fix/commit-msg-diffs-grandes` @ `070d7bb`, **PR #137** con los 13 checks en verde
-  (incluidos `CodeQL` y `ci-gate`, que llegan tarde). Pendiente de merge.
-
-## What changed
-
-`local_commit_msg` procesa el diff entero en vez de sus primeros 20 000 caracteres. Siete tareas,
-de las que **dos no estaban en el plan original** y salieron de medir contra el backend real:
-
-1-3. Splitter de diff por archivo, inventario calculado sin modelo, y `_chat_map_reduce`
-     parametrizable con un reduce propio.
-4. Nota de alcance en la salida y error explícito para el diff vacío.
-5. La medida contra el backend real.
-6. **Reintento cuando un trozo no cabe en el contexto** — el presupuesto está en chars y el límite
-   en tokens.
-7. **Prompts del map que dan las rutas reales** y declaran qué trozo continúa un archivo.
-
-## Decisions
-
-- **El splitter de diff es global pero se autoinhibe.** Va como nivel 0 de `_SPLITTERS`, y
-  devuelve el texto entero si no empieza por una cabecera de diff. Así un Markdown con un diff
-  dentro de un fence se sigue partiendo por headers y no puede degradar `local_translate`.
-- **El respaldo `--- `/`+++ ` solo se usa si no hay ningún `diff --git`.** En un diff `--git` cada
-  archivo trae también su `--- a/x`: cortar por ambas cabeceras partiría cada archivo en dos.
-- **El inventario se calcula sin modelo** porque es un conteo, no un juicio, y así no cuesta una
-  llamada. Se colapsa por directorio si pasa del 25 % del presupuesto.
-- **La nota de alcance va siempre, no bajo `FEEDBACK_ENABLED`**: no es contabilidad de ahorro, es
-  lo que impide que procesar de menos vuelva a ser invisible.
-- **El reintento por desborde cubre el map y no el reduce**, y eso está anotado como límite
-  conocido en `verification.md`, no como cubierto.
-- **La calidad se juzga con un diff coherente, no con el grande.** Un rango de seis PRs mezclados
-  no tiene un buen mensaje de commit posible; sirve para medir que entra entero, no calidad.
-
-## Next action
-
-Mergear el PR #137 (squash, como el resto del repo), aprobar el gate `memory` y cerrar el cambio.
-
-Lo que quedó fuera a propósito y ahora es evaluable sobre una base medida: **filtrar el ruido del
-diff** —lockfiles, generados, líneas de contexto sin cambiar—. Reduciría el número de trozos y el
-coste; el caso grande son hoy 17 llamadas y 122 s.
-
-## Memory
-
-- Nota canónica: pendiente de escribir en el vault tras el merge.
-- Índices actualizados: pendiente.
+# Handoff: local_commit_msg deja de truncar diffs grandes
+
+## Current state
+
+- SDD status: `closed` (modo lite). Los cinco gates aprobados.
+- **PR #137 mergeado** (squash) como `ed2db74` en `main`, con los 13 checks en verde — incluidos
+  `CodeQL` y `ci-gate`, que llegan tarde. Rama borrada.
+
+## What changed
+
+`local_commit_msg` procesa el diff entero en vez de sus primeros 20 000 caracteres. Siete tareas,
+de las que **dos no estaban en el plan original** y salieron de medir contra el backend real:
+
+1-3. Splitter de diff por archivo, inventario calculado sin modelo, y `_chat_map_reduce`
+     parametrizable con un reduce propio.
+4. Nota de alcance en la salida y error explícito para el diff vacío.
+5. La medida contra el backend real.
+6. **Reintento cuando un trozo no cabe en el contexto** — el presupuesto está en chars y el límite
+   en tokens.
+7. **Prompts del map que dan las rutas reales** y declaran qué trozo continúa un archivo.
+
+## Decisions
+
+- **El splitter de diff es global pero se autoinhibe.** Va como nivel 0 de `_SPLITTERS`, y
+  devuelve el texto entero si no empieza por una cabecera de diff. Así un Markdown con un diff
+  dentro de un fence se sigue partiendo por headers y no puede degradar `local_translate`.
+- **El respaldo `--- `/`+++ ` solo se usa si no hay ningún `diff --git`.** En un diff `--git` cada
+  archivo trae también su `--- a/x`: cortar por ambas cabeceras partiría cada archivo en dos.
+- **El inventario se calcula sin modelo** porque es un conteo, no un juicio, y así no cuesta una
+  llamada. Se colapsa por directorio si pasa del 25 % del presupuesto.
+- **La nota de alcance va siempre, no bajo `FEEDBACK_ENABLED`**: no es contabilidad de ahorro, es
+  lo que impide que procesar de menos vuelva a ser invisible.
+- **El reintento por desborde cubre el map y no el reduce**, y eso está anotado como límite
+  conocido en `verification.md`, no como cubierto.
+- **La calidad se juzga con un diff coherente, no con el grande.** Un rango de seis PRs mezclados
+  no tiene un buen mensaje de commit posible; sirve para medir que entra entero, no calidad.
+
+## Next action
+
+Nada pendiente de este cambio. Lo que quedó fuera a propósito y ahora es evaluable sobre una base medida: **filtrar el ruido del
+diff** —lockfiles, generados, líneas de contexto sin cambiar—. Reduciría el número de trozos y el
+coste; el caso grande son hoy 17 llamadas y 122 s.
+
+## Memory
+
+- Nota canónica: `projects/local-delegate/jornada-2026-08-04-el-diff-que-no-cabia.md`.
+- Memoria nueva del proyecto: `presupuesto-en-chars-limite-en-tokens.md`.
+- Índices actualizados: memoria de Claude Code del proyecto (jornada, gotcha nuevo, y los
+  contadores de `probar-la-pieza-no-es-probar-el-uso` y `un-pendiente-es-una-hipotesis`).
diff --git a/.sdd/changes/commit-msg-diffs-grandes/state.json b/.sdd/changes/commit-msg-diffs-grandes/state.json
index b0d2662..584866c 100644
--- a/.sdd/changes/commit-msg-diffs-grandes/state.json
+++ b/.sdd/changes/commit-msg-diffs-grandes/state.json
@@ -3,9 +3,9 @@
   "slug": "commit-msg-diffs-grandes",
   "title": "local_commit_msg deja de truncar diffs grandes",
   "mode": "lite",
-  "status": "result-review",
+  "status": "closed",
   "createdAt": "2026-08-04T14:53:23.504Z",
-  "updatedAt": "2026-08-04T17:24:11.183Z",
+  "updatedAt": "2026-08-04T17:46:59.102Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-04T17:46:58.992Z",
+      "evidence": "Nota canonica en el vault: projects/local-delegate/jornada-2026-08-04-el-diff-que-no-cabia.md. Memoria nueva del proyecto: presupuesto-en-chars-limite-en-tokens.md. Punteros sincronizados en la memoria de Claude Code del proyecto (jornada, gotcha nuevo, y contadores actualizados de probar-la-pieza-no-es-probar-el-uso y un-pendiente-es-una-hipotesis). Sin secretos ni datos personales.",
+      "actor": "user"
     }
   },
   "history": [
@@ -168,6 +168,28 @@
       "at": "2026-08-04T17:24:11.183Z",
       "evidence": "Los siete requisitos implementados y verificados contra el backend real y con tests. Veredicto conforms-with-notes: REQ-004 cumple con dos limites de calidad anotados (el tipo del commit no siempre acierta y el cuerpo es irregular), ninguno bloqueante. Cinco hallazgos anotados, incluidos dos tests propios que no median lo que decian y una hipotesis de diagnostico caida.",
       "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-08-04T17:46:58.992Z",
+      "evidence": "Nota canonica en el vault: projects/local-delegate/jornada-2026-08-04-el-diff-que-no-cabia.md. Memoria nueva del proyecto: presupuesto-en-chars-limite-en-tokens.md. Punteros sincronizados en la memoria de Claude Code del proyecto (jornada, gotcha nuevo, y contadores actualizados de probar-la-pieza-no-es-probar-el-uso y un-pendiente-es-una-hipotesis). Sin secretos ni datos personales.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-08-04T17:46:59.050Z",
+      "reason": "PR #137 mergeado como ed2db74; memoria persistida"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-08-04T17:46:59.102Z",
+      "reason": "cambio cerrado"
     }
   ]
 }
```

### Mensaje A

```
docs(sdd): cerrar cambio de local_commit_msg y actualizar memoria

- Actualiza el estado del cambio a `closed` en el archivo de estado.
- Registra la aprobación del gate `memory` con las notas de la jornada.
- Actualiza el handoff con la información del merge del PR #137.
```

### Mensaje B

```
ci(changes): cerrar cambio commit-msg-diffs-grandes
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 04

Diff: 3 ficheros, +65 −1

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 5fd32c4..d3f0f47 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,19 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+### Fixed
+- **El check `hooks copiados` contaba `__pycache__` como si fuera un script.** Decía «4 script(s)»
+  donde había 3, porque contaba las entradas del directorio y Python deja ahí su caché en cuanto
+  los hooks se ejecutan una vez. No es cosmético: **ese número es justo el que se mira para
+  confirmar que un script retirado desapareció** —así se verificó la retirada de `output_policy.py`
+  y compañía en la 0.27.0—, así que un directorio de más hacía que el check afirmara lo contrario
+  de lo que había pasado.
+
+  Se cuentan los `.py`. Medido antes de tocar nada sobre los **tres** probes que listan un
+  directorio: `scaffold.hook_orphans` y `scaffold.skill` no tenían el defecto —usan la lista para
+  saber si el directorio existe, no para contar—, así que el arreglo es de un solo sitio y no de
+  tres. Dos tests nuevos, uno de ellos el control que impide que el otro pase en vacío.
+
 ### Changed
 - **El hook de lectura empieza a avisar a los 8 KB y no a los 32, porque el aviso no se ignoraba:
   no llegaba.** La pregunta era por qué el asistente no delega cuando toca, y la respuesta que
diff --git a/src/local_delegate/checks.py b/src/local_delegate/checks.py
index 8a2fe36..076342a 100644
--- a/src/local_delegate/checks.py
+++ b/src/local_delegate/checks.py
@@ -582,7 +582,12 @@ def _probe_hook_files(ctx: Context) -> Result:
     faltan = [name for name in expected if name not in entries]
     if faltan:
         return Result(WARN, f"faltan scripts en {ctx.hooks_dir}: {', '.join(faltan)}", INSTALL_HINT)
-    return Result(OK, f"{len(entries)} script(s) en {ctx.hooks_dir}")
+    # Se cuentan los `.py`, no las entradas del directorio: en cuanto los hooks se ejecutan una vez,
+    # Python deja ahí un `__pycache__/` y el conteo decía «4 script(s)» donde hay 3. No es cosmético
+    # —es JUSTO el número que se mira para confirmar que un script retirado desapareció—, y con un
+    # directorio de más el check afirmaba lo contrario de lo que había pasado.
+    scripts = [name for name in entries if name.endswith(".py")]
+    return Result(OK, f"{len(scripts)} script(s) en {ctx.hooks_dir}")
 
 
 def _probe_hook_orphans(ctx: Context) -> Result:
diff --git a/tests/test_checks.py b/tests/test_checks.py
index ab8a092..015eef2 100644
--- a/tests/test_checks.py
+++ b/tests/test_checks.py
@@ -1115,3 +1115,49 @@ def test_una_entrada_stdio_no_cuenta_como_ciega(tmp_path, monkeypatch):
     result = result_for("service.daemon_auth", ctx)
 
     assert "Codex" not in result.detail
+
+
+def test_el_conteo_de_hooks_no_cuenta_el_pycache(tmp_path):
+    """`__pycache__` aparece en cuanto los hooks se ejecutan una vez, y no es un script.
+
+    No es cosmético: **ese número es justo el que se mira para confirmar que un script retirado
+    desapareció** —así se verificó la retirada de `output_policy.py` y compañía en la 0.27.0—, y
+    con un directorio de más el check afirmaba lo contrario de lo que había pasado. Medido en la
+    máquina real: decía «4 script(s)» donde había 3.
+    """
+    home = make_home(tmp_path)
+    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
+    scripts = sorted(p.name for p in hooks_dir.iterdir() if p.suffix == ".py")
+
+    antes = result_for("scaffold.hook_files", make_ctx(home))
+    assert antes.status == checks.OK
+    assert f"{len(scripts)} script(s)" in antes.detail, antes.detail
+
+    # Lo que hace Python en cuanto el hook corre una vez.
+    pycache = hooks_dir / "__pycache__"
+    pycache.mkdir()
+    (pycache / "hook_common.cpython-311.pyc").write_bytes(b"\x00")
+
+    despues = result_for("scaffold.hook_files", make_ctx(home))
+    assert despues.status == checks.OK
+    assert f"{len(scripts)} script(s)" in despues.detail, (
+        f"el __pycache__ se coló en el conteo: {despues.detail}"
+    )
+
+
+def test_el_conteo_de_hooks_sigue_los_scripts_de_verdad(tmp_path):
+    """Control del test de arriba: sin esto, un conteo clavado a mano lo dejaría en verde.
+
+    Se añade un `.py` en vez de borrar uno porque el HOME de pruebas tiene **un solo** script (el
+    de `_HOOK_EVENTS`), y quitarlo dispararía el `warn` de «faltan scripts», que es otro camino y
+    no diría nada del conteo.
+    """
+    home = make_home(tmp_path)
+    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
+    antes = len([p for p in hooks_dir.iterdir() if p.suffix == ".py"])
+
+    (hooks_dir / "hook_common.py").write_text("# ayudante", encoding="utf-8")
+
+    result = result_for("scaffold.hook_files", make_ctx(home))
+    assert result.status == checks.OK
+    assert f"{antes + 1} script(s)" in result.detail, result.detail
```

### Mensaje A

```
fix(checks): contar solo .py en hooks para excluir __pycache__

- El directorio __pycache__ de Python se contaba como script,
  alterando el número de archivos y falsificando la verificación
  de scripts retirados.
- Se filtra por extensión .py en lugar de listar entradas del
  directorio.
- Se añaden dos tests para validar el conteo correcto.
```

### Mensaje B

```
fix(checks): contar solo archivos .py en el check de hooks copiados

- Evita que el directorio `__pycache__` infle el número de scripts detectados.
- Asegura la precisión del conteo para verificar la eliminación de scripts.
- Añade tests para validar que el conteo ignore directorios y detecte nuevos archivos `.py`.
- Actualiza el CHANGELOG.md.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 05

Diff: 6 ficheros, +11 −8

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index ee25564..6f690bd 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.26.0] - 2026-08-18
+
 ### Added
 - **`doctor` ve cuando una entrada MCP no puede autenticarse contra el daemon.** Check nuevo
   `service.daemon_auth`: si el puerto del daemon exige token, comprueba que las entradas en modo
@@ -1630,7 +1632,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 - Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
   registro oficial de MCP.
 
-[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.25.0...HEAD
+[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.26.0...HEAD
+[0.26.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.25.0...v0.26.0
 [0.25.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.24.0...v0.25.0
 [0.24.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.23.0...v0.24.0
 [0.23.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.1...v0.23.0
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index e385ff2..0c7e09c 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.25.0",
-  "sha256": "ed356f95c102b7418d9141546839dfa088f277c5abd8658cee5f47c54f6638ba",
-  "bytes": 722914
+  "version": "0.26.0",
+  "sha256": "cd9e0127566d67e71b5e7335b3694a2c30825558fbdfe2a4f029c49ed0c81827",
+  "bytes": 721419
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index cc99a87..eec2443 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index c4c037a..50d51c0 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.25.0"
+version = "0.26.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/server.json b/server.json
index d1704db..d61e60c 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.25.0",
+  "version": "0.26.0",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.25.0",
+      "version": "0.26.0",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/uv.lock b/uv.lock
index 622fe10..d8ac3ad 100644
--- a/uv.lock
+++ b/uv.lock
@@ -437,7 +437,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.25.0"
+version = "0.26.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
chore(release): subir versión a 0.26.0

- Actualizar versión en pyproject.toml, server.json y uv.lock
- Actualizar CHANGELOG.md con la nueva versión
- Actualizar metadatos de dashboard.json y assets
```

### Mensaje B

```
feat: lanzamiento v0.26.0 con verificación de autenticación
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 06

Diff: 3 ficheros, +213 −0

```diff
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/plan.md b/.sdd/changes/delegacion-precisa-y-fiable/plan.md
index 0bc7528..6f77f7f 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/plan.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/plan.md
@@ -426,6 +426,49 @@ midio algo sin comprobar antes el instrumento, lo roto era la prueba.
       elegidos sobre un motor en el que no corren.
     - Rollback or recovery: no se toca `config.py`; el catalogo vigente sigue vivo hasta que F3
       escriba las cadenas sobre los roles resultantes (REQ-F2-5).
+    - Decisiones del usuario tras la tarea 20 (2026-09-15), que sustituyen dos puntos de este texto:
+      (1) **la revision humana a ciegas de §4.8 queda cubierta por los 30 pares de P-15** (15 en
+      `long`, 15 en `code`, comprobados letra a letra); no se genera la hoja 0/1/2. (2) **Produccion
+      migra a b10909 antes de que F3 toque el catalogo**: la eleccion no se transfiere sin verificar.
+    - Dato previo, medido por ejecucion (2026-09-15 13:20-13:22 UTC, `protocolo-f2.md` §10 sesion 6):
+      **los tres candidatos cargan y generan en b9925** (`D:\Projects\llms\llamacpp`, `9925
+      ed8c26150`) con el perfil del driver de produccion activo y las configs de la tanda (`--fit off
+      -ngl 99`; b9925 no tiene `--load-mode`, asi que carga con `mmap`). Gemma 4 26B-A4B `-ncmoe 0`
+      `-c 36736`: sano en 7,7 s, VRAM 14 917 MiB, 72 tok/s. Qwen3.6-35B-A3B `-ncmoe 8` `-c 7168`: 8,1
+      s, 14 847 MiB, 58 tok/s. Gemma 4 12B con `mmproj` y `ubatch 2048`: 4,6 s, 9 549 MiB, describe la
+      imagen de control. `Shared Usage` del adaptador sube como mucho 174 MiB, bajo el umbral de 1 024.
+      Consecuencia: **la migracion no la fuerza una incompatibilidad**, la fuerza REQ-F2-6 —la calidad y
+      la velocidad se midieron sobre b10909, y en b9925 solo esta comprobado que cargan—. Por eso la
+      decision (2) se mantiene, y la tarea de migrar es de F3, antes de su primera tarea de catalogo.
+    - Asignacion de roles que escribe esta tarea en `verification.md`, con el dato de cada una:
+
+      | Rol | Modelo | Criterio | Dato |
+      | --- | --- | --- | --- |
+      | `mechanical` | `gemma3-4b` (no cambia) | empate en techo, decide la velocidad | 5 casos en 1,0 los dos; 516 contra 561 ms, dentro de la banda |
+      | `long` | **Gemma 4 26B-A4B** | calidad por pares | 15 a 0; 1,8 s contra 3,0 s; techo igual |
+      | `code` | **Qwen3.6-35B-A3B** | calidad por pares | 15 a 0; techo 157 873 contra 20 171 bytes; 4,6 s contra 9,3 s |
+      | `vision` | **Gemma 4 12B** (decision del usuario, 2026-09-15) | sin agregado; caso a caso | separa en `leer-cifras-dashboard` (1,0 contra 0,67); ver abajo |
+      | `fast` | `qwen35-2b` (no cambia, no se mide) | decidido antes de medir | 2 usos en tres meses, ninguna tool lo enruta |
+
+      `vision` no la decide la regla: §7 no da agregado con dos casos. Caso a caso, Gemma 4 12B separa
+      **solo en `leer-cifras-dashboard`** (1,0 contra 0,67, banda 0); en `describir-dashboard` la
+      diferencia (1,0 contra 0,75) **es igual a la banda (0,25), no la supera**. Va mas lenta (6,1 s y
+      1,2 s contra 4,4 s y 0,5 s) y todo sale de **una sola imagen**, con un caso inventado. **El
+      usuario eligio Gemma 4 12B con este dato delante (2026-09-15)**; queda escrito como decision
+      suya sobre un caso que separa, no como resultado de la regla.
+    - **P-5 (un modelo para varios roles): no aplica con lo medido.** Cada rol sale con un modelo
+      distinto y ninguno se midio fuera de su rol. Que Gemma 4 26B-A4B pudiera cubrir tambien `vision`
+      es una hipotesis sin un solo dato, y se escribe asi en `verification.md`, no como descartada.
+    - **Lo que hereda F3, escrito aqui para que la condicion de replanificacion sea comprobable:**
+      migrar produccion a b10909 (con el perfil del driver movido y medido, porque es por ejecutable) y
+      repetir en b10909 la prueba de carga de estos tres; decidir `-ncmoe 0` o `4` para Gemma 4
+      26B-A4B (15,1 GB pico contra 14 GB de presupuesto diario; §7, salvedades); subir los candidatos
+      con el razonamiento apagado; fijar el `n_ctx` de produccion; y **`fast` queda fuera de las
+      cadenas de respaldo** —no hay dato con que declarar nada sobre el—, con la pregunta de si el rol
+      debe existir en el backlog del vault.
+    - Verification (ademas de la de arriba): las cuatro tablas de §9 pegadas desde
+      `resultados/decidir-final.md`, generadas y no copiadas a mano; la tabla de roles; y la condicion de replanificacion de F3
+      comprobada frase a frase contra este bloque.
 
 ### F3 - Respaldo y enfriamiento (bloque, se replanifica)
 
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
index f46a38b..edc33fc 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
@@ -1900,6 +1900,27 @@ s** (`cudaMalloc` 12 288 MiB, sale con 0xC0000005, esta vez con la linea de OOM
 daemon se arranco despues. La votacion por pares no necesita la maquina. La entrada de
 `llama-bench.exe` en la NVIDIA App queda a criterio del usuario.
 
+**Sesion 6, ¿cargan los candidatos en b9925? (2026-09-15, 13:20:28-13:22:15 UTC, tarea 21).** Con el
+daemon de produccion arriba y su llama-swap **sin ningun `llama-server` cargado** (VRAM 674 MiB), se
+lanzo `D:\Projects\llms\llamacpp\llama-server.exe` (`version: 9925 (ed8c26150)`) a mano en el puerto
+9696, uno cada vez, con el perfil del driver de produccion activo (medido a las 12:10: b9925 OOM).
+Flags comunes `--fit off -ngl 99 --cache-ram 1024 -np 1 --jinja --reasoning off`, y los del modelo
+como en `llama-swap-pruebas.yaml` (`t-*`); b9925 **no tiene `--load-mode`**, asi que carga con `mmap`,
+su defecto. Criterio: `/health` en `ok` y una peticion real que devuelva texto.
+
+| Modelo | Config | Sano en | VRAM usada | `Shared Usage` adaptador (reposo -> cargado) | Peticion |
+| --- | --- | --- | --- | --- | --- |
+| Gemma 4 26B-A4B | `-ncmoe 0 -c 36736` | 7,7 s | 14 917 MiB | 165 -> 221 MiB | codigo Python correcto, `stop`, 19 tok, 72,3 tok/s |
+| Qwen3.6-35B-A3B | `-ncmoe 8 -c 7168` | 8,1 s | 14 847 MiB | 165 -> 188 MiB | codigo Python correcto, `stop`, 19 tok, 58,0 tok/s |
+| Gemma 4 12B | `--mmproj` `-c 8192 --batch-size 2048 --ubatch-size 2048` | 4,6 s | 9 549 MiB | 165 -> 339 MiB | con `dashboard-bcbe39f.png`: «un panel de estadisticas de un servidor [...]», `stop`, 19 tok, 48,1 tok/s |
+
+Los dos de texto se corrieron **dos veces** (13:20 y 13:21): la primera cargaron igual (7,3 s y 8,1 s,
+VRAM 14 920 y 14 847 MiB) y el fallo fue del script, que recortaba la respuesta con la longitud
+equivocada; la tabla es la segunda. Ninguna linea de `error`, `fail`, `unsupported` ni OOM en los logs.
+Lo que esto **no** prueba: calidad ni velocidad en b9925 —un solo prompt corto, sin corpus—, ni que
+cargue con escritorio ocupando VRAM. Para la quinta medicion de adopcion (§1.5): el intervalo toco la
+GPU con produccion arriba; si llego alguna delegacion en esos dos minutos, pudo competir por VRAM.
+
 **Sesion 5, cierre del setup de medicion.** La tanda termino a las 04:21:01 UTC con llama-swap de
 pruebas y `llama-server` parados. **A las 04:31:35 la tarea `LocalDelegateDaemon` volvio a arrancar
 el daemon de produccion** (y su llama-swap en 9292, con b9925), sin intervencion de la sesion que
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/verification.md b/.sdd/changes/delegacion-precisa-y-fiable/verification.md
index 61b1fec..bb1b643 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/verification.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/verification.md
@@ -696,3 +696,152 @@ Resultado y salvedades en `protocolo-f2.md` §7 «Resultado de la tarea 20»; in
 ### Suite
 
 `uv run pytest -q`: **1119 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios.
+
+## F2: tarea 21, asignacion de roles y que pasa a produccion (2026-09-15)
+
+Detalle y lo que hereda F3 en `plan.md`, tarea 21. Prueba de carga en b9925 en `protocolo-f2.md` §10,
+sesion 6.
+
+### Roles (REQ-F2-4)
+
+| Rol | Modelo | Criterio | Dato que lo sostiene |
+| --- | --- | --- | --- |
+| `mechanical` | `gemma3-4b`, **no cambia** (REQ-F2-6) | empate en techo, decide la velocidad | los 5 casos en 1,0 con los dos; 516 contra 561 ms, dentro de la banda. La regla no puede disparar en este rol: «no cambia» no distingue nada |
+| `long` | **Gemma 4 26B-A4B** `-ncmoe 0` | calidad por pares | 15 a 0; `extraer-uvlock-48k` 1,0 contra 0,5; 1,8 s contra 3,0 s; techo igual (106 092 bytes) |
+| `code` | **Qwen3.6-35B-A3B** `-ncmoe 8` | calidad por pares | 15 a 0; `boilerplate-156` 1,0 contra 0,8; 4,6 s contra 9,3 s; techo 157 873 contra 20 171 bytes |
+| `vision` | **Gemma 4 12B** | **decision del usuario**, no de la regla | §7 sin agregado. Separa en `leer-cifras-dashboard` (1,0 contra 0,67, banda 0); en `describir-dashboard` la diferencia (0,25) iguala la banda. Mas lenta (6,1 s y 1,2 s contra 4,4 s y 0,5 s). Una sola imagen, un caso inventado |
+| `fast` | `qwen35-2b`, **no cambia y no se mide** | decidido antes de medir (desviacion aprobada en el gate de plan) | 2 usos reales en tres meses; ninguna tool lo enruta; cero casos en el corpus |
+
+**Un modelo para varios roles (P-5): no se da.** Cada rol sale con un modelo distinto, y ninguno se
+midio fuera de su rol; que Gemma 4 26B-A4B cubra `vision` es una hipotesis sin dato, no un descarte.
+
+**Revision humana (REQ-F2-2):** la cubren los 30 pares a ciegas (15 en `long`, 15 en `code`),
+comprobados letra a letra contra la hoja; no se genera la hoja 0/1/2 de §4.8 (decision del usuario).
+
+### Que pasa a produccion
+
+**La medida es sobre b10909 y produccion corre b9925.** Se comprobo por ejecucion que los tres modelos
+nuevos **cargan y generan en b9925** con el perfil del driver activo (Gemma 4 26B-A4B 14 917 MiB, Qwen3.6
+14 847 MiB, Gemma 4 12B 9 549 MiB con imagen), asi que la migracion no la fuerza una incompatibilidad.
+La fuerza REQ-F2-6: calidad y velocidad solo estan medidas sobre b10909. **Decision del usuario:
+produccion migra a b10909 antes de que F3 toque el catalogo.** `config.py` no se toca en F2.
+
+Salvedades que hereda F3: Gemma 4 26B-A4B `-ncmoe 0` **no cabe en el presupuesto de uso diario**
+(15,1 GB de VRAM pico contra 14; la alternativa medida es `-ncmoe 4`); los candidatos van con el
+razonamiento apagado; Gemma 4 12B necesita `--ubatch-size 2048`; el `n_ctx` de produccion esta por
+fijar; y `fast` queda fuera de las cadenas de respaldo.
+
+### Las cuatro tablas de §9
+
+Pegadas por programa desde `benchmarks/catalogo-2026-09/resultados/decidir-final.md` (salida de
+`analizar_benchmark.py decidir`), sin editar. El veredicto `sin_agregado` de `vision` es el de la regla;
+la asignacion es la de la tabla de roles de arriba. Las anuladas son todas primeras corridas por
+`process_changed` y una `zero_vram_samples`, repetidas por el runner; los `rechazo_por_contexto` son las
+5 corridas de `techo-commit-156k` con `qwen25-coder-14b` (contexto nativo de 32 768 tokens, §10 sesion 5).
+
+#### Tabla 1: por rol
+
+| Rol | Vigente | Candidato | Calidad v / c | Banda | Latencia ms v / c | RAM host pico c | RAM privada pico c | Working set pico c | VRAM dedicada pico c | Shared pico c | Cabe uso diario c | Descartadas | Rechazos | Veredicto | Criterio |
+| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
+| mechanical | gemma3-4b | gemma4-e4b | 1.000 / 1.000 | 0.100 | 516 / 561 | 3835772928 | 10081951744 | 3419594752 | 3477020672 | 2434793472 | si | 0 | 0 | **no_sustituye** | empate |
+| long | llama31-8b | gemma4-26b-a4b | 0.500 / 1.000 | 0.000 | 3013 / 1849 | 3716284416 | 18551582720 | 3419594752 | 15100747776 | 918552576 | no | 0 | 0 | **sustituye** | calidad |
+| code | qwen25-coder-14b | qwen36-35b-a3b | 0.800 / 1.000 | 0.600 | 9348 / 4619 | 6123499520 | 21017739264 | 5472796672 | 14894239744 | 3625975808 | si | 0 | 0 | **sustituye** | calidad |
+| vision | qwen3-vl-8b | gemma4-12b | — / — | — | — / — | 4960354304 | 13616750592 | 3321196544 | 9496805376 | 759169024 | si | 0 | 0 | **sin_agregado** | — |
+
+##### mechanical: no_sustituye
+
+- nadie mejora al vigente: el rol no se cambia (REQ-F2-6)
+- casos en el agregado: 0 (ninguno)
+- fuera del agregado: resumen-md-2k (techo)
+- fuera del agregado: extraer-toml-2k (techo)
+- fuera del agregado: clasificar-53 (techo)
+- fuera del agregado: traducir-42 (techo)
+- fuera del agregado: delegar-56 (techo)
+- **la regla no puede disparar**: ni un candidato con calidad 1,0 superaria la banda; «no se cambia» aqui no distingue nada
+
+##### long: sustituye
+
+- casos en el agregado: 0 (ninguno)
+- fuera del agregado: extraer-uvlock-48k (techo)
+- comparacion por pares (resumen-md-10k, resumen-changelog-7k, lint-9k): candidato 15, vigente 0, empates 0 -> **mejor**
+
+##### code: sustituye
+
+- casos en el agregado: 1 (boilerplate-156)
+- comparacion por pares (commit-diff-19k, explicar-metrics-15k, explicar-install-20k): candidato 15, vigente 0, empates 0 -> **mejor**
+- **la regla no puede disparar**: ni un candidato con calidad 1,0 superaria la banda; «no se cambia» aqui no distingue nada
+
+##### vision: sin_agregado
+
+- vision no presenta agregado (§7): decide la tabla caso a caso y la revision
+
+#### Tabla 2: caso a caso
+
+| Rol | Caso | Modelo | Corridas (calidad, outcome) | Mediana | Dispersion | Latencia mediana |
+| --- | --- | --- | --- | --- | --- | --- |
+| mechanical | resumen-md-2k | gemma3-4b | 1.00 ok fria, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 1697 |
+| mechanical | extraer-toml-2k | gemma3-4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 467 |
+| mechanical | clasificar-53 | gemma3-4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 71 |
+| mechanical | traducir-42 | gemma3-4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 113 |
+| mechanical | delegar-56 | gemma3-4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 233 |
+| mechanical | resumen-md-2k | gemma4-e4b | 1.00 ok, 1.00 ok, 0.50 ok, 1.00 ok, 1.00 ok | 1.000 | 0.500 | 1731 |
+| mechanical | extraer-toml-2k | gemma4-e4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 605 |
+| mechanical | clasificar-53 | gemma4-e4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 85 |
+| mechanical | traducir-42 | gemma4-e4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 116 |
+| mechanical | delegar-56 | gemma4-e4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 267 |
+| long | resumen-md-10k | llama31-8b | 0.33 ok, 0.00 ok, 0.00 ok, 0.00 ok, 0.67 ok | 0.000 | 0.667 | 4645 |
+| long | resumen-changelog-7k | llama31-8b | 1.00 ok, 0.33 ok, 0.83 ok, 0.83 ok, 0.50 ok | 0.833 | 0.667 | 3837 |
+| long | extraer-uvlock-48k | llama31-8b | 0.50 ok, 0.50 ok, 0.50 ok, 0.50 ok, 0.50 ok | 0.500 | 0.000 | 558 |
+| long | lint-9k | llama31-8b | 0.00 truncado, 0.00 truncado, 0.00 truncado, 0.00 truncado, 0.00 truncado | 0.000 | 0.000 | — |
+| long | techo-resumen-103k | llama31-8b | — truncado, — truncado, — truncado, — truncado, — truncado | — | — | — |
+| long | resumen-md-10k | gemma4-26b-a4b | 0.67 ok, 0.67 ok, 0.67 ok, 0.67 ok, 0.67 ok | 0.667 | 0.000 | 2519 |
+| long | resumen-changelog-7k | gemma4-26b-a4b | 0.83 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.167 | 2486 |
+| long | extraer-uvlock-48k | gemma4-26b-a4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 543 |
+| long | lint-9k | gemma4-26b-a4b | 0.33 ok, 0.33 ok, 0.33 ok, 0.33 ok, 0.33 ok | 0.333 | 0.000 | 5794 |
+| long | techo-resumen-103k | gemma4-26b-a4b | — ok, — ok, — ok, — ok, — ok | — | — | 3290 |
+| code | commit-diff-19k | qwen25-coder-14b | 0.00 ok, 0.00 ok, 0.00 ok, 0.00 ok, 0.00 ok | 0.000 | 0.000 | 684 |
+| code | explicar-metrics-15k | qwen25-coder-14b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 16359 |
+| code | explicar-install-20k | qwen25-coder-14b | 0.60 ok, 0.80 ok, 0.20 ok, 0.60 ok, 0.80 ok | 0.600 | 0.600 | 11719 |
+| code | boilerplate-156 | qwen25-coder-14b | 1.00 ok, 1.00 ok, 0.80 ok, 0.80 ok, 0.60 ok | 0.800 | 0.400 | 8628 |
+| code | techo-commit-156k | qwen25-coder-14b | — rechazo_por_contexto, — rechazo_por_contexto, — rechazo_por_contexto, — rechazo_por_contexto, — rechazo_por_contexto | — | — | — |
+| code | commit-diff-19k | qwen36-35b-a3b | 0.20 ok, 0.20 ok, 0.20 ok, 0.20 ok, 0.20 ok | 0.200 | 0.000 | 270 |
+| code | explicar-metrics-15k | qwen36-35b-a3b | 0.29 ok, 0.57 ok, 0.29 ok, 0.29 ok, 0.29 ok | 0.286 | 0.286 | 4277 |
+| code | explicar-install-20k | qwen36-35b-a3b | 0.40 ok, 0.80 ok, 0.60 ok, 0.40 ok, 0.40 ok | 0.400 | 0.400 | 4373 |
+| code | boilerplate-156 | qwen36-35b-a3b | 1.00 ok, 1.00 ok, 1.00 ok, 0.40 ok, 1.00 ok | 1.000 | 0.600 | 9555 |
+| code | techo-commit-156k | qwen36-35b-a3b | — ok, — ok, — ok, — ok, — ok | — | — | 375 |
+| vision | describir-dashboard | qwen3-vl-8b | 1.00 ok, 0.75 ok, 0.75 ok, 1.00 ok, 0.75 ok | 0.750 | 0.250 | 4431 |
+| vision | leer-cifras-dashboard | qwen3-vl-8b | 0.67 ok, 0.67 ok, 0.67 ok, 0.67 ok, 0.67 ok | 0.667 | 0.000 | 524 |
+| vision | describir-dashboard | gemma4-12b | 1.00 ok fria, 1.00 ok, 0.75 ok, 0.75 ok, 1.00 ok | 1.000 | 0.250 | 6080 |
+| vision | leer-cifras-dashboard | gemma4-12b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 1213 |
+
+#### Tabla 3: entorno
+
+| Modelo | n_ctx | --load-mode | -ncmoe | llama-server | llama-swap | Anuladas (motivo) |
+| --- | --- | --- | --- | --- | --- | --- |
+| gemma3-4b | 2560 | none | — | b10909 | v255 | — |
+| gemma4-e4b | 2560 | none | — | b10909 | v255 | resumen-md-2k run=1 (process_changed) |
+| llama31-8b | 36736 | none | — | b10909 | v255 | resumen-md-10k run=1 (process_changed); techo-resumen-103k run=1 (process_changed) |
+| llama31-8b | 65536 | none | — | b10909 | v255 | resumen-md-10k run=1 (process_changed); techo-resumen-103k run=1 (process_changed) |
+| gemma4-26b-a4b | 36736 | none | 0 | b10909 | v255 | resumen-md-10k run=1 (process_changed); techo-resumen-103k run=1 (process_changed) |
+| gemma4-26b-a4b | 65536 | none | 0 | b10909 | v255 | resumen-md-10k run=1 (process_changed); techo-resumen-103k run=1 (process_changed) |
+| qwen25-coder-14b | 65536 | none | — | b10909 | v255 | commit-diff-19k run=1 (process_changed); techo-commit-156k run=1 (process_changed); techo-commit-156k run=1 (zero_vram_samples) |
+| qwen25-coder-14b | 7168 | none | — | b10909 | v255 | commit-diff-19k run=1 (process_changed); techo-commit-156k run=1 (process_changed); techo-commit-156k run=1 (zero_vram_samples) |
+| qwen36-35b-a3b | 65536 | none | 8 | b10909 | v255 | commit-diff-19k run=1 (process_changed); techo-commit-156k run=1 (process_changed) |
+| qwen36-35b-a3b | 7168 | none | 8 | b10909 | v255 | commit-diff-19k run=1 (process_changed); techo-commit-156k run=1 (process_changed) |
+| qwen3-vl-8b | 8192 | none | — | b10909 | v255 | describir-dashboard run=1 (process_changed) |
+| gemma4-12b | 8192 | none | — | b10909 | v255 | — |
+
+Tanda concluyente segun §6: **si**.
+
+#### Tabla 4: techo
+
+| Rol | Modelo | Mayor entrada aceptada (bytes) |
+| --- | --- | --- |
+| mechanical | gemma3-4b | 2075 |
+| mechanical | gemma4-e4b | 2075 |
+| long | llama31-8b | 106092 |
+| long | gemma4-26b-a4b | 106092 |
+| code | qwen25-coder-14b | 20171 |
+| code | qwen36-35b-a3b | 157873 |
+| vision | qwen3-vl-8b | 718456 |
+| vision | gemma4-12b | 718456 |
```

### Mensaje A

```
docs(f2): registrar tarea 21, roles y carga en b9925
```

### Mensaje B

```
docs(delegacion): registrar resultados de la tarea 21 y asignación de roles

- Añadir pruebas de carga en b9925 al protocolo de ejecución.
- Documentar la asignación final de modelos para los roles `long`, `code` y `vision`.
- Incluir tablas de resultados detalladas en la verificación.
- Registrar decisiones del usuario sobre la migración de producción a b10909.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 07

Diff: 3 ficheros, +181 −24

````diff
diff --git a/.sdd/changes/opencode-tercer-cliente/handoff.md b/.sdd/changes/opencode-tercer-cliente/handoff.md
index ae7de00..ce48de7 100644
--- a/.sdd/changes/opencode-tercer-cliente/handoff.md
+++ b/.sdd/changes/opencode-tercer-cliente/handoff.md
@@ -2,12 +2,16 @@
 
 ## Current state
 
-- SDD status: `verifying`. Gates `spec` y `plan` aprobados; `quality`, `conformance` y `memory`
-  pendientes de la revisión del usuario, con la evidencia ya recogida en `verification.md`.
-- Rama `claude/opencode-mcb-integration-m8q9qq`, base `67e585f`.
-- Suite: **700 passed, 4 skipped, 1 failed**. El fallo es anterior y ambiental (la suite corre
-  como root y `chmod 000` no le quita permiso de lectura); baseline antes de tocar nada:
-  `667 passed, 1 failed`, el mismo.
+- SDD status: **`closed`** (2026-09-08). Los cinco gates aprobados. El código lleva en `main` desde
+  el PR #123 y salió publicado con la 0.19.0; el cambio se quedó en `verifying` un mes por los tres
+  gates finales, no por trabajo pendiente.
+- Suite en el cierre: **794 passed, 2 skipped** en Windows, con los 36 tests propios del change en
+  verde. La evidencia de agosto (`710 passed`) era de un árbol con 84 tests menos y **no** se
+  reutilizó: todo se volvió a medir. Ver la sección «Revalidación para el cierre» de
+  `verification.md`.
+- Verificado también contra el binario real de **opencode 1.18.29** en Windows (agosto fue 1.18.11
+  en Linux): `opencode mcp add` sigue registrando la entrada, conserva comentarios y claves del
+  usuario, y `opencode mcp list` dice `connected`.
 
 ## What changed
 
@@ -39,6 +43,9 @@ Las cuatro que no se deducen del código, cada una con lo que las decidió:
   estilo: una clave de primer nivel desconocida hace que opencode **no arranque**. De ahí también
   que no exista un `--force-mcp-opencode`: sin marcadores no hay forma de distinguir nuestra
   entrada de una escrita a mano, exactamente como en Claude Code.
+  *(Al cerrar, 2026-09-08: la primera mitad de ese motivo **caducó**. Medido contra los dos
+  binarios el mismo día, 1.18.11 rechaza la clave desconocida y **1.18.29 ya no**. La decisión se
+  mantiene —ahora por prudencia— y la segunda mitad, la de los marcadores, sigue intacta.)*
 - **La skill y la memoria se instalan en el sitio propio de opencode**, aunque esté medido que lee
   `~/.claude/skills/` y `~/.claude/CLAUDE.md`. Las dos compatibilidades son apagables
   (`OPENCODE_DISABLE_EXTERNAL_SKILLS`, `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT`) y **no existen** en
@@ -65,10 +72,17 @@ Dos cosas que se decidieron **midiendo, no diseñando**:
 
 ## Next steps
 
-1. Aprobar los gates `quality` y `conformance` con `verification.md` delante.
-2. Dejar que el CI corra el e2e en Windows y macOS: es lo único de este change que aquí solo se
-   ejercitó en Linux.
-3. Al publicar, la línea del `CHANGELOG` ya está redactada en `Unreleased`.
+Ninguno para este change: cerrado el 2026-09-08 con los cinco gates aprobados, el código en `main`
+y el CI en verde. Lo que salió de la revalidación y **no** pertenece aquí:
+
+1. **Tres frases de documentación desactualizadas por el cliente, no por nosotros.** `spec.md`
+   (REQ-011), el docstring de `install.py` y `docs/wiki/Integration-install.md` dicen que una clave
+   de primer nivel desconocida impide arrancar opencode. Era cierto en 1.18.11 y **ya no lo es en
+   1.18.29** (medido con los dos binarios el mismo día). El comportamiento del paquete no cambia;
+   corregir la justificación es un cambio de documentación aparte.
+2. **`update` repone en el transporte de la máquina, no en el que había.** Con el daemon levantado,
+   una entrada `stdio` borrada vuelve como `http`. Hace lo mismo con Claude Code, así que es
+   comportamiento de `update` y no de este change; queda anotado por si alguna vez sorprende.
 
 ## Cómo repetir las mediciones
 
diff --git a/.sdd/changes/opencode-tercer-cliente/state.json b/.sdd/changes/opencode-tercer-cliente/state.json
index 14507bf..854b9b8 100644
--- a/.sdd/changes/opencode-tercer-cliente/state.json
+++ b/.sdd/changes/opencode-tercer-cliente/state.json
@@ -3,9 +3,9 @@
   "slug": "opencode-tercer-cliente",
   "title": "opencode como tercer cliente de install",
   "mode": "standard",
-  "status": "verifying",
+  "status": "closed",
   "createdAt": "2026-08-02T15:45:00.000Z",
-  "updatedAt": "2026-08-02T21:30:00.000Z",
+  "updatedAt": "2026-09-09T01:10:07.588Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -20,22 +20,22 @@
       "actor": "user"
     },
     "quality": {
-      "status": "pending",
-      "updatedAt": "2026-08-02T17:40:00.000Z",
-      "evidence": "pytest 710 passed 2 skipped en Windows (en Linux eran 701 passed 4 skipped con 1 failed ambiental: la suite corre como root y chmod 000 no le quita lectura; baseline 667 passed con el mismo fallo); ruff check All checks passed; ruff format 74 files already formatted; extract_dashboard_js exit 0; check_install_e2e OK en linux y en win32 (ampliado para cubrir opencode); 11 mutantes verificados al reves, cada uno rompe su propio test; verificado contra el binario real: opencode mcp list responde local-delegate connected. Dos revisiones del diff encontraron dos defectos reales, ambos corregidos con test: la lectura tolerante que confundia vacio con ilegible, y el falso OK del check de la skill (miraba solo la de Claude Code mientras install la escribia tambien en opencode, asi que doctor decia 'instalada' con la de opencode borrada y update no la reponia)",
-      "actor": "pending"
+      "status": "approved",
+      "updatedAt": "2026-09-09T01:03:02.365Z",
+      "evidence": "Revalidado el 2026-09-08 contra el arbol de hoy, sin reutilizar la evidencia de agosto: pytest 794 passed 2 skipped (los 36 propios del change en verde); ruff check All checks passed; ruff format 77 files already formatted; extract_dashboard_js exit 0; check_install_e2e instalador OK en win32. Ademas los 8 escenarios de aceptacion reejecutados end-to-end con el CLI real sobre HOMEs simulados: 26/26 comprobaciones en verde, con control positivo (--no-mcp --no-skill no deja fichero, asi que un OK vacio se caeria solo). REQ-030 medido y no razonado: con la entrada MCP y la skill borradas, doctor las da por FALT y update las repone.",
+      "actor": "user"
     },
     "conformance": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": "",
-      "actor": "pending"
+      "status": "approved",
+      "updatedAt": "2026-09-09T01:03:13.418Z",
+      "evidence": "Revision fresca contra los 34 requisitos con el codigo de main de hoy. Verificado contra el binario REAL de opencode 1.18.29 (agosto fue 1.18.11 en Linux; esto es Windows): debug paths resuelve a <home>/.config/opencode; opencode mcp add registra la entrada conservando comentario y clave theme del usuario; reejecutar deja una sola entrada; nuestra entrada escrita a mano coincide clave por clave con la que escribe la CLI (lo que sostiene no escribir enabled: true); opencode mcp list dice local-delegate connected. REQ-034 remedido: el initialize declara solo roots, protocolo 2025-11-25, sin elicitation. Dos derivas deliberadas ya documentadas: enabled (REQ-007/008) quitado por medicion, y diecisiete->dieciocho checks (REQ-029/032) por un check posterior, con el test del docstring en verde. Un hallazgo: la justificacion de REQ-011 caduco con la version del cliente -- 1.18.11 rechaza una clave de primer nivel desconocida (exit 1, Unrecognized key) y 1.18.29 ya no. La medicion de agosto era correcta; el cliente relajo la validacion. El comportamiento del paquete no cambia (no escribir claves ajenas sigue siendo lo correcto); lo que queda desactualizado son tres frases de documentacion, que son un cambio aparte. Todo en verification.md.",
+      "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": "",
-      "actor": "pending"
+      "status": "approved",
+      "updatedAt": "2026-09-09T01:05:52.076Z",
+      "evidence": "Handoff actualizado al estado de cierre (suite del cierre, verificacion contra 1.18.29 en Windows, y los dos cabos que NO pertenecen a este change). Nota durable en el vault: projects/local-delegate/jornada-2026-09-08-la-justificacion-que-caduco.md, con el metodo (instalar tambien la version vieja para distinguir 'me equivoque' de 'el mundo cambio') y las dos trampas de medicion. Puntero anadido a la memoria del proyecto en Claude Code. Sin secretos ni datos personales: el escenario del token comprueba justamente que el valor NO llega a disco.",
+      "actor": "user"
     }
   },
   "history": [
@@ -101,6 +101,51 @@
       "type": "note",
       "at": "2026-08-02T21:30:00.000Z",
       "note": "Revision del diff desde Windows: dos correcciones. (1) Falso OK del check de la skill, que miraba solo ~/.claude/skills mientras plan_install la escribia tambien en opencode: con Claude Code presente, doctor decia 'instalada' con la de opencode borrada y update no la reponia. Corregido en _probe_skill (recorre _clientes) y en el Repair (PRESENT en vez de claude); anadido REQ-030b. Un test pasaba por la guarda equivocada (se llamaba 'solo Codex' con opencode instalado por defecto). Tres mutantes nuevos, cada uno cazado. (2) Cuatro ficheros habian pasado de CRLF a LF al editarse desde un runner Linux, inflando el diff de 2213 a 4340 lineas; devueltos a CRLF. Verificado en Windows: 710 passed 2 skipped, ruff limpio, check_install_e2e OK en win32"
+    },
+    {
+      "type": "gate",
+      "gate": "quality",
+      "status": "approved",
+      "at": "2026-09-09T01:03:02.365Z",
+      "evidence": "Revalidado el 2026-09-08 contra el arbol de hoy, sin reutilizar la evidencia de agosto: pytest 794 passed 2 skipped (los 36 propios del change en verde); ruff check All checks passed; ruff format 77 files already formatted; extract_dashboard_js exit 0; check_install_e2e instalador OK en win32. Ademas los 8 escenarios de aceptacion reejecutados end-to-end con el CLI real sobre HOMEs simulados: 26/26 comprobaciones en verde, con control positivo (--no-mcp --no-skill no deja fichero, asi que un OK vacio se caeria solo). REQ-030 medido y no razonado: con la entrada MCP y la skill borradas, doctor las da por FALT y update las repone.",
+      "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "conformance",
+      "status": "approved",
+      "at": "2026-09-09T01:03:13.418Z",
+      "evidence": "Revision fresca contra los 34 requisitos con el codigo de main de hoy. Verificado contra el binario REAL de opencode 1.18.29 (agosto fue 1.18.11 en Linux; esto es Windows): debug paths resuelve a <home>/.config/opencode; opencode mcp add registra la entrada conservando comentario y clave theme del usuario; reejecutar deja una sola entrada; nuestra entrada escrita a mano coincide clave por clave con la que escribe la CLI (lo que sostiene no escribir enabled: true); opencode mcp list dice local-delegate connected. REQ-034 remedido: el initialize declara solo roots, protocolo 2025-11-25, sin elicitation. Dos derivas deliberadas ya documentadas: enabled (REQ-007/008) quitado por medicion, y diecisiete->dieciocho checks (REQ-029/032) por un check posterior, con el test del docstring en verde. Un hallazgo: la justificacion de REQ-011 caduco con la version del cliente -- 1.18.11 rechaza una clave de primer nivel desconocida (exit 1, Unrecognized key) y 1.18.29 ya no. La medicion de agosto era correcta; el cliente relajo la validacion. El comportamiento del paquete no cambia (no escribir claves ajenas sigue siendo lo correcto); lo que queda desactualizado son tres frases de documentacion, que son un cambio aparte. Todo en verification.md.",
+      "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-09-09T01:05:52.076Z",
+      "evidence": "Handoff actualizado al estado de cierre (suite del cierre, verificacion contra 1.18.29 en Windows, y los dos cabos que NO pertenecen a este change). Nota durable en el vault: projects/local-delegate/jornada-2026-09-08-la-justificacion-que-caduco.md, con el metodo (instalar tambien la version vieja para distinguir 'me equivoque' de 'el mundo cambio') y las dos trampas de medicion. Puntero anadido a la memoria del proyecto en Claude Code. Sin secretos ni datos personales: el escenario del token comprueba justamente que el valor NO llega a disco.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-09-09T01:06:10.705Z",
+      "reason": "Evidencia revalidada el 2026-09-08 (suite, ocho escenarios e2e y binario real de opencode 1.18.29 en Windows); pasa a revision del resultado contra la spec."
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-09-09T01:10:07.345Z",
+      "reason": "Revision del resultado hecha por medicion: 26/26 escenarios e2e, 9/10 comprobaciones contra el binario real 1.18.29, y las tres desviaciones de la spec resueltas y documentadas en verification.md."
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-09-09T01:10:07.588Z",
+      "reason": "Cinco gates aprobados con evidencia revalidada el 2026-09-08 contra el arbol y el binario de hoy. El codigo lleva en main desde el PR #123."
     }
   ]
 }
diff --git a/.sdd/changes/opencode-tercer-cliente/verification.md b/.sdd/changes/opencode-tercer-cliente/verification.md
index cafdbaa..dc27d70 100644
--- a/.sdd/changes/opencode-tercer-cliente/verification.md
+++ b/.sdd/changes/opencode-tercer-cliente/verification.md
@@ -170,3 +170,101 @@ inspección directa del artefacto:
 - **El camino por CLI bajo `--home`.** Está apagado a propósito (`use_cli=False` con HOME simulado)
   para que la suite no dependa de qué binarios haya en la máquina. Se ejercitó a mano, con el
   binario real, llamando a `_register_opencode_mcp` directamente (punto 2 de arriba).
+
+## Revalidación para el cierre (2026-09-08)
+
+El código lleva en `main` desde el PR #123 y la evidencia de arriba es del 2 de agosto. Antes de
+cerrar los gates se **volvió a medir todo**, contra el árbol de hoy y contra el binario de hoy. No
+se reutilizó ni una línea de la evidencia anterior.
+
+### Suite y estática, hoy
+
+```
+uv run pytest -q             → 794 passed, 2 skipped
+uv run pytest tests/test_install_opencode.py -q → 36 passed
+uv run ruff check .          → All checks passed!
+uv run ruff format --check   → 77 files already formatted
+scripts/extract_dashboard_js.py → exit 0
+scripts/check_install_e2e.py    → instalador OK en win32
+```
+
+Los `710 passed` de agosto eran de un árbol con 84 tests menos. Los 36 propios de este change
+siguen todos en verde.
+
+### Los ocho escenarios de aceptación, reejecutados
+
+Corridos con el CLI de verdad sobre HOMEs simulados, comprobando el artefacto en disco:
+**26 de 26 comprobaciones en verde**. Cubren los siete escenarios de `spec.md` que no dependen del
+binario del cliente: solo-opencode (sin crear `.claude` ni `.codex`), idempotencia con `theme` y
+entrada MCP ajena, comentarios sin CLI (fichero intacto byte a byte, exit code sin subir, y el
+aviso con ruta + motivo + qué hacer), HTTP con `{env:LOCAL_DELEGATE_WEB_TOKEN}` y **sin** el valor
+del token en disco, desinstalación que deja la entrada ajena y el `theme`, config roto que no se
+toca, y `--home` con `XDG_CONFIG_HOME` puesta escribiendo dentro del árbol simulado.
+
+**Control positivo:** con `--no-mcp --no-skill` el fichero de config no llega a existir, así que
+una comprobación que diera `ok` sin haberse escrito nada se caería sola. Se verificó.
+
+**REQ-030, medido y no razonado:** con la entrada MCP y la skill borradas a mano, `doctor` las da
+las dos por `[FALT]` y `update` las repone; el `doctor` posterior las da por `[ OK ]`. De paso se
+observó que `update` repone en el transporte que corresponde a **la máquina** (aquí `http`, con el
+daemon levantado) aunque la instalación original fuera `stdio`. **No es de este change**: se
+comprobó que hace exactamente lo mismo con la entrada de Claude Code.
+
+### Contra el binario real, hoy y en Windows
+
+En agosto esto se midió en Linux contra opencode **1.18.11**. Se repitió contra **1.18.29**, que es
+lo que instala hoy `npm i opencode-ai@latest`, y en Windows, que en agosto era justo lo que faltaba:
+
+| Comprobación | Resultado |
+|---|---|
+| `debug paths` apunta a `<home>/.config/opencode` | OK |
+| `opencode mcp add` con nuestros args registra la entrada | OK |
+| el comentario y la clave `theme` del usuario sobreviven | OK |
+| reejecutar deja **una sola** entrada | OK |
+| nuestra entrada escrita a mano == la que escribe la CLI | OK (mismas claves y mismo contenido) |
+| `opencode mcp list` → `✓ local-delegate connected` | OK |
+
+La quinta fila es la que sostiene la decisión de **no escribir `"enabled": true`**: los dos caminos
+siguen dejando exactamente la misma forma en disco.
+
+**REQ-034 remedido:** el `initialize` de 1.18.29 declara `capabilities {"roots":{}}`, protocolo
+`2025-11-25`, `clientInfo {"name":"opencode","version":"1.18.29"}`. Sigue **sin** `elicitation`, así
+que la documentación no promete nada falso.
+
+### Un hallazgo: la justificación de REQ-011 caducó con la versión del cliente
+
+`spec.md` (REQ-011), el docstring de `install.py` y `docs/wiki/Integration-install.md` dicen que una
+clave de primer nivel desconocida hace que opencode **no arranque** (`ConfigInvalidError`), y que
+por eso no existe un `--force-mcp-opencode`. Medido hoy con los dos binarios, mismo config y mismos
+subcomandos:
+
+| opencode | `{"clave_que_no_existe": true}` |
+|---|---|
+| **1.18.11** (el de agosto) | `exit=1`, «Unrecognized key» en `mcp list`, `debug config` y `models` |
+| **1.18.29** (hoy) | `exit=0`, sin queja: la tolera |
+
+La medición de agosto **era correcta**; el cliente relajó la validación entre las dos versiones.
+
+Dos avisos sobre cómo se midió, porque la primera pasada no discriminaba:
+
+- **El `exit code` no sirve de señal**: con un JSON sintácticamente roto, opencode imprime
+  `Error: Config file ... is not valid JSON(C)` y aun así **devuelve 0**. Hay que mirar la salida.
+  (Es el mismo aprendizaje que ya está en el código para `_register_opencode_mcp`.)
+- **Con un control positivo que tampoco discriminaba** —`{"theme": 12345}`, tipo equivocado en una
+  clave que sí existe— **ninguna** de las dos versiones se queja. La validación que existía en
+  1.18.11 era específica de claves desconocidas, no del esquema entero.
+
+**Qué cambia y qué no.** El comportamiento del paquete **no cambia**: no escribir ninguna clave
+ajena a `mcp` sigue siendo lo correcto, ahora por prudencia en vez de por obligación, y la ausencia
+de `--force-mcp-opencode` se sostiene igual por el otro motivo, que sigue en pie: sin marcadores no
+hay forma de distinguir nuestra entrada de una escrita a mano. Lo que queda desactualizado es la
+**justificación escrita**, atada a una versión concreta del cliente. Corregir esas tres frases es un
+cambio de documentación independiente, no un defecto de este change.
+
+### Deriva respecto a la spec, ya conocida y deliberada
+
+- **`enabled`** (REQ-007/008): la spec lo pedía; se quitó al medir que la CLI del cliente tampoco lo
+  escribe. Reconfirmado hoy: las dos formas coinciden.
+- **«diecisiete»** (REQ-029/032): hoy el `doctor` tiene **dieciocho** checks porque después de este
+  change entró uno más. El requisito de fondo —que las frases de tamaño digan el número de verdad—
+  lo guarda `test_el_docstring_dice_cuantos_checks_hay_de_verdad`, que está en verde.
````

### Mensaje A

```
feat(opencode-tercer-cliente): cerrar change con revalidación completa

- Revalidar suite (794 passed) y e2e (26/26) contra árbol y binario 1.18.29
- Aprobar gates quality, conformance y memory con evidencia fresca
- Documentar que la justificación de REQ-011 caducó con la nueva versión
- Anotar desviaciones no propias: doc desactualizada y comportamiento de update
```

### Mensaje B

```
docs(opencode-tercer-cliente): cerrar el change y actualizar estado de gates

- Cambia el estado de `verifying` a `closed` en el SDD.
- Actualiza la evidencia de los gates `quality`, `conformance` y `memory` con la revalidación del 2026-09-08.
- Añade sección de revalidación en `verification.md` con resultados de la suite, escenarios e2e y pruebas contra el binario opencode 1.18.29 en Windows.
- Documenta el hallazgo sobre la caducidad de la justificación del REQ-011 debido a cambios en la validación del cliente.
- Registra las derivas deliberadas respecto a la spec (REQ-007/008 y REQ-029/032).
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 08

Diff: 9 ficheros, +188 −10

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 33b6a99..b37dbc9 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,20 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+### Fixed
+- **`update` no reponía los hooks de una versión anterior.** El chequeo `scaffold.hook_files` solo
+  miraba que los scripts existieran con su nombre, así que unos hooks viejos daban `[ OK ]`, y la
+  reparación solo actuaba si faltaba la carpeta entera. Actualizar el paquete no toca
+  `~/.claude/hooks/`, de modo que `uv tool install … && local-delegate update` dejaba corriendo los
+  hooks del último `install`: la Mac pasó una semana en la 0.31.1 con los hooks de la 0.27, sin la
+  telemetría de F1 ni el bloqueo. Ahora el chequeo compara cada script con el del paquete, byte a
+  byte, y avisa también si falta uno que no se registra (`hook_common.py`); `update` los repone en
+  los dos casos.
+- **Al reponer los hooks, `update` quitaba el de lectura.** Reescribía su registro en
+  `settings.json` sin la bandera del hook de lectura, y `merge_hook_settings` retira antes todas
+  nuestras entradas. Hasta ahora solo pasaba si faltaba la carpeta de hooks; con el arreglo anterior
+  habría pasado en cada actualización. Ahora `update` deja el de lectura como estaba.
+
 ## [0.31.1] - 2026-09-22
 
 ### Security
diff --git a/docs/wiki/Integration-install.md b/docs/wiki/Integration-install.md
index 1969c1e..cf8093c 100644
--- a/docs/wiki/Integration-install.md
+++ b/docs/wiki/Integration-install.md
@@ -200,7 +200,7 @@ local-delegate doctor --home /tmp/x  # diagnostica contra un HOME simulado (solo
 | Entorno | clientes MCP observados | con qué clientes se ha **hablado** de verdad: versión, revisión de protocolo negociada y si declaran `elicitation` (o sea, si las tools pueden preguntarles en vez de fallar). Sale de `clients.jsonl`, en `LOG_DIR`, y es **informativo**: nunca sube el exit code |
 | Entorno | rol rápido retirado | si `LOCAL_DELEGATE_MODEL_FAST`, `LOCAL_DELEGATE_MAX_CHARS_FAST` o `LOCAL_DELEGATE_FALLBACK_FAST` siguen en el entorno. El rol `fast` se retiró en la 0.30.0 —no lo enrutaba ninguna tool— y esas variables ya no tienen efecto: sin este aviso, quien las tuviera puestas seguiría creyendo que configuran algo |
 | Entorno | cadenas de respaldo | que cada `LOCAL_DELEGATE_FALLBACK_<ROL>` nombre solo roles o modelos del catálogo de texto —lo que no, se ignora al delegar y un rol se queda sin el respaldo que creías— y de qué modelo sale el residente: del grupo `persistent` de llama-swap o, si no se puede leer, del rol mecánico |
-| Andamiaje | hooks copiados | los scripts en `~/.claude/hooks/local-delegate/` |
+| Andamiaje | hooks copiados | los scripts en `~/.claude/hooks/local-delegate/`, y que sean **los del paquete instalado**, byte a byte. Actualizar el paquete no toca esa carpeta: con scripts de otra versión da `warn` y `update` los repone. Antes solo miraba los nombres, y unos hooks viejos pasaban por buenos |
 | Andamiaje | hooks huérfanos | scripts nuestros sueltos en `~/.claude/hooks/` que dejó una instalación anterior; `install` los retira |
 | Andamiaje | hooks registrados | entradas **nuestras** en `~/.claude/settings.json` (las ajenas no se cuentan) |
 | Andamiaje | skill delegacion-local | la skill **en cada cliente al que se le escribe**: `~/.claude/skills/delegacion-local/SKILL.md` y `~/.config/opencode/skill/delegacion-local/`. Mirar solo la de Claude Code daba un `[ OK ]` con la de opencode borrada |
diff --git a/docs/wiki/Remote-backend.md b/docs/wiki/Remote-backend.md
index 07693c7..af6b9a1 100644
--- a/docs/wiki/Remote-backend.md
+++ b/docs/wiki/Remote-backend.md
@@ -77,7 +77,12 @@ local-delegate update             # aplica y deja el daemon arriba
 
 Revisa el estado real de la máquina con las mismas comprobaciones que `doctor`, actualiza el pin
 donde exista, completa la configuración que falte y termina dejando el daemon arriba: lo reinicia si
-corría, lo levanta si no. Es idempotente. El backend de inferencia **no se toca** salvo que lo pidas
+corría, lo levanta si no. Es idempotente.
+
+Eso incluye **los hooks de Claude Code**: si los de `~/.claude/hooks/local-delegate/` no son los del
+paquete instalado, los repone, y deja el hook de lectura como estaba —registrado si lo estaba, fuera
+si no—. Hasta la 0.31.1 no lo hacía: miraba solo que los ficheros existieran, así que tras actualizar
+el paquete seguían corriendo los hooks de la versión con la que se hizo el último `install`. El backend de inferencia **no se toca** salvo que lo pidas
 con `--restart-backend`, porque reiniciar llama-swap descargaría los modelos de la VRAM.
 
 **Lo que `update` NO hace: actualizar el propio CLI si lo instalaste con `uv tool`.** Te lo dice al
diff --git a/src/local_delegate/checks.py b/src/local_delegate/checks.py
index b5d6ca4..766d0ee 100644
--- a/src/local_delegate/checks.py
+++ b/src/local_delegate/checks.py
@@ -53,6 +53,7 @@ STATUS_LABEL: dict[str, str] = {
 }
 
 INSTALL_HINT = "local-delegate install"
+UPDATE_HOOKS_HINT = "local-delegate update  (repone los hooks sin tocar el resto)"
 SERVE_HINT = "local-delegate serve  (o arranca la tarea programada del daemon)"
 CLI_HINT = "uv tool install local-delegate-mcp  (deja `local-delegate` en el PATH)"
 RESTART_HINT = "reinicia el daemon para que sirva la versión instalada"
@@ -408,6 +409,31 @@ def _dir_entries(path: Path) -> tuple[list[str] | None, str | None]:
         return None, f"no se pudo listar {path}: {exc.strerror or exc}"
 
 
+def _packaged_hooks() -> dict[str, Path]:
+    """Los ``.py`` de hooks que trae el paquete instalado, por nombre. Vacío si no se pueden leer.
+
+    Vacío degrada a mirar solo los nombres de ``_HOOK_EVENTS``, como antes: sin la referencia no
+    hay con qué comparar, y un ``warn`` inventado haría que ``update`` reescribiera los hooks en
+    cada pasada.
+    """
+    try:
+        return {
+            p.name: p for p in (install.resources_dir() / "hooks").iterdir() if p.suffix == ".py"
+        }
+    except OSError:
+        return {}
+
+
+def _differs(instalado: Path, empaquetado: Path | None) -> bool:
+    """True si el script instalado no es byte a byte el del paquete. Sin referencia, no se afirma."""
+    if empaquetado is None:
+        return False
+    try:
+        return instalado.read_bytes() != empaquetado.read_bytes()
+    except OSError:
+        return False
+
+
 def _has_block(text: str, begin: str, end: str) -> bool:
     """True si el bloque gestionado está delimitado y en orden."""
     start = text.find(begin)
@@ -627,10 +653,22 @@ def _probe_hook_files(ctx: Context) -> Result:
         return Result(UNKNOWN, reason)
     if entries is None:
         return Result(MISSING, f"no existe {ctx.hooks_dir}", INSTALL_HINT)
-    expected = [script for script, _event, _matcher in install._HOOK_EVENTS]
+    empaquetados = _packaged_hooks()
+    expected = sorted(empaquetados) or [script for script, _event, _matcher in install._HOOK_EVENTS]
     faltan = [name for name in expected if name not in entries]
     if faltan:
         return Result(WARN, f"faltan scripts en {ctx.hooks_dir}: {', '.join(faltan)}", INSTALL_HINT)
+    # Que estén no basta: hay que mirar que sean LOS DE ESTA VERSIÓN. Actualizar el paquete no
+    # toca `~/.claude/hooks/`, y mirando solo los nombres unos hooks de la 0.27 pasaban por buenos
+    # con la 0.31.1 instalada —así estuvo la Mac del 2026-09-15 al 2026-09-22, sin el bloqueo ni
+    # la telemetría de F1, y `update` respondiendo que no había nada que reparar—.
+    viejos = [name for name in expected if _differs(ctx.hooks_dir / name, empaquetados.get(name))]
+    if viejos:
+        return Result(
+            WARN,
+            f"scripts de otra versión en {ctx.hooks_dir}: {', '.join(viejos)}",
+            UPDATE_HOOKS_HINT,
+        )
     # Se cuentan los `.py`, no las entradas del directorio: en cuanto los hooks se ejecutan una vez,
     # Python deja ahí un `__pycache__/` y el conteo decía «4 script(s)» donde hay 3. No es cosmético
     # —es JUSTO el número que se mira para confirmar que un script retirado desapareció—, y con un
diff --git a/src/local_delegate/install.py b/src/local_delegate/install.py
index dde6faf..e7266ac 100644
--- a/src/local_delegate/install.py
+++ b/src/local_delegate/install.py
@@ -327,6 +327,31 @@ def _is_ours(hook: dict, hooks_dir: Path) -> bool:
     return any(name in normalized for name in _SCRIPT_NAMES + _SCRIPTS_RETIRADOS)
 
 
+def read_hook_registered(claude_dir: Path) -> bool:
+    """True si el ``settings.json`` de Claude Code registra ya nuestro hook de lectura.
+
+    Lo necesita ``update``: al reponer los hooks reescribe el registro con ``merge_hook_settings``,
+    que **retira** todas nuestras entradas previas antes de poner las nuevas. Si no sabe que el de
+    lectura estaba puesto, lo quita, y el bloqueo se apaga en silencio justo al actualizar.
+    Se mira el nombre del script y no ``READ_HOOK_FLAG``: una entrada vieja sin la bandera también
+    es una decisión del usuario de tenerlo, y respetarla es no quitarlo.
+    """
+    hooks = _read_json(claude_dir / "settings.json").get("hooks")
+    if not isinstance(hooks, dict):
+        return False
+    hooks_dir = claude_dir / "hooks" / HOOKS_SUBDIR
+    for groups in hooks.values():
+        for group in groups if isinstance(groups, list) else []:
+            for hook in group.get("hooks", []) if isinstance(group, dict) else []:
+                if not isinstance(hook, dict) or not _is_ours(hook, hooks_dir):
+                    continue
+                args = hook.get("args")
+                texto = " ".join([str(hook.get("command", ""))] + [str(a) for a in args or []])
+                if _READ_HOOK[0] in texto:
+                    return True
+    return False
+
+
 def merge_hook_settings(
     settings: dict, entries: list[tuple[str, str | None, str]], hooks_dir: Path
 ) -> tuple[dict, int]:
diff --git a/src/local_delegate/update.py b/src/local_delegate/update.py
index 2872cfe..56e4255 100644
--- a/src/local_delegate/update.py
+++ b/src/local_delegate/update.py
@@ -153,7 +153,16 @@ class Repair:
 # `scaffold.mcp_codex`: no se pisa configuración escrita por una persona. El aviso dice qué pasa y
 # qué comando lo arregla; ejecutarlo es del usuario.
 REPAIRS: tuple[Repair, ...] = (
-    Repair("scaffold.hook_files", (checks.MISSING,), frozenset({"hooks"}), frozenset({"claude"})),
+    Repair(
+        "scaffold.hook_files",
+        # `warn` aquí significa «faltan scripts» o «son de otra versión»: los dos son nuestros y
+        # están viejos. Sin repararlo en `warn`, actualizar el paquete dejaba los hooks de la
+        # versión anterior para siempre, porque nada más en `update` los reescribe.
+        (checks.MISSING, checks.WARN),
+        frozenset({"hooks"}),
+        frozenset({"claude"}),
+        why="scripts de hooks de otra versión",
+    ),
     Repair(
         "scaffold.hook_settings",
         # `warn` aquí significa «hooks de una instalación anterior»: son nuestros y están
@@ -263,6 +272,10 @@ def plan_repairs(
                         targets={target},
                         python_exe=install.default_python(),
                         mcp_mode=mcp_mode,
+                        # Reponer los hooks reescribe su registro, y `merge_hook_settings` retira
+                        # antes todas nuestras entradas: sin esto, el hook de lectura desaparecía
+                        # al actualizar y el bloqueo se apagaba sin que nadie lo pidiera.
+                        enable_read_hook=install.read_hook_registered(opts.home / ".claude"),
                         # Con un HOME simulado hay que escribir el fichero a mano: el camino
                         # por CLI (`claude mcp add-json --scope user`) escribe SIEMPRE en el
                         # `~/.claude.json` del usuario real, ignorando `home`. Se descubrió
diff --git a/tests/conftest.py b/tests/conftest.py
index 0e7660b..6791c4a 100644
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -87,8 +87,10 @@ def make_home(tmp_path: Path, *, claude=True, codex=True, opencode=True, complet
         if complete:
             hooks_dir = claude_dir / "hooks" / install.HOOKS_SUBDIR
             hooks_dir.mkdir(parents=True)
-            for script, _event, _matcher in install._HOOK_EVENTS:
-                (hooks_dir / script).write_text("# hook\n", encoding="utf-8")
+            # Los scripts de verdad, byte a byte: `scaffold.hook_files` compara contra los del
+            # paquete, y un «# hook» de relleno contaría como hooks de otra versión.
+            for script in (install.resources_dir() / "hooks").glob("*.py"):
+                (hooks_dir / script.name).write_bytes(script.read_bytes())
             entries = [
                 (event, matcher, install.hook_command(hooks_dir, script, "python"))
                 for script, event, matcher in install._HOOK_EVENTS
diff --git a/tests/test_checks.py b/tests/test_checks.py
index 319fb6b..d4899cc 100644
--- a/tests/test_checks.py
+++ b/tests/test_checks.py
@@ -1347,16 +1347,43 @@ def test_el_conteo_de_hooks_no_cuenta_el_pycache(tmp_path):
 def test_el_conteo_de_hooks_sigue_los_scripts_de_verdad(tmp_path):
     """Control del test de arriba: sin esto, un conteo clavado a mano lo dejaría en verde.
 
-    Se añade un `.py` en vez de borrar uno porque el HOME de pruebas tiene **un solo** script (el
-    de `_HOOK_EVENTS`), y quitarlo dispararía el `warn` de «faltan scripts», que es otro camino y
-    no diría nada del conteo.
+    Se añade un `.py` en vez de borrar uno porque quitarlo dispararía el `warn` de «faltan
+    scripts», que es otro camino y no diría nada del conteo. Y se añade uno que **no** es del
+    paquete: reescribir uno de los nuestros ahora es «script de otra versión», también otro camino.
     """
     home = make_home(tmp_path)
     hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
     antes = len([p for p in hooks_dir.iterdir() if p.suffix == ".py"])
 
-    (hooks_dir / "hook_common.py").write_text("# ayudante", encoding="utf-8")
+    (hooks_dir / "mi_hook_propio.py").write_text("# del usuario", encoding="utf-8")
 
     result = result_for("scaffold.hook_files", make_ctx(home))
     assert result.status == checks.OK
     assert f"{antes + 1} script(s)" in result.detail, result.detail
+
+
+def test_hooks_de_otra_version_son_warn(tmp_path):
+    """Los nombres están todos, pero el contenido no es el del paquete instalado.
+
+    Es lo que tuvo la Mac una semana: paquete en 0.31.1 y hooks de la 0.27, y el check en `ok`
+    porque solo miraba nombres. `update` no los reponía y la telemetría de F1 nunca llegó a correr.
+    """
+    home = make_home(tmp_path)
+    script = install._READ_HOOK[0]
+    (home / ".claude" / "hooks" / install.HOOKS_SUBDIR / script).write_text(
+        "# versión anterior\n", encoding="utf-8"
+    )
+    result = result_for("scaffold.hook_files", make_ctx(home))
+    assert result.status == checks.WARN
+    assert "otra versión" in result.detail
+    assert script in result.detail
+    assert result.fix_hint == checks.UPDATE_HOOKS_HINT
+
+
+def test_falta_un_script_empaquetado_aunque_no_se_registre(tmp_path):
+    """`hook_common.py` no está en `_HOOK_EVENTS`, pero sin él ningún hook arranca."""
+    home = make_home(tmp_path)
+    (home / ".claude" / "hooks" / install.HOOKS_SUBDIR / "hook_common.py").unlink()
+    result = result_for("scaffold.hook_files", make_ctx(home))
+    assert result.status == checks.WARN
+    assert "hook_common.py" in result.detail
diff --git a/tests/test_update.py b/tests/test_update.py
index 2a794f5..fec28a1 100644
--- a/tests/test_update.py
+++ b/tests/test_update.py
@@ -749,3 +749,57 @@ def test_los_nombres_del_servicio_coinciden_con_la_wiki():
     texto = wiki.read_text(encoding="utf-8")
     for nombre in (update.TASK_NAME, update.LAUNCH_LABEL, update.SYSTEMD_UNIT):
         assert nombre in texto, f"{nombre} no aparece en docs/wiki/Daemon.md"
+
+
+# --- Hooks de otra versión: el caso de la Mac ---------------------------------
+
+
+def test_hooks_de_otra_version_se_reponen_sin_apagar_el_de_lectura(tmp_path):
+    """Paquete nuevo, hooks viejos y el de lectura encendido: `update` los repone y lo respeta.
+
+    Tres cosas, y cada una falló o habría fallado: el check daba `ok` con hooks de otra versión,
+    la reparación solo actuaba si faltaba el directorio entero, y al reponer los hooks se
+    reescribía su registro sin el de lectura —con el arreglo de los dos primeros, eso habría
+    apagado el bloqueo en cada actualización—.
+    """
+    home = make_home(tmp_path, complete=False)
+    install.apply(
+        install.plan_install(
+            install.Options(
+                home=home,
+                components={"hooks"},
+                targets={"claude"},
+                python_exe="python",
+                enable_read_hook=True,
+            )
+        ),
+        dry_run=False,
+        out=lambda *a: None,
+    )
+    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
+    viejo = hooks_dir / install._READ_HOOK[0]
+    viejo.write_text("# versión anterior\n", encoding="utf-8")
+    assert install.read_hook_registered(home / ".claude")
+
+    actions, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
+    assert any(a.kind == "copy" and a.target == hooks_dir for a in actions), actions
+    install.apply(actions, dry_run=False, out=lambda *a: None)
+
+    empaquetado = install.resources_dir() / "hooks" / install._READ_HOOK[0]
+    assert viejo.read_bytes() == empaquetado.read_bytes()
+    assert install.read_hook_registered(home / ".claude"), "update apagó el hook de lectura"
+    segunda, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
+    assert [a for a in segunda if "hooks" in str(a.target)] == []
+
+
+def test_sin_hook_de_lectura_registrado_update_no_lo_enciende(tmp_path):
+    """El otro lado: respetar la elección es también no activarlo si no estaba."""
+    home = make_home(tmp_path)
+    assert not install.read_hook_registered(home / ".claude")
+    hooks_dir = home / ".claude" / "hooks" / install.HOOKS_SUBDIR
+    (hooks_dir / install._HOOK_EVENTS[0][0]).write_text("# versión anterior\n", encoding="utf-8")
+
+    actions, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts_for(home))
+    assert actions
+    install.apply(actions, dry_run=False, out=lambda *a: None)
+    assert not install.read_hook_registered(home / ".claude")
```

### Mensaje A

```
fix(hooks): validar integridad byte a byte y respetar hook de lectura

- Comparar scripts instalados con los del paquete para detectar versiones
  antiguas que pasaban por válidas al solo verificar nombres.
- Reponer hooks obsoletos durante `update` para asegurar funcionalidad
  completa (telemetría, bloqueo, etc.).
- Preservar el estado del hook de lectura al reescribir `settings.json`,
  evitando que `update` desactive silenciosamente el bloqueo.
- Actualizar documentación y tests para reflejar la nueva validación.
```

### Mensaje B

```
fix(hooks): mejorar la detección y reposición de hooks en `update`

- Detecta hooks de versiones anteriores comparando el contenido byte a byte.
- Repone los hooks cuando el contenido difiere, incluso si los nombres coinciden.
- Preserva el estado del hook de lectura en `settings.json` al actualizar.
- Incluye la comprobación de scripts necesarios que no están en la lista de eventos.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 09

Diff: 2 ficheros, +75 −25

```diff
diff --git a/.sdd/changes/cierre-total-backlog/handoff.md b/.sdd/changes/cierre-total-backlog/handoff.md
index 19ff56c..5f640a2 100644
--- a/.sdd/changes/cierre-total-backlog/handoff.md
+++ b/.sdd/changes/cierre-total-backlog/handoff.md
@@ -1,25 +1,38 @@
-# Handoff: Cierre total del backlog: los puntos vivos, la auditoria del proyecto y la release
+# Traspaso — cierre total del backlog
 
-## Current state
+## Qué quedó hecho
 
-- SDD status:
-- Last completed gate:
-- Current revision:
+**0.21.0 publicada** (PyPI + registro MCP `isLatest: true`) y el **backlog sin ningún punto
+abierto**. Cinco PRs: #116, #117, #118, #119, #120.
 
-## What changed
+Del backlog: `CTRL_BREAK` arreglado con su diagnóstico, panel probado interactuado, `clients.jsonl`
+con techo, instalador ejercido en los tres sistemas, brazo B desbloqueado y encendido. El chunking,
+Codex-con-token, la UI de `elicitation` y las ideas de la sección 4 quedan como **decisiones
+escritas**, no como pendientes.
 
-- Summarize completed work without reproducing the full Git history.
+Nuevos, encontrados en la auditoría: `--version` inexistente, `--enable-read-hook` como no-op
+silencioso, Playwright sin declarar, el mensaje del lock que engañaba, y un **ciclo de importación
+real** con seis alertas de CodeQL.
 
-## Decisions
+## Estado de la máquina
 
-- Record decisions that a future session cannot reliably derive from code alone.
+- CLI y daemon en **0.21.0 desde el paquete publicado** (`uv tool`), no del venv del repo.
+- Entradas MCP en **`http`** contra el daemon del 9393.
+- **Brazo B encendido**: el hook de Read registrado con `--enabled`, verificado ejecutándolo tal
+  cual quedó en el `settings.json` real, con el entorno limpio.
 
-## Next action
+## Lo que la próxima sesión debe saber
 
-- State the single best next step and any prerequisite context.
+1. **`install` sin `--mcp-mode http` vuelve al default `stdio`**, que en esta máquina deja las
+   tools en 401. Se pisó en esta sesión y se corrigió en el acto. Pasarlo **siempre**.
+2. **El brazo B necesita días de datos.** Al medirlo, no usar la tasa global: el 17 % del brazo A
+   salía entero de dos categorías.
+3. **Propuesta abierta, no deuda**: el proyecto no tiene comprobador de tipos. Decidir si entra.
+4. `uv tool upgrade` puede no actualizar por caché del índice → `uv tool install --force --refresh`.
+5. Tras rebasar el CHANGELOG, comprobar que `git diff origin/main` da **cero líneas borradas**: un
+   fusionador ingenuo con CRLF borró 1011 líneas en esta sesión.
 
-## Memory
-
-- Canonical note:
-- Indexes updated:
+## Sin secretos
 
+Ningún artefacto de este cambio contiene credenciales, tokens ni datos personales. El diagnóstico
+imprime **nombres** de variables, nunca valores.
diff --git a/.sdd/changes/cierre-total-backlog/state.json b/.sdd/changes/cierre-total-backlog/state.json
index b05f1c0..03a9b99 100644
--- a/.sdd/changes/cierre-total-backlog/state.json
+++ b/.sdd/changes/cierre-total-backlog/state.json
@@ -3,9 +3,9 @@
   "slug": "cierre-total-backlog",
   "title": "Cierre total del backlog: los puntos vivos, la auditoria del proyecto y la release",
   "mode": "standard",
-  "status": "verifying",
+  "status": "closed",
   "createdAt": "2026-08-01T16:28:47.746Z",
-  "updatedAt": "2026-08-01T19:05:48.828Z",
+  "updatedAt": "2026-08-01T19:22:09.115Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -26,16 +26,16 @@
       "actor": "user"
     },
     "conformance": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-01T19:18:27.938Z",
+      "evidence": "Los 10 requisitos con evidencia en verification.md. 0.21.0 publicada en PyPI y en el registro MCP (isLatest: true); CLI y daemon de la maquina en 0.21.0 DESDE EL PAQUETE PUBLICADO; verificado con local_status y local_summarize contra el backend real, no solo con doctor. Brazo B encendido y comprobado ejecutando el hook tal cual quedo registrado en el settings.json real, con el entorno limpio.",
+      "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-01T19:22:07.694Z",
+      "evidence": "Backlog del vault reescrito sin puntos abiertos; jornada-2026-08-01-el-backlog-sin-nada-abierto.md creada; memorias de Claude Code actualizadas (estado 0.21.0, backlog, MEMORY.md) y una regla nueva: control-positivo-no-es-opcional. Sin secretos ni datos personales.",
+      "actor": "user"
     }
   },
   "history": [
@@ -111,6 +111,43 @@
       "to": "verifying",
       "at": "2026-08-01T19:05:48.828Z",
       "reason": "Los cuatro PRs mezclados (#116, #117, #118, #119); se prepara la 0.21.0"
+    },
+    {
+      "type": "gate",
+      "gate": "conformance",
+      "status": "approved",
+      "at": "2026-08-01T19:18:27.938Z",
+      "evidence": "Los 10 requisitos con evidencia en verification.md. 0.21.0 publicada en PyPI y en el registro MCP (isLatest: true); CLI y daemon de la maquina en 0.21.0 DESDE EL PAQUETE PUBLICADO; verificado con local_status y local_summarize contra el backend real, no solo con doctor. Brazo B encendido y comprobado ejecutando el hook tal cual quedo registrado en el settings.json real, con el entorno limpio.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-08-01T19:18:28.532Z",
+      "reason": "Release publicada y verificada en la maquina"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-08-01T19:22:07.694Z",
+      "evidence": "Backlog del vault reescrito sin puntos abiertos; jornada-2026-08-01-el-backlog-sin-nada-abierto.md creada; memorias de Claude Code actualizadas (estado 0.21.0, backlog, MEMORY.md) y una regla nueva: control-positivo-no-es-opcional. Sin secretos ni datos personales.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-08-01T19:22:08.487Z",
+      "reason": "Release publicada, maquina verificada y memoria persistida"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-08-01T19:22:09.115Z",
+      "reason": "Backlog sin ningun punto abierto"
     }
   ]
 }
```

### Mensaje A

```
feat(cierre-backlog): cerrar backlog y publicar 0.21.0

- Publicar 0.21.0 en PyPI y registro MCP
- Cerrar todos los puntos del backlog
- Verificar CLI, daemon y brazo B
- Actualizar memoria y documentación
```

### Mensaje B

```
docs(sdd): cerrar el backlog y documentar el traspaso de la v0.21.0

- Actualizar el documento de handoff con el estado final y auditoría.
- Marcar el cambio como cerrado en el archivo de estado.
- Registrar la aprobación de las puertas de conformidad y memoria.
- Documentar la publicación de la versión 0.21.0 en PyPI y MCP.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 10

Diff: 2 ficheros, +111 −20

```diff
diff --git a/.sdd/changes/panel-dice-la-verdad/handoff.md b/.sdd/changes/panel-dice-la-verdad/handoff.md
index 0913d12..04c943f 100644
--- a/.sdd/changes/panel-dice-la-verdad/handoff.md
+++ b/.sdd/changes/panel-dice-la-verdad/handoff.md
@@ -1,25 +1,45 @@
-# Handoff: El panel puede decir que no hay adopcion
+# Handoff
 
-## Current state
+## Qué se cerró
 
-- SDD status:
-- Last completed gate:
-- Current revision:
+El panel ya puede distinguir un mes de smoke tests de un mes de trabajo real: el log de uso firma
+cada delegación con el cliente MCP que la pidió, `/api/stats` lo desglosa, y la tarjeta de hooks
+muestra por qué el hook de lectura se calló en lo que se calló.
 
-## What changed
+Mergeado en **PR #149** (`1c6998c`), con el CI en verde.
 
-- Summarize completed work without reproducing the full Git history.
+## Decisiones que sobreviven a este cambio
 
-## Decisions
+- **La identidad viaja en un `ContextVar` que el middleware fija antes de `call_next`.** Ese
+  «antes» es el cambio entero: puesto después no firmaría nada. Y las tools son síncronas, así que
+  el SDK las corre en el threadpool — que el `ContextVar` cruce ese salto se midió antes de
+  diseñarlo.
+- **Las líneas sin cliente caen en «desconocido», casilla propia.** Repartirlas entre los clientes
+  conocidos inventaría de quién eran; descartarlas descuadraría la tarjeta con el KPI de arriba.
+  Un test comprueba que la suma por cliente es el total.
+- **Sigue sin haber ninguna tasa de conversión.** Nada enlaza una sugerencia con la delegación que
+  vino después. La tarjeta muestra la **selectividad** del hook —de lo que vio, en qué avisó— que
+  vive entera dentro de la telemetría y no necesita cruzarse con nada.
+- **El desglose por motivo se acota a `category == "read"`.** `motivo` sólo lo escribe ese hook;
+  recorrer todos los eventos metería `lint` y `summarize` en «sin registrar» y la tarjeta diría
+  que el hook descarta sin motivo la mitad de las veces. Un número que se lee bien y significa otra
+  cosa.
 
-- Record decisions that a future session cannot reliably derive from code alone.
+## Lo que se corrigió al medir
 
-## Next action
+El SDK **del cliente** rellena `mcp` cuando no se le da `client_info`, así que «sin identidad»
+casi no existe visto desde el servidor. El test lo dice ahora tal cual; el camino de omitir el
+campo sigue vivo para cuando `client_info` llegue en `None` de verdad.
 
-- State the single best next step and any prerequisite context.
+## Qué queda abierto
 
-## Memory
+- **La captura del README no se regeneró aquí.** Los mocks ya traen `by_client`, `by_motivo`,
+  `by_ext` y `read_total` con los números cuadrando, pero la imagen se regenera en la release,
+  que es donde el manifiesto la ata a la versión.
+- El desglose por cliente sólo tendrá datos hacia adelante: las delegaciones de antes de este
+  cambio salen como desconocidas para siempre, que es lo correcto y también un límite.
 
-- Canonical note:
-- Indexes updated:
+## Estado del entorno
 
+`local-delegate doctor`: todo a punto. Esta máquina sigue con la 0.24.0 instalada desde el repo;
+se normaliza en la próxima release.
diff --git a/.sdd/changes/panel-dice-la-verdad/state.json b/.sdd/changes/panel-dice-la-verdad/state.json
index cd0d68e..bff1ff0 100644
--- a/.sdd/changes/panel-dice-la-verdad/state.json
+++ b/.sdd/changes/panel-dice-la-verdad/state.json
@@ -3,9 +3,9 @@
   "slug": "panel-dice-la-verdad",
   "title": "El panel puede decir que no hay adopcion",
   "mode": "standard",
-  "status": "understanding",
+  "status": "closed",
   "createdAt": "2026-08-18T13:15:47.918Z",
-  "updatedAt": "2026-08-18T13:33:32.197Z",
+  "updatedAt": "2026-08-18T13:38:27.825Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-18T13:38:26.461Z",
+      "evidence": "handoff.md con las decisiones durables, lo corregido al medir y lo que queda abierto. Sin secretos ni datos personales: el campo nuevo es solo el nombre del cliente MCP, y la telemetria sigue sin guardar rutas.",
+      "actor": "user"
     }
   },
   "history": [
@@ -77,6 +77,77 @@
       "at": "2026-08-18T13:33:32.197Z",
       "evidence": "verification.md mapea los 7 REQ. End-to-end con el daemon real en el 9494: dos clientes MCP dejan dos firmas distintas en el log en disco, /api/stats las separa y el panel pinta las dos tarjetas en el navegador. Un requisito se corrigio con lo medido: el SDK del cliente rellena 'mcp' por defecto.",
       "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-08-18T13:38:26.461Z",
+      "evidence": "handoff.md con las decisiones durables, lo corregido al medir y lo que queda abierto. Sin secretos ni datos personales: el campo nuevo es solo el nombre del cliente MCP, y la telemetria sigue sin guardar rutas.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "understanding",
+      "to": "researching",
+      "at": "2026-08-18T13:38:26.612Z",
+      "reason": "telemetria, transcripts y codigo del panel"
+    },
+    {
+      "type": "transition",
+      "from": "researching",
+      "to": "specifying",
+      "at": "2026-08-18T13:38:26.768Z",
+      "reason": "spec.md con 7 requisitos"
+    },
+    {
+      "type": "transition",
+      "from": "specifying",
+      "to": "planning",
+      "at": "2026-08-18T13:38:26.936Z",
+      "reason": "plan.md con 6 tareas"
+    },
+    {
+      "type": "transition",
+      "from": "planning",
+      "to": "plan-review",
+      "at": "2026-08-18T13:38:27.081Z",
+      "reason": "review.md adversarial, 5 hallazgos sin bloqueantes"
+    },
+    {
+      "type": "transition",
+      "from": "plan-review",
+      "to": "implementing",
+      "at": "2026-08-18T13:38:27.232Z",
+      "reason": "clients, server, metrics, HTML y mocks de la captura"
+    },
+    {
+      "type": "transition",
+      "from": "implementing",
+      "to": "verifying",
+      "at": "2026-08-18T13:38:27.378Z",
+      "reason": "762 tests, mutante y end-to-end con el daemon real"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-08-18T13:38:27.529Z",
+      "reason": "verification.md mapea los 7 REQ"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-08-18T13:38:27.676Z",
+      "reason": "PR #149 mergeado"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-08-18T13:38:27.825Z",
+      "reason": "panel verificado en el navegador"
     }
   ]
 }
```

### Mensaje A

```
feat(panel): cierra panel-dice-la-verdad con handoff y telemetría
```

### Mensaje B

```
docs(panel-dice-la-verdad): cerrar el cambio y documentar handoff

- Actualizar el estado de la tarea a 'closed'.
- Refactorizar el archivo handoff.md con las decisiones finales y aprendizajes.
- Registrar el historial de transiciones y la aprobación de la memoria en state.json.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 11

Diff: 6 ficheros, +13 −8

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 8e24c98..96fb403 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.22.0] - 2026-08-02
+
 ### Added
 - **opencode como tercer cliente de `install`, `doctor` y `update`.** Hasta ahora el instalador
   conocía dos clientes y la lista estaba repartida en cinco sitios. Quien tuviera **opencode** no
@@ -1469,7 +1471,10 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 - Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
   registro oficial de MCP.
 
-[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.19.0...HEAD
+[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.0...HEAD
+[0.22.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.21.0...v0.22.0
+[0.21.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.20.0...v0.21.0
+[0.20.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.19.0...v0.20.0
 [0.19.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.18.1...v0.19.0
 [0.18.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.18.0...v0.18.1
 [0.18.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.17.0...v0.18.0
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index 0c91030..1502e50 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.21.0",
-  "sha256": "3cc8e03ef752743822e3243b2c633b61e02f054b303edb078c6ac668357df681",
-  "bytes": 660615
+  "version": "0.22.0",
+  "sha256": "24d7eaab509bfd835e37ff493c72c9a758dbb7a723e000077ecfec738cc71f2b",
+  "bytes": 661142
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index f25a3c4..007c323 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index 5dc8960..043d594 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.21.0"
+version = "0.22.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/server.json b/server.json
index c9ff66b..58c326d 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.21.0",
+  "version": "0.22.0",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.21.0",
+      "version": "0.22.0",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/uv.lock b/uv.lock
index a5809e4..f5c73c8 100644
--- a/uv.lock
+++ b/uv.lock
@@ -437,7 +437,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.21.0"
+version = "0.22.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
chore(release): versión 0.22.0

- Actualizar la versión en pyproject.toml, server.json y uv.lock
- Registrar la nueva versión en CHANGELOG.md
- Actualizar metadatos de dashboard.json y el asset dashboard.png
```

### Mensaje B

```
feat: lanzar versión 0.22.0 con soporte para opencode
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 12

Diff: 8 ficheros, +194 −52

```diff
diff --git a/.sdd/changes/auth-puerto-daemon/state.json b/.sdd/changes/auth-puerto-daemon/state.json
index 424008f..f2614d3 100644
--- a/.sdd/changes/auth-puerto-daemon/state.json
+++ b/.sdd/changes/auth-puerto-daemon/state.json
@@ -3,9 +3,9 @@
   "slug": "auth-puerto-daemon",
   "title": "El puerto del daemon exige token cuando se configura uno",
   "mode": "standard",
-  "status": "closing",
+  "status": "closed",
   "createdAt": "2026-07-31T21:02:45.922Z",
-  "updatedAt": "2026-07-31T21:29:27.659Z",
+  "updatedAt": "2026-07-31T23:06:55.393Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:06:55.265Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
     }
   },
   "history": [
@@ -133,6 +133,21 @@
       "to": "closing",
       "at": "2026-07-31T21:29:27.659Z",
       "reason": "CI verde, hilo resuelto, PR mergeado"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-07-31T23:06:55.265Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-07-31T23:06:55.393Z",
+      "reason": "0.20.0 publicada en PyPI y en el registro MCP; verificado con una tool real"
     }
   ]
 }
diff --git a/.sdd/changes/cancelled-ci-main/state.json b/.sdd/changes/cancelled-ci-main/state.json
index 6c60f12..632735c 100644
--- a/.sdd/changes/cancelled-ci-main/state.json
+++ b/.sdd/changes/cancelled-ci-main/state.json
@@ -3,9 +3,9 @@
   "slug": "cancelled-ci-main",
   "title": "El cancelled del CI en main tiene causa conocida y firma reconocible",
   "mode": "standard",
-  "status": "closing",
+  "status": "closed",
   "createdAt": "2026-07-31T21:41:26.677Z",
-  "updatedAt": "2026-07-31T21:59:32.101Z",
+  "updatedAt": "2026-07-31T23:06:56.015Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:06:55.824Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
     }
   },
   "history": [
@@ -133,6 +133,21 @@
       "to": "closing",
       "at": "2026-07-31T21:59:32.101Z",
       "reason": "CI verde y PR mergeado"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-07-31T23:06:55.824Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-07-31T23:06:56.015Z",
+      "reason": "0.20.0 publicada en PyPI y en el registro MCP; verificado con una tool real"
     }
   ]
 }
diff --git a/.sdd/changes/ctrl-c-limpio/state.json b/.sdd/changes/ctrl-c-limpio/state.json
index 780a047..92bcf34 100644
--- a/.sdd/changes/ctrl-c-limpio/state.json
+++ b/.sdd/changes/ctrl-c-limpio/state.json
@@ -3,9 +3,9 @@
   "slug": "ctrl-c-limpio",
   "title": "Ctrl+C sobre el MCP stdio sale limpio en vez de con traceback",
   "mode": "standard",
-  "status": "closing",
+  "status": "closed",
   "createdAt": "2026-07-31T22:20:08.487Z",
-  "updatedAt": "2026-07-31T22:29:04.806Z",
+  "updatedAt": "2026-07-31T23:06:56.738Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:06:56.588Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
     }
   },
   "history": [
@@ -133,6 +133,21 @@
       "to": "closing",
       "at": "2026-07-31T22:29:04.806Z",
       "reason": "CI verde y mergeado"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-07-31T23:06:56.588Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-07-31T23:06:56.738Z",
+      "reason": "0.20.0 publicada en PyPI y en el registro MCP; verificado con una tool real"
     }
   ]
 }
diff --git a/.sdd/changes/iconos-atados-al-svg/state.json b/.sdd/changes/iconos-atados-al-svg/state.json
index d2650a3..0625d81 100644
--- a/.sdd/changes/iconos-atados-al-svg/state.json
+++ b/.sdd/changes/iconos-atados-al-svg/state.json
@@ -3,9 +3,9 @@
   "slug": "iconos-atados-al-svg",
   "title": "Los PNG de la marca quedan atados al favicon.svg",
   "mode": "standard",
-  "status": "closing",
+  "status": "closed",
   "createdAt": "2026-07-31T22:43:27.651Z",
-  "updatedAt": "2026-07-31T22:55:19.711Z",
+  "updatedAt": "2026-07-31T23:06:57.235Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:06:57.118Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
     }
   },
   "history": [
@@ -133,6 +133,21 @@
       "to": "closing",
       "at": "2026-07-31T22:55:19.711Z",
       "reason": "CI verde y mergeado"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-07-31T23:06:57.118Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-07-31T23:06:57.235Z",
+      "reason": "0.20.0 publicada en PyPI y en el registro MCP; verificado con una tool real"
     }
   ]
 }
diff --git a/.sdd/changes/js-dashboard-comportamiento/state.json b/.sdd/changes/js-dashboard-comportamiento/state.json
index 3d01fbf..16f0bb4 100644
--- a/.sdd/changes/js-dashboard-comportamiento/state.json
+++ b/.sdd/changes/js-dashboard-comportamiento/state.json
@@ -3,9 +3,9 @@
   "slug": "js-dashboard-comportamiento",
   "title": "El JS del panel se prueba ejecutandolo",
   "mode": "standard",
-  "status": "closing",
+  "status": "closed",
   "createdAt": "2026-07-31T22:34:37.136Z",
-  "updatedAt": "2026-07-31T22:41:43.998Z",
+  "updatedAt": "2026-07-31T23:06:57.018Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:06:56.863Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
     }
   },
   "history": [
@@ -133,6 +133,21 @@
       "to": "closing",
       "at": "2026-07-31T22:41:43.998Z",
       "reason": "CI verde y mergeado"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-07-31T23:06:56.863Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-07-31T23:06:57.018Z",
+      "reason": "0.20.0 publicada en PyPI y en el registro MCP; verificado con una tool real"
     }
   ]
 }
diff --git a/.sdd/changes/sync-wiki-nativa/state.json b/.sdd/changes/sync-wiki-nativa/state.json
index 5a1ade9..3680aa8 100644
--- a/.sdd/changes/sync-wiki-nativa/state.json
+++ b/.sdd/changes/sync-wiki-nativa/state.json
@@ -3,9 +3,9 @@
   "slug": "sync-wiki-nativa",
   "title": "La wiki nativa se sincroniza sola desde docs/wiki",
   "mode": "standard",
-  "status": "verifying",
+  "status": "closed",
   "createdAt": "2026-07-31T21:29:27.814Z",
-  "updatedAt": "2026-07-31T21:37:33.143Z",
+  "updatedAt": "2026-07-31T23:07:20.634Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -26,16 +26,16 @@
       "actor": "user"
     },
     "conformance": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:07:20.431Z",
+      "evidence": "PR 108 mergeado; el workflow corrio y publico (commit 5ce59fa en la wiki): 11 paginas, 18 enlaces convertidos, 0 rotos, 18 internos conservados, e identicas a lo que genera el script",
+      "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:06:55.520Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
     }
   },
   "history": [
@@ -111,6 +111,43 @@
       "at": "2026-07-31T21:37:33.143Z",
       "evidence": "620 passed 1 skipped (611 antes); ruff y format limpios; node --check OK; 5 mutantes, 5 cazados tras arreglar un test que no podia ver lo que decia comprobar",
       "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-07-31T23:06:55.520Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-07-31T23:07:08.567Z",
+      "reason": "wiki verificada contra la publicada; 0.20.0 fuera"
+    },
+    {
+      "type": "gate",
+      "gate": "conformance",
+      "status": "approved",
+      "at": "2026-07-31T23:07:20.431Z",
+      "evidence": "PR 108 mergeado; el workflow corrio y publico (commit 5ce59fa en la wiki): 11 paginas, 18 enlaces convertidos, 0 rotos, 18 internos conservados, e identicas a lo que genera el script",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-07-31T23:07:20.527Z",
+      "reason": "wiki verificada contra la publicada; 0.20.0 fuera"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-07-31T23:07:20.634Z",
+      "reason": "wiki verificada contra la publicada; 0.20.0 fuera"
     }
   ]
 }
diff --git a/.sdd/changes/telemetria-hooks-dashboard/state.json b/.sdd/changes/telemetria-hooks-dashboard/state.json
index b6c4d4c..041f2fd 100644
--- a/.sdd/changes/telemetria-hooks-dashboard/state.json
+++ b/.sdd/changes/telemetria-hooks-dashboard/state.json
@@ -3,9 +3,9 @@
   "slug": "telemetria-hooks-dashboard",
   "title": "El dashboard lee la telemetria de los hooks",
   "mode": "standard",
-  "status": "closing",
+  "status": "closed",
   "createdAt": "2026-07-31T22:00:22.634Z",
-  "updatedAt": "2026-07-31T22:18:36.031Z",
+  "updatedAt": "2026-07-31T23:06:56.436Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:06:56.132Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
     }
   },
   "history": [
@@ -133,6 +133,21 @@
       "to": "closing",
       "at": "2026-07-31T22:18:36.031Z",
       "reason": "CI verde y mergeado"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-07-31T23:06:56.132Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-07-31T23:06:56.436Z",
+      "reason": "0.20.0 publicada en PyPI y en el registro MCP; verificado con una tool real"
     }
   ]
 }
diff --git a/.sdd/changes/version-derivada/state.json b/.sdd/changes/version-derivada/state.json
index 6372a0e..5a55448 100644
--- a/.sdd/changes/version-derivada/state.json
+++ b/.sdd/changes/version-derivada/state.json
@@ -3,9 +3,9 @@
   "slug": "version-derivada",
   "title": "__version__ deja de ser un literal clavado y sale de la metadata del paquete",
   "mode": "standard",
-  "status": "closing",
+  "status": "closed",
   "createdAt": "2026-07-31T20:30:38.654Z",
-  "updatedAt": "2026-07-31T20:42:01.027Z",
+  "updatedAt": "2026-07-31T23:06:55.115Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T23:06:54.949Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
     }
   },
   "history": [
@@ -133,6 +133,21 @@
       "to": "closing",
       "at": "2026-07-31T20:42:01.027Z",
       "reason": "Sin follow-up requerido; queda la nota del vault al cierre de sesion"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-07-31T23:06:54.949Z",
+      "evidence": "Backlog del vault vaciado y jornada-2026-07-31-el-backlog-cerrado escrita; punteros de memoria de Claude Code actualizados; sin secretos ni datos personales",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-07-31T23:06:55.115Z",
+      "reason": "0.20.0 publicada en PyPI y en el registro MCP; verificado con una tool real"
     }
   ]
 }
```

### Mensaje A

```
chore(sdd): cerrar cambios pendientes y aprobar gate de memoria

- Cambia el estado de múltiples cambios de `closing` o `verifying` a `closed`.
- Aprueba el gate de `memory` en todos los archivos de estado afectados.
- Registra la evidencia de vaciado de backlog y actualización de memoria.
- Añade las transiciones finales al historial de cada cambio.
```

### Mensaje B

```
feat(wiki): la wiki nativa se sincroniza sola desde docs/wiki

- Era el último fleco manual del release.
- La wiki estaba congelada desde el 28 de julio.
- El workflow se dispara en el push a main, no en el tag.
- Arregla 18 enlaces rotos en 6 páginas de la wiki.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 13

Diff: 8 ficheros, +146 −8

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 96fb403..6f569c2 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,40 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.22.1] - 2026-08-03
+
+### Fixed
+- **La captura del README publicaba el log real de quien la regeneraba.** El script promete
+  interceptar `/api/*` con datos de ejemplo para no publicar actividad real, pero dos endpoints se
+  habían quedado fuera de la lista: `/api/stats`, de donde salen los **cuatro KPIs grandes** de la
+  cabecera, y `/api/hooks`, que pinta la tabla de sugerencias. Los dos llegaban al servidor real,
+  así que la imagen enseñaba las cuentas y la telemetría de quien capturó.
+
+  No saltó a la vista porque **dependía del entorno**: sin `LD_HOOK_TELEMETRY_LOG` definida la
+  tarjeta de hooks se esconde sola, así que para quien no tuviera esa variable el escape era
+  invisible. La imagen sí lo delataba, y llevaba varias releases haciéndolo: el pie decía
+  «390 eventos» —los de ejemplo— y el KPI de al lado «120 delegaciones», que eran de otro sitio.
+
+  Ahora los dos están mockeados, y el de `/api/stats` **se deriva de los mismos eventos de
+  ejemplo** en vez de llevar números a mano, así que la cabecera no puede volver a contradecir al
+  resto del panel. `tests/test_captura.py` gana un guardián que compara los `/api/*` que la página
+  pide con los que el script intercepta: un endpoint nuevo sin mock rompe el test en vez de
+  filtrarse callado.
+
+### Changed
+- **Dependencias al día.** Seis actualizaciones de Dependabot, sin cambios de código propio:
+  `fastapi` 0.140.7 → 0.141.1, `uvicorn` 0.51.0 → 0.52.0, `filelock` 3.32.0 → 3.32.2 y `ruff`
+  0.16.0 → 0.16.1 en el grupo de desarrollo. Las cuatro son bumps de minor o parche dentro de los
+  rangos ya declarados —`filelock` sigue bajo su techo `<4`— y ninguna requirió tocar
+  `pyproject.toml`.
+
+- **`actions/upload-pages-artifact` y `actions/deploy-pages`, de la v4 a la v5** en
+  `pages.yml`. Son bumps de **major**, así que se comprobó qué cambia antes de mezclarlos: el
+  `action.yml` de la v5 conserva las dos cosas de las que depende el workflow —el input `path` en
+  la primera y el output `page_url` en la segunda—, y el major solo mueve el runtime
+  (`deploy-pages` pasa a `node24`; `upload-pages-artifact` usa `upload-artifact` v7 por dentro).
+  Ninguna entrada del workflow cambia.
+
 ## [0.22.0] - 2026-08-02
 
 ### Added
@@ -1471,7 +1505,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 - Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
   registro oficial de MCP.
 
-[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.0...HEAD
+[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.1...HEAD
+[0.22.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.0...v0.22.1
 [0.22.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.21.0...v0.22.0
 [0.21.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.20.0...v0.21.0
 [0.20.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.19.0...v0.20.0
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index 1502e50..185607b 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.22.0",
-  "sha256": "24d7eaab509bfd835e37ff493c72c9a758dbb7a723e000077ecfec738cc71f2b",
-  "bytes": 661142
+  "version": "0.22.1",
+  "sha256": "321e97747153b9ad4ec5a5deba58d2f3248ac617cc959eb73f36f686909d45b1",
+  "bytes": 670690
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index 007c323..7512353 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index 043d594..56e9679 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.22.0"
+version = "0.22.1"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/scripts/dev/capture_dashboard.py b/scripts/dev/capture_dashboard.py
index 58dd111..286c3f0 100755
--- a/scripts/dev/capture_dashboard.py
+++ b/scripts/dev/capture_dashboard.py
@@ -11,6 +11,11 @@ con datos de ejemplo **deterministas**, así que:
 - `/api/status` se deja pasar sin tocar, para que la versión, el catálogo de modelos y el
   número de tools que aparecen sean los de verdad.
 
+Que la segunda promesa se cumpla **no depende de acordarse**: `tests/test_captura.py` compara los
+`/api/*` que la página pide con las claves de `MOCKS`, y un endpoint nuevo sin interceptar rompe el
+test. Se añadió después de descubrir que `/api/hooks` y `/api/stats` llevaban tiempo escapándose y
+publicando el log real de quien capturaba.
+
 El README avisa de que son «datos de ejemplo». Mantener ese pie es parte del trato.
 
 Junto al PNG se escribe un **manifiesto** (`dashboard.json`) con la versión que sirvió el
@@ -150,6 +155,28 @@ SEED_AND_MOCK = """() => {
   }
   events.sort((a, b) => a.ts.localeCompare(b.ts));
 
+  // Los cuatro KPIs grandes NO se calculan sobre `events`: el panel los pide a `/api/stats`,
+  // porque `/api/events` viene topado y sumar ahí subestimaría. Así que este mock no es opcional
+  // —sin él la cabecera del panel enseña el log real de quien captura— y tampoco puede llevar
+  // números a mano: se derivan de los mismos eventos de ejemplo, con las reglas de
+  // `_accounting()`. Cuando no cuadraban, la imagen se contradecía a sí misma: el pie decía
+  // «390 eventos» y el KPI de al lado «120 delegaciones».
+  const CPT = 4;
+  const stats = events.reduce((a, e) => {
+    const chunks = e.chunks || 1;
+    // `chars_in` de local_describe_image son BYTES, no caracteres: ahí estimar por chars no
+    // significa nada y el token real es el único orden de magnitud honesto.
+    const estimable = e.tool !== 'local_describe_image';
+    a.calls += 1;
+    a.backend_calls += chunks;
+    a.tokens_in += e.tokens_in;
+    a.tokens_out += e.tokens_out;
+    // Solo `source: 'path'` ahorra contexto: si el input viajó inline, ya pasó por Claude.
+    if (e.source === 'path') a.saved += estimable ? Math.floor(e.chars_in / CPT) : e.tokens_in;
+    if (!e.ok) a.errors += 1;
+    return a;
+  }, {calls: 0, backend_calls: 0, tokens_in: 0, tokens_out: 0, saved: 0, errors: 0});
+
   const MOCKS = {
     '/api/events': {meta: {chars_per_token: 4, log_dir: 'D:\\\\datos\\\\local-delegate',
       count: events.length, files_read: ['usage-202607.jsonl'],
@@ -178,6 +205,38 @@ SEED_AND_MOCK = """() => {
       gen_histogram: {p50: 61.4, p95: 48.2},
       prompt_histogram: {p50: 1840.5, p95: 1210.7},
       total_input_tokens: 486320, total_output_tokens: 138940, total_cache_tokens: 214880}},
+    // Los eventos de ejemplo siempre traen `tokens_in`/`tokens_out`, así que no hay ninguno
+    // estimado: `estimated_events: 0` es la consecuencia, no una simplificación.
+    '/api/stats': {total: {calls: stats.calls, backend_calls: stats.backend_calls,
+      errors: stats.errors, tokens_in: stats.tokens_in, tokens_out: stats.tokens_out,
+      saved: stats.saved, estimated_events: 0},
+      tokens_context_saved: stats.saved, tokens_generated_local: stats.tokens_out,
+      tokens_local_input: stats.tokens_in, backend_calls: stats.backend_calls,
+      estimated_events: 0, by_tool: [], by_model: [], by_backend: []},
+    // La tarjeta de hooks lee de aquí, y este mock **no es cosmético**: `/api/hooks` se quedó
+    // fuera de la lista y el endpoint llegaba al servidor real, así que la captura publicaba la
+    // telemetría de quien la regeneraba —conteos por categoría de su propia sesión— justo lo que
+    // la cabecera de este script promete que no pasa. Con `LD_HOOK_TELEMETRY_LOG` sin definir la
+    // tarjeta se esconde y el fallo no se veía: dependía del entorno de quien capturaba.
+    //
+    // `total`, `suggested` y `rate` se derivan de las filas en vez de escribirse a mano: si la
+    // cabecera dijera un número y la tabla sumara otro, la imagen enseñaría un panel que el
+    // dashboard real nunca puede pintar.
+    '/api/hooks': (() => {
+      const cats = [
+        {category: 'bash', suggested: 148, total: 604},
+        {category: 'lint', suggested: 96, total: 96},
+        {category: 'sin categoría', suggested: 0, total: 214},
+        {category: 'summarize', suggested: 72, total: 80},
+        {category: 'read', suggested: 41, total: 130},
+        {category: 'extract', suggested: 18, total: 22},
+      ];
+      const total = cats.reduce((a, c) => a + c.total, 0);
+      const suggested = cats.reduce((a, c) => a + c.suggested, 0);
+      return {enabled: true, log: 'D:\\\\datos\\\\local-delegate\\\\hooks.jsonl', exists: true,
+        total, suggested, rate: suggested / total,
+        by_category: cats, by_event: [], by_day: []};
+    })(),
   };
 
   const real = window.fetch.bind(window);
diff --git a/server.json b/server.json
index 58c326d..f57d548 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.22.0",
+  "version": "0.22.1",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.22.0",
+      "version": "0.22.1",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/tests/test_captura.py b/tests/test_captura.py
index 4b3e63b..ff9aadb 100644
--- a/tests/test_captura.py
+++ b/tests/test_captura.py
@@ -20,6 +20,7 @@ from __future__ import annotations
 
 import hashlib
 import json
+import re
 import tomllib
 from pathlib import Path
 
@@ -28,6 +29,16 @@ import pytest
 RAIZ = Path(__file__).resolve().parents[1]
 CAPTURA = RAIZ / "docs" / "assets" / "dashboard.png"
 MANIFIESTO = RAIZ / "docs" / "assets" / "dashboard.json"
+SCRIPT = RAIZ / "scripts" / "dev" / "capture_dashboard.py"
+PANEL = RAIZ / "src" / "local_delegate" / "web" / "metrics.py"
+
+# Lo que el script deja pasar al servidor real, con su motivo. Es una lista corta y explícita a
+# propósito: crecer aquí es una decisión, no un descuido.
+PASAN_AL_SERVIDOR_REAL = {
+    # La versión del badge, el catálogo de modelos y el número de tools tienen que ser los de
+    # verdad — el manifiesto los usa para fechar la captura.
+    "/api/status",
+}
 
 REGENERAR = (
     "Regenera la captura y su manifiesto (necesita Playwright):\n"
@@ -74,6 +85,39 @@ def test_la_captura_ensena_la_version_actual_del_proyecto():
     )
 
 
+def test_la_captura_no_publica_datos_reales_por_un_endpoint_sin_mock():
+    """Todo `/api/*` que la página pide o está mockeado, o está en la lista de los que pasan.
+
+    Este es el fallo que motivó la comprobación: `/api/hooks` y `/api/stats` no estaban en los
+    mocks, llegaban al servidor real y la captura publicaba la telemetría y los KPIs de quien la
+    regeneraba. No saltó a la vista porque **dependía del entorno**: sin
+    `LD_HOOK_TELEMETRY_LOG` la tarjeta de hooks se esconde sola, así que el escape era invisible
+    para quien no tuviera la variable puesta.
+
+    Se comparan los endpoints que la página **pide** —no los que el servidor expone— porque solo
+    puede filtrar lo que el navegador llega a preguntar.
+    """
+    pedidos = set(re.findall(r"fetch\('(/api/[a-z/]+)", PANEL.read_text(encoding="utf-8")))
+    mockeados = set(
+        re.findall(r"^\s*'(/api/[a-z/]+)':", SCRIPT.read_text(encoding="utf-8"), re.MULTILINE)
+    )
+
+    # Control positivo: si un refactor cambia la forma de pedir o de mockear, estas dos búsquedas
+    # devolverían conjuntos vacíos y el test pasaría sin haber comprobado nada.
+    assert len(pedidos) >= 6, f"la extracción de endpoints no encontró casi nada: {pedidos}"
+    assert "/api/events" in mockeados, (
+        f"la extracción de mocks no encontró los conocidos: {mockeados}"
+    )
+
+    escapan = pedidos - mockeados - PASAN_AL_SERVIDOR_REAL
+    assert not escapan, (
+        f"la página pide {sorted(escapan)} y el script no lo intercepta, así que la captura "
+        f"publicaría la respuesta real de quien la regenere.\n"
+        f"Añádelo a MOCKS en {SCRIPT.relative_to(RAIZ).as_posix()}, o a PASAN_AL_SERVIDOR_REAL "
+        f"con su motivo si de verdad tiene que pasar."
+    )
+
+
 def test_el_manifiesto_no_se_escribe_a_mano():
     """El texto que explica de dónde sale el manifiesto viaja con él, no en un comentario suelto.
 
diff --git a/uv.lock b/uv.lock
index f73bc03..7513bca 100644
--- a/uv.lock
+++ b/uv.lock
@@ -437,7 +437,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.22.0"
+version = "0.22.1"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
fix: mockear /api/stats y /api/hooks para evitar fugas de datos reales

- Los endpoints escapaban al servidor real, publicando telemetría de quien
  capturaba la imagen.
- Se derivan los valores de los eventos de ejemplo para mantener la
  consistencia con el panel.
- Se añade un test que valida que todos los `/api/*` solicitados estén
  interceptados o explícitamente permitidos.
- Se actualizan dependencias y acciones de GitHub Actions.
```

### Mensaje B

```
fix(release): actualizar a v0.22.1 y corregir fuga de datos en captura

- Corrige la fuga de telemetría real en los endpoints `/api/stats` y `/api/hooks` durante la captura del dashboard.
- Añade mocks para los endpoints faltantes en `capture_dashboard.py`.
- Implementa un test en `test_captura.py` para asegurar que ningún endpoint nuevo escape de la interceptación.
- Actualiza dependencias (fastapi, uvicorn, filelock, ruff) y GitHub Actions.
- Actualiza la versión en `pyproject.toml`, `server.json`, `uv.lock` y el manifiesto de assets.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 14

Diff: 4 ficheros, +302 −0

````diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 5aea716..1930ad0 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,26 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+### Added
+- **La wiki tiene por fin una página de catálogo de tools** (`docs/wiki/Tools.md`). Hasta ahora las
+  once tools `local_*` solo estaban en la tabla resumen del README y en la skill: la wiki no las
+  nombraba en ningún sitio, así que `local_boilerplate` no aparecía en toda la documentación
+  extendida. La página lleva, por tool, la firma exacta, qué devuelve, qué modelo la atiende y qué
+  pasa cuando la entrada no cabe, más la letra pequeña que solo estaba en el código:
+
+  - que **map-reduce y troceado no son lo mismo** —el primero reduce (`local_summarize`,
+    `local_lint_summary`, `local_commit_msg`) y el segundo transforma trozo a trozo
+    (`local_delegate`, `local_translate`), porque fundir una traducción perdería contenido—;
+  - que `local_extract` **trunca** y lo dice dentro del propio objeto, con la clave reservada
+    `_local_delegate`;
+  - que `local_status` no llama al backend de chat, así que **no** prueba que la credencial sirva;
+  - y que un diff que no cabe da un mensaje de commit que solo describe el principio del cambio.
+
+  El catálogo sale de `server.mcp.list_tools()`, o sea de lo que el cliente MCP ve de verdad. Tres
+  tests nuevos en `tests/test_wiki.py` lo mantienen así: uno compara las secciones con el servidor
+  en los dos sentidos, otro la tabla índice, y otro el número escrito con letra. Añadir una tool
+  sin documentarla pone el CI en rojo en el mismo PR que la introduce.
+
 ### Fixed
 - **La wiki llevaba cuatro versiones sin actualizarse, y ahora hay quien lo note.** `docs/wiki/`
   no se tocaba desde la 0.23.0: la tabla de comprobaciones de `doctor` tenía **diecisiete** filas
diff --git a/docs/wiki/Home.md b/docs/wiki/Home.md
index 486ff9e..0437ee2 100644
--- a/docs/wiki/Home.md
+++ b/docs/wiki/Home.md
@@ -5,6 +5,7 @@ Documentación extendida del MCP `local-delegate`. Para empezar rápido, ve al
 
 ## Páginas
 
+- **[Catálogo de tools](Tools.md)** — las once tools `local_*`: firma, qué devuelven, qué modelo usan y qué pasa cuando la entrada no cabe.
 - **[Architecture](Architecture.md)** — daemon HTTP/compatibilidad stdio → endpoint OpenAI-compatible, guardrail, logging y dashboard.
 - **[Daemon compartido](Daemon.md)** — un solo MCP persistente para Codex, Claude Code y otros clientes.
 - **[Instalación de la integración](Integration-install.md)** — `install`/`uninstall`: entrada MCP, hooks, skill y bloque de memoria en CLAUDE.md/AGENTS.md.
diff --git a/docs/wiki/Tools.md b/docs/wiki/Tools.md
new file mode 100644
index 0000000..792feb2
--- /dev/null
+++ b/docs/wiki/Tools.md
@@ -0,0 +1,231 @@
+# Catálogo de tools
+
+Las **once** tools `local_*` que expone el servidor MCP, con su firma exacta, lo que devuelven y la
+letra pequeña que solo estaba en el código. El [README](../../README.md) tiene la tabla de una
+ojeada; esta página es la referencia.
+
+## La regla que gobierna todas: pasa `path`, no el contenido
+
+Casi todas aceptan `text` (o `code`, o `diff`) **y** `path`. No son equivalentes:
+
+- Con **`text`**, el contenido pasa por tu contexto antes de llegar a la tool. Ya lo pagaste.
+- Con **`path`**, el archivo lo lee el **servidor**, y el contenido no entra a tu contexto jamás.
+  Ahí está el ahorro, y por eso todo lo que hay debajo insiste en lo mismo.
+
+Con backend remoto (la Mac delegando en la PC), la ruta se resuelve **en la máquina donde corre el
+MCP**, no donde está el modelo. Ver [Backend remoto](Remote-backend.md).
+
+## De un vistazo
+
+| Tool | Qué hace | Modelo | Si la entrada no cabe |
+|---|---|---|---|
+| [`local_summarize`](#local_summarize) | Resume texto o archivo | mecánico / largo (auto) | **map-reduce** |
+| [`local_classify`](#local_classify) | Devuelve UNA etiqueta de una lista | mecánico | trunca |
+| [`local_extract`](#local_extract) | Extrae campos → objeto ya validado | mecánico / largo (auto) | trunca y **lo dice** |
+| [`local_boilerplate`](#local_boilerplate) | Genera código y lo **escribe en disco** | código | (la spec es corta) |
+| [`local_delegate`](#local_delegate) | Escape genérico texto→texto | mecánico, o el que pases | **trozo a trozo** |
+| [`local_lint_summary`](#local_lint_summary) | Resume salida de lint/tests/CI | mecánico / largo (auto) | **map-reduce** |
+| [`local_commit_msg`](#local_commit_msg) | Mensaje de commit desde un diff | código | **map-reduce** |
+| [`local_translate`](#local_translate) | Traduce texto o archivo | mecánico / largo (auto) | **trozo a trozo** |
+| [`local_explain_code`](#local_explain_code) | Explica código en prosa | código | trunca |
+| [`local_describe_image`](#local_describe_image) | Imagen → texto | visión | — |
+| [`local_status`](#local_status) | Diagnóstico de solo lectura | — | — |
+
+Las dos formas de trocear **no** son la misma, y la diferencia se nota en el resultado:
+
+- **map-reduce** — resume cada trozo y funde los resúmenes. Sirve para *reducir*: el resultado es
+  más corto que la entrada.
+- **trozo a trozo** — transforma cada trozo y concatena. Sirve para *transformar* conservando el
+  tamaño (traducir, reescribir); fundir aquí perdería contenido.
+
+El presupuesto de cada trozo se mide en **caracteres** y sale del modelo destino
+(`LOCAL_DELEGATE_MAX_CHARS_*`, ver [Configuration](Configuration.md)).
+
+---
+
+## `local_summarize`
+
+```python
+local_summarize(text=None, path=None, max_words=150) -> str
+```
+
+Resume un texto o archivo. Prefiérela a leer el archivo con `Read` cuando pasa de ~200 líneas o
+~10 KB y solo necesitas el sentido, no el literal.
+
+| Parámetro | | |
+|---|---|---|
+| `text` | opcional | El texto a resumir. Usa esto **o** `path`. |
+| `path` | opcional | Ruta al archivo, leído por el servidor. **Preferible.** |
+| `max_words` | `150` | Tope de palabras del resumen. |
+
+Enruta sola al modelo de contexto largo cuando la entrada es grande. Si aun así no cabe, hace
+map-reduce: el log del panel guarda **una** entrada con `chunks: N`, no N entradas.
+
+## `local_classify`
+
+```python
+local_classify(text, labels) -> str
+```
+
+Devuelve **una** de las etiquetas de `labels`, sin prosa alrededor. Los dos parámetros son
+obligatorios. Una llamada, siempre: si el texto no cabe, se trunca.
+
+## `local_extract`
+
+```python
+local_extract(fields, text=None, path=None) -> dict
+```
+
+Extrae campos estructurados. **Devuelve un objeto ya validado**, con exactamente las claves que
+pediste — no una cadena que haya que parsear.
+
+| Parámetro | | |
+|---|---|---|
+| `fields` | **obligatorio** | Nombres de los campos, que son las claves del JSON. |
+| `text` / `path` | opcional | La fuente. `path` no gasta contexto. |
+
+Dos cosas que conviene saber y solo estaban en el código:
+
+- **Si hubo que truncar la entrada, lo dice en el propio objeto**, con la clave reservada
+  `_local_delegate`. Antes ese aviso iba como texto delante del JSON, donde obligaba a limpiar la
+  cadena antes de poder parsearla.
+- Pide al backend un JSON restringido por schema (`LOCAL_DELEGATE_JSON_SCHEMA=auto`); si el backend
+  no lo soporta, reintenta en modo libre.
+
+## `local_boilerplate`
+
+```python
+local_boilerplate(spec, language, target, overwrite=False) -> str
+```
+
+Genera código desde una especificación. **Escribe el resultado en `target` y devuelve solo un
+recibo** de dos líneas (ruta, tamaño y los tokens que no entraron al contexto).
+
+| Parámetro | | |
+|---|---|---|
+| `spec` | **obligatorio** | Qué debe hacer el código. |
+| `language` | **obligatorio** | `python`, `typescript`, … |
+| `target` | **obligatorio** | Ruta **absoluta** del archivo. Los directorios que falten se crean. |
+| `overwrite` | `False` | Pisar `target` si existe. Sin él **falla antes de generar nada**. |
+
+`target` es obligatorio **a propósito**: como parámetro opcional, el ahorro dependería de que quien
+llama se acuerde de usarlo, y de eso hay tres mediciones seguidas con cero adopción. El código
+generado no vuelve a tu contexto; para verlo, abre el archivo.
+
+> **Cambió en la 0.27.0.** Antes devolvía el código. Si tienes una integración vieja que esperaba
+> recibirlo, ahora recibe el recibo.
+
+## `local_delegate`
+
+```python
+local_delegate(task, input, output_format, model=None, chunk="auto") -> str
+```
+
+La tool de escape: cualquier tarea texto→texto que no tenga tool propia.
+
+| Parámetro | | |
+|---|---|---|
+| `task` | **obligatorio** | Qué hacer, en una frase. |
+| `input` | **obligatorio** | El texto de entrada. |
+| `output_format` | **obligatorio** | Qué forma debe tener la salida. **No es decorativo**: es lo que hace revisable el resultado. |
+| `model` | auto | Fuerza un modelo del catálogo permitido. |
+| `chunk` | `"auto"` | Cómo trocear si no cabe. |
+
+Trocea **trozo a trozo**, porque una tarea genérica puede ser una transformación y fundir los
+trozos perdería contenido.
+
+## `local_lint_summary`
+
+```python
+local_lint_summary(path=None, text=None, max_words=200) -> str
+```
+
+Resume la salida de lint, tests o CI: qué falló, dónde y por qué, sin las mil líneas de ruido. Es
+la tool para cuando un comando escupe más de lo que cabe — vuelca la salida a un archivo y pasa
+`path`. Map-reduce si hace falta.
+
+## `local_commit_msg`
+
+```python
+local_commit_msg(diff=None, path=None, style="conventional") -> str
+```
+
+Mensaje de commit a partir de un diff.
+
+| Parámetro | | |
+|---|---|---|
+| `diff` / `path` | opcional | El diff. Para uno grande, vuélcalo a archivo y pasa `path`. |
+| `style` | `"conventional"` | Estilo del mensaje. |
+
+Hace map-reduce sobre el diff, y eso importa más de lo que parece: un diff que no cabe y se
+**trunca** produce un mensaje que solo describe el principio del cambio.
+
+## `local_translate`
+
+```python
+local_translate(target_lang, text=None, path=None) -> str
+```
+
+Traduce. `target_lang` es obligatorio; la fuente va en `text` o `path`. Trocea **trozo a trozo**,
+que es lo correcto al traducir: el resultado debe conservar el tamaño del original.
+
+## `local_explain_code`
+
+```python
+local_explain_code(code=None, path=None, question=None) -> str
+```
+
+Explica código en prosa, con el modelo de código. Con `question` responde algo concreto en vez de
+dar la explicación general. Una llamada: si el archivo no cabe, se trunca.
+
+## `local_describe_image`
+
+```python
+local_describe_image(path, question=None, max_words=200) -> str
+```
+
+Describe una imagen o responde una pregunta sobre ella, con el modelo de visión. `path` es
+obligatorio — la imagen la lee el servidor, no la adjuntas tú.
+
+Es **imagen→texto** y nada más: no genera ni edita imágenes. El tope de tamaño lo pone
+`LOCAL_DELEGATE_MAX_IMAGE_MB` (8 MB por defecto).
+
+## `local_status`
+
+```python
+local_status() -> str
+```
+
+Diagnóstico de solo lectura: backend, catálogo de modelos, ruta del log, VRAM y RAM del sistema.
+**No llama al backend de chat**, así que sirve para saber si el backend responde, pero **no**
+prueba que la credencial funcione — para eso hace falta una tool que ejerza el modelo de verdad.
+Para el diagnóstico completo de la instalación, `local-delegate doctor` (ver
+[Instalación](Integration-install.md)).
+
+---
+
+## Qué modelo usa cada perfil
+
+Cuatro perfiles, todos cambiables por entorno (ver [Configuration](Configuration.md)):
+
+| Perfil | Variable | Por defecto | Lo usan |
+|---|---|---|---|
+| mecánico | `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | resumir, clasificar, extraer, traducir, delegar |
+| contexto largo | `LOCAL_DELEGATE_MODEL_LONG` | `llama31-8b` | los mismos, cuando la entrada es grande |
+| código | `LOCAL_DELEGATE_MODEL_CODE` | `qwen25-coder-14b` | boilerplate, commit-msg, explicar código |
+| visión | `LOCAL_DELEGATE_MODEL_VISION` | `qwen3-vl-8b` | describir imágenes |
+
+El salto de mecánico a largo es **automático** y se decide sondeando el tamaño: bytes del archivo
+para `path`, caracteres para `text`.
+
+## Cuándo NO delegar
+
+Estas tools son para pasos mecánicos con un formato de salida claro. Lo que pide criterio,
+arquitectura, razonamiento encadenado o cruzar varias fuentes **no** se delega: el ahorro no
+compensa un resultado que hay que rehacer.
+
+## Ver también
+
+- **[Savings & metrics](Savings-and-metrics.md)** — cómo se cuenta el ahorro de cada llamada.
+- **[Backend remoto](Remote-backend.md)** — dónde se resuelve `path` cuando el modelo está en otra máquina.
+- **[Troubleshooting](Troubleshooting.md)** — qué hacer cuando una tool responde `401` o el backend no está.
diff --git a/tests/test_wiki.py b/tests/test_wiki.py
index 78c7ead..02d6ac6 100644
--- a/tests/test_wiki.py
+++ b/tests/test_wiki.py
@@ -30,6 +30,8 @@ WORKFLOW = RAIZ / ".github" / "workflows" / "wiki.yml"
 from local_delegate import checks
 
 _GRUPOS_DE_LA_TABLA = {"Entorno", "Andamiaje", "Servicios", "Backend"}
+_NUMERO_DE_TOOLS = {10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce"}
+
 _NUMERO_DE_CHECKS = {
     15: "quince",
     16: "dieciséis",
@@ -228,3 +230,51 @@ def test_la_wiki_dice_cuantas_comprobaciones_hay_de_verdad():
     texto = (WIKI / "Integration-install.md").read_text(encoding="utf-8")
     frase = f"las {cuantas} piezas"
     assert frase in texto, f"la wiki no dice «{frase}»; hay {len(checks.CHECKS)} comprobaciones"
+
+
+def _tools_del_servidor() -> list[str]:
+    """Los nombres que el servidor MCP expone de verdad, no los que creemos que expone."""
+    import asyncio
+
+    from local_delegate import server
+
+    return sorted(t.name for t in asyncio.run(server.mcp.list_tools()))
+
+
+def _tools_documentadas() -> list[str]:
+    """Las que `Tools.md` documenta con su propia sección `## \\`local_x\\``."""
+    texto = (WIKI / "Tools.md").read_text(encoding="utf-8")
+    return sorted(re.findall(r"^## `(local_\w+)`", texto, re.MULTILINE))
+
+
+def test_el_catalogo_documenta_todas_las_tools_y_ninguna_de_mas():
+    """La página de tools envejece con cada tool nueva, así que no puede depender de acordarse.
+
+    Es la misma medicina que la tabla del doctor: la wiki se comparó contra el registro real y
+    resultó llevar cuatro versiones desfasada. Aquí la fuente es `server.mcp.list_tools()`, o sea
+    lo que el cliente MCP ve de verdad — añadir una tool sin documentarla pone el CI en rojo en el
+    mismo PR que la introduce, y quitar una deja la sección huérfana a la vista.
+    """
+    del_servidor = _tools_del_servidor()
+    documentadas = _tools_documentadas()
+
+    faltan = [t for t in del_servidor if t not in documentadas]
+    sobran = [t for t in documentadas if t not in del_servidor]
+    assert not faltan, f"tools sin sección en Tools.md: {faltan}"
+    assert not sobran, f"secciones de Tools.md sin tool detrás: {sobran}"
+
+
+def test_el_catalogo_dice_cuantas_tools_hay_de_verdad():
+    """El número escrito con letra en la entradilla y en el índice de la wiki."""
+    cuantas = _NUMERO_DE_TOOLS[len(_tools_del_servidor())]
+    assert f"Las **{cuantas}** tools" in (WIKI / "Tools.md").read_text(encoding="utf-8")
+    assert f"las {cuantas} tools" in (WIKI / "Home.md").read_text(encoding="utf-8")
+
+
+def test_la_tabla_de_un_vistazo_lista_todas_las_tools():
+    """La tabla índice y las secciones son dos listas del mismo conjunto: se desincronizan solas."""
+    texto = (WIKI / "Tools.md").read_text(encoding="utf-8")
+    tabla = re.findall(r"^\| \[`(local_\w+)`\]", texto, re.MULTILINE)
+    assert sorted(tabla) == _tools_del_servidor(), (
+        f"la tabla «De un vistazo» no cuadra con el servidor: {sorted(tabla)}"
+    )
````

### Mensaje A

```
docs(wiki): añadir catálogo de tools con firma, modelo y comportamiento

- Documentar las once tools `local_*` en `docs/wiki/Tools.md`
- Incluir firma exacta, modelo asignado y manejo de entrada grande
- Explicar diferencias entre map-reduce y troceado por trozo
- Actualizar `Home.md` con enlace al nuevo catálogo
- Añadir tests en `test_wiki.py` para mantener la wiki sincronizada
- Validar que el catálogo coincida con `server.mcp.list_tools()`
- Verificar consistencia entre tabla índice y secciones detalladas
- Comprobar que el número de tools escrito coincide con la realidad
```

### Mensaje B

```
docs(wiki): añadir catálogo detallado de tools y tests de validación

- Se crea `docs/wiki/Tools.md` con la documentación técnica de las once tools `local_*`.
- Se incluye información sobre firmas, modelos, gestión de contextos y comportamiento ante entradas excedidas.
- Se añade un enlace al nuevo catálogo en `docs/wiki/Home.md`.
- Se implementan tests en `tests/test_wiki.py` para asegurar que la documentación esté sincronizada con el servidor MCP y que el número de tools sea correcto.
- Se actualiza el `CHANGELOG.md` con las novedades.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 15

Diff: 3 ficheros, +93 −24

```diff
diff --git a/.sdd/changes/aislar-entorno-en-tests/handoff.md b/.sdd/changes/aislar-entorno-en-tests/handoff.md
index 3fb6fd1..10e5187 100644
--- a/.sdd/changes/aislar-entorno-en-tests/handoff.md
+++ b/.sdd/changes/aislar-entorno-en-tests/handoff.md
@@ -2,24 +2,40 @@
 
 ## Current state
 
-- SDD status:
-- Last completed gate:
-- Current revision:
+- SDD status: `closed` (modo lite).
+- Last completed gate: `memory`.
+- Current revision: `main` @ `0436aa4` (squash de la PR #135).
 
 ## What changed
 
-- Summarize completed work without reproducing the full Git history.
+`config` lleva ahora su propio inventario de variables de entorno (`VARIABLES_DE_ENTORNO`, 34),
+alimentado por las lecturas reales del módulo a través de `_leer`, que es su única puerta a
+`os.environ`. `tests/conftest.py` usa ese inventario para correr la suite como si ninguna variable
+del paquete estuviera definida, recargando el módulo. `tests/test_aislamiento_entorno.py` añade tres
+guardianes.
+
+Efecto: `uv run pytest` da `725 passed, 2 skipped` tanto en una máquina con el daemon instalado como
+en CI. Antes daba cuatro fallos `401 == 200` en la primera.
 
 ## Decisions
 
-- Record decisions that a future session cannot reliably derive from code alone.
+- **Recargar `config` en vez de reasignar constantes** en el conftest. Copiar los defaults allí
+  crearía una segunda fuente de verdad que envejece en silencio — el defecto recurrente del repo.
+  El reload es seguro **porque nadie hace `from local_delegate.config import <constante>`**;
+  comprobado por búsqueda. Si algún día alguien lo hiciera, esta decisión deja de ser válida.
+- **La lista de variables no se escribe a mano** por el mismo motivo, y se congela al final de
+  `config.py` a propósito: declararla antes dejaría fuera lo que se lea más abajo.
+- **Lo capturado en tiempo de import queda fuera de alcance** (`server._chat_slots` fija
+  `MAX_CONCURRENT_REQUESTS` al importar). Declarado y medido, no olvidado.
 
 ## Next action
 
-- State the single best next step and any prerequisite context.
+Nada pendiente. GitHub queda sin alertas de ningún tipo, sin issues y sin PRs abiertos.
 
 ## Memory
 
-- Canonical note:
-- Indexes updated:
-
+- Canonical note: `obsidian-vault/projects/local-delegate/jornada-2026-08-03-las-alertas-de-codeql.md`,
+  sección de cierre (misma jornada: esto es la deuda que dejó la PR #133).
+- Indexes updated: memoria del proyecto en Claude Code — el gancho del gotcha de
+  `LOCAL_DELEGATE_WEB_TOKEN` pasa de «deuda abierta» a resuelto, con el patrón que lo cierra.
+- Sin secretos ni datos personales en los artefactos.
diff --git a/.sdd/changes/aislar-entorno-en-tests/review.md b/.sdd/changes/aislar-entorno-en-tests/review.md
index 6a1437f..3958029 100644
--- a/.sdd/changes/aislar-entorno-en-tests/review.md
+++ b/.sdd/changes/aislar-entorno-en-tests/review.md
@@ -2,19 +2,35 @@
 
 ## Verdict
 
-Choose one: `conforms`, `conforms-with-notes`, or `does-not-conform`.
+`conforms` — los seis requisitos implementados y verificados, cada uno contra ejecución real y no
+contra inspección.
 
 ## Specification comparison
 
 | Requirement | Implemented | Verified | Notes |
 | --- | --- | --- | --- |
-| REQ-001 | | | |
+| REQ-001 | sí | sí | 34 variables registradas solas; la enumeración manual previa veía 14 |
+| REQ-002 | sí | sí | `_leer` es la única aparición de `os.environ` en `config.py`; guardián AST |
+| REQ-003 | sí | sí | Sin duplicar defaults: el aislamiento recarga el módulo |
+| REQ-004 | sí | sí | `25 passed` con `LOCAL_DELEGATE_WEB_TOKEN` puesta (antes 4 fallos) |
+| REQ-005 | sí | sí | Dos mutantes + control positivo del inventario |
+| REQ-006 | sí | sí | `725 passed, 2 skipped` en los dos entornos; 13/13 checks en la PR #135 |
 
 ## Findings
 
-- List correctness, security, maintainability, or scope findings in severity order.
+1. **El inventario automático se pagó solo en la primera medición.** El mutante del aislamiento
+   destapó que las variables contaminando esta máquina eran cuatro y no dos: `LOCAL_DELEGATE_AUTOSTART`
+   y `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS` también estaban definidas. Una lista escrita a mano
+   habría cubierto las dos que yo había visto y habría dejado las otras dos vivas, con el mismo
+   aspecto de «arreglado».
+2. **Enumerar a ojo subestimó el alcance a la mitad** (14 de 34). El `grep` inicial solo capturaba
+   `_env(`, no `_env_int`/`_env_flag`/`_env_float`. Cuando la pregunta es «cuántos sitios hay»,
+   preguntárselo al programa es mejor que contarlos leyendo.
+3. **`gh pr checks` completo, no `gh run list`** — aplicado desde el principio en esta PR, tal como
+   lo dejó escrito la revisión de la #133. Los 13 checks incluyen el `CodeQL` que no aparece en el
+   listado de workflows.
 
 ## Required follow-up
 
-- Identify work that must be completed before closure.
-
+Ninguno. El único límite conocido —lo que otros módulos capturan en tiempo de import— está
+declarado en el brief, medido, y hoy no afecta a ningún test.
diff --git a/.sdd/changes/aislar-entorno-en-tests/state.json b/.sdd/changes/aislar-entorno-en-tests/state.json
index 1f969b7..fc04a4a 100644
--- a/.sdd/changes/aislar-entorno-en-tests/state.json
+++ b/.sdd/changes/aislar-entorno-en-tests/state.json
@@ -3,9 +3,9 @@
   "slug": "aislar-entorno-en-tests",
   "title": "La suite no puede heredar el entorno de quien la corre",
   "mode": "lite",
-  "status": "verifying",
+  "status": "closed",
   "createdAt": "2026-08-04T00:53:19.826Z",
-  "updatedAt": "2026-08-04T00:55:43.833Z",
+  "updatedAt": "2026-08-04T01:01:28.614Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -26,16 +26,16 @@
       "actor": "user"
     },
     "conformance": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-04T01:01:27.902Z",
+      "evidence": "Revision fresca en review.md contra los seis requisitos: los seis implementados y verificados por ejecucion. 725 passed en los dos entornos, 13/13 checks en la PR #135, mergeada en 0436aa4. Veredicto conforms, sin follow-up.",
+      "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-04T01:01:28.433Z",
+      "evidence": "Nota del vault ampliada con la seccion de cierre. Punteros actualizados en los tres indices, incluido el de Codex que decia 'still open as debt' y ahora dice resuelto. Nuevo conocimiento reutilizable registrado en los dos indices globales. Sin secretos ni PII.",
+      "actor": "user"
     }
   },
   "history": [
@@ -111,6 +111,43 @@
       "at": "2026-08-04T00:55:43.833Z",
       "evidence": "725 passed / 2 skipped con el entorno REAL del usuario y con el limpio, mismo numero. Los 25 de test_daemon.py pasan con LOCAL_DELEGATE_WEB_TOKEN puesta (antes 4 fallos). ruff check y format limpios; node --check ok. Dos mutantes, uno por guardian, ambos fallan por su propio assert; mas control positivo del inventario.",
       "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "conformance",
+      "status": "approved",
+      "at": "2026-08-04T01:01:27.902Z",
+      "evidence": "Revision fresca en review.md contra los seis requisitos: los seis implementados y verificados por ejecucion. 725 passed en los dos entornos, 13/13 checks en la PR #135, mergeada en 0436aa4. Veredicto conforms, sin follow-up.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-08-04T01:01:28.064Z",
+      "reason": "PR #135 mergeada"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-08-04T01:01:28.245Z",
+      "reason": "conformidad aprobada"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-08-04T01:01:28.433Z",
+      "evidence": "Nota del vault ampliada con la seccion de cierre. Punteros actualizados en los tres indices, incluido el de Codex que decia 'still open as debt' y ahora dice resuelto. Nuevo conocimiento reutilizable registrado en los dos indices globales. Sin secretos ni PII.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-08-04T01:01:28.614Z",
+      "reason": "deuda cerrada y memoria persistida"
     }
   ]
 }
```

### Mensaje A

```
docs(sdd): cerrar cambio de aislamiento de entorno en tests

- Actualizar el estado de la SDD a `closed`.
- Registrar la conformidad de los requisitos en `review.md`.
- Documentar las decisiones de diseño y el inventario de variables en `handoff.md`.
- Actualizar el historial de transiciones y la memoria en `state.json`.
```

### Mensaje B

```
feat: aislar entorno en tests y cerrar deuda
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 16

Diff: 6 ficheros, +11 −8

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 1610fb6..03d17ec 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.25.0] - 2026-08-18
+
 ### Added
 - **El panel dice quién delegó.** Cada línea del log de uso lleva ahora el nombre del cliente MCP
   que pidió la llamada, y `/api/stats` trae el desglose por cliente. El KPI de ahorro es
@@ -1606,7 +1608,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 - Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
   registro oficial de MCP.
 
-[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.24.0...HEAD
+[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.25.0...HEAD
+[0.25.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.24.0...v0.25.0
 [0.24.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.23.0...v0.24.0
 [0.23.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.1...v0.23.0
 [0.22.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.0...v0.22.1
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index c5f3b22..e385ff2 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.24.0",
-  "sha256": "1f421a75c6d889edf44ac593fcdad315aa8ce2fb1098da50488860ca0049bd13",
-  "bytes": 670197
+  "version": "0.25.0",
+  "sha256": "ed356f95c102b7418d9141546839dfa088f277c5abd8658cee5f47c54f6638ba",
+  "bytes": 722914
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index 806ded0..cc99a87 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index ae1c10b..c4c037a 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.24.0"
+version = "0.25.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/server.json b/server.json
index 614738e..d1704db 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.24.0",
+  "version": "0.25.0",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.24.0",
+      "version": "0.25.0",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/uv.lock b/uv.lock
index 375576b..622fe10 100644
--- a/uv.lock
+++ b/uv.lock
@@ -437,7 +437,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.24.0"
+version = "0.25.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
feat: actualizar versión a 0.25.0

- mostrar cliente MCP en log de uso y API stats
- actualizar artefactos y metadatos de versión
- refrescar lockfile y documentación
```

### Mensaje B

```
build(release): actualizar versión a 0.25.0

- Actualizar versión en pyproject.toml, server.json y uv.lock
- Registrar versión 0.25.0 en CHANGELOG.md
- Actualizar metadatos de dashboard.json y assets
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 17

Diff: 2 ficheros, +173 −1

```diff
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
index e0d5a56..abe157a 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
@@ -130,6 +130,30 @@ Ninguno es opcional. Dos veces en este proyecto lo roto era la prueba, no el cod
 
 **Falla CP-1 => no hay tanda.** Es el unico control con veto absoluto.
 
+#### Resultado de CP-1 (tarea 18, 2026-09-14): pasa, despues de un veto real
+
+- **El 122B no esta en disco.** Sustituto aprobado por el usuario: `qwen25-coder-14b` con KV f16 y
+  contexto grande. **El primer sustituto no discriminaba**: a `-c 131072` la KV pide 24 576 MiB de
+  una vez, y eso no cabe ni con desbordamiento (quedan ~7 GB de VRAM + ~15,5 GB compartidos). El que
+  vale es **`-c 65536`: ~12 GiB de KV + 8,4 GB de pesos ~= 21 GB**, que no cabe en VRAM y si cabe
+  con memoria compartida. Solo con ese la politica decide el resultado.
+- **b10909 trae `--fit on` y `-ngl auto` por defecto**, que reducen capas hasta que quepa: sin
+  `--fit off -ngl 99` CP-1 «pasaria» cargando a medias. Fijado en `llama-swap-pruebas.yaml`.
+- **Control del control: la misma carga contra los dos ejecutables.** Medido con
+  `\GPU Adapter Memory(luid_..._0x0000F722_phys_0)\Shared Usage` (reposo: ~140 MiB).
+
+| Hora UTC | Perfil en la NVIDIA App | b10909 | b9925 (produccion) |
+| --- | --- | --- | --- |
+| 19:37 | entrada «nueva» que quedo apuntando a produccion | **cargo en 6,6 s, 6 071 MiB compartidos** | OOM a los 4,1 s |
+| 19:42 | usuario borra la entrada y la anade de nuevo sobre b10909 | **OOM a los 3,9 s** (`cudaMalloc` 12 288 MiB) | cargo en 7,1 s, 6 124 MiB compartidos |
+
+- **La NVIDIA App muestra los programas solo por nombre de fichero.** Anadir un segundo
+  `llama-server.exe` no crea otra entrada: se queda la primera, y nada en el panel dice a que ruta
+  apunta. Solo la medida lo delata. Consecuencia: **produccion queda sin perfil mientras dure la
+  medicion**, y el rollback de la tarea 18 incluye volver a anadirlo y **medirlo** con esta misma
+  prueba (b9925 debe dar OOM).
+- De paso, la primera verificacion por efecto del perfil de produccion del 2026-09-12: **si actuaba**.
+
 ### CP-2 — El medidor mide el proceso
 
 Cargar `qwen35-2b` y `qwen25-coder-14b` y leer la sonda con cada uno. **Esperado: numeros
@@ -140,6 +164,34 @@ En la misma pasada se averigua **que es `llamaswap_memory_used_bytes`** (el gaug
 `MetricsSampler`): si resulta ser memoria del sistema, se degrada a dato de contexto y no entra en
 ninguna decision. Es el candidato a repetir el error de julio.
 
+#### Resultado de CP-1 negativo y CP-2 (tarea 18, 2026-09-14): pasan
+
+Por el llama-swap de pruebas (puerto 9595), leyendo con `ProcessProbe` del repo y, en la misma
+muestra, la RAM del sistema, `nvidia-smi` y los gauges de llama-swap. «Reposo» es tras `GET /unload`.
+
+| Estado (UTC) | VRAM ded. proceso | VRAM compart. proceso | Privada proceso | Working set | RAM sistema | `nvidia-smi` | `llamaswap_memory_used` | `llamaswap_gpu_memory_used` |
+| --- | --- | --- | --- | --- | --- | --- | --- | --- |
+| reposo | — (`no_process`) | — | — | — | 13 038 | 852 | 13 035 | 852 |
+| `gemma3-4b` (19:43) | 2 918 | 98 | 3 554 | 2 834 | 15 950 | 3 769 | 15 948 | 3 769 |
+| `qwen35-2b` (19:44) | 3 092 | 96 | 4 269 | 3 331 | 16 471 | 3 943 | 16 454 | 3 943 |
+| `qwen25-coder-14b` (19:44) | 8 838 | 108 | 9 555 | 8 641 | 21 791 | 9 689 | 21 805 | 9 689 |
+| reposo | — (`no_process`) | — | — | — | 13 123 | 852 | 13 124 | 852 |
+
+(MiB.)
+
+- **CP-1 negativo pasa**: `gemma3-4b` carga (HTTP 200) sin desbordar (98 MiB compartidos, igual que
+  cualquier proceso en reposo). Con la mitad positiva, **CP-1 pasa**.
+- **CP-2 pasa**: la sonda da numeros distintos por modelo, del orden del GGUF, y vuelve a
+  `no_process` al descargar.
+- **`llamaswap_memory_used_bytes` es la RAM usada de TODO el sistema** (13 035 vs 13 038, 21 805 vs
+  21 791), y `llamaswap_gpu_memory_used_bytes` es `nvidia-smi` del adaptador entero. Los dos quedan
+  **degradados a dato de contexto**: ninguno entra en una decision. Confirma la pista de §3.4 (el
+  `nvidia-smi.exe` hijo de llama-swap).
+- **Hallazgo que CP-2b hereda: la RAM privada del proceso INCLUYE la VRAM reservada.** Con el 14B,
+  9 555 MiB privados para 8 838 de VRAM: en WDDM la memoria de GPU cuenta en el commit del proceso.
+  Asi que `PrivateUsage` no es «RAM del host» a secas, y lo que mide los expertos en RAM es la
+  **diferencia** entre configuraciones, o `privada - VRAM dedicada`.
+
 ### CP-2b — El contador ve los expertos que viven en RAM
 
 CP-2 compara dos modelos densos y **los dos escalarian aunque los dos subestimaran**. El caso que de
@@ -152,6 +204,34 @@ segundo caso en un orden parecido al tamano de los expertos descargados** (~0,38
 calibrado en julio). Si no sube, el `--load-mode` elegido no sirve para medir y se cambia — o se
 publican los dos contadores, el privado y el working set, diciendo cual es cual.
 
+#### Resultado de CP-2b (tarea 18, 2026-09-14): el contador ve los expertos solo con `none`, y en diferencia
+
+`gpt-oss-20b` MXFP4 (11,3 GB), mismo llama-swap de pruebas. MiB, lectura ~3 s tras cargar.
+
+| Variante (UTC) | VRAM ded. | VRAM compart. | Privada | Working set | Privada − VRAM ded. | WS − VRAM ded. | RAM sistema |
+| --- | --- | --- | --- | --- | --- | --- | --- |
+| reposo (19:45) | — | — | — | — | — | — | 13 133 |
+| `mmap`, `-ncmoe 0` (19:45) | 11 484 | 100 | 12 424 | 11 665 | 940 | 181 | 23 932 |
+| `mmap`, `-ncmoe 12` (19:46) | 6 742 | 100 | 7 671 | 10 830 | **929** | **4 088** | 23 135 |
+| `none`, `-ncmoe 0` (19:46) | 11 485 | 688 | 12 989 | 1 298 | 1 504 | — | 13 542 |
+| `none`, `-ncmoe 12` (19:46) | 6 752 | **5 542** | 13 103 | 6 153 | **6 351** | — | 18 359 |
+
+- `-ncmoe 12` saca **4 742 MiB** de la VRAM: ~395 MiB por capa, en linea con los ~0,38 GiB de julio.
+- **H4 confirmada, y con la forma exacta del riesgo**: con `mmap`, la privada no ve los expertos
+  (`privada − VRAM` se queda en ~930); solo el working set los recoge, y parcialmente (+3 907).
+- **Con `none` si los ve**: `privada − VRAM` sube **+4 847**, lo mismo que la RAM del sistema
+  (+4 817). `none` carga en ~4 s tras la primera lectura del GGUF: practicable.
+- **El esperado de este control estaba mal escrito**: «la RAM del proceso sube». La privada
+  **absoluta** apenas se mueve en ningun modo (+114 con `none`, −4 753 con `mmap`), porque en WDDM la
+  privada incluye la VRAM reservada (resultado de CP-2) y lo que sale de la VRAM compensa lo que entra
+  en RAM. La magnitud que decide es **`privada − VRAM dedicada`**. Leido al pie de la letra, el
+  control habria fallado en los dos modos, o pasado con el que no sirve si se hubiera mirado el WS.
+- **Trampa nueva**: con `none`, los expertos en RAM aparecen **tambien como VRAM compartida** del
+  proceso (5 542): son buffers anclados de CUDA. Con `none`, «VRAM compartida > 0» **no** significa
+  desbordamiento. Lo que impide el desbordamiento en la tanda es el perfil del driver (CP-1), no
+  este contador.
+- **Pendiente de decision (P-13, §10.1)**: `--load-mode` de la tanda y que magnitud se publica.
+
 ### CP-3 — El corpus discrimina
 
 Piloto del corpus con el modelo mas debil del catalogo (`qwen35-2b`) y el mas fuerte
@@ -1180,7 +1260,28 @@ Sirve para reproducir la tanda y para descontar estos intervalos de la quinta me
 
 | # | Inicio UTC | Fin UTC | Duracion estimada / real | Que se midio | llama.cpp | llama-swap | `--load-mode` | CP-1..CP-4 | Anuladas |
 | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
-| — | — | — | — | *(sin ejecutar)* | — | — | — | — | — |
+| 1 | 2026-09-14 19:24 | 2026-09-14 19:51 | ~60 min / 27 min | Tarea 18: entorno, CP-1, CP-2, CP-2b (sin tanda) | b10909 (`a2878d30d`, CUDA 13.3) | v255 (`7761aa1`), puerto 9595 | `mmap` y `none` (CP-2b los compara) | CP-1 pasa (tras un veto: perfil en la ruta equivocada), CP-2 pasa, CP-2b ve expertos solo con `none` y en diferencia (P-13) | ninguna |
+
+Desviaciones de §1.4 en la sesion 1, que la tanda tiene que resolver antes de empezar:
+
+- **RAM libre 17,9 GB, no >= 24**: la maquina tiene **32 GB**, no ~62 como dice §1.1
+  (`Win32_PhysicalMemory`: 2 x 16 GB). El presupuesto de pesos de §1.1 esta mal y hay que rehacerlo.
+- **`nvidia-smi --query-compute-apps` nunca sale vacio en WDDM**: lista explorer, WebView2,
+  PowerToys... El punto 2 se reescribe como «ningun proceso de computo ajeno» (sin `llama-server`
+  ni otro cargador vivo).
+- **Produccion sin perfil del driver entre ~19:40 y 19:50 UTC** (con el daemon parado, sin uso). Al
+  cerrar se devolvio a `D:\Projects\llms\llamacpp\llama-server.exe` y **se midio**: b10909 carga
+  desbordando 6 056 MiB, y b9925 **no carga** (tres intentos, 19:50-19:52, sale a los 5-6 s con
+  `0xC0000005` al crear el contexto). Esta vez el log **no** trae la linea `cudaMalloc failed`
+  —el proceso muere antes de escribirla—, asi que la prueba es por contraste: a las 19:42, sin
+  perfil, **el mismo binario con los mismos argumentos cargo**, y lo unico que cambio despues fue el
+  perfil. Daemon arrancado a las 19:51; `local_status` lo da arriba, sin modelos cargados.
+- `%APPDATA%\llama.cpp\config.ini` **no existe** (comprobado al empezar y al cerrar): nada que
+  respaldar ni restaurar.
+- b10909 (`D:\Projects\llms\llamacpp-b10909`), llama-swap v255 (`D:\Projects\llms\llama-swap-v255`) y
+  `llama-swap-pruebas.yaml` **se quedan en disco** para la tarea 19; el perfil **no**: la tarea 19
+  tiene que moverlo a b10909 y volver a medirlo, porque la NVIDIA App solo admite una entrada por
+  nombre de fichero.
 
 ---
 
@@ -1214,6 +1315,14 @@ Sirve para reproducir la tanda y para descontar estos intervalos de la quinta me
   la maxima del rol; (c) dar mas terminos a los casos de uno o dos. La (c) toca el corpus y la (b) la
   regla: **las dos se deciden con la salida de CP-3 delante y antes de la tanda**, nunca despues de
   ver quien gana, que es como se ajusta una regla al resultado que se queria.
+- **P-13 — abierta (2026-09-14).** CP-2b (tarea 18) mostro que con `--load-mode mmap` ningun
+  contador privado ve los expertos en RAM, y que con `none` los ve solo como **`privada − VRAM
+  dedicada`**, porque en WDDM la privada incluye la VRAM reservada. Hay que decidir, antes de la
+  tanda: (a) `--load-mode` de la tanda — la evidencia apunta a `none`; (b) que magnitud se publica
+  como «RAM del proceso» — `privada − VRAM dedicada`, con privada y working set al lado; (c) si esa
+  resta la hace `analizar_benchmark.py` (codigo nuevo, con su test) o solo la hoja de resultados.
+  Y un aviso para §3.2: con `none` la **VRAM compartida** del proceso sube por los buffers anclados
+  de CUDA, asi que no sirve como senal de desbordamiento; esa senal es el OOM que da el perfil.
 
 ---
 
diff --git a/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml b/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
new file mode 100644
index 0000000..7e12810
--- /dev/null
+++ b/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
@@ -0,0 +1,63 @@
+# llama-swap de PRUEBAS para F2 (protocolo-f2.md §1.2, tarea 18). Produccion no se toca:
+# ejecutable, puerto y config propios. Se lanza con:
+#   D:\Projects\llms\llama-swap-v255\llama-swap.exe --config <este fichero> --listen 127.0.0.1:9595
+#
+# Flags comunes, y por que:
+# - `--fit off -ngl 99`: b10909 trae `--fit on` y `-ngl auto` por defecto, que reducen capas hasta
+#   que el modelo quepa. Con eso CP-1 «pasaria» cargando a medias y ninguna medida seria del modelo
+#   entero. Fijarlo es la condicion para que el perfil del driver sea lo unico que decide.
+# - `--cache-ram 1024 -np 1`: §1.2.
+# - `--load-mode` explicito: decide si el contador de RAM privada ve los pesos (§3.1, CP-2b).
+# Sin `groups`: llama-swap descarga el anterior al cambiar, y asi hay un solo llama-server vivo (§1.4).
+
+macros:
+  server: >-
+    D:\Projects\llms\llamacpp-b10909\llama-server.exe --port ${PORT} --host 127.0.0.1
+    --fit off -ngl 99 --cache-ram 1024 -np 1
+
+models:
+  # CP-1 negativo: cabe y debe cargar normal.
+  gemma3-4b:
+    cmd: >-
+      ${server} --load-mode mmap
+      --model D:\Projects\llms\models\gemma3-4b\gemma-3-4b-it-Q4_K_M.gguf
+      --ctx-size 8192 --reasoning off
+  # CP-1 positivo: 8,4 GB de pesos + ~24 GiB de KV f16 a 131072 tokens. No cabe en 16 GB.
+  # Sustituye al Qwen3.5-122B del protocolo, que no esta en disco (decision del usuario, 2026-09-14).
+  cp1-no-cabe:
+    cmd: >-
+      ${server} --load-mode mmap
+      --model D:\Projects\llms\models\qwen25-coder-14b\Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf
+      --ctx-size 131072 --cache-type-k f16 --cache-type-v f16
+  # CP-2: dos densos de tamano muy distinto.
+  qwen35-2b:
+    cmd: >-
+      ${server} --load-mode mmap
+      --model D:\Projects\llms\models\Qwen3.5-2B\Qwen3.5-2B-UD-Q8_K_XL.gguf
+      --ctx-size 8192 --reasoning off
+  qwen25-coder-14b:
+    cmd: >-
+      ${server} --load-mode mmap
+      --model D:\Projects\llms\models\qwen25-coder-14b\Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf
+      --ctx-size 8192 --cache-type-k q4_0 --cache-type-v q4_0
+  # CP-2b: el MoE con expertos en GPU (ncmoe 0) y con 12 capas de expertos en RAM, en los dos modos.
+  gptoss-ncmoe0-mmap:
+    cmd: >-
+      ${server} --load-mode mmap -ncmoe 0
+      --model D:\Projects\llms\models\gpt-oss-20b-canary\gpt-oss-20b-MXFP4.gguf
+      --ctx-size 8192
+  gptoss-ncmoe12-mmap:
+    cmd: >-
+      ${server} --load-mode mmap -ncmoe 12
+      --model D:\Projects\llms\models\gpt-oss-20b-canary\gpt-oss-20b-MXFP4.gguf
+      --ctx-size 8192
+  gptoss-ncmoe0-none:
+    cmd: >-
+      ${server} --load-mode none -ncmoe 0
+      --model D:\Projects\llms\models\gpt-oss-20b-canary\gpt-oss-20b-MXFP4.gguf
+      --ctx-size 8192
+  gptoss-ncmoe12-none:
+    cmd: >-
+      ${server} --load-mode none -ncmoe 12
+      --model D:\Projects\llms\models\gpt-oss-20b-canary\gpt-oss-20b-MXFP4.gguf
+      --ctx-size 8192
```

### Mensaje A

```
docs(protocolo): registrar resultados de la tarea 18 y nuevos hallazgos

- Añadir resultados de CP-1, CP-2 y CP-2b al protocolo-f2.md.
- Documentar la necesidad de usar `privada - VRAM dedicada` para medir expertos en RAM.
- Registrar desviaciones de hardware y comportamiento de la NVIDIA App.
- Añadir `llama-swap-pruebas.yaml` para replicar el entorno de pruebas.
```

### Mensaje B

```
docs(protocolo): registrar resultados tarea 18 y config pruebas
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 18

Diff: 3 ficheros, +109 −0

```diff
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/plan.md b/.sdd/changes/delegacion-precisa-y-fiable/plan.md
index 3689bcd..0bc7528 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/plan.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/plan.md
@@ -400,6 +400,13 @@ midio algo sin comprobar antes el instrumento, lo roto era la prueba.
       `privada − VRAM dedicada` por muestra; el presupuesto de uso diario (2 GB de VRAM y 8 GB de RAM
       de reserva) es solo informativo. Tras CP-3 son **5 corridas y ~350 peticiones**, no 3 y ~214
       (§5.2 del protocolo manda).
+    - Estado (2026-09-15): **hecha** (`protocolo-f2.md` §7, «Resultado de la tarea 20»). `long` y
+      `code` sustituyen (pares 15 a 0 cada uno, y los candidatos van al doble de velocidad),
+      `mechanical` no cambia (todo en techo), `vision` caso a caso a favor de Gemma 4 12B. Lo que la
+      tanda obligo a cambiar respecto a este texto: 5 corridas; techo en config aparte con la misma
+      `--label`; razonamiento apagado en los candidatos; umbral de `Shared Usage` 1 024 MiB; latencia
+      sobre casos comunes; perfil del driver tambien para `llama-bench.exe`; y el LUID de la GPU
+      resuelto en cada invocacion porque un reinicio lo reasigna.
 
 21. **Asignacion de roles, y que se transfiere a produccion**
     - Files or modules: `verification.md`, `protocolo-f2.md` §9 y §10
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
index 377583f..f46a38b 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
@@ -1672,6 +1672,53 @@ quedo vivo en la primera pasada —quitar la tolerancia no rompia nada— porque
 promediaba cuatro casos y diluia la diferencia a 0,25, lejos de la banda: el caso de prueba no podia
 distinguir. Se reescribio con un solo caso en el agregado.
 
+#### Resultado de la tarea 20 (2026-09-15): la regla aplicada a la tanda
+
+`analizar_benchmark.py decidir` con el CP-3 del cuarto piloto (`cp3d-*.json`), todos los
+`resultados/tanda-*.jsonl`, `--umbral-shared-mib 1024` y los dos JSON de pares destapados. Informe
+completo en `resultados/decidir-final.md`; la regla la aplica el programa, esto es su lectura.
+
+| Rol | Vigente | Candidato | Veredicto | Criterio | Datos que lo sostienen |
+| --- | --- | --- | --- | --- | --- |
+| `mechanical` | `gemma3-4b` | Gemma 4 E4B | **no se cambia** | empate | los 5 casos en techo (1,0 y 1,0); latencia 516 contra 561 ms, dentro de su banda (387) |
+| `long` | `llama31-8b` | Gemma 4 26B-A4B `-ncmoe 0` | **sustituye** | calidad | pares **15 a 0** (prueba de signos «mejor»); formula 0,5 contra 1,0 en `extraer-uvlock-48k`; latencia 3,0 s contra **1,8 s** (sin `lint-9k`, que el vigente no termino nunca); techo igual (106 092 bytes los dos) |
+| `code` | `qwen25-coder-14b` | Qwen3.6-35B-A3B `-ncmoe 8` | **sustituye** | calidad | pares **15 a 0**; `boilerplate-156` 0,8 contra 1,0; latencia 9,3 s contra **4,6 s**; techo 20 171 contra **157 873 bytes** (el vigente esta limitado a sus 32 768 tokens nativos) |
+| `vision` | `qwen3-vl-8b` | Gemma 4 12B | sin agregado (§7) | caso a caso | `describir-dashboard` mediana 0,75 contra **1,0**; `leer-cifras-dashboard` 0,67 contra **1,0**; latencia peor (4,4 s y 0,5 s contra 6,1 s y 1,2 s) |
+
+**Los votos se comprobaron letra a letra.** El usuario los dio tambien en el chat (15 + 15) y se
+compararon con lo que leyo `destapar`: **0 diferencias**. Y no es un sesgo de posicion: el lado de cada
+modelo esta sorteado, y las letras van 9 A / 6 B en `long` y 8 A / 7 B en `code`, todas al candidato.
+
+**P-15 con datos nuevos: la cobertura de terminos acierta al reves en las explicaciones de codigo.**
+
+| Caso | La metrica prefiere | Acuerdo con la persona | Veredicto |
+| --- | --- | --- | --- |
+| `resumen-md-10k` | 4 | 4 (100 %) | valida |
+| `lint-9k` | 5 | 5 (100 %) | valida |
+| `resumen-changelog-7k` | 5 | 4 (80 %) | valida |
+| `commit-diff-19k` | 5 | 5 (100 %) | valida |
+| `explicar-install-20k` | 4 | **1 (25 %)** | no valida |
+| `explicar-metrics-15k` | 5 | **0 (0 %)** | no valida |
+
+Con esta pareja la metrica coincide en los resumenes y el commit, y en las dos explicaciones de codigo
+prefiere al vigente casi siempre que la persona elige al candidato: la misma forma de fallo que
+`resumen-md-10k` tuvo en P-15 (premiar que se nombren terminos, no que se explique bien). No cambia
+nada de esta decision —esos casos ya los decidian los pares— pero confirma que la cobertura no puede
+volver a decidir texto abierto.
+
+**Salvedades que acompanan al veredicto, no lo cambian:**
+
+- **Gemma 4 26B-A4B no cabe en el presupuesto de uso diario** (§1.1, informativo): 15,1 GB de VRAM
+  pico con `-ncmoe 0`, frente a 14 GB. Con escritorio ocupando VRAM y el perfil activo, esa config puede
+  dar OOM al cargar. El barrido tiene la alternativa medida: `-ncmoe 4` (60,9 tok/s a 33 k, contra 76,9).
+  Decidirlo es de F3, que es donde se sube el catalogo.
+- **Todos los candidatos corren con el razonamiento apagado**, y asi hay que subirlos: piensan por
+  defecto y con los `max_tokens` de produccion devuelven vacio.
+- **Gemma 4 12B necesita `--batch-size 2048 --ubatch-size 2048`** para procesar imagenes.
+- **`vision` se decide sobre dos casos y una sola imagen**, uno inventado (§4.4).
+- **La tanda midio con `n_ctx` de 36 736 en `long`**; produccion corre `llama31-8b` a 16 384, que ya
+  rechaza la entrada real mayor (backlog 1.3). El `n_ctx` de produccion lo fija F3.
+
 ---
 
 ## 8. Scripts: que se toca y que se crea
@@ -1845,6 +1892,14 @@ invocacion. El JSONL sin VRAM se conserva como `resultados/invalida-luid-gemma4-
 `F722` fijo en su contador de `Shared Usage`; hay que corregirlo antes de medir el perfil al devolverlo
 a produccion, o la prueba leera un contador inexistente.
 
+**Sesion 5, setup de medicion desmontado (2026-09-15).** Con la tanda y `vision` medidos, el usuario
+devolvio el perfil del driver a `D:\Projects\llms\llamacpp\llama-server.exe` y se midio por su efecto
+con `medir-perfil-cp1.ps1` (ya resuelve el LUID solo: `F336`): 12:10:02 UTC **b9925 da OOM a los 6,1
+s** (`cudaMalloc` 12 288 MiB, sale con 0xC0000005, esta vez con la linea de OOM en el log); 12:10:12
+**b10909 carga en 13,6 s desbordando 5 985 MiB**. El perfil vuelve a actuar sobre produccion y el
+daemon se arranco despues. La votacion por pares no necesita la maquina. La entrada de
+`llama-bench.exe` en la NVIDIA App queda a criterio del usuario.
+
 **Sesion 5, cierre del setup de medicion.** La tanda termino a las 04:21:01 UTC con llama-swap de
 pruebas y `llama-server` parados. **A las 04:31:35 la tarea `LocalDelegateDaemon` volvio a arrancar
 el daemon de produccion** (y su llama-swap en 9292, con b9925), sin intervencion de la sesion que
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/verification.md b/.sdd/changes/delegacion-precisa-y-fiable/verification.md
index e85c1b2..61b1fec 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/verification.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/verification.md
@@ -649,3 +649,50 @@ al `chore: update version to 0.7.0` del 14B sin mirar el diff, que si sube a 0.7
 
 `uv run pytest -q`: **1081 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios en
 `src`, `scripts` y `tests`. `construir_corpus.py --comprobar`: ok.
+
+## F2: tarea 20, la tanda y el veredicto por rol (2026-09-14 a 2026-09-15)
+
+Sesiones 4 y 5 de §10. PRs #180 (P-13 y P-14), #181 (`n_ctx` y KV medidos), #182 (barrido de
+`-ncmoe`) y #183 (la tanda y las reglas que corrigio), todos mezclados con el CI entero en verde.
+Resultado y salvedades en `protocolo-f2.md` §7 «Resultado de la tarea 20»; informe del programa en
+`resultados/decidir-final.md`.
+
+### El veredicto
+
+| Rol | Veredicto | Lo decide |
+| --- | --- | --- |
+| `mechanical` | no se cambia `gemma3-4b` | todo en techo, empate de latencia |
+| `long` | **Gemma 4 26B-A4B** sustituye a `llama31-8b` | pares 15 a 0; ademas 1,8 s contra 3,0 s |
+| `code` | **Qwen3.6-35B-A3B** sustituye a `qwen25-coder-14b` | pares 15 a 0; techo 157 873 contra 20 171 bytes; mitad de latencia |
+| `vision` | sin agregado; Gemma 4 12B mejor caso a caso | 1,0 y 1,0 contra 0,75 y 0,67 |
+
+### Lo que la maquina obligo a cambiar, con decision del usuario
+
+- **El perfil del driver es por ejecutable**: `llama-bench.exe` desbordaba sin avisar y el primer
+  barrido no valia (Qwen3.6 con `-ncmoe 4` corria a 91 tok/s y no cabe). Entrada propia, medida por su
+  efecto con `-v` y un control negativo.
+- **Los cuatro candidatos piensan por defecto** y devolvian vacio: corren con `--reasoning-effort off`.
+- **Techo en config aparte con la misma `--label`**: con el `n_ctx` de calidad los sondeos median la
+  ventana. §6 compara `n_ctx` por tipo de caso.
+- **Umbral de `Shared Usage` 1 024 MiB** (estaba en 0 sin calibrar y nada era concluyente).
+- **Latencia sobre casos comunes**: el vigente de `long` no termino nunca `lint-9k` y vetaba al
+  candidato.
+- **Gemma 4 12B necesita `--ubatch-size 2048`**, y **un reinicio de Windows reasigna el LUID de la
+  GPU**: el script ya no lo fija, y el del perfil lo resuelve solo.
+
+### Lo que se probo al reves
+
+- Mutantes muertos, cada uno por su assert: resta de picos y VRAM ausente como cero en la RAM del host;
+  los dos limites del presupuesto de uso diario; §6 sin agrupar por tipo, `_pico` contando el techo y
+  §6 solo con calidad; y la latencia sobre todos los casos.
+- **Cada fallo se diagnostico por reproduccion y no por suposicion.** Dos hipotesis propias cayeron: que
+  el 502 de `vision` fuera el `mmproj` o `--load-mode none` (era el `ubatch`), y que la falta de VRAM
+  fuera un `-1` de `typeperf` (era el LUID).
+- **Los 30 votos se compararon letra a letra** con los que el usuario dio en el chat: 0 diferencias, y
+  las letras no son todas iguales (9/6 y 8/7), asi que no es un sesgo de posicion.
+- El perfil del driver se midio al montar y al desmontar: al cerrar, b9925 da OOM y b10909 desborda
+  5 985 MiB, y el daemon volvio a arrancar.
+
+### Suite
+
+`uv run pytest -q`: **1119 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios.
```

### Mensaje A

```
docs(delegacion): registrar resultados de la tarea 20 y veredictos

- Añadir el veredicto de la tanda de pruebas en `plan.md` y `protocolo-f2.md`.
- Documentar la sustitución de modelos para los roles `long` y `code`.
- Detallar las salvedades técnicas (VRAM, razonamiento, LUID y `ubatch-size`).
- Actualizar `verification.md` con el resumen de la tarea 20 y la suite de pruebas.
```

### Mensaje B

```
docs: registrar veredicto tarea 20 y ajustes de tanda
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 19

Diff: 4 ficheros, +180 −12

```diff
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
index fb94483..23a28d5 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
@@ -941,6 +941,49 @@ Este es el fallo 5 de julio, que la primera version de este protocolo no cerraba
   densidad varia mas del doble segun el contenido: 48 000 chars de `uv.lock` no son los mismos tokens
   que 48 000 de Markdown, y este repo ya tiene documentada esa trampa. Un `n_ctx` estimado en chars
   convierte el caso mayor en `rechazo_por_contexto` y §6 tumba el rol entero por un error de unidades.
+- **Dos configs por modelo, decision del usuario (2026-09-14).** Con `n_ctx` fijado por el caso de
+  calidad mayor, los sondeos de techo (26 353 y 47 181 tokens) darian `rechazo_por_contexto` en los
+  dos modelos siempre: medirian la ventana configurada, no el modelo, y el primer desempate de §7
+  seria un control que no puede dar un resultado distinto. Asi que cada modelo de `long` y `code`
+  tiene **una config de calidad** —`n_ctx` = el **maximo por caso de tokens de prompt + su
+  `max_tokens`**, en el mayor de los dos modelos, + 10 %, redondeado hacia arriba a multiplo de 512—
+  y **una config de techo con `n_ctx` 65 536**, igual para vigente y
+  candidato. Las dos corren con la **misma `--label`** (el runner la separa del `--model` de
+  llama-swap y del `--context-size`); §6 compara `n_ctx` y `--load-mode` **dentro de cada tipo de
+  caso**, y la memoria publicada sale solo de los casos de calidad (`analizar_benchmark.py`). Cada
+  config tiene su propio presupuesto de KV y su barrido.
+- **Tokens medidos con el vocabulario de cada modelo** (`llama-tokenize` de b10909, `system` +
+  `user` renderizados como los manda el runner; la plantilla de chat suma unas decenas, que cubre el
+  10 %). Tres trampas que la medida destapo, y que una estimacion en chars no habria visto:
+  - **El caso mayor en chars no es el mayor en tokens**: en `code`, `commit-diff-19k` (19 041 chars)
+    da mas tokens de prompt que `explicar-install-20k` (20 000).
+  - **El caso con mas prompt no es el que mas contexto pide**: `delegar-56` tiene 75 tokens y
+    `max_tokens` 2 048, el triple de lo que pide `extraer-toml-2k`. La primera redaccion de esta
+    regla («tokens del caso mayor + su `max_tokens`») lo habria dejado fuera.
+  - **El vocabulario del candidato cambia el rol entero**: con Gemma 4, `extraer-uvlock-48k` son
+    **32 822** tokens, un 45 % mas que con `llama31-8b`, y el sondeo de `long` (29 241) queda **por
+    debajo** del caso de calidad. Con ese vocabulario el sondeo no sondea nada que la calidad no
+    pida ya; se escribe junto al veredicto de techo de `long`.
+
+  Control de la medida: Gemma 3 4B, Gemma 4 E4B y Gemma 4 26B-A4B dan conteos identicos (698 y 646
+  en los dos casos mayores de `mechanical`: comparten vocabulario) y `llama31-8b` da otros (685 y
+  649), asi que la herramienta distingue vocabularios y no devuelve siempre lo mismo.
+
+  | Rol | Modelo | Caso que mas contexto pide (prompt + `max_tokens`) | Caso mayor en prompt | Sondeo de techo | `n_ctx` de calidad |
+  | --- | --- | --- | --- | --- | --- |
+  | `mechanical` | `gemma3-4b` y Gemma 4 E4B (mismo vocabulario) | `delegar-56`: 75 + 2 048 = 2 123 | `extraer-toml-2k`: 698 | — | **2 560** |
+  | `long` | `llama31-8b` | `extraer-uvlock-48k`: 22 607 + 512 = 23 119 | el mismo | `techo-resumen-103k`: 26 353 | |
+  | `long` | Gemma 4 26B-A4B | `extraer-uvlock-48k`: 32 822 + 512 = 33 334 | el mismo | `techo-resumen-103k`: 29 241 | **36 736** |
+  | `code` | `qwen25-coder-14b` | `explicar-install-20k`: 5 484 + 700 = 6 184 | `commit-diff-19k`: 5 757 | `techo-commit-156k`: 47 181 | |
+  | `code` | Qwen3.6-35B-A3B | `commit-diff-19k`: 5 996 + 256 = 6 252 | el mismo | `techo-commit-156k`: 47 393 | **7 168** |
+
+  Config de techo: **65 536** en `long` y `code`, que cubre los sondeos medidos. `vision` no entra en
+  esta cuenta: sus tokens de imagen los pone el `mmproj`, no el texto.
+
+  **Hallazgo de produccion, anotado para F3 (decision del usuario):** `llama31-8b` corre en
+  produccion con `--ctx-size 16384`, asi que `extraer-uvlock-48k` —la entrada real mayor que
+  `MAX_CHARS` de `long` deja pasar— **da rechazo por contexto hoy**. El tope esta en chars y la
+  ventana en tokens. No se corrige en plena ventana de F1 (backlog, punto 1.3).
 - **Si vigente y candidato no pueden compartir `n_ctx`** —el candidato tiene un techo menor—, se mide
   a los dos con el menor de los dos y se escribe. Lo que no vale es compararlos a contextos distintos.
 - **`rechazo_por_contexto` es una clase de resultado propia**, distinta de `descartada` y distinta de
@@ -1372,6 +1415,33 @@ anotan aqui porque son parte de la identidad de la medida, no del arranque.
 Columnas que se rellenan al fijar el entorno: `n_ctx`, VRAM de pesos, VRAM de KV, `-ncmoe` elegido,
 `--load-mode`.
 
+#### Presupuesto de KV medido (tarea 20, 2026-09-14)
+
+Medido cargando cada config en b10909 con `-v --load-mode none --fit off -ngl 99 -np 1`, sumando las
+lineas `llama_kv_cache: size =` (con SWA salen dos) y matando el proceso; un solo `llama-server` vivo
+cada vez. En los MoE se carga con `-ncmoe 99`: el KV no depende de donde vivan los expertos, y asi la
+medida no depende de si los pesos caben. KV `f16` salvo `qwen25-coder-14b`, que va `q4_0/q4_0` como en
+produccion. Candidatos descargados de unsloth y verificados contra el sha256 que publica Hugging Face.
+MiB.
+
+| Rol | Config | `n_ctx` | KV | Pesos en GPU | Pesos en RAM | Computo GPU | Nota |
+| --- | --- | --- | --- | --- | --- | --- | --- |
+| `mechanical` | `gemma3-4b` | 2 560 | 224 | 2 368 | 525 | 78 | SWA: 50 + 174 |
+| `mechanical` | Gemma 4 E4B Q4_K_M | 2 560 | 80 | 2 884 | **2 208** | 105 | la familia E deja embeddings por capa en RAM aun con `-ngl 99` |
+| `long` | `llama31-8b` calidad | 36 736 | **4 608** | 4 403 | 282 | 144 | denso sin SWA: el contexto le cuesta mas que los pesos |
+| `long` | `llama31-8b` techo | 65 536 | **8 192** | 4 403 | 282 | 172 | cabe: ~12,8 GiB |
+| `long` | Gemma 4 26B-A4B UD-IQ4_XS calidad | 36 736 | 1 020 | (MoE) 2 459 | 11 241 | 412 | entero en GPU serian ~13,4 GiB de pesos + KV + computo: al limite, lo decide el barrido |
+| `long` | Gemma 4 26B-A4B techo | 65 536 | 1 580 | (MoE) 2 459 | 11 241 | 440 | |
+| `code` | `qwen25-coder-14b` calidad | 7 168 | 378 | 8 148 | 418 | 118 | `q4_0/q4_0` |
+| `code` | `qwen25-coder-14b` techo | 65 536 | 3 456 | 8 148 | 418 | 360 | cabe: ~11,7 GiB |
+| `code` | Qwen3.6-35B-A3B UD-IQ4_XS calidad | 7 168 | 140 | (MoE) 1 921 | **14 977** | 286 | atencion lineal en la mayoria de capas: el KV casi no cuenta. ~16,9 GiB de pesos: **no cabe entero en GPU**, el barrido decide cuantos expertos suben; con `none` los ~15 GiB en RAM caben justos en los ~19 GB libres |
+| `code` | Qwen3.6-35B-A3B techo | 65 536 | 1 280 | (MoE) 1 921 | 14 977 | 450 | |
+| `vision` | `qwen3-vl-8b` | 8 192 | 1 152 | 4 455 | 334 | 500 | con `mmproj` |
+| `vision` | Gemma 4 12B Q4_K_M | 8 192 | 608 | 6 777 | 540 | 203 | con `mmproj-F16`; `n_ctx` de vision = el de produccion |
+
+Las configs de los densos estan en `llama-swap-pruebas.yaml` (`t-*`). Las de los dos MoE esperan al
+barrido de `-ncmoe` (§5.1 paso 5).
+
 Descarga: los **~85 GB** de la lista corta del vault menos los ~5 GB de los candidatos de `fast`, que salen de la tanda, mas los **36,6 GB** del modelo que no cabe de CP-1: **~117 GB** en total, dentro de los 400 GB libres. La cifra se contrasta al descargar; no se deriva de nada mas. `gpt-oss-20b` ya esta. **Qwen3.5-122B-A10B UD-IQ2_XXS
 (36,6 GB) no es candidato**: entra solo como el modelo que no cabe de CP-1.
 
diff --git a/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml b/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
index 6bd3320..70ef401 100644
--- a/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
+++ b/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
@@ -81,3 +81,51 @@ models:
       ${server} --load-mode none -ncmoe 12
       --model D:\Projects\llms\models\gpt-oss-20b-canary\gpt-oss-20b-MXFP4.gguf
       --ctx-size 8192
+
+  # --- Tanda (tarea 20) ---------------------------------------------------------------------------
+  # Todo con --load-mode none (P-13). n_ctx de calidad = max por caso de (tokens de prompt medidos +
+  # max_tokens) en el mayor de los dos modelos del rol, +10 %, a multiplo de 512; techo a 65 536 en
+  # long y code (protocolo §3.5). Flags de cada vigente como en produccion; KV f16 salvo el coder.
+  # Pendientes del barrido de -ncmoe: Gemma 4 26B-A4B y Qwen3.6-35B-A3B.
+  t-qwen25-coder-14b:
+    cmd: >-
+      ${server} --load-mode none
+      --model D:\Projects\llms\models\qwen25-coder-14b\Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf
+      --ctx-size 7168 --cache-type-k q4_0 --cache-type-v q4_0
+  t-gemma3-4b:
+    cmd: >-
+      ${server} --load-mode none
+      --model D:\Projects\llms\models\gemma3-4b\gemma-3-4b-it-Q4_K_M.gguf
+      --ctx-size 2560 --reasoning off
+  t-gemma4-e4b:
+    cmd: >-
+      ${server} --load-mode none
+      --model D:\Projects\llms\models\gemma4-e4b\gemma-4-E4B-it-Q4_K_M.gguf
+      --ctx-size 2560 --reasoning off
+  t-llama31-8b:
+    cmd: >-
+      ${server} --load-mode none
+      --model D:\Projects\llms\models\llama31-8b\Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
+      --ctx-size 36736
+  t-llama31-8b-techo:
+    cmd: >-
+      ${server} --load-mode none
+      --model D:\Projects\llms\models\llama31-8b\Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
+      --ctx-size 65536
+  t-qwen25-coder-14b-techo:
+    cmd: >-
+      ${server} --load-mode none
+      --model D:\Projects\llms\models\qwen25-coder-14b\Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf
+      --ctx-size 65536 --cache-type-k q4_0 --cache-type-v q4_0
+  t-qwen3-vl-8b:
+    cmd: >-
+      ${server} --load-mode none
+      --model D:\Projects\llms\models\qwen3-vl-8b\Qwen3VL-8B-Instruct-Q4_K_M.gguf
+      --mmproj D:\Projects\llms\models\qwen3-vl-8b\mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf
+      --ctx-size 8192
+  t-gemma4-12b:
+    cmd: >-
+      ${server} --load-mode none
+      --model D:\Projects\llms\models\gemma4-12b\gemma-4-12b-it-Q4_K_M.gguf
+      --mmproj D:\Projects\llms\models\gemma4-12b\mmproj-F16.gguf
+      --ctx-size 8192
diff --git a/scripts/analizar_benchmark.py b/scripts/analizar_benchmark.py
index 311ae7b..f8a613a 100755
--- a/scripts/analizar_benchmark.py
+++ b/scripts/analizar_benchmark.py
@@ -473,13 +473,20 @@ def validar_tanda(
             if not _caso(cfg, cid, corpus).calidades:
                 motivos.append(f"{cfg.selector}: {cid} sin ninguna puntuacion valida")
     registros = [r for cfg in configs for r in cfg.registros if r.get("role") == rol]
-    for clave, nombre in (("context_size", "n_ctx"), ("load_mode", "--load-mode")):
-        valores = {(r.get("variant") or {}).get(clave) for r in registros}
-        if None in valores:
-            # Sin declararlo no se puede comprobar, y un control que no puede fallar no es control.
-            motivos.append(f"{nombre} sin declarar en alguna corrida")
-        elif len(valores) > 1:
-            motivos.append(f"{nombre} distinto entre corridas: {sorted(map(str, valores))}")
+    # Por tipo de caso (§3.5, decision del usuario 2026-09-14): la calidad corre con el n_ctx del caso
+    # mayor y los sondeos de techo en otra config con mas contexto, o medirian la ventana y no el
+    # modelo. Lo que no vale es que vigente y candidato difieran DENTRO de un mismo tipo.
+    for kind in sorted({r.get("kind") for r in registros}, key=str):
+        del_tipo = [r for r in registros if r.get("kind") == kind]
+        for clave, nombre in (("context_size", "n_ctx"), ("load_mode", "--load-mode")):
+            valores = {(r.get("variant") or {}).get(clave) for r in del_tipo}
+            if None in valores:
+                # Sin declararlo no se puede comprobar, y un control que no puede fallar no es control.
+                motivos.append(f"{nombre} sin declarar en alguna corrida de {kind}")
+            elif len(valores) > 1:
+                motivos.append(
+                    f"{nombre} distinto entre corridas de {kind}: {sorted(map(str, valores))}"
+                )
     for cfg in configs:
         propios = [r for r in cfg.registros if r.get("role") == rol]
         primeras = [
@@ -693,7 +700,9 @@ def _fmt(valor: Any, decimales: int = 3) -> str:
 def _pico(config: Config, rol: str, ruta: tuple[str, ...]) -> Any:
     valores = []
     for r in config.registros:
-        if r.get("role") != rol:
+        # Solo calidad: el sondeo de techo corre con mas contexto y su KV inflaria la memoria de la
+        # config que se decide (§3.5).
+        if r.get("role") != rol or r.get("kind") != "calidad":
             continue
         valor: Any = r
         for clave in ruta:
diff --git a/tests/test_analisis_benchmark.py b/tests/test_analisis_benchmark.py
index af8d58e..a225a65 100644
--- a/tests/test_analisis_benchmark.py
+++ b/tests/test_analisis_benchmark.py
@@ -397,16 +397,57 @@ def test_un_caso_sin_ninguna_puntuacion_valida_no_es_concluyente():
 @pytest.mark.parametrize(
     ("kw", "motivo"),
     [
-        ({"ctx": 8192}, "n_ctx distinto entre corridas: ['16384', '8192']"),
-        ({"load": "mmap"}, "--load-mode distinto entre corridas: ['mmap', 'none']"),
-        ({"load": None}, "--load-mode sin declarar en alguna corrida"),
+        ({"ctx": 8192}, "n_ctx distinto entre corridas de {}: ['16384', '8192']"),
+        ({"load": "mmap"}, "--load-mode distinto entre corridas de {}: ['mmap', 'none']"),
+        ({"load": None}, "--load-mode sin declarar en alguna corrida de {}"),
     ],
 )
 def test_contexto_o_load_mode_distintos_o_sin_declarar_no_son_concluyentes(kw, motivo):
+    # `_tanda` aplica el cambio a los casos de calidad y al sondeo: sale un motivo por tipo.
     d = _decidir(
         _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0), **kw)
     )
-    assert (d["veredicto"], d["motivos"]) == ("no_concluyente", [motivo])
+    assert (d["veredicto"], d["motivos"]) == (
+        "no_concluyente",
+        [motivo.format("calidad"), motivo.format("techo")],
+    )
+
+
+def _techo_con_ctx(registros, ctx):
+    for r in registros:
+        if r["kind"] == "techo":
+            r["variant"]["context_size"] = ctx
+    return registros
+
+
+def test_el_sondeo_de_techo_corre_con_su_propio_n_ctx_sin_tumbar_la_tanda():
+    # §3.5, dos configs por modelo: calidad a 16 384 y techo a 65 536 en los dos es concluyente.
+    d = _decidir(
+        _techo_con_ctx(_tanda("vigente", "long", TERCIO), 65536)
+        + _techo_con_ctx(_tanda("candidato", "long", (1.0, 1.0, 1.0)), 65536)
+    )
+    assert d["veredicto"] == "sustituye"
+
+
+def test_el_n_ctx_del_techo_tiene_que_coincidir_entre_vigente_y_candidato():
+    d = _decidir(
+        _techo_con_ctx(_tanda("vigente", "long", TERCIO), 65536)
+        + _tanda("candidato", "long", (1.0, 1.0, 1.0))
+    )
+    assert (d["veredicto"], d["motivos"]) == (
+        "no_concluyente",
+        ["n_ctx distinto entre corridas de techo: ['16384', '65536']"],
+    )
+
+
+def test_la_memoria_publicada_sale_solo_de_los_casos_de_calidad():
+    # El KV de la config de techo (65 536) no puede inflar la memoria de la config que se decide.
+    gib = 1024**3
+    registros = _tanda("candidato", "long", (1.0, 1.0, 1.0))
+    for r in registros:
+        r["resources"]["vram_dedicated_bytes_peak"] = (9 if r["kind"] == "techo" else 1) * gib
+    cfg = analizar.cargar_config(registros, analizar.Selector.parse("candidato"))
+    assert analizar._pico(cfg, "long", ("resources", "vram_dedicated_bytes_peak")) == gib
 
 
 def test_shared_usage_que_crece_tira_cp1_y_no_solo_la_corrida():
```

### Mensaje A

```
docs(protocolo): definir dos configs por modelo y medir presupuesto KV
```

### Mensaje B

```
docs(protocolo): actualizar protocolo de medición y presupuesto KV

- Implementar dos configuraciones por modelo: una de calidad y otra de techo.
- Definir `n_ctx` de calidad basado en el caso de mayor demanda de tokens.
- Establecer `n_ctx` de techo en 65 536 para roles `long` y `code`.
- Ajustar `analizar_benchmark.py` para validar consistencia por tipo de caso.
- Asegurar que la memoria publicada provenga solo de los casos de calidad.
- Añadir tabla de presupuesto de KV medido y nuevos modelos al catálogo.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 20

Diff: 6 ficheros, +145 −8

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 888fbaf..2a0f3a0 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,17 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+### Fixed
+- **Una `~/.codex/config.toml` reescrita por otro programa rompía Codex al reinstalar.** El plugin
+  de JetBrains, al añadir su servidor, indenta el fichero entero y se come los comentarios, marcador
+  de cierre incluido. La búsqueda de `[mcp_servers.local-delegate]` exigía la cabecera al principio
+  de la línea: `doctor` daba la entrada por ausente con Codex funcionando, e `install`/`update`
+  añadían una segunda tabla con el mismo nombre —TOML inválido, y Codex sin cargar ningún MCP—.
+  Ahora se acepta la sangría. Y la entrada ya no se quita emparejando marcadores: un `begin`
+  huérfano se habría emparejado con el `end` del bloque nuevo y la siguiente reinstalación habría
+  borrado todo lo de en medio. Se quita la tabla por su nombre y las líneas de marcador sueltas.
+  `doctor` da `[ OK ]` con el marcador de apertura, y dice cuándo falta el de cierre.
+
 ## [0.31.3] - 2026-09-22
 
 ### Fixed
diff --git a/docs/wiki/Integration-install.md b/docs/wiki/Integration-install.md
index cf8093c..d2ee1f7 100644
--- a/docs/wiki/Integration-install.md
+++ b/docs/wiki/Integration-install.md
@@ -206,7 +206,7 @@ local-delegate doctor --home /tmp/x  # diagnostica contra un HOME simulado (solo
 | Andamiaje | skill delegacion-local | la skill **en cada cliente al que se le escribe**: `~/.claude/skills/delegacion-local/SKILL.md` y `~/.config/opencode/skill/delegacion-local/`. Mirar solo la de Claude Code daba un `[ OK ]` con la de opencode borrada |
 | Andamiaje | memoria global | el bloque entre marcadores en `CLAUDE.md` y `AGENTS.md` |
 | Andamiaje | MCP en Claude Code | la entrada `local-delegate` en `~/.claude.json` |
-| Andamiaje | MCP en Codex | la sección `[mcp_servers.local-delegate]` de `~/.codex/config.toml` |
+| Andamiaje | MCP en Codex | la sección `[mcp_servers.local-delegate]` de `~/.codex/config.toml`, **también con sangría**: otros programas reescriben ese fichero a su manera (el plugin de JetBrains lo indenta entero y se come los comentarios). Con el marcador de apertura es nuestra y `[ OK ]`, aunque falte el de cierre; sin marcadores, `warn` y no se pisa |
 | Andamiaje | MCP en opencode | la clave `mcp.local-delegate` de `~/.config/opencode/opencode.json` **o** `opencode.jsonc` — opencode lee los dos y los fusiona |
 | Servicios | daemon | `http://127.0.0.1:9393/api/daemon` (versión y pid), y si sirve una versión **distinta de la instalada** |
 | Servicios | backend | `BASE_URL/models` |
diff --git a/src/local_delegate/checks.py b/src/local_delegate/checks.py
index d713404..402076d 100644
--- a/src/local_delegate/checks.py
+++ b/src/local_delegate/checks.py
@@ -905,9 +905,17 @@ def _probe_mcp_codex(ctx: Context) -> Result:
     if not section:
         return Result(MISSING, f"sin [mcp_servers.{install.SERVER_NAME}] en {path}", INSTALL_HINT)
     kind = _codex_mode(section.group(0))
-    managed = _has_block(text, install.TOML_BEGIN, install.TOML_END)
-    if not managed:
+    if install.TOML_BEGIN not in text:
         return Result(WARN, f"entrada {kind} en {path}, pero puesta a mano (sin marcadores)")
+    # El de apertura basta para saber que es nuestra. Si falta el de cierre es que otro programa
+    # reescribió el fichero —así lo dejó el plugin de JetBrains—: Codex la carga igual, e `install`
+    # la reescribe entera sin emparejar marcadores, así que no hay nada roto que avisar.
+    if not _has_block(text, install.TOML_BEGIN, install.TOML_END):
+        return Result(
+            OK,
+            f"bloque gestionado en {path} ({kind}); otro programa reescribió el fichero y se "
+            "llevó el marcador de cierre",
+        )
     return Result(OK, f"bloque gestionado en {path} ({kind})")
 
 
diff --git a/src/local_delegate/install.py b/src/local_delegate/install.py
index e7266ac..ccf385e 100644
--- a/src/local_delegate/install.py
+++ b/src/local_delegate/install.py
@@ -564,22 +564,45 @@ def codex_mcp_block(entry: dict) -> str:
     return "\n".join(lines)
 
 
+# Con sangría opcional delante de cada cabecera, y no es cosmético: otros programas reescriben este
+# fichero a su manera. El 2026-09-22 el plugin de JetBrains añadió su servidor, indentó TODO el
+# fichero dos espacios y se comió los comentarios. Con `^\[` a secas la entrada dejaba de verse:
+# `doctor` la daba por ausente con Codex funcionando, e `install`/`update` añadían una segunda
+# `[mcp_servers.local-delegate]` —TOML inválido, y Codex, sin poder cargar su config, se quedaba
+# sin NINGÚN MCP—.
 _CODEX_SECTION_RE = re.compile(
-    r"(?ms)^\[mcp_servers\." + re.escape(SERVER_NAME) + r"(?:\.[^\]]+)?\]\n.*?(?=^\[|\Z)"
+    r"(?ms)^[ \t]*\[mcp_servers\."
+    + re.escape(SERVER_NAME)
+    + r"(?:\.[^\]]+)?\][ \t]*\n.*?(?=^[ \t]*\[|\Z)"
 )
+# Las líneas de marcador, estén donde estén y con la sangría que tengan.
+_CODEX_MARKER_RE = re.compile(
+    r"(?m)^[ \t]*(?:" + re.escape(TOML_BEGIN) + "|" + re.escape(TOML_END) + r")[ \t]*(?:\n|\Z)"
+)
+
+
+def _strip_codex_mcp(text: str) -> str:
+    """Quita nuestra entrada y nuestros marcadores, sin emparejar marcadores.
+
+    Emparejar (`remove_block`) es peligroso aquí: si otro programa se come el marcador de cierre,
+    el `begin` huérfano se emparejaría con el `end` del bloque que escribiéramos después, y la
+    siguiente reinstalación borraría todo lo que hubiera entre los dos —las entradas de otros
+    servidores, los proyectos—. El bloque gestionado es solo nuestra tabla, así que basta con
+    quitarla por su nombre y borrar las líneas de marcador que queden sueltas.
+    """
+    text = _CODEX_SECTION_RE.sub("", text)
+    return _CODEX_MARKER_RE.sub("", text)
 
 
 def upsert_codex_mcp(text: str, block: str) -> str:
     """Reemplaza cualquier entrada previa de local-delegate (gestionada o a mano)."""
-    text = remove_block(text, TOML_BEGIN, TOML_END)
-    text = _CODEX_SECTION_RE.sub("", text).rstrip()
+    text = _strip_codex_mcp(text).rstrip()
     managed = f"{TOML_BEGIN}\n{block}\n{TOML_END}"
     return (text + "\n\n" if text else "") + managed + "\n"
 
 
 def remove_codex_mcp(text: str) -> str:
-    text = remove_block(text, TOML_BEGIN, TOML_END)
-    return _CODEX_SECTION_RE.sub("", text).strip() + "\n"
+    return _strip_codex_mcp(text).strip() + "\n"
 
 
 # --- Entrada del servidor MCP en opencode ------------------------------------
diff --git a/tests/test_checks.py b/tests/test_checks.py
index d8fa076..81ce3f3 100644
--- a/tests/test_checks.py
+++ b/tests/test_checks.py
@@ -1404,3 +1404,30 @@ def test_falta_un_script_empaquetado_aunque_no_se_registre(tmp_path):
     result = result_for("scaffold.hook_files", make_ctx(home))
     assert result.status == checks.WARN
     assert "hook_common.py" in result.detail
+
+
+def test_codex_reescrito_por_otro_programa_no_es_missing(tmp_path):
+    """Indentado y sin marcador de cierre, como lo dejó el plugin de JetBrains: Codex lo carga.
+
+    Darlo por ausente no era solo un aviso falso: `update` lo «reparaba» añadiendo otra entrada.
+    """
+    home = make_home(tmp_path)
+    (home / ".codex" / "config.toml").write_text(
+        '  # local-delegate:begin\n  [mcp_servers.local-delegate]\n    url = "http://127.0.0.1:9393/mcp"\n\n'
+        '  [mcp_servers.pycharm]\n    url = "http://127.0.0.1:64342/sse"\n',
+        encoding="utf-8",
+    )
+    result = result_for("scaffold.mcp_codex", make_ctx(home))
+    assert result.status == checks.OK, result.detail
+    assert "http" in result.detail
+    assert "cierre" in result.detail
+
+
+def test_codex_indentado_sin_marcadores_sigue_siendo_de_otro(tmp_path):
+    """Sin el de apertura no es nuestra, con sangría o sin ella: `warn`, y `update` no la pisa."""
+    home = make_home(tmp_path)
+    (home / ".codex" / "config.toml").write_text(
+        '  [mcp_servers.local-delegate]\n    command = "uvx"\n', encoding="utf-8"
+    )
+    result = result_for("scaffold.mcp_codex", make_ctx(home))
+    assert result.status == checks.WARN
diff --git a/tests/test_install.py b/tests/test_install.py
index 6204e06..710602d 100644
--- a/tests/test_install.py
+++ b/tests/test_install.py
@@ -614,3 +614,71 @@ def test_enable_read_hook_deja_TAMBIEN_el_hook_de_shell_encendido(tmp_path, monk
     # instalado ARRANCA, importa a su vecino y decide, que es donde estaba el agujero.
     assert proceso.stdout.strip() == "", proceso.stdout
     assert "Traceback" not in proceso.stderr
+
+
+# Tal como dejó `~/.codex/config.toml` el plugin de JetBrains el 2026-09-22: todo indentado dos
+# espacios, sin comentarios salvo nuestro marcador de apertura, y SIN el de cierre. Con una
+# entrada ajena justo después y más tablas detrás, que es lo que un emparejamiento de marcadores
+# mal hecho se llevaría por delante.
+_CODEX_REESCRITO_POR_OTRO = """model = "x"
+
+  [mcp_servers.git]
+    command = "uvx"
+    args = ["mcp-server-git"]
+
+  # local-delegate:begin
+  [mcp_servers.local-delegate]
+    url = "http://127.0.0.1:9393/mcp"
+    bearer_token_env_var = "LOCAL_DELEGATE_WEB_TOKEN"
+
+  [mcp_servers.pycharm]
+    url = "http://127.0.0.1:64342/sse"
+
+  [projects.proyecto]
+    trust_level = "trusted"
+"""
+
+
+def test_codex_reescrito_por_otro_programa_se_reemplaza_sin_duplicar(tmp_path):
+    """La entrada indentada se reconoce, se reemplaza y no se duplica.
+
+    Antes, la búsqueda exigía la cabecera al principio de la línea y no la veía: `install` añadía una segunda `[mcp_servers.local-delegate]`, el TOML
+    quedaba inválido y Codex se quedaba sin ningún MCP.
+    """
+    assert tomllib.loads(_CODEX_REESCRITO_POR_OTRO)  # el de partida es TOML válido
+    entry = inst.mcp_entry("http", None, api_key_env=False, version=None)
+    result = inst.upsert_codex_mcp(_CODEX_REESCRITO_POR_OTRO, inst.codex_mcp_block(entry))
+
+    data = tomllib.loads(result)
+    assert result.count("mcp_servers.local-delegate]") == 1
+    assert data["mcp_servers"]["pycharm"]["url"].endswith("/sse")
+    assert data["mcp_servers"]["git"]["command"] == "uvx"
+    assert data["projects"]["proyecto"]["trust_level"] == "trusted"
+    assert result.count(inst.TOML_BEGIN) == 1
+    assert result.count(inst.TOML_END) == 1
+
+
+def test_un_marcador_huerfano_no_se_lleva_lo_que_hay_detras(tmp_path):
+    """Dos reinstalaciones seguidas sobre el fichero sin marcador de cierre.
+
+    Emparejando marcadores, la segunda casaría el `begin` huérfano con el `end` escrito por la
+    primera y borraría lo de en medio: `pycharm` y los proyectos. El huérfano tiene que desaparecer
+    en la primera pasada, y la segunda tiene que dejar el fichero igual.
+    """
+    entry = inst.mcp_entry("http", None, api_key_env=False, version=None)
+    block = inst.codex_mcp_block(entry)
+    primera = inst.upsert_codex_mcp(_CODEX_REESCRITO_POR_OTRO, block)
+    segunda = inst.upsert_codex_mcp(primera, block)
+
+    assert segunda == primera
+    data = tomllib.loads(segunda)
+    assert "pycharm" in data["mcp_servers"]
+    assert "proyecto" in data["projects"]
+
+
+def test_quitar_la_entrada_de_un_codex_reescrito_deja_lo_demas(tmp_path):
+    result = inst.remove_codex_mcp(_CODEX_REESCRITO_POR_OTRO)
+    data = tomllib.loads(result)
+    assert "local-delegate" not in data["mcp_servers"]
+    assert set(data["mcp_servers"]) == {"git", "pycharm"}
+    assert inst.TOML_BEGIN not in result
```

### Mensaje A

```
fix(config): tolerar sangría y marcadores rotos en config.toml de Codex

- Aceptar secciones con sangría para evitar conflictos con editores
  que reescriben el archivo (ej. plugin de JetBrains).
- No requerir emparejamiento estricto de marcadores begin/end para
  evitar borrar contenido ajeno si falta el marcador de cierre.
- Actualizar regex y lógica de limpieza para manejar casos huérfanos.
```

### Mensaje B

```
fix(codex): mejorar la gestión de config.toml con sangría o marcadores rotos

- Permite detectar la sección de MCP aunque tenga sangría o falte el marcador de cierre.
- Evita la duplicación de tablas al usar la búsqueda por nombre en lugar de por marcadores.
- Previene la pérdida de datos al no intentar emparejar marcadores de bloque huérfanos.
- Actualiza la documentación y el changelog.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 21

Diff: 1 ficheros, +22 −0

```diff
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/verification.md b/.sdd/changes/delegacion-precisa-y-fiable/verification.md
index 2c32399..ff423ba 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/verification.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/verification.md
@@ -1410,3 +1410,25 @@ Suite: **1293 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios.
 nuevo mete otra version en la ventana de F1, que cierra el 2026-09-19; se instala al cerrarla. Y un
 cliente con `LOCAL_DELEGATE_MODEL_*` distinto del lanzador del daemon hace que el hook mire el
 defecto: ante la duda no ve el enfriamiento y sigue bloqueando, que es el comportamiento anterior.
+
+## Release 0.28.0 (2026-09-15)
+
+Publicada antes de cerrar la ventana de F1 por decision del usuario (`plan.md`, tras la tarea 31).
+
+| Paso | Resultado |
+| --- | --- |
+| #195 (tarea 31), #196 (docs de la release), #197 (bump) | 13 de 13 checks en verde cada una; mezcladas como `d7ffa37`, `cf527b7` y `bd49264`. En la #195, CodeQL abrio un hilo (`py/empty-except`): arreglado con comentario y hilo resuelto |
+| Auditoria de docs contra el CHANGELOG | receta de llama-swap con los defaults viejos, receta de hooks y una entrada del CHANGELOG con el apagado por variable, y huecos en Configuration, Architecture, Tools, Backend-versions, Troubleshooting, README y `.env.example`; cada uno comprobado antes de corregir |
+| Captura del README | contra la app de metricas del repo en el 9494; manifiesto en 0.28.0. `uv sync` habia retirado Playwright, que no es dependencia: reinstalado a la misma version (1.62.0) |
+| `release.py 0.28.0 --dry-run` y `release.py 0.28.0` | Release `v0.28.0` con rueda y sdist |
+| `publish.yml` | `check-version`, `pypi` y `mcp-registry` en verde; PyPI y el registro MCP sirven 0.28.0 |
+| Daemon desde PyPI | `uv tool install --force --reinstall --refresh "local-delegate-mcp[llamaswap]==0.28.0"`, 21:03:19Z; `local_status` v0.28.0, respaldo y enfriamiento encendidos |
+| `install --mcp-mode http --web-token-env --enable-read-hook --agents` | 21:03:55Z; 4 hooks registrados, incluido `PreToolUse/mcp__.+__(read_[a-z_]*\|get_file_contents)`; entradas MCP con la cabecera del token |
+| `doctor` | «todo a punto». El aviso previo de llama-swap v238 era el entorno heredado de la sesion: el de usuario ya apuntaba a v255 y el proceso vivo es v255 |
+| Hook instalado, ejecutado tal cual | lectura por `mcp__filesystem__read_text_file`: sin salida, evento `camino: mcp`, `bloqueo: encendido`; control por `Read` sobre el mismo fichero: `deny`. Version de script `a1485d36` |
+
+**La ventana de F1 cambia de version de hook a las 2026-09-15T21:03:55Z**: la medicion se lee por
+tramos de version, que `medir_adopcion.py` ya distingue.
+
+Pendiente: el depscore de Socket del paquete publicado (el MCP de Socket respondio «No valid
+session» en tres intentos) y actualizar la Mac, que sigue en 0.27.0.
```

### Mensaje A

```
docs: actualizar verificación de release 0.28.0
```

### Mensaje B

```
docs(verification): añadir registro de la release 0.28.0

- Documentar los resultados de la verificación de la versión 0.28.0
- Incluir detalles de los checks, auditoría de docs y pruebas de instalación
- Registrar el cambio de versión en la ventana de F1
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 22

Diff: 7 ficheros, +40 −13

```diff
diff --git a/.sdd/changes/iconos-atados-al-svg/state.json b/.sdd/changes/iconos-atados-al-svg/state.json
index ed40f8d..d2650a3 100644
--- a/.sdd/changes/iconos-atados-al-svg/state.json
+++ b/.sdd/changes/iconos-atados-al-svg/state.json
@@ -3,9 +3,9 @@
   "slug": "iconos-atados-al-svg",
   "title": "Los PNG de la marca quedan atados al favicon.svg",
   "mode": "standard",
-  "status": "verifying",
+  "status": "closing",
   "createdAt": "2026-07-31T22:43:27.651Z",
-  "updatedAt": "2026-07-31T22:46:48.863Z",
+  "updatedAt": "2026-07-31T22:55:19.711Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -26,10 +26,10 @@
       "actor": "user"
     },
     "conformance": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-07-31T22:55:19.525Z",
+      "evidence": "review.md conforms-with-notes; 7 requisitos verificados; CI del PR 113 en verde tras normalizar el hash a LF; mergeado",
+      "actor": "user"
     },
     "memory": {
       "status": "pending",
@@ -111,6 +111,28 @@
       "at": "2026-07-31T22:46:48.863Z",
       "evidence": "655 passed 1 skipped; ruff y format limpios; script ejecutado de verdad; 3 mutantes, 3 cazados",
       "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "conformance",
+      "status": "approved",
+      "at": "2026-07-31T22:55:19.525Z",
+      "evidence": "review.md conforms-with-notes; 7 requisitos verificados; CI del PR 113 en verde tras normalizar el hash a LF; mergeado",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-07-31T22:55:19.623Z",
+      "reason": "CI verde y mergeado"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-07-31T22:55:19.711Z",
+      "reason": "CI verde y mergeado"
     }
   ]
 }
diff --git a/CHANGELOG.md b/CHANGELOG.md
index b309567..0efdec1 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,11 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.20.0] - 2026-07-31
+
+> La tanda que **vació el backlog auditado**: los siete puntos que la auditoría del 2026-07-31
+> dejó confirmados, más el `Ctrl+C` reportado durante la propia sesión.
+
 ### Added
 - **Los PNG de la marca quedan atados al `favicon.svg` del que salen.** `icon.src.html` ya cargaba
   el SVG canónico en vez de redibujar la marca, pero **nada obligaba a regenerar los PNG cuando el
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index 3f1869e..01e8b55 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.19.0",
-  "sha256": "ecb5cbdbabafc02577e50635ac142d2b21cf400803255395732763f63ac183db",
-  "bytes": 610728
+  "version": "0.20.0",
+  "sha256": "1b04c43ddf2e2a969af9e81682db4b3972853f2da2f123689cf6336c8d8afc0a",
+  "bytes": 653195
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index 373ef35..a698574 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index a7344ae..0076e2f 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.19.0"
+version = "0.20.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/server.json b/server.json
index 45c285d..124f9c7 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.19.0",
+  "version": "0.20.0",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.19.0",
+      "version": "0.20.0",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/uv.lock b/uv.lock
index e15efc4..63760c7 100644
--- a/uv.lock
+++ b/uv.lock
@@ -360,7 +360,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.19.0"
+version = "0.20.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
feat: vincula PNG de marca al favicon.svg y libera backlog
```

### Mensaje B

```
docs(sdd): registra la aprobación de la conformidad de una traza
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 23

Diff: 7 ficheros, +212 −59

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 67a3d5e..4e264e6 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,28 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.7.0] - 2026-07-10
+
+### Fixed
+- Dashboard: el panel «En curso» nunca mostraba delegaciones activas si el navegador
+  consultaba un proceso MCP distinto del que las ejecutaba (varias sesiones de Claude Code
+  abiertas a la vez, o la web arrancada manualmente con
+  `python -m local_delegate.web.metrics`) — el estado `inflight` vivía solo en memoria del
+  proceso que ganaba el puerto 9393. Ahora `_inflight_start`/`_inflight_end`/
+  `inflight_snapshot()` leen y escriben `LOG_DIR/inflight.json` bajo `FileLock`, así
+  `/api/inflight` ve las delegaciones de **todas** las sesiones activas en la máquina, no
+  solo la del proceso que sirve la web. Autolimpieza de entradas huérfanas (proceso muerto o
+  con más de 30 min sin cerrarse) en cada lectura, sin hilo de fondo dedicado.
+- Dashboard: el mensaje vacío «Sin delegaciones en curso» heredaba `Inter` en vez de
+  `JetBrains Mono` como el resto del panel «Backend local» (badges, nombres de modelo,
+  contador de tiempo).
+
+### Added
+- Dashboard: el modelo que está procesando una delegación ahora se marca en el panel
+  «Backend local» (punto ámbar con pulso, estado «procesando») y la tool en uso se resalta
+  en los chips de «Tools MCP disponibles», cruzando el modelo/tool de cada entrada de
+  `/api/inflight` contra las filas ya renderizadas.
+
 ## [0.6.0] - 2026-07-10
 
 ### Added
diff --git a/pyproject.toml b/pyproject.toml
index b5b0b5b..a910c72 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.6.0"
+version = "0.7.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/src/local_delegate/server.py b/src/local_delegate/server.py
index 325aade..655ab7b 100644
--- a/src/local_delegate/server.py
+++ b/src/local_delegate/server.py
@@ -64,10 +64,77 @@ def _get_client() -> httpx.Client:
     return _client
 
 
-# --- Delegaciones en curso (visibilidad; solo dentro de este proceso) -------
+# --- Delegaciones en curso (visibilidad multi-proceso vía archivo compartido) ----------------
+# El estado vive en LOG_DIR/inflight.json (mismo directorio de datos que el log de uso), no
+# solo en memoria: así CUALQUIER proceso MCP que sirva la web (metrics.py) ve las delegaciones
+# en curso de TODAS las sesiones de Claude activas en esta máquina, no solo la suya. El
+# contador local (_inflight_lock/_inflight_next_id) solo genera ids únicos por proceso; nunca
+# toca disco.
 _inflight_lock = threading.Lock()
-_inflight: dict[int, dict] = {}
 _inflight_next_id = 0
+_INFLIGHT_STALE_S = 1800  # red de seguridad: entrada huérfana (proceso muerto a media escritura)
+
+
+def _inflight_file() -> Path:
+    return config.LOG_DIR / "inflight.json"
+
+
+def _pid_alive(pid: int) -> bool:
+    """Best-effort: True si el proceso con ese PID sigue vivo. Nunca lanza."""
+    if pid == os.getpid():
+        return True
+    try:
+        if sys.platform == "win32":
+            import ctypes
+
+            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFO
+            if not handle:
+                return False
+            ctypes.windll.kernel32.CloseHandle(handle)
+            return True
+        os.kill(pid, 0)
+        return True
+    except Exception:
+        return False
+
+
+def _read_inflight_data(path: Path) -> dict:
+    try:
+        with path.open(encoding="utf-8") as f:
+            data = json.load(f)
+        return data if isinstance(data, dict) else {}
+    except (OSError, ValueError):
+        return {}
+
+
+def _atomic_write_json(path: Path, data: dict) -> None:
+    tmp = path.with_name(path.name + ".tmp")
+    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
+    tmp.replace(path)
+
+
+def _inflight_mutate(mutate_fn) -> None:
+    """Aplica mutate_fn(dict) al archivo compartido de inflight bajo lock exclusivo.
+
+    Best-effort como el resto del logging: si no consigue el lock en 1s, aplica igual sin
+    lock (nunca bloquea ni rompe una delegación). El peor caso es una entrada perdida o
+    duplicada, que se autolimpia por TTL/pid-muerto en inflight_snapshot().
+    """
+    path = _inflight_file()
+    try:
+        path.parent.mkdir(parents=True, exist_ok=True)
+        lock = FileLock(str(path) + ".lock", timeout=1)
+        try:
+            with lock:
+                data = _read_inflight_data(path)
+                mutate_fn(data)
+                _atomic_write_json(path, data)
+        except Timeout:
+            data = _read_inflight_data(path)
+            mutate_fn(data)
+            _atomic_write_json(path, data)
+    except OSError:
+        pass  # el tracking de inflight es best-effort; jamás rompe una delegación
 
 
 def _inflight_start(*, tool: str, model: str, source: str, chars_in: int) -> int:
@@ -75,36 +142,67 @@ def _inflight_start(*, tool: str, model: str, source: str, chars_in: int) -> int
     with _inflight_lock:
         _inflight_next_id += 1
         entry_id = _inflight_next_id
-        _inflight[entry_id] = {
-            "tool": tool,
-            "model": model,
-            "source": source,
-            "chars_in": chars_in,
-            "started_at": time.time(),
-        }
+    pid = os.getpid()
+    key = f"{pid}:{entry_id}"
+    entry = {
+        "tool": tool,
+        "model": model,
+        "source": source,
+        "chars_in": chars_in,
+        "started_at": time.time(),
+        "pid": pid,
+    }
+
+    def _add(data: dict) -> None:
+        data[key] = entry
+
+    _inflight_mutate(_add)
     return entry_id
 
 
 def _inflight_end(entry_id: int) -> None:
-    with _inflight_lock:
-        _inflight.pop(entry_id, None)
+    key = f"{os.getpid()}:{entry_id}"
+
+    def _remove(data: dict) -> None:
+        data.pop(key, None)
+
+    _inflight_mutate(_remove)
 
 
 def inflight_snapshot() -> list[dict]:
-    """Copia de las delegaciones en curso, con `elapsed_s`. Usada por la web de métricas."""
+    """Delegaciones en curso de TODOS los procesos MCP activos, con `elapsed_s`.
+
+    Lee/limpia el archivo compartido de inflight (ver _inflight_mutate). Descarta entradas
+    huérfanas (TTL vencido o proceso ya muerto) en la misma pasada, así no hace falta un hilo
+    de housekeeping aparte. Usada por /api/inflight (web de métricas).
+    """
     now = time.time()
-    with _inflight_lock:
-        return [
-            {
-                "id": entry_id,
-                "tool": v["tool"],
-                "model": v["model"],
-                "source": v["source"],
-                "chars_in": v["chars_in"],
-                "elapsed_s": round(now - v["started_at"], 1),
-            }
-            for entry_id, v in _inflight.items()
-        ]
+    result: list[dict] = []
+
+    def _collect_and_prune(data: dict) -> None:
+        stale = []
+        for key, v in data.items():
+            age = now - v.get("started_at", 0)
+            pid = v.get("pid")
+            if age > _INFLIGHT_STALE_S or (pid is not None and not _pid_alive(pid)):
+                stale.append(key)
+                continue
+            result.append(
+                {
+                    "id": key,
+                    "tool": v.get("tool"),
+                    "model": v.get("model"),
+                    "source": v.get("source"),
+                    "chars_in": v.get("chars_in"),
+                    "elapsed_s": round(age, 1),
+                }
+            )
+        for key in stale:
+            data.pop(key, None)
+
+    _inflight_mutate(_collect_and_prune)
+    result.sort(key=lambda e: -e["elapsed_s"])
+    return result
 
 
 # --- Helpers ----------------------------------------------------------------
diff --git a/src/local_delegate/web/metrics.py b/src/local_delegate/web/metrics.py
index fa1156b..c31ced6 100644
--- a/src/local_delegate/web/metrics.py
+++ b/src/local_delegate/web/metrics.py
@@ -15,9 +15,9 @@ Solo se abren los archivos cuyo mes interseca el rango pedido — releer un rang
 recorre el histórico completo. Cache en memoria por archivo (mtime+size); solo el archivo del
 mes actual cambia entre refrescos.
 
-Limitación de /api/inflight: solo ve las llamadas en vuelo del PROCESO que sirve esta web (el
-MCP que la arrancó). Si tienes varias instancias de Claude con su propio MCP, cada una sirve su
-propia web y su propio /api/inflight — no hay estado compartido entre procesos.
+/api/inflight lee un archivo compartido (LOG_DIR/inflight.json, ver server._inflight_mutate) en
+vez de memoria local: ve las delegaciones en curso de TODAS las sesiones de Claude activas en
+esta máquina (mismo usuario del SO), no solo la del proceso que sirve esta web.
 
 Dos formas de arrancar:
   1) Automática: el MCP (server.py) llama a run_in_thread() en un hilo daemon,
@@ -550,20 +550,24 @@ td.mono,th.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
   border-radius:999px;padding:3px 10px;text-transform:uppercase}
 .pill.up{color:var(--acc);background:color-mix(in srgb,var(--acc) 12%,transparent);border:1px solid color-mix(in srgb,var(--acc) 32%,transparent)}
 .pill.down{color:var(--danger);background:color-mix(in srgb,var(--danger) 12%,transparent);border:1px solid color-mix(in srgb,var(--danger) 32%,transparent)}
-.mrow{display:flex;align-items:center;gap:10px;padding:8px 2px;border-bottom:1px dashed color-mix(in srgb,var(--bd) 75%,transparent)}
+.mrow{display:flex;align-items:center;gap:10px;padding:8px 2px;border-bottom:1px dashed color-mix(in srgb,var(--bd) 75%,transparent);border-radius:8px;transition:background .2s}
 .mrow:last-child{border-bottom:0}
+.mrow.busy{background:color-mix(in srgb,var(--amber) 9%,transparent);padding-left:6px;padding-right:6px}
 .mdot{width:8px;height:8px;border-radius:50%;background:var(--faint);opacity:.55;flex:0 0 auto;transition:.2s}
 .mdot.ready{background:var(--acc);opacity:1;box-shadow:0 0 8px color-mix(in srgb,var(--acc) 60%,transparent)}
 .mdot.starting{background:var(--amber);opacity:1;box-shadow:0 0 8px color-mix(in srgb,var(--amber) 60%,transparent)}
+.mdot.busy{background:var(--amber);opacity:1;box-shadow:0 0 8px color-mix(in srgb,var(--amber) 60%,transparent);animation:pulse 1.4s infinite}
 .mname{font-family:var(--mono);font-size:12.5px;font-weight:600;color:var(--tx)}
 .mrole{font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:2px 7px;border-radius:6px;
   background:color-mix(in srgb,var(--violet) 13%,transparent);color:var(--violet)}
 .mstate{margin-left:auto;font-size:11px;color:var(--mut);font-family:var(--mono)}
+.mrow.busy .mstate{color:var(--amber);font-weight:600}
 .subh{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin:14px 0 6px}
 .toolchips{display:flex;flex-wrap:wrap;gap:6px}
 .tchip{font-family:var(--mono);font-size:10.5px;color:var(--mut);border:1px solid var(--bd);border-radius:7px;padding:3px 8px;cursor:default;transition:.13s}
 .tchip:hover{color:var(--acc);border-color:color-mix(in srgb,var(--acc) 40%,transparent)}
-.ifrow{display:flex;align-items:center;gap:9px;padding:6px 2px;font-size:12.5px;color:var(--tx2)}
+.tchip.busy{color:var(--amber);border-color:color-mix(in srgb,var(--amber) 50%,transparent);background:color-mix(in srgb,var(--amber) 12%,transparent)}
+.ifrow{display:flex;align-items:center;gap:9px;padding:6px 2px;font-size:12.5px;color:var(--tx2);font-family:var(--mono)}
 .spin{width:12px;height:12px;border-radius:50%;flex:0 0 auto;
   border:2px solid color-mix(in srgb,var(--amber) 28%,transparent);border-top-color:var(--amber);animation:rot .8s linear infinite}
 @keyframes rot{to{transform:rotate(360deg)}}
@@ -749,7 +753,7 @@ footer{color:var(--faint);font-size:11.5px;margin-top:26px;padding-top:18px;bord
 <script>
 const CPT = 4, F = new Intl.NumberFormat('es'), PAGE = 10;
 const state = {events:[], range:'today', auto:true, charts:{},
-  page:0, status:null, running:{}, backendUp:undefined};
+  page:0, status:null, running:{}, backendUp:undefined, inflight:[]};
 const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
 const tok = c => Math.round(c/CPT);
 const MONO = "'JetBrains Mono',ui-monospace,monospace";
@@ -867,25 +871,28 @@ function renderBackend(){
   pill.title = st.base_url||'';
   const models = [...(((st.backend)||{}).models||[])];
   (st.catalog||[]).forEach(c=>{ if(!models.includes(c.model)) models.push(c.model); });
+  const busyModels = new Set((state.inflight||[]).map(it=>it.model));
   const body = document.getElementById('modelsBody');
   if(!models.length){
     body.innerHTML = '<div class="empty" style="padding:16px">El backend no expone modelos ('+(st.base_url||'?')+').</div>';
     return;
   }
   body.innerHTML = models.map(m=>{
+    const busy = busyModels.has(m);
     const run = state.running[m];
-    const cls = run==='ready'?'ready':(run?'starting':'');
-    const stateTxt = run==='ready'?'montado':(run||'frío');
+    const cls = (run==='ready'?'ready':(run?'starting':'')) + (busy?' busy':'');
+    const stateTxt = busy?'procesando':(run==='ready'?'montado':(run||'frío'));
     const roles = roleLabels(m).map(l=>`<span class="mrole">${l}</span>`).join('');
-    return `<div class="mrow"><span class="mdot ${cls}"></span><span class="mname">${m}</span>${roles}<span class="mstate">${stateTxt}</span></div>`;
+    return `<div class="mrow${busy?' busy':''}"><span class="mdot ${cls}"></span><span class="mname">${m}</span>${roles}<span class="mstate">${stateTxt}</span></div>`;
   }).join('');
 }
 
 function renderTools(){
   const tools = ((state.status||{}).tools)||[];
+  const busyTools = new Set((state.inflight||[]).map(it=>it.tool));
   document.getElementById('toolsCount').textContent = tools.length?('('+tools.length+')'):'';
   document.getElementById('toolsBody').innerHTML = tools.length
-    ? tools.map(t=>`<span class="tchip" title="${(t.summary||'').replace(/"/g,'&quot;')}">${t.name}</span>`).join('')
+    ? tools.map(t=>`<span class="tchip${busyTools.has(t.name)?' busy':''}" title="${(t.summary||'').replace(/"/g,'&quot;')}">${t.name}</span>`).join('')
     : '<span class="tchip">sin datos</span>';
 }
 
@@ -897,10 +904,10 @@ async function pollInflight(){
     state.backendUp = !!bj.available;
     state.running = {};
     if(bj.available) (bj.running||[]).forEach(m=>{ if(m.model) state.running[m.model]=m.state||'ready'; });
-    renderBackend();
-    const items = ij.inflight||[];
-    document.getElementById('inflightBody').innerHTML = items.length
-      ? items.map(it=>`<div class="ifrow"><span class="spin"></span><span class="badge">${it.tool}</span>
+    state.inflight = ij.inflight||[];
+    renderBackend(); renderTools();
+    document.getElementById('inflightBody').innerHTML = state.inflight.length
+      ? state.inflight.map(it=>`<div class="ifrow"><span class="spin"></span><span class="badge">${it.tool}</span>
           <span class="badge model">${it.model}</span>
           <span class="num" style="color:var(--mut)">${it.elapsed_s}s · ${F.format(it.chars_in||0)} chars</span></div>`).join('')
       : '<div class="ifrow" style="color:var(--faint)">Sin delegaciones en curso</div>';
diff --git a/tests/test_core.py b/tests/test_core.py
index f737ff8..a1b90cf 100644
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -459,7 +459,9 @@ def test_log_event_writes_to_rotated_file(monkeypatch, tmp_path):
 
 
 # --- F4: delegaciones en curso (inflight) -----------------------------------------------
-def test_inflight_snapshot_during_and_after_chat(monkeypatch):
+def test_inflight_snapshot_during_and_after_chat(tmp_path, monkeypatch):
+    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
+
     def slow_post_chat(model, payload):
         _time.sleep(0.3)
         return server.ChatResult(text="ok", ok=True, finish_reason="stop")
diff --git a/tests/test_metrics.py b/tests/test_metrics.py
index ce590d4..8f86478 100644
--- a/tests/test_metrics.py
+++ b/tests/test_metrics.py
@@ -4,6 +4,7 @@
 from __future__ import annotations
 
 import json
+import os
 import time
 from datetime import datetime, timezone
 
@@ -108,26 +109,49 @@ def test_api_events_default_range_last_30_days(tmp_path, monkeypatch):
     assert len(data["meta"]["files_read"]) == 1
 
 
-def test_api_inflight_reflects_server_state(monkeypatch):
-    monkeypatch.setattr(
-        server,
-        "_inflight",
-        {
-            1: {
-                "tool": "t",
-                "model": "m",
-                "source": "path",
-                "chars_in": 5,
-                "started_at": time.time(),
-            }
+def test_api_inflight_reflects_server_state(tmp_path, monkeypatch):
+    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
+    entry_id = server._inflight_start(tool="t", model="m", source="path", chars_in=5)
+    try:
+        client = TestClient(metrics.app)
+        r = client.get("/api/inflight")
+        assert r.status_code == 200
+        data = r.json()
+        assert len(data["inflight"]) == 1
+        assert data["inflight"][0]["tool"] == "t"
+    finally:
+        server._inflight_end(entry_id)
+
+
+def test_api_inflight_sees_other_process_and_drops_dead_pid(tmp_path, monkeypatch):
+    """/api/inflight lee el archivo compartido: ve entradas de OTROS pids vivos y descarta
+    las de pids muertos, sin que este proceso haya llamado a _inflight_start para ellas."""
+    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
+    other_pid = os.getppid()  # un pid real y vivo, distinto del nuestro
+    path = server._inflight_file()
+    data = {
+        f"{other_pid}:1": {
+            "tool": "local_classify",
+            "model": "m",
+            "source": "inline",
+            "chars_in": 1,
+            "started_at": time.time(),
+            "pid": other_pid,
         },
-    )
+        "999999:1": {
+            "tool": "local_extract",
+            "model": "m",
+            "source": "inline",
+            "chars_in": 1,
+            "started_at": time.time(),
+            "pid": 999999,
+        },
+    }
+    server._atomic_write_json(path, data)
+
     client = TestClient(metrics.app)
-    r = client.get("/api/inflight")
-    assert r.status_code == 200
-    data = r.json()
-    assert len(data["inflight"]) == 1
-    assert data["inflight"][0]["tool"] == "t"
+    tools = {e["tool"] for e in client.get("/api/inflight").json()["inflight"]}
+    assert tools == {"local_classify"}
 
 
 @respx.mock
diff --git a/uv.lock b/uv.lock
index 7916c34..d5a7663 100644
--- a/uv.lock
+++ b/uv.lock
@@ -377,7 +377,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.6.0"
+version = "0.7.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
fix(dashboard): visibilidad multi-proceso de delegaciones en curso

- Persistir estado inflight en inflight.json con FileLock para que
  todas las sesiones MCP compartan la vista de delegaciones activas.
- Autolimpieza de entradas huérfanas por TTL o PID muerto en lectura.
- Resaltar modelo y herramienta en uso en el panel Backend local.
- Corregir fuente del mensaje vacío en el panel de delegaciones.
```

### Mensaje B

```
feat(dashboard): implementar visibilidad multi-proceso de delegaciones

- Permite que el dashboard muestre delegaciones de todas las sesiones activas mediante un archivo JSON compartido.
- Añade detección de procesos muertos y autolimpieza de entradas huérfanas.
- Mejora la UI para resaltar modelos y herramientas que están procesando tareas actualmente.
- Corrige inconsistencias tipográficas en el panel de backend local.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 24

Diff: 2 ficheros, +103 −1

```diff
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
index 23a28d5..0fd7bd3 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
@@ -1702,6 +1702,87 @@ Sirve para reproducir la tanda y para descontar estos intervalos de la quinta me
 | 1 | 2026-09-14 19:24 | 2026-09-14 19:51 | ~60 min / 27 min | Tarea 18: entorno, CP-1, CP-2, CP-2b (sin tanda) | b10909 (`a2878d30d`, CUDA 13.3) | v255 (`7761aa1`), puerto 9595 | `mmap` y `none` (CP-2b los compara) | CP-1 pasa (tras un veto: perfil en la ruta equivocada), CP-2 pasa, CP-2b ve expertos solo con `none` y en diferencia (P-13) | ninguna |
 | 2 | 2026-09-14 20:09 | 2026-09-14 20:58 | ~75 min / 49 min (CP-3 en si: 20:14-20:24) | Tarea 19: perfil del driver movido a b10909 y medido, CP-3 (`qwen35-2b` vs `qwen25-coder-14b`, 3 corridas, `-c 32768`) y control de entrada de `vision` (`qwen3-vl-8b`) | b10909 (`a2878d30d`, CUDA 13.3) | v255 (`7761aa1`), puerto 9595 | `mmap` (CP-3 no decide RAM; P-13 sigue abierta) | CP-3 **no pasa** (`code` y `mechanical`; `long` y `vision` pasan solo en el programa, ver resultado de CP-3); CP-4 pasa (test) | 2 por `process_changed` (primera corrida de cada modelo), **no repetidas** |
 | 3 | 2026-09-14 22:58 | **abierta**: el setup de medicion (perfil en b10909, daemon parado) se mantiene hasta la tanda por decision del usuario; descontar todo el intervalo de la quinta medicion de adopcion (§1.5) | ~90 min / segundo piloto 23:00:36-23:10:30; tercer piloto (commit `a3bd148`) 00:06-00:17 y bloque del 2B repetido 00:19-00:20; cuarto piloto (commit `29c5e61`, 5 corridas) 00:36-00:50; llama-swap de pruebas parado al acabar | Tarea 19, segundo piloto de CP-3 entero (P-9) con el corpus y el runner corregidos: perfil del driver medido en b10909, texto con `qwen35-2b` y `qwen25-coder-14b` (3 corridas), control de entrada de `vision` con `qwen3-vl-8b` | b10909 (`a2878d30d`, CUDA 13.3) | v255 (`7761aa1`), puerto 9595 | `mmap` | — | — |
+| 4 | 2026-09-15 02:40 (perfil) / 02:41:02 (barrido) | 2026-09-15 03:04 | ~25-30 min, escrita antes de empezar / barrido invalido 02:41-02:48 (cortado); arreglo del perfil y controles 02:54-02:56; barrido v2 02:56:28-03:01:43 (5 min 15 s); causa de `-ncmoe 4` y cargas con `llama-server` 03:02-03:04 | Tarea 20: tokens y KV por carga (§3.5, §5.2), perfil del driver medido, barrido de `-ncmoe` (0/4/8/12/16) con `llama-bench -lm none -ngl 99 -p 512 -n 128 -r 3` en Gemma 4 26B-A4B (profundidad 0 y 33 334) y Qwen3.6-35B-A3B (0 y 6 252) | b10909 (`a2878d30d`, CUDA 13.3) | no se usa (`llama-bench` directo) | `none` | perfil: b10909 OOM a los 6,1 s, b9925 cargo desbordando 5 855 MiB (pasa). **El barrido NO vale**: el perfil no cubre `llama-bench.exe` (ver abajo) | barrido cortado por el sistema por falta de memoria en Qwen3.6 `-ncmoe 12` (02:48 UTC) |
+
+**Hallazgo de la sesion 4: el perfil del driver no cubre `llama-bench.exe`, y el barrido desbordo sin
+avisar.** El Qwen3.6-35B-A3B con `-ncmoe 0` (~16,9 GiB de pesos en 16 GB) **corrio** en `llama-bench`
+a 16 tok/s, cuando con el perfil activo tendria que dar OOM. Control a las 02:49 UTC, la misma carga
+con `-p 64 -n 8 -r 1`: **sale con 0 en 6,9 s y `Shared Usage` del adaptador sube de 47 a 1 409 MiB**,
+sin linea de OOM. El perfil es por nombre de ejecutable (§1.3) y solo lo tiene `llama-server.exe`.
+Consecuencia: ningun punto del barrido separa «cabe» de «desborda», y un `-ncmoe` rapido puede estar
+desbordando en parte; es el error 1 de julio en otro ejecutable. Lo medido se conserva en
+`resultados/barrido-*.jsonl` (26B-A4B completo; Qwen3.6 con 0, 4 y 8) como dato **invalido para
+decidir**. Ademas, el sistema corto el barrido por falta de memoria con Qwen3.6 `-ncmoe 12` y
+`--load-mode none`: con 32 GB, la RAM es un limite real para ese modelo.
+
+**Arreglo, medido por su efecto (decision del usuario, 2026-09-15).** El usuario anadio en la NVIDIA
+App una entrada «Prefer No Sysmem Fallback» para `llama-bench.exe` de b10909: es otro nombre de
+fichero y convive con la de `llama-server.exe`. Controles, en este orden:
+
+| Hora UTC | Prueba | Resultado |
+| --- | --- | --- |
+| 02:54:51 | `llama-bench` Qwen3.6 `-ncmoe 0` | sale con 1 en 1,7 s, `Shared Usage` plano (125 MiB); sin causa en el log |
+| 02:54:57 | CP-1, `llama-server` b10909 | OOM a los 6,1 s (`cudaMalloc` 12 288 MiB): la entrada original sigue en su sitio |
+| 02:55:07 | CP-1, `llama-server` b9925 | carga en 12,1 s desbordando 5 666 MiB |
+| 02:55:54 | `llama-bench` Qwen3.6 `-ncmoe 0` **con `-v`** | **`cudaMalloc failed: out of memory`** al pedir 16 383 MiB: el fallo de 02:54:51 era OOM y no otra cosa |
+| 02:56:00 | control negativo, `llama-bench` Qwen3.6 `-ncmoe 8` | carga y mide (tg 61 tok/s): `llama-bench` no falla con todo |
+
+«Failed to load model» sin `-v` no distingue un OOM de un fichero roto: por eso hizo falta el `-v` y
+el negativo. En el negativo `Shared Usage` sube a 3 494 MiB, y **no es desbordamiento**: con
+`--load-mode none` los expertos en RAM cuentan como compartida (buffers anclados, CP-2b). En el
+barrido «no cabe» lo decide el OOM, nunca `Shared Usage`. El barrido se repite entero (`-v2`), con
+vigilancia de RAM: si la libre baja de 1,5 GB se detiene esa carga, se anota «no cabe en RAM» y no se
+intentan los `-ncmoe` mayores de ese modelo.
+
+**Barrido v2 (02:56:28-03:01:43 UTC, 5 min 15 s; estimado 25-30 min).** `llama-bench -lm none -ngl 99
+-p 512 -n 128 -r 3`, perfil activo en `llama-bench.exe`. tok/s (media de 3); `d` = profundidad del caso
+de calidad que mas contexto pide del rol. Datos crudos en `resultados/barrido-*-v2.jsonl`. Ningun valor
+se quedo sin RAM (minimo libre: 12,6 GB).
+
+| Modelo | `-ncmoe` | pp512 d=0 | tg128 d=0 | pp512 d | tg128 d | RAM libre min (GB) |
+| --- | --- | --- | --- | --- | --- | --- |
+| Gemma 4 26B-A4B (d = 33 334) | **0** | 3 397 | 94,5 | 2 151 | **76,9** | 17,7 |
+| | 4 | 2 113 | 67,3 | 1 575 | 60,9 | 16,4 |
+| | 8 | 1 596 | 57,0 | 1 294 | 49,9 | 15,1 |
+| | 12 | 1 267 | 44,7 | 1 065 | 41,4 | 13,9 |
+| | 16 | 1 099 | 44,8 | 948 | 35,5 | 12,6 |
+| Qwen3.6-35B-A3B (d = 6 252) | 0 | no cabe en GPU: `cudaMalloc` de 16 383 MiB (control con `-v` de 02:55:54) | | | | |
+| | 4 | no cabe en GPU: carga 14 959 MiB de pesos + 497 de computo y falla al crear el handle de cuBLAS (`CUDA error: the resource allocation failed`, 0xC0000409; control con `-v` a las 03:02:59) | | | | |
+| | **8** | 1 417 | 77,1 | 1 343 | **76,0** | 15,9 |
+| | 12 | 1 189 | 69,0 | 1 126 | 67,8 | 14,5 |
+| | 16 | 1 043 | 61,1 | 976 | 61,3 | 13,4 |
+
+**Elegidos, el punto mas rapido que cabe: Gemma 4 26B-A4B `-ncmoe 0` y Qwen3.6-35B-A3B `-ncmoe 8`.**
+Tres lecturas que el barrido invalido habria cambiado:
+
+- El 26B-A4B da las mismas cifras con y sin perfil (76,9 contra 79,0 a 33 k): no desbordaba, cabe entero.
+- **El Qwen3.6 con `-ncmoe 4` corrio a 91 tok/s en el barrido invalido y no cabe**: desbordaba y era
+  *mas rapido* que el elegido. Sin el perfil, el barrido habria elegido una config que en la tanda da
+  error al cargar. Es exactamente la trampa que CP-1 existe para evitar.
+- El fallo de `-ncmoe 4` no es un OOM limpio sino un `CUDA error` al crear cuBLAS: un script que solo
+  busque «out of memory» lo clasifica como «error» (el v2 lo hizo). Queda en la tabla con su causa.
+
+En los dos MoE, bajar expertos a RAM cuesta velocidad en todos los pasos medidos: no hay un punto
+intermedio que gane.
+
+**Confirmado con `llama-server` y el contexto completo** (03:04 UTC, `medir_kv`: `-v --load-mode none
+--fit off -ngl 99`). `llama-bench` solo reserva el contexto del test, asi que el `-ncmoe` elegido podia
+caber en el barrido y no en la config real; las cuatro cargan:
+
+| Config | `n_ctx` | KV | Pesos en GPU | Pesos en RAM | Computo GPU |
+| --- | --- | --- | --- | --- | --- |
+| Gemma 4 26B-A4B `-ncmoe 0`, calidad | 36 736 | 1 020 | 12 952 | 748 | 178 |
+| Gemma 4 26B-A4B `-ncmoe 0`, techo | 65 536 | 1 580 | 12 952 | 748 | 206 |
+| Qwen3.6-35B-A3B `-ncmoe 8`, calidad | 7 168 | 140 | 13 535 | 3 363 | 212 |
+| Qwen3.6-35B-A3B `-ncmoe 8`, techo | 65 536 | 1 280 | 13 535 | 3 363 | 376 |
+
+Las configs de techo caben con el mismo `-ncmoe` que las de calidad: no hace falta subirlo. Todas
+estan en `llama-swap-pruebas.yaml` (`t-*`).
+
+Estado de §1.4 al empezar la sesion 4 (§1.4 ya rehecho): RAM libre 20,6 GB; VRAM del adaptador 856
+MiB; ningun `llama-server`, `llama-swap` ni `pythonw`; `LocalDelegateDaemon` en `Ready` (parado); una
+sola sesion de Claude Code, la que mide. El barrido no pasa por el runner: mide velocidad, no memoria
+por proceso, y «cabe» es cargar sin OOM con el perfil activo.
 
 Desviaciones de §1.4 en la sesion 1, que la tanda tiene que resolver antes de empezar (**resueltas
 el 2026-09-14**: §1.1 y §1.4 rehechos con estos datos):
diff --git a/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml b/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
index 70ef401..772aba1 100644
--- a/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
+++ b/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
@@ -86,7 +86,28 @@ models:
   # Todo con --load-mode none (P-13). n_ctx de calidad = max por caso de (tokens de prompt medidos +
   # max_tokens) en el mayor de los dos modelos del rol, +10 %, a multiplo de 512; techo a 65 536 en
   # long y code (protocolo §3.5). Flags de cada vigente como en produccion; KV f16 salvo el coder.
-  # Pendientes del barrido de -ncmoe: Gemma 4 26B-A4B y Qwen3.6-35B-A3B.
+  # MoE: -ncmoe del barrido v2 (el punto mas rapido que cabe con el perfil activo, protocolo §10
+  # sesion 4), confirmado cargando cada config con llama-server y su contexto completo.
+  t-gemma4-26b-a4b:
+    cmd: >-
+      ${server} --load-mode none -ncmoe 0
+      --model D:\Projects\llms\models\gemma4-26b-a4b\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf
+      --ctx-size 36736
+  t-gemma4-26b-a4b-techo:
+    cmd: >-
+      ${server} --load-mode none -ncmoe 0
+      --model D:\Projects\llms\models\gemma4-26b-a4b\gemma-4-26B-A4B-it-UD-IQ4_XS.gguf
+      --ctx-size 65536
+  t-qwen36-35b-a3b:
+    cmd: >-
+      ${server} --load-mode none -ncmoe 8
+      --model D:\Projects\llms\models\qwen36-35b-a3b\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf
+      --ctx-size 7168
+  t-qwen36-35b-a3b-techo:
+    cmd: >-
+      ${server} --load-mode none -ncmoe 8
+      --model D:\Projects\llms\models\qwen36-35b-a3b\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf
+      --ctx-size 65536
   t-qwen25-coder-14b:
     cmd: >-
       ${server} --load-mode none
```

### Mensaje A

```
docs(protocolo): añadir resultados de la sesión 4 y configurar modelos MoE

- Registrar hallazgos sobre el perfil del driver y errores de OOM en `llama-bench`.
- Documentar el barrido v2 de `-ncmoe` para Gemma 4 y Qwen3.6.
- Configurar las tareas de prueba en `llama-swap-pruebas.yaml` con los valores de `-ncmoe` óptimos.
```

### Mensaje B

```
docs(protocolo): registrar sesion 4 y configurar MoE en YAML
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 25

Diff: 7 ficheros, +111 −10

````diff
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/plan.md b/.sdd/changes/delegacion-precisa-y-fiable/plan.md
index 6a2437c..5a86555 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/plan.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/plan.md
@@ -539,6 +539,15 @@ de F3 escribe esa config—. Las tareas 22 y 24 editan la config de produccion d
       Y la Mac delega con su configuracion de siempre.
     - Rollback or recovery: restaurar el `config.yaml` respaldado y devolver el perfil a la ruta de
       b9925, medido; b9925 sigue en disco. El cambio de `RECOMMENDED_VERSIONS` se revierte con el PR.
+    - Estado (2026-09-15): **hecha en la maquina** (`protocolo-f2.md` §10 sesion 7). Produccion corre
+      b10909 + v255 con el catalogo vigente desde las 15:04:55 UTC. Falta comprobar la Mac. Lo que
+      obligo a cambiar respecto a este texto: el ejecutable de llama-swap lo decide la variable de
+      usuario `LLAMASWAP_EXE` (no el `config.yaml`), asi que migrar y deshacer es cambiar esa variable;
+      y **`doctor` leia `b0` con el `--version` semver de b10909** —defecto silencioso que habria
+      marcado como desactualizado un build mas nuevo—, arreglado con test rojo y mutante en el mismo
+      PR. Rollback concreto: `LLAMASWAP_EXE` -> `D:\Projects\llms\llama-swap\llama-swap.exe`, copiar
+      `config.yaml.pre-b10909-20260915.bak` sobre `config.yaml`, perfil a `llamacpp\llama-server.exe`
+      (medido) y reiniciar el daemon.
 
 23. **Capturas reales para REQ-020 y la senal de modelo cargandose**
     - Files or modules: `tests/fixtures/backend/` (nuevo, respuestas crudas con version anotada),
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
index edc33fc..7a5f303 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
@@ -1921,6 +1921,26 @@ Lo que esto **no** prueba: calidad ni velocidad en b9925 —un solo prompt corto
 cargue con escritorio ocupando VRAM. Para la quinta medicion de adopcion (§1.5): el intervalo toco la
 GPU con produccion arriba; si llego alguna delegacion en esos dos minutos, pudo competir por VRAM.
 
+**Sesion 7, F3 tarea 22: migrar produccion a b10909 y llama-swap v255 con el catalogo vigente
+(2026-09-15, inicio 14:32:47 UTC, duracion estimada ~45 min, escrita antes de tocar nada).** Daemon
+parado a las 14:32:47 (`schtasks /End` y fin de su `pythonw` y su llama-swap v238); ningun
+`llama-server`, `llama-swap` ni `pythonw` del daemon vivo; VRAM 673 MiB. Produccion sin servicio
+durante toda la ventana: descontarla de la quinta medicion de adopcion (§1.5).
+
+Resultado (cierre 15:04:55 UTC, 32 min reales):
+
+| Hora UTC | Paso | Resultado |
+| --- | --- | --- |
+| 14:40-14:50 | v255 con la config de produccion, clave falsa solo en ese proceso, sin cargar modelos | acepta `groups`; con clave 200, sin clave 401, clave incorrecta 401; **sin la variable no arranca** (`environment variable 'LOCAL_DELEGATE_REMOTE_API_KEY' is not set`) |
+| — | el usuario mueve el perfil a `llamacpp-b10909\llama-server.exe` | — |
+| 15:03:01 / 15:03:12 | perfil medido (`medir-perfil-cp1.ps1`, LUID `F336`) | **b10909 OOM a los 6,1 s** (`cudaMalloc failed`, 12 288 MiB); b9925 carga desbordando 5 885 MiB |
+| 15:03:37-15:04:18 | catalogo vigente sobre b10909 + v255 en 9595 con la clave real | clave 200/401/401; los cinco cargan y responden (2,6 a 11,3 s); `gemma3-4b` sigue `ready` al entrar cada modelo del grupo `swap`; todos los `llama-server` desde `llamacpp-b10909`; VRAM pico 12 786 MiB (residente + 14B), `Shared Usage` <= 326 MiB; log sin errores |
+| 15:04:41 | produccion | `LLAMASWAP_EXE` de usuario -> `llama-swap-v255\llama-swap.exe`; `config.yaml` = `config.b10909.yaml` (sha256 `7858E9AB...`); respaldo `config.yaml.pre-b10909-20260915.bak` (`37BA542E...`) |
+| 15:04:55 | daemon arrancado (`schtasks /Run`) | `local_status` arriba; `local_classify` y `local_describe_image` responden por el daemon; llama-swap desde `llama-swap-v255`, `llama-server` desde `llamacpp-b10909`; `doctor` del repo: v255 y b10909 |
+
+Sin `--gpu-luid` fijo en ningun paso. Queda por comprobar, desde la Mac, que sigue delegando contra
+este backend.
+
 **Sesion 5, cierre del setup de medicion.** La tanda termino a las 04:21:01 UTC con llama-swap de
 pruebas y `llama-server` parados. **A las 04:31:35 la tarea `LocalDelegateDaemon` volvio a arrancar
 el daemon de produccion** (y su llama-swap en 9292, con b9925), sin intervencion de la sesion que
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/verification.md b/.sdd/changes/delegacion-precisa-y-fiable/verification.md
index bb1b643..9fef804 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/verification.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/verification.md
@@ -845,3 +845,31 @@ Tanda concluyente segun §6: **si**.
 | code | qwen36-35b-a3b | 157873 |
 | vision | qwen3-vl-8b | 718456 |
 | vision | gemma4-12b | 718456 |
+
+## F3: tarea 22, produccion migrada a b10909 y llama-swap v255 (2026-09-15)
+
+Sesion 7 de `protocolo-f2.md` §10 (14:32:47-15:04:55 UTC), con la tabla de pasos y horas.
+
+### Lo que se comprobo, y con que prueba
+
+| Comprobacion | Prueba | Resultado |
+| --- | --- | --- |
+| Perfil del driver en la ruta nueva | carga de CP-1 contra los dos ejecutables | b10909 **OOM** a los 6,1 s; b9925 carga desbordando 5 885 MiB |
+| v255 lee la config de produccion | arrancarlo con ella, sin cargar modelos | acepta `groups` y lista los cinco modelos |
+| `apiKeys`, las dos mitades | con clave, sin clave y con clave incorrecta | 200, 401 y 401 (con clave falsa y con la real) |
+| `apiKeys` con la variable ausente | arrancar v255 sin ella | **no arranca**: falla cerrado, no queda abierto |
+| Catalogo vigente sobre b10909 | peticion real a cada modelo, vision con imagen | los cinco responden; el residente sigue `ready` al entrar cada modelo de `swap`; todos los `llama-server` desde `llamacpp-b10909` |
+| Por el daemon, no por `curl` | `local_status`, `local_classify`, `local_describe_image` | arriba y responden; llama-swap desde `llama-swap-v255` |
+| `doctor` contra la instalacion real | `uv run local-delegate doctor --config ...` | `v255` y `b10909` |
+
+### Defecto encontrado al migrar
+
+`doctor.detect_llamaserver_version` buscaba el primer numero tras `version:`, y b10909 imprime
+`version: 0.4.0-dev (build 10909, ...)`: devolvia **`b0` sin avisar**. Dos tests nuevos, vistos en
+rojo por su propio assert (`'b0' == 'b10909'` y `'b0' is None`) antes del arreglo; un mutante que
+quita el parentesis obligatorio del formato viejo cae solo en el test del semver sin build; y se
+comprobo despues contra el binario real.
+
+### Pendiente
+
+- Comprobar desde la Mac que sigue delegando contra este backend.
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 21b71ee..0835968 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -97,7 +97,22 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
   que lo más probable es que llama-swap esté montando el modelo: arrancar otro no arregla nada. Pasa
   a tener clase propia y mensaje propio.
 
+- **`doctor` leía como `b0` las versiones nuevas de llama.cpp.** Desde que llama.cpp numera en
+  semver, `--version` imprime `version: 0.4.0-dev (build 10909, commit ...)`, y la expresión que
+  buscaba el primer número tras `version:` se quedaba con el `0` **sin avisar**: el doctor daba por
+  desactualizado un build más nuevo que el recomendado. Ahora lee primero `build N` y solo acepta el
+  formato viejo (`version: 9925 (...)`) con el paréntesis detrás, así que un semver sin número de
+  build da «salida inesperada» en vez de una versión inventada. Salió al migrar esta máquina a b10909.
+
 ### Changed
+- **Versiones recomendadas del backend: llama.cpp b10909 y llama-swap v255** (antes b9925 y
+  v238). Son las de la medición del catálogo de modelos, y la producción del autor ya corre sobre
+  ellas con el catálogo de siempre: los cinco modelos cargan y responden por el daemon, el residente
+  sigue cargado al entrar otro modelo y `apiKeys` responde 200 con la clave y 401 sin ella. Dos cosas
+  que conviene saber al actualizar: b10909 trae `--fit on`, que recorta capas en silencio para que
+  el modelo quepa (fija `--fit off -ngl 99` si prefieres un OOM claro), y v255 **no arranca** si
+  falta la variable que referencia `apiKeys`. `doctor` compara contra estos valores.
+
 - **La clasificación de fallos sale de `server.py` a un módulo puro** (`fallos.py`): recibe el
   resultado o la excepción y devuelve la clase, sin red, sin estado y sin decidir reintentos. Es la
   primera de las tres capas que el respaldo entre modelos necesita, y las siete clases de la tabla
diff --git a/docs/wiki/Backend-versions.md b/docs/wiki/Backend-versions.md
index 89f9967..7b12b42 100644
--- a/docs/wiki/Backend-versions.md
+++ b/docs/wiki/Backend-versions.md
@@ -10,8 +10,8 @@ carpetas con las que el autor verifica cada release. Ni requisito ni obligación
 | Componente | Versión probada | Verificado | Notas |
 |---|---|---|---|
 | `local-delegate` | 0.14.0 | 2026-07-30 | esta release |
-| `llama-server` (llama.cpp) | **b9925** | 2026-07-11 | RTX 5060 (Blackwell/sm_120), runtime **CUDA 13.3** |
-| `llama-swap` | **v238** | 2026-07-11 | trae `status` en `/v1/models` (#901) y métricas SQLite (#898) |
+| `llama-server` (llama.cpp) | **b10909** | 2026-09-15 | RTX 5060 (Blackwell/sm_120), runtime **CUDA 13.3**; `--version` pasa a semver (`0.4.0-dev (build 10909, ...)`) y trae `--fit on` por defecto: fija `--fit off -ngl 99` si quieres un OOM claro en vez de capas recortadas en silencio |
+| `llama-swap` | **v255** | 2026-09-15 | acepta la misma config que v238 (`groups`, `apiKeys` con `${env...}`); sin la variable de la clave **no arranca**, en vez de quedar abierto |
 
 > Fuente de verdad: `RECOMMENDED_VERSIONS` en
 > [`src/local_delegate/doctor.py`](../../src/local_delegate/doctor.py). El comando
@@ -28,10 +28,11 @@ Todo vive autocontenido bajo un único raíz (aquí `D:\Projects\llms\`):
 ```
 D:\Projects\llms\              ← raíz único, autocontenido
   ├─ llama-swap\
-  │   ├─ llama-swap.exe        (v238)
   │   └─ config.yaml           (modelos + groups; ver recipes)
-  ├─ llamacpp\
-  │   ├─ llama-server.exe      (b9925)
+  ├─ llama-swap-v255\
+  │   └─ llama-swap.exe        (v255)
+  ├─ llamacpp-b10909\
+  │   ├─ llama-server.exe      (b10909)
   │   └─ *.dll                 (ggml-*, cudart64_13, cublas64_13, cublasLt64_13)
   └─ models\                   (una subcarpeta por modelo)
       ├─ gemma3-4b\*.gguf
@@ -46,7 +47,7 @@ Variables de entorno que enlazan las piezas (en el config del host MCP — Claud
 | Variable | Valor de referencia |
 |---|---|
 | `LOCAL_DELEGATE_BASE_URL` | `http://127.0.0.1:9292/v1` |
-| `LLAMASWAP_EXE` | `D:\Projects\llms\llama-swap\llama-swap.exe` |
+| `LLAMASWAP_EXE` | `D:\Projects\llms\llama-swap-v255\llama-swap.exe` |
 | `LLAMASWAP_CONFIG` | `D:\Projects\llms\llama-swap\config.yaml` |
 
 El detalle de GPU (build CUDA para Blackwell, `-ngl`, flash-attn) está en el
diff --git a/src/local_delegate/doctor.py b/src/local_delegate/doctor.py
index 0cb16dc..123daff 100644
--- a/src/local_delegate/doctor.py
+++ b/src/local_delegate/doctor.py
@@ -31,9 +31,10 @@ from . import autostart, checks, config
 # Versiones del backend verificadas en vivo con esta release de local-delegate. La doc
 # (docs/wiki/Backend-versions.md) las referencia desde aquí para no divergir.
 RECOMMENDED_VERSIONS: dict[str, str] = {
-    # llama.cpp, probado 2026-07-11 en RTX 5060 (Blackwell/sm_120) con runtime CUDA 13.3.
-    "llama-server": "b9925",
-    "llama-swap": "v238",
+    # llama.cpp y llama-swap probados 2026-09-15 en RTX 5060 (Blackwell/sm_120) con runtime CUDA
+    # 13.3: medidos en la tanda de F2 y migrada la produccion del autor (F3, tarea 22).
+    "llama-server": "b10909",
+    "llama-swap": "v255",
 }
 
 # Repos de GitHub para el chequeo opcional --online.
@@ -118,7 +119,10 @@ def detect_llamaserver_version(config_path: Path | None) -> tuple[str | None, st
     text = _run_version(exe)
     if not text:
         return None, f"no se pudo ejecutar {exe} --version"
-    m = re.search(r"version:\s*(\d+)", text)
+    # Dos formatos: el viejo `version: 9925 (ed8c26150)` y, desde que llama.cpp numera en semver,
+    # `version: 0.4.0-dev (build 10909, commit ...)`. Con el primero solo, el segundo daba "b0" sin
+    # avisar. El viejo exige el paréntesis tras el número para que un semver no cuele.
+    m = re.search(r"\bbuild\s+(\d+)", text) or re.search(r"version:\s*(\d+)\s*\(", text)
     if not m:
         return None, f"salida de --version inesperada de {exe}"
     return f"b{m.group(1)}", None
diff --git a/tests/test_doctor.py b/tests/test_doctor.py
index 08068f6..2efc278 100644
--- a/tests/test_doctor.py
+++ b/tests/test_doctor.py
@@ -51,6 +51,30 @@ def test_detect_llamaserver_version_parses_build(tmp_path, monkeypatch):
     assert reason is None
 
 
+def test_detect_llamaserver_version_parses_semver_build(tmp_path, monkeypatch):
+    # Formato de b10909: la version es semver y el numero de build va entre parentesis. Leido con la
+    # regex vieja daba "b0" sin avisar, y el doctor lo marcaba como desactualizado frente a b9925.
+    cfg = tmp_path / "config.yaml"
+    cfg.write_text("models:\n  m:\n    cmd: '/usr/bin/llama-server --port 1'\n", encoding="utf-8")
+    monkeypatch.setattr(
+        doctor,
+        "_run_version",
+        lambda exe: "version: 0.4.0-dev (build 10909, commit a2878d30d)\nbuilt with Clang 20.1.8",
+    )
+    version, reason = doctor.detect_llamaserver_version(cfg)
+    assert version == "b10909"
+    assert reason is None
+
+
+def test_detect_llamaserver_version_semver_without_build_is_not_b0(tmp_path, monkeypatch):
+    cfg = tmp_path / "config.yaml"
+    cfg.write_text("models:\n  m:\n    cmd: '/usr/bin/llama-server --port 1'\n", encoding="utf-8")
+    monkeypatch.setattr(doctor, "_run_version", lambda exe: "version: 0.4.0-dev\nbuilt with Clang")
+    version, reason = doctor.detect_llamaserver_version(cfg)
+    assert version is None
+    assert reason and "inesperada" in reason
+
+
 def test_detect_llamaserver_version_reports_reason_without_config():
     version, reason = doctor.detect_llamaserver_version(None)
     assert version is None
````

### Mensaje A

```
fix(doctor): corregir detección de versión de llama.cpp y actualizar backend

- Corrige el error donde `doctor` leía versiones semver como `b0` debido a una regex incorrecta.
- Actualiza las versiones recomendadas a llama-server `b10909` y llama-swap `v255`.
- Añade tests para validar el nuevo formato de salida `--version` (semver con build).
- Actualiza la documentación técnica, el changelog y los protocolos de migración con los resultados de la sesión F3.
```

### Mensaje B

```
fix(doctor): corregir deteccion de version semver en llama.cpp

- Actualizar doctor.py para buscar 'build N' antes que el numero
  de version, evitando que b10909 se interprete como b0.
- Actualizar RECOMMENDED_VERSIONS a llama-server b10909 y
  llama-swap v255 tras migracion de produccion.
- Agregar tests para formato semver y salida inesperada sin build.
- Actualizar CHANGELOG, wiki y planes con detalles de la migracion.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 26

Diff: 3 ficheros, +29 −0

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index ef4e7f1..485cc43 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,13 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+### Fixed
+- **`doctor` daba 401 falso con el token de Claude Desktop cuando el `Bearer` va dentro de la
+  variable.** Con `--header "Authorization:${AUTH_HEADER}"` y `env.AUTH_HEADER = "Bearer xxx"` —la
+  forma que recomienda `mcp-remote`—, el chequeo quitaba el prefijo `Bearer ` antes de expandir la
+  variable, probaba `Bearer Bearer xxx` contra el daemon y culpaba a un token que era bueno. Ahora lo
+  quita también después de expandir.
+
 ## [0.31.2] - 2026-09-22
 
 ### Fixed
diff --git a/src/local_delegate/checks.py b/src/local_delegate/checks.py
index 766d0ee..d713404 100644
--- a/src/local_delegate/checks.py
+++ b/src/local_delegate/checks.py
@@ -1211,6 +1211,11 @@ def _probe_desktop_auth(ctx: Context) -> Result:
                 arreglo,
             )
         token = _VARIABLE_DE_MCP_REMOTE.sub(valor, token)
+        # Y otra vez aquí, después de expandir: la forma que recomienda `mcp-remote` —y la de la
+        # Mac— es `Authorization:${AUTH_HEADER}` con el `Bearer` DENTRO de la variable. Quitarlo
+        # solo antes de expandir dejaba `Bearer xxx` como token, la prueba mandaba
+        # `Bearer Bearer xxx`, el daemon respondía 401 y el check culpaba a un token que era bueno.
+        token = token.removeprefix("Bearer ").strip()
 
     acepta = ctx.daemon_accepts_token(host, port, token)
     if acepta is None:
diff --git a/tests/test_checks.py b/tests/test_checks.py
index d4899cc..d8fa076 100644
--- a/tests/test_checks.py
+++ b/tests/test_checks.py
@@ -1295,6 +1295,23 @@ def test_desktop_con_variable_referenciada_prueba_su_valor(tmp_path, monkeypatch
     assert llamadas == ["valor-del-entorno"]
 
 
+def test_desktop_con_bearer_dentro_de_la_variable_prueba_solo_el_token(tmp_path, monkeypatch):
+    """La forma de la Mac: `Authorization:${AUTH_HEADER}` y `env.AUTH_HEADER = "Bearer xxx"`.
+
+    Con el prefijo quitado solo antes de expandir, lo que se probaba era `Bearer xxx`, la
+    petición salía con `Bearer Bearer xxx` y el check daba 401 con el token bueno.
+    """
+    monkeypatch.delenv("AUTH_HEADER", raising=False)
+    entry = _desktop_entry(header="Authorization:${AUTH_HEADER}")
+    entry["env"] = {"AUTH_HEADER": "Bearer token-bueno"}
+    llamadas: list[str] = []
+    home = _con_desktop(make_home(tmp_path), entry)
+    result = result_for("service.desktop_auth", _desktop_ctx(home, llamadas=llamadas))
+
+    assert llamadas == ["token-bueno"]
+    assert result.status == checks.OK, result.detail
+
+
 def test_desktop_con_variable_que_no_esta_avisa_como_sospecha(tmp_path, monkeypatch):
     monkeypatch.delenv("TOKEN_DESKTOP_PRUEBA", raising=False)
     llamadas: list[str] = []
```

### Mensaje A

```
fix(local_delegate): corregir 401 falso al extraer Bearer tras expansión

- El chequeo de autenticación removía el prefijo "Bearer " antes de
  expandir variables, pero no después.
- Esto causaba que se enviara "Bearer Bearer <token>" al daemon,
  generando un 401 falso positivo.
- Se añade la limpieza del prefijo después de la expansión de la
  variable de entorno.
- Se agrega prueba para validar el flujo con Bearer dentro de la
  variable.
```

### Mensaje B

```
fix(doctor): corregir error 401 falso al expandir tokens con Bearer

- Elimina el prefijo "Bearer " también después de expandir variables de entorno.
- Evita que se duplique el prefijo (ej. "Bearer Bearer xxx") al validar tokens.
- Actualiza el changelog con la descripción del error corregido.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 27

Diff: 3 ficheros, +108 −23

```diff
diff --git a/.sdd/changes/codeql-alertas-abiertas/handoff.md b/.sdd/changes/codeql-alertas-abiertas/handoff.md
index 582e946..c3e8245 100644
--- a/.sdd/changes/codeql-alertas-abiertas/handoff.md
+++ b/.sdd/changes/codeql-alertas-abiertas/handoff.md
@@ -2,24 +2,50 @@
 
 ## Current state
 
-- SDD status:
-- Last completed gate:
-- Current revision:
+- SDD status: `closed` (modo lite).
+- Last completed gate: `memory`.
+- Current revision: `main` @ `d087b1c` (squash de la PR #133).
 
 ## What changed
 
-- Summarize completed work without reproducing the full Git history.
+Las diez alertas abiertas de code scanning quedaron a cero: seis cerradas como `fixed` por el
+código y cuatro como `dismissed` con motivo y comentario en GitHub.
+
+- **Arreglos:** patrón del extractor del JS del dashboard (`py/bad-tag-filter`); comentario
+  explicativo en los tres `except` vacíos; test de tipografías web buscando la hoja completa con
+  esquema y ruta; test de concurrencia comprobando que el semáforo devuelve sus dos slots.
+- **Descartes:** `#19` (falso positivo intraprocedural en `sysinfo.py`), `#13` (el `BaseException`
+  del canario de macOS es deliberado), `#11` y `#12` (imports perezosos de `ctypes` bajo guarda
+  `win32`, que no se pueden unificar porque `ctypes.wintypes` hay que importarlo aparte).
 
 ## Decisions
 
-- Record decisions that a future session cannot reliably derive from code alone.
+- **El criterio de reparto fue: se arregla si el código queda mejor; se descarta si el único
+  beneficio sería que la herramienta calle.** Por eso `#11`/`#12` y `#13` se descartan aunque sean
+  técnicamente "arreglables": tocar código Windows-only o el manejo de un hilo lector por una regla
+  de estilo mete más riesgo que beneficio.
+- **`codeql.yml` se queda con la suite `security-and-quality`**, aunque sea la fuente del ruido de
+  reglas de estilo: de ahí salieron también las 15 alertas legítimas ya cerradas.
+- **La escalera de `py/bad-tag-filter` se acepta hasta tres vueltas**, con el límite fijado de
+  antemano: a la cuarta objeción la alerta pasaba a descarte por inaplicable (el fondo de esa regla
+  es «no parsees HTML con regex»). No hizo falta.
 
 ## Next action
 
-- State the single best next step and any prerequisite context.
+Nada pendiente de este cambio. Lo único que dejó abierto, para tratar aparte y sin urgencia:
+**`tests/test_daemon.py` no aísla `LOCAL_DELEGATE_WEB_TOKEN`**, así que da cuatro `401 == 200` en
+cualquier máquina que la tenga definida (esta, desde la 0.22.1). En CI no se ve porque allí no
+existe. Se arregla con un `monkeypatch.delenv` o una fixture de entorno limpio.
 
 ## Memory
 
-- Canonical note:
-- Indexes updated:
-
+- Canonical note: `obsidian-vault/projects/local-delegate/jornada-2026-08-03-las-alertas-de-codeql.md`.
+- Indexes updated: los tres.
+  - Memoria del proyecto (Claude Code): jornada nueva, gancho del gotcha de `LOCAL_DELEGATE_WEB_TOKEN`,
+    y **actualización de dos memorias existentes en vez de duplicarlas** —
+    `feedback-verify-full-ci-before-done` (ahora dice que `gh run list` no ve todos los checks) y
+    `control-positivo-no-es-opcional` (ahora exige mirar *qué* assert dispara el mutante).
+  - Índice global de Claude Code: dos punteros transversales (`gh run list` ≠ CI en verde; el mutante
+    que no prueba nada).
+  - Índice de Codex: bloque `Task Group` con nota canónica, conocimiento reutilizable y fallos.
+- Sin secretos ni datos personales en ninguno de los artefactos.
diff --git a/.sdd/changes/codeql-alertas-abiertas/review.md b/.sdd/changes/codeql-alertas-abiertas/review.md
index e791d74..a964f00 100644
--- a/.sdd/changes/codeql-alertas-abiertas/review.md
+++ b/.sdd/changes/codeql-alertas-abiertas/review.md
@@ -2,19 +2,41 @@
 
 ## Verdict
 
-Choose one: `conforms`, `conforms-with-notes`, or `does-not-conform`.
+`conforms-with-notes` — los seis requisitos se cumplen y están verificados contra el repo real, no
+contra una suposición. Las notas son dos hallazgos laterales, ninguno bloqueante.
 
 ## Specification comparison
 
 | Requirement | Implemented | Verified | Notes |
 | --- | --- | --- | --- |
-| REQ-001 | | | |
+| REQ-001 | sí | sí | Hizo falta tres vueltas, y las tres las dictó el check de CodeQL de la PR, no la comprobación local. Salida del extractor idéntica byte a byte en las tres |
+| REQ-002 | sí | sí | Tres comentarios; ningún `except` cambió de tipo ni de cuerpo |
+| REQ-003 | sí | sí | Mutante: `config.WEB_FONTS` forzado a `True` → falla en `assert hoja not in html` |
+| REQ-004 | sí | sí | Mutante dirigido (2 hilos, sin deadlock) → falla solo en la comprobación nueva |
+| REQ-005 | sí | sí | Los cuatro descartados tras el merge; `?state=open` devuelve `[]` |
+| REQ-006 | sí | sí | 13 checks verdes en la PR; los seis workflows de `main` en verde tras el merge |
 
 ## Findings
 
-- List correctness, security, maintainability, or scope findings in severity order.
+1. **El `gh run list` verde no significa CI verde.** El check `CodeQL` de la PR (el que juzga las
+   alertas) es distinto del job `Analyze (python)` (el que corre el análisis), y solo se ve con
+   `gh pr checks`. Estuvo en rojo dos rondas seguidas mientras los tres workflows salían `success`.
+   Es la lección del job fantasma por una puerta nueva, y merece quedar escrita.
+2. **Un control positivo puede no probar nada y parecer que sí.** El primer mutante de REQ-004 hacía
+   fallar el test, pero por un assert que ya existía. Sin mirar *qué* assert disparaba, habría
+   contado como cubierto un cambio que no lo estaba.
+3. **Cuatro tests fallan en máquinas con `LOCAL_DELEGATE_WEB_TOKEN` definida** (`tests/test_daemon.py`,
+   `401 == 200`), desde antes de este cambio. No aíslan la variable de entorno; en CI no se ve
+   porque allí no existe. **Fuera del alcance de este cambio**, pero es deuda real: cualquiera con
+   el token puesto ve su suite en rojo sin motivo.
+4. **La escalera de `py/bad-tag-filter` tiene fondo conocido**: la regla existe para decir «no
+   parsees HTML con regex». Se cerró en tres vueltas porque cada tolerancia era barata y la salida
+   no cambiaba; el plan fijaba de antemano que a la cuarta objeción se pasaba a descarte.
 
 ## Required follow-up
 
-- Identify work that must be completed before closure.
+Nada bloqueante para el cierre. Pendiente de decidir aparte, sin urgencia:
 
+- Aislar `LOCAL_DELEGATE_WEB_TOKEN` en `tests/test_daemon.py` (hallazgo 3), con un `monkeypatch.delenv`
+  o una fixture de entorno limpio.
+- Ninguna acción sobre `codeql.yml`: la suite `security-and-quality` se mantiene tal cual.
diff --git a/.sdd/changes/codeql-alertas-abiertas/state.json b/.sdd/changes/codeql-alertas-abiertas/state.json
index d36426a..1fba0d3 100644
--- a/.sdd/changes/codeql-alertas-abiertas/state.json
+++ b/.sdd/changes/codeql-alertas-abiertas/state.json
@@ -3,9 +3,9 @@
   "slug": "codeql-alertas-abiertas",
   "title": "Cerrar las 10 alertas abiertas de CodeQL: 6 arreglos y 4 descartes",
   "mode": "lite",
-  "status": "verifying",
+  "status": "closed",
   "createdAt": "2026-08-03T22:43:42.806Z",
-  "updatedAt": "2026-08-03T22:57:29.376Z",
+  "updatedAt": "2026-08-04T00:38:41.321Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -26,16 +26,16 @@
       "actor": "user"
     },
     "conformance": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-04T00:33:57.256Z",
+      "evidence": "Revision fresca contra los seis requisitos en review.md: los seis implementados y verificados contra el repo real. gh api code-scanning/alerts?state=open devuelve lista vacia; las 10 quedan 6 fixed y 4 dismissed con motivo. Los seis workflows de main en verde tras el merge. Veredicto conforms-with-notes: tres hallazgos laterales, ninguno bloqueante.",
+      "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-04T00:38:41.151Z",
+      "evidence": "Nota canonica en el vault: projects/local-delegate/jornada-2026-08-03-las-alertas-de-codeql.md. Punteros sincronizados en los tres indices (memoria del proyecto de Claude Code, indice global de Claude Code, indice de Codex). Dos memorias existentes actualizadas en vez de duplicadas: feedback-verify-full-ci-before-done y control-positivo-no-es-opcional. Handoff escrito. Sin secretos ni datos personales.",
+      "actor": "user"
     }
   },
   "history": [
@@ -111,6 +111,43 @@
       "at": "2026-08-03T22:57:29.376Z",
       "evidence": "722 passed / 2 skipped; ruff check y ruff format limpios; node --check ok; salida del extractor identica byte a byte (sha256 6e030c20). Control positivo real en los dos tests: el primer mutante de REQ-004 lo atrapaba un assert previo (deadlock) y se repitio con uno dirigido que solo dispara el assert nuevo. Cuatro fallos preexistentes de test_daemon.py causados por LOCAL_DELEGATE_WEB_TOKEN del entorno, confirmados con git stash y con la variable vacia: fuera de alcance.",
       "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-08-04T00:33:57.055Z",
+      "reason": "Merge hecho (d087b1c), cuatro descartes aplicados y cero alertas abiertas"
+    },
+    {
+      "type": "gate",
+      "gate": "conformance",
+      "status": "approved",
+      "at": "2026-08-04T00:33:57.256Z",
+      "evidence": "Revision fresca contra los seis requisitos en review.md: los seis implementados y verificados contra el repo real. gh api code-scanning/alerts?state=open devuelve lista vacia; las 10 quedan 6 fixed y 4 dismissed con motivo. Los seis workflows de main en verde tras el merge. Veredicto conforms-with-notes: tres hallazgos laterales, ninguno bloqueante.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-08-04T00:33:57.423Z",
+      "reason": "Conformidad aprobada; queda registrar el handoff"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-08-04T00:38:41.151Z",
+      "evidence": "Nota canonica en el vault: projects/local-delegate/jornada-2026-08-03-las-alertas-de-codeql.md. Punteros sincronizados en los tres indices (memoria del proyecto de Claude Code, indice global de Claude Code, indice de Codex). Dos memorias existentes actualizadas en vez de duplicadas: feedback-verify-full-ci-before-done y control-positivo-no-es-opcional. Handoff escrito. Sin secretos ni datos personales.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-08-04T00:38:41.321Z",
+      "reason": "Diez alertas a cero, PR #133 mergeada, memoria persistida"
     }
   ]
 }
```

### Mensaje A

```
docs(codeql): cerrar las 10 alertas de CodeQL y actualizar documentación

- Se resuelven 6 alertas mediante arreglos de código y 4 mediante descartes justificados.
- Se actualizan los archivos de handoff, review y estado del proceso SDD.
- Se registran hallazgos sobre el aislamiento de variables de entorno en tests y la verificación de CI.
- Se sincronizan las memorias del proyecto y los índices de conocimiento.
```

### Mensaje B

```
docs(codeql): cerrar 10 alertas y actualizar memoria
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 28

Diff: 2 ficheros, +120 −31

```diff
diff --git a/.sdd/changes/punteria-hook-read/handoff.md b/.sdd/changes/punteria-hook-read/handoff.md
index 099f070..4660f5d 100644
--- a/.sdd/changes/punteria-hook-read/handoff.md
+++ b/.sdd/changes/punteria-hook-read/handoff.md
@@ -1,25 +1,43 @@
-# Handoff: Arreglar la punteria del hook de lectura y medir la extension
-
-## Current state
-
-- SDD status:
-- Last completed gate:
-- Current revision:
-
-## What changed
-
-- Summarize completed work without reproducing the full Git history.
-
-## Decisions
-
-- Record decisions that a future session cannot reliably derive from code alone.
-
-## Next action
-
-- State the single best next step and any prerequisite context.
-
-## Memory
-
-- Canonical note:
-- Indexes updated:
-
+# Handoff
+
+## Qué se cerró
+
+El hook `suggest_delegate_read` avisaba en 572 de 852 lecturas y sólo 29 apuntaban a algo
+delegable. Ahora se calla ante código y ante lecturas acotadas, y los umbrales suben de 8/32 KB a
+32/100 KB. La telemetría registra `ext` y el motivo del descarte.
+
+Mergeado en **PR #146** (`9453893`), con los 13 checks en verde —CodeQL incluido, que es el que no
+sale en `gh run list`.
+
+## Decisiones que sobreviven a este cambio
+
+- **La conversión cero no era un problema de redacción.** Un control con `claude -p` sobre un
+  archivo de 114 KB mostró que el modelo delega solo cuando la tarea es una transformación global,
+  con hook y sin él. Lo que fallaba era la puntería. Antes de reescribir un aviso que se ignora,
+  mide si el aviso hacía falta.
+- **`markitdown` se obedece siempre con una línea de descripción y sin skill.** No es la prosa: es
+  que si le das un PDF, `Read` no sirve. `delegacion-local`, mucho mejor escrita, se invocó 0 veces
+  en 49 sesiones porque compite contra `Read`, que siempre funciona. La obediencia viene de que la
+  alternativa no exista.
+- **Se descartó el hook que bloquea** (`permissionDecision: deny`). El prototipo funciona y está
+  medido, pero el control negativo dice que el modelo ya delega solo en esos casos.
+- **Excluir todo el código deja sin aviso a `local_explain_code`.** Aceptado a conciencia: 562
+  lecturas de código en 14 días contra 8 llamadas históricas a esa tool. Si hace falta recuperarlo,
+  el sitio es `suggest_delegate_prompt`, que ve la intención y no el tamaño en disco.
+
+## Qué queda abierto
+
+- **Las tools del MCP llegan diferidas en 43 de 49 sesiones.** Es la causa con más peso real de la
+  no-adopción: 601 tools compitiendo, 208 de ellas sin un solo uso en 14 días (MCP_DOCKER 50,
+  Postman 41, Figma 33, Canva 32, Cloudflare 23, Drive 11). No se arregla en este paquete: la
+  mayoría son conectores de la cuenta de claude.ai y se desactivan en su panel de conectores, no en
+  disco.
+- **Esta máquina corre una 0.24.0 instalada desde el repo**, con el hook nuevo dentro. La versión
+  dice 0.24.0 y el código es el de `main`. Se normaliza en la próxima release.
+- El panel no muestra todavía la puntería, aunque el dato (`ext`, `motivo`) ya se registra.
+
+## Estado del entorno tras el cierre
+
+`local-delegate doctor`: todo a punto. Daemon pid 20152, backend arriba, credencial correcta, hook
+instalado idéntico al del repo y verificado en vivo (un `.py` grande no dispara; `CHANGELOG.md` de
+116 KB sí).
diff --git a/.sdd/changes/punteria-hook-read/state.json b/.sdd/changes/punteria-hook-read/state.json
index eeb800e..25427f5 100644
--- a/.sdd/changes/punteria-hook-read/state.json
+++ b/.sdd/changes/punteria-hook-read/state.json
@@ -3,9 +3,9 @@
   "slug": "punteria-hook-read",
   "title": "Arreglar la punteria del hook de lectura y medir la extension",
   "mode": "lite",
-  "status": "understanding",
+  "status": "closed",
   "createdAt": "2026-08-18T12:14:10.407Z",
-  "updatedAt": "2026-08-18T12:22:13.661Z",
+  "updatedAt": "2026-08-18T12:44:23.525Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -32,10 +32,10 @@
       "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-18T12:44:05.564Z",
+      "evidence": "handoff.md con las decisiones durables, lo que queda abierto y el estado del entorno. Sin secretos ni datos personales: la telemetria nueva registra extension y motivo, nunca rutas ni nombres.",
+      "actor": "user"
     }
   },
   "history": [
@@ -77,6 +77,77 @@
       "at": "2026-08-18T12:22:13.661Z",
       "evidence": "verification.md mapea los 6 REQ a evidencia concreta. La regla nueva medida importando el modulo real contra 852 lecturas reales: 572 -> 29 avisos (95% menos), el objetivo de la spec. Prueba en vivo del script fuera de pytest con los tres casos.",
       "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-08-18T12:44:05.564Z",
+      "evidence": "handoff.md con las decisiones durables, lo que queda abierto y el estado del entorno. Sin secretos ni datos personales: la telemetria nueva registra extension y motivo, nunca rutas ni nombres.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "understanding",
+      "to": "researching",
+      "at": "2026-08-18T12:44:22.241Z",
+      "reason": "telemetria y transcripts cruzados en research.md"
+    },
+    {
+      "type": "transition",
+      "from": "researching",
+      "to": "specifying",
+      "at": "2026-08-18T12:44:22.398Z",
+      "reason": "spec.md con 6 requisitos verificables"
+    },
+    {
+      "type": "transition",
+      "from": "specifying",
+      "to": "planning",
+      "at": "2026-08-18T12:44:22.559Z",
+      "reason": "plan.md con 6 tareas y propiedad de ficheros"
+    },
+    {
+      "type": "transition",
+      "from": "planning",
+      "to": "plan-review",
+      "at": "2026-08-18T12:44:22.717Z",
+      "reason": "review.md adversarial, 5 hallazgos sin bloqueantes"
+    },
+    {
+      "type": "transition",
+      "from": "plan-review",
+      "to": "implementing",
+      "at": "2026-08-18T12:44:22.868Z",
+      "reason": "hook, tests, CHANGELOG y docs"
+    },
+    {
+      "type": "transition",
+      "from": "implementing",
+      "to": "verifying",
+      "at": "2026-08-18T12:44:23.045Z",
+      "reason": "752 tests, ruff limpio, dos mutantes y simulacion contra 852 lecturas reales"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-08-18T12:44:23.214Z",
+      "reason": "verification.md mapea los 6 REQ a evidencia"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-08-18T12:44:23.371Z",
+      "reason": "PR #146 mergeado con 13 checks en verde"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-08-18T12:44:23.525Z",
+      "reason": "hook reinstalado y verificado en vivo en esta maquina"
     }
   ]
 }
```

### Mensaje A

```
docs(punteria-hook-read): cerrar tarea y documentar handoff

- Actualiza el handoff con decisiones sobre la puntería del hook
- Registra la resolución de la mejora de umbrales y telemetría
- Cambia el estado de la tarea a 'closed' en state.json
- Añade el historial de transiciones completas del proceso
```

### Mensaje B

```
fix(punteria): cierra hook de lectura y ajusta umbrales
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 29

Diff: 8 ficheros, +85 −42

```diff
diff --git a/.sdd/changes/cierre-total-backlog/state.json b/.sdd/changes/cierre-total-backlog/state.json
index b3d5e79..b05f1c0 100644
--- a/.sdd/changes/cierre-total-backlog/state.json
+++ b/.sdd/changes/cierre-total-backlog/state.json
@@ -3,9 +3,9 @@
   "slug": "cierre-total-backlog",
   "title": "Cierre total del backlog: los puntos vivos, la auditoria del proyecto y la release",
   "mode": "standard",
-  "status": "implementing",
+  "status": "verifying",
   "createdAt": "2026-08-01T16:28:47.746Z",
-  "updatedAt": "2026-08-01T17:22:37.942Z",
+  "updatedAt": "2026-08-01T19:05:48.828Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -20,10 +20,10 @@
       "actor": "user"
     },
     "quality": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-01T19:05:48.156Z",
+      "evidence": "673 passed, 2 skipped; ruff check y format limpios; gitleaks verde en los cuatro PRs; CodeQL: cinco avisos sobre codigo nuevo, los cinco arreglados y ninguno silenciado; Socket depscore de playwright 1.62.0 y pyee 13.0.1 por encima del umbral.",
+      "actor": "user"
     },
     "conformance": {
       "status": "pending",
@@ -96,6 +96,21 @@
       "to": "implementing",
       "at": "2026-08-01T17:22:37.942Z",
       "reason": "Sin hallazgo bloqueante; 8 tareas en PRs por tema"
+    },
+    {
+      "type": "gate",
+      "gate": "quality",
+      "status": "approved",
+      "at": "2026-08-01T19:05:48.156Z",
+      "evidence": "673 passed, 2 skipped; ruff check y format limpios; gitleaks verde en los cuatro PRs; CodeQL: cinco avisos sobre codigo nuevo, los cinco arreglados y ninguno silenciado; Socket depscore de playwright 1.62.0 y pyee 13.0.1 por encima del umbral.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "implementing",
+      "to": "verifying",
+      "at": "2026-08-01T19:05:48.828Z",
+      "reason": "Los cuatro PRs mezclados (#116, #117, #118, #119); se prepara la 0.21.0"
     }
   ]
 }
diff --git a/.sdd/changes/cierre-total-backlog/verification.md b/.sdd/changes/cierre-total-backlog/verification.md
index 6c5f75b..e8fec6c 100644
--- a/.sdd/changes/cierre-total-backlog/verification.md
+++ b/.sdd/changes/cierre-total-backlog/verification.md
@@ -3,53 +3,73 @@
 ## Entorno
 
 - Base: `main` en `1314b0b` (0.20.0 publicada). Suite de partida: **655 passed, 1 skipped**.
-- Python 3.11 (`.venv` del repo), uvicorn 0.51.0, Playwright 1.62.0 + Chromium.
-- CI: `ci.yml` sobre ubuntu/windows/macos, más `install-smoke`, `secrets`, `ci-gate` y CodeQL.
+- Al cierre: **673 passed, 2 skipped**. Python 3.11, uvicorn 0.51.0, Playwright 1.62.0 + Chromium.
+- Entregado en cuatro PRs: **#116, #117, #118, #119**, todos mezclados.
 
 ## Evidencia
 
 | Requisito | Comprobación | Resultado | Evidencia |
 |---|---|---|---|
 | REQ-001 | Procesos reales con `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT`, código de salida pedido al SO | **cumplido** | `serve` 3→0, stdio `0xC000013A`→0. Al revés: neutralizado el arreglo, fallan con `3221225786` y `3` exactos |
-| REQ-002 | Lock tomado y `daemon.json` apuntando a otro puerto | **cumplido** | el mensaje nombra 9393, el pid y el puerto pedido. Control negativo: `daemon.json` huérfano no se anuncia |
-| REQ-003 | `local-delegate --version` | **cumplido** | `local-delegate 0.20.0`, rc=0. Test contra `__version__`, no contra un literal |
+| REQ-002 | Lock tomado y `daemon.json` apuntando a otro puerto | **cumplido** | el mensaje nombra 9393, el pid y el puerto pedido. Control negativo: un `daemon.json` huérfano no se anuncia |
+| REQ-003 | `local-delegate --version` | **cumplido** | `local-delegate 0.21.0`, rc=0. Test contra `__version__`, no contra un literal |
 | REQ-004 | Comando **tal cual quedó en `settings.json`**, ejecutado con el entorno limpio | **cumplido** | emite `additionalContext`. Al revés: sin el argumento, rojo. Control negativo sin la bandera |
 | REQ-005 | Rotación por encima del techo + lectura del check | **cumplido** | tras rotar, `client.observed` sigue viendo a los dos clientes. Al revés: reducido el lector al fichero vivo, rojo |
 | REQ-006 | Playwright contra el dashboard servido | **cumplido** | paginación, rango y rango personalizado. Al revés: neutralizado `pgNext`, 2 de 3 rojos |
-| REQ-007 | `[dependency-groups] ui` | **cumplido** | `uv lock` resuelve playwright 1.62.0; `scripts/dev/README.md` documenta los dos grupos |
+| REQ-007 | `[dependency-groups] ui` | **cumplido** | medido en vivo: `uv sync --group dev --group ui` **ya no desinstala Playwright** |
 | REQ-008 | `scripts/check_install_e2e.py` en los tres sistemas | **cumplido** | verde en `test (macos-latest)`, ubuntu y windows. Control positivo del contador de hooks: 2 → 3 al añadir el de Read |
-| REQ-009 | Nota del vault | pendiente de la release | se actualiza al cerrar |
-| REQ-010 | Release | pendiente | se ejecuta tras mezclar los cuatro PRs |
+| REQ-009 | Backlog del vault | **cumplido** | sin ningún punto abierto; lo no resuelto pasa a decisiones con su medición |
+| REQ-010 | Release 0.21.0 y máquina al día | **cumplido** | publicada, instalada desde PyPI y verificada con una tool real |
 
 ## Comprobaciones de calidad
 
-- [x] **Suite del proyecto en verde**: 667 passed, 1–2 skipped (los saltos son el módulo de
-      navegador fuera del CI y un skip preexistente).
+- [x] **Suite del proyecto**: 673 passed, 2 skipped (los saltos son el módulo de navegador fuera
+      del CI y un skip preexistente).
 - [x] **Lint y formato**: `ruff check` y `ruff format --check` limpios.
-- [x] **Escaneo de secretos**: `gitleaks` verde en el job `secrets` de los cuatro PRs; el hook
-      `Detect hardcoded secrets` de pre-commit pasó en cada commit.
-- [x] **CodeQL**: cinco avisos sobre código nuevo, **los cinco arreglados, ninguno silenciado** —
-      dos `except` sin comentario, un `BaseException` en un test, un import cíclico
-      (`cli` → `server`) y un `import` + `import from` mezclados.
-- [x] **Sin cambios ajenos**: cada PR toca solo su tema; el CHANGELOG solo añade (cero líneas
-      borradas, verificado con `git diff origin/main` en los tres rebases).
+- [x] **Escaneo de secretos**: `gitleaks` verde en los cuatro PRs; el hook de pre-commit pasó en
+      cada commit.
+- [x] **CodeQL**: **cinco** avisos sobre código nuevo, los cinco arreglados y **ninguno
+      silenciado** — dos `except` sin comentario, un `BaseException` en un test, un `import` +
+      `import from` mezclados, y un `return` explícito mezclado con caída implícita. Aparte, el
+      analizador destapó un **ciclo de importación preexistente** (seis alertas) que se arregló de
+      raíz en vez de desactivarse.
+- [x] **Auditoría de dependencias (Socket)**: `playwright@1.62.0` (license 70, supplyChain 79) y
+      `pyee@13.0.1` (100 en todo). Ninguno bajo el umbral. El 79 tiene causa —driver nativo y
+      descarga de navegadores— y alcance acotado: el grupo `ui` no entra en el wheel ni en el sdist.
+- [x] **Sin cambios ajenos**: el CHANGELOG solo añade, cero líneas borradas, verificado con
+      `git diff origin/main` en cada uno de los cinco rebases.
 
 ## Verificación al revés
 
-Regla de la casa aplicada a cada arreglo: **se neutralizó el cambio y se comprobó que el test
-falla, y que falla por lo que dice**. Cinco veces, todas con el resultado esperado. Dos de los
-controles positivos detectaron fallos **en las propias pruebas** antes de que contaran como
-evidencia: el `readline()` sobre un stderr con buffer, y un `select_option("7d")` sobre un valor
-que no existe (`"7"`).
+Regla de la casa aplicada a cada arreglo: **se neutralizó el cambio y se comprobó que el test falla,
+y que falla por lo que dice**. Cinco veces, todas con el resultado esperado.
+
+Dos controles positivos detectaron fallos **en las propias pruebas** antes de que contaran como
+evidencia: un `readline()` sobre un stderr con buffer que colgaba el test, y un
+`select_option("7d")` sobre un valor que no existe (el real es `"7"`). Sin el control, el primero
+habría colgado el CI y el segundo habría pasado por un plazo agotado.
+
+## Premisas del backlog que cayeron al medir — cuatro
+
+1. **El `3` del `CTRL_BREAK` no salía del repo.** Sale de `uvicorn.Server.capture_signals`, que
+   restaura el handler original y **vuelve a lanzar la señal**; para `SIGBREAK` ese original era
+   `SIG_DFL`. Medido con un envoltorio: `serve()` no retornaba y `atexit` no corría.
+2. **El brazo B del A/B no estaba bloqueado por «falta definir la variable».** Estaba bloqueado
+   porque `install --enable-read-hook` **no encendía nada**: dos puertas y la bandera abría una.
+3. **macOS no necesitaba un Mac**, necesitaba un runner — que llevaba tiempo en la matriz del CI.
+4. **Los «filtros de tool/modelo» del panel no existen.** Los controles reales son otros.
 
 ## Desviaciones y riesgo residual
 
-- **Sin comprobador de tipos.** Carencia real, anotada en `research.md` y **fuera de esta tanda**
-  a propósito: es una iniciativa nueva, no deuda del backlog.
+- **Sin comprobador de tipos.** Carencia real, anotada y **fuera de esta tanda** a propósito: es una
+  iniciativa nueva, no deuda del backlog. Se propone aparte.
 - **Codex contra un daemon con token** y **la UI de `elicitation` en un tty** siguen sin medirse.
-  No hay forma de responderlos aquí, y lo que sí era medible ya está medido. Se cierran como
-  decisión escrita, no como «hecho».
-- **El chunking sin memoria entre trozos** no se implementa: el síntoma no se reproduce y el
-  arreglo obvio (solapamiento) es *incorrecto* para `_chat_chunked`, que transforma y concatena.
-- **El brazo B del A/B** queda encendido pero **sin medir**: los datos necesitan días. Lo que esta
-  tanda desbloquea es que encenderlo por fin haga algo.
+  No hay forma de responderlos aquí y lo medible ya está medido; se cierran como decisión escrita,
+  no como «hecho».
+- **El chunking sin memoria entre trozos** no se implementa: el síntoma no se reproduce y el arreglo
+  obvio (solapamiento) es *incorrecto* para `_chat_chunked`, que transforma y concatena.
+- **El brazo B queda encendido pero sin medir**: los datos necesitan días. Lo que esta tanda
+  desbloquea es que encenderlo por fin haga algo.
+- **El cuelgue de `test (windows-latest)` volvió a aparecer** (cuarta vez), con la firma exacta ya
+  documentada: 13:00 clavados = `timeout-minutes: 8` + 5 de gracia. Se resolvió relanzando. No es
+  una avería del repo.
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 355222c..09937e1 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,14 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.21.0] - 2026-08-01
+
+> La tanda del **backlog cerrado entero**: los dos puntos vivos que quedaban, los tres «no
+> auditables» resueltos o cerrados como decisión, y **cinco defectos nuevos** que destapó la
+> auditoría — entre ellos un ciclo de importación real y una opción del instalador que no hacía
+> nada. Cada arreglo verificado **al revés**: neutralizado el cambio, el test se pone rojo por lo
+> que dice.
+
 ### Added
 - **`local-delegate --version`.** Salía con código 2 y un `usage`: el parser raíz exigía subcomando
   y no exponía la bandera, así que la única forma de saber qué versión estaba instalada era
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index 01e8b55..0c91030 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.20.0",
-  "sha256": "1b04c43ddf2e2a969af9e81682db4b3972853f2da2f123689cf6336c8d8afc0a",
-  "bytes": 653195
+  "version": "0.21.0",
+  "sha256": "3cc8e03ef752743822e3243b2c633b61e02f054b303edb078c6ac668357df681",
+  "bytes": 660615
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index a698574..f25a3c4 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index 7287968..5dc8960 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.20.0"
+version = "0.21.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/server.json b/server.json
index 124f9c7..c9ff66b 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.20.0",
+  "version": "0.21.0",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.20.0",
+      "version": "0.21.0",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/uv.lock b/uv.lock
index 185952d..a5809e4 100644
--- a/uv.lock
+++ b/uv.lock
@@ -437,7 +437,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.20.0"
+version = "0.21.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
chore(release): publicar versión 0.21.0 y cerrar backlog

- Actualiza la versión del proyecto a 0.21.0 en todos los archivos de configuración.
- Cambia el estado del cambio de `implementing` a `verifying`.
- Registra la aprobación de la puerta de calidad (`quality gate`) con evidencias de tests, linting y seguridad.
- Actualiza el CHANGELOG con los detalles de la nueva versión.
- Actualiza los metadatos del dashboard y archivos de manifiesto.
```

### Mensaje B

```
feat: cierre total del backlog y release 0.21.0

- Cierra puntos vivos y decisiones pendientes
- Arregla 5 defectos detectados por auditoría
- Actualiza versión a 0.21.0 en todos los artefactos
- Publica release y verifica integridad
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 30

Diff: 4 ficheros, +116 −3

```diff
diff --git a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
index 0fd7bd3..377583f 100644
--- a/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
+++ b/.sdd/changes/delegacion-precisa-y-fiable/protocolo-f2.md
@@ -1442,6 +1442,34 @@ MiB.
 Las configs de los densos estan en `llama-swap-pruebas.yaml` (`t-*`). Las de los dos MoE esperan al
 barrido de `-ncmoe` (§5.1 paso 5).
 
+#### Los candidatos piensan por defecto (tarea 20, 2026-09-15)
+
+**Ningun caso del corpus fija `reasoning_effort`**, asi que lo decide la plantilla del modelo. Medido
+con `llama-server` de b10909 y la config de calidad de cada MoE, la misma pregunta corta con
+`max_tokens` 256:
+
+| Modelo | Sin `chat_template_kwargs` | Con `enable_thinking: false` |
+| --- | --- | --- |
+| Qwen3.6-35B-A3B `-ncmoe 8` | `finish_reason: length`, 256 tokens **todos de razonamiento**, contenido **vacio** (4,0 s) | `stop`, 27 tokens, responde (0,5 s) |
+| Gemma 4 26B-A4B `-ncmoe 0` | `length`, 256 tokens de razonamiento, contenido **vacio** (3,2 s) | `stop`, 11 tokens, responde (0,2 s) |
+| Gemma 4 E4B | `stop` con **226 de 256** tokens, casi todo razonamiento; responde al limite (6,3 s) | `stop`, 12 tokens (0,2 s) |
+| Gemma 4 12B (con `mmproj`) | `stop` con **228 de 256** tokens, casi todo razonamiento (4,6 s) | `stop`, 15 tokens (0,4 s) |
+
+Los cuatro candidatos piensan por defecto. E4B y 12B llegan a contestar con esta pregunta, pero por
+~30 tokens: con un caso de `max_tokens` 16 (`clasificar-53`) o una entrada que haga pensar mas, darian
+vacio igual.
+
+Con los `max_tokens` de produccion (16-2 048), la tanda sin fijar el razonamiento mediria a los
+candidatos por respuestas vacias, no por calidad: el fallo 4 de julio. Los vigentes de texto
+(`llama31-8b`, `qwen25-coder-14b`, `gemma3-4b`) no son modelos de razonamiento.
+
+**Decision del usuario (2026-09-15): todos los candidatos corren con `--reasoning-effort off`**
+(`enable_thinking: false`), que queda en `variant.reasoning_effort` de cada registro. Es como tendria
+que configurarlos produccion con estos `max_tokens`, y compara igual con igual contra vigentes que no
+razonan. Si un candidato gana, F3 lo sube con el razonamiento apagado; medirlo encendido exigiria
+otros `max_tokens`, o sea otro corpus y repetir CP-3. La columna `reasoning_effort` por defecto del
+registro de arriba queda en `off` para todos los candidatos.
+
 Descarga: los **~85 GB** de la lista corta del vault menos los ~5 GB de los candidatos de `fast`, que salen de la tanda, mas los **36,6 GB** del modelo que no cabe de CP-1: **~117 GB** en total, dentro de los 400 GB libres. La cifra se contrasta al descargar; no se deriva de nada mas. `gpt-oss-20b` ya esta. **Qwen3.5-122B-A10B UD-IQ2_XXS
 (36,6 GB) no es candidato**: entra solo como el modelo que no cabe de CP-1.
 
@@ -1617,6 +1645,14 @@ sin comprobar nada.
   (1/24 en un agregado de cuatro casos de seis terminos).
 - **`Shared Usage`**: crece si el pico de una corrida supera la menor primera lectura del modelo en
   el rol. El umbral por defecto es 0 y **esta sin calibrar**: lo fija la tarea 18 al ver CP-1.
+  **Calibrado en la tarea 20 (decision del usuario, 2026-09-15): 1 024 MiB** (`--umbral-shared-mib
+  1024`). Se decidio despues de que el umbral 0 diera «no concluyente» en los tres roles, y por eso
+  quedan escritos los datos que lo sostienen, todos de magnitud y ninguno de quien gana: ruido en la
+  tanda de 0 a 82 MiB por modelo (casi siempre en la primera corrida); ruido en CP-1, antes de la
+  tanda, de +74 MiB en una carga que acabo en OOM; desbordamiento real de 5 666 a 6 114 MiB (CP-1,
+  b9925 sin perfil). Con `--load-mode none` el contador se mueve siempre algo, y con 0 ninguna tanda
+  podria ser concluyente: era un control que no puede dar un resultado distinto. Coste aceptado: un
+  desbordamiento parcial por debajo de 1 GB no se ve aqui; lo sigue impidiendo el perfil (CP-1).
 
 **El hallazgo: con la granularidad real, en `code` la regla puede no disparar nunca.** El corpus
 tiene casos de muy pocos terminos (`commit-diff-19k` tiene **uno**: calidad 0 o 1;
@@ -1778,6 +1814,55 @@ caber en el barrido y no en la config real; las cuatro cargan:
 
 Las configs de techo caben con el mismo `-ncmoe` que las de calidad: no hace falta subirlo. Todas
 estan en `llama-swap-pruebas.yaml` (`t-*`).
+| 5 | 2026-09-15 04:06:37 (§1.4 a las 04:06:36: RAM libre 20,2 GB, VRAM del adaptador 329 MiB, ningun `llama-server`/`llama-swap`/`pythonw`, daemon `Ready`, una sesion de Claude Code; prueba del script a las 04:05:50 con `gemma3-4b` y 1 corrida, fuera de la tanda) | 2026-09-15 04:21:01 (tanda principal, **14,4 min** contra ~45 estimados); `vision` de Gemma 4 12B repetido dos veces por causas distintas —`--ubatch-size` (10:56-10:57) y LUID reasignado tras reiniciar (valida: 11:01:25-11:02:08)— | **~45 min, escrita antes de empezar** (vigentes ~1-4 min por rol con 5 corridas segun los pilotos, sondeos de techo ~3-5 min cada uno, candidatos parecidos, 12 cargas) / pendiente | Tarea 20, la tanda: linea base de los 4 vigentes, calidad de los 4 candidatos (`--reasoning-effort off`) y sondeos de techo de `long` y `code` en su config de 65 536; 5 corridas, `--save-responses`, sonda por proceso | b10909 (`a2878d30d`, CUDA 13.3) | v255, puerto 9595, `llama-swap-pruebas.yaml` (`t-*`) | `none` | pendiente | pendiente |
+
+**Sesion 5, `vision`: Gemma 4 12B se caia con cada imagen, y la causa no era la sospechada.** En la
+tanda dio `http_502` en las 12 corridas. Diagnostico fuera de la tanda (llama-server directo, la
+misma config, la imagen del corpus): carga bien y **aborta al procesar la imagen** con `GGML_ASSERT
+... non-causal attention requires n_ubatch >= n_tokens` (0xC0000409). El codificador de imagen de
+Gemma 4 usa atencion no causal y la imagen son **1 114 tokens**, mas que el `--ubatch-size` por
+defecto (512). No era el `mmproj` ni `--load-mode none`. Con `--batch-size 2048 --ubatch-size 2048`
+responde en 2 s. **No es ajustar la config al resultado**: sin ese flag el modelo no procesa ninguna
+imagen, y produccion necesitaria el mismo; `qwen3-vl-8b` no tiene esa restriccion. El JSONL de los
+12 errores se conserva como `resultados/invalida-ubatch-gemma4-12b.jsonl` y el bloque se repite.
+Para repetirlo se paro otra vez el daemon de produccion (10:51:55 UTC, decision del usuario).
+Repetido de 10:56:04 a 10:57:57 UTC. **Desviacion de §1.4 al arrancarlo: VRAM del adaptador 1 089
+MiB, por encima de los 1 024** (RAM libre 17,8 GB, sin procesos de inferencia). Se anota y no se
+repite: el punto 5 busca algo pintando en la GPU que robe VRAM al modelo, y 65 MiB de mas no cambian
+lo que cabe en un modelo de 6,8 GB de pesos.
+
+**Y esa repeticion tampoco vale: 0 muestras de VRAM en las 30 corridas, todas anuladas
+(`zero_vram_samples`)**, con las respuestas bien. La causa se busco por reproduccion y no por
+suposicion (la primera hipotesis, un `-1` de `typeperf`, era falsa): **el LUID de la NVIDIA cambio de
+`0x00000000_0x0000F722` a `0x00000000_0x0000F336`**. Windows reasigna los LUID al reiniciar, y el
+script de la tanda pasaba `--gpu-luid` fijo con el viejo, asi que la cabecera de `typeperf` nunca
+traia la instancia pedida. Con el LUID nuevo, `typeperf` da valores normales para `gemma3-4b`
+(control) y para Gemma 4 12B con y sin `--ubatch-size 2048`. **Los 7 modelos de la tanda principal
+(04:06-04:20 UTC) se midieron con el LUID correcto** (tienen muestras de VRAM); solo cae esta
+repeticion. Arreglo: el script ya no fija el LUID y el runner lo resuelve contra `nvidia-smi` en cada
+invocacion. El JSONL sin VRAM se conserva como `resultados/invalida-luid-gemma4-12b.jsonl`.
+**Trampa que hereda el cierre:** `~/.claude/relevos/medir-perfil-cp1.ps1` tambien lleva el LUID
+`F722` fijo en su contador de `Shared Usage`; hay que corregirlo antes de medir el perfil al devolverlo
+a produccion, o la prueba leera un contador inexistente.
+
+**Sesion 5, cierre del setup de medicion.** La tanda termino a las 04:21:01 UTC con llama-swap de
+pruebas y `llama-server` parados. **A las 04:31:35 la tarea `LocalDelegateDaemon` volvio a arrancar
+el daemon de produccion** (y su llama-swap en 9292, con b9925), sin intervencion de la sesion que
+mide. No afecta a la tanda, que ya habia cerrado; si a lo que venga despues, porque produccion corre
+**sin perfil del driver** (sigue en b10909). Para la quinta medicion de adopcion de F1 (§1.5), el
+intervalo a descontar de la sesion 3-5 va de 2026-09-14 22:58:35 a 2026-09-15 04:31:35 UTC.
+
+**Sesion 5, escrito durante la tanda y antes de ver al candidato de `code` en el techo:** el sondeo
+`techo-commit-156k` de `qwen25-coder-14b` da `rechazo_por_contexto` en las 5 corridas en ~55 ms, con
+el cuerpo del error `request (47213 tokens) exceeds the available context size (32768 tokens)`.
+**llama-server recorta el `n_ctx` al contexto nativo de entrenamiento del modelo** (32 768 en
+Qwen2.5-Coder, sin YaRN) aunque la config pida 65 536. Es un techo real del modelo tal como corre en
+produccion, no un fallo de la config: el sondeo mide lo que tiene que medir. Dos consecuencias
+escritas ahora, no despues: (1) el `n_ctx` que §6 compara es el **declarado** (65 536 en los dos
+modelos de `code`), y el efectivo del vigente fue 32 768; la comparacion por techo es la del modelo,
+no la de la ventana; (2) el KV medido para `qwen25-coder-14b@65536` (3 456 MiB) reserva 65 536
+celdas aunque la ventana util sea 32 768. `llama31-8b` acepta su sondeo (26 454 tokens de prompt;
+las 5 corridas se cortan por `max_tokens`, que cuenta como aceptada).
 
 Estado de §1.4 al empezar la sesion 4 (§1.4 ya rehecho): RAM libre 20,6 GB; VRAM del adaptador 856
 MiB; ningun `llama-server`, `llama-swap` ni `pythonw`; `LocalDelegateDaemon` en `Ready` (parado); una
diff --git a/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml b/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
index 772aba1..c8481fe 100644
--- a/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
+++ b/benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml
@@ -149,4 +149,4 @@ models:
       ${server} --load-mode none
       --model D:\Projects\llms\models\gemma4-12b\gemma-4-12b-it-Q4_K_M.gguf
       --mmproj D:\Projects\llms\models\gemma4-12b\mmproj-F16.gguf
-      --ctx-size 8192
+      --ctx-size 8192 --batch-size 2048 --ubatch-size 2048
diff --git a/scripts/analizar_benchmark.py b/scripts/analizar_benchmark.py
index f8a613a..8b2932d 100755
--- a/scripts/analizar_benchmark.py
+++ b/scripts/analizar_benchmark.py
@@ -597,13 +597,27 @@ def decidir_rol(
         }
 
     # Latencia de TODOS los casos de calidad: los de pares tambien corren y tardan.
-    (lat_v, lat_c), banda_lat = _latencia_del_rol([vigente, candidato], ids + casos_pares, corpus)
+    # Condicion 3 sobre los casos con latencia medida en LOS DOS (decision del usuario, tarea 20): el
+    # vigente de long se corto en todas las corridas de lint-9k y la media del rol salia vacia, asi que
+    # su fallo vetaba al candidato. Que un modelo no termine un caso ya lo castigan calidad y pares.
+    casos_lat = ids + casos_pares
+    con_latencia = [
+        cid
+        for cid in casos_lat
+        if all(_caso(cfg, cid, corpus).latencia_mediana is not None for cfg in (vigente, candidato))
+    ]
+    (lat_v, lat_c), banda_lat = _latencia_del_rol([vigente, candidato], con_latencia, corpus)
     hay_techo = bool(_casos_del_rol(corpus, rol, "techo"))
     techo_v, techo_c = techo_aceptado(vigente, rol, corpus), techo_aceptado(candidato, rol, corpus)
     resultado.update(
         {
             "debilmente_decidible": len(casos_calidad) < MIN_CASOS_DECIDIBLE and pares_rol is None,
-            "latencia_ms": {"vigente": lat_v, "candidato": lat_c, "banda": banda_lat},
+            "latencia_ms": {
+                "vigente": lat_v,
+                "candidato": lat_c,
+                "banda": banda_lat,
+                "fuera": [cid for cid in casos_lat if cid not in con_latencia],
+            },
             "techo_bytes": {"vigente": techo_v, "candidato": techo_c} if hay_techo else None,
         }
     )
diff --git a/tests/test_analisis_benchmark.py b/tests/test_analisis_benchmark.py
index a225a65..60a4ef2 100644
--- a/tests/test_analisis_benchmark.py
+++ b/tests/test_analisis_benchmark.py
@@ -877,3 +877,17 @@ def test_cabe_uso_diario_es_informativo_y_mira_los_dos_limites():
     assert analizar._cabe_uso_diario(14 * gib, 24 * gib + 1) == "no"
     assert analizar._cabe_uso_diario(None, 1) == "—"
     assert analizar._cabe_uso_diario(1, None) == "—"
+
+
+def test_la_latencia_se_compara_solo_en_los_casos_que_los_dos_terminan():
+    # Tarea 20: llama31-8b se corto por max_tokens en las 5 corridas de lint-9k. Sin latencia en ese
+    # caso, la media del rol salia vacia y la condicion 3 vetaba al candidato por un fallo del vigente.
+    registros = _tanda("vigente", "long", TERCIO)
+    for r in registros:
+        if r["case"] == "lint-9k":
+            r["outcome"] = "truncado"
+            r["score"] = {"quality": 0.0, "zero_by": "truncado_repetido"}
+    d = _decidir(registros + _tanda("candidato", "long", (1.0, 1.0, 1.0)))
+    assert d["latencia_ms"]["fuera"] == ["lint-9k"]
+    assert d["latencia_ms"]["vigente"] is not None
+    assert (d["veredicto"], d["motivos"]) == ("sustituye", [])
```

### Mensaje A

```
fix(benchmark): ajustar latencia y config de Gemma 4 12B
```

### Mensaje B

```
docs(protocolo): documentar tarea 20 y ajustar comparación de latencia

- Añadir detalles sobre el razonamiento por defecto de los candidatos y la decisión de usar `--reasoning-effort off`.
- Registrar el nuevo umbral de calibración para `Shared Usage` (1024 MiB).
- Documentar errores de `ubatch-size` en Gemma 4 12B y problemas de LUID en Windows.
- Añadir nota sobre el límite de contexto efectivo en Qwen2.5-Coder.
- Modificar `analizar_benchmark.py` para comparar latencia solo en casos donde tanto el vigente como el candidato completan la ejecución.
- Actualizar configuración de Gemma 4 12B con `--ubatch-size 2048`.
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 31

Diff: 2 ficheros, +132 −29

```diff
diff --git a/.sdd/changes/doctor-ve-el-token-del-daemon/handoff.md b/.sdd/changes/doctor-ve-el-token-del-daemon/handoff.md
index 1424be4..9a9fa98 100644
--- a/.sdd/changes/doctor-ve-el-token-del-daemon/handoff.md
+++ b/.sdd/changes/doctor-ve-el-token-del-daemon/handoff.md
@@ -1,25 +1,41 @@
-# Handoff: doctor ve cuando la entrada MCP no puede autenticarse contra el daemon
+# Handoff
 
-## Current state
+## Qué se cerró
 
-- SDD status:
-- Last completed gate:
-- Current revision:
+`doctor` ya ve la combinación que hoy daba «todo a punto» con las once tools en 401: entrada MCP
+en modo HTTP, daemon que exige token, y nada con qué autenticarse.
 
-## What changed
+Mergeado en **PR #152** (`0a03477`), con el CI en verde.
 
-- Summarize completed work without reproducing the full Git history.
+## Decisiones que sobreviven
 
-## Decisions
+- **El check nuevo NO sustituye a `service.credential`, lo acompaña.** Aquel mira la puerta del
+  backend (¿tiene el proceso MCP la API key?) y este la del daemon (¿puede el cliente entrar al
+  puerto?). Se cierran por separado: el día de la avería la del backend estaba bien.
+- **Vive en `servicio` y no en `andamiaje`**, porque pregunta al puerto y ese grupo no sale a la
+  red por contrato — es lo que permite a `install` correr su reporte sin tocar nada externo.
+- **Los dos avisos tienen fuerza distinta a propósito.** «No hay cabecera» es una avería segura;
+  «la variable está vacía en el entorno de `doctor`» es una sospecha con testigo, porque el
+  cliente puede haberse lanzado desde otra consola. Redactarlos igual haría de la segunda una
+  certeza falsa.
+- **Las entradas `stdio` no cuentan aquí.** No hablan con el puerto, y de su problema ya avisa
+  `service.credential`; contarlas sería falso positivo y aviso duplicado.
+- **Tres clientes, tres vocabularios** (`headers.Authorization`, `bearer_token_env_var`,
+  `{env:VAR}`). El probe los traduce a uno solo en un punto, en vez de comparar tres formatos en
+  el sitio de la decisión.
 
-- Record decisions that a future session cannot reliably derive from code alone.
+## Qué queda abierto
 
-## Next action
+- **`install` sigue borrando la cabecera al reinstalar sin `--web-token-env`.** Fuera de alcance
+  a propósito: es otro fichero y otra decisión (¿conservar lo que había? ¿avisar?). Ahora al menos
+  `doctor` lo dice al momento siguiente.
+- **Claude Desktop sigue fuera del registro de clientes**, así que este check tampoco lo mira. Es
+  el punto de backlog abierto desde el 2026-08-06.
+- El check depende de que `doctor` corra en un entorno parecido al del cliente. Ese límite está
+  escrito en el docstring y es la razón de que el segundo aviso sea sospecha y no veredicto.
 
-- State the single best next step and any prerequisite context.
+## Nota de operación
 
-## Memory
-
-- Canonical note:
-- Indexes updated:
+En esta máquina, `install` necesita **dos** flags y no uno:
 
+    local-delegate install --mcp-mode http --web-token-env --enable-read-hook --agents
diff --git a/.sdd/changes/doctor-ve-el-token-del-daemon/state.json b/.sdd/changes/doctor-ve-el-token-del-daemon/state.json
index abc6ac5..195b1c6 100644
--- a/.sdd/changes/doctor-ve-el-token-del-daemon/state.json
+++ b/.sdd/changes/doctor-ve-el-token-del-daemon/state.json
@@ -3,9 +3,9 @@
   "slug": "doctor-ve-el-token-del-daemon",
   "title": "doctor ve cuando la entrada MCP no puede autenticarse contra el daemon",
   "mode": "standard",
-  "status": "understanding",
+  "status": "closed",
   "createdAt": "2026-08-18T14:38:59.586Z",
-  "updatedAt": "2026-08-18T14:41:03.912Z",
+  "updatedAt": "2026-08-18T14:52:49.341Z",
   "gates": {
     "spec": {
       "status": "approved",
@@ -20,22 +20,22 @@
       "actor": "user"
     },
     "quality": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-18T14:48:04.961Z",
+      "evidence": "uv run pytest: 769 passed 2 skipped (eran 762); ruff check y format limpios. Dos mutantes uno a uno: el que nunca avisa y el que avisa siempre, cada uno falla un solo test y el correcto.",
+      "actor": "user"
     },
     "conformance": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-18T14:48:05.115Z",
+      "evidence": "verification.md mapea los 7 REQ. Verificado contra la maquina real: con la cabecera doctor da ok, quitandola da warn nombrando a Claude Code y el 401, y restaurando vuelve a ok. Antes de este cambio los tres estados daban 'todo a punto'.",
+      "actor": "user"
     },
     "memory": {
-      "status": "pending",
-      "updatedAt": null,
-      "evidence": null,
-      "actor": null
+      "status": "approved",
+      "updatedAt": "2026-08-18T14:52:47.889Z",
+      "evidence": "handoff.md con las decisiones durables, lo que queda abierto y la nota de operacion de los dos flags. Sin secretos: el check nombra la variable, nunca su valor.",
+      "actor": "user"
     }
   },
   "history": [
@@ -61,6 +61,93 @@
       "at": "2026-08-18T14:41:03.912Z",
       "evidence": "plan.md con 5 tareas y propiedad de ficheros; review.md adversarial con 5 hallazgos, ninguno bloqueante: H1 (el guardian del conteo obliga a tocar seis sitios) entra como tarea y H2 (comprobar que daemon_needs_token no avisa en maquinas sanas) pasa a verificacion obligatoria.",
       "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "quality",
+      "status": "approved",
+      "at": "2026-08-18T14:48:04.961Z",
+      "evidence": "uv run pytest: 769 passed 2 skipped (eran 762); ruff check y format limpios. Dos mutantes uno a uno: el que nunca avisa y el que avisa siempre, cada uno falla un solo test y el correcto.",
+      "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "conformance",
+      "status": "approved",
+      "at": "2026-08-18T14:48:05.115Z",
+      "evidence": "verification.md mapea los 7 REQ. Verificado contra la maquina real: con la cabecera doctor da ok, quitandola da warn nombrando a Claude Code y el 401, y restaurando vuelve a ok. Antes de este cambio los tres estados daban 'todo a punto'.",
+      "actor": "user"
+    },
+    {
+      "type": "gate",
+      "gate": "memory",
+      "status": "approved",
+      "at": "2026-08-18T14:52:47.889Z",
+      "evidence": "handoff.md con las decisiones durables, lo que queda abierto y la nota de operacion de los dos flags. Sin secretos: el check nombra la variable, nunca su valor.",
+      "actor": "user"
+    },
+    {
+      "type": "transition",
+      "from": "understanding",
+      "to": "researching",
+      "at": "2026-08-18T14:52:48.057Z",
+      "reason": "la averia vivida y el hueco leido en checks.py"
+    },
+    {
+      "type": "transition",
+      "from": "researching",
+      "to": "specifying",
+      "at": "2026-08-18T14:52:48.214Z",
+      "reason": "spec.md con 7 requisitos"
+    },
+    {
+      "type": "transition",
+      "from": "specifying",
+      "to": "planning",
+      "at": "2026-08-18T14:52:48.381Z",
+      "reason": "plan.md con 5 tareas"
+    },
+    {
+      "type": "transition",
+      "from": "planning",
+      "to": "plan-review",
+      "at": "2026-08-18T14:52:48.545Z",
+      "reason": "review.md adversarial, 5 hallazgos sin bloqueantes"
+    },
+    {
+      "type": "transition",
+      "from": "plan-review",
+      "to": "implementing",
+      "at": "2026-08-18T14:52:48.710Z",
+      "reason": "probe, registro, conteo y tests"
+    },
+    {
+      "type": "transition",
+      "from": "implementing",
+      "to": "verifying",
+      "at": "2026-08-18T14:52:48.869Z",
+      "reason": "769 tests, dos mutantes y la averia reproducida en la maquina real"
+    },
+    {
+      "type": "transition",
+      "from": "verifying",
+      "to": "result-review",
+      "at": "2026-08-18T14:52:49.023Z",
+      "reason": "verification.md mapea los 7 REQ"
+    },
+    {
+      "type": "transition",
+      "from": "result-review",
+      "to": "closing",
+      "at": "2026-08-18T14:52:49.178Z",
+      "reason": "PR #152 mergeado"
+    },
+    {
+      "type": "transition",
+      "from": "closing",
+      "to": "closed",
+      "at": "2026-08-18T14:52:49.341Z",
+      "reason": "doctor verificado en los tres estados"
     }
   ]
 }
```

### Mensaje A

```
docs(sdd): cerrar tarea de autenticación del daemon en doctor

- Actualiza el handoff con las decisiones técnicas y temas pendientes
- Cambia el estado de la tarea a 'closed' en el archivo de estado
- Registra la aprobación de los gates de calidad, conformidad y memoria
```

### Mensaje B

```
feat(doctor): cierra verificación de token del daemon

- Aprueba calidad, conformidad y memoria
- Actualiza handoff con decisiones y estado abierto
- Registra transiciones y evidencias en state.json
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 32

Diff: 6 ficheros, +11 −8

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 1984cbb..5c5ebbc 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.24.0] - 2026-08-04
+
 ### Fixed
 - **`local_commit_msg` deja de redactar el mensaje sobre el principio del diff.** Era la única tool
   de reducción que seguía truncando la entrada: por encima de 20 000 caracteres, el resto se
@@ -1552,7 +1554,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 - Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
   registro oficial de MCP.
 
-[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.23.0...HEAD
+[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.24.0...HEAD
+[0.24.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.23.0...v0.24.0
 [0.23.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.1...v0.23.0
 [0.22.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.0...v0.22.1
 [0.22.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.21.0...v0.22.0
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index 1068911..c5f3b22 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.23.0",
-  "sha256": "8d82f6870f4440508aaabefaf0431b61854ffc120b283dee64156cd80efe22dd",
-  "bytes": 670248
+  "version": "0.24.0",
+  "sha256": "1f421a75c6d889edf44ac593fcdad315aa8ce2fb1098da50488860ca0049bd13",
+  "bytes": 670197
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index f5a61f9..806ded0 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index 26fb5cb..ae1c10b 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.23.0"
+version = "0.24.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/server.json b/server.json
index ae3ba2d..614738e 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.23.0",
+  "version": "0.24.0",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.23.0",
+      "version": "0.24.0",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/uv.lock b/uv.lock
index ad6c370..e5cbfe2 100644
--- a/uv.lock
+++ b/uv.lock
@@ -437,7 +437,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.23.0"
+version = "0.24.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
chore(release): subir versión a 0.24.0

- Actualizar versión en pyproject.toml, server.json y uv.lock
- Actualizar CHANGELOG.md con la nueva versión
- Actualizar metadatos de dashboard.json y assets
```

### Mensaje B

```
feat: lanzamiento v0.24.0 y corrección en local_commit_msg
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 

## Par 33

Diff: 6 ficheros, +11 −8

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 3cac857..cfeb8d8 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -6,6 +6,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 
 ## [Unreleased]
 
+## [0.19.0] - 2026-07-31
+
 ### Added
 - **`doctor` mira si el cliente podrá autenticarse contra el backend, y no solo si el backend está
   vivo.** Nace `service.credential`, la comprobación **nº16**. Sale de una avería real que **ningún
@@ -1121,7 +1123,8 @@ y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).
 - Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
   registro oficial de MCP.
 
-[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.18.1...HEAD
+[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.19.0...HEAD
+[0.19.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.18.1...v0.19.0
 [0.18.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.18.0...v0.18.1
 [0.18.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.17.0...v0.18.0
 [0.17.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.16.0...v0.17.0
diff --git a/docs/assets/dashboard.json b/docs/assets/dashboard.json
index 4c41f42..3f1869e 100644
--- a/docs/assets/dashboard.json
+++ b/docs/assets/dashboard.json
@@ -11,7 +11,7 @@
     "Lo comprueba `tests/test_captura.py`. Procedimiento: docs/wiki/Publishing.md."
   ],
   "file": "dashboard.png",
-  "version": "0.18.1",
-  "sha256": "e446bf8c101807e6787f8d111256c22d521e8cd76fb7bcbdbd97c50a12ecc2af",
-  "bytes": 620633
+  "version": "0.19.0",
+  "sha256": "ecb5cbdbabafc02577e50635ac142d2b21cf400803255395732763f63ac183db",
+  "bytes": 610728
 }
diff --git a/docs/assets/dashboard.png b/docs/assets/dashboard.png
index 9bc407f..373ef35 100644
Binary files a/docs/assets/dashboard.png and b/docs/assets/dashboard.png differ
diff --git a/pyproject.toml b/pyproject.toml
index 873a7eb..a7344ae 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "local-delegate-mcp"
-version = "0.18.1"
+version = "0.19.0"
 description = "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota."
 readme = "README.md"
 requires-python = ">=3.11"
diff --git a/server.json b/server.json
index 32a7ef9..45c285d 100644
--- a/server.json
+++ b/server.json
@@ -6,12 +6,12 @@
     "url": "https://github.com/ZahiriNatZuke/local-delegate",
     "source": "github"
   },
-  "version": "0.18.1",
+  "version": "0.19.0",
   "packages": [
     {
       "registryType": "pypi",
       "identifier": "local-delegate-mcp",
-      "version": "0.18.1",
+      "version": "0.19.0",
       "transport": { "type": "stdio" },
       "environmentVariables": [
         {
diff --git a/uv.lock b/uv.lock
index 8b5d369..e15efc4 100644
--- a/uv.lock
+++ b/uv.lock
@@ -360,7 +360,7 @@ wheels = [
 
 [[package]]
 name = "local-delegate-mcp"
-version = "0.18.1"
+version = "0.19.0"
 source = { editable = "." }
 dependencies = [
     { name = "fastapi" },
```

### Mensaje A

```
chore: realiza tareas de mantenimiento

- Actualiza varios archivos
- Mejora algunos detalles
- Ajusta el contenido existente
```

### Mensaje B

```
chore(release): actualizar versión a 0.19.0

- Actualizar versión en pyproject.toml, server.json y uv.lock
- Registrar cambios en CHANGELOG.md
- Actualizar metadatos de dashboard.json y assets
```

Inventa A (s/n): 
Inventa B (s/n): 
Lo principal A (s/p/n): [opcional] 
Lo principal B (s/p/n): [opcional] 
Específico A (s/n): [opcional] 
Específico B (s/n): [opcional] 
Mejor (A/B/=): 
