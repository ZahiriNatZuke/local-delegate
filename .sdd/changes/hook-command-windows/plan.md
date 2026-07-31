# Plan de implementación (modo lite): el comando del hook se rompe en Windows

> **Reconstruido a posteriori el 2026-07-31** desde el `brief.md` original y el diff mergeado.
> Ver la nota en `spec.md`.

## Enfoque

El bug se reprodujo antes de tocar nada, con `sh -c`, así que el arreglo no se diseñó a ciegas.
`_quote` solo ponía comillas si la ruta tenía **espacios**, y una ruta de Windows normalmente no
los tiene. La corrección es dejar de decidir: **citar siempre** y usar `as_posix()`.

Alcance de dos funciones, que es lo que justifica el modo ligero.

## Tareas, en orden

1. **`hook_command` cita siempre y usa `as_posix()`**
   - Ficheros: `install.py`
   - Requisitos: REQ-001, REQ-002, REQ-003
   - Verificación: test con la ruta exacta del bug —sin un solo `\` en el resultado y con
     `shlex.split` devolviendo la ruta entera— más ejecución real en la máquina donde falló
   - Reversión: la condición anterior, tres líneas

2. **`backend_probe` distingue 401/403 de caído**
   - Ficheros: `checks.py`
   - Requisitos: REQ-004
   - Verificación: test dedicado más comprobación contra el llama-swap vivo que el doctor daba por
     muerto
   - Reversión: volver a tratar cualquier no-200 como caído

## Estrategia de pruebas

- **Unitarias:** los dos tests citados.
- **Por ejecución:** en la máquina donde el bug apareció, que es la única prueba que cuenta para
  un fallo específico de plataforma.
- **Secretos:** ninguno en juego.

## Migración y compatibilidad

Un `install` con esta versión repara los hooks al reescribirlos. Los usuarios que ya tenían el
comando roto necesitan volver a registrarlos.

## Revisión del plan

- [x] Cada requisito se mapea a una tarea y a una verificación.
- [x] El riesgo está acotado: dos funciones, con reversión de pocas líneas cada una.
- [x] Sin dependencias nuevas.
- [x] El segundo arreglo entra porque salió el mismo día y toca el mismo diagnóstico; queda dicho.
