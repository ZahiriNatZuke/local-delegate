# Especificación: restos menores de tres SDD cerrados

## Resumen

Pulido y tests pendientes de `backend-extra-params` (§1.13), `cli-completion` (§1.14) y
`retire-legacy-aliases` (§1.15) del backlog, más tres decisiones de producto del usuario
(2026-10-21): tema del panel según el sistema y dos avisos nuevos de `doctor`.

## Requisitos

### Panel (§1.13.3, §1.13.4)

- **REQ-001 — Booleanos `on`/`off` en el panel.** El diálogo de parámetros del backend pinta los
  booleanos (`enable_thinking` y cualquier otro de la lista cerrada) como `on`/`off`, igual que la
  CLI, `doctor` y `local_status`; nunca `true`/`false`.
- **REQ-002 — Tema según el sistema.** Sin elección guardada (`localStorage` `ld-theme` ausente o
  ilegible), el panel arranca con el tema de `prefers-color-scheme` y lo sigue en vivo si el sistema
  cambia. Con elección guardada, manda la elección y el cambio del sistema no la pisa. El botón de
  tema sigue alternando y guardando como hoy. Sin parpadeo visible del tema equivocado al cargar en
  la medida en que lo permita el HTML servido (el atributo se fija antes de pintar).

### Parámetros del backend (§1.13.1, §1.13.2)

- **REQ-003 — Test de «resolver una vez por operación» (REQ-012 de `backend-extra-params`).** Un
  test reescribe el fichero de parámetros entre dos trozos de una operación troceada y comprueba que
  todos los trozos llevan los parámetros resueltos al empezar. Debe fallar si la resolución se hace
  por llamada (control positivo con un mutante que lo demuestre).
- **REQ-004 — Presupuesto mínimo de razonamiento para el rol `code`.** Medir en vivo (backend real,
  ventana de pruebas marcada) los presupuestos 512, 1024 y 2048 con `truncated_out` y la calidad de
  la respuesta, con criterio fijado antes de medir y `--repeat 3`; documentar el mínimo
  recomendable en la wiki de `backend-params`. Que `set` avise por debajo es opcional y solo si la
  medición da un mínimo claro.

### Autocompletado e instalador (§1.14)

- **REQ-005 — `uninstall` no deja carpetas vacías que creó `install`.** Con HOME simulado, tras
  `install --shell-completion …` + `uninstall`, no quedan `Documents/` ni
  `.local/share/local-delegate/` vacías si las creó el instalador. Nunca se borra una carpeta que
  tenga contenido ajeno ni una que existía antes.
- **REQ-006 — Guardia de perfiles reales para todos los shells.** El fixture
  `real_profiles_untouchable` vigila también `.bashrc`, `.bash_profile` y `.zshrc` del usuario real.
- **REQ-007 — Política simulada marcada.** Con HOME simulado, la línea de política de ejecución de
  PowerShell dice que es la supuesta, no la efectiva (texto por catálogo es/en).
- **REQ-008 — Línea final del `--dry-run` de solo autocompletado.** Termina con la misma línea final
  de dry-run que los demás modos.
- **REQ-009 — Comentarios en inglés** en `shell_profiles.py`, `install.py`, `cli.py`, `update.py`
  (los añadidos por `cli-completion`; los textos al usuario no se tocan).
- **REQ-010 — El manifiesto valida `lang`.** `completion.py` rechaza o ignora con aviso un `lang`
  que no sea un idioma conocido del catálogo.
- **REQ-011 — «No escribe en disco» de verdad.** La prueba de que `completion` no escribe en disco
  vigila también HOME y el directorio temporal, no solo el de trabajo.

### `doctor` (§1.15.1, §1.15.4)

- **REQ-012 — Aviso de `settings.json` no UTF-8.** Si un `settings.json` que `doctor` lee no es
  UTF-8 válido (con o sin BOM), `doctor` da WARN con la ruta y la causa, aunque el contenido parsee
  como JSON. Un UTF-8 con BOM sigue siendo válido (REQ-026 de `retire-legacy-aliases`).
- **REQ-013 — Aviso de la copia `.bak` de la migración.** Si existe
  `~/.claude/settings.json.retired-names.bak` (o sus variantes con fecha), `doctor` da WARN con la
  ruta, dice que puede contener claves del `env` y sugiere borrarla tras comprobar la migración.
  Nunca imprime su contenido. Sin la copia, no aparece nada. Textos es/en; fila en la wiki de
  `doctor`.

## Fuera de alcance

§1.15.2 (resuelto fuera del repo), §1.15.3 (solo con caso real), §1.15.5 (0.41.0).

## Trazabilidad

| REQ | Backlog | Lote |
|---|---|---|
| 001, 002 | §1.13.3, §1.13.4 | L3 panel |
| 003 | §1.13.2 | L4 test de parámetros |
| 004 | §1.13.1 | L5 medición |
| 005–011 | §1.14.1–7 | L1 autocompletado |
| 012, 013 | §1.15.1, §1.15.4 | L2 doctor |
