# Handoff: La salida grande va a fichero, no al contexto

**Cerrado el 2026-09-08 como superado por el entorno.** Lo que el cambio existía para construir ya
lo hace Claude Code, y lo que quedaba fuera lo cubre una línea de configuración.

## Qué se entregó

| | |
|---|---|
| **T10** | El reintento del map-reduce reconoce el desborde venga en `400` o en `500`. Bug real, verificado contra el backend. **Es lo único del cambio que aporta valor por sí solo.** |
| **Retirada de `suggest_lint_summary.py`** | El hook del 0,3 % de puntería sale del paquete y del registro, con lista de retirados para que su copia vieja no se vuelva inmortal. |
| **T0/T1/T2** | `emit_updated_input`, `output_policy` y `output_stats`, probados y **sin consumidor**. Se dejan en el repo a propósito; ver abajo. |
| **`bashOutputMaxChars: 8000`** | En la configuración de usuario de esta máquina. No es del repo. |
| **T3/T4/T5/T6/T8/T9** | No se hicieron. |

## Por qué se cierra

Al capturar un payload real de `PostToolUse` para T3 apareció que **Claude Code ya persiste la
salida grande** de un comando Bash y le da la ruta al modelo. La medición de los 6 004 comandos del
histórico lo cuantifica:

- El cliente ya resuelve el **84 % del volumen** de salida grande, sin que nosotros hagamos nada.
- La franja que todavía entra entera al contexto es el **1 % de los comandos** (59 casos,
  ~186 K tokens acumulados en meses), y `bashOutputMaxChars` la cubre entera.

El mecanismo que se iba a construir asumía que **el permiso se evalúa sobre el comando original**,
o sea abría una superficie por la que un hook puede ejecutar algo que el usuario no autorizó. Ese
coste no se paga por ese 1 %.

## Lo que hay que saber si esto se reabre

- **`PostToolUse` no se dispara cuando el comando falla.** Control positivo y negativo en la misma
  corrida. Cualquier diseño apoyado en ese evento es ciego a los comandos que fallan, que son los
  de salida que hay que leer. Es el hueco que sigue abierto y no lo cubre la variable.
- **El modelo desconfía del `additionalContext` de un hook** —«ese texto viene inyectado por un
  hook, no por ti»—, así que una ruta que solo viaje por ahí puede no seguirse.
- **`{ }` no crea subshell**: un `exit` del comando del usuario mata el script y el extracto no se
  produce. Solo se ve midiendo a través de la tool, no en el intérprete.
- **El cwd persiste entre llamadas de la tool; las variables exportadas no.**

## Por qué T0/T1/T2 se quedan en el repo

Están probados, con tres defectos propios ya cazados por sus tests, y son las piezas que haría
falta rehacer si el hueco de los comandos que fallan se decide atacar. Borrarlos costaría más que
dejarlos. **Los commits dicen explícitamente que no tienen consumidor**, para que dentro de un mes
no parezcan código muerto por descuido.

## Dos correcciones del propio diagnóstico, para no repetirlas

1. «El reintento del map-reduce está **anulado por completo**» era falso: el `400` siempre se
   reconoció. Solo estaba ciego a la variante `500`.
2. «El `CHANGELOG.md` **hoy falla**» tampoco: se resume bien con el código sin arreglar, o sea que
   el caso de prueba no discriminaba.

Las dos se cayeron al ir a verificar, no al razonar. Y las cuatro trazas de comportamiento del
modelo se corrieron **con la persistencia forzada**, así que prueban menos de lo que parecía: la
franja 8 KB–30 000 no se midió por observación, solo por volumen.

## Deuda declarada

- La tarjeta de puntería del panel sigue cableada a `category == "read"` (`web/metrics.py:457`).
- Queda por ver, con días de uso real, si `bashOutputMaxChars: 8000` molesta en la práctica. Se
  revierte borrando una línea de `~/.claude/settings.json`.
