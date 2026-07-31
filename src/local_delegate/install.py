"""install.py — instalación de la integración con los clientes (hooks, skill, memoria, MCP).

El paquete ya no se queda en "aquí tienes las tools MCP, el resto cópialo a mano": este
módulo instala en el HOME del usuario los cuatro pedazos que hacen que la delegación se use
de verdad, y los deja desinstalables:

1. **hooks** consultivos de Claude Code (`resources/hooks/`) en `~/.claude/hooks/local-delegate/`
   y registrados en `~/.claude/settings.json`.
2. **skill** `delegacion-local` en `~/.claude/skills/delegacion-local/`.
3. **memoria global**: un bloque delimitado en `~/.claude/CLAUDE.md` y `~/.codex/AGENTS.md`.
4. **servidor MCP** en la configuración del cliente (Claude Code y/o Codex).

Todo es idempotente y reversible:

- Los archivos copiados viven bajo directorios propios (`hooks/local-delegate/`,
  `skills/delegacion-local/`), así que desinstalar no toca nada ajeno.
- Los bloques en archivos compartidos van entre marcadores `local-delegate:begin/end`; al
  reinstalar se reemplaza el bloque, nunca se duplica.
- Antes de sobreescribir un archivo del usuario se deja una copia `.bak`.
- `plan()` describe cada acción sin tocar disco (`--dry-run`); `apply()` la ejecuta.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from importlib.resources import files as _resource_files
from pathlib import Path, PurePath

# Marcadores de los bloques gestionados en archivos que también edita el usuario.
MD_BEGIN = "<!-- local-delegate:begin -->"
MD_END = "<!-- local-delegate:end -->"
TOML_BEGIN = "# local-delegate:begin"
TOML_END = "# local-delegate:end"

SERVER_NAME = "local-delegate"
HOOKS_SUBDIR = "local-delegate"  # ~/.claude/hooks/local-delegate/
SKILL_NAME = "delegacion-local"

# Hooks recomendados tras el piloto A/B (docs/recipes/claude-code-hooks.md). El de Read
# quedó apagado por defecto: en el piloto avisó en 2 de 4 tareas negativas.
_HOOK_EVENTS: tuple[tuple[str, str, str | None], ...] = (
    ("suggest_delegate_prompt.py", "UserPromptSubmit", None),
    ("suggest_lint_summary.py", "PreToolUse", "Bash"),
)
_READ_HOOK = ("suggest_delegate_read.py", "PreToolUse", "Read")


def resources_dir() -> Path:
    """Directorio de recursos empaquetados (hooks, skill, memoria)."""
    return Path(str(_resource_files("local_delegate"))) / "resources"


# --- Dos preguntas sobre el HOME, con una sola respuesta cada una -------------
# Las dos las necesitan `install`, `update` y el CLI. Viven aquí —el módulo más bajo de los
# tres— porque tenerlas duplicadas es exactamente la clase de verdad repartida que ya costó
# caro en este repo (tres copias de la cuenta de tokens, dos derivaciones del host del daemon).
def is_simulated_home(home: Path) -> bool:
    """True si ``home`` apunta fuera del HOME real: entonces no se toca nada global.

    «Global» son dos cosas distintas y las dos importan: los servicios de la máquina (lo que ya
    cuidaba ``update``) y el binario ``claude``, que con ``mcp add-json --scope user`` escribe
    **siempre** en el ``~/.claude.json`` del usuario que ejecuta, ignorando cualquier ``--home``.
    """
    try:
        return home.resolve() != Path.home().resolve()
    except OSError:
        # Una ruta irresoluble se trata como simulada: el lado seguro es no tocar lo global.
        return True


def present_targets(home: Path) -> set[str]:
    """Clientes que existen de verdad bajo ``home``.

    Mismo criterio que el check ``client.presence``, y a propósito una función y no una lectura
    de su ``Result``: el ``detail`` de un check es texto de presentación («detectados: Claude
    Code, Codex»), no un dato. Derivar de ahí a quién se le escribe la configuración ataría el
    instalador a un string de interfaz.
    """
    pairs = (("claude", ".claude"), ("codex", ".codex"))
    return {name for name, sub in pairs if (home / sub).is_dir()}


def default_python() -> str:
    """Intérprete con el que se ejecutarán los hooks.

    NO se usa ``sys.executable``: cuando el instalador corre bajo ``uvx`` ese intérprete
    vive en un entorno efímero que desaparece al terminar el comando, y el hook quedaría
    apuntando a una ruta inexistente. Un nombre resuelto por PATH sobrevive.
    """
    return "python" if sys.platform == "win32" else "python3"


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path


@dataclass
class Action:
    """Un cambio concreto sobre el sistema de archivos o la config de un cliente."""

    kind: str  # copy | settings | markdown | toml | mcp | remove
    target: Path | str
    detail: str
    run: object = field(repr=False, default=None)  # callable() -> str | None

    def describe(self) -> str:
        return f"[{self.kind}] {self.target} — {self.detail}"


# --- Utilidades de escritura -------------------------------------------------
def _backup(path: Path) -> None:
    if path.is_file():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))


def _detect_newline(path: Path) -> str:
    """Terminador de línea dominante del archivo; LF para uno que aún no existe.

    Hace falta porque `write_text` escribe con el terminador de la *plataforma*: en Windows
    convertiría a CRLF un `CLAUDE.md` guardado en LF, y el usuario vería su archivo entero
    como modificado —conflictos en git, diff ilegible— por haberle añadido un bloque. Se
    escribe con el que ya tenía: tocar un archivo ajeno debe notarse solo en lo que cambia.
    """
    try:
        return "\r\n" if b"\r\n" in path.read_bytes() else "\n"
    except OSError:
        return "\n"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = _detect_newline(path)
    _backup(path)
    normalized = text.replace("\r\n", "\n").replace("\n", newline)
    path.write_bytes(normalized.encode("utf-8"))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = _detect_newline(path)
    _backup(path)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def upsert_block(text: str, block: str, begin: str, end: str) -> str:
    """Inserta o reemplaza el bloque delimitado, conservando el resto del archivo."""
    managed = f"{begin}\n{block.strip()}\n{end}"
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(managed, text, count=1)
    prefix = text.rstrip()
    return (prefix + "\n\n" if prefix else "") + managed + "\n"


def remove_block(text: str, begin: str, end: str) -> str:
    """Quita el bloque gestionado (y los blancos que deja) sin tocar lo demás."""
    pattern = re.compile(r"\n*" + re.escape(begin) + r".*?" + re.escape(end) + r"\n*", re.DOTALL)
    cleaned = pattern.sub("\n\n", text)
    return cleaned.strip() + "\n" if cleaned.strip() else ""


# --- Hooks de Claude Code ----------------------------------------------------
def hook_command(hooks_dir: PurePath, script: str, python_exe: str) -> str:
    """Comando del hook: un único string que Claude Code entrega a un shell.

    La ruta va **siempre entre comillas y con barras `/`**, no solo cuando tiene espacios. En
    Windows, pasar `C:\\Users\\...` desnudo llega al shell como `C:UsersYohan.claudehooks...`
    —el shell interpreta cada `\\` como escape y lo borra— y el hook muere con «can't open
    file». Cuando eso le pasa a `UserPromptSubmit`, **bloquea cada prompt del usuario**: no es
    un hook que no sugiere, es un cliente inutilizable. Python abre rutas con `/` en Windows sin
    problema, así que la forma citada y con barras funciona en los tres shells (sh, cmd,
    PowerShell) y en los tres sistemas.
    """
    return f'{python_exe} "{(hooks_dir / script).as_posix()}"'


# Nombres de nuestros scripts: sirven para reconocer instalaciones ANTERIORES hechas a mano
# siguiendo la recipe vieja, que quedaban en `~/.claude/hooks/` (sin subdirectorio) y con el
# formato `{"command": "python", "args": [...]}`.
#
# Aquí decía que ese formato «Claude Code no lo ejecuta, así que esas entradas están muertas»:
# es **falso**, y conviene no volver a escribirlo. `args` es el *exec form* del schema y se
# ejecuta sin shell; se verificó en vivo viendo disparar `suggest_lint_summary.py`. Se limpian
# al instalar porque cambió la ruta y el formato que ponemos, no porque no funcionen: dejarlas
# produciría hooks duplicados que sugieren dos veces lo mismo.
_SCRIPT_NAMES = (
    "suggest_delegate_prompt.py",
    "suggest_delegate_read.py",
    "suggest_lint_summary.py",
)


def _is_ours(hook: dict, hooks_dir: Path) -> bool:
    """True si esta entrada de hook la puso local-delegate (ahora o en una versión previa).

    Reconoce el comando actual (ruta a nuestro directorio) y también el formato heredado con
    `args`. No basta con que el comando mencione «local-delegate»: un hook propio del usuario
    en otra ruta nunca debe ser desregistrado ni borrado por nosotros — de ahí que se exija la
    ruta de nuestro directorio o el nombre exacto de uno de nuestros scripts.
    """
    parts = [str(hook.get("command", ""))]
    args = hook.get("args")
    if isinstance(args, list):
        parts.extend(str(a) for a in args)
    normalized = " ".join(parts).replace("\\", "/")
    if f"hooks/{HOOKS_SUBDIR}" in normalized or str(hooks_dir).replace("\\", "/") in normalized:
        return True
    return any(name in normalized for name in _SCRIPT_NAMES)


def merge_hook_settings(
    settings: dict, entries: list[tuple[str, str | None, str]], hooks_dir: Path
) -> tuple[dict, int]:
    """Registra nuestros hooks en settings.json quitando primero cualquier versión previa.

    `entries` = [(evento, matcher|None, comando)]. Idempotente: reinstalar deja exactamente
    un registro por hook, y los hooks de terceros no se tocan. Devuelve (settings, entradas
    previas retiradas) para poder avisar de una migración desde el formato heredado.
    """
    settings, removed = strip_hook_settings(settings, hooks_dir)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    for event, matcher, command in entries:
        group = {"hooks": [{"type": "command", "command": command}]}
        if matcher:
            group["matcher"] = matcher
        hooks.setdefault(event, []).append(group)
    return settings, removed


def strip_hook_settings(settings: dict, hooks_dir: Path) -> tuple[dict, int]:
    """Quita del settings.json solo los hooks de local-delegate (incluidos los heredados).

    Devuelve (settings, cuántas entradas se quitaron).
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings, 0
    removed = 0
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        pruned = []
        for group in groups:
            if not isinstance(group, dict):
                pruned.append(group)
                continue
            inner = []
            for h in group.get("hooks", []):
                if isinstance(h, dict) and _is_ours(h, hooks_dir):
                    removed += 1
                    continue
                inner.append(h)
            if inner:
                group["hooks"] = inner
                pruned.append(group)
        if pruned:
            hooks[event] = pruned
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    return settings, removed


