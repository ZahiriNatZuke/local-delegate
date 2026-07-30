# Brief: doctor compara la version instalada contra la publicada en PyPI

## Problem

`local-delegate doctor` diagnostica el andamiaje, los servicios y las versiones del **backend**
(llama-swap y llama-server), pero **no mira nunca su propia versión frente a lo publicado**. El
resultado es que una instalación vieja pasa el diagnóstico sin una sola señal.

Pasó de verdad el 2026-07-30: con el CLI en **0.16.0** y la **0.17.0 ya publicada**, `doctor`
imprimía `Resultado: todo a punto (andamiaje, servicios y versiones probadas)`.

El dato para detectarlo ya existe en el repo, repartido en dos módulos que hoy no se hablan para
esto:

- `checks._installed_version()` (`checks.py:210-219`) devuelve la versión instalada vía
  `importlib.metadata`; hoy solo la usan `cli.path` (para el texto) y `service.daemon` (para
  detectar que el daemon sirve código viejo).
- `update.latest_version()` (`update.py:259-280`) devuelve la última publicada consultando el
  **índice simple** de PyPI. Solo la usa `update`, y para eso hay que ejecutarlo.

Es decir: `doctor` sabe qué versión hay instalada y el repo sabe cómo preguntar cuál es la última,
pero nadie junta las dos cosas.

## Desired outcome

`local-delegate doctor` incluye en el grupo `entorno` una comprobación más que compara la versión
instalada con la última publicada en PyPI:

- instalada < publicada → `[WARN]` con la pista de qué comando actualiza;
- instalada == publicada → `[ OK ]`;
- instalada > publicada → `[ OK ]` (repo por delante de lo publicado, caso normal en desarrollo);
- sin red, PyPI ilegible o versión instalada desconocida → `[ -- ]` con el motivo, sin contar
  como aviso.

Y —requisito igual de importante que el anterior— `install` y `update` **siguen sin salir a
internet por correr el grupo `entorno`**.

## In scope

- Un check nuevo en el registro `checks.CHECKS`, grupo `entorno`.
- Un colaborador inyectable en `checks.Context` para la consulta a PyPI, en la línea de los tres
  que ya existen (`daemon_status`, `backend_models`, `version_of`), de modo que los tests no
  salgan a la red.
- Que `cli.py` (reporte final de `install`) y `update.py` inyecten el colaborador que **no**
  consulta.
- Actualizar los cuatro sitios del módulo que dicen el tamaño del registro (hay un test que lo
  exige) y el CHANGELOG.

## Out of scope

- **Arreglar la caché de PyPI** (que `update` anuncie la versión anterior justo tras publicar).
  Es un pendiente aparte, con su propio change, y aquí solo se hereda el comportamiento actual de
  `latest_version()` tal cual está.
- **Que `doctor` actualice nada.** `probe` nunca escribe; esta comprobación tampoco. Lo único que
  aporta es el `fix_hint`.
- **Que `update` actualice el CLI de `uv tool`.** Es otro pendiente; aquí el `fix_hint` se limita
  a decir el comando que hoy resuelve el caso.

## Constraints and risks

- **`doctor` deja de ser un diagnóstico puramente local.** Decisión tomada explícitamente por el
  usuario: el check consulta siempre, con timeout corto, porque nadie corre `doctor --online` a
  diario y el valor está en que la señal aparezca sin pedirla. Medido por ejecución: dos consultas
  seguidas al índice simple tardaron **0.08 s y 0.07 s**. Sin red, el coste tope es el timeout.
- **Riesgo principal: sacar a la red a quien no lo pidió.** El reporte final de `install` corre
  los grupos `entorno` y `andamiaje` (`cli.py:157`), y `update` corre el registro entero
  (`update.py:585`). Los dos construyen el `Context` sin más colaboradores, así que un check que
  consulte por defecto **los ataría a internet**. Es exactamente lo que el filtro por grupos se
  añadió a evitar («instalar unos hooks no es motivo para salir a la red»,
  `checks.run_all` docstring). Mitigación: los dos inyectan el colaborador que no consulta, y
  hay verificación por test de que no se toca la red.
- **`update` ya consulta PyPI por su cuenta.** Dejar que además corra el check duplicaría la
  llamada en el mismo comando.
- **Ciclo de imports.** `update` importa `checks`, así que `checks` no puede importar `update` a
  nivel superior. El módulo ya resuelve esto para `daemon` y `doctor` con imports diferidos, y el
  docstring explica el porqué.
- **`doctor._vnum()` NO sirve para comparar aquí**: extrae *un solo* número (`'v238' -> 238`), que
  es lo que necesitan las versiones del backend. Comparar semver de tres partes pide la misma
  clave que ya usa `latest_version()` para ordenar (`[int(p) for p in re.findall(r"\d+", v)]`).
- **Verdad duplicada.** «Cuál es la última publicada» debe seguir teniendo **una sola** definición
  (`update.latest_version`), por el mismo motivo por el que `daemon_host_port()` se hizo pública:
  dos derivaciones del mismo dato ya costaron caro en este repo.

## Open questions

- ~~¿El check consulta siempre o solo con `--online`?~~ **Resuelto por el usuario:** siempre, con
  timeout corto y degradando a `[ -- ]` si no hay red.
