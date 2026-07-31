# Implementation plan: Auditoría del backlog: veredicto por punto

## Approach

Auditar primero, arreglar después, y **no confundir las dos cosas**: cada punto se reproduce por
ejecución antes de tocar nada, porque siete premisas de este backlog ya salieron falsas y el coste
de planificar sobre una falsa es mucho mayor que el de medirla.

Para el check nuevo, la decisión de diseño que lo ordena todo es **por qué camino se pregunta**. El
arreglo del PR #100 hizo que `service.backend` preguntara al daemon, que sí tiene credencial; eso
es correcto para diagnosticar el backend y es exactamente el camino equivocado para saber si el
cliente podrá usarlo. Por eso el check nuevo pregunta **sin cabecera de autorización**: es la única
forma de ver lo que se encontrará un proceso que no lleva la key. Los dos checks conviven porque
responden a preguntas distintas, y por eso `backend_requires_key` es una función aparte de
`backend_probe` y no un parámetro suyo — un booleano cuyo significado dependiera del entorno de
quien pregunta sería la clase de dato que engaña.

## Ordered tasks

1. **Auditar los 18 puntos, cada uno con su ejecución**
   - Files or modules: ninguno (lecturas y comandos)
   - Requirements covered: REQ-001
   - Verification: la tabla de `verification.md`, con comando y salida por punto
   - Rollback: n/a

2. **`doctor.backend_requires_key`: preguntar al backend sin credencial**
   - Files or modules: `src/local_delegate/doctor.py`
   - Requirements covered: REQ-002
   - Verification: doblada en los dos arneses; ejercitada por los 5 tests del check
   - Rollback: la función es aditiva; quitarla no toca a `backend_probe`

3. **`service.credential`: el check nº16**
   - Files or modules: `src/local_delegate/checks.py` (colaborador `backend_needs_key`, helpers
     `_entry_mode`/`_codex_mode`, probe y entrada en `CHECKS`)
   - Requirements covered: REQ-002, REQ-003
   - Verification: 5 tests + `doctor` contra la avería real de esta máquina + dos mutantes
   - Rollback: quitar la entrada de `CHECKS` lo desactiva sin tocar nada más

4. **`--dry-run` con el texto literal**
   - Files or modules: `src/local_delegate/install.py` (`Action.literal`, `plan_install`, `apply`)
   - Requirements covered: REQ-004
   - Verification: `test_dry_run_enseña_el_comando_literal_de_cada_hook`, y el dry-run real
   - Rollback: el campo tiene default `""`; sin rellenarlo, el comportamiento es el de antes

5. **Documentación y traza**
   - Files or modules: `CHANGELOG.md`, `docs/wiki/Integration-install.md`, `.sdd/`, vault
   - Requirements covered: REQ-005
   - Verification: el test que obliga al docstring de `checks.py` a decir su tamaño real

## Test strategy

- **Unit:** los 5 del check nuevo, con la pareja `http`/`stdio` sobre el **mismo** backend, para
  que ninguna mitad del probe pueda aprobar por la guarda de la otra; más el del literal del plan.
- **Integration:** `doctor` completo contra la máquina real, que es donde vive la avería.
- **End-to-end o manual:** `install --dry-run` contra un HOME simulado; cliente MCP propio contra
  el `/mcp` del daemon por `streamable_http`; `local_translate` de 14.222 chars con `chunks=8`.
- **Verificar al revés:** dos mutantes —ignorar el modo de la entrada, y preguntar por el camino
  del daemon— comprobando que caen los tests **por la razón que declaran**.
- **Security and secret scanning:** gitleaks en pre-commit; y la propiedad explícita de que el
  secreto no se escribe en ningún fichero ni sale por pantalla.

## Migration and compatibility

- Todo aditivo: un check más y un campo opcional en `Action`. Ninguna firma pública cambia.
- El check puede salir `warn` en máquinas que hoy salían limpias — que es justamente el punto: esas
  máquinas tenían la delegación rota y nadie lo decía. Sube el exit code de `doctor`, como cualquier
  otro `warn`.
- La configuración de esta máquina (`--mcp-mode http`) la aplica el usuario; se revierte con
  `--mcp-mode stdio` y el `.bak` que deja `install`.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback. El único cambio sobre
      configuración real (`~/.claude.json`) lo ejecuta el usuario, acotado con
      `--no-hooks --no-skill --no-memory` y con `.bak`.
- [x] Dependencies and configuration changes are explicit. Sin dependencias nuevas.
- [x] The plan does not include unrelated work. Lo confirmado que no cabe queda **propuesto con
      tamaño**, no empezado a medias.