# --- Entrada del servidor MCP ------------------------------------------------
def mcp_entry(mode: str, base_url: str | None, api_key_env: bool, version: str | None) -> dict:
    """Entrada de servidor MCP para Claude Code (stdio vía uvx, o HTTP contra el daemon)."""
    if mode == "http":
        port = os.environ.get("LOCAL_DELEGATE_WEB_PORT", "9393")
        host = os.environ.get("LOCAL_DELEGATE_WEB_HOST", "127.0.0.1")
        return {"type": "http", "url": f"http://{host}:{port}/mcp"}
    package = f"local-delegate-mcp=={version}" if version else "local-delegate-mcp"
    entry: dict = {
        "type": "stdio",
        "command": "uvx",
        "args": ["--from", package, "local-delegate-mcp"],
    }
    env: dict[str, str] = {}
    if base_url:
        env["LOCAL_DELEGATE_BASE_URL"] = base_url
        env["LOCAL_DELEGATE_AUTOSTART"] = "0"
    if api_key_env:
        # Nunca se escribe el secreto: se referencia la variable del entorno del cliente.
        env["LOCAL_DELEGATE_API_KEY"] = "${LOCAL_DELEGATE_API_KEY}"
    if env:
        entry["env"] = env
    return entry


def codex_mcp_block(entry: dict) -> str:
    """Bloque TOML equivalente para `~/.codex/config.toml` (sin dependencia de un writer)."""
    lines = [f"[mcp_servers.{SERVER_NAME}]"]
    if entry.get("type") == "http":
        lines.append(f"url = {json.dumps(entry['url'])}")
        return "\n".join(lines)
    lines.append(f"command = {json.dumps(entry['command'])}")
    lines.append("args = [" + ", ".join(json.dumps(a) for a in entry.get("args", [])) + "]")
    # `${VAR}` no se expande en TOML: la key se reenvía por `env_vars`, nunca se escribe.
    env = {k: v for k, v in (entry.get("env") or {}).items() if not v.startswith("${")}
    if (entry.get("env") or {}).get("LOCAL_DELEGATE_API_KEY"):
        lines.append('env_vars = ["LOCAL_DELEGATE_API_KEY"]')
    if env:
        # Tabla INLINE a propósito: así el bloque gestionado es UNA sola tabla TOML y lo que
        # el usuario escriba después del marcador de cierre no queda absorbido por `.env`.
        inline = ", ".join(f"{k} = {json.dumps(v)}" for k, v in env.items())
        lines.append("env = { " + inline + " }")
    return "\n".join(lines)


