# Implementation plan: __version__ deja de ser un literal clavado y sale de la metadata del paquete

## Approach

Reutilizar `server._get_version()` en vez de escribir un lector nuevo en `__init__.py`.

Tres razones, todas de la investigación:

1. **No añade importaciones.** `__init__.py` ya hace `from .server import main`, así que el módulo
   `server` —y con él `importlib.metadata`— ya está cargado cuando se evalúa la línea siguiente.
2. **No duplica el manejo del fallo.** `_get_version()` ya decide qué pasa sin metadata (`"0.0.0"`)
   y ya cachea el resultado. Escribir un `try/except` propio sería una segunda política para el
   mismo caso — el defecto que este change viene a quitar, reintroducido en pequeño.
3. **Coincide con lo que el paquete anuncia de sí mismo por el otro canal.** `MCPServer(...)`
   declara `version=_get_version()` en el handshake `initialize` (`server.py:55-63`). Que
   `__version__` salga de la misma llamada garantiza que ambos canales digan lo mismo siempre.

El test va en `tests/test_release_metadata.py`, el módulo que ya existe para «la versión está
declarada en varios sitios y hay que atarlos».

## Ordered tasks

1. **Derivar `__version__`**
   - Ficheros: `src/local_delegate/__init__.py`
   - Requisitos: REQ-001, REQ-002, REQ-004
   - Verificación: `python -c "import local_delegate; print(local_delegate.__version__)"` imprime
     la versión de `pyproject.toml`.
   - Rollback: revertir una línea.

2. **Atar el atributo con un test**
   - Ficheros: `tests/test_release_metadata.py`
   - Requisitos: REQ-003
   - Verificación: el test pasa; y con el literal restaurado a mano, **falla** señalando
     `__init__.py`.
   - Rollback: borrar el test.

3. **CHANGELOG**
   - Ficheros: `CHANGELOG.md` (sección `Unreleased`, hoy vacía)
   - Requisitos: ninguno directamente; es la regla del repo.
   - Verificación: la sección existe y describe el cambio.
   - Rollback: revertir la sección.

## Test strategy

- **Unit:** el test nuevo compara `local_delegate.__version__` con `pyproject.toml`.
- **Verificación al revés (obligatoria en este repo):** restaurar el literal `"0.10.0"` en
  `__init__.py` y comprobar **qué** test cae y **con qué mensaje**. Si cae otro distinto, o cae
  por una guarda ajena, el test no prueba lo que dice.
- **Integration / e2e:** no aplica; el cambio no tiene superficie de ejecución.
- **Secretos:** no se toca ninguna credencial ni configuración. `gitleaks` corre en el pre-commit.

## Migration and compatibility

Ninguna. El atributo conserva nombre, tipo y visibilidad; lo único que cambia es de dónde sale su
valor. Un consumidor externo que hoy lea `0.10.0` pasará a leer la versión real, que es la
corrección buscada.

## Plan review

- [x] Cada requisito mapea a una tarea y a un paso de verificación (tabla de `spec.md`).
- [x] No hay operaciones destructivas; el rollback de cada tarea es revertir el fichero.
- [x] No hay dependencias ni configuración nuevas: `importlib.metadata` es de la stdlib y ya
      estaba en la cadena de importación.
- [x] El plan no arrastra trabajo ajeno: los dos accesores de versión y `bump_version.py` quedan
      explícitamente fuera en `spec.md`.
