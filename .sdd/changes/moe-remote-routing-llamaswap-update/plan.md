# Implementation plan: fase de investigacion y decision

## Approach

Ejecutar cuatro tracks independientes en orden de menor riesgo. Cada track produce datos y una
decision; las implementaciones de producto se abren despues como cambios SDD separados. No se
actualiza el entorno estable durante este plan.

## Ordered tasks

1. **Harness MoE y corpus**
   - Crear corpus pequeño versionable sin datos privados, rubricas y runner de benchmark.
   - Capturar version, flags, seed, contexto, cuantizacion, RAM/VRAM, tok/s, latencia y respuesta.
   - Probar gpt-oss-20b MXFP4 con `--n-cpu-moe` 0/6/12/18/24 a 8k/16k/32k.
   - Comparar con Gemma 3 4B y Llama 3.1 8B; hacer tres corridas y cold/hot split.
   - Gate: decidir `adopt/iterate/reject`; solo si adopta, repetir con Qwen3-30B-A3B Q4_K_M.
   - Requirements: REQ-001..004.
   - Rollback: modelos/config canary separados; no tocar `config.yaml` estable.

2. **Piloto de inferencia de delegacion en Claude Code**
   - Añadir instrumentacion agregada de oportunidades sin contenido.
   - Reemplazar el aviso tardio Post-Bash por Pre-Bash y probar bandas Read 8/32 KiB.
   - Probar un hook `UserPromptSubmit` determinista para intenciones mecanicas explicitas.
   - Compactar la regla global y auditar allowlists de los 40 agents; no inyectar la skill completa
     donde solo duplicaria contexto.
   - Ejecutar A/B por sesiones equivalentes y revisar manualmente una muestra de sugerencias.
   - Gate: >=40% adopcion elegible, <=10% falsos positivos, mejora neta de tokens.
   - Requirements: REQ-005..006.
   - Rollback: hooks consultivos, feature flag y backup de settings/instrucciones.

3. **Prueba remota Mac -> PC**
   - Crear recipe con MCP local en Mac y `LOCAL_DELEGATE_BASE_URL` remoto.
   - Configurar canary de llama-swap en interfaz privada con `apiKeys`; secretos solo por env/keychain.
   - Probar inline, path local de Mac, archivo largo, reconexion y dos llamadas concurrentes.
   - Comparar con daemon MCP remoto para dejar documentada la limitacion de paths.
   - Gate: 20/20 llamadas, auth cerrada, path preservado y overhead aceptable.
   - Requirements: REQ-007..008.
   - Rollback: volver endpoint a loopback; no cambiar scopes globales hasta aprobar.

4. **Canal de actualizacion de backends**
   - Automatizar reporte `instalada/probada/latest/edad/issues relevantes`, sin auto-upgrade.
   - Esperar ventana de 7 dias de v241/b10098 o escoger un tag posterior que cierre issues.
   - Descargar lado a lado, verificar checksum, copiar config y correr suite backend completa.
   - Soak 24 h, probar rollback y solo entonces proponer cambios a doctor/README/Wiki.
   - Requirements: REQ-009.
   - Rollback: binario estable nunca se sobrescribe hasta promocion atomica.

5. **Decision y especificaciones de implementacion**
   - Publicar matriz de resultados y decisiones `adopt/iterate/reject`.
   - Si MoE aporta: abrir cambio para perfil/diagnostico MoE; no necesariamente un rol nuevo.
   - Si documentos fallan por tamaño: abrir cambio separado de chunking/PDF y auditar cualquier
     dependencia con Socket antes de añadirla.
   - Si hooks pasan: abrir cambio de integracion Claude y sincronizacion de agents.
   - Si remoto pasa: publicar recipe y decidir si hace falta CLI de setup.
   - Requirements: REQ-010.

## Test strategy

- Unit: parsers/runners, hook classification, redaction y reporte de versiones.
- Integration: llama-server/llama-swap canary, MCP Mac/backend PC, concurrency y auth.
- Quality: corpus con respuestas esperadas y revision ciega de outputs.
- Security: secret scan, bind privado, respuestas 401, logs sin prompts/tokens.
- Reproducibility: resultados crudos versionados cuando no contengan datos privados; metadata de
  hardware/software completa.

## Migration and compatibility

No hay migracion durante este plan. Stable permanece en v238/b9925, loopback y catalogo actual.
Cada experimento usa config, puerto y directorio separados. La promocion futura sera otro cambio.

## Plan review

- [x] Todos los requisitos tienen tarea y gate cuantitativo.
- [x] Modelos/binarios/configuraciones se aislan del entorno estable.
- [x] La topologia remota preserva `path` y no depende de una VPN concreta.
- [x] El plan corrige la premisa de expertos por tarea.
- [x] PDF/chunking y nuevas dependencias no se cuelan sin especificacion separada.

Adversarial review: el mayor riesgo era implementar un rol MoE sin demostrar calidad o exponer el
MCP remoto perdiendo acceso a paths. El orden actual elimina ambos: benchmark antes de catalogo y
MCP local/backend remoto como topologia primaria.
