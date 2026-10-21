# Handoff — `retire-legacy-aliases`

## Estado

Implementado en `main`: L1–L10 (#370–#377, #379), arreglo de la revisión de conformidad (#380) y
L11 (salida de la CLI tolerante a cp1252). Verificación en vivo en `verification.md`; revisión de
conformidad en `review.md` (el bloqueante quedó arreglado en #380).

## Decisiones durables

- Los 7 nombres renombrados en la 0.35.0 quedan como **retirados con sucesor** (`retired_from`,
  `warn_until="0.40.0"`): sin efecto, con aviso de `doctor`/`local_status` hasta la 0.40.x. En la
  0.41.0 el test de horizonte pedirá borrarlos del registro.
- `_FAST` y la doble escritura de `enfriamiento.json`: borradas del todo. La lectura de ficheros
  de datos viejos no tiene plazo.
- `update`/`install` migran el `env` de `~/.claude/settings.json` y el fichero interruptor (copia
  `settings.json.retired-names.bak`, registro `retired-names-migration.json` sin valores). No tocan
  variables del sistema, perfiles ni el lanzador.
- Los hooks no detectan nombres viejos (no tienen canal para avisar).
- `install`/`update` no reescriben un fichero de configuración ilegible; leen y conservan el BOM.

## Pendiente

Restos menores en el backlog del vault, §1.15. Memoria: vault
`projects/local-delegate/jornada-2026-10-21-retirada-de-alias-y-0-38.md`.