_CODEX_SECTION_RE = re.compile(
    r"(?ms)^\[mcp_servers\." + re.escape(SERVER_NAME) + r"(?:\.[^\]]+)?\]\n.*?(?=^\[|\Z)"
)


def upsert_codex_mcp(text: str, block: str) -> str:
    """Reemplaza cualquier entrada previa de local-delegate (gestionada o a mano)."""
    text = remove_block(text, TOML_BEGIN, TOML_END)
    text = _CODEX_SECTION_RE.sub("", text).rstrip()
    managed = f"{TOML_BEGIN}\n{block}\n{TOML_END}"
    return (text + "\n\n" if text else "") + managed + "\n"


def remove_codex_mcp(text: str) -> str:
    text = remove_block(text, TOML_BEGIN, TOML_END)
    return _CODEX_SECTION_RE.sub("", text).strip() + "\n"


# --- Plan de instalación -----------------------------------------------------
@dataclass
class Options:
    home: Path
    components: set[str]  # hooks | skill | memory | mcp
    targets: set[str]  # claude | codex
    python_exe: str
    enable_read_hook: bool = False
    mcp_mode: str = "stdio"
    base_url: str | None = None
    api_key_env: bool = False
    pin_version: str | None = None
    use_cli: bool = True
    # Suprime SOLO la escritura de la entrada MCP de Codex. Lo decide quien llama (el CLI, tras
    # ver el check `scaffold.mcp_codex` en `warn` y preguntar), y se pasa como dato en vez de
    # filtrar la lista de acciones por su `kind`: un filtro por string desde fuera sería frágil
    # y, sobre todo, mudo — nadie sabría por qué falta esa acción.
    skip_codex_mcp: bool = False


