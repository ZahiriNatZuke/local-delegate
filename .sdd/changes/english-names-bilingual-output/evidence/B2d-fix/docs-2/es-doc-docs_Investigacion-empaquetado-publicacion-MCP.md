# Investigación: empaquetar `local-delegate` como MCP publicable + repo GitHub (README + wiki)

> Estado del proyecto a la fecha (2026‑07‑06): MCP `local-delegate` funcional con 9 tools, logging JSONL, web de métricas (auto‑arranque en hilo daemon + preview de Claude Code). Repo local en `D:\Projects\llms\local-delegate` **sin commits, sin remote** (pizarra limpia, sin secretos en el historial).

---

## 1. Resumen ejecutivo (TL;DR)

- **Sí es publicable**, pero hoy está **acoplado a tu entorno** (rutas `D:\Projects\llms\...`, catálogo de 4 modelos concretos, auto‑arranque de llama‑swap, y trabajo personal como `update_agents.py` + 27 subagentes). El grueso del trabajo no es "publicar", es **desacoplar** para que sirva a cualquiera.
- **Ruta recomendada:** distribuir como **paquete Python en PyPI ejecutable con `uvx`** + registrarlo en el **registro oficial MCP** (`server.json` vía `mcp-publisher`). Es lo más natural para un MCP stdio en Python con `uv`, y `uvx` da a los usuarios "cero instalación".
- **Modelo mental clave:** publicar el MCP como un **cliente genérico de cualquier endpoint OpenAI‑compatible** (llama‑swap, Ollama, LM Studio, vLLM…). Tu setup concreto (llama‑swap + 4 GGUF + Blackwell) pasa a ser **una guía de referencia en la wiki**, no una dependencia dura del paquete.
- **Separar dos cosas:** (a) el **paquete publicable** (`local-delegate` MCP genérico); (b) tu **integración personal** (auto‑arranque de llama‑swap, `update_agents.py`, los 27 agentes, la skill). Lo personal NO se publica, o va como "extras/recipes" opcionales.
- **Seguridad:** los 3 configs de Claude (`claude_desktop_config.json` en especial) tienen **secretos en claro** y **no pertenecen a este repo**. Basta con no incluirlos + `.gitignore` + plantillas `*.example`. Como el repo aún no tiene commits, no hay que reescribir historial.
- **Directorio limpio (greenfield):** el paquete se construye **desde cero en `D:\Projects\local-delegate`** (nuevo, separado de `llms\`). El montaje actual en `D:\Projects\llms\local-delegate` **sigue intacto y funcionando** hasta el **switch‑over final**. Nada se rompe por el camino.

---

## 2. El reto real: desacoplar antes de publicar

Inventario de acoplamientos y qué hacer con cada uno:

| Acoplamiento actual | Problema para publicar | Solución |
|---|---|---|
| Rutas `D:\Projects\llms\...` hardcodeadas (`SWAP_CONFIG`, `USAGE_LOG`, `LLAMASWAP_EXE`) | No existen en otra máquina | Config por **variables de entorno** con defaults sensatos y multiplataforma (`platformdirs`) |
| Catálogo fijo `gemma3-4b / llama31-8b / qwen25-coder-14b / qwen35-2b` | Otros no tienen esos modelos | Catálogo/routing **configurable** (archivo `models.toml` o env); defaults documentados |
| Auto‑arranque de llama‑swap (proceso DETACHED, rutas del `.exe`) | Muy específico de tu PC | Convertir en **opt‑in** (`LOCAL_DELEGATE_AUTOSTART=0` por defecto en el paquete). Por defecto: "trae tu endpoint ya corriendo" |
| Web embebida en el MCP | Puede no quererla todo el mundo | Ya es un flag (`LOCAL_DELEGATE_WEB`); mantener **desactivada por defecto** en el paquete o documentarla |
| `update_agents.py` + 27 subagentes + skill (`~/.claude/...`) | Es TU integración de Claude Code | **Fuera del paquete.** Va como `docs/recipes/` o repo aparte |
| `.claude/launch.json` con ruta absoluta al venv | Máquina‑específica | Usar `uvx local-delegate` o `${workspaceFolder}`; dar plantilla |

**Regla de oro del refactor:** el paquete solo debe asumir **"un endpoint OpenAI‑compatible en una URL"**. Todo lo demás (qué motor lo sirve, en qué hardware, con qué modelos) es configuración + documentación.

---

## 2.bis — Estrategia de directorio limpio (greenfield)

**Decisión:** el MCP empaquetado se crea **desde cero en `D:\Projects\local-delegate`** (directorio nuevo, fuera de `llms\`). Motivos:

- El montaje actual (`D:\Projects\llms\local-delegate`) es el MCP **registrado y en uso**; refactorizarlo en sitio arriesga romper la sesión durante la migración.
- El directorio actual queda como **implementación de referencia**: la lógica se **porta** desde ahí (copiar + adaptar), no se edita.
- El **switch‑over** (repuntar los 3 configs de Claude al nuevo paquete vía `uvx` y reiniciar Claude) se hace **al final, en un solo paso**, cuando el nuevo esté probado. Hasta entonces, todo lo de hoy sigue vivo.

**Se porta (copiar + adaptar):** `server.py` (tools + `_chat` + logging), `metrics_web.py`, y `update_agents.py` → `docs/recipes/`.
**No se toca hasta el switch‑over:** el registro MCP actual, el `usage.jsonl` de hoy, los 27 agentes, la skill, los scripts en `llms\local-delegate`.

## 3. Parte A — Empaquetar el MCP para publicar

### 3.1. Panorama de distribución

| Canal | Qué es | Encaje aquí |
|---|---|---|
| **PyPI + `uvx`** | Paquete Python; `uvx local-delegate` lo baja y ejecuta aislado | ✅ **Recomendado** (es Python + `uv`, stdio) |
| **Registro oficial MCP** | Índice de metadatos (no aloja artefactos); `server.json` | ✅ **Recomendado** encima de PyPI para descubribilidad |
| npm | Para MCPs en Node | ❌ No aplica |
| Docker | Imagen con todo dentro | ⚠️ Opcional; útil si empaquetas también un motor, pero pesado por los GGUF |
| **DXT** (Desktop Extension) | Bundle 1‑clic para Claude Desktop | ⚠️ Opcional más adelante; buena DX para no técnicos |

### 3.2. Recomendación y por qué

**PyPI (artefacto) + registro oficial MCP (descubrimiento), ejecutable con `uvx`.** Motivos: ya usas `uv`; `uvx` da instalación cero al usuario (`uvx local-delegate`), aislado; el registro oficial es el índice canónico que consumen los clientes MCP. Docker/DXT quedan como mejoras futuras.

### 3.3. Refactor mínimo para que sea genérico

1. **Layout `src/`** con paquete importable y un entry point:
   ```
   local-delegate/
   ├─ pyproject.toml
   ├─ src/local_delegate/
   │  ├─ __init__.py        # main() -> arranca el server MCP
   │  ├─ server.py          # tools + _chat + logging (sin rutas D:\)
   │  ├─ config.py          # lee env / archivo config, defaults multiplataforma
   │  └─ web/metrics.py     # web opcional
   └─ README.md
   ```
2. **`pyproject.toml`** con script de consola:
   ```toml
   [project]
   name = "local-delegate-mcp"
   version = "0.1.0"
   requires-python = ">=3.11"
   dependencies = ["mcp>=1.2", "httpx>=0.27"]
   # web opcional como extra:
   [project.optional-dependencies]
   web = ["fastapi", "uvicorn"]

   [project.scripts]
   local-delegate = "local_delegate:main"
   ```
   Así `uvx local-delegate` funciona y en configs MCP se pone `command: "uvx"`, `args: ["local-delegate"]`.
3. **Externalizar config** (con defaults): `LOCAL_DELEGATE_BASE_URL` (endpoint OpenAI‑compatible; default `http://127.0.0.1:9292/v1`), `LOCAL_DELEGATE_LOG` (default en dir de datos de usuario vía `platformdirs`, no `D:\`), catálogo/routing de modelos configurable. **Quitar todas las rutas `D:\` del código.**
4. **Desacoplar llama‑swap:** el auto‑arranque pasa a `LOCAL_DELEGATE_AUTOSTART=0` por defecto. El paquete asume que el endpoint ya corre; tu auto‑arranque se documenta como "recipe" para llama‑swap.
5. **Separar lo personal:** `update_agents.py`, los 27 agentes y la skill **no** entran al paquete. Van a `docs/recipes/` (ejemplos) o a un repo aparte "local-delegate-claude-code-integration".

### 3.4. `server.json` (registro oficial MCP)

Esquema real (obtenido de la doc oficial). Genera la plantilla con `mcp-publisher init` y edítala:

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.<tu-usuario>/local-delegate",
  "description": "Delegate mechanical text tasks to a local OpenAI-compatible LLM endpoint to conserve Claude subscription quota.",
  "repository": { "url": "https://github.com/<tu-usuario>/local-delegate", "source": "github" },
  "version": "0.1.0",
  "packages": [
    {
      "registryType": "pypi",
      "identifier": "local-delegate-mcp",
      "version": "0.1.0",
      "transport": { "type": "stdio" },
      "environmentVariables": [
        { "name": "LOCAL_DELEGATE_BASE_URL", "description": "OpenAI-compatible endpoint", "isRequired": false, "format": "string", "isSecret": false }
      ]
    }
  ]
}
```

- El `name` **debe** empezar por `io.github.<tu-usuario>/` (autenticación GitHub) y **coincidir** con la verificación del paquete.
- **Verificación PyPI:** el README publicado en PyPI debe incluir la cadena `mcp-name: io.github.<tu-usuario>/local-delegate` (puede ir en un comentario HTML). Es el equivalente del `mcpName` de npm.
- `environmentVariables` soporta `isSecret: true` para marcar credenciales (aquí no hay secretos: todo es local).

### 3.5. Flujo de publicación (paso a paso)

1. `uv build` → genera `dist/*.whl` + `*.tar.gz`.
2. `uv publish` (o Trusted Publishing por OIDC en CI, sin tokens) → sube a PyPI. Verifica en `https://pypi.org/project/local-delegate-mcp/`.
3. Instala el CLI del registro: `mcp-publisher` (binario oficial de `modelcontextprotocol/registry`).
4. `mcp-publisher init` → genera `server.json`; edítalo.
5. `mcp-publisher login github` → device‑code auth.
6. `mcp-publisher publish` → publica metadatos. Verifica con la API del registro.
7. **Automatizable** con GitHub Actions + OIDC (sin guardar secretos).

### 3.6. Versionado y releases

SemVer (`0.y.z` mientras sea preview), `CHANGELOG.md` (Keep a Changelog), tags `vX.Y.Z` y GitHub Releases. Cada release: bump de versión en `pyproject.toml` **y** en `server.json` (deben coincidir con el paquete).

---

## 4. Parte B — Repo de GitHub (README + wiki + seguridad)

### 4.1. Estructura propuesta

> Ubicación del repo: **`D:\Projects\local-delegate`** (nuevo/limpio; el viejo `llms\local-delegate` no se toca hasta el switch‑over).

```
local-delegate/            # = D:\Projects\local-delegate
├─ .github/
│  ├─ workflows/{ci.yml, publish.yml}   # tests + publish PyPI/registro (OIDC)
│  ├─ ISSUE_TEMPLATE/ , PULL_REQUEST_TEMPLATE.md
├─ src/local_delegate/...
├─ tests/
├─ docs/
│  ├─ recipes/llama-swap-blackwell.md   # TU setup como referencia
│  └─ recipes/claude-code-integration.md# update_agents, skill (opcional)
├─ examples/
│  ├─ claude_desktop_config.example.json
│  └─ .env.example
├─ .gitignore   (añadir: usage.jsonl, *.jsonl, .venv, dist/, _demo*, .claude/)
├─ CHANGELOG.md , LICENSE , CONTRIBUTING.md , CODE_OF_CONDUCT.md
├─ server.json
└─ README.md
```

### 4.2. README (qué va aquí vs qué va a la wiki)

Principio: **el README es "empezar a usar"**; la documentación larga va a la **wiki**. Las 2 primeras líneas responden *qué es* y *por qué me importa*. Usa tablas (escaneables) en vez de listas largas.

Orden recomendado del README:

1. **Título + una frase** (qué es) + badges (PyPI, CI, licencia).
2. **Por qué** (1‑2 frases): conservar cuota de la suscripción delegando trabajo mecánico a un LLM local.
3. **Demo**: screenshot del dashboard + GIF de una delegación.
4. **Instalación rápida**: `uvx local-delegate` + snippet de config para Claude Desktop/Code.
5. **Requisitos**: un endpoint OpenAI‑compatible (enlazar recipe de llama‑swap).
6. **Tools** (tabla: nombre · qué hace · modelo sugerido).
7. **Configuración** (tabla de env vars).
8. **La métrica de ahorro** (2 líneas + enlace a la wiki).
9. **Enlaces**: wiki, CONTRIBUTING, CHANGELOG, licencia.
10. `mcp-name: io.github.<usuario>/local-delegate` (comentario HTML, para la verificación PyPI).

### 4.3. Wiki (páginas propuestas)

- **Home** — mapa de la wiki.
- **Architecture** — MCP stdio → endpoint OpenAI‑compatible; por qué texto→texto (sin tool‑calling en el modelo local); el guardrail.
- **Configuration reference** — todas las env vars, routing de modelos.
- **Savings & metrics** — semántica del ahorro (`source=path` = contexto que no entró a Claude ≈ tokens ÷4), la web, `/api/events`.
- **Recipes: local backends** — llama‑swap (tu setup Blackwell paso a paso), Ollama, LM Studio, vLLM.
- **Recipes: Claude Code integration** — `update_agents.py`, la skill, subagentes.
- **Publishing / release process** — PyPI + registro + CI.
- **Troubleshooting**.

> Nota: la wiki de GitHub es su propio repo git (`<repo>.wiki.git`); se puede versionar y automatizar. Alternativa: `docs/` + GitHub Pages si prefieres que viva en el mismo repo.

### 4.4. Seguridad — NO exponer secretos (crítico)

- **Nunca** subir los 3 configs de Claude (`settings.json`, `claude_desktop_config.json`, `~/.claude.json`): tienen secretos en claro y **no son de este repo**. Publicar solo **plantillas** `*.example` con placeholders.
- `.gitignore`: añadir `usage.jsonl`/`*.jsonl` (datos de uso), `.venv`, `dist/`, `build/`, `_demo*`, y valorar `.claude/` (el `launch.json` lleva una ruta absoluta a tu venv → mejor plantilla o `uvx`).
- **Ventaja actual:** el repo **no tiene commits**, así que **no hay historial que reescribir**. Empiezas limpio.
- Añadir **`gitleaks`** como pre‑commit y/o step de CI para bloquear secretos antes de que entren.
- Si algún día se filtra un secreto: rotarlo primero, luego limpiar historial (`git filter-repo`).

### 4.5. Licencia y comunidad

Licencia permisiva (MIT o Apache‑2.0; Apache‑2.0 añade cláusula de patentes). `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, plantillas de issue/PR. `CITATION.cff` si quieres que se te cite.

### 4.6. CI/CD (GitHub Actions)

- **`ci.yml`**: en cada push/PR → `uv sync`, `ruff`/`ruff format --check`, `pytest`, y validar el JS del dashboard (`node --check`).
- **`publish.yml`**: en tag `v*` → `uv build` + `uv publish` con **Trusted Publishing (OIDC)** (sin token en secrets) y luego `mcp-publisher publish` con **GitHub OIDC**. Cero secretos guardados.

---

## 5. Riesgos y decisiones abiertas (para ti)

1. **Alcance del paquete:** ¿publicar `local-delegate` como cliente **genérico** de endpoints OpenAI‑compatible (recomendado), o atado a llama‑swap? Lo primero llega a mucha más gente.
2. **Lo personal (agentes/skill/auto‑arranque):** ¿`docs/recipes` en el mismo repo, o repo separado "integration"?
3. **Nombre del paquete PyPI:** `local-delegate-mcp` u otro (verificar disponibilidad en PyPI). El nombre en el registro será `io.github.<usuario>/local-delegate`.
4. **Licencia:** MIT vs Apache‑2.0.
5. **Web en el paquete:** ¿extra `[web]` opcional (recomendado) o dependencia base?
6. **Docker/DXT:** ¿ahora o como fase 2?

---

## 6. Plan de ejecución por fases (checklist)

**Fase 0 — Crear el directorio limpio (no romper lo actual):**
- [ ] Crear `D:\Projects\local-delegate` (vacío) + `git init`. El viejo `llms\local-delegate` queda como **referencia** (solo lectura).
- [ ] Copiar el plan a `docs/` y arrancar el scaffolding.

**Fase 1 — Portar y desacoplar (en `D:\Projects\local-delegate`):**
- [ ] Layout `src/local_delegate/`, con `__init__.py:main()` y `[project.scripts]` (portando la lógica del server viejo).
- [ ] `config.py`: todo por env con defaults multiplataforma (`platformdirs`); **eliminar rutas `D:\`**.
- [ ] Auto‑arranque de llama‑swap → `LOCAL_DELEGATE_AUTOSTART=0` por defecto.
- [ ] Sacar `update_agents.py`/agentes/skill del paquete → `docs/recipes/`.

**Fase 2 — Repo:**
- [ ] `.gitignore` reforzado, `examples/*.example`, LICENSE, CONTRIBUTING, CODE_OF_CONDUCT.
- [ ] README (estructura §4.2) + `mcp-name:` para verificación.
- [ ] `gitleaks` en pre‑commit + CI.
- [ ] Primer commit + push a GitHub (repo nuevo, público).

**Fase 3 — Publicar:**
- [ ] `uv build` + `uv publish` a PyPI (probar `uvx local-delegate` desde cero en otra carpeta).
- [ ] `mcp-publisher init/login/publish` al registro oficial.
- [ ] CI de publish por OIDC en tags.
- [ ] **Switch‑over (solo cuando `uvx local-delegate` funcione desde cero):** repuntar los 3 configs de Claude al nuevo comando (`uvx local-delegate`) y reiniciar Claude. Verificar tools + web. Solo entonces retirar/archivar el montaje viejo `llms\local-delegate`.

**Fase 4 — Wiki y pulido:**
- [ ] Poblar la wiki (§4.3), recipes (llama‑swap Blackwell, Ollama…).
- [ ] Screenshots/GIF del dashboard.
- [ ] (Opcional) DXT / Docker.

---

## 7. Fuentes

- MCP Registry — Quickstart (oficial): https://modelcontextprotocol.io/registry/quickstart
- MCP Registry — repo: https://github.com/modelcontextprotocol/registry
- server.json requirements (Glama): https://glama.ai/blog/2026-01-24-official-mcp-registry-serverjson-requirements
- MCP packaging & distribution (npm/PyPI/Docker/DXT/registro): https://chatforest.com/guides/mcp-server-packaging-distribution/
- Publicar MCP en PyPI con FastMCP: https://circleci.com/blog/building-and-deploying-a-python-mcp-server-with-fastmcp/
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- README best practices: https://github.com/jehna/readme-best-practices · https://github.com/matiassingers/awesome-readme
- GitHub — best practices for repositories: https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories
