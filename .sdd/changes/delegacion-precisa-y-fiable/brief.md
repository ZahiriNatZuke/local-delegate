# Brief: delegacion precisa y fiable

## Problem

El MCP `local-delegate` existe para que los pasos mecanicos (resumir, clasificar, extraer,
boilerplate, traducir, explicar codigo, describir imagenes) acaben en modelos locales y no gasten
contexto ni cuota del modelo principal. Hoy eso **no ocurre**, y esta medido:

- **Cuarta medicion seguida con adopcion cero.** Entre el 2026-09-08 23:03 (umbral del hook de Read
  bajado de 32 KB a 8 KB) y el 2026-09-11 hubo **447 lecturas, 85 avisos y cero delegaciones**
  provocadas por un aviso. Las unicas 3 llamadas del periodo las decidio el agente por su cuenta.
- **El aviso ya acierta el blanco.** Tras bajar el umbral, los 85 avisos caen sobre `.md` (49),
  `.txt` (15), `.json` (2) e imagenes (18): documentacion, que era el mercado real identificado.
  Es decir, el problema ya no es punteria ni latencia: es que **sugerir no cambia la conducta**.
- **El experimento esta contaminado.** 14 lecturas de 8-32 KB se callaron por "pequeno" despues del
  cambio (13 el 09-09, 1 el 09-11): las sesiones ya abiertas heredan el umbral viejo del lanzador.
- **Claude Desktop no tiene hooks.** Su entrada MCP existe y se conecto el 2026-09-11, pero alli no
  hay aviso posible: la delegacion depende solo de que el modelo elija la tool. Cero delegaciones
  registradas desde ese cliente.

A eso se suma que la parte de fiabilidad tiene defectos **verificados por ejecucion** (ver
`research.md`) y que el catalogo de modelos locales lleva meses sin revisarse, con candidatos nuevos
publicados entre junio y septiembre de 2026 que caben en la maquina.

## Desired outcome

1. Un paso mecanico identificable acaba en un modelo local **por regla**, no por criterio del agente,
   y lo que no se pueda decidir por regla se mide para saber cuanto se escapa.
2. Un fallo del backend se clasifica bien y el sistema se recupera solo cuando puede.
3. El catalogo de modelos se elige **con mediciones propias**, no con benchmarks de terceros.
4. Todo lo anterior es observable: ofrecido, aceptado, rechazado y por que.

## In scope

Cuatro fases, en este orden (decision del usuario, 2026-09-11):

- **F0 - Deteccion de fallos.** Arreglar los tres defectos verificados de `_post_chat`.
- **F1 - Precision de la delegacion.** Decidir por reglas en vez de sugerir, comprimir salidas antes
  de que entren al contexto, y medir lo ofrecido frente a lo aceptado. Absorbe el cambio abierto
  `read-obliga-a-delegar`.
- **F2 - Catalogo de modelos.** Protocolo de medicion propio y eleccion de modelo por rol.
- **F3 - Respaldo y enfriamiento.** Los 20 requisitos heredados de
  `.sdd/changes/fallback-entre-modelos-locales/`, que queda **absorbido y sin aprobar por separado**.

## Out of scope

- **Instalar OmniRoute o cualquier parte de su codigo.** Solo se toman ideas de diseno. Motivo en
  `research.md`: CVE-2026-88062 (RCE critica con PoC publico), contradiccion sin resolver sobre la
  version corregida, camuflaje de huella TLS y baneos de cuentas reportados.
- Proveedores externos o de pago: todo sale de `LOCAL_DELEGATE_BASE_URL`.
- El fork de streaming de KV de llama.cpp: da contexto, no modelos mas grandes, y en esta maquina
  (PCIe 4.0 x8) no compensa.
- Cambiar el contrato de las tools `local_*` mas alla de lo que exija una fase.

## Constraints and risks

- **Una sola GPU de 16 GB** y ~26 GB de RAM util tras limpiar el equipo; PCIe 4.0 x8.
- **llama.cpp b9925 es del 2026-07-08**; la rama principal va ~1 000 builds por delante y ha
  eliminado flags (`--mmap`, `--mlock`, `--direct-io`). Cualquier prueba exige fijar la version.
- **Windows**: el driver desborda VRAM a RAM en silencio salvo que se active "Prefer No Sysmem
  Fallback"; `--cache-ram` reserva hasta 8 GB de RAM por proceso; la memoria del proceso se mide con
  `PrivateMemorySize64`, no con el working set.
- **Riesgo principal de F1**: bloquear por regla molesta al usuario si la regla se equivoca. La
  puntería ya esta medida por extension y tamano, pero bloquear es irreversible dentro de la sesion.
  Por eso el bloqueo se apaga en caliente (REQ-F1-11) y se cae solo cuando no hay a donde delegar
  (REQ-F1-10).
- **Riesgo de medicion**: una sesion abierta hereda la configuracion vieja. Toda medida debe anotar
  cuando arranco la sesion y con que version.
- **Riesgo de desvio**: bloquear un camino de lectura no cierra los demas (`cat`, `Get-Content`,
  `rtk read`, las tools de otros MCP). Si solo se cuenta el camino cerrado, la adopcion medida sube
  sin que se ahorre un token. De ahi REQ-F1-9 y la pregunta P-6.
- **Restriccion del cliente**: reescribir la salida de una herramienta antes de que entre al
  contexto no tiene mecanismo viable hoy, y esta medido (0.27.0, `CHANGELOG.md:127-141`). REQ-F1-4
  queda suspendido hasta P-7.

## Open questions

- ~~**P-1**~~ **RESUELTA (2026-09-11): bloquear y obligar a delegar.** La lectura que cumple el caso
  acotado se rechaza con un mensaje que nombra la tool; no se sustituye la salida por el resumen.
- **P-2**: que hacer con Claude Desktop, donde no hay hooks. Sin mecanismo propio, F1 no le aplica.
- ~~**P-3**~~ **RESUELTA (2026-09-11): hasta 2 saltos, y el primero va siempre al residente.**
- **P-4**: los numeros del enfriamiento (3 fallos, 120 s, x2, tope 900 s) no estan medidos. Se
  parametrizan o se validan con datos de F2.
- **P-5**: si un solo modelo grande puede cubrir varios roles, lo que cambiaria las cadenas de F3.
- ~~**P-6**~~ **RESUELTA (2026-09-11): se cierran `Read` y las lecturas completas de shell; las tools de lectura de otros MCP solo se miden.** Pregunta original: de la superficie de lectura de REQ-F1-9, **que caminos se
  cierran** ademas de la tool `Read`. Opciones, de menos a mas: (a) solo `Read`, y los demas
  caminos se **miden** para saber cuanto se desvia; (b) `Read` mas las lecturas completas por
  `cat`/`Get-Content`/`rtk read` en Bash y PowerShell, que es donde el desvio es trivial; (c)
  ademas, las tools de lectura de otros MCP. Recomendacion: **(b)**, porque (a) deja abierta la
  salida de un solo caracter y (c) toca superficie de terceros sin dato que lo justifique. En
  cualquier caso, medir **todos** los caminos es obligatorio: es lo unico que distingue «se
  delego» de «se leyo por otro lado».
- **P-7 (bloquea REQ-F1-4)**: si queda algun mecanismo para recortar o resumir la salida de una
  herramienta antes de que entre al contexto. Lo medido dice que no: `PostToolUse` llega tarde y
  `updatedInput` se salta el allowlist de permisos. Mientras no haya respuesta, el requisito esta
  suspendido y **no entra al plan**; lo que si da ahorro y ya funciona es leer del lado del
  servidor con `path`.
