# Excepciones del detector de nombres en español (REQ-016)

`name_exceptions.json` es la lista de nombres en español que pueden quedar en el repo, cada uno
con su motivo. La lee `scripts/detect_spanish_names.py` (por defecto; otra lista con
`--exceptions <fichero.json>`) y la vigila el test
`test_repo_has_no_spanish_name_outside_the_exception_list`, que falla si el fichero falta.

Formato: `sections` es una lista de secciones, una por motivo (`title`, `note` opcional y
`entries`); cada entrada es `{"name", "file", "reason"}`. Un hallazgo se aparta cuando coinciden el
nombre y el fichero: los dos admiten comodines (`*` para cualquiera); el nombre distingue
mayúsculas y el fichero es un glob relativo a la raíz del repo. Toda entrada lleva su motivo.

Nació como `.sdd/changes/english-names-bilingual-output/rename-exceptions.md` (tablas Markdown) y se
mudó aquí tras la 0.36.0 para que el guardián no dependa de la carpeta del cambio, que se archiva.

Los únicos motivos válidos (REQ-016):

- alias de compatibilidad (REQ-001, REQ-002, REQ-012), con su versión de retirada;
- lectura de formato viejo (excepción de REQ-005, REQ-006, REQ-007, REQ-008);
- envoltorio de REQ-046;
- dato de un tercero que no controla el paquete;
- dato de prueba del propio detector: nombres en español que sus tests y su léxico necesitan como
  entrada (enmienda del 2026-10-12 tras la ola A0);
- palabra inglesa que el léxico del detector clasifica como española (enmienda del 2026-10-13,
  ola A8b, aprobada por la sesión principal): `meter` es «medidor» en inglés y el verbo «meter» en
  español; el nombre está en inglés y no se renombra;
- dato congelado de corpus o caso (enmienda del 2026-10-13, ola A10, aprobada por la sesión
  principal como desviación de REQ-016): ids, contenido y valores ya escritos en corpus o copias
  congeladas (`benchmarks/`, `tests/fixtures/`) que no se reescriben;
- entrada de interfaz escrita por una persona (enmienda del 2026-10-14, ola A10b-5, aprobada por la
  sesión principal como desviación de REQ-016): las respuestas que la persona escribe a mano en
  una hoja `.md` en español (`si`, `parcial`, `empate`), y lo que el programa guarda de ellas; se
  traducen en el frente B, que lee las dos formas;
- texto de salida que traduce el frente B (enmienda del 2026-10-14, cierre del frente A, decisión 1
  de la sesión principal, como desviación de REQ-016): rótulos y motivos que ve una persona y que
  el detector toma por nombres de máquina (rótulos del JS del panel, `sin_cruce` de `recompute`,
  `pruebas` de `excluded_by_reason`); cada fila nombra la ola B que lo traduce;
- **pendiente**: lo que el frente A renombra pero se publica en el B (las subclaves y marcadores
  de REQ-010, que salen en B2).

Al cerrar el frente A, la sección «Pendiente» solo puede tener lo de REQ-010; al cerrar el cambio,
tiene que estar vacía, igual que «Texto de salida que traduce el frente B».
