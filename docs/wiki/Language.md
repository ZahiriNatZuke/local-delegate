# Idioma

Desde la 0.36.0, `local-delegate` habla en español o en inglés: el CLI (con su `--help`),
`doctor`, las salidas de las tools MCP y `local_status`, los hooks, `install`/`update`/`uninstall`,
la skill `local-delegation`, el bloque de memoria de `CLAUDE.md`/`AGENTS.md` y el catálogo que se
inserta en los subagentes. El panel web tiene su propio selector (ver
[Savings & metrics](Savings-and-metrics.md#idioma)). Los nombres de comandos, opciones, variables,
tools y claves JSON no se traducen.

## Cómo se elige (precedencia)

Cada proceso resuelve su idioma una vez, en este orden; el primer paso que da resultado decide:

1. **`LOCAL_DELEGATE_LANG`** — `es` o `en`, con o sin región (`es-MX`, `en_US`, `es-419`), sin
   distinguir mayúsculas. Un valor no válido (`fr`, `english`) se ignora con aviso. Origen:
   «variable».
2. **La preferencia guardada** — el fichero `language.json` del directorio de datos (el mismo de
   los logs: `%LOCALAPPDATA%\local-delegate` en Windows, `~/Library/Application Support/local-delegate`
   en macOS, `~/.local/share/local-delegate` en Linux, o `LOCAL_DELEGATE_LOG_DIR`). Origen:
   «preferencia».
3. **El sistema** — en Windows, el idioma de la **interfaz** (no el formato regional); en Linux y
   macOS, `LC_ALL`, `LC_MESSAGES`, `LANG` y `LANGUAGE`. `C`/`POSIX` no declaran idioma. Origen:
   «sistema».
4. **La reserva** — inglés. Origen: «reserva».

Lo que empieza por `es` es español; cualquier otra cosa, inglés.

## Por qué hay un fichero de preferencia

El daemon (tarea programada, `launchd`, `systemd`) y los hooks no ven el entorno de tu terminal,
así que una `LOCAL_DELEGATE_LANG` puesta en la shell no les llega. Por eso **`install` y `update`
guardan en `language.json` el idioma de la sesión en la que los ejecutas**, con su origen
(`{"lang": "es", "source": "variable"}`). Ese fichero llega igual al CLI, al servidor MCP, al daemon
y a los hooks, sin tocar lanzadores ni `settings.json`.

Regla de escritura:

- si la sesión tiene `LOCAL_DELEGATE_LANG`, se guarda (es una elección explícita);
- si el idioma sale del sistema, se guarda solo si no había fichero o lo guardado también vino
  del sistema: **una elección explícita no se pisa nunca**;
- si la sesión no declara idioma (reserva), el fichero no se toca.

`uninstall` (completo) borra `language.json`. Con `--home` apuntando a un HOME de prueba no se
toca, salvo que también fijes `LOCAL_DELEGATE_LOG_DIR`.

## Elegir español (o inglés)

```bash
LOCAL_DELEGATE_LANG=es local-delegate install      # o update
```

En PowerShell: `$env:LOCAL_DELEGATE_LANG = "es"; local-delegate install`. Reinicia el daemon
(`local-delegate update` lo hace) para que tome el idioma nuevo.

## Volver a seguir al sistema

Una elección explícita se queda aunque cambies el idioma del sistema. Para volver a seguirlo,
**borra `language.json` y ejecuta `install`** sin la variable: guardará
`{"lang": "<el del sistema>", "source": "system"}`. `doctor` te lo recuerda con la ruta exacta
cuando el idioma vigente viene de una elección explícita.

## Qué se instala en cada idioma

`install` escribe en el idioma vigente (el que queda tras guardar la preferencia):

- la skill: `SKILL.md` es la versión de ese idioma (en el paquete, `SKILL.md` en español y
  `SKILL.en.md` en inglés, con las mismas tools y los mismos argumentos);
- el bloque gestionado de `CLAUDE.md`/`AGENTS.md`: reinstalar en el otro idioma lo reemplaza y
  deja uno solo;
- con `--agents`, el bloque de catálogo de los subagentes. La sección de delegación se reconoce
  por su encabezado en español («Delegación a modelos locales») o en inglés («Delegation to local
  models»).

`update` no cambia de idioma lo que ya está al día: un bloque o un catálogo en español o en
inglés que coincide con el empaquetado da `OK` en `doctor` y no se reescribe. Para pasar el
bloque y la skill al otro idioma, usa `install`.

El script de autocompletado (`install --shell-completion`) es la excepción: sus descripciones
salen en el idioma configurado al generarlo, y `update` **sí** lo regenera en el idioma vigente.
`local-delegate completion <shell>` a mano sale en el idioma de la sesión. Ver
[Autocompletado del shell](Integration-install.md#autocompletado-del-shell).

## Cómo ver el idioma vigente

- `local-delegate doctor` muestra en la cabecera `Idioma: <lang> (<origen>; <ruta de language.json>)`.
- `local_status` muestra lo mismo para el proceso servidor (el daemon incluido).

Si los dos no coinciden, el daemon arrancó antes de guardar la preferencia: reinícialo.

## Idioma de la respuesta del modelo

Aparte del idioma de la interfaz, `LOCAL_DELEGATE_OUTPUT_LANGUAGE` y
`LOCAL_DELEGATE_COMMIT_LANGUAGE` eligen en qué idioma responde el modelo local en las tools de
texto libre y en `local_commit_msg`; ver [Configuration](Configuration.md).