def _claude_dir(opts: Options) -> Path:
    return opts.home / ".claude"


def _codex_dir(opts: Options) -> Path:
    return opts.home / ".codex"


def packaged_hook_names() -> set[str]:
    """Nombres de los scripts de hooks que **este paquete instala**.

    Es la definición de «qué es nuestro» dentro de `~/.claude/hooks/`, y por tanto de qué se puede
    retirar. Sale del directorio empaquetado y no de una constante escrita a mano, porque una
    constante paralela se desincroniza: `_SCRIPT_NAMES` tiene tres nombres y **no** incluye
    `hook_common.py`, que es uno de los huérfanos reales que hay que limpiar.

    Si el directorio no se puede listar devuelve vacío, y con vacío no se borra nada: la
    degradación segura de una operación destructiva es no hacer nada.
    """
    try:
        return {p.name for p in (resources_dir() / "hooks").iterdir() if p.suffix == ".py"}
    except OSError:
        return set()


def orphan_hook_scripts(claude_dir: Path) -> list[Path]:
    """Scripts nuestros sueltos en la **raíz** de ``~/.claude/hooks/``.

    Las instalaciones anteriores los dejaban ahí; la actual los pone en
    ``hooks/local-delegate/`` y nunca limpiaba los viejos, así que se quedaban para siempre.

    Mira la raíz y **nunca** el subdirectorio: los de dentro de ``local-delegate/`` son la
    instalación buena. Confundir las dos rutas haría que se borrara justo lo que acaba de
    instalarse.
    """
    root = claude_dir / "hooks"
    names = packaged_hook_names()
    if not names:
        return []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []
    # `is_file()` y no `exists()`: un directorio que se llame como uno de nuestros scripts no es
    # nuestro script, y aquí lo que está en juego es un borrado.
    return [p for p in entries if p.name in names and p.is_file()]


