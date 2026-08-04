# Implementation plan: La suite no puede heredar el entorno de quien la corre

## Approach

Tres piezas, y el orden importa porque cada una habilita la siguiente.

**1. Que el módulo sepa qué lee.** Un `_leer(name)` que es la única puerta a `os.environ` en
`config.py` y va anotando los nombres en un set; los cuatro helpers (`_env`, `_env_int`,
`_env_flag`, `_env_float`) pasan por él, y las cuatro lecturas sueltas que había también. Al final
del módulo, `VARIABLES_DE_ENTORNO = frozenset(...)`. Va **al final** a propósito: declararlo antes
dejaría fuera lo que se lea más abajo, que es el mismo fallo que esto viene a impedir.

**2. Que la suite se aísle sin copiar nada.** Una fixture de sesión que hace `delenv` de todo el
inventario y **recarga `config`**. Recargar en vez de reasignar constante por constante es lo que
evita duplicar los defaults en `conftest.py` — la segunda fuente de verdad es el defecto recurrente
de este repo, y aquí sería especialmente traicionera porque envejecería en silencio.

**3. Que no se pueda romper otra vez.** Tres guardianes: uno mira que nadie se salte `_leer`
(parseando el AST de `config.py`), otro que el entorno esté limpio durante la suite, y un tercero
que impide que los dos anteriores pasen en vacío si el inventario se rompiera.

## Ordered tasks

1. **Registro automático en `config`**
   - Files or modules: `src/local_delegate/config.py` (helpers + las 4 lecturas directas + la
     constante final; exclusivo)
   - Requirements covered: REQ-001, REQ-002, REQ-006
   - Verification: importar y contar el inventario; `grep os.environ` debe dejar solo `_leer`
   - Rollback: revertir el fichero; nada depende todavía de la constante nueva

2. **Fixture de aislamiento**
   - Files or modules: `tests/conftest.py` (exclusivo)
   - Requirements covered: REQ-003, REQ-004
   - Verification: `pytest tests/test_daemon.py` con `LOCAL_DELEGATE_WEB_TOKEN` **puesta**
   - Rollback: revertir; la suite vuelve al estado de antes, que ya era el defectuoso

3. **Guardianes**
   - Files or modules: `tests/test_aislamiento_entorno.py` (nuevo, exclusivo)
   - Requirements covered: REQ-005
   - Verification: **dos mutantes**, uno por guardián, más el control positivo del inventario
   - Rollback: borrar el fichero

4. **Suite completa en los dos entornos**
   - Requirements covered: REQ-006
   - Verification: `uv run pytest` con el entorno real y con las cuatro variables quitadas; mismo
     número de tests pasados en ambos
   - Rollback: no subir si divergen

## Test strategy

- **Unit:** los tres guardianes nuevos.
- **Integration:** la suite entera, que es justamente el sujeto del cambio.
- **Control positivo, obligatorio aquí:** cada guardián se valida con un mutante que lo dispare —
  (A) una lectura directa nueva en `config.py`, (B) la fixture desactivada con la variable real
  puesta— y hay que comprobar que falla **por su assert** y no por otro.
- **Doble corrida:** entorno real vs entorno limpio. Es la única medida que responde a la pregunta
  del cambio; un solo entorno no distingue.
- **Security and secret scanning:** el diff no toca autenticación ni añade dependencias. El token
  sigue leyéndose igual en producción; lo único que cambia es que la **suite** no lo hereda.

## Migration and compatibility

Aditivo. `VARIABLES_DE_ENTORNO` es una constante nueva; ninguna existente cambia de valor. Sin bump
de versión: no hay nada visible para quien usa el paquete.

## Plan review

- [x] Cada requisito tiene tarea y verificación — REQ-001/002/006→t1, REQ-003/004→t2, REQ-005→t3,
      REQ-006→t4.
- [x] Operaciones arriesgadas con salvaguarda — la mutación de ficheros para los controles positivos
      va con `trap ... EXIT`, tras haber dejado un fichero mutado en disco esta misma sesión cuando
      un test se colgó y la restauración venía después.
- [x] Dependencias y configuración explícitas — ninguna nueva.
- [x] Sin trabajo no relacionado.

### Revisión adversarial

- **«¿El `reload` puede romper referencias?»** Solo si alguien hiciera
  `from local_delegate.config import <constante>`. Comprobado por búsqueda en `src/`, `tests/` y
  `scripts/`: nadie. Todos usan `config.X`, y `reload` actualiza el módulo en sitio.
- **«¿Y lo que otros módulos capturaron al importar?»** No lo arregla — `server._chat_slots` fija
  `MAX_CONCURRENT_REQUESTS` en tiempo de import. Está declarado fuera de alcance y **medido**: esa
  variable está definida en esta máquina y la suite pasa entera igual.
- **«¿El guardián del AST puede dar falso positivo?»** Solo mira `os.environ` / `os.getenv` con
  receptor `os`, y excluye la propia `_leer`. Un alias raro se le escaparía, pero eso empeora la
  detección, no la corrección — y el otro guardián (entorno limpio) lo pillaría igual.
