# Benchmark MoE canary

Este corpus es sintetico y no contiene datos privados. El runner no descarga ni arranca modelos:
apunta a un endpoint canary ya aislado y produce JSONL reproducible. La plantilla
`llama-swap-canary.yaml` publica las 15 combinaciones en `127.0.0.1:9294`; exige un token efimero
por `CANARY_API_KEY`.

```powershell
$env:LLAMA_SERVER_EXE = 'D:\ruta\a\llama-server.exe'
$env:GPT_OSS_GGUF = 'D:\ruta\a\gpt-oss-20b-MXFP4.gguf'
$env:CANARY_API_KEY = '<token-efimero>'
$env:LOCAL_DELEGATE_API_KEY = $env:CANARY_API_KEY
llama-swap --config benchmarks/moe/llama-swap-canary.yaml --listen 127.0.0.1:9294
```

```powershell
uv run local-delegate benchmark `
  --endpoint http://127.0.0.1:9294/v1 `
  --model gpt-oss-20b-c8k-m12 `
  --label gptoss-mxfp4-ncmoe12-c8k `
  --quantization MXFP4 --context-size 8192 --n-cpu-moe 12 `
  --reasoning-effort low `
  --llama-swap-version v238 --llama-server-version b9925 `
  --cases benchmarks/moe/cases.json `
  --runs 3 `
  --save-responses `
  --output scratch_/bench-gptoss-ncmoe12-c8k.jsonl
```

La etiqueta debe codificar cuantizacion, `--n-cpu-moe` y contexto. El archivo guarda hashes de
entrada/respuesta, uso reportado por el backend, latencia, cobertura de terminos y picos muestreados
desde `/metrics`. También conserva los `timings` que devuelva llama-server y separa la primera
corrida `cold` de las siguientes `hot`. No guarda API keys. Sin `--save-responses`, tampoco guarda
el texto generado.

Orden de la matriz aprobada:

1. Baselines densos actuales.
2. gpt-oss-20b MXFP4 con `--n-cpu-moe` 0/6/12/18/24 y contexto 8k/16k/32k.
3. Qwen3-30B-A3B Q4_K_M solo si gpt-oss pasa los gates de memoria, estabilidad y calidad.
