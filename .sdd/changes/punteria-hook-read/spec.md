# Specification: el hook de lectura sólo avisa cuando tiene razón

## Summary

`suggest_delegate_read` deja de sugerir delegar lecturas que no se pueden delegar —código, franjas
acotadas y archivos medianos— y la telemetría registra la extensión, para que la puntería del hook
sea medible desde el panel sin guardar rutas.

## Requirements

- **REQ-001:** El hook no sugiere nada cuando la lectura trae `offset` o `limit`: una franja pedida
  a propósito no es candidata a una transformación global.
- **REQ-002:** El hook no sugiere nada cuando la extensión del archivo es de código fuente. La
  lista de extensiones es un dato del módulo, no está escrita dentro de la función de decisión.
- **REQ-003:** Los umbrales por defecto pasan de 8/32 KB a **32/100 KB**, sin cambiar los nombres
  de las variables de entorno que los configuran (`LD_HOOK_READ_SUGGEST_KB`,
  `LD_HOOK_READ_STRONG_KB`).
- **REQ-004:** La telemetría de cada evento de lectura incluye `ext` (la extensión en minúsculas,
  o `""` si no tiene). No incluye la ruta, el nombre del archivo ni ninguna parte de ellos.
- **REQ-005:** El hook sigue sin bloquear nunca: no emite `permissionDecision`, y una lectura
  descartada por REQ-001/002/003 se registra con `suggested: false` en vez de callarse, para que la
  puntería se pueda medir sobre el total.
- **REQ-006:** El hook sigue apagado por defecto y se enciende igual que hoy (`--enabled` o
  `LD_HOOK_READ_ENABLED`); el resto de su contrato de entrada/salida no cambia.

## Acceptance scenarios

### Scenario: una lectura de código grande ya no genera ruido

- **Given** el hook encendido y un `.ts` de 150 KB
- **When** el modelo lo va a leer entero
- **Then** no se emite ninguna sugerencia, y la telemetría registra el evento con
  `suggested: false` y `ext: ".ts"`

### Scenario: una franja pedida a propósito se respeta

- **Given** el hook encendido y un `.md` de 200 KB
- **When** la lectura trae `offset: 500, limit: 100`
- **Then** no se emite ninguna sugerencia

### Scenario: el caso que sí vale la pena sigue avisando

- **Given** el hook encendido y un `.md` de 120 KB leído entero
- **When** el modelo lo va a leer
- **Then** se emite la sugerencia en banda `strong`, con la telemetría marcando `ext: ".md"`

### Scenario: el archivo mediano deja de disparar

- **Given** un `.md` de 20 KB leído entero
- **When** el modelo lo va a leer
- **Then** no se emite sugerencia (por debajo del nuevo umbral de 32 KB)

### Scenario: la telemetría sigue sin filtrar rutas

- **Given** una lectura de `C:\proyecto\secreto\informe-confidencial.md`
- **When** el hook registra el evento
- **Then** la línea del log contiene `.md` pero ni `secreto`, ni `informe-confidencial`, ni ningún
  fragmento de la ruta

## Out of scope

- Bloquear lecturas (`permissionDecision: deny`). El control negativo mostró que el modelo ya
  delega solo en los casos claros; el valor incremental no justifica el riesgo de estorbar una
  lectura legítima.
- La redacción de la skill `delegacion-local`. El research muestra que la prosa no es la causa.
- Que las tools del MCP lleguen diferidas en las sesiones. Es la causa con más peso real, pero se
  arregla en la configuración de los clientes, no en este paquete.
- Los otros dos hooks (`suggest_lint_summary`, `suggest_delegate_prompt`).

## Verification

- Suite del proyecto (`uv run pytest`), con tests nuevos en `tests/test_hook_recipes.py` que cubran
  cada escenario de arriba.
- Un control que falle si los tests nuevos pasan en vacío: el mismo `.md` de 120 KB debe seguir
  produciendo sugerencia, de modo que un hook que niegue todo no pase la suite.
- Simulación de las reglas nuevas contra las 852 lecturas reales de los transcripts: debe caer de
  572 a ~29 sugerencias.
