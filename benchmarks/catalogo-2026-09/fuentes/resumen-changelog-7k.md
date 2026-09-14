## [0.27.0] - 2026-09-08

### Changed
- **BREAKING — `local_boilerplate` escribe el código en disco y ya no lo devuelve.** La firma pasa
  a `local_boilerplate(spec, language, target, overwrite=False)`: `target` es obligatorio y debe
  ser una ruta **absoluta**. La tool devuelve un recibo de dos líneas —ruta, líneas, chars y los
  tokens que no entraron al contexto— y el código generado viaja al archivo, no de vuelta.

  El proyecto existe para que el contenido voluminoso no pase por el contexto caro, y esta era la
  única tool que aún lo mandaba entero de vuelta. `target` es obligatorio a propósito: como
  parámetro opcional, el ahorro habría dependido otra vez de que el modelo se acordara de usarlo,
  y de eso ya hay tres mediciones seguidas con cero adopción. Esta es la vía que ahorra **sin
  depender de que nadie obedezca un aviso**.

  Detalles del contrato nuevo:

  - **Se valida antes de gastar backend.** Ruta relativa, destino que ya existe sin
    `overwrite=True`, `target` vacío o fuera de `LOCAL_DELEGATE_ALLOWED_DIRS` fallan sin llamar al
    modelo. Generar código para tirarlo es el peor de los dos errores posibles.
  - **No pisa nada por defecto**; `overwrite=True` es explícito.
  - **Un fallo del backend no deja archivo.** El mensaje de error se devuelve como en cualquier
    otra tool, en vez de quedarse en disco con nombre de código fuente.
  - Los directorios que falten se crean, se escribe siempre con `\n` (el separador no depende de
    en qué sistema corra el daemon) y se garantiza el salto de línea final.
  - Sus anotaciones MCP dejan de decir `read_only_hint: true`, que en esta tool ya sería mentira:
    ahora declara `read_only_hint: false` con `destructive_hint: false` (por defecto solo crea) e
    `idempotent_hint: false`. El resto de las tools no cambia.

- **El panel cuenta el ahorro de salida.** Los eventos que escriben su resultado a un archivo
  llevan `output_to_file` en el log, y la contabilidad suma esos tokens al «contexto conservado»
  —usando el token real que reportó el backend, no una estimación por caracteres—. Es un ahorro
  distinto del de leer la entrada server-side (`source=path`) y se suma, porque una misma llamada
  puede ahorrar por los dos lados. La regla se actualizó en sus **dos** copias, la de Python y el
  espejo JavaScript del dashboard, y el test de paridad que las compara ejercita ya el caso nuevo.

### Removed
- **Retirados `output_policy.py`, `output_stats.py` y `emit_updated_input()`.** Eran las piezas del
  mecanismo que reescribía un comando para mandar su salida a un fichero, y se quedaron sin
  consumidor cuando ese mecanismo se descartó: el cliente ya persiste la salida grande por su
  cuenta, y `updatedInput` se salta el allowlist de permisos —el permiso se evalúa sobre el
  comando original, medido—.

  La última puerta que les quedaba la cerró la medición de `PostToolUseFailure`, el evento que
  faltaba por probar. **Sí existe y sí se dispara** cuando un comando Bash termina con código
  distinto de cero (`PostToolUse` no lo hace), y su payload trae el error y admite inyectar
  contexto. Pero no habilita ningún ahorro: cuando dispara, la salida truncada ya entró al
  contexto, y lo que sobraba no está en ninguna parte —a diferencia de los comandos que
  terminan bien, los que fallan **no** persisten su salida en disco ni traen
  `persistedOutputPath`—. Medido con control positivo y negativo: cinco comandos fallidos de
  18 900 bytes y ni un archivo persistido, frente al de código 0 que sí lo dejó entero.

  Eran 590 líneas de módulos y 475 de tests. Nunca llegaron a PyPI —se crearon después de la
  0.26.0, así que esta habría sido la primera release en empaquetarlos— pero sí estaban copiados
  en `~/.claude/hooks/`, puestos ahí por una instalación desde el repo. Quedan declarados en la
  lista de **scripts retirados** de `install`, para que esas copias se limpien en vez de volverse
  inmortales.

- **Retirado el hook `suggest_lint_summary.py`.** Decidía con una regex sobre el comando, antes de
  ejecutarlo, y la medición de 21 días de uso real le dio **366 disparos y 1 acierto** (0,3 %), con
  la mediana de salida en 402 bytes: lo que de verdad lo activaba eran las palabras `test` y
  `build` dentro de rutas. Un aviso que casi nunca tiene razón enseña a ignorar todos los avisos,
  incluidos los que la tienen. Ampliarle la lista de comandos no lo salvaba — ningún ejecutable del
  corpus superaba el umbral de tamaño en más del 9 % de sus ejecuciones.

  `install` retira la entrada de `settings.json` y borra el fichero de las instalaciones que lo
  tuvieran. Para que eso sea posible existe una lista de **scripts retirados**: sin ella, un script
  que deja de empaquetarse se vuelve inmortal, porque la limpieza de huérfanos se deriva de lo que
  hay en el directorio del paquete.

  Con esto, por defecto no queda registrado ningún hook `PreToolUse`.

### Fixed
- **El reintento del map-reduce reconoce el desborde de contexto venga como venga.** La detección
  comparaba contra tres literales de un proveedor y no cubría el `500` con
  `Context size has been exceeded.`, así que en ese caso el troceado se rendía en el primer trozo
  sin reintentar. Ahora se compara sin distinguir mayúsculas, por códigos de error conocidos o por
  la presencia de una palabra de «contexto» junto a una de «exceso». Y cuando el reintento se agota
  de verdad, el mensaje dice qué modelo se quedó corto y qué se puede tocar, en vez de devolver el
  error crudo del backend.

## [0.26.0] - 2026-08-18

### Added
- **`doctor` ve cuando una entrada MCP no puede autenticarse contra el daemon.** Check nuevo
  `service.daemon_auth`: si el puerto del daemon exige token, comprueba que las entradas en modo
  HTTP de los tres clientes lleven con qué entrar.

  Sale de una avería real. `install` sin `--web-token-env` escribe la entrada **sin** cabecera
  `Authorization` —y de paso borra la que hubiera—, así que contra un daemon con token Claude Code
  cae al flujo OAuth y responde «Dynamic Client Registration rejected (HTTP 401)»: las once tools
  desaparecen. Y `doctor` decía **todo a punto**, porque el check de andamiaje sólo comprueba que
  la entrada exista.

  Es la tercera vez que el mismo patrón muerde —2026-07-31, 2026-08-06 y ahora— y las tres el
  diagnóstico miraba por un camino distinto del roto. El check nuevo es hermano de
  `service.credential` un piso más arriba: aquel mira la puerta del **backend** y este la del
  **daemon**, que se cierran por separado.

  Reconoce las tres formas en que `install` escribe la autenticación (`headers.Authorization` en
  Claude Code y opencode, `bearer_token_env_var` en Codex), no cuenta las entradas `stdio` —de
  esas ya avisa `service.credential`— y avisa aparte, redactado como sospecha y no como veredicto,
  cuando la cabecera referencia una variable que este proceso no ve: el entorno de `doctor` es un
  testigo del que verá el cliente, no una prueba.

