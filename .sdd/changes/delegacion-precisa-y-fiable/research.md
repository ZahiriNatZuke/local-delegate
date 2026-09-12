# Research: delegacion precisa y fiable

Consolida tres investigaciones: la de modelos abiertos (esta sesion, 2026-09-11), la de respaldo y
OmniRoute (sesion `yohan-ee`, mismo dia) y la medicion de adopcion hecha hoy sobre la telemetria
real. Lo verificado por ejecucion se marca como HECHO; lo demas, como HIPOTESIS.

## 1. Adopcion: medido hoy sobre 14 323 eventos de telemetria

Fuentes: `~/.claude/hooks/telemetry.jsonl` (2026-07-29 a 2026-09-11) y
`%LOCALAPPDATA%/local-delegate/usage-2026*.jsonl`. Corte del experimento: 2026-09-08 23:03, cuando
`LD_HOOK_READ_SUGGEST_KB` paso de 32 a 8 (PR #169).

| Medida | Resultado |
| --- | --- |
| Lecturas despues del cambio | 447 en 3 dias |
| Avisos emitidos | 85 (19,0 %) |
| Extensiones avisadas | `.md` 49, `.jpg` 18, `.txt` 15, `.json` 2, `.png` 1 |
| Delegaciones provocadas por un aviso | **0** |
| Llamadas reales en el periodo | 3, todas decididas por el agente (62 520 chars, cuadran al caracter con los resumenes de esta sesion) |

HECHO: el aviso **llega y acierta el tipo de fichero**; documentacion, que era el mercado real. HECHO:
la adopcion sigue en cero. Es la **cuarta medicion consecutiva con cero**, despues de las tres del
vault (`medicion-adopcion-delegacion.md`). Consecuencia de diseno: el problema no es la redaccion del
aviso ni su punteria, es que **sugerir no cambia la conducta**.

HECHO (contaminacion): 14 lecturas de 8-32 KB se registraron con `motivo: pequeno` despues del
cambio (13 el 09-09, 1 el 09-11), lo que con umbral 8 KB es imposible. HIPOTESIS de la causa, no
verificada: las sesiones ya abiertas heredan el entorno del lanzador con el umbral viejo. Apoya la
hipotesis que ese mismo dia otras sesiones si avisaban con 8 KB. Toda medicion futura debe anotar
cuando arranco la sesion.

Silencios despues del cambio: `acotada` 242, `pequeno` 74, `codigo` 46. La guarda de lectura acotada
es hoy la mayor fuente de silencio, y no esta medida su justificacion.

## 2. Clientes

Fuente: `%LOCALAPPDATA%/local-delegate/clients.jsonl`, 75 registros desde 2026-07-31.

- `claude-code` 51 registros; ultimo 2026-09-11.
- `claude-ai (via mcp-remote)` presente: **Claude Desktop esta registrado y se conecto el
  2026-09-11T23:08:45Z**. Su entrada MCP apunta al daemon (`127.0.0.1:9393/mcp`) con cabecera
  `Authorization` literal en `claude_desktop_config.json`.
- HECHO: **cero delegaciones registradas desde Claude Desktop**.
- HECHO: los hooks son un mecanismo exclusivo de Claude Code. En Desktop no existe el umbral ni
  ningun aviso, asi que F1 no le aplica sin un mecanismo propio (pregunta abierta P-2).

## 3. Defectos de `_post_chat`, verificados por ejecucion

Verificados hoy con dobles del cliente `httpx2`, sin tocar el backend
(`scratchpad/verificar_defectos.py`). La sesion anterior los habia deducido leyendo el codigo; aqui
dejan de ser hipotesis.

| Defecto | Evidencia de ejecucion | Estado |
| --- | --- | --- |
| `content: null` en `server.py:605` | `AttributeError: 'NoneType' object has no attribute 'strip'`, sin capturar: se escapa de `_post_chat` | HECHO |
| `ConnectTimeout` mal clasificado | Devuelve `error='http_error'`; `issubclass(ConnectTimeout, ConnectError)` es `False`. No dispara autoarranque ni la pregunta | HECHO |
| `ReadTimeout` igual | Devuelve `error='http_error'` | HECHO (era inferencia de la otra sesion) |
| Control positivo | Un `ConnectError` real si devuelve `error='connect_error'` | HECHO |
| `retry_exhausted` (`server.py:659-663`) | Con `ConnectError` en el segundo intento la funcion retorna antes; la linea final no se alcanza por ese camino | HECHO parcial: la inalcanzabilidad total sigue siendo por razonamiento sobre las ramas |

Mapa de impacto completo con fichero:linea en
`.sdd/changes/fallback-entre-modelos-locales/research.md` (no se duplica aqui). Puntos clave: todas
las llamadas pasan por `_run_chat`; `_post_chat` no distingue 4xx de 5xx; el desborde de contexto
llega como HTTP 400 y se detecta por texto; solo lo trata map-reduce.

## 4. OmniRoute: que se toma y que no

Origen: un reel de Instagram (2026-09-10) que el usuario pidio transcribir. El proyecto real es un
proxy local que reparte peticiones entre proveedores; **no es un plugin de Claude Code**. Lo
estudiaron dos subagentes leyendo su codigo y sus issues. **Nunca se instalo ni se ejecuto.**

**NO SE INSTALA, y la spec lo deja escrito:**

- CVE-2026-88062, ejecucion remota critica con prueba de concepto publica.
- Contradiccion sin resolver: la base de avisos lo marca vulnerable en `<=3.8.50` sin version
  corregida; el aviso del repo dice que se corrigio en 3.8.49. Verificado con
  `gh api /advisories/GHSA-hf57-cqmx-p4gr`.
- Camuflaje de huella TLS y baneos de cuentas reportados (Anthropic, Google).

**Ideas de diseno que si se toman** (de `fallbackPolicy.ts`, `accountFallback.ts`,
`circuitBreaker.ts`):

1. Tres capas separadas: clasificar el error, decidir si se salta, y llevar el estado de salud del
   modelo. Hoy las tres estan mezcladas en `_post_chat`.
2. Un error de la peticion (4xx del cliente) no penaliza al modelo.
3. El estado de enfriamiento tiene salida de prueba y tope, nunca es permanente.

## 5. Catalogo de modelos

Nota canonica: vault `projects/llms/investigacion-modelos-abiertos-2026-09.md`; informe navegable en
el artifact publicado el 2026-09-11. Resumen para F2:

- Presupuesto real: 16 GB de VRAM + ~26 GB de RAM tras limpiar, es decir, ~40 GB de pesos.
- Candidatos que caben enteros en la GPU: Gemma 4 26B-A4B (85-99 tok/s medidos en 5060 Ti),
  Qwen3.8-27B (35 tok/s, 50-55 con MTP), gpt-oss-20b (121 tok/s medidos en esta maquina).
- Candidatos con expertos en RAM: Qwen3.6-35B-A3B (~50 tok/s en un equipo gemelo), North-Mini-Code,
  KAT-Coder-V2.5, Laguna XS 2.1, Nemotron 3.5 Lightning.
- Roles rapidos: MiniCPM5-2B (2026-09-06), Gemma 4 E4B, LFM2.5-2.6B.
- El descarte de gpt-oss-20b de julio **no es concluyente**: el gate media la RAM de todo el sistema.

## 6. Lo que sigue sin saberse

- Cuanto de los 242 silencios por "lectura acotada" eran casos donde si convenia delegar.
- Si bloquear (en vez de avisar) se acepta en la practica o molesta lo bastante como para que el
  usuario apague el hook. No hay dato: nunca se ha probado.
- El coste real de comprimir la salida de una tool antes de que entre al contexto.
- Los numeros del enfriamiento, sin medir (vienen de bajar de escala los de OmniRoute).
- Si `retry_exhausted` es inalcanzable por todos los caminos, no solo por el de `ConnectError`.