def _prune_orphans_action(claude_dir: Path) -> Action:
    root = claude_dir / "hooks"

    def _run() -> str:
        removed, failed = [], []
        for path in orphan_hook_scripts(claude_dir):
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:
                # Un fichero que no se deja borrar no tumba el resto del install: se dice y se
                # sigue. El usuario se entera y puede quitarlo a mano.
                failed.append(f"{path.name} ({exc.strerror or exc})")
        detail = (
            f"retirados {len(removed)}: {', '.join(removed)}" if removed else "nada que retirar"
        )
        return detail + (f" · NO se pudieron retirar: {'; '.join(failed)}" if failed else "")

    return Action("prune", root, "retira scripts de hooks de una instalación anterior", _run)


def _agents_action(agents_dir: Path, cambios: list) -> Action:
    """Escribe los subagentes que cambian. `cambios` viene de `agents.pending()`, que solo lee."""
    resumen = ", ".join(
        f"{path.name} (+{len(added)} tools{', catálogo ' + action if action else ''})"
        for path, _text, added, action in cambios
    )

    def _run() -> str:
        escritos, fallidos = [], []
        for path, text, _added, _action in cambios:
            try:
                # `_write_text` deja `.bak` y conserva el terminador de línea del fichero: en
                # Windows, escribir con el de la plataforma marcaría el agente entero como
                # modificado por haberle añadido una línea.
                _write_text(path, text)
                escritos.append(path.name)
            except OSError as exc:
                fallidos.append(f"{path.name} ({exc.strerror or exc})")
        detalle = f"actualizados {len(escritos)}: {', '.join(escritos)}"
        return detalle + (f" · NO se pudieron escribir: {'; '.join(fallidos)}" if fallidos else "")

    return Action("agents", agents_dir, f"actualiza {len(cambios)} subagente(s): {resumen}", _run)


def _copy_tree_action(src: Path, dst: Path, detail: str) -> Action:
    def _run() -> str:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return f"copiado -> {dst}"

    return Action("copy", dst, detail, _run)


