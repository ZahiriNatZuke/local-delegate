# Implementation plan

## Ficheros

| Fichero | Qué cambia |
|---|---|
| `src/local_delegate/checks.py` | El probe nuevo y su entrada en el registro |
| `tests/test_checks.py` | Un test por escenario |
| `CHANGELOG.md` | Entrada en `Unreleased` |

`install.py` no se toca: el arreglo de que reinstalar borre la cabecera está fuera de alcance.

## Tareas

### T1 — un lector de «¿esta entrada se puede autenticar?» por cliente

Tres formas distintas (research), así que una función por cliente que devuelva
`(habla_http, tiene_credencial, referencia_variable)`. Se leen con los helpers que
`_probe_mcp_credential` ya usa, no con lectores nuevos: dos fuentes para el mismo dato es la clase
de defecto recurrente del repo.

### T2 — el probe

```
exige = ctx.daemon_needs_token(host, port)
None  -> UNKNOWN
False -> OK
True  -> mirar las entradas http:
         ciegas   = las que no llevan nada        -> WARN (REQ-003)
         a_ciegas = las que referencian una variable vacía en ESTE entorno -> WARN (REQ-006)
         ninguna  -> OK
```

Las dos clases de aviso se redactan distinto a propósito: la primera es una avería segura, la
segunda una sospecha con testigo. Mezclarlas en un texto único haría que la segunda sonara a
certeza.

### T3 — registrarlo

En `servicio`, junto a `service.credential`, con el mismo comentario de por qué no está en
`andamiaje`.

### T4 — tests

Uno por escenario. El colaborador `daemon_needs_token` se dobla siempre: sin doblarlo la suite
sale a la red, verde en CI y otra cosa en la máquina de quien desarrolla — ya pasó dos veces el
2026-07-31 y `NO_TOKEN_PROBE` existe justo para esto.

**Control anti-vacío:** el escenario de la instalación correcta tiene que dar `ok`. Sin él, un
probe que avisara siempre pasaría los seis restantes.

### T5 — CHANGELOG

## Verificación

- `uv run pytest`, `ruff check`, `ruff format --check`.
- **Contra la máquina real**: `doctor` da `ok` con la entrada correcta; se le quita la cabecera a
  mano y debe dar `warn`; se restaura y vuelve a `ok`. Reproducir la avería y deshacerla es la
  única prueba de que el check ve lo que hoy no se veía.

## Lo que puede salir mal

- **Que algún test existente cuente los checks.** El registro pasa de 17 a 18 y el docstring de
  `run_all` dice «los diecisiete probes». Hay que mirarlo antes, no después.
- **Que `daemon_needs_token` responda `True` cuando el puerto lo ocupa otra cosa.** Su docstring
  dice que separa «ahí hay otra cosa» de «ahí está nuestro daemon protegido»; si no lo hiciera, el
  check avisaría en máquinas sanas. Se comprueba leyendo `daemon.daemon_requires_token`.
