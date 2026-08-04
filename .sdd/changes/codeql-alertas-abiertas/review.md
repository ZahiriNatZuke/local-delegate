# Result review: Cerrar las 10 alertas abiertas de CodeQL: 6 arreglos y 4 descartes

## Verdict

`conforms-with-notes` — los seis requisitos se cumplen y están verificados contra el repo real, no
contra una suposición. Las notas son dos hallazgos laterales, ninguno bloqueante.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | Hizo falta tres vueltas, y las tres las dictó el check de CodeQL de la PR, no la comprobación local. Salida del extractor idéntica byte a byte en las tres |
| REQ-002 | sí | sí | Tres comentarios; ningún `except` cambió de tipo ni de cuerpo |
| REQ-003 | sí | sí | Mutante: `config.WEB_FONTS` forzado a `True` → falla en `assert hoja not in html` |
| REQ-004 | sí | sí | Mutante dirigido (2 hilos, sin deadlock) → falla solo en la comprobación nueva |
| REQ-005 | sí | sí | Los cuatro descartados tras el merge; `?state=open` devuelve `[]` |
| REQ-006 | sí | sí | 13 checks verdes en la PR; los seis workflows de `main` en verde tras el merge |

## Findings

1. **El `gh run list` verde no significa CI verde.** El check `CodeQL` de la PR (el que juzga las
   alertas) es distinto del job `Analyze (python)` (el que corre el análisis), y solo se ve con
   `gh pr checks`. Estuvo en rojo dos rondas seguidas mientras los tres workflows salían `success`.
   Es la lección del job fantasma por una puerta nueva, y merece quedar escrita.
2. **Un control positivo puede no probar nada y parecer que sí.** El primer mutante de REQ-004 hacía
   fallar el test, pero por un assert que ya existía. Sin mirar *qué* assert disparaba, habría
   contado como cubierto un cambio que no lo estaba.
3. **Cuatro tests fallan en máquinas con `LOCAL_DELEGATE_WEB_TOKEN` definida** (`tests/test_daemon.py`,
   `401 == 200`), desde antes de este cambio. No aíslan la variable de entorno; en CI no se ve
   porque allí no existe. **Fuera del alcance de este cambio**, pero es deuda real: cualquiera con
   el token puesto ve su suite en rojo sin motivo.
4. **La escalera de `py/bad-tag-filter` tiene fondo conocido**: la regla existe para decir «no
   parsees HTML con regex». Se cerró en tres vueltas porque cada tolerancia era barata y la salida
   no cambiaba; el plan fijaba de antemano que a la cuarta objeción se pasaba a descarte.

## Required follow-up

Nada bloqueante para el cierre. Pendiente de decidir aparte, sin urgencia:

- Aislar `LOCAL_DELEGATE_WEB_TOKEN` en `tests/test_daemon.py` (hallazgo 3), con un `monkeypatch.delenv`
  o una fixture de entorno limpio.
- Ninguna acción sobre `codeql.yml`: la suite `security-and-quality` se mantiene tal cual.
