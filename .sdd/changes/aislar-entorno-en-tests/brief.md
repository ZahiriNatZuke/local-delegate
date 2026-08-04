# Brief: La suite no puede heredar el entorno de quien la corre

## Problem

`uv run pytest` daba **cuatro fallos `401 == 200`** en `tests/test_daemon.py` en esta máquina y
**cero en CI**, sobre el mismo commit. La causa, verificada por ejecución: `config.WEB_TOKEN` se
calcula al importar el módulo desde `LOCAL_DELEGATE_WEB_TOKEN`, que está definida en cualquier
máquina con el daemon instalado (aquí desde la 0.22.1) y no existe en el runner.

Confirmado con dos controles antes de tocar nada: con `git stash` los mismos cuatro fallaban sin
ningún cambio local, y con `LOCAL_DELEGATE_WEB_TOKEN=` pasaban los 25.

**El problema no es esa variable, es la clase entera.** `tests/conftest.py` ya neutralizaba
`LD_HOOK_TELEMETRY_LOG` — el patrón existía y solo cubría una. Al enumerar el resto aparecieron
**34 variables** que `config` lee (una enumeración manual previa se había quedado en 14), y **cuatro
estaban definidas en esta máquina**: `LD_HOOK_TELEMETRY_LOG`, `LOCAL_DELEGATE_WEB_TOKEN`,
`LOCAL_DELEGATE_AUTOSTART` y `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS`.

Un fallo así es caro por dónde aparece: le sale a quien está haciendo otra cosa, y parece suyo.

## Desired outcome

`uv run pytest` da **el mismo resultado** con el entorno real del usuario y con el entorno limpio de
CI, y sigue dándolo cuando alguien añada una opción de configuración nueva sin acordarse de esto.

## In scope

- Aislar la suite de **todas** las variables que lee `config`, no solo de la que rompía.
- Que la lista de variables **no se escriba a mano**: que salga de las lecturas reales del módulo.
- Guardianes que fallen si la cobertura se rompe en el futuro.

## Out of scope

- Cambiar el comportamiento de `config` en producción: los valores que lee y sus defaults se quedan
  exactamente como están.
- Los valores capturados por otros módulos en tiempo de import (p. ej. `server._chat_slots`, que
  fija `MAX_CONCURRENT_REQUESTS` al importar). Los tests que dependen de eso ya hacen su propio
  `monkeypatch`; medido: la suite pasa entera con esa variable definida.

## Constraints and risks

- **Copiar los defaults al conftest crearía una segunda fuente de verdad** — el defecto recurrente
  de este repo. La solución no puede duplicar ni los nombres ni los valores por defecto.
- **Recargar `config` es seguro aquí y hay que dejar dicho por qué**: nadie en `src/`, `tests/` ni
  `scripts/` hace `from local_delegate.config import <constante>`; todos acceden como `config.X`
  sobre el objeto módulo, que `importlib.reload` actualiza en sitio. Comprobado por búsqueda.
- Riesgo de guardián inútil: si el inventario quedara vacío, los tests de aislamiento pasarían sin
  comprobar nada. Necesita su propio control positivo.

## Open questions

Ninguna.