def plan_install(opts: Options) -> list[Action]:
    """Lista ordenada de acciones. No toca disco: ejecutarlas es responsabilidad de apply()."""
    actions: list[Action] = []
    res = resources_dir()
    claude = _claude_dir(opts)
    codex = _codex_dir(opts)

    if "hooks" in opts.components and "claude" in opts.targets:
        hooks_dst = claude / "hooks" / HOOKS_SUBDIR
        actions.append(_copy_tree_action(res / "hooks", hooks_dst, "scripts de hooks consultivos"))
        # Solo si hay algo que retirar: sin esto, reinstalar sobre una máquina limpia emitiría
        # una acción que no hace nada y el plan mentiría sobre lo que va a pasar.
        if orphan_hook_scripts(claude):
            actions.append(_prune_orphans_action(claude))
        entries = [
            (event, matcher, hook_command(hooks_dst, script, opts.python_exe))
            for script, event, matcher in _HOOK_EVENTS
        ]
        if opts.enable_read_hook:
            script, event, matcher = _READ_HOOK
            entries.append((event, matcher, hook_command(hooks_dst, script, opts.python_exe)))
        settings_path = claude / "settings.json"

        def _run_settings(path=settings_path, entries=entries, hooks_dir=hooks_dst) -> str:
            data, removed = merge_hook_settings(_read_json(path), entries, hooks_dir)
            _write_json(path, data)
            note = f" (retiradas {removed} entrada(s) previa(s))" if removed else ""
            return f"{len(entries)} hook(s) registrados{note}"

        actions.append(
            Action(
                "settings",
                settings_path,
                f"registra {len(entries)} hook(s): "
                + ", ".join(f"{e}{'/' + m if m else ''}" for e, m, _c in entries),
                _run_settings,
            )
        )

    if "skill" in opts.components and "claude" in opts.targets:
        actions.append(
            _copy_tree_action(
                res / "skills" / SKILL_NAME,
                claude / "skills" / SKILL_NAME,
                f"skill {SKILL_NAME}",
            )
        )

    # `agents` es el único componente que NO está en el default, y la asimetría es deliberada:
    # los subagentes los escribió el usuario, no son andamiaje nuestro. Se planifica solo si hay
    # algo que cambiar, para que el plan no anuncie trabajo inexistente.
    if "agents" in opts.components and "claude" in opts.targets:
        # Import diferido y una ruta que se pasa, no que se descubre: `agents` no importa este
        # módulo (cerraría un ciclo que CodeQL marcó), así que la fuente del catálogo se le da.
        from . import agents as agents_mod

        skill_md = res / "skills" / SKILL_NAME / "SKILL.md"
        cambios = agents_mod.pending(claude / "agents", skill_md)
        if cambios:
            actions.append(_agents_action(claude / "agents", cambios))

    if "memory" in opts.components:
        block = (res / "memory" / "local-delegate.md").read_text(encoding="utf-8")
        memory_files = []
        if "claude" in opts.targets:
            memory_files.append(claude / "CLAUDE.md")
        if "codex" in opts.targets:
            memory_files.append(codex / "AGENTS.md")
        for path in memory_files:

            def _run_md(path=path, block=block) -> str:
                _write_text(path, upsert_block(_read_text(path), block, MD_BEGIN, MD_END))
                return "bloque gestionado actualizado"

            actions.append(Action("markdown", path, "bloque de regla de delegación", _run_md))

    if "mcp" in opts.components:
        entry = mcp_entry(opts.mcp_mode, opts.base_url, opts.api_key_env, opts.pin_version)
        if "claude" in opts.targets:
            actions.append(
                Action(
                    "mcp",
                    "claude",
                    f"registra el servidor MCP '{SERVER_NAME}' ({opts.mcp_mode})",
                    lambda entry=entry: _register_claude_mcp(opts, entry),
                )
            )
        if "codex" in opts.targets and not opts.skip_codex_mcp:
            config_path = codex / "config.toml"

            def _run_codex(path=config_path, entry=entry) -> str:
                _write_text(path, upsert_codex_mcp(_read_text(path), codex_mcp_block(entry)))
                return "entrada [mcp_servers.local-delegate] actualizada"

            actions.append(
                Action(
                    "toml",
                    config_path,
                    f"registra el servidor MCP '{SERVER_NAME}' ({opts.mcp_mode})",
                    _run_codex,
                )
            )
    return actions


