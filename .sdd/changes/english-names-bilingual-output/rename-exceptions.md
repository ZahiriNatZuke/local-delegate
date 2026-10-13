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
| delegacion-local | src/local_delegate/install.py | alias de compatibilidad permanente (REQ-012/013): nombre de la skill hasta la 0.34.0 en `_RETIRED_SKILLS`; sin retirada, porque quien salte desde una 0.34 sigue teniendo la copia vieja (ola A6, respuesta 7) |
| anotar_llamada.py | src/local_delegate/install.py | alias de compatibilidad permanente (REQ-012): nombre del hook hasta la 0.34.0 en `_RETIRED_SCRIPTS`; misma razón (ola A2, apuntado en A6, respuesta 7) |
| delegacion-local | tests/* | alias de compatibilidad (REQ-012): instalación 0.34.0 simulada en los tests de `install`/`update` y de la retirada de la skill (ola A6) |
| ld_sesion | tests/test_web_auth.py | alias de compatibilidad (REQ-012): cookie de la 0.34.0 que tiene que dar 401 (ola A6) |

## Lectura de formato viejo

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| residente | src/local_delegate/chains.py | lectura de formato viejo (REQ-022): `_OBSOLETE_SYNONYMS` acepta `residente` (y `resident`) como sinónimo obsoleto del paso `loaded` en `LOCAL_DELEGATE_FALLBACK_<ROL>`, con aviso de `doctor`; hoy el detector no lo marca, la fila deja escrito por qué sigue (ola A8a-1, respuesta 4) |

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
