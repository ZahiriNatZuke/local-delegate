# Implementation plan: El cancelled del CI en main tiene causa conocida y firma reconocible

## Approach

**Corregir el diagnóstico en los tres sitios que lo repiten, y atar los números con tests.**

El pendiente pedía elegir remedio —reintento, `timeout-minutes`, o dejar de contarlo—. Medir
disolvió la pregunta: **el remedio ya estaba puesto**. Lo que faltaba era saber que funcionaba, y
poder reconocer su firma sin reinvestigar.

Dos decisiones:

1. **La corrección se escribe como corrección**, diciendo qué ponía antes y por qué era falso, en
   vez de borrar y reescribir. Es la segunda vez que este cuelgue se diagnostica mal; borrar el
   rastro invita a una tercera.
2. **El límite del paso se añade porque la medición lo pidió**, no por completitud: en dos de los
   tres casos quien seguía corriendo era pytest. Es la única acción nueva del change, y la única
   que cambia comportamiento.

## Ordered tasks

1. **`ci.yml`: corregir el comentario y añadir el límite del paso**
   - Requisitos: REQ-001, REQ-002
   - Verificación: los tests de la tarea 4.
   - Rollback: revertir; se vuelve al estado de hoy, con el diagnóstico falso.

2. **`ci_gate.py`: corregir su docstring**
   - Requisitos: REQ-001
   - Verificación: la suite del gate sigue verde (23 tests).
   - Rollback: revertir.

3. **`Repo-hardening.md`: reescribir la sección con la firma y una tabla de lectura**
   - Requisitos: REQ-001, REQ-005
   - Verificación: la tabla clasifica los tres casos observados.
   - Rollback: revertir.

4. **`tests/test_ci_gate.py`: atar los números**
   - Requisitos: REQ-003, REQ-004
   - Verificación: mutantes sobre `ci.yml` (límite del job, límite del paso ausente, límite del
     paso ≥ el del job).
   - Rollback: borrar los dos tests.

5. **CHANGELOG**

## Test strategy

- **Unit:** los dos tests nuevos leen `ci.yml` con `yaml.safe_load`, igual que el parser de jobs
  que ya existe en ese módulo.
- **Verificación al revés:** cuatro mutantes sobre `ci.yml`. El escenario real —cambiar el límite
  del job y dejar el texto viejo— tiene que caer.
- **No hay integración ni e2e posibles:** reproducir el cuelgue exigiría que GitHub se colgara a
  demanda. La evidencia es la de los tres runs ya ocurridos.
- **Secretos:** no se toca ninguno.

## Migration and compatibility

Un solo cambio de comportamiento: con pytest colgado, el job pasará a fallar a los ~5 minutos con
log en vez de morir a los 13 sin log. Es mejor en las dos dimensiones que importan —antes y con
evidencia— pero la conclusión que se ve pasa de `cancelled` a `failure`.

## Plan review

- [x] Cada requisito mapea a tarea y verificación.
- [x] Nada destructivo. El único cambio de comportamiento está acotado a un paso y razonado.
- [x] Sin dependencias nuevas.
- [x] Sin trabajo ajeno: no se toca el gate ni la lista de jobs esperados; solo su docstring.
