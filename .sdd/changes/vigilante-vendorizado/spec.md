# Specification: Vigilante del vendorizado de Chart.js: integridad, CVEs y version

## Summary

`resources/vendor/chart.umd.min.js` son 205 KB de JavaScript de terceros que **nadie audita**:
Dependabot no ve un blob, CodeQL no lo analiza, y Socket cubre dependencias declaradas, no ficheros
sueltos. Hoy no hay siquiera un hash registrado, así que un cambio en ese fichero —accidental o no—
pasaría sin dejar rastro, y un CVE publicado mañana no avisaría a nadie.

Vendorizar fue la decisión correcta y no se toca: el dashboard tiene que funcionar sin internet. Lo
que falta es el **proceso que lo vigile**, y eso es lo que añade este cambio: declarar qué hay ahí
con su procedencia comprobable, y comprobarlo automáticamente.

## Requirements

- **REQ-001:** Existe un **manifiesto versionado** que declara, para cada fichero vendorizado: nombre,
  versión, URL de origen, licencia y **SHA-256 del contenido**. Pasa a ser la fuente de verdad de la
  versión, que hoy solo vive en un comentario de `metrics.py:472`.
- **REQ-002:** Una comprobación **offline** verifica que el hash del fichero en disco coincide con el
  del manifiesto. **Falla** si no coincide.
- **REQ-003:** Una comprobación consulta **OSV.dev** por vulnerabilidades conocidas de la versión
  declarada. **Falla** si hay alguna.
- **REQ-004:** Una comprobación consulta npm por la última versión publicada y **avisa sin fallar**
  si el vendorizado está por detrás.
- **REQ-005:** Si OSV o npm no responden, la comprobación **avisa y no falla**. Un servicio ajeno
  caído no puede bloquear PRs legítimos — es la lección ya anotada sobre exigir `install-smoke`.
- **REQ-006:** El manifiesto documenta la **trampa del banner de jsDelivr**: descargar esa URL y
  comparar el hash directamente da siempre distinto, porque jsDelivr antepone 274 bytes propios. Sin
  esta nota, el siguiente que verifique a mano concluirá que el blob está adulterado.
- **REQ-007:** La vigilancia corre en cada PR/push **y también en un cron semanal**: los CVEs se
  publican cuando les toca, no cuando hay PRs, así que un repo tranquilo no se enteraría. Hay
  precedente en `codeql.yml`, que ya usa las dos.
- **REQ-008:** El proceso queda documentado: qué hace, qué falla, qué solo avisa, y **cómo actualizar
  el vendorizado** (bajar, recalcular hash, actualizar manifiesto) para que sea tarea repetible y no
  arqueología.

## Acceptance scenarios

### Scenario: el blob cambia sin declararlo

- **Given** el manifiesto con el hash de 4.4.1
- **When** alguien reemplaza o corrompe `chart.umd.min.js`
- **Then** la comprobación **falla** en el CI, sin depender de ningún servicio externo

### Scenario: se publica un CVE de la versión vendorizada

- **Given** `chart.js` 4.4.1 declarado en el manifiesto
- **When** OSV publica una vulnerabilidad que le afecta
- **Then** el cron semanal **falla** y lo saca a la luz, aunque nadie haya abierto un PR

### Scenario: sale una versión nueva

- **Given** 4.4.1 vendorizado y 4.5.1 publicada
- **Then** el job **avisa** en su salida y **no** rompe el CI: que alguien publique algo no es un
  fallo de este repo

### Scenario: OSV está caído

- **Given** un PR legítimo
- **When** `api.osv.dev` no responde o devuelve error
- **Then** el job avisa y **pasa**: la comprobación de integridad, que es offline, ya se hizo

## Edge cases and failure behavior

- **Fichero vendorizado ausente:** falla — es tan anómalo como un hash que no cuadra.
- **Manifiesto y directorio desincronizados** (un fichero en `vendor/` sin entrada, o al revés):
  falla. Un vendorizado no declarado es justo el punto ciego que este cambio viene a cerrar.
- **Respuesta de OSV malformada:** se trata como servicio no disponible — avisa, no falla.

## Non-functional requirements

- **Sin dependencias nuevas**: el script usa solo la stdlib. El vigilante es herramienta de CI, no
  código de runtime, y no puede engordar el wheel ni el árbol de quien instala.
- **Rápido y silencioso en el camino feliz**: unos segundos y sin ruido cuando todo está bien.
- **Determinista offline**: la parte que puede fallar el CI (integridad) no toca la red.

## Non-goals

- **No se actualiza Chart.js a 4.5.1.** Primero el vigilante, con una versión de estado conocido;
  actualizar será su primer encargo, en un cambio aparte. Si se mezclara y el panel se rompiera, no
  se sabría si fue el vendorizado nuevo o el vigilante.
- **No se retira el vendorizado** ni se vuelve a un CDN: la razón de servirlo desde el paquete sigue
  siendo válida.
- **No se vendoriza nada más** (las fuentes web siguen descartadas por tamaño del wheel).
- **No se exige el job nuevo como check requerido** en la protección de rama: ya hay una lección
  anotada sobre que un check exigido que nadie reporta bloquea el repo para siempre.

## Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | Manifiesto en `resources/vendor/` | El fichero, con el hash real del blob |
| REQ-002 | Comprobación de hash en el script | Test que corrompe una copia y espera fallo |
| REQ-003 | Consulta a OSV | Ejecución real contra OSV; test con respuesta simulada |
| REQ-004 | Consulta a npm | Ejecución real: avisa de 4.5.1 sin fallar |
| REQ-005 | Manejo de red caída | Test que simula el fallo y espera exit 0 |
| REQ-006 | Nota en el manifiesto | El propio fichero |
| REQ-007 | Job en `ci.yml` con `schedule` | El workflow; corrida verde en el PR |
| REQ-008 | Sección en la documentación | El documento |
