# Brief: El dashboard lee la telemetria de los hooks

## Problem

Los hooks consultivos llevan tiempo escribiendo telemetría y **el dashboard no la mira**. De las
tres afirmaciones del pendiente viejo, la auditoría del 2026-07-31 tumbó dos:

- ❌ «`LD_HOOK_TELEMETRY_LOG` no está definida» → **sí lo está**.
- ❌ «no se registra nada» → **1817 eventos** entre el 29 y el 31 de julio.
- ✅ **Lo único cierto:** `metrics.py` no menciona `telemetry` ni `hook` ni una vez.

O sea: el dato existe, es abundante, y no se ve por ningún sitio.

## Desired outcome

El panel enseña cuántas veces los hooks sugirieron delegar, en el mismo rango que el resto de la
página, **sin afirmar nada que el dato no sostenga**.

## In scope

- `GET /api/hooks` con agregados por evento, categoría y día.
- Una tarjeta en el dashboard.
- Documentación de la frontera entre lo que mide y lo que no.

## Out of scope

- **Cruzar la telemetría con el log de uso** para saber cuántas sugerencias se siguieron. Son dos
  registros sin identificador común; correlacionarlos por cercanía temporal sería inventar un dato.
- Cambiar lo que los hooks registran.
- El brazo B del piloto A/B (`LD_HOOK_READ_ENABLED`): es otra decisión y cambia la experiencia
  diaria del usuario.

## Constraints and risks

- **El riesgo principal es de interpretación, no técnico.** Una tarjeta que diga «17 %» sin
  contexto se lee como «el 17 % de mi trabajo se delega», que es falso: se sugirió, no se delegó.
- **La telemetría promete no registrar contenido** (ni prompts, ni comandos, ni rutas). El
  dashboard no puede romper esa promesa exponiendo el evento crudo.
- `enabled` importa: un panel a cero por falta de fichero se lee igual que un panel a cero por
  falta de sugerencias, y son cosas distintas.

## Open questions

- Ninguna. La frontera de lo que se afirma queda fijada en la spec.
