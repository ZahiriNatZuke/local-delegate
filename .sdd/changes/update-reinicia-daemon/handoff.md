# Handoff: update_to_latest.sh reinicia el daemon MCP segun el mecanismo de cada sistema

## Current state

- **SDD status:** cerrado.
- **Último gate:** `memory`.
- **Revisión:** PR **#66**, **publicado en la 0.17.0**. La traza se cerró el **2026-07-31**, un día
  después de publicar, con verificación **fresca contra el paquete de PyPI** — no contra la rama.

## What changed

`local-delegate update`: revisa el andamiaje con `checks.run_all`, actualiza el pin donde exista,
completa lo que falte reusando `install.plan_install` y deja el daemon arriba con el mecanismo
registrado en cada sistema.

## Por qué esta traza se cerró tarde, y qué se hizo al respecto

El change quedó en `verifying` mientras salía la 0.17.0, así que sus tres últimos gates se
firmaron con el código **ya publicado**. Firmarlos de memoria habría sido cómodo y falso: se
repitió la verificación contra `~/.local/bin/local-delegate` (0.17.0 desde PyPI), y el resultado
está en `verification.md` en una sección aparte, no reescribiendo la original.

**Once requisitos re-verificados, seis declarados como no re-verificados con su motivo.** Los seis
exigen reiniciar el daemon o el backend de la máquina del usuario, y decir que no se hizo es más
útil que un tic en una casilla.

## Decisions

1. **El pid sale solo de `/api/daemon`, nunca de `daemon.json`.** La forma más fuerte de no
   señalar a un pid reciclado no es leerlo y verificarlo: es **no leerlo**. Verificado en fresco:
   las dos menciones a `daemon.json` en `update.py` son comentarios que dicen justo eso.
2. **El backend no se toca sin `--restart-backend`.** Reiniciar llama-swap descargaría los modelos
   de la VRAM y la siguiente delegación pagaría la carga.
3. **Con `--home` simulado no se toca ningún servicio.** El daemon no vive en el HOME, así que un
   flag documentado «para pruebas» reiniciaría el daemon de verdad.
4. **REQ-017 quedó superado por una decisión posterior.** Exigía que `scripts/update_to_latest.sh`
   quedara como envoltorio fino; ese fichero se retiró el 2026-07-31 (PR #81). No es un requisito
   incumplido: dejó de tener sentido.

## Next action

Nada de este change. En la sesión del 2026-07-31 quedaron abiertos los puntos 8 y 9 del backlog
(la captura del README sin check que la obligue, y el amarillo del botón de idioma de la landing)
y la **fase 3 del SDK MCP** —`middleware`, elicitation y `auth`—, que son tres changes con
research propio y merecen contexto fresco.

## Memory

- **Nota canónica:** la jornada del 2026-07-30/31 en el vault (`projects/local-delegate/`).
- **Índices actualizados:** `CHANGELOG.md` de la 0.17.0.
- Sin secretos, credenciales ni datos personales.
