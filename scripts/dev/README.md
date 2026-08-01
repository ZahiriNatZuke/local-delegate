# scripts/dev — bancos de prueba manuales

Herramientas de desarrollo que **no** forman parte del paquete ni del CI. Existen porque hay
tres cosas de este proyecto que ninguna suite automática verifica bien:

| Qué no cubre la suite | Cómo se prueba aquí |
|---|---|
| El panel «En curso» con delegaciones vivas de verdad | [`fake_backend.py`](./fake_backend.py) |
| Que los rangos del dashboard usen tu hora local | [`dashboard_timezone_check.py`](./dashboard_timezone_check.py) |
| Que el instalador no pise configuración ajena | `--home` contra un HOME simulado (abajo) |

Se montaron durante el desarrollo de la 0.11.0 y en su momento se perdieron al cerrar la
sesión. Están aquí para que la próxima vez no haya que reconstruirlas — reconstruir un banco
de pruebas es la forma más fiable de acabar no verificando nada.

## 1. Backend falso y lento

Un endpoint OpenAI-compatible con latencia controlada y respuestas deterministas. Permite ver
el panel «En curso» y ejercitar el chunking **sin GPU** y sin ensuciar el log real.

```bash
python scripts/dev/fake_backend.py --port 9595 --delay 1.5
```

Con `--truncate-first` la primera respuesta vuelve con `finish_reason='length'`, que es como se
ejercita el reintento del chunking (un trozo cortado se vuelve a partir).

Apuntando el MCP a él y con el dashboard en otro puerto se ve el ciclo completo:

```bash
LOCAL_DELEGATE_LOG_DIR=/tmp/ld-logs LOCAL_DELEGATE_WEB_PORT=9494 \
  uv run python -m local_delegate.web.metrics &

LOCAL_DELEGATE_LOG_DIR=/tmp/ld-logs LOCAL_DELEGATE_BASE_URL=http://127.0.0.1:9595/v1 \
  uv run python -c "from local_delegate import server; server.local_translate('inglés', path='grande.md')"

curl -s http://127.0.0.1:9494/api/inflight | python -m json.tool
```

Usa un `LOG_DIR` de usar y tirar: así el log real no se contamina con eventos de prueba.

## 2. Zona horaria del dashboard

```bash
uv sync --group dev --group ui && uv run playwright install chromium
python scripts/dev/dashboard_timezone_check.py --url http://127.0.0.1:9494/ --check-live
```

> **Los dos grupos, siempre.** Playwright vive en el grupo `ui` porque arrastra un navegador de
> ~150 MB que no todo el mundo necesita; un `uv sync` a secas lo **desinstala**, y entonces esto y
> las capturas dejan de funcionar sin que nada avise. Antes ni siquiera estaba declarado, que es
> por lo que esa trampa se pisó más de una vez. El navegador se instala aparte y solo una vez.

Abre el dashboard en Chromium con `timezone_id` forzado y compara qué instante calcula
`computeRange('today')` en cada zona. `--check-live` fuerza además los cuatro estados del
indicador manipulando `state` y llamando a `updateLive()`, en vez de esperar 30 minutos a que
caiga en reposo.

## 3. Instalador contra un HOME simulado

`--home` existe justamente para esto y `--no-client-cli` evita invocar el binario `claude` real:

```bash
uv run local-delegate install   --home /tmp/fakehome --no-client-cli --dry-run
uv run local-delegate install   --home /tmp/fakehome --no-client-cli
uv run local-delegate uninstall --home /tmp/fakehome --no-client-cli
```

Lo que hay que mirar: que tres instalaciones seguidas no dupliquen nada, que un hook ajeno siga
intacto, que el `config.toml` de Codex parsee, y que después de `uninstall` los archivos que ya
existían queden **byte a byte** como estaban. `tests/test_install.py` cubre esto contra
`tmp_path`; el paso manual sirve para probarlo en tu sistema real antes de tocar tu HOME.
