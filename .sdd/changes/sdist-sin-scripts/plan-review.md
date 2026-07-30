# Revisión adversarial del plan

Revisión hecha sin delegar en subagentes (convención de la sesión). El criterio fue atacar las
afirmaciones del plan y de la investigación, no confirmarlas.

## Hallazgos

### H1 — Afirmación falsa en la investigación (corregido, no bloqueante)

`research.md` afirmaba que el script «apunta a una ruta que ya no existe». Es falso.
`git ls-tree -r --name-only v0.10.0 -- docs/recipes/hooks` devuelve los cuatro `.py`: la ruta
desapareció de `main` pero vive en el tag, y GitHub sirve por tag.

El script **funciona hoy**. No es código muerto: es un instalador operativo que trae hooks de la
v0.10.0 por red, sin verificar hash. Agrava el caso en vez de mitigarlo, pero la afirmación era
incorrecta y estaba a punto de quedar escrita como evidencia.

**Resuelto:** corregidos el punto 4 y la conclusión de `research.md`.

### H2 — El `skip` de T3 puede enmascarar un borrado accidental (bloqueante, corregido)

Tal como estaba redactado, T3 saltaba los tests cuando el fichero del script no existía. Eso
convierte un borrado accidental de `scripts/check_vendor.py` o `scripts/bump_version.py` en un CI
**verde**: los tests desaparecerían en silencio y nadie se enteraría.

Es justo el fallo contra el que advierte la convención del repositorio: un test que no falla con el
bug puesto no prueba nada.

Mitigación parcial que ya existe: `vendor-audit.yml` ejecuta `scripts/check_vendor.py` directamente,
así que su borrado sí rompería ese workflow. Pero `bump_version.py` no lo cubre nadie: su ausencia
no se notaría hasta el siguiente release.

**Resuelto:** la condición del `skip` pasa a distinguir los dos casos. Se salta solo cuando falta
**el directorio `scripts/` entero** —que es lo que ocurre en un sdist podado—; si el directorio
existe pero el fichero no, eso es un borrado accidental y el test debe fallar como hasta ahora.

### H3 — Hooks duplicados en máquinas donde se ejecutó el `.sh` (no bloqueante, al backlog)

Las dos vías instalan en sitios distintos: el `.sh` escribe en `~/.claude/hooks/*.py` y el CLI
`install` en `~/.claude/hooks/local-delegate/`. Quien haya corrido el script alguna vez tiene los
hooks por duplicado y registrados dos veces en `settings.json`; borrar el script no lo limpia.

Fuera del alcance de este cambio. Candidato natural a comprobación del `doctor`, que ya sabe mirar
el registro de hooks. Se anota en el backlog.

## Verificación de la lista del plan

- **Cobertura de requisitos:** cada uno tiene tarea y evidencia. Correcto.
- **Forma del `exclude`:** `/scripts` es coherente con las cuatro entradas presentes
  (`/.codex`, `/.sdd`, `/.venv`, `/dist`), y la barra inicial ancla a la raíz del proyecto.
- **`allow_module_level=True`:** disponible en la versión de pytest del proyecto (>=8), y necesario
  porque ambos ficheros llaman a `_load_script()` en el cuerpo del módulo.
- **Orden de ruff:** el `skip` queda después de todos los imports, así que no dispara E402.
- **Aritmética del sdist:** 124 − 15 = 109 entradas. Coherente con el listado medido.
- **Ninguna referencia entrante al fichero borrado:** verificado por búsqueda sobre `.md`, `.yml`
  y `.py`.

## Veredicto

Aprobable con H1 y H2 ya incorporados. H3 queda registrado como seguimiento, no bloquea.
