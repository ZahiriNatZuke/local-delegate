# Excepciones del detector de nombres en español (REQ-016)

Lista de nombres en español que pueden quedar en el repo al cerrar el frente A, cada uno con su
motivo. La lee `scripts/detect_spanish_names.py --exceptions <este fichero>`: toma las filas de las
tablas (`| Nombre | Fichero | Motivo |`) y aparta un hallazgo cuando coinciden el nombre y el
fichero (el fichero admite comodines, `*` para cualquiera).

Los únicos motivos válidos (REQ-016):

- alias de compatibilidad (REQ-001, REQ-002, REQ-012), con su versión de retirada;
- lectura de formato viejo (excepción de REQ-005, REQ-006, REQ-007, REQ-008);
- envoltorio de REQ-046;
- dato de un tercero que no controla el paquete;
- dato de prueba del propio detector: nombres en español que sus tests y su léxico necesitan como
  entrada (enmienda del 2026-10-12 tras la ola A0);
- **pendiente**: lo que el frente A renombra pero se publica en el B (las subclaves y marcadores
  de REQ-010, que salen en B2).

Al cerrar el frente A, la sección «Pendiente» solo puede tener lo de REQ-010; al cerrar el cambio,
tiene que estar vacía.

Estado al terminar la ola A0: **lista vacía**. Cada ola añade aquí las filas que necesite, en la
sección de su motivo.

## Alias de compatibilidad

| Nombre | Fichero | Motivo |
| --- | --- | --- |

## Lectura de formato viejo

| Nombre | Fichero | Motivo |
| --- | --- | --- |

## Envoltorio de REQ-046

| Nombre | Fichero | Motivo |
| --- | --- | --- |

## Dato de un tercero

| Nombre | Fichero | Motivo |
| --- | --- | --- |

## Dato de prueba del detector

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| * | tests/test_detect_spanish_names.py | casos de control positivo del detector (REQ-044) |
| * | scripts/data/* | léxico congelado y palabras reservadas del detector (REQ-044) |

## Pendiente

| Nombre | Fichero | Motivo |
| --- | --- | --- |
