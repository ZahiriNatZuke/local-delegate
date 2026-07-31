# Brief: Check de doctor sobre los clientes MCP observados

## Problem

El PR #95 hizo que el daemon registrara **qué cliente MCP hay al otro lado** (nombre, versión,
revisión de protocolo negociada y capabilities declaradas) en `clients.jsonl` y en `/api/status`.
Pero `doctor` no lo mira: sus **catorce** comprobaciones (`checks.CHECKS`) no incluyen ninguna sobre
los clientes observados.

El resultado es que el dato existe y **nadie lo enseña por el camino que el usuario usa para
diagnosticar**. En particular no hay forma de responder desde el CLI a la pregunta que motivó el
PR #96: *¿el cliente con el que hablo soporta `elicitation`, o sea, las tools pueden preguntar en
vez de fallar seco?*

El check se dejó deliberadamente fuera del change anterior porque **qué cuenta como fallo solo se
podía decidir con el dato delante**. Ese dato ya está medido (ver `research.md`).

## Desired outcome

`local-delegate doctor` muestra una línea más, en el grupo `entorno`, que dice **con qué clientes
MCP ha hablado local-delegate**: nombre, versión, revisión de protocolo y si pueden responder
preguntas (`elicitation`). Cuando nunca se ha visto ninguno, lo dice como `[ -- ]` (`unknown`) y
**no altera el exit code**.

## In scope

- Un check nuevo `client.observed` en `checks.CHECKS`, grupo `entorno`.
- Leer las observaciones desde `clients.jsonl` (`config.LOG_DIR`), con un colaborador inyectable en
  `checks.Context`, siguiendo el patrón de los cuatro que ya existen.
- Deduplicar: quedarse con la observación **más reciente por nombre de cliente**.
- Actualizar las cinco afirmaciones de tamaño de `checks.py`, el mapa `_NUMERO` del test que las
  ata, la lista de checks no reparables de `update.py` y la wiki que dice «catorce piezas».

## Out of scope

- **Cambiar `clients.py`**: ni el formato del registro, ni la rotación, ni la deduplicación en
  escritura. El crecimiento del fichero es real (ver riesgos) pero es otro cambio.
- **Que `install` o `update` «reparen» nada**: no hay arreglo que dependa del repo; el check es de
  solo lectura y sin `fix_hint`.
- Tocar `/api/status`, el dashboard o su JS.
- Medir cómo **pinta** cada cliente la pregunta de `elicitation` (es trabajo de uso real, aparte).

## Constraints and risks

- `probe` **nunca escribe** — hay un test que compara el árbol del HOME byte a byte.
- Lo que no se pudo comprobar es `unknown`, **nunca** `missing`.
- El `detail` de un `Result` es **texto de interfaz**: nadie debe parsearlo.
- **Sin caracteres fuera de cp1252** en la salida: una flecha `→` mata el doctor en la consola de
  Windows.
- `config.LOG_DIR` **no depende de `HOME`**, así que `doctor --home <árbol simulado>` leerá el
  registro real de la máquina. Es el mismo comportamiento que ya tienen `service.daemon` y
  `service.backend`, pero hay que dejarlo escrito para que no se lea como el defecto del change C.
- **Riesgo de dato engañoso:** `clients.jsonl` es histórico y acumula una línea **por cada arranque
  de proceso** (medido). Sin deduplicar, el check enseñaría la misma identidad decenas de veces.

## Open questions

Ninguna abierta. Las dos que había quedaron resueltas por medición y están razonadas en `spec.md`:

1. **¿De dónde lee el dato?** De `clients.jsonl`, no de `/api/status` — el endpoint solo expone la
   memoria del proceso del daemon y **no ve a los clientes stdio**, que son justo Claude Code y
   Codex.
2. **¿Qué cuenta como fallo?** Nada salvo no poder leer. Un cliente sin `elicitation` es
   información, no un defecto, y no hay comando del repo que lo arregle.
