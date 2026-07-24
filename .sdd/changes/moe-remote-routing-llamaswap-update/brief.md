# Brief: investigacion MoE, delegacion, acceso remoto y politica de backends

## Problem

Hay cuatro ideas de evolucion que todavia no deben convertirse directamente en codigo:

1. evaluar si un modelo Mixture of Experts mejora las tareas mecanicas de `local-delegate` en
   una RTX 5060 Ti de 16 GiB y un host de 32 GiB de RAM;
2. lograr que Claude Code detecte oportunidades de delegacion con una frecuencia comparable a
   Codex sin delegar trabajo que exige criterio;
3. usar desde una Mac el computo de la PC sin perder la ventaja de `path` server-side;
4. actualizar `llama-swap` y `llama-server` solo despues de un periodo de maduracion y pruebas.

La hipotesis inicial de "montar cierta cantidad de expertos segun la tarea" no coincide con el
funcionamiento habitual de un MoE: el numero de expertos activos por token lo fija la arquitectura
y el router aprendido del modelo. El operador decide ubicacion de pesos (GPU/CPU), cuantizacion y
contexto, no cuantos expertos necesita un resumen concreto.

## Desired outcome

Un paquete de decision con evidencia reproducible: candidatos, corpus de prueba, matriz de
offload/contexto, umbrales de delegacion, topologia remota recomendada, politica de actualizacion y
criterios objetivos para aprobar o descartar cada feature antes de implementarla.

## In scope

- Explicar MoE, memoria total frente a parametros activos y limites de llama.cpp.
- Seleccionar como maximo dos candidatos GGUF confiables para un benchmark local.
- Diseñar benchmarks de resumen, extraccion, logs, codigo y documentos largos.
- Auditar instrucciones, skills, agents y hooks de Claude Code con evidencia de uso real.
- Comparar MCP remoto directo contra MCP local con backend remoto.
- Definir un canal canary y rollback para `llama-swap`/`llama-server`.
- Dejar una especificacion y plan aprobables; no ejecutar la implementacion.

## Out of scope

- Descargar modelos, actualizar binarios o cambiar configuraciones activas en esta fase.
- Configurar Tailscale, VPN, DNS, TLS o firewall.
- Cambiar el `top-k` interno de un modelo MoE o entrenar/afinar expertos.
- Prometer soporte directo de PDF antes de definir extraccion y chunking.
- Publicar una release de `local-delegate`.

## Constraints and risks

- El host necesita margen: objetivo maximo 14.5 GiB VRAM y 28 GiB RAM durante pruebas.
- `local_summarize(path=...)` hoy lee texto y trunca segun `MAX_CHARS`; un PDF binario o documento
  mayor de 48k caracteres no es una prueba valida de resumen completo sin pipeline adicional.
- La ruta de una Mac no existe en la PC: un MCP remoto directo rompe la semantica de `path`.
- No se guardan prompts, contenido de archivos, tokens ni credenciales en telemetria o SDD.
- Los proyectos upstream son rolling release; "latest" no equivale a "recomendado".

## Open questions to resolve experimentally

- ¿`gpt-oss-20b` mejora calidad suficiente frente a Gemma 3 4B/Llama 3.1 8B para justificar carga?
- ¿Que `--n-cpu-moe` produce el mejor balance memoria/latencia sin degradar estabilidad?
- ¿Hace falta un pipeline map-reduce y un extra de documentos antes de ofrecer resumen de PDF?
- ¿Que umbral y hook aumentan delegacion en Claude sin falsos positivos molestos?
- ¿La topologia de backend remoto preserva dashboard, auth y rendimiento en la Mac real?
