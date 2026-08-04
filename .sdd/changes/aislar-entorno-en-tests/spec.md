# Specification: La suite no puede heredar el entorno de quien la corre

## Summary

`uv run pytest` produce el mismo resultado en una máquina con el daemon instalado (variables
definidas) y en CI (sin ninguna), y la cobertura de ese aislamiento se mantiene sola cuando se
añaden opciones de configuración nuevas.

## Requirements

- **REQ-001:** `config` expone el inventario de las variables de entorno que lee, **derivado de sus
  propias lecturas** y no de una lista escrita a mano.
- **REQ-002:** Toda lectura del entorno en `config` pasa por una única puerta; ninguna se salta el
  inventario.
- **REQ-003:** Durante la suite, ninguna variable del inventario está definida en `os.environ`, y
  las constantes de `config` valen su default —sin que los defaults se dupliquen fuera de
  `config.py`.
- **REQ-004:** Los cuatro tests de `tests/test_daemon.py` que fallaban pasan con
  `LOCAL_DELEGATE_WEB_TOKEN` definida.
- **REQ-005:** Existen guardianes que fallan si (a) alguien añade una lectura directa del entorno en
  `config`, o (b) el aislamiento deja de aplicarse. Y un tercero que impide que los dos anteriores
  pasen en vacío.
- **REQ-006:** El comportamiento de `config` en producción no cambia: mismas variables, mismos
  defaults, mismos valores resultantes.

## Acceptance scenarios

### Scenario: el mismo veredicto en las dos máquinas

- **Given** esta máquina, con cuatro variables del paquete definidas
- **When** se corre `uv run pytest` con el entorno real y otra vez con esas variables quitadas
- **Then** ambas corridas dan el mismo número de tests pasados, sin fallos

### Scenario: una opción nueva queda cubierta sin tocar los tests

- **Given** una lectura nueva del entorno añadida a `config` con los helpers
- **When** corre la suite
- **Then** la variable entra en el inventario y el aislamiento la cubre, sin editar `conftest.py`

### Scenario: una lectura que se salta la puerta se detecta

- **Given** un `os.environ.get(...)` directo añadido a `config.py`
- **When** corre la suite
- **Then** un guardián falla nombrando dónde está la lectura

## Edge cases and failure behavior

- **Inventario vacío:** si el registro dejara de alimentarse, los guardianes de aislamiento pasarían
  sin comprobar nada. Un tercer test asevera que el inventario tiene tamaño y contiene las dos
  variables que motivaron el cambio.
- **Constantes ya capturadas por otros módulos** en tiempo de import: fuera de alcance, declarado en
  el brief y medido (la suite pasa con esas variables definidas).

## Non-functional requirements

- **Compatibilidad:** sin cambios de API pública ni de CLI. `VARIABLES_DE_ENTORNO` es aditivo.
- **Sin segunda fuente de verdad:** ni los nombres ni los defaults se repiten fuera de `config.py`.

## Non-goals

- No se cambia qué variables lee el paquete ni sus valores por defecto.
- No se tocan los tests que ya hacen `monkeypatch` de `config` a propósito.

## Traceability

| Requisito | Trabajo | Verificación |
|-----------|---------|--------------|
| REQ-001 | `_VARIABLES_LEIDAS` + `VARIABLES_DE_ENTORNO` en `config.py` | 34 nombres registrados al importar |
| REQ-002 | las cuatro lecturas directas pasan por `_leer` | guardián AST; `grep` de `os.environ` deja solo `_leer` |
| REQ-003 | fixture de sesión en `conftest.py` (delenv + reload) | guardián de `os.environ` limpio |
| REQ-004 | consecuencia de REQ-003 | `pytest tests/test_daemon.py` con la variable puesta |
| REQ-005 | `tests/test_aislamiento_entorno.py` | mutante A y mutante B, más el control positivo |
| REQ-006 | ningún cambio de valores | suite completa verde en los dos entornos |