def _register_claude_mcp(opts: Options, entry: dict) -> str:
    """Registra el MCP en Claude Code: primero por CLI, si no editando ~/.claude.json.

    Se prefiere la CLI porque `~/.claude.json` es un archivo grande y vivo (estado de
    sesiones): que lo escriba el propio cliente evita pisar cambios concurrentes.
    """
    if opts.use_cli and shutil.which("claude"):
        try:
            subprocess.run(
                ["claude", "mcp", "remove", "--scope", "user", SERVER_NAME],
                capture_output=True,
                text=True,
                timeout=30,
            )
            done = subprocess.run(
                [
                    "claude",
                    "mcp",
                    "add-json",
                    "--scope",
                    "user",
                    SERVER_NAME,
                    json.dumps(entry),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if done.returncode == 0:
                return "registrado con `claude mcp add-json --scope user`"
        except (OSError, subprocess.SubprocessError):
            pass  # cae al modo archivo
    path = opts.home / ".claude.json"
    data = _read_json(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    servers[SERVER_NAME] = entry
    _write_json(path, data)
    return f"escrito en {path}"


def plan_uninstall(opts: Options) -> list[Action]:
    """Deshace exactamente lo que instaló plan_install(); nunca borra nada ajeno."""
    actions: list[Action] = []
    claude = _claude_dir(opts)
    codex = _codex_dir(opts)
    hooks_dst = claude / "hooks" / HOOKS_SUBDIR

    if "hooks" in opts.components and "claude" in opts.targets:
        settings_path = claude / "settings.json"

        def _run_settings(path=settings_path, hooks_dir=hooks_dst) -> str:
            if not path.is_file():
                return "settings.json no existe"
            data, removed = strip_hook_settings(_read_json(path), hooks_dir)
            _write_json(path, data)
            return f"{removed} hook(s) de local-delegate quitados"

        actions.append(
            Action("settings", settings_path, "quita los hooks registrados", _run_settings)
        )

        def _run_rm(path=hooks_dst) -> str:
            if path.is_dir():
                shutil.rmtree(path)
                return "eliminado"
            return "no existía"

        actions.append(Action("remove", hooks_dst, "borra los scripts de hooks", _run_rm))

    if "skill" in opts.components and "claude" in opts.targets:
        skill_dst = claude / "skills" / SKILL_NAME

        def _run_skill(path=skill_dst) -> str:
            if path.is_dir():
                shutil.rmtree(path)
                return "eliminada"
            return "no existía"

        actions.append(Action("remove", skill_dst, f"borra la skill {SKILL_NAME}", _run_skill))

    if "memory" in opts.components:
        paths = []
        if "claude" in opts.targets:
            paths.append(claude / "CLAUDE.md")
        if "codex" in opts.targets:
            paths.append(codex / "AGENTS.md")
        for path in paths:

            def _run_md(path=path) -> str:
                if not path.is_file():
                    return "no existía"
                _write_text(path, remove_block(_read_text(path), MD_BEGIN, MD_END))
                return "bloque gestionado quitado"

            actions.append(Action("markdown", path, "quita el bloque de delegación", _run_md))

    if "mcp" in opts.components:
        if "claude" in opts.targets:
            actions.append(
                Action(
                    "mcp",
                    "claude",
                    f"quita el servidor MCP '{SERVER_NAME}'",
                    lambda: _unregister_claude_mcp(opts),
                )
            )
        if "codex" in opts.targets:
            config_path = codex / "config.toml"

            # `skip_codex_mcp` NO se consulta aquí, y la asimetría con `plan_install` es
            # deliberada: al instalar, reemplazar una entrada puesta a mano cambia la
            # configuración del usuario por la nuestra —de ahí la pregunta—, mientras que al
            # desinstalar la sección `[mcp_servers.local-delegate]` es nuestra por definición y
            # retirarla es justo lo que se pidió. Preguntar aquí sería estorbar.
            def _run_codex(path=config_path) -> str:
                if not path.is_file():
                    return "no existía"
                _write_text(path, remove_codex_mcp(_read_text(path)))
                return "entrada quitada"

            actions.append(Action("toml", config_path, f"quita '{SERVER_NAME}'", _run_codex))
    return actions


def _unregister_claude_mcp(opts: Options) -> str:
    if opts.use_cli and shutil.which("claude"):
        try:
            done = subprocess.run(
                ["claude", "mcp", "remove", "--scope", "user", SERVER_NAME],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if done.returncode == 0:
                return "quitado con `claude mcp remove`"
        except (OSError, subprocess.SubprocessError):
            pass
    path = opts.home / ".claude.json"
    data = _read_json(path)
    servers = data.get("mcpServers")
    if isinstance(servers, dict) and servers.pop(SERVER_NAME, None) is not None:
        _write_json(path, data)
        return f"quitado de {path}"
    return "no estaba registrado"


def apply(actions: list[Action], *, dry_run: bool, out=print) -> int:
    """Ejecuta (o solo describe) las acciones. Devuelve el número de fallos."""
    failures = 0
    for action in actions:
        if dry_run:
            out(f"[dry-run] {action.describe()}")
            continue
        out(action.describe())
        try:
            result = action.run() if callable(action.run) else None
        except Exception as exc:  # una acción fallida no debe abortar el resto
            failures += 1
            out(f"    ERROR: {exc}")
            continue
        if result:
            out(f"    {result}")
    return failures
