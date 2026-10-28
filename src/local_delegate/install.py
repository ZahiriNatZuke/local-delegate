"""install.py — instalación de la integración con los clientes (hooks, skill, memoria, MCP).

El paquete ya no se queda en "aquí tienes las tools MCP, el resto cópialo a mano": este
módulo instala en el HOME del usuario los cuatro pedazos que hacen que la delegación se use
de verdad, y los deja desinstalables:

1. **hooks** consultivos de Claude Code (`resources/hooks/`) en `~/.claude/hooks/local-delegate/`
   y registrados en `~/.claude/settings.json`.
2. **skill** `local-delegation` en `~/.claude/skills/local-delegation/` y en
   `~/.config/opencode/skill/local-delegation/`.
3. **memoria global**: un bloque delimitado en `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` y
   `~/.config/opencode/AGENTS.md`.
4. **servidor MCP** en la configuración del cliente (Claude Code, Codex y/o opencode).

Todo es idempotente y reversible:

- Los archivos copiados viven bajo directorios propios (`hooks/local-delegate/`,
  `skills/local-delegation/`), así que desinstalar no toca nada ajeno.
- Los bloques en archivos compartidos van entre marcadores `local-delegate:begin/end`; al
  reinstalar se reemplaza el bloque, nunca se duplica.
- Antes de sobreescribir un archivo del usuario se deja una copia `.bak`.
- `plan()` describe cada acción sin tocar disco (`--dry-run`); `apply()` la ejecuta.
"""

from __future__ import annotations

import codecs
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from importlib import import_module
from importlib.resources import files as _resource_files
from pathlib import Path, PurePath

from . import completion, config, deprecations, i18n, shell_profiles
from .i18n import t
from .resources.hooks import hook_common
from .simulated_home import is_simulated_home

# Marcadores de los bloques gestionados en archivos que también edita el usuario.
MD_BEGIN = "<!-- local-delegate:begin -->"
MD_END = "<!-- local-delegate:end -->"
TOML_BEGIN = "# local-delegate:begin"
TOML_END = "# local-delegate:end"

SERVER_NAME = "local-delegate"
HOOKS_SUBDIR = "local-delegate"  # ~/.claude/hooks/local-delegate/
SKILL_NAME = "local-delegation"

# --- opencode ----------------------------------------------------------------
# Los dos nombres de fichero que opencode lee, EN ESTE ORDEN. No es una preferencia nuestra: es
# el orden con el que el propio cliente elige a cuál escribir (medido contra opencode 1.18.11,
# traza en .sdd/changes/opencode-tercer-cliente/research.md R3-R4). Los lee **los dos** y los
# fusiona, así que quien compruebe si la entrada está tiene que mirar en ambos.
OPENCODE_CONFIG_NAMES = ("opencode.json", "opencode.jsonc")
OPENCODE_SKILL_SUBDIR = "skill"  # ~/.config/opencode/skill/<nombre>/
OPENCODE_SCHEMA = "https://opencode.ai/config.json"

# Hooks recomendados tras el piloto A/B (docs/recipes/claude-code-hooks.md). El de Read
# quedó apagado por defecto: en el piloto avisó en 2 de 4 tareas negativas.
#
# `record_call.py` (coste-api-y-cuota, REQ-002; antes `anotar_llamada.py`) va siempre, no detrás
# de `--enable-read-hook`: no avisa ni bloquea, solo anota quién pide cada delegación. Va AL
# FINAL para que `_HOOK_EVENTS[0]` siga siendo el de `UserPromptSubmit`, que es el que miran los
# tests.
_HOOK_EVENTS: tuple[tuple[str, str, str | None], ...] = (
    ("suggest_delegate_prompt.py", "UserPromptSubmit", None),
    ("record_call.py", "PreToolUse", "mcp__local-delegate__.*"),
    # Issue #443: las tools `local_*` son diferidas y un subagente no las carga sin motivo; este
    # hook le recuerda, al arrancar, que las cargue y que localice antes de leer. Solo aconseja.
    ("subagent_start.py", "SubagentStart", None),
)
_READ_HOOK = ("suggest_delegate_read.py", "PreToolUse", "Read")

#: El mismo control, sobre la otra mitad de la superficie de lectura. Va con la misma bandera que
#: `_READ_HOOK` a proposito: son una regla sola declarada sobre dos caminos, y encender uno sin el
#: otro no cambia la conducta, la muda de sitio —`cat informe.md` hace lo que la tool `Read`—.
_SHELL_HOOK = ("suggest_delegate_shell.py", "PreToolUse", "Bash|PowerShell")

#: La tercera fila de la superficie de lectura (REQ-F1-9, P-6): las tools de lectura de OTROS MCP
#: se miden y nunca se cierran. Es el mismo script que `Read`, que por este camino solo registra;
#: sin contarlas, una subida de la adopcion no distingue «se delego» de «se leyo por otro sitio».
_MCP_READ_HOOK = (
    "suggest_delegate_read.py",
    "PreToolUse",
    "mcp__.+__(read_[a-z_]*|get_file_contents)",
)

#: Scripts que este paquete YA NO instala, pero que sigue reconociendo como suyos.
#:
#: Sin esta lista, un script retirado se vuelve **inmortal**: la limpieza de huérfanos sale de
#: `packaged_hook_names()`, que lista el directorio empaquetado, así que en cuanto el fichero
#: desaparece de ahí su copia vieja en `~/.claude/hooks/` deja de ser reconocible y nadie la
#: borra nunca. Lo mismo con `_is_ours`, que es quien desregistra la entrada de `settings.json`.
#:
#: `suggest_lint_summary.py` se retiró el 2026-09-08 por punteria: **366 disparos y 1 acierto**
#: (0,3 %) medidos sobre 21 días de uso real, con la mediana de salida en 402 bytes. Disparaba
#: con una regex sobre el COMANDO, antes de ejecutarlo, y las palabras que lo activaban eran
#: `test` y `build` dentro de rutas. Un aviso que casi nunca tiene razón enseña a ignorar todos
#: los avisos, incluidos los que la tienen.
#: `output_policy.py` y `output_stats.py` se retiraron el 2026-09-08 por quedarse sin consumidor.
#: Eran la mitad «decide si esta salida merece delegarse» del mecanismo que reescribía el comando
#: para mandar la salida a un fichero, y ese mecanismo se descartó: el cliente ya persiste la
#: salida grande por su cuenta, y `updatedInput` se salta el allowlist de permisos. La medición de
#: `PostToolUseFailure` cerró la última puerta que les quedaba —el evento existe y se dispara, pero
#: llega cuando el coste ya se pagó y sin la salida completa, así que no habilita ningún ahorro—.
#: Nunca llegaron a registrarse como hook, pero sí se copiaron a `~/.claude/hooks/`, así que sin
#: esta lista sus 24 KB se quedarían ahí para siempre.
#: `anotar_llamada.py` se renombró a `record_call.py` (REQ-012): sin esta entrada la copia vieja y
#: su registro en `settings.json` seguirían anotando cada llamada, dos veces.
_RETIRED_SCRIPTS = (
    "suggest_lint_summary.py",
    "output_policy.py",
    "output_stats.py",
    "anotar_llamada.py",
)

#: Skills que el paquete instaló alguna vez y ya no instala (REQ-013). Mismo papel que
#: `_RETIRED_SCRIPTS` para los hooks: sin esta lista, renombrar la skill dejaría la copia vieja
#: en cada destino para siempre. Se borran **solo por nombre exacto**: una skill del usuario con
#: otro nombre no se toca jamás. `delegacion-local` es el nombre de la skill hasta la 0.34.0: la
#: entrada es permanente, porque quien salte de una 0.34 a cualquier versión posterior sigue
#: teniendo la copia vieja.
_RETIRED_SKILLS: tuple[str, ...] = ("delegacion-local",)

# El argumento con el que se registra el hook de Read, y **por qué existe uno**.
#
# `--enable-read-hook` registraba el script y ya: el hook seguía exigiendo además
# `LD_HOOK_READ_ENABLED=1` en el entorno, que nadie ponía. Eran dos puertas y la bandera abría
# una, así que la opción no hacía nada — y en silencio, que es lo peor: quedaba registrada en
# `settings.json`, se veía en el plan del instalador y no sugería jamás. Medido con control
# positivo: mismo hook, mismo archivo grande, emite con la variable y no emite sin ella.
#
# Se arregla por el argumento y no escribiendo la variable en el `settings.json` del usuario por
# dos razones: la variable sería global a la sesión (afectaría a cualquier proceso hijo, no solo
# al hook) y `uninstall` no la retiraría. Con el argumento, **el registro mismo es el
# interruptor**: instalar lo enciende y desinstalar lo apaga, sin estado repartido.
READ_HOOK_FLAG = "--enabled"


def _sibling(name: str):
    """A module that imports this one (`claude_plugin`, `install_state`, `plugin_migration`).

    Resolved by name at call time, so the modules do not import each other (CodeQL
    `py/cyclic-import`), the same way `completion.render` reaches `cli`.
    """
    return import_module(f"{__package__}.{name}")


def resources_dir() -> Path:
    """Directorio de recursos empaquetados (hooks, skill, memoria)."""
    return Path(str(_resource_files("local_delegate"))) / "resources"


# --- Dos preguntas sobre el HOME, con una sola respuesta cada una -------------
# Las dos las necesitan `install`, `update` y el CLI. Viven aquí —el módulo más bajo de los
# tres— porque tenerlas duplicadas es exactamente la clase de verdad repartida que ya costó
# caro en este repo (tres copias de la cuenta de tokens, dos derivaciones del host del daemon).
# `is_simulated_home` lives in `simulated_home` (`shell_profiles`, which this module imports, uses
# it too) and is re-exported above under the same name.


def opencode_dir(home: Path) -> Path:
    """Directorio de configuración global de opencode bajo ``home``.

    Existe como **función** —y no como una expresión ``home / ".config" / "opencode"`` repetida en
    ``install``, ``checks`` y ``update``— por un motivo medido, no por estilo: opencode resuelve su
    config con ``XDG_CONFIG_HOME`` **por encima** de ``HOME`` (`opencode debug paths`, versión
    1.18.11). En una máquina que exporte esa variable, la ruta derivada del HOME sería falsa:
    ``install`` escribiría un fichero que el cliente nunca lee y ``doctor`` diría que falta la
    entrada que se acaba de escribir. Dos derivaciones de esto es exactamente la clase de verdad
    repartida que ya costó caro tres veces en este repo.

    Con un HOME simulado la variable se ignora **a propósito**: si no se ignorara, ``--home``
    dejaría de ser un sandbox en cuanto quien ejecuta tuviera ``XDG_CONFIG_HOME`` en su entorno.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg and not is_simulated_home(home):
        return Path(xdg).expanduser() / "opencode"
    return home / ".config" / "opencode"


def present_targets(home: Path) -> set[str]:
    """Clientes que existen de verdad bajo ``home``.

    Mismo criterio que el check ``client.presence``, y a propósito una función y no una lectura
    de su ``Result``: el ``detail`` de un check es texto de presentación («detectados: Claude
    Code, Codex»), no un dato. Derivar de ahí a quién se le escribe la configuración ataría el
    instalador a un string de interfaz.
    """
    candidates = {
        "claude": home / ".claude",
        "codex": home / ".codex",
        # opencode NO cuelga del HOME como los otros dos: ver `opencode_dir`.
        "opencode": opencode_dir(home),
    }
    return {name for name, path in candidates.items() if path.is_dir()}


def default_python() -> str:
    """Intérprete con el que se ejecutarán los hooks.

    NO se usa ``sys.executable``: cuando el instalador corre bajo ``uvx`` ese intérprete
    vive en un entorno efímero que desaparece al terminar el comando, y el hook quedaría
    apuntando a una ruta inexistente. Un nombre resuelto por PATH sobrevive.
    """
    return "python" if sys.platform == "win32" else "python3"


def _shell_exe(python_exe: str) -> str:
    """The interpreter as the first word of a hook command, safe for the shell that runs it.

    A bare name (``python``, ``python3``) or a plain POSIX path goes untouched, so the command
    of a default install stays byte for byte what it was. A path with spaces or ``\\``
    (``--python "C:\\Program Files\\Python312\\python.exe"``) goes with ``/`` and between
    double quotes, like the script path: unquoted, the shell cuts it at the space and Git Bash
    also eats every ``\\``, so the hook dies and, on ``UserPromptSubmit``, blocks every prompt.
    Quotes the user may have typed around it are dropped first, so they never end up doubled.
    """
    exe = python_exe.strip()
    if len(exe) >= 2 and exe[0] == exe[-1] and exe[0] in "\"'":
        exe = exe[1:-1]
    if not exe or not any(c.isspace() or c in "\\\"'" for c in exe):
        return exe
    exe = exe.replace("\\", "/").replace('"', "")
    return f'"{exe}"'


@dataclass
class Action:
    """Un cambio concreto sobre el sistema de archivos o la config de un cliente."""

    kind: str  # copy | settings | markdown | toml | mcp | remove | migrate
    target: Path | str
    detail: str
    run: object = field(repr=False, default=None)  # callable() -> str | None
    # Lo que se va a escribir, **textual**. Solo lo imprime `--dry-run`, y existe por un caso
    # concreto: el incidente de los hooks en Windows del 2026-07-30. El plan decía «registra 2
    # hook(s)» y el defecto vivía en el *string generado* —un comando de shell sin comillas—, así
    # que revisar el plan antes de aplicarlo no habría avisado de nada. Un resumen dice cuántas
    # cosas se escriben; esto dice **qué** se escribe, que es lo único revisable.
    literal: str = ""

    def describe(self) -> str:
        return f"[{self.kind}] {self.target} — {self.detail}"


# --- Utilidades de escritura -------------------------------------------------
def _backup(path: Path) -> None:
    """Copies ``path`` to ``<path>.bak`` **only if that copy does not exist yet**.

    Overwriting it on every write made it useless exactly when it was needed: after a write that
    damaged the file, the next one replaced the good copy with the damaged version. Kept once, the
    copy holds the state before local-delegate first touched the file (like the profiles' copy,
    REQ-046), and a `.bak` the user had is never overwritten either.
    """
    copy = path.with_suffix(path.suffix + ".bak")
    if path.is_file() and not copy.exists():
        shutil.copy2(path, copy)


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
    """Writes ``text`` in UTF-8 with the line ending and the UTF-8 BOM the file already had.

    A leading U+FEFF in ``text`` is dropped and the BOM decided by the file: whether the caller
    read it with ``utf-8`` (BOM in the text) or ``utf-8-sig`` (BOM gone), it ends up exactly once.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = _detect_newline(path)
    bom = codecs.BOM_UTF8 if _has_utf8_bom(path) else b""
    _backup(path)
    normalized = text.removeprefix("﻿").replace("\r\n", "\n").replace("\n", newline)
    path.write_bytes(bom + normalized.encode("utf-8"))


def _read_text(path: Path) -> str:
    """For read-only lookups: a missing or unreadable file reads as ``""``.

    A step that rewrites the file afterwards must use `_read_text_for_rewrite`: rebuilding the file
    from this ``""`` would wipe everything the user had in it.
    """
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""


class UnreadableConfigError(Exception):
    """A config file exists but cannot be read (not a JSON object, not UTF-8, cannot be opened).

    The step that would rewrite it raises this instead, so the file stays byte for byte as it was
    and `apply` counts the action as a failure (REQ-027 of `retire-legacy-aliases`).
    """


def _read_text_for_rewrite(path: Path) -> str:
    """For a step that rewrites ``path``: ``""`` if it does not exist; `UnreadableConfigError` if
    it exists but cannot be read as UTF-8 text.

    `_read_text` gives ``""`` for both an empty file and one in cp1252 or UTF-16, and rebuilding
    from that ``""`` left a `CLAUDE.md` with only our block (or empty, on uninstall) while the
    command said OK. A UTF-8 BOM is fine and is dropped here; `_write_text` puts it back. NUL bytes
    are refused too: UTF-16 without a BOM is valid UTF-8 byte by byte.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        reason = str(exc.strerror or exc)
    else:
        if raw.startswith(tuple(bom for bom, _codec in _UTF16_BOMS)):
            reason = t("install.text_unreadable.reason.utf16")
        elif b"\x00" in raw:
            reason = t("install.completion.reason.nul_bytes")
        else:
            try:
                # Universal newlines, as `read_text` did: the regexes (`[ \t]*\n`) expect `\n`,
                # and `_write_text` puts back the file's own line ending.
                return raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
            except UnicodeDecodeError:
                reason = t("install.migrate.reason.not_utf8")
    raise UnreadableConfigError(
        t(
            "install.config_unreadable",
            path=path,
            reason=reason,
            fix=t("install.text_unreadable.fix"),
        )
    )


def _decode_config_json(raw: bytes) -> tuple[dict | None, str | None]:
    """`(object, None)` or `(None, reason)`. Decodes with `utf-8-sig`: a BOM is not an error."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, t("install.migrate.reason.not_utf8")
    try:
        data = json.loads(text)
    except ValueError:
        return None, t("install.migrate.reason.not_json")
    if not isinstance(data, dict):
        return None, t("install.migrate.reason.not_object")
    return data, None


def _read_json(path: Path) -> dict:
    """For read-only lookups: a missing or unreadable file reads as `{}`.

    A step that rewrites the file afterwards must use `_read_config_json`: rebuilding the file from
    this `{}` would wipe its `env` and every foreign key (REQ-027).
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    data, _reason = _decode_config_json(raw)
    return data if data is not None else {}


def _read_config_json(path: Path) -> dict:
    """For a step that rewrites `path`: `{}` if it does not exist; `UnreadableConfigError` if it
    exists but cannot be read as a JSON object (REQ-027). A BOM is read (REQ-026)."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        reason = str(exc.strerror or exc)
    else:
        data, reason = _decode_config_json(raw)
        if data is not None:
            return data
    raise UnreadableConfigError(
        t(
            "install.config_unreadable",
            path=path,
            reason=reason,
            fix=t("install.config_unreadable.fix"),
        )
    )


def _has_utf8_bom(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(codecs.BOM_UTF8)) == codecs.BOM_UTF8
    except OSError:
        return False


def _write_json(path: Path, data: dict, *, atomic: bool = False) -> None:
    """Writes `data` with the line ending and the UTF-8 BOM the file already had (REQ-026).

    With ``atomic``, through a temporary + ``os.replace`` (`_atomic_write`): for `~/.claude.json`,
    which Claude Code keeps rewriting, a half-written file would lose every session's state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = _detect_newline(path)
    bom = codecs.BOM_UTF8 if _has_utf8_bom(path) else b""
    _backup(path)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    payload = bom + text.replace("\n", newline).encode("utf-8")
    if atomic:
        _atomic_write(path, payload)
    else:
        path.write_bytes(payload)


def upsert_block(text: str, block: str, begin: str, end: str) -> str:
    """Inserta o reemplaza el bloque delimitado, conservando el resto del archivo."""
    managed = f"{begin}\n{block.strip()}\n{end}"
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(managed, text, count=1)
    prefix = text.rstrip()
    return (prefix + "\n\n" if prefix else "") + managed + "\n"


def managed_block(text: str, begin: str, end: str) -> str | None:
    """Lo que hay entre los marcadores, o ``None`` si el fichero no tiene el bloque completo."""
    pattern = re.compile(re.escape(begin) + r"(.*?)" + re.escape(end), re.DOTALL)
    found = pattern.search(text)
    return found.group(1) if found else None


def localized_resource(path: Path, lang: str) -> Path:
    """La variante de ``path`` en ``lang``: el español es el fichero base (`SKILL.md`) y cada
    otro idioma lleva su código antes de la extensión (`SKILL.en.md`), en el mismo directorio.

    Así el directorio de la skill se copia entero salvo las variantes, y el `SKILL.md` instalado
    es siempre el del idioma vigente (REQ-029).
    """
    if lang == i18n.CATALOG_FALLBACK:
        return path
    return path.with_name(f"{path.stem}.{lang}{path.suffix}")


def skill_source(lang: str) -> Path:
    """El `SKILL.md` empaquetado en ``lang``."""
    return localized_resource(resources_dir() / "skills" / SKILL_NAME / "SKILL.md", lang)


def memory_source(lang: str) -> Path:
    """El bloque de memoria empaquetado en ``lang``."""
    return localized_resource(resources_dir() / "memory" / "local-delegate.md", lang)


def packaged_memory_blocks() -> tuple[str, ...]:
    """El bloque de memoria empaquetado de cada idioma admitido (D12).

    Es la lista contra la que `doctor` decide si el bloque de `CLAUDE.md`/`AGENTS.md` está al
    día, y por eso `checks` llama a esta función en vez de leer el fichero: no tiene que saber
    cuántos idiomas hay. Un bloque al día en **cualquier** idioma da `OK` y `update` no lo
    reescribe; cambiar de idioma es cosa de `install`.
    """
    return tuple(memory_source(lang).read_text(encoding="utf-8") for lang in i18n.LANGUAGES)


def catalog_block_for(lang: str) -> str | None:
    """El bloque de catálogo de subagentes en ``lang``, sacado de la skill de ese idioma."""
    # Import diferido por el mismo motivo que en `plan_install`: `agents` no importa este módulo.
    from . import agents as agents_mod

    catalog = agents_mod.tool_catalog(skill_source(lang))
    return agents_mod.catalog_block(catalog, lang) if catalog else None


def packaged_catalog_blocks() -> tuple[str, ...]:
    """El bloque de catálogo de subagentes empaquetado de cada idioma admitido (D12)."""
    blocks = (catalog_block_for(lang) for lang in i18n.LANGUAGES)
    return tuple(block for block in blocks if block)


def memory_block_is_current(text: str) -> bool | None:
    """¿El bloque gestionado de ``text`` es uno de los empaquetados? ``None`` si no hay bloque."""
    from .agents import normalize_block

    inner = managed_block(text, MD_BEGIN, MD_END)
    if inner is None:
        return None
    packaged = {normalize_block(block) for block in packaged_memory_blocks()}
    return normalize_block(inner) in packaged


def plan_catalog_refresh(home: Path, lang: str | None = None) -> list[Action]:
    """Regenera el bloque de catálogo de los subagentes que ya lo tienen y está desfasado (D12).

    Solo mira los `~/.claude/agents/*.md` que **ya** traen los marcadores de catálogo, y solo
    reescribe lo que hay entre ellos: por eso no necesita `--agents`, que es el permiso para
    tocar ficheros que escribió el usuario. Un subagente sin marcadores no se toca, y uno cuyo
    bloque coincide con el empaquetado de algún idioma tampoco. Lo desfasado se reescribe en
    ``lang`` (el idioma vigente; por defecto, el de este proceso).
    """
    from . import agents as agents_mod

    agents_dir = home / ".claude" / "agents"
    packaged = packaged_catalog_blocks()
    current = catalog_block_for(lang or i18n.lang())
    if not packaged or current is None or not agents_dir.is_dir():
        return []
    changes = []
    for path in sorted(agents_dir.glob("*.md")):
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        updated = agents_mod.refresh_catalog_block(original, current, packaged)
        if updated is not None:
            changes.append((path, updated))
    if not changes:
        return []

    def _run() -> str:
        written, failed = [], []
        for path, text in changes:
            try:
                _write_text(path, text)
                written.append(path.name)
            except OSError as exc:
                failed.append(_failure(path.name, exc))
        detail = t("install.agents.catalog_refreshed", n=len(written), names=", ".join(written))
        return detail + _not_written(failed)

    names = ", ".join(path.name for path, _ in changes)
    return [Action("agents", agents_dir, t("install.agents.refresh_plan", names=names), _run)]


def _failure(name: str, exc: OSError) -> str:
    """``nombre (motivo)`` de un fichero que no se pudo escribir o borrar."""
    return f"{name} ({exc.strerror or exc})"


def _not_written(failed: list[str]) -> str:
    return t("install.not_written", names="; ".join(failed)) if failed else ""


def _not_removed(failed: list[str]) -> str:
    return t("install.not_removed", names="; ".join(failed)) if failed else ""


def remove_block(text: str, begin: str, end: str) -> str:
    """Quita el bloque gestionado (y los blancos que deja) sin tocar lo demás."""
    pattern = re.compile(r"\n*" + re.escape(begin) + r".*?" + re.escape(end) + r"\n*", re.DOTALL)
    cleaned = pattern.sub("\n\n", text)
    return cleaned.strip() + "\n" if cleaned.strip() else ""


# --- Shell profiles, as bytes (SDD cli-completion, deviation 1) -------------
# `upsert_block`/`remove_block` do not fit a profile: `_read_text` gives "" for a file that is not
# UTF-8 (a 5.1 profile saved in ANSI with accents would be replaced by the block), `_write_text`
# always writes UTF-8, both do `strip()` and `_backup` overwrites the user's `.bak`. These two
# helpers do not write: they compute the new bytes, and `write_profile_edit` writes them. Outside
# the block, the profile stays byte for byte the same (REQ-028).
PROFILE_BACKUP_SUFFIX = ".local-delegate.bak"
_UTF8_BOM = b"\xef\xbb\xbf"
_UTF16_BOMS = ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))
#: Reason why a profile is not touched → its text in the catalog.
PROFILE_SKIP_REASONS = {
    "unreadable": "install.completion.reason.unreadable",
    "nul_bytes": "install.completion.reason.nul_bytes",
    "marker_mismatch": "install.completion.reason.marker_mismatch",
    "broken_link": "install.completion.reason.broken_link",
}


@dataclass(frozen=True)
class ProfileEdit:
    """What has to be done to a profile, without having done it yet.

    ``target`` is the resolved destination (the real file if ``path`` is a link, REQ-045).
    ``data`` are the new bytes, or ``None`` if there is no change. ``reason`` says why it is not
    touched (a key of ``PROFILE_SKIP_REASONS``); ``existed``, whether the destination existed when
    planning.
    """

    path: Path
    target: Path
    data: bytes | None = None
    reason: str | None = None
    existed: bool = False

    @property
    def changed(self) -> bool:
        return self.data is not None

    def skip_message(self) -> str | None:
        """The catalog warning of a profile that is not touched, or ``None``."""
        if self.reason is None:
            return None
        return t(
            "install.completion.profile_skipped",
            path=self.path,
            reason=t(PROFILE_SKIP_REASONS[self.reason]),
        )


def profile_backup_path(target: Path) -> Path:
    """The own copy of a profile, next to the destination: never ``<profile>.bak`` (REQ-046)."""
    return target.with_name(target.name + PROFILE_BACKUP_SUFFIX)


def _profile_target(path: Path) -> tuple[Path, str | None]:
    """The resolved destination of ``path`` and, if it cannot be touched, the reason (REQ-045)."""
    target = path
    if path.is_symlink():
        try:
            target = path.resolve(strict=True)
        except (OSError, RuntimeError):
            return path, "broken_link"
    if target.exists() and not target.is_file():
        return target, "unreadable"
    return target, None


def _decode_profile(raw: bytes) -> tuple[str, str, bytes] | str:
    """``(text, codec, BOM)`` of a profile, or the reason why it is not touched.

    UTF-16 BOM → that codec; NUL without a UTF-16 BOM → not touched (it would be an unmarked
    UTF-16); strict UTF-8 (with or without BOM); otherwise ``latin-1``, which round-trips any byte.
    """
    for bom, codec in _UTF16_BOMS:
        if raw.startswith(bom):
            try:
                return raw[len(bom) :].decode(codec), codec, bom
            except UnicodeDecodeError:
                return "unreadable"
    if b"\x00" in raw:
        return "nul_bytes"
    bom = _UTF8_BOM if raw.startswith(_UTF8_BOM) else b""
    body = raw[len(bom) :]
    try:
        return body.decode("utf-8"), "utf-8", bom
    except UnicodeDecodeError:
        return body.decode("latin-1"), "latin-1", bom


def _dominant_newline(text: str) -> str:
    crlf = text.count("\r\n")
    return "\r\n" if crlf > text.count("\n") - crlf else "\n"


def _profile_block_span(text: str) -> tuple[int, int] | str | None:
    """Where the block is, ``None`` if there is none, or ``"marker_mismatch"`` if half of it."""
    begin, end = shell_profiles.BLOCK_BEGIN, shell_profiles.BLOCK_END
    starts, ends = text.count(begin), text.count(end)
    if starts == 0 and ends == 0:
        return None
    if starts != 1 or ends != 1 or text.index(end) < text.index(begin):
        return "marker_mismatch"
    return text.index(begin), text.index(end) + len(end)


def _read_profile(path: Path) -> tuple[Path, tuple[str, str, bytes] | None, str | None]:
    """Destination, ``(text, codec, BOM)`` (``None`` if missing) and reason not to touch it."""
    target, problem = _profile_target(path)
    if problem or not target.exists():
        return target, None, problem
    try:
        raw = target.read_bytes()
    except OSError:
        return target, None, "unreadable"
    decoded = _decode_profile(raw)
    if isinstance(decoded, str):
        return target, None, decoded
    return target, decoded, None


def upsert_profile_block(path: Path, block: str) -> ProfileEdit:
    """Puts ``block`` (with its markers) into the profile, without writing (REQ-027, REQ-028).

    - Empty or missing profile → ``block + NL``.
    - With text → ``text + NL + block + NL``: if the text ended in a newline, a blank separating
      line is left; if not, not.
    - With the block already in place → what is inside is replaced without moving anything else.

    The line ending is the file's dominant one, and the encoding (and BOM) the one it had.
    """
    target, decoded, problem = _read_profile(path)
    if problem:
        return ProfileEdit(path, target, reason=problem, existed=target.exists())
    if decoded is None:
        data = (block + "\n").encode("utf-8")
        return ProfileEdit(path, target, data=data, existed=False)
    text, codec, bom = decoded
    newline = _dominant_newline(text)
    inserted = block.replace("\r\n", "\n").replace("\n", newline)
    if codec == "latin-1":
        # The bash/zsh block may carry the path in UTF-8: those bytes are what the shell will
        # read, so they go as they are into the text decoded as latin-1.
        inserted = inserted.encode("utf-8").decode("latin-1")
    span = _profile_block_span(text)
    if isinstance(span, str):
        return ProfileEdit(path, target, reason=span, existed=True)
    if span is not None:
        updated = text[: span[0]] + inserted + text[span[1] :]
    elif text == "":
        updated = inserted + newline
    else:
        updated = text + newline + inserted + newline
    if updated == text:
        return ProfileEdit(path, target, existed=True)
    return ProfileEdit(path, target, data=bom + updated.encode(codec), existed=True)


def remove_profile_block(path: Path) -> ProfileEdit:
    """Removes the block from the profile, without writing; the exact inverse of
    ``upsert_profile_block``.

    The block, the newline that closes it and the newline before it (if any) are removed: a
    profile that ended in a newline ends in one again, and one that did not comes back without it.
    With the block at the start, only the block and its newline are removed.
    """
    target, decoded, problem = _read_profile(path)
    if problem:
        return ProfileEdit(path, target, reason=problem, existed=target.exists())
    if decoded is None:
        return ProfileEdit(path, target, existed=False)
    text, codec, bom = decoded
    span = _profile_block_span(text)
    if isinstance(span, str):
        return ProfileEdit(path, target, reason=span, existed=True)
    if span is None:
        return ProfileEdit(path, target, existed=True)
    start, end = span
    for newline in ("\r\n", "\n"):
        if text.startswith(newline, end):
            end += len(newline)
            break
    for newline in ("\r\n", "\n"):
        if text[:start].endswith(newline):
            start -= len(newline)
            break
    updated = text[:start] + text[end:]
    return ProfileEdit(path, target, data=bom + updated.encode(codec), existed=True)


def write_profile_edit(edit: ProfileEdit, *, backup: bool = True) -> str | None:
    """Writes a ``ProfileEdit`` to its resolved destination; ``None`` if it went well (or there
    was nothing to do).

    - It writes in place, not with a temporary + ``os.replace``: over a link that would break it
      (REQ-045), and on POSIX it would bypass the protection of a read-only file.
    - With ``backup``, the destination is first copied to ``<destination>.local-delegate.bak``
      **only if that copy does not exist**, so it keeps the state before the first install
      (REQ-046).
    - A write error does not raise: ``name (reason)`` is returned, like ``_failure``, for the
      ``install.not_written`` warning (REQ-028).
    """
    if edit.data is None:
        return None
    target = edit.target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if backup and target.is_file():
            copy = profile_backup_path(target)
            if not copy.exists():
                shutil.copy2(target, copy)
        target.write_bytes(edit.data)
    except OSError as exc:
        return _failure(target.name, exc)
    return None


# --- install/uninstall --shell-completion (SDD cli-completion, L3b) ----------
class CompletionWriteError(OSError):
    """A completion profile or file that could not be written or deleted.

    It is raised from ``Action.run`` on purpose: ``apply`` counts it as a failure and the exit
    code becomes 1 (REQ-028, REQ-030), while the other shells go on.
    """


@dataclass(frozen=True)
class ShellProbes:
    """What completion asks the machine, injectable for the tests.

    ``None`` in each field is the real value (``sys.platform``, ``shutil.which``, the PowerShell
    query…). ``shell_env`` is the ``$SHELL`` of REQ-024.
    """

    platform: str | None = None
    which: Callable[[str], str | None] | None = None
    shell_env: str | None = None
    query: shell_profiles.Query | None = None
    environ: Mapping[str, str] | None = None
    known_folder: Callable[[], Path | None] | None = None
    simulated_policy: str = shell_profiles.SIMULATED_POLICY


def shell_probes() -> ShellProbes:
    """The real probes. The CLI tests replace it with ones made of doubles."""
    return ShellProbes(shell_env=os.environ.get("SHELL"))


@dataclass
class CompletionPlan:
    """The completion actions and the warnings given before applying them."""

    actions: list[Action] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Data shown before the warnings: the profile path and policy of each PowerShell edition
    #: (REQ-040), with and without ``--dry-run``.
    notes: list[str] = field(default_factory=list)


def _atomic_write(path: Path, data: bytes) -> None:
    """Temporary in the same folder + ``os.replace``: never a half-written file (REQ-026)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def missing_dirs(directory: Path) -> list[Path]:
    """`directory` and its ancestors that do not exist yet, deepest first: the folders a
    `mkdir(parents=True)` would create (SDD backlog-minor-leftovers, REQ-005)."""
    missing: list[Path] = []
    current = directory
    while not current.exists() and current.parent != current:
        missing.append(current)
        current = current.parent
    return missing


def remove_empty_dirs(paths: Sequence[Path | str]) -> bool:
    """Removes each folder of `paths` that exists and is empty, deepest first; `True` if none is
    left. A folder with anything inside (ours or someone else's) is never touched (REQ-005)."""
    left = False
    for path in sorted((Path(p) for p in paths), key=lambda p: len(p.parts), reverse=True):
        # A folder that cannot be read or removed is simply left, and counted as left.
        with contextlib.suppress(OSError):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        left = left or path.exists()
    return not left


def _same_bytes(path: Path, data: bytes) -> bool:
    try:
        return path.read_bytes() == data
    except OSError:
        return False


def _owned_file_action(
    kind: str, path: Path, data: bytes, detail: str, literal: str = ""
) -> Action:
    """Writes a file of ours (completion or manifest): no ``.bak``, atomic (REQ-026)."""
    if _same_bytes(path, data):
        return Action(kind, path, t("install.completion.up_to_date"))

    def _run() -> str:
        try:
            _atomic_write(path, data)
        except OSError as exc:
            raise CompletionWriteError(
                t("install.completion.not_written", names=_failure(path.name, exc))
            ) from exc
        return t("install.completion.written")

    return Action(kind, path, detail, _run, literal=literal)


def _profile_install_action(shell: str, edit: ProfileEdit, block: str, backup: bool) -> Action:
    if not edit.changed:
        return Action("profile", edit.path, t("install.completion.up_to_date"))

    def _run() -> str:
        error = write_profile_edit(edit, backup=backup)
        if error:
            raise CompletionWriteError(t("install.completion.not_written", names=error))
        return t("install.completion.block_written")

    detail = t("install.completion.profile_plan", shell=shell)
    return Action("profile", edit.path, detail, _run, literal=block)


def plan_completion_install(
    home: Path,
    requested: Sequence[str],
    *,
    lang: str,
    data_dir: Path | None = None,
    probes: ShellProbes | None = None,
) -> CompletionPlan:
    """The actions of ``install --shell-completion`` (REQ-024 to REQ-029, REQ-043, REQ-044).

    For each resolved shell: the completion file (``render(shell, lang=lang)``), the load block in
    each profile and, at the end, the manifest merged with any previous one. A PowerShell edition
    with a blocking policy is skipped with a warning; if all are skipped, neither
    ``local-delegate.ps1`` nor its entry is written. It writes nothing: ``apply`` does.
    """
    probes = probes or shell_probes()
    simulated = is_simulated_home(home)
    directory = shell_profiles.completion_dir(home, data_dir)
    resolution = shell_profiles.resolve_shells(
        requested, platform=probes.platform, which=probes.which, shell_env=probes.shell_env
    )
    plan = CompletionPlan(warnings=resolution.warnings())

    profiles: dict[str, list[Path]] = {}
    for target in resolution.targets:
        location = shell_profiles.profile_path(
            target,
            home,
            simulated=simulated,
            query=probes.query,
            platform=probes.platform,
            environ=probes.environ,
            known_folder=probes.known_folder,
            simulated_policy=probes.simulated_policy,
        )
        note = shell_profiles.policy_note(target, location)
        if note:
            plan.notes.append(note)
        warning = shell_profiles.policy_warning(target, location.policy)
        if warning:
            plan.warnings.append(warning)
        if shell_profiles.policy_blocks(location.policy):
            continue
        paths = profiles.setdefault(target.shell, [])
        if location.path not in paths:
            paths.append(location.path)

    manifest = _read_manifest_or_warn(directory, plan.warnings)
    listed = {
        profile["path"]: profile
        for entry in (manifest or {}).get("shells", [])
        for profile in entry["profiles"]
    }
    written: dict[str, tuple[str, list[dict]]] = {}
    for shell in (s for s in shell_profiles.SHELLS if s in profiles):
        file = shell_profiles.completion_file(directory, shell)
        content = completion.render(shell, lang=lang).encode("utf-8")
        detail = t("install.completion.file_plan", shell=shell)
        plan.actions.append(_owned_file_action("completion", file, content, detail))
        block = shell_profiles.load_block(shell, file)
        entries = []
        for path in profiles[shell]:
            edit = upsert_profile_block(path, block)
            if edit.reason:
                plan.warnings.append(edit.skip_message())
                continue
            previous = listed.get(str(path))
            if previous:
                entries.append(dict(previous))
            else:
                entry = {
                    "path": str(path),
                    "created": not edit.existed,
                    "created_parent": not edit.target.parent.exists(),
                }
                # Folders above the parent that `install` creates too (REQ-005, e.g. `Documents`).
                ancestors = missing_dirs(edit.target.parent.parent)
                if entry["created_parent"] and ancestors:
                    entry["created_ancestors"] = [str(d) for d in ancestors]
                entries.append(entry)
            created = entries[-1]["created"]
            # A profile that `install` created gets no copy: its previous state is «missing».
            plan.actions.append(_profile_install_action(shell, edit, block, backup=not created))
        written[shell] = (str(file), entries)

    if written:
        from .version import get_version

        data = completion.merge_manifest(
            manifest,
            generator=get_version(),
            lang=lang,
            written=written,
            created_ancestors=[str(d) for d in missing_dirs(directory.parent)],
        )
        text = completion.manifest_bytes(data)
        path = completion.manifest_path(directory)
        detail = t("install.completion.manifest_plan")
        plan.actions.append(
            _owned_file_action("manifest", path, text, detail, literal=text.decode("utf-8"))
        )
    return plan


def _read_manifest_or_warn(directory: Path, warnings: list[str]) -> dict | None:
    try:
        return completion.read_manifest(directory)
    except completion.ManifestUnreadableError:
        path = completion.manifest_path(directory)
        warnings.append(t("install.completion.manifest_unreadable", path=path))
        return None


def _profile_uninstall_action(
    edit: ProfileEdit, created: bool, created_parent: bool, ancestors: Sequence[str] = ()
) -> Action:
    data = edit.data or b""

    def _run() -> str:
        target = edit.target
        if created and not data.strip():
            # `install` created the profile and only emptiness is left: it is deleted, and so is
            # its folder if `install` also created it and it is now empty (REQ-032), and the
            # empty folders above it that `install` created (REQ-005). A profile that already
            # existed is never deleted.
            try:
                target.unlink()
                if created_parent and not any(target.parent.iterdir()):
                    target.parent.rmdir()
            except OSError as exc:
                raise CompletionWriteError(
                    t("install.completion.not_removed", names=_failure(target.name, exc))
                ) from exc
            if created_parent:
                remove_empty_dirs(ancestors)
            return t("install.completion.profile_deleted")
        error = write_profile_edit(edit, backup=not created)
        if error:
            raise CompletionWriteError(t("install.completion.not_written", names=error))
        # The own copy is not needed if the profile went back to being it (REQ-046).
        copy = profile_backup_path(target)
        if _same_bytes(copy, data):
            with contextlib.suppress(OSError):
                copy.unlink()
        return t("install.completion.block_removed")

    return Action("profile", edit.path, t("install.completion.uninstall_profile_plan"), _run)


def _remove_owned_action(kind: str, path: Path, detail: str) -> Action:
    def _run() -> str:
        try:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        except FileNotFoundError:
            return t("install.uninstall.did_not_exist")
        except OSError as exc:
            raise CompletionWriteError(
                t("install.completion.not_removed", names=_failure(path.name, exc))
            ) from exc
        return t("install.uninstall.removed")

    return Action(kind, path, detail, _run)


def uninstall_shells(requested: Sequence[str]) -> tuple[str, ...]:
    """The shells of ``uninstall --shell-completion``: ``auto`` (or nothing) means all (REQ-032)."""
    if not requested or "auto" in requested:
        return shell_profiles.SHELLS
    return tuple(s for s in shell_profiles.SHELLS if s in requested)


def plan_completion_uninstall(
    home: Path,
    requested: Sequence[str],
    *,
    data_dir: Path | None = None,
    probes: ShellProbes | None = None,
) -> CompletionPlan:
    """The actions that remove completion from the requested shells (REQ-032, REQ-046).

    It removes the block from the union of the manifest profiles and the existing candidates,
    deletes the completion files, updates or deletes the manifest, and deletes the
    ``completion/`` directory if it is left empty, plus the empty folders above it that
    ``install`` created (REQ-005). With nothing installed, there are no actions. It writes nothing.
    """
    probes = probes or shell_probes()
    shells = uninstall_shells(requested)
    simulated = is_simulated_home(home)
    directory = shell_profiles.completion_dir(home, data_dir)
    plan = CompletionPlan()
    manifest_file = completion.manifest_path(directory)
    manifest = _read_manifest_or_warn(directory, plan.warnings)
    broken = manifest is None and manifest_file.is_file()

    listed: dict[str, dict] = {}
    for entry in (manifest or {}).get("shells", []):
        if entry["shell"] in shells:
            for profile in entry["profiles"]:
                listed.setdefault(profile["path"], profile)
    candidates = shell_profiles.candidate_profiles(
        home,
        simulated=simulated,
        platform=probes.platform,
        which=probes.which,
        query=probes.query,
        environ=probes.environ,
        known_folder=probes.known_folder,
        shells=shells,
    )
    paths: list[Path] = []
    for path in [Path(p) for p in listed] + candidates:
        if path not in paths:
            paths.append(path)
    for path in paths:
        edit = remove_profile_block(path)
        if edit.reason:
            plan.warnings.append(edit.skip_message())
            continue
        if not edit.changed:
            continue
        entry = listed.get(str(path), {})
        plan.actions.append(
            _profile_uninstall_action(
                edit,
                bool(entry.get("created")),
                bool(entry.get("created_parent")),
                entry.get("created_ancestors", ()),
            )
        )

    removed: set[Path] = set()
    for shell in shells:
        file = shell_profiles.completion_file(directory, shell)
        if file.is_file():
            detail = t("install.completion.uninstall_file_plan", shell=shell)
            plan.actions.append(_remove_owned_action("completion", file, detail))
            removed.add(file)

    if manifest is not None:
        left = completion.manifest_without(manifest, shells)
        if left is None:
            detail = t("install.completion.uninstall_manifest_plan")
            plan.actions.append(_remove_owned_action("manifest", manifest_file, detail))
            removed.add(manifest_file)
        elif left != manifest:
            text = completion.manifest_bytes(left)
            detail = t("install.completion.manifest_plan")
            plan.actions.append(_owned_file_action("manifest", manifest_file, text, detail))
    elif broken and set(shells) == set(shell_profiles.SHELLS):
        detail = t("install.completion.uninstall_manifest_plan")
        plan.actions.append(_remove_owned_action("manifest", manifest_file, detail))
        removed.add(manifest_file)

    if removed and directory.is_dir() and set(directory.iterdir()) <= removed:
        detail = t("install.completion.uninstall_dir_plan")
        plan.actions.append(_remove_owned_action("remove", directory, detail))
        # Only when no entry is left: the folders above `completion/` are shared by all shells.
        ancestors = (manifest or {}).get("created_ancestors", [])
        if ancestors and completion.manifest_without(manifest, shells) is None:
            plan.actions.append(_remove_ancestors_action(ancestors))
    return plan


def _remove_ancestors_action(ancestors: Sequence[str]) -> Action:
    """Removes the folders above `completion/` that `install` created, while they are empty
    (SDD backlog-minor-leftovers, REQ-005). One with foreign content stays, without an error."""
    deepest = max((Path(p) for p in ancestors), key=lambda p: len(p.parts))

    def _run() -> str:
        if remove_empty_dirs(ancestors):
            return t("install.uninstall.removed")
        return t("install.completion.ancestors_kept")

    return Action("remove", deepest, t("install.completion.uninstall_ancestors_plan"), _run)


# --- Hooks de Claude Code ----------------------------------------------------
def hook_command(
    hooks_dir: PurePath, script: str, python_exe: str, extra: tuple[str, ...] = ()
) -> str:
    """Comando del hook: un único string que Claude Code entrega a un shell.

    La ruta va **siempre entre comillas y con barras `/`**, no solo cuando tiene espacios. En
    Windows, pasar `C:\\Users\\...` desnudo llega al shell como `C:UsersYohan.claudehooks...`
    —el shell interpreta cada `\\` como escape y lo borra— y el hook muere con «can't open
    file». Cuando eso le pasa a `UserPromptSubmit`, **bloquea cada prompt del usuario**: no es
    un hook que no sugiere, es un cliente inutilizable. Python abre rutas con `/` en Windows sin
    problema, así que la forma citada y con barras funciona en los tres shells (sh, cmd,
    PowerShell) y en los tres sistemas.

    El intérprete sigue la misma regla en cuanto lleva espacios o `\\` (``--python`` con una
    ruta como `C:\\Program Files\\...`): ver ``_shell_exe``. El nombre por defecto
    (``python``/``python3``) va desnudo, como siempre. Límite conocido: un comando que *empieza*
    entre comillas lo aceptan sh y cmd, pero PowerShell lo lee como una cadena y no lo ejecuta;
    sin comillas no lo ejecutaba ningún shell, y Claude Code corre estos hooks con sh.

    ``extra`` son argumentos para el script. Solo lo usa el hook de Read, y para que el propio
    registro sea el interruptor: ver el comentario de ``_READ_HOOK``.
    """
    parts = [_shell_exe(python_exe), f'"{(hooks_dir / script).as_posix()}"', *extra]
    return " ".join(parts)


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
    "suggest_delegate_shell.py",
    "record_call.py",
    "subagent_start.py",
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
    return any(name in normalized for name in _SCRIPT_NAMES + _RETIRED_SCRIPTS)


def read_hook_registered(claude_dir: Path) -> bool:
    """True si el ``settings.json`` de Claude Code registra ya nuestro hook de lectura.

    Lo necesita ``update``: al reponer los hooks reescribe el registro con ``merge_hook_settings``,
    que **retira** todas nuestras entradas previas antes de poner las nuevas. Si no sabe que el de
    lectura estaba puesto, lo quita, y el bloqueo se apaga en silencio justo al actualizar.
    Se mira el nombre del script y no ``READ_HOOK_FLAG``: una entrada vieja sin la bandera también
    es una decisión del usuario de tenerlo, y respetarla es no quitarlo.
    """
    hooks = _read_json(claude_dir / "settings.json").get("hooks")
    if not isinstance(hooks, dict):
        return False
    hooks_dir = claude_dir / "hooks" / HOOKS_SUBDIR
    for groups in hooks.values():
        for group in groups if isinstance(groups, list) else []:
            for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                if not isinstance(hook, dict) or not _is_ours(hook, hooks_dir):
                    continue
                args = hook.get("args")
                text = " ".join([str(hook.get("command", ""))] + [str(a) for a in args or []])
                if _READ_HOOK[0] in text:
                    return True
    return False


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
WEB_TOKEN_VAR = "LOCAL_DELEGATE_WEB_TOKEN"


def daemon_mcp_url() -> str:
    """URL del MCP del daemon. Una sola derivación para los tres clientes.

    La calculaban `mcp_entry` y (desde que existe opencode) haría falta otra vez en
    `opencode_mcp_entry`. Dos copias de «dónde escucha el daemon» es justo el defecto que este
    repo ya pagó con la cuenta de tokens y con el host del daemon.
    """
    # Vacía cuenta como no puesta, igual que en `config._env`: `http://:9393/mcp` no es una URL.
    port = os.environ.get("LOCAL_DELEGATE_WEB_PORT", "").strip() or "9393"
    host = os.environ.get("LOCAL_DELEGATE_WEB_HOST", "").strip() or "127.0.0.1"
    return f"http://{host}:{port}/mcp"


def uvx_command(version: str | None) -> list[str]:
    """Cómo se lanza el servidor por stdio. También compartida por los tres clientes."""
    package = f"local-delegate-mcp=={version}" if version else "local-delegate-mcp"
    return ["uvx", "--from", package, "local-delegate-mcp"]


def stdio_env(base_url: str | None, api_key_env: bool, key_ref: str) -> dict[str, str]:
    """Variables de entorno del proceso stdio. ``key_ref`` es **cómo se referencia** la key.

    El único punto en el que los clientes difieren de verdad: Claude Code expande ``${VAR}`` y
    opencode expande ``{env:VAR}``. Escribir la sintaxis del otro deja la variable literal en el
    entorno del hijo — un fallo silencioso que se ve como un 401 y no como una configuración mala.
    """
    env: dict[str, str] = {}
    if base_url:
        env["LOCAL_DELEGATE_BASE_URL"] = base_url
        env["LOCAL_DELEGATE_AUTOSTART"] = "0"
    if api_key_env:
        # Nunca se escribe el secreto: se referencia la variable del entorno del cliente.
        env["LOCAL_DELEGATE_API_KEY"] = key_ref
    return env


def mcp_entry(
    mode: str,
    base_url: str | None,
    api_key_env: bool,
    version: str | None,
    web_token_env: bool = False,
) -> dict:
    """Entrada de servidor MCP para Claude Code (stdio vía uvx, o HTTP contra el daemon)."""
    if mode == "http":
        entry: dict = {"type": "http", "url": daemon_mcp_url()}
        if web_token_env:
            # Se referencia la variable, nunca su valor. Medido contra Claude Code 2.1.220: la
            # expansión de `${VAR}` dentro de `headers` funciona y llega al servidor ya resuelta.
            entry["headers"] = {"Authorization": f"Bearer ${{{WEB_TOKEN_VAR}}}"}
        return entry
    command = uvx_command(version)
    entry: dict = {
        "type": "stdio",
        "command": command[0],
        "args": command[1:],
    }
    env = stdio_env(base_url, api_key_env, "${LOCAL_DELEGATE_API_KEY}")
    if env:
        entry["env"] = env
    return entry


# --- La cabecera que ya tenía la entrada --------------------------------------
# Reinstalar con `--mcp-mode http` sin `--web-token-env` borraba la cabecera de una entrada que
# funcionaba, y contra un daemon con token el cliente pasaba a 401 al instante (2026-08-18). Por eso
# el flag tiene tres estados y el de «no dijiste nada» conserva lo que hubiera. Se lee del disco y
# no se deduce preguntando al daemon: `install` no sale a la red por contrato.
# Las dos formas de cadena TOML: básica (`"VAR"`) y literal (`'VAR'`). Hasta la 0.40.0 solo se
# reconocía la básica, y una entrada editada a mano o reescrita por otro programa con comillas
# simples se reinstalaba sin la variable: Codex, a 401. Anclada al principio de línea para no leer
# una clave comentada. Se queda en regex y no en `tomllib` a propósito: la sección se recorta del
# fichero, que puede no ser TOML válido entero, y un fallo de análisis no puede dejar sin cabecera.
_CODEX_BEARER_RE = re.compile(
    r"""(?m)^[ \t]*bearer_token_env_var[ \t]*=[ \t]*(?:"([^"\n]+)"|'([^'\n]+)')"""
)


def codex_bearer_variable(section: str) -> str | None:
    """El nombre de la variable de `bearer_token_env_var` en la sección de Codex, o ``None``."""
    found = _CODEX_BEARER_RE.search(section)
    return (found.group(1) or found.group(2)) if found else None


# `Bearer ${VAR}` (Claude Code) o `Bearer {env:VAR}` (opencode). Lo que no casa es un token literal.
_REFERENCE_RE = re.compile(r"^Bearer (?:\$\{([^}]+)\}|\{env:([^}]+)\})$")


def existing_header(home: Path, target: str) -> str | None:
    """El valor de `Authorization` de la entrada HTTP ya instalada en ``target``, o ``None``.

    Se devuelve **en la sintaxis de ese cliente** y tal cual, incluido un nombre de variable que no
    sea el nuestro: conservar es no cambiar lo que funcionaba. Codex no guarda una cabecera sino el
    nombre de la variable, así que se le da forma de cabecera para que `codex_mcp_block` lo
    reconstruya igual.

    Una entrada `stdio` no tiene nada que conservar: el token protege el puerto del daemon.
    """
    if target == "claude":
        servers = _read_json(home / ".claude.json").get("mcpServers")
        entry = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
        kind = "http"
    elif target == "opencode":
        entry = opencode_mcp_installed(home)
        kind = "remote"
    elif target == "codex":
        section = _CODEX_SECTION_RE.search(_read_text(home / ".codex" / "config.toml"))
        var = codex_bearer_variable(section.group(0)) if section else None
        return f"Bearer ${{{var}}}" if var else None
    else:
        return None
    if not isinstance(entry, dict) or entry.get("type") != kind:
        return None
    value = (entry.get("headers") or {}).get("Authorization")
    return value if isinstance(value, str) and value else None


def _with_header(entry: dict, header: str | None) -> dict:
    """``entry`` con la cabecera conservada. Una entrada que no es HTTP se devuelve intacta."""
    if not header or entry.get("type") not in ("http", "remote"):
        return entry
    return {**entry, "headers": {"Authorization": header}}


# --- Los plazos que ya tenía la entrada ---------------------------------------
# `install` no escribe nunca un plazo, pero el usuario sí: con el turno del daemon una espera puede
# pasar de los 60 s con los que Codex corta, y la wiki manda subirlo en la propia entrada. Hasta la
# 0.33.0 el siguiente `install` (o `update`, que repara llamándolo) reescribía la entrada y se lo
# llevaba. Se conservan **tal cual**, con el nombre de clave de cada cliente; si no había ninguno,
# no se añade nada: ningún cliente necesita uno nuestro para funcionar.
TIMEOUT_KEYS: dict[str, tuple[str, ...]] = {
    # Claude Code: `timeout` (ms) en la entrada del servidor, que gana a `MCP_TOOL_TIMEOUT`.
    "claude": ("timeout",),
    # opencode: `timeout` (ms) en la entrada de `mcp`, para `local` y `remote`.
    "opencode": ("timeout",),
    # Codex: los dos plazos de la tabla, y la variante en ms del de arranque que también acepta.
    "codex": ("tool_timeout_sec", "startup_timeout_sec", "startup_timeout_ms"),
}
# El valor se guarda como TEXTO, sin interpretarlo: así se reescribe byte a byte lo que había
# (`900`, `1_800`, `90.5`) y no hace falta un escritor de TOML para devolverlo.
_CODEX_TIMEOUT_RE = re.compile(
    r"(?m)^[ \t]*(" + "|".join(TIMEOUT_KEYS["codex"]) + r")[ \t]*=[ \t]*([^\s#]+)"
)


def existing_timeouts(home: Path, target: str) -> dict:
    """Los plazos puestos en la entrada ya instalada en ``target``, o ``{}``.

    Para Claude Code y opencode, ``{clave: valor JSON}``; para Codex, ``{clave: texto TOML}``.
    Mira la entrada sea del modo que sea: un plazo vale igual en `stdio` que en `http`.
    """
    if target == "codex":
        section = _CODEX_SECTION_RE.search(_read_text(home / ".codex" / "config.toml"))
        return dict(_CODEX_TIMEOUT_RE.findall(section.group(0))) if section else {}
    if target == "claude":
        servers = _read_json(home / ".claude.json").get("mcpServers")
        entry = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
    elif target == "opencode":
        entry = opencode_mcp_installed(home)
    else:
        return {}
    if not isinstance(entry, dict):
        return {}
    return {k: entry[k] for k in TIMEOUT_KEYS[target] if entry.get(k) is not None}


def _describe_timeouts(timeouts: dict) -> str:
    """``tool_timeout_sec = 900, …`` para el detalle del plan y de `doctor`."""
    return ", ".join(f"{k} = {v}" for k, v in timeouts.items())


def _without_secrets(entry: dict) -> dict:
    """Copia para ENSEÑAR (el `literal` del `--dry-run`): un token escrito a pelo no se imprime.

    Se escribe tal cual en disco —ya estaba ahí—, pero la pantalla no es sitio para un secreto.
    """
    value = (entry.get("headers") or {}).get("Authorization")
    if not value or _REFERENCE_RE.match(value):
        return entry
    hidden = f"Bearer <{t('install.mcp.token_hidden')}>"
    return {**entry, "headers": {"Authorization": hidden}}


def codex_mcp_block(entry: dict, timeouts: dict | None = None) -> str:
    """Bloque TOML equivalente para `~/.codex/config.toml` (sin dependencia de un writer).

    ``timeouts`` son los plazos conservados de la entrada anterior (ver `existing_timeouts`), como
    texto TOML; van al final de la tabla, tras el `env` en línea, que es un valor y no la cierra.
    """
    lines = _codex_mcp_lines(entry)
    lines += [f"{k} = {v}" for k, v in (timeouts or {}).items()]
    return "\n".join(lines)


def _codex_mcp_lines(entry: dict) -> list[str]:
    lines = [f"[mcp_servers.{SERVER_NAME}]"]
    if entry.get("type") == "http":
        lines.append(f"url = {json.dumps(entry['url'])}")
        if entry.get("headers"):
            # Codex NO expande `${VAR}` (ver más abajo, el caso stdio), pero para `streamable_http`
            # tiene la clave exacta que hace falta: `bearer_token_env_var` toma el **nombre** de la
            # variable y la lee él. No es una preferencia de estilo — su validador rechaza de plano
            # el `bearer_token` literal en este transporte, así que escribir el secreto aquí ni
            # siquiera sería posible.
            # El nombre sale de la cabecera y no de la constante: una entrada conservada puede
            # referenciar otra variable, y reescribirla con la nuestra sería cambiar lo que iba.
            ref = _REFERENCE_RE.match(entry["headers"].get("Authorization", ""))
            var = (ref.group(1) or ref.group(2)) if ref else WEB_TOKEN_VAR
            lines.append(f"bearer_token_env_var = {json.dumps(var)}")
        return lines
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
    return lines


# Con sangría opcional delante de cada cabecera, y no es cosmético: otros programas reescriben este
# fichero a su manera. El 2026-09-22 el plugin de JetBrains añadió su servidor, indentó TODO el
# fichero dos espacios y se comió los comentarios. Con `^\[` a secas la entrada dejaba de verse:
# `doctor` la daba por ausente con Codex funcionando, e `install`/`update` añadían una segunda
# `[mcp_servers.local-delegate]` —TOML inválido, y Codex, sin poder cargar su config, se quedaba
# sin NINGÚN MCP—.
_CODEX_SECTION_RE = re.compile(
    r"(?ms)^[ \t]*\[mcp_servers\."
    + re.escape(SERVER_NAME)
    + r"(?:\.[^\]]+)?\][ \t]*\n.*?(?=^[ \t]*\[|\Z)"
)
# Las líneas de marcador, estén donde estén y con la sangría que tengan.
_CODEX_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?:" + re.escape(TOML_BEGIN) + "|" + re.escape(TOML_END) + r")[ \t]*(?:\n|\Z)"
)


def _strip_codex_mcp(text: str) -> str:
    """Quita nuestra entrada y nuestros marcadores, sin emparejar marcadores.

    Emparejar (`remove_block`) es peligroso aquí: si otro programa se come el marcador de cierre,
    el `begin` huérfano se emparejaría con el `end` del bloque que escribiéramos después, y la
    siguiente reinstalación borraría todo lo que hubiera entre los dos —las entradas de otros
    servidores, los proyectos—. El bloque gestionado es solo nuestra tabla, así que basta con
    quitarla por su nombre y borrar las líneas de marcador que queden sueltas.
    """
    text = _CODEX_SECTION_RE.sub("", text)
    return _CODEX_MARKER_RE.sub("", text)


def upsert_codex_mcp(text: str, block: str) -> str:
    """Reemplaza cualquier entrada previa de local-delegate (gestionada o a mano)."""
    text = _strip_codex_mcp(text).rstrip()
    managed = f"{TOML_BEGIN}\n{block}\n{TOML_END}"
    return (text + "\n\n" if text else "") + managed + "\n"


def remove_codex_mcp(text: str) -> str:
    return _strip_codex_mcp(text).strip() + "\n"


# --- Entrada del servidor MCP en opencode ------------------------------------
# opencode se parece a Claude Code y NO a Codex en lo único que aquí importa: la entrada se
# identifica por su **clave** (`mcp["local-delegate"]`) y no por marcadores. No es una preferencia:
# un `# local-delegate:begin` propio sería una clave de primer nivel ajena al esquema, y eso puede
# dejar al usuario sin cliente. Cuidado con la fuerza de esa afirmación, porque **depende de la
# versión**: medido el 2026-09-08 con los dos binarios a la vez, 1.18.11 rechaza una clave de
# primer nivel desconocida (`Unrecognized key`) y 1.18.29 ya la tolera. La regla se mantiene
# igualmente —escribir solo dentro de `mcp` es lo que no depende de qué versión tenga el usuario—
# y lo que NO ha cambiado es el castigo por una entrada mal formada DENTRO de `mcp`: las dos
# versiones se niegan a arrancar si le falta `type` o `command`, o si `command` no es un array.
#
# Consecuencia que conviene decir en voz alta: aquí NO se puede distinguir una entrada nuestra de
# una que escribió el usuario a mano, así que tampoco hay pregunta previa como la de
# `--force-mcp-codex`. Es exactamente lo que ya pasa con Claude Code, y por el mismo motivo: lo que
# protege el `warn` de Codex es el bloque sin marcadores, y aquí no hay marcadores que mirar.
def _scan_jsonc(text: str) -> tuple[str, bool]:
    """(texto sin comentarios, había comentarios). Una sola definición de «esto es un comentario».

    Detectar comentarios con ``"//" in texto`` es **falso** y de un modo que se dispara justo en
    nuestro caso: una entrada HTTP legítima contiene ``http://127.0.0.1:9393/mcp``, así que
    cualquier configuración con una URL quedaría marcada como comentada —y por tanto intocable—.
    Hay que recorrer el texto sabiendo cuándo se está dentro de una cadena y cuándo hay un escape.

    Los comentarios se sustituyen por espacios en vez de borrarse para que las posiciones y los
    números de línea del texto resultante sigan siendo los del original: si ``json.loads`` falla
    después, el error señala el sitio de verdad.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    had_comments = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            had_comments = True
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            had_comments = True
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            # Los saltos de línea se conservan: si no, un comentario de bloque desplazaría todas
            # las líneas siguientes y el error de parseo señalaría a otro sitio.
            out.extend("\n" if ch == "\n" else " " for ch in text[i:end])
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out), had_comments


def has_comments(text: str) -> bool:
    """True si el JSONC lleva comentarios fuera de una cadena."""
    return _scan_jsonc(text)[1]


def strip_jsonc(text: str) -> str:
    """Texto sin comentarios. **Solo para leer**: este resultado nunca se escribe a disco."""
    return _scan_jsonc(text)[0]


def opencode_config_paths(home: Path) -> tuple[Path, ...]:
    """Los ficheros de configuración global de opencode, en el orden en que él los resuelve.

    Son dos y **los lee los dos**, fusionándolos (medido): mirar solo uno daría por ausente una
    entrada que está puesta en el otro.
    """
    base = opencode_dir(home)
    return tuple(base / name for name in OPENCODE_CONFIG_NAMES)


def opencode_config_target(home: Path) -> Path:
    """A cuál de los dos se escribe. Misma regla que usa el propio `opencode mcp add` (medida).

    `opencode.json` si existe; si no, `opencode.jsonc`; y si no hay ninguno, `opencode.jsonc`, que
    es el que crea el cliente en una máquina limpia. Coincidir con él importa: si eligiéramos otro,
    una instalación por CLI y otra por fichero acabarían en sitios distintos y la segunda parecería
    no haber hecho nada.
    """
    json_path, jsonc_path = opencode_config_paths(home)
    return json_path if json_path.is_file() else jsonc_path


def read_opencode_config(path: Path) -> tuple[dict | None, str | None]:
    """(config, motivo por el que no se pudo leer). Tolera comentarios, que son legales aquí.

    Devuelve ``(None, None)`` cuando el fichero no existe —una ausencia de verdad— y
    ``(None, motivo)`` cuando existe y no se puede entender, que es ``unknown`` y nunca ``missing``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError) as exc:
        reason = getattr(exc, "strerror", None) or exc
        return None, t("install.opencode.unreadable_path", path=path, reason=reason)
    if not text.strip():
        return {}, None
    try:
        data = json.loads(strip_jsonc(text))
    except ValueError as exc:
        return None, t("install.opencode.invalid_json_path", path=path, reason=exc.msg)
    if isinstance(data, dict):
        return data, None
    return None, t("install.opencode.not_an_object_path", path=path)


def opencode_mcp_entry(
    mode: str,
    base_url: str | None,
    api_key_env: bool,
    version: str | None,
    web_token_env: bool = False,
) -> dict:
    """Entrada de servidor MCP para opencode.

    Se construye desde los mismos datos que `mcp_entry` y **no** traduciendo su salida: la
    traducción ataría la forma de un cliente a la del otro, y el próximo cambio en una rompería la
    otra en silencio. Lo que sí comparten —la URL del daemon, el comando de `uvx`, qué variables
    van al proceso— sale de las tres funciones comunes de más arriba.

    Forma medida contra opencode 1.18.11: `type` es obligatorio, `command` es **siempre un array**,
    las variables van en `environment` (no `env`), y la interpolación es `{env:VAR}` — `${VAR}` no
    se sustituye.

    **No se escribe `"enabled": true`** aunque el esquema lo acepte, y no es por brevedad: la CLI
    del propio cliente no lo escribe (medido), así que ponerlo haría que los dos caminos —CLI y
    fichero— dejaran formas distintas, y sobre todo que el `literal` del `--dry-run` prometiera una
    clave que luego no aparece. `enabled` sirve para **desactivar** (`false`); en `true` es el
    default y no dice nada.
    """
    if mode == "http":
        entry: dict = {"type": "remote", "url": daemon_mcp_url()}
        if web_token_env:
            entry["headers"] = {"Authorization": f"Bearer {{env:{WEB_TOKEN_VAR}}}"}
        return entry
    entry = {"type": "local", "command": uvx_command(version)}
    env = stdio_env(base_url, api_key_env, "{env:LOCAL_DELEGATE_API_KEY}")
    if env:
        entry["environment"] = env
    return entry


def opencode_mcp_add_args(entry: dict) -> list[str]:
    """Argumentos de `opencode mcp add` que producen ``entry``.

    Existe aparte para poder probarla sin ejecutar el binario: es la traducción entre la forma que
    escribimos nosotros y la que entiende la CLI del cliente, y es donde se colaría un `--env` mal
    puesto sin que ningún test lo viera.
    """
    args = ["mcp", "add", SERVER_NAME]
    if entry.get("type") == "remote":
        args += ["--url", str(entry["url"])]
        for name, value in (entry.get("headers") or {}).items():
            args += ["--header", f"{name}={value}"]
        return args
    for name, value in (entry.get("environment") or {}).items():
        args += ["--env", f"{name}={value}"]
    # El comando va tras `--`, y no como valor de una opción: así lo pide la CLI (medido).
    return args + ["--", *entry.get("command", [])]


# --- Plan de instalación -----------------------------------------------------
@dataclass
class Options:
    home: Path
    components: set[str]  # hooks | skill | memory | mcp
    targets: set[str]  # claude | codex | opencode
    python_exe: str
    enable_read_hook: bool = False
    mcp_mode: str = "stdio"
    base_url: str | None = None
    api_key_env: bool = False
    # Solo tiene efecto con `mcp_mode="http"`: es el puerto del daemon el que puede exigir token.
    # Tres estados: True la escribe, False la quita y None conserva la que ya tuviera cada cliente.
    web_token_env: bool | None = None
    pin_version: str | None = None
    use_cli: bool = True
    # Suprime SOLO la escritura de la entrada MCP de Codex. Lo decide quien llama (el CLI, tras
    # ver el check `scaffold.mcp_codex` en `warn` y preguntar), y se pasa como dato en vez de
    # filtrar la lista de acciones por su `kind`: un filtro por string desde fuera sería frágil
    # y, sobre todo, mudo — nadie sabría por qué falta esa acción.
    skip_codex_mcp: bool = False
    # REQ-047: `install` guarda en `language.json` el idioma de la sesión en la que corre. `update`
    # lo pone a False en las llamadas por reparación y escribe la preferencia una sola vez.
    write_language: bool = True
    # Dónde vive `language.json`; `None` = el que diga `language_dir` (ver allí).
    data_dir: Path | None = None
    # La regla del idioma, inyectable para los tests: recibe el directorio de datos y devuelve la
    # resolución de REQ-018. `None` = `hook_common.resolve_language` con el entorno del proceso.
    language_probe: Callable[[Path], hook_common.LanguageResolution] | None = None
    # REQ-016: con Claude en el plan, `install` migra antes los nombres retirados. `update` lo pone
    # a False en las llamadas por reparación: él migra una sola vez, como primer paso (REQ-014).
    migrate_retired_names: bool = True
    # REQ-005 (SDD claude-plugin-and-mods): `--claude-delivery plugin|settings`; `None` lets
    # `claude_plugin.decide` choose, which is the plugin whenever its conditions hold.
    claude_delivery: str | None = None
    # `--disable-read-hook`: with `uninstall`, the only way to turn the active layer off.
    disable_read_hook: bool = False
    # `--desktop` (REQ-012): the Claude Desktop chat entry, pointing at `desktop-bridge`.
    desktop: bool = False
    # Injectable for the tests: the `claude` runner and lookup, and an `ld_bin` already resolved.
    # `None` means the real ones (`claude_plugin.run_subprocess`, `shutil.which`, the `uv tool`
    # environment that is running).
    claude_runner: Callable | None = None
    claude_which: Callable[[str], str | None] | None = None
    claude_ld_bin: object | None = None
    # Where Claude Desktop keeps its config (`<dir>/Claude/claude_desktop_config.json`) and the
    # executable its entry runs. `None`: `%APPDATA%` (a simulated HOME uses its own) and the
    # `local-delegate` next to the running interpreter.
    desktop_dir: Path | None = None
    desktop_executable: Path | None = None
    # `sys.platform`, unless a test says otherwise.
    platform: str | None = None


# --- La preferencia de idioma (REQ-047, D11) ----------------------------------
#: Orígenes que `install`/`update` pueden pisar al escribir el del sistema. «Variable» es una
#: elección explícita y no se pisa nunca; un fichero sin origen, por si acaso, tampoco.
_OVERWRITABLE_SOURCES = frozenset({"system", "fallback"})


@dataclass(frozen=True)
class LanguagePlan:
    """Qué hace `install`/`update` con el idioma: cuál vale y qué se escribe.

    ``lang`` es el idioma vigente **después** de escribir: el de la skill, los bloques y el
    catálogo de los subagentes. ``write`` es lo que se escribirá en ``path`` (`None` si no se
    toca), y ``reason`` un código de máquina de por qué (`written`, `unchanged`, `explicit_kept`,
    `fallback`, `no_data_dir`).
    """

    lang: str
    path: Path | None
    write: dict | None
    reason: str
    stored: dict | None = None


def data_dir_for(home: Path, data_dir: Path | None = None) -> Path | None:
    """El directorio de datos del instalador para `home`, o `None` si no se debe tocar.

    `data_dir` si se da; si no, `config.LOG_DIR`, el mismo que leen el CLI, el servidor y los hooks
    (REQ-047). Con un HOME simulado no se toca, porque el directorio de datos no vive en el HOME y
    `--home` es un sandbox: solo vale si además se eligió con `LOCAL_DELEGATE_LOG_DIR`. Lo usan
    `language.json` y el registro de la migración de nombres retirados (REQ-015).
    """
    if data_dir is not None:
        return data_dir
    if is_simulated_home(home) and not os.environ.get("LOCAL_DELEGATE_LOG_DIR", "").strip():
        return None
    return Path(config.LOG_DIR)


def language_dir(opts: Options) -> Path | None:
    """El directorio de datos donde va `language.json`, o `None` si no se debe tocar."""
    return data_dir_for(opts.home, opts.data_dir)


def _stored_preference(path: Path) -> dict | None:
    """``{"lang", "source"}`` de un `language.json` válido, o `None` si falta o no vale."""
    data = _read_json(path)
    lang = data.get("lang")
    parsed = hook_common.parse_language(lang) if isinstance(lang, str) else None
    if parsed is None:
        return None
    return {"lang": parsed, "source": data.get("source")}


def plan_language(opts: Options) -> LanguagePlan:
    """Aplica la regla de escritura de REQ-047 sin tocar el disco.

    El idioma de la sesión se resuelve con los pasos 1, 3 y 4 de REQ-018 (variable, sistema y
    reserva), **sin** leer la preferencia vieja: se le pasa a la regla un directorio vacío.
    """
    probe = opts.language_probe or hook_common.resolve_language
    with tempfile.TemporaryDirectory() as empty:
        session = probe(Path(empty))
    data_dir = language_dir(opts)
    if data_dir is None:
        return LanguagePlan(session.lang, None, None, "no_data_dir")
    path = data_dir / hook_common.LANGUAGE_PREFERENCE_FILE
    stored = _stored_preference(path)

    write = None
    if session.source == "variable":
        write = {"lang": session.lang, "source": "variable"}
    elif session.source == "system" and (
        stored is None or stored["source"] in _OVERWRITABLE_SOURCES
    ):
        write = {"lang": session.lang, "source": "system"}

    if write is not None and write == stored:
        return LanguagePlan(write["lang"], path, None, "unchanged", stored)
    if write is not None:
        return LanguagePlan(write["lang"], path, write, "written", stored)
    if stored is not None:
        reason = "fallback" if session.source == "fallback" else "explicit_kept"
        return LanguagePlan(stored["lang"], path, None, reason, stored)
    # Reserva y sin preferencia: el idioma vigente es el de la reserva, y el fichero no se toca.
    return LanguagePlan(session.lang, path, None, "fallback", stored)


def language_action(plan: LanguagePlan) -> Action | None:
    """La acción que escribe `language.json`, o la que dice por qué no se toca."""
    if plan.path is None:
        return None
    if plan.write is None:
        if plan.reason == "explicit_kept":
            detail = t("install.language.explicit_kept", lang=plan.lang, path=plan.path)
        elif plan.reason == "unchanged":
            detail = t("install.language.unchanged", lang=plan.lang)
        else:
            detail = t("install.language.fallback")
        return Action("language", plan.path, detail)
    source = t(f"common.language.source.{plan.write['source']}")
    detail = t("install.language.write_plan", lang=plan.lang, source=source)
    content = json.dumps(plan.write, ensure_ascii=False)

    def _run(path=plan.path, content=content) -> str:
        # Sin `.bak`: es configuración del instalador, no un fichero del usuario.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + "\n", encoding="utf-8")
        return t("install.language.written", path=path)

    return Action("language", plan.path, detail, _run, literal=content)


# --- Migración de nombres retirados con sucesor (REQ-015, REQ-016, REQ-017) ---------------
#: Registro de la migración, en el directorio de datos: una fecha UTC por nombre viejo y ningún
#: valor (`{"names": {"<viejo>": "<ts>"}}`). Lo lee `doctor` para no pedir «renombra» por eventos
#: de telemetría anteriores a la migración (REQ-012).
RETIRED_NAMES_MIGRATION_FILE = "retired-names-migration.json"
#: Base de la copia propia de `settings.json` antes de migrar su `env`. No es la `.bak` genérica:
#: esa la pisaría la siguiente escritura de la misma corrida (la reparación de hooks).
RETIRED_NAMES_BACKUP = "settings.json.retired-names"


def retired_names_with_successor(surface: str) -> tuple[deprecations.DeprecatedName, ...]:
    """Retirados con sucesor cuya superficie efectiva es `surface` (`env_var` o `switch_file`).

    Solo estos se migran: un alias vigente aún funciona y no se toca (desviación 10).
    """
    return tuple(
        e
        for e in deprecations.DEPRECATED_NAMES
        if e.is_retired and e.new is not None and deprecations.effective_kind(e) == surface
    )


def read_migration_record(directory: Path | None) -> dict[str, datetime]:
    """Fecha de migración de cada nombre viejo; vacío sin directorio, sin registro o ilegible."""
    if directory is None:
        return {}
    names = _read_json(directory / RETIRED_NAMES_MIGRATION_FILE).get("names")
    if not isinstance(names, dict):
        return {}
    record: dict[str, datetime] = {}
    for old, stamp in names.items():
        try:
            when = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        record[old] = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
    return record


def _record_migration(directory: Path | None, names: Sequence[str]) -> str:
    """Fusiona en el registro la fecha de ahora para `names`; devuelve la línea que lo cuenta."""
    if directory is None:
        return t("install.migrate.record_skipped")
    path = directory / RETIRED_NAMES_MIGRATION_FILE
    stored = _read_json(path).get("names")
    merged = dict(stored) if isinstance(stored, dict) else {}
    now = datetime.now(UTC).isoformat()
    merged.update(dict.fromkeys(names, now))
    payload = json.dumps({"names": merged}, ensure_ascii=False, indent=2) + "\n"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload.encode("utf-8"))
    except OSError as exc:
        return t("install.migrate.record_failed", path=path, reason=exc.strerror or exc)
    return t("install.migrate.record_written", path=path)


def _read_settings_for_migration(path: Path) -> tuple[dict | None, bytes, str | None]:
    """`(datos, bytes, motivo)` de `settings.json` para migrar su `env`.

    Sin fichero: `(None, b"", None)`. Si no se puede migrar (no se lee, no es UTF-8, no es JSON,
    no es un objeto o su `env` no es un objeto): `(None, bytes, motivo)`. Lee con `utf-8-sig`, así
    que un fichero con BOM (PowerShell 5.1 con `-Encoding UTF8`) se migra igual.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, b"", None
    except OSError as exc:
        return None, b"", str(exc.strerror or exc)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, raw, t("install.migrate.reason.not_utf8")
    try:
        data = json.loads(text)
    except ValueError:
        return None, raw, t("install.migrate.reason.not_json")
    if not isinstance(data, dict):
        return None, raw, t("install.migrate.reason.not_object")
    if "env" in data and not isinstance(data["env"], dict):
        return None, raw, t("install.migrate.reason.env_not_object")
    return data, raw, None


def _migrated_env(env: dict) -> tuple[dict, list[deprecations.DeprecatedName]]:
    """El `env` con los retirados migrados y cuáles se migraron.

    Viejo solo: la clave pasa a llamarse como el nuevo, mismo valor y misma posición. Los dos: se
    quita el viejo, que ya perdía frente al nuevo.
    """
    moved = [e for e in retired_names_with_successor("env_var") if e.old in env]
    result = dict(env)
    for entry in moved:
        if entry.new in result:
            del result[entry.old]
        else:
            result = {(entry.new if k == entry.old else k): v for k, v in result.items()}
    return result, moved


def _switch_to_migrate(claude: Path, entry: deprecations.DeprecatedName) -> bool:
    """¿El interruptor viejo es un fichero normal? Un directorio o un enlace no se tocan."""
    old = claude / entry.old
    return old.is_file() and not old.is_symlink()


def retired_names_to_migrate(home: Path) -> tuple[deprecations.DeprecatedName, ...]:
    """Los retirados que la migración cubre en `<home>/.claude/`: `env` de `settings.json` e
    interruptores. Solo lee. `update` lo usa para quitar de sus notas el «renombra» de lo migrado.
    """
    claude = home / ".claude"
    data, _raw, _reason = _read_settings_for_migration(claude / "settings.json")
    env = data.get("env") if data else None
    in_env = _migrated_env(env)[1] if isinstance(env, dict) else []
    switches = [
        e for e in retired_names_with_successor("switch_file") if _switch_to_migrate(claude, e)
    ]
    return (*in_env, *switches)


def _names(entries: Sequence[deprecations.DeprecatedName]) -> str:
    """`VIEJO -> NUEVO, …`: solo nombres, nunca valores (el `env` puede llevar claves, REQ-017).

    Flecha ASCII a propósito: con la salida redirigida en Windows (cp1252) una «→» no se puede
    escribir, y esta línea la imprime `update` lanzado por un script (REQ-028).
    """
    return ", ".join(f"{e.old} -> {e.new}" for e in entries)


def _retired_names_backup(path: Path, raw: bytes, stamp: str) -> Path:
    """Copia `raw` a la primera copia libre, sin pisar nunca otra (REQ-015).

    `settings.json.retired-names.bak`; si existe, `….<stamp>.bak` (UTC); y si también, con sufijo
    de desempate `-1`, `-2`… Apertura exclusiva (`xb`): ni dos corridas en el mismo segundo se
    pisan. La copia conserva los permisos del original.
    """
    attempt = 0
    while True:
        if attempt == 0:
            name = f"{RETIRED_NAMES_BACKUP}.bak"
        elif attempt == 1:
            name = f"{RETIRED_NAMES_BACKUP}.{stamp}.bak"
        else:
            name = f"{RETIRED_NAMES_BACKUP}.{stamp}-{attempt - 1}.bak"
        attempt += 1
        candidate = path.with_name(name)
        try:
            with candidate.open("xb") as handle:
                handle.write(raw)
        except FileExistsError:
            continue
        shutil.copymode(path, candidate)
        return candidate


def _write_migrated_settings(path: Path, raw: bytes, data: dict) -> Path:
    """Copia propia y luego `settings.json` de una vez, con su fin de línea y su BOM."""
    backup = _retired_names_backup(path, raw, datetime.now(UTC).strftime("%Y%m%d%H%M%S"))
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    payload = text.replace("\n", newline).encode("utf-8")
    if raw.startswith(codecs.BOM_UTF8):
        payload = codecs.BOM_UTF8 + payload
    path.write_bytes(payload)
    return backup


def _run_env_migration(path: Path, directory: Path | None) -> str:
    """Migra el `env` **releyendo** `settings.json` al aplicar, como `_run_settings`: así se
    combina con cualquier otra escritura de la corrida (B1 de la revisión de la spec)."""
    data, raw, reason = _read_settings_for_migration(path)
    if reason is not None:
        return t("install.migrate.settings_unreadable", reason=reason)
    env = data.get("env") if data else None
    migrated, moved = _migrated_env(env) if isinstance(env, dict) else ({}, [])
    if not moved:
        return t("install.migrate.nothing")
    data["env"] = migrated
    backup = _write_migrated_settings(path, raw, data)
    done = t("install.migrate.settings_done", names=_names(moved), backup=backup)
    return f"{done}; {_record_migration(directory, [e.old for e in moved])}"


def _run_switch_migration(
    claude: Path, entry: deprecations.DeprecatedName, directory: Path | None
) -> str:
    old, new = claude / entry.old, claude / entry.new
    if not _switch_to_migrate(claude, entry):
        return t("install.migrate.nothing")
    if new.exists() or new.is_symlink():
        old.unlink()
        done = t("install.migrate.switch_removed", old=entry.old, new=entry.new)
    else:
        old.rename(new)
        done = t("install.migrate.switch_renamed", old=entry.old, new=entry.new)
    return f"{done}; {_record_migration(directory, [entry.old])}"


def plan_retired_name_migration(home: Path, data_dir: Path | None = None) -> list[Action]:
    """Acciones `migrate` que pasan los retirados con sucesor a su nombre nuevo (REQ-015).

    Mira **solo** `<home>/.claude/settings.json` (su `env`) y los interruptores de `<home>/.claude/`:
    nunca el entorno del proceso, perfiles, el lanzador del daemon, `settings.local.json`,
    `~/.claude.json` ni `~/.codex` (REQ-017). Todas las claves de `env` van en **una** acción, que
    relee el fichero al aplicarse; cada interruptor, en la suya. El registro de la migración va al
    directorio de datos de `data_dir_for(home, data_dir)`: con HOME simulado y sin
    `LOCAL_DELEGATE_LOG_DIR` no hay ninguno y no se escribe (lo dice la salida). Solo lee: escribe
    `apply`, y en `--dry-run` nada.
    """
    claude = home / ".claude"
    directory = data_dir_for(home, data_dir)
    actions: list[Action] = []
    settings_path = claude / "settings.json"
    data, _raw, reason = _read_settings_for_migration(settings_path)
    if reason is not None:
        # Sin `run`: no escribe nada en él, solo lo dice (REQ-016).
        detail = t("install.migrate.settings_unreadable", reason=reason)
        actions.append(Action("migrate", settings_path, detail))
    elif data is not None and isinstance(data.get("env"), dict):
        _env, moved = _migrated_env(data["env"])
        if moved:
            names = _names(moved)

            def _run_env(path=settings_path, directory=directory) -> str:
                return _run_env_migration(path, directory)

            detail = t("install.migrate.settings_plan", names=names)
            actions.append(Action("migrate", settings_path, detail, _run_env, literal=names))
    for entry in retired_names_with_successor("switch_file"):
        if not _switch_to_migrate(claude, entry):
            continue
        new = claude / entry.new
        key = "switch_remove_plan" if new.exists() or new.is_symlink() else "switch_rename_plan"

        def _run_switch(entry=entry, directory=directory) -> str:
            return _run_switch_migration(claude, entry, directory)

        detail = t(f"install.migrate.{key}", old=entry.old, new=entry.new)
        actions.append(
            Action("migrate", claude / entry.old, detail, _run_switch, literal=_names([entry]))
        )
    return actions


def _claude_dir(opts: Options) -> Path:
    return opts.home / ".claude"


def _codex_dir(opts: Options) -> Path:
    return opts.home / ".codex"


def packaged_hook_names() -> set[str]:
    """Nombres de los scripts de hooks que este paquete instala **o instaló alguna vez**.

    Es la definición de «qué es nuestro» dentro de `~/.claude/hooks/`, y por tanto de qué se puede
    retirar. Lo que se empaqueta hoy sale del directorio y no de una constante escrita a mano,
    porque una constante paralela se desincroniza: `_SCRIPT_NAMES` **no** incluye
    `hook_common.py`, que es uno de los huérfanos reales que hay que limpiar.

    Y a eso se le suman los **retirados**, que no están en el directorio precisamente por estar
    retirados. Sin ellos, dejar de empaquetar un script haría que su copia vieja no fuera
    reconocible por nadie y se quedara en el disco del usuario para siempre.

    Si el directorio no se puede listar devuelve vacío, y con vacío no se borra nada: la
    degradación segura de una operación destructiva es no hacer nada.
    """
    try:
        packaged = {p.name for p in (resources_dir() / "hooks").iterdir() if p.suffix == ".py"}
    except OSError:
        return set()
    return packaged | set(_RETIRED_SCRIPTS)


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


def retired_skill_dirs(skills_root: Path) -> list[Path]:
    """Skills retiradas presentes en ``skills_root``, buscadas por su nombre exacto.

    No se lista el directorio: se pregunta por cada nombre de `_RETIRED_SKILLS`. Así es imposible
    que una skill ajena entre en la lista por parecido o por estar ahí.
    """
    return [skills_root / name for name in _RETIRED_SKILLS if (skills_root / name).is_dir()]


def _retire_skills_action(skills_root: Path) -> Action:
    def _run() -> str:
        removed, failed = [], []
        for path in retired_skill_dirs(skills_root):
            try:
                shutil.rmtree(path)
                removed.append(path.name)
            except OSError as exc:
                # Igual que con los hooks huérfanos: lo que no se deja borrar se dice y se sigue.
                failed.append(_failure(path.name, exc))
        if removed:
            detail = t("install.skill.retired", n=len(removed), names=", ".join(removed))
        else:
            detail = t("install.nothing_to_retire")
        return detail + _not_removed(failed)

    names = ", ".join(p.name for p in retired_skill_dirs(skills_root))
    return Action("prune", skills_root, t("install.skill.retire_plan", names=names), _run)


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
                failed.append(_failure(path.name, exc))
        if removed:
            detail = t("install.hooks.retired", n=len(removed), names=", ".join(removed))
        else:
            detail = t("install.nothing_to_retire")
        return detail + _not_removed(failed)

    return Action("prune", root, t("install.hooks.retire_plan"), _run)


def _agent_summary(path: Path, added: list[str], action: str | None) -> str:
    """``nombre (+N tools, catálogo insertado)`` de un subagente que cambia."""
    if action:
        return t(
            "install.agents.item_with_catalog",
            name=path.name,
            n=len(added),
            action=t(f"install.agents.catalog_action.{action}"),
        )
    return t("install.agents.item", name=path.name, n=len(added))


def _agents_action(agents_dir: Path, changes: list, opts: Options | None = None) -> Action:
    """Escribe los subagentes que cambian. `cambios` viene de `agents.pending()`, que solo lee.

    With ``opts``, what was written is recorded in the installation state (REQ-011), so that
    ``uninstall`` can undo exactly that and nothing else.
    """
    summary = ", ".join(
        _agent_summary(path, added, action) for path, _text, added, action in changes
    )

    def _run() -> str:
        written, failed, record = [], [], {}
        for path, text, added, action in changes:
            try:
                # `_write_text` deja `.bak` y conserva el terminador de línea del fichero: en
                # Windows, escribir con el de la plataforma marcaría el agente entero como
                # modificado por haberle añadido una línea.
                _write_text(path, text)
                written.append(path.name)
                record[path.name] = {"added": list(added), "block": action}
            except OSError as exc:
                failed.append(_failure(path.name, exc))
        if opts is not None and record:
            _record_agents(opts, agents_dir, record)
        detail = t("install.agents.updated", n=len(written), names=", ".join(written))
        return detail + _not_written(failed)

    plan = t("install.agents.update_plan", n=len(changes), summary=summary)
    return Action("agents", agents_dir, plan, _run)


def _record_agents(opts: Options, agents_dir: Path, record: dict) -> None:
    """Adds to the state's `agents` piece what this run wrote, file by file (REQ-011).

    Merged with what earlier runs wrote: the tools added now join the ones added before, and a
    block counts as ours if any run inserted it.
    """
    install_state = _sibling("install_state")

    state = install_state.load(opts.home, opts.data_dir)
    previous = (install_state.piece(state, "agents") or {}).get("files") or {}
    files = {name: dict(entry) for name, entry in previous.items() if isinstance(entry, dict)}
    for name, entry in record.items():
        merged = files.setdefault(name, {"added": [], "block": None})
        merged["added"] = sorted(set(merged.get("added") or []) | set(entry["added"]))
        if entry["block"] == "inserted" or merged.get("block") == "inserted":
            merged["block"] = "inserted"
        else:
            merged["block"] = merged.get("block") or entry["block"]
    base = state or install_state.new_state("settings", "")
    install_state.save(
        opts.home,
        install_state.with_piece(base, "agents", dir=str(agents_dir), files=files),
        opts.data_dir,
    )


def _revert_agents_action(opts: Options, agents_dir: Path, piece: dict) -> Action:
    """Undoes what `install --agents` wrote, as the state records it, and nothing else."""
    from . import agents as agents_mod

    install_state = _sibling("install_state")

    files = piece.get("files") or {}

    def _run() -> str:
        restored_names, failed = [], []
        for name, entry in files.items():
            path = agents_dir / name
            if not path.is_file():
                continue
            try:
                current = _read_text_for_rewrite(path)
                restored = agents_mod.revert(
                    current,
                    entry.get("added") or [],
                    remove_block=entry.get("block") == "inserted",
                )
                if restored != current:
                    _write_text(path, restored)
                    restored_names.append(name)
            except OSError as exc:
                failed.append(_failure(name, exc))
            except UnreadableConfigError as exc:
                failed.append(f"{name} ({exc})")
        state = install_state.load(opts.home, opts.data_dir)
        if state is not None:
            install_state.save(
                opts.home, install_state.without_piece(state, "agents"), opts.data_dir
            )
        detail = t(
            "plugin_install.agents.restored", n=len(restored_names), names=", ".join(restored_names)
        )
        return detail + _not_written(failed)

    return Action("agents", agents_dir, t("plugin_install.agents.revert_plan", n=len(files)), _run)


def _copy_tree_action(src: Path, dst: Path, detail: str) -> Action:
    def _run() -> str:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return t("install.copied", path=dst)

    return Action("copy", dst, detail, _run)


#: Las variantes por idioma de la skill (`SKILL.en.md`): no se copian, se elige una (REQ-029).
_LOCALIZED_VARIANTS = tuple(
    f"*.{lang}.md" for lang in i18n.LANGUAGES if lang != i18n.CATALOG_FALLBACK
)


def _copy_skill_action(dst: Path, lang: str, detail: str) -> Action:
    """Copia la skill con su `SKILL.md` en ``lang`` y sin las variantes de los otros idiomas."""
    src = resources_dir() / "skills" / SKILL_NAME

    def _run() -> str:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*_LOCALIZED_VARIANTS))
        (dst / "SKILL.md").write_bytes(skill_source(lang).read_bytes())
        return t("install.copied", path=dst)

    return Action("copy", dst, detail, _run)


# --- Claude Code delivery: plugin or settings (SDD claude-plugin-and-mods, F1-install) --------
#
# `install` does not repeat a single step of the migration: it decides the delivery with
# `claude_plugin.decide` and carries it out with `plugin_migration` (REQ-005, REQ-006, REQ-008 b).
# Both modules import this one, so they are imported where they are used.


def claude_delivery_decision(opts: Options):
    """REQ-005: which delivery Claude Code gets. A `claude` that cannot even be asked → settings."""
    claude_plugin = _sibling("claude_plugin")

    runner = opts.claude_runner or claude_plugin.run_subprocess
    which = opts.claude_which or shutil.which
    try:
        return claude_plugin.decide(
            opts.home,
            requested=opts.claude_delivery,
            runner=runner,
            which=which,
            platform=opts.platform,
            ld_bin=opts.claude_ld_bin,  # type: ignore[arg-type]
        )
    except Exception as exc:  # the probe itself failed: settings, saying why, never a crash
        detail = t("plugin.fallback.version_unknown", output=str(exc)[:120])
        return claude_plugin.Decision(
            claude_plugin.SETTINGS,
            reason="version_unknown",
            warning=t("plugin.fallback.lead", detail=detail),
        )


def _settings_hook_entries(hooks_dst: Path, python_exe: str, read_hook: bool) -> list:
    """`(event, matcher, command)` of the settings delivery; the read trio only when it is on."""
    entries = [
        (event, matcher, hook_command(hooks_dst, script, python_exe))
        for script, event, matcher in _HOOK_EVENTS
    ]
    if read_hook:
        for script, event, matcher in (_READ_HOOK, _MCP_READ_HOOK, _SHELL_HOOK):
            command = hook_command(hooks_dst, script, python_exe, (READ_HOOK_FLAG,))
            entries.append((event, matcher, command))
    return entries


def _register_settings_hooks(claude: Path, entries: list) -> str:
    hooks_dst = claude / "hooks" / HOOKS_SUBDIR
    path = claude / "settings.json"
    data, removed = merge_hook_settings(_read_config_json(path), entries, hooks_dst)
    _write_json(path, data)
    note = t("install.hooks.previous_removed", n=removed) if removed else ""
    return t("install.hooks.registered", n=len(entries), note=note)


def _settings_hook_actions(opts: Options, claude: Path, warning: str | None) -> list[Action]:
    """The settings delivery as it was until 0.39: scripts copied and entries in settings.json."""
    actions: list[Action] = []
    hooks_dst = claude / "hooks" / HOOKS_SUBDIR
    actions.append(
        _copy_tree_action(resources_dir() / "hooks", hooks_dst, t("install.hooks.copy_plan"))
    )
    # Solo si hay algo que retirar: sin esto, reinstalar sobre una máquina limpia emitiría
    # una acción que no hace nada y el plan mentiría sobre lo que va a pasar.
    if orphan_hook_scripts(claude):
        actions.append(_prune_orphans_action(claude))
    read_hook = opts.enable_read_hook and not opts.disable_read_hook
    entries = _settings_hook_entries(hooks_dst, opts.python_exe, read_hook)
    detail = t(
        "install.hooks.register_plan",
        n=len(entries),
        events=", ".join(f"{e}{'/' + m if m else ''}" for e, m, _c in entries),
    )
    if warning:
        detail = f"{detail}\n    {warning}"
    actions.append(
        Action(
            "settings",
            claude / "settings.json",
            detail,
            lambda claude=claude, entries=entries: _register_settings_hooks(claude, entries),
            literal="\n".join(
                f"{e}{'/' + m if m else ''}: {json.dumps(c, ensure_ascii=False)}"
                for e, m, c in entries
            ),
        )
    )
    return actions


def _plugin_delivery_action(opts: Options, decision, lang: str) -> Action:
    """REQ-005/006: the plugin in, the settings delivery out, through `apply_plugin_delivery`."""
    claude_plugin = _sibling("claude_plugin")
    plugin_migration = _sibling("plugin_migration")
    from .version import get_version

    version = get_version()
    runner = opts.claude_runner or claude_plugin.run_subprocess

    def _run() -> str:
        result = plugin_migration.apply_plugin_delivery(
            opts.home,
            claude_bin=decision.claude_bin,
            ld_bin=decision.ld_bin,
            language=lang,
            version=version,
            runner=runner,
            env=decision.env,
            data_dir=opts.data_dir,
        )
        text = "\n    ".join(result.messages)
        if not result.ok:
            raise RuntimeError(text or t("plugin_install.failed", step=result.failed_step))
        return text

    detail = t(
        "plugin_install.plan",
        plugin=claude_plugin.PLUGIN_ID,
        version=version,
        claude=decision.version or "?",
    )
    literal = "\n".join(claude_plugin.dry_run_lines(decision, language=lang))
    return Action("plugin", "claude", detail, _run, literal=literal)


def _revert_to_settings_action(opts: Options, claude: Path) -> Action:
    """REQ-008 b: `--claude-delivery settings` with the plugin in: out with it, settings back."""
    claude_plugin = _sibling("claude_plugin")
    plugin_migration = _sibling("plugin_migration")

    runner = opts.claude_runner or claude_plugin.run_subprocess
    which = opts.claude_which or shutil.which

    def _restore(read_hook_enabled: bool) -> None:
        hooks_dst = claude / "hooks" / HOOKS_SUBDIR
        if hooks_dst.exists():
            shutil.rmtree(hooks_dst)
        shutil.copytree(resources_dir() / "hooks", hooks_dst)
        read_hook = (read_hook_enabled or opts.enable_read_hook) and not opts.disable_read_hook
        _register_settings_hooks(
            claude, _settings_hook_entries(hooks_dst, opts.python_exe, read_hook)
        )

    def _run() -> str:
        claude_bin = which("claude")
        if not claude_bin:
            raise RuntimeError(t("plugin_install.revert_without_cli"))
        result = plugin_migration.revert_to_settings(
            opts.home,
            claude_bin=claude_bin,
            restore_settings=_restore,
            runner=runner,
            env=claude_plugin.child_env(opts.home),
            data_dir=opts.data_dir,
        )
        text = "\n    ".join(result.messages)
        if not result.ok:
            raise RuntimeError(text or t("plugin_install.failed", step=result.failed_step))
        return text

    return Action("plugin", "claude", t("plugin_install.revert_plan"), _run)


def _installation_state(opts: Options) -> dict | None:
    install_state = _sibling("install_state")

    return install_state.load(opts.home, opts.data_dir)


def _record_delivery_choice(opts: Options) -> None:
    """Marks (``--claude-delivery settings``) or unmarks (anything else) the choice in the state.

    Without the mark, `update` migrates a settings install that meets REQ-005 (REQ-008 a), and the
    way back to settings would only last until the next `update`. Without a state and without a
    choice to record, nothing is written: that is the old install REQ-008 a migrates.
    """
    claude_plugin = _sibling("claude_plugin")
    install_state = _sibling("install_state")
    from .version import get_version

    explicit = opts.claude_delivery == claude_plugin.SETTINGS
    state = install_state.load(opts.home, opts.data_dir)
    if state is None and not explicit:
        return
    base = state or install_state.new_state(claude_plugin.SETTINGS, get_version())
    if explicit:
        base = {**base, "claude_delivery": claude_plugin.SETTINGS}
    new = install_state.with_delivery_explicit(base, explicit)
    if new != state:
        install_state.save(opts.home, new, opts.data_dir)


def _with_delivery_choice(opts: Options, action: Action) -> Action:
    """``action`` that, once it has run, records whether the delivery was chosen by hand."""
    inner = action.run

    def _run() -> str | None:
        result = inner() if callable(inner) else None
        _record_delivery_choice(opts)
        return result

    return replace(action, run=_run)


def _claude_hook_actions(opts: Options, claude: Path, lang: str) -> list[Action]:
    """The hooks of Claude Code by the delivery `decide` chose, and the read switch after them."""
    claude_plugin = _sibling("claude_plugin")
    install_state = _sibling("install_state")

    decision = claude_delivery_decision(opts)
    plugin_now = install_state.delivery(_installation_state(opts)) == claude_plugin.PLUGIN
    actions: list[Action] = []
    if decision.delivery == claude_plugin.PLUGIN:
        actions.append(_plugin_delivery_action(opts, decision, lang))
    elif plugin_now and opts.claude_delivery == claude_plugin.SETTINGS:
        actions.append(_revert_to_settings_action(opts, claude))
    elif plugin_now:
        # The plugin stays (no CLI to remove it with, or an old one): registering settings on
        # top of it would duplicate every hook (REQ-006). Say it and leave both as they are.
        actions.append(
            Action(
                "plugin",
                "claude",
                t("plugin_install.kept", warning=decision.warning or ""),
                lambda: t("plugin_install.kept_done"),
            )
        )
    else:
        actions.extend(_settings_hook_actions(opts, claude, decision.warning))
    actions[-1] = _with_delivery_choice(opts, actions[-1])
    if opts.enable_read_hook or opts.disable_read_hook:
        action = _read_switch_action(opts, active=not opts.disable_read_hook)
        if action is not None:
            actions.append(action)
    return actions


def write_read_switch(home: Path, data_dir: Path | None, active: bool) -> Path | None:
    """`read-hook.json` (`{"active", "since"}`); `since` only moves when the value changes."""
    install_state = _sibling("install_state")
    plugin_migration = _sibling("plugin_migration")

    target = plugin_migration.read_switch_path(home, data_dir)
    if target is None:
        return None
    previous = plugin_migration._switch_active(target) if target.exists() else None
    since = None
    if previous is active:
        with contextlib.suppress(OSError, ValueError, AttributeError):
            since = json.loads(target.read_text(encoding="utf-8-sig")).get("since")
    install_state.write_json_atomic(
        target, {"active": active, "since": since or install_state.now_iso()}
    )
    return target


def _read_switch_action(opts: Options, *, active: bool) -> Action | None:
    """The active layer of the read hook (REQ-004): `--enable-read-hook` / `--disable-read-hook`."""
    plugin_migration = _sibling("plugin_migration")

    target = plugin_migration.read_switch_path(opts.home, opts.data_dir)
    if target is None:
        return None
    key = "plugin_install.read_switch.on" if active else "plugin_install.read_switch.off"

    def _run() -> str:
        write_read_switch(opts.home, opts.data_dir, active)
        return t(key)

    return Action("switch", target, t(f"{key}_plan"), _run)


# --- Claude Desktop chat entry (REQ-012) ----------------------------------------------------
def desktop_executable(opts: Options) -> Path:
    """The `local-delegate` of the environment that is running: what the Desktop entry runs."""
    if opts.desktop_executable is not None:
        return Path(opts.desktop_executable)
    import sysconfig

    name = "local-delegate.exe" if (opts.platform or sys.platform) == "win32" else "local-delegate"
    return Path(sysconfig.get_path("scripts")) / name


def desktop_config_path(opts: Options) -> Path:
    """`claude_desktop_config.json`: `%APPDATA%`, or the simulated HOME's own `AppData/Roaming`."""
    from . import desktop_config

    if opts.desktop_dir is not None:
        return desktop_config.config_path(opts.desktop_dir)
    if is_simulated_home(opts.home):
        return desktop_config.config_path(opts.home / "AppData" / "Roaming")
    return desktop_config.config_path()


def _desktop_action(opts: Options) -> Action:
    """Writes the bridge entry; a foreign one is replaced because `--desktop` asked, with a word."""
    from . import desktop_config

    install_state = _sibling("install_state")

    path = desktop_config_path(opts)
    executable = desktop_executable(opts)

    def _run() -> str:
        state = install_state.load(opts.home, opts.data_dir)
        recorded = install_state.piece(state, "desktop_entry")
        result = desktop_config.write_entry(
            path, executable, replace_foreign=True, owned=recorded is not None
        )
        lines = [
            t(
                "plugin_install.desktop.written"
                if result.changed
                else "plugin_install.desktop.up_to_date"
            )
        ]
        if result.replaced_foreign:
            lines.append(t("plugin_install.desktop.replaced_foreign", backup=result.backup))
        if result.changed or recorded is not None:
            replaced = bool(result.replaced_foreign or (recorded or {}).get("replaced_foreign"))
            backup = result.backup if result.replaced_foreign else (recorded or {}).get("backup")
            base = state or install_state.new_state(install_state.delivery(state) or "settings", "")
            install_state.save(
                opts.home,
                install_state.with_piece(
                    base,
                    "desktop_entry",
                    path=str(path),
                    replaced_foreign=replaced,
                    backup=str(backup) if backup else None,
                ),
                opts.data_dir,
            )
        return "\n    ".join(lines)

    detail = t("plugin_install.desktop.plan", path=path)
    literal = json.dumps(desktop_config.bridge_entry(executable), ensure_ascii=False)
    return Action("desktop", path, detail, _run, literal=literal)


def plan_install(opts: Options) -> list[Action]:
    """Lista ordenada de acciones. No toca disco: ejecutarlas es responsabilidad de apply()."""
    actions: list[Action] = []
    claude = _claude_dir(opts)
    codex = _codex_dir(opts)
    opencode = opencode_dir(opts.home)
    # El idioma va primero: la skill, el bloque y el catálogo se escriben en el que quede vigente.
    language = plan_language(opts)
    lang = language.lang
    if opts.write_language and (language_step := language_action(language)) is not None:
        actions.append(language_step)

    # Antes de cualquier otra acción sobre `settings.json` (REQ-016).
    if opts.migrate_retired_names and "claude" in opts.targets:
        actions.extend(plan_retired_name_migration(opts.home, opts.data_dir))

    if "hooks" in opts.components and "claude" in opts.targets:
        actions.extend(_claude_hook_actions(opts, claude, lang))

    if "skill" in opts.components and "claude" in opts.targets:
        if retired_skill_dirs(claude / "skills"):
            actions.append(_retire_skills_action(claude / "skills"))
        actions.append(
            _copy_skill_action(
                claude / "skills" / SKILL_NAME,
                lang,
                t("install.skill.copy_plan", skill=SKILL_NAME, lang=lang),
            )
        )

    # La skill se instala también en el directorio propio de opencode, y NO se confía en que la
    # lea de `~/.claude/skills/`. Que la lee está medido; que sirva como diseño, no: esa
    # compatibilidad es apagable (`OPENCODE_DISABLE_EXTERNAL_SKILLS=1`) y **no existe** en una
    # máquina sin Claude Code, donde este `plan_install` ni siquiera emite la acción de arriba.
    # Crearle un `~/.claude/` a quien no tiene Claude Code es justo lo que se corrigió al retirar
    # el default `--target all`.
    if "skill" in opts.components and "opencode" in opts.targets:
        if retired_skill_dirs(opencode / OPENCODE_SKILL_SUBDIR):
            actions.append(_retire_skills_action(opencode / OPENCODE_SKILL_SUBDIR))
        actions.append(
            _copy_skill_action(
                opencode / OPENCODE_SKILL_SUBDIR / SKILL_NAME,
                lang,
                t("install.skill.copy_plan_opencode", skill=SKILL_NAME, lang=lang),
            )
        )

    # `agents` es el único componente que NO está en el default, y la asimetría es deliberada:
    # los subagentes los escribió el usuario, no son andamiaje nuestro. Se planifica solo si hay
    # algo que cambiar, para que el plan no anuncie trabajo inexistente.
    if "agents" in opts.components and "claude" in opts.targets:
        # Import diferido y una ruta que se pasa, no que se descubre: `agents` no importa este
        # módulo (cerraría un ciclo que CodeQL marcó), así que la fuente del catálogo se le da.
        from . import agents as agents_mod

        changes = agents_mod.pending(claude / "agents", skill_source(lang), lang)
        if changes:
            actions.append(_agents_action(claude / "agents", changes, opts))

    if "memory" in opts.components:
        block = memory_source(lang).read_text(encoding="utf-8")
        memory_files = []
        if "claude" in opts.targets:
            memory_files.append(claude / "CLAUDE.md")
        if "codex" in opts.targets:
            memory_files.append(codex / "AGENTS.md")
        if "opencode" in opts.targets:
            # Mismo razonamiento que con la skill: está medido que opencode carga **también**
            # `~/.claude/CLAUDE.md` —es una lista de ficheros, no un «el primero que haya»—, pero
            # eso es apagable (`OPENCODE_DISABLE_CLAUDE_CODE_PROMPT`) y no existe sin Claude Code.
            memory_files.append(opencode / "AGENTS.md")
        for path in memory_files:

            def _run_md(path=path, block=block) -> str:
                from .agents import normalize_block

                current = _read_text_for_rewrite(path)
                updated = upsert_block(current, block, MD_BEGIN, MD_END)
                if path.is_file() and normalize_block(updated) == normalize_block(current):
                    return t("install.memory.up_to_date")
                _write_text(path, updated)
                return t("install.memory.updated")

            plan = t("install.memory.plan", lang=lang)
            actions.append(Action("markdown", path, plan, _run_md))

    if "mcp" in opts.components:
        requested = opts.web_token_env is True
        entry = mcp_entry(
            opts.mcp_mode,
            opts.base_url,
            opts.api_key_env,
            opts.pin_version,
            requested,
        )
        detail = t("install.mcp.register_plan", server=SERVER_NAME, mode=opts.mcp_mode)

        def _kept(target: str) -> str | None:
            # Solo cuando nadie dijo nada: un flag explícito, en cualquiera de sus dos sentidos,
            # es una orden y manda sobre lo que hubiera.
            if opts.web_token_env is not None:
                return None
            return existing_header(opts.home, target)

        def _detail(header: str | None, timeouts: dict) -> str:
            text = detail
            if header:
                text += t("install.mcp.keeps_header")
            if timeouts:
                text += t("install.mcp.keeps_timeouts", timeouts=_describe_timeouts(timeouts))
            return text

        if "claude" in opts.targets:
            kept = _kept("claude")
            timeouts = existing_timeouts(opts.home, "claude")
            claude_entry = {**_with_header(entry, kept), **timeouts}
            actions.append(
                Action(
                    "mcp",
                    "claude",
                    _detail(kept, timeouts),
                    lambda entry=claude_entry: _register_claude_mcp(opts, entry),
                    literal=json.dumps(_without_secrets(claude_entry), ensure_ascii=False),
                )
            )
        if "codex" in opts.targets and not opts.skip_codex_mcp:
            config_path = codex / "config.toml"
            kept = _kept("codex")
            timeouts = existing_timeouts(opts.home, "codex")
            codex_block = codex_mcp_block(_with_header(entry, kept), timeouts)

            def _run_codex(path=config_path, block=codex_block) -> str:
                _write_text(path, upsert_codex_mcp(_read_text_for_rewrite(path), block))
                return t("install.mcp.codex_updated", server=SERVER_NAME)

            actions.append(
                Action(
                    "toml",
                    config_path,
                    _detail(kept, timeouts),
                    _run_codex,
                    literal=codex_block,
                )
            )
        if "opencode" in opts.targets:
            kept = _kept("opencode")
            timeouts = existing_timeouts(opts.home, "opencode")
            oc_entry = {
                **_with_header(
                    opencode_mcp_entry(
                        opts.mcp_mode,
                        opts.base_url,
                        opts.api_key_env,
                        opts.pin_version,
                        requested,
                    ),
                    kept,
                ),
                **timeouts,
            }
            actions.append(
                Action(
                    "mcp",
                    "opencode",
                    _detail(kept, timeouts),
                    lambda entry=oc_entry: _register_opencode_mcp(opts, entry),
                    literal=json.dumps(
                        {SERVER_NAME: _without_secrets(oc_entry)}, ensure_ascii=False
                    ),
                )
            )
    # REQ-012: only when asked, and only on Windows (the CLI refuses the flag elsewhere).
    if opts.desktop and (opts.platform or sys.platform) == "win32":
        actions.append(_desktop_action(opts))
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
            # Con un plazo conservado se comprueba que la CLI lo dejó escrito: si lo descartara,
            # el usuario lo perdería igual que antes del arreglo. Si no está, se escribe el fichero.
            timeouts = {k: entry[k] for k in TIMEOUT_KEYS["claude"] if k in entry}
            if done.returncode == 0 and (
                not timeouts or existing_timeouts(opts.home, "claude") == timeouts
            ):
                return t("install.mcp.registered_with", command="claude mcp add-json --scope user")
        except (OSError, subprocess.SubprocessError):
            pass  # cae al modo archivo
    path = opts.home / ".claude.json"
    data = _read_config_json(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    servers[SERVER_NAME] = entry
    _write_json(path, data)
    return t("install.mcp.written_to", path=path)


# Lo que se dice cuando la entrada de opencode NO se escribe (`install.opencode.untouched`). Es un
# aviso, no un fallo: el resto de componentes sí se instala y el exit code no sube (ver `apply`).


def _read_opencode_config(path: Path) -> tuple[str, str | None]:
    """(contenido, motivo por el que no se pudo leer).

    **No** vale ``_read_text`` aquí, y la diferencia es un defecto de verdad: aquella devuelve
    ``""`` tanto para un fichero vacío como para uno que no se pudo abrir. Con ese ``""``, la
    comprobación de más abajo daría vía libre y se escribiría un config nuevo **encima del que no
    se pudo leer** — justo lo que este camino existe para no hacer. Un fichero ilegible es
    exactamente el caso en el que hay que no tocar nada.
    """
    try:
        return path.read_text(encoding="utf-8"), None
    except FileNotFoundError:
        return "", None
    except (OSError, UnicodeDecodeError) as exc:
        reason = getattr(exc, "strerror", None) or exc
        return "", t("install.opencode.unreadable", reason=reason)


def _reason_not_to_write(text: str) -> str | None:
    """Por qué NO se puede reescribir este config, o ``None`` si sí se puede.

    Se comprueba antes de tocar nada y por dos condiciones distintas, porque el riesgo es distinto
    en cada una: los comentarios se perderían **sin que el fichero pareciera roto** (JSON no los
    tiene, así que un `json.dumps` los borra en silencio), y lo que no parsea no se puede reescribir
    sin inventarse lo que decía. En los dos casos el lado seguro es el mismo: no escribir y avisar.

    Ojo: recibe el texto **ya leído con éxito**. Que el fichero se pueda leer es condición previa y
    la resuelve `_read_opencode_config`, porque un fallo de lectura aquí llegaría como `""` y se
    confundiría con un fichero vacío, que sí es escribible.
    """
    if not text.strip():
        return None
    clean, had_comments = _scan_jsonc(text)
    if had_comments:
        return t("install.opencode.has_comments")
    try:
        data = json.loads(clean)
    except ValueError as exc:
        return t("install.opencode.invalid_json", reason=exc.msg)
    if not isinstance(data, dict):
        return t("install.opencode.not_an_object")
    if not isinstance(data.get("mcp", {}), dict):
        return t("install.opencode.mcp_not_an_object", key="mcp")
    return None


def opencode_mcp_installed(home: Path) -> dict | None:
    """La entrada de local-delegate en la config de opencode, mirando **los dos** ficheros."""
    for path in opencode_config_paths(home):
        data, _reason = read_opencode_config(path)
        if not isinstance(data, dict):
            continue
        servers = data.get("mcp")
        entry = servers.get(SERVER_NAME) if isinstance(servers, dict) else None
        if isinstance(entry, dict):
            return entry
    return None


def _opencode_cli_env(home: Path) -> dict[str, str]:
    """Entorno con el que se invoca la CLI de opencode.

    Se fija `XDG_CONFIG_HOME` **siempre**, y no solo con un HOME simulado: es la única forma de que
    «dónde creemos que está el config» y «dónde escribe el cliente» sean lo mismo en los tres
    sistemas. Con el HOME real y la variable ya puesta es un no-op; sin ella, apunta a `~/.config`,
    que es justo donde opencode habría escrito. Con `--home`, mantiene la escritura dentro del
    árbol simulado — que es lo que `claude mcp add-json --scope user` **no** sabe hacer.
    """
    environment = dict(os.environ)
    environment["HOME"] = str(home)
    environment["XDG_CONFIG_HOME"] = str(opencode_dir(home).parent)
    return environment


def _register_opencode_mcp(opts: Options, entry: dict) -> str:
    """Registra el MCP en opencode: primero con su CLI, si no escribiendo el fichero.

    Se prefiere la CLI por lo mismo que en Claude Code y con un motivo extra que aquí pesa más:
    **conserva los comentarios y las demás claves** del usuario, y valida la forma el propio
    cliente — cuyo castigo por una forma mala no es una entrada rota, sino no arrancar.

    Con un HOME simulado, ``opts.use_cli`` ya viene en ``False`` y se escribe el fichero. Nótese
    que aquí **no es por el motivo del binario `claude`**: `opencode` sí respeta el HOME que se le
    pasa (medido, y por eso existe `_opencode_cli_env`). Se mantiene apagado porque ``--home`` es
    el modo de prueba, y lanzar el cliente real desde la suite la haría depender de qué hay
    instalado en la máquina.

    Con un plazo conservado (``timeout``) **no** se usa la CLI: sus opciones medidas (`--url`,
    `--header`, `--env`) no lo expresan, y registrar por ahí lo perdería. Se va al fichero, y si
    el fichero no se puede reescribir se avisa y la entrada anterior, con su plazo, queda intacta.
    """
    has_timeout = any(k in entry for k in TIMEOUT_KEYS["opencode"])
    if opts.use_cli and not has_timeout and shutil.which("opencode"):
        try:
            done = subprocess.run(
                ["opencode", *opencode_mcp_add_args(entry)],
                capture_output=True,
                text=True,
                timeout=60,
                env=_opencode_cli_env(opts.home),
            )
            # El `returncode` NO basta: está medido que el binario devuelve 0 también para
            # subcomandos que no existen (`opencode mcp remove`). Si algún día `add` cambia de
            # nombre, confiar en el código de salida daría por hecho un registro que no ocurrió.
            # Lo que decide es que la entrada esté después.
            if done.returncode == 0 and opencode_mcp_installed(opts.home) is not None:
                return t("install.mcp.registered_with", command="opencode mcp add")
        except (OSError, subprocess.SubprocessError):
            pass  # cae al modo archivo

    path = opencode_config_target(opts.home)
    text, failure = _read_opencode_config(path)
    reason = failure or _reason_not_to_write(text)
    if reason:
        return t("install.opencode.untouched", path=path, reason=reason, server=SERVER_NAME)
    data = json.loads(strip_jsonc(text)) if text.strip() else {"$schema": OPENCODE_SCHEMA}
    servers = data.setdefault("mcp", {})
    servers[SERVER_NAME] = entry
    _write_json(path, data)
    return t("install.mcp.written_to", path=path)


def _unregister_opencode_mcp(opts: Options) -> str:
    """Quita la entrada de los ficheros de opencode. **No** hay `opencode mcp remove` (medido).

    Por eso este camino no tiene la rama por CLI que sí tienen sus dos hermanos: no existe el
    comando en el que delegar, así que la edición es nuestra y con la misma regla de seguridad que
    al instalar.
    """
    details: list[str] = []
    for path in opencode_config_paths(opts.home):
        if not path.is_file():
            continue
        text, failure = _read_opencode_config(path)
        reason = failure or _reason_not_to_write(text)
        if reason:
            details.append(t("install.opencode.not_touched", path=path, reason=reason))
            continue
        data = json.loads(strip_jsonc(text)) if text.strip() else {}
        servers = data.get("mcp")
        if not isinstance(servers, dict) or servers.pop(SERVER_NAME, None) is None:
            continue
        # Una clave `mcp` vacía es válida para opencode, pero dejarla es dejar basura nuestra en un
        # fichero ajeno: si se queda sin entradas y no la había antes, se retira.
        if not servers:
            data.pop("mcp", None)
        _write_json(path, data)
        details.append(t("install.mcp.removed_from", path=path))
    return " · ".join(details) if details else t("install.mcp.not_registered")


def plan_uninstall(opts: Options) -> list[Action]:
    """Deshace exactamente lo que instaló plan_install(); nunca borra nada ajeno."""
    actions: list[Action] = []
    claude = _claude_dir(opts)
    codex = _codex_dir(opts)
    opencode = opencode_dir(opts.home)
    hooks_dst = claude / "hooks" / HOOKS_SUBDIR
    state = _installation_state(opts)

    # REQ-011: the plugin and its marketplace, only if the state says `install` put them there.
    if (
        "hooks" in opts.components
        and "claude" in opts.targets
        and _state_piece(state, "plugin") is not None
    ):
        actions.append(_uninstall_plugin_action(opts, state))

    if "hooks" in opts.components and "claude" in opts.targets:
        settings_path = claude / "settings.json"

        def _run_settings(path=settings_path, hooks_dir=hooks_dst) -> str:
            if not path.is_file():
                return t("install.uninstall.no_settings", name=path.name)
            data, removed = strip_hook_settings(_read_config_json(path), hooks_dir)
            _write_json(path, data)
            return t("install.uninstall.hooks_removed", n=removed)

        actions.append(
            Action("settings", settings_path, t("install.uninstall.hooks_plan"), _run_settings)
        )

        def _run_rm(path=hooks_dst) -> str:
            if path.is_dir():
                shutil.rmtree(path)
                return t("install.uninstall.removed")
            return t("install.uninstall.did_not_exist")

        actions.append(Action("remove", hooks_dst, t("install.uninstall.scripts_plan"), _run_rm))

    if "skill" in opts.components and "claude" in opts.targets:
        skill_dst = claude / "skills" / SKILL_NAME

        def _run_skill(path=skill_dst) -> str:
            if path.is_dir():
                shutil.rmtree(path)
                return t("install.uninstall.skill_removed")
            return t("install.uninstall.did_not_exist")

        plan = t("install.uninstall.skill_plan", skill=SKILL_NAME)
        actions.append(Action("remove", skill_dst, plan, _run_skill))
        # Una máquina que pasó de la 0.34 sin `install` ni `update` conserva la skill con su
        # nombre viejo, que también es nuestra.
        if retired_skill_dirs(claude / "skills"):
            actions.append(_retire_skills_action(claude / "skills"))

    if "skill" in opts.components and "opencode" in opts.targets:
        oc_skill = opencode / OPENCODE_SKILL_SUBDIR / SKILL_NAME

        def _run_skill_oc(path=oc_skill) -> str:
            if path.is_dir():
                shutil.rmtree(path)
                return t("install.uninstall.skill_removed")
            return t("install.uninstall.did_not_exist")

        plan = t("install.uninstall.skill_plan_opencode", skill=SKILL_NAME)
        actions.append(Action("remove", oc_skill, plan, _run_skill_oc))
        if retired_skill_dirs(opencode / OPENCODE_SKILL_SUBDIR):
            actions.append(_retire_skills_action(opencode / OPENCODE_SKILL_SUBDIR))

    if "memory" in opts.components:
        paths = []
        if "claude" in opts.targets:
            paths.append(claude / "CLAUDE.md")
        if "codex" in opts.targets:
            paths.append(codex / "AGENTS.md")
        if "opencode" in opts.targets:
            paths.append(opencode / "AGENTS.md")
        for path in paths:

            def _run_md(path=path) -> str:
                if not path.is_file():
                    return t("install.uninstall.did_not_exist")
                _write_text(path, remove_block(_read_text_for_rewrite(path), MD_BEGIN, MD_END))
                return t("install.uninstall.block_removed")

            plan = t("install.uninstall.block_plan")
            actions.append(Action("markdown", path, plan, _run_md))

    if "mcp" in opts.components:
        if "claude" in opts.targets:
            actions.append(
                Action(
                    "mcp",
                    "claude",
                    t("install.uninstall.mcp_plan", server=SERVER_NAME),
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
                    return t("install.uninstall.did_not_exist")
                _write_text(path, remove_codex_mcp(_read_text_for_rewrite(path)))
                return t("install.uninstall.entry_removed")

            plan = t("install.uninstall.codex_plan", server=SERVER_NAME)
            actions.append(Action("toml", config_path, plan, _run_codex))
        if "opencode" in opts.targets:
            actions.append(
                Action(
                    "mcp",
                    "opencode",
                    t("install.uninstall.mcp_plan", server=SERVER_NAME),
                    lambda: _unregister_opencode_mcp(opts),
                )
            )

    # REQ-012: the Desktop chat entry is an MCP entry; it goes if `install --desktop` wrote it.
    desktop_piece = _state_piece(state, "desktop_entry")
    if "mcp" in opts.components and desktop_piece is not None:
        actions.append(_uninstall_desktop_action(opts, desktop_piece))

    # REQ-011: what `install --agents` wrote in the subagents (until 0.39 it stayed).
    agents_piece = _state_piece(state, "agents")
    full = FULL_COMPONENTS <= opts.components
    if (
        agents_piece is not None
        and "claude" in opts.targets
        and (full or "agents" in opts.components)
    ):
        actions.append(_revert_agents_action(opts, claude / "agents", agents_piece))

    # REQ-047: `language.json` lo escribió `install`, así que se va con lo demás. Solo en una
    # desinstalación completa: quitar un componente suelto no es dejar de usar el paquete.
    data_dir = language_dir(opts)
    if full and data_dir is not None:
        actions.append(_remove_language_action(data_dir / hook_common.LANGUAGE_PREFERENCE_FILE))
    # The read switch and, last of all, the installation state (REQ-004, REQ-007).
    if "hooks" in opts.components and "claude" in opts.targets:
        plugin_migration = _sibling("plugin_migration")

        switch = plugin_migration.read_switch_path(opts.home, opts.data_dir)
        if switch is not None and switch.exists():
            actions.append(_remove_file_action(switch, t("plugin_install.uninstall.switch_plan")))
    if full:
        install_state = _sibling("install_state")

        state_path = install_state.path(opts.home, opts.data_dir)
        if state_path is not None and state_path.exists():
            detail = t("plugin_install.uninstall.state_plan")
            actions.append(_remove_file_action(state_path, detail))
    return actions


def _state_piece(state: dict | None, name: str) -> dict | None:
    install_state = _sibling("install_state")

    return install_state.piece(state, name)


def _remove_file_action(path: Path, detail: str) -> Action:
    def _run() -> str:
        try:
            path.unlink()
        except FileNotFoundError:
            return t("install.uninstall.did_not_exist")
        return t("install.uninstall.removed")

    return Action("remove", path, detail, _run)


def _uninstall_plugin_action(opts: Options, state: dict | None) -> Action:
    """Uninstalls the plugin and, if the state lists it, the marketplace (REQ-011)."""
    claude_plugin = _sibling("claude_plugin")
    install_state = _sibling("install_state")

    runner = opts.claude_runner or claude_plugin.run_subprocess
    which = opts.claude_which or shutil.which
    with_marketplace = install_state.piece(state, "marketplace") is not None

    def _call(argv: list[str]) -> None:
        done = runner(argv, claude_plugin.child_env(opts.home))
        if done.returncode != 0:
            detail = (done.stderr or done.stdout or "").strip()
            command = " ".join(argv[1:4])
            raise RuntimeError(
                t("plugin_install.uninstall.step_failed", command=command, detail=detail)
            )

    def _run() -> str:
        claude_bin = which("claude")
        if not claude_bin:
            raise RuntimeError(t("plugin_install.uninstall.no_cli"))
        _call(claude_plugin.uninstall_argv(claude_bin))
        if with_marketplace:
            _call(claude_plugin.marketplace_remove_argv(claude_bin))
        current = install_state.load(opts.home, opts.data_dir)
        if current is not None:
            current = install_state.without_piece(current, "plugin")
            current = install_state.without_piece(current, "marketplace")
            install_state.save(opts.home, current, opts.data_dir)
        return t("plugin_install.uninstall.plugin_removed", plugin=claude_plugin.PLUGIN_ID)

    detail = t("plugin_install.uninstall.plugin_plan", plugin=claude_plugin.PLUGIN_ID)
    return Action("plugin", "claude", detail, _run)


def _uninstall_desktop_action(opts: Options, piece: dict) -> Action:
    """Removes our Desktop entry (REQ-012).

    A foreign entry it once replaced is NOT put back, because it could carry the token: the
    copy that holds it is named instead.
    """
    from . import desktop_config

    install_state = _sibling("install_state")

    path = Path(piece["path"]) if piece.get("path") else desktop_config_path(opts)

    def _run() -> str:
        result = desktop_config.remove_entry(path)
        key = (
            "install.uninstall.entry_removed"
            if result.changed
            else "install.uninstall.did_not_exist"
        )
        lines = [t(key)]
        if piece.get("replaced_foreign") and piece.get("backup"):
            lines.append(t("plugin_install.uninstall.desktop_backup", backup=piece["backup"]))
        current = install_state.load(opts.home, opts.data_dir)
        if current is not None:
            install_state.save(
                opts.home, install_state.without_piece(current, "desktop_entry"), opts.data_dir
            )
        return "\n    ".join(lines)

    return Action("desktop", path, t("plugin_install.uninstall.desktop_plan"), _run)


#: Los componentes por defecto: desinstalarlos todos es una desinstalación completa.
FULL_COMPONENTS = frozenset({"hooks", "skill", "memory", "mcp"})


def _remove_language_action(path: Path) -> Action:
    def _run() -> str:
        try:
            path.unlink()
        except FileNotFoundError:
            return t("install.uninstall.did_not_exist")
        return t("install.uninstall.removed")

    return Action("remove", path, t("install.uninstall.language_plan"), _run)


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
                return t("install.mcp.removed_with", command="claude mcp remove")
        except (OSError, subprocess.SubprocessError):
            # El binario `claude` está pero no se pudo ejecutar (o se pasó del plazo). No es un
            # fallo de la desinstalación: justo debajo está el camino que edita `.claude.json`
            # directamente, que es el que se usa cuando no hay CLI. Degradar a él en silencio es
            # correcto; abortar aquí dejaría la entrada MCP puesta por no haber podido usar el
            # atajo.
            pass
    path = opts.home / ".claude.json"
    data = _read_config_json(path)
    servers = data.get("mcpServers")
    if isinstance(servers, dict) and servers.pop(SERVER_NAME, None) is not None:
        _write_json(path, data)
        return t("install.mcp.removed_from", path=path)
    return t("install.mcp.not_registered")


def apply(actions: list[Action], *, dry_run: bool, out=print) -> int:
    """Ejecuta (o solo describe) las acciones. Devuelve el número de fallos."""
    failures = 0
    for action in actions:
        if dry_run:
            out(f"[dry-run] {action.describe()}")
            # El literal SOLO aquí: al aplicar de verdad, la salida ya la escribe `action.run()`
            # con lo que pasó, y repetir lo que se iba a escribir sobraría. En `--dry-run` es al
            # revés: es lo único que se puede revisar antes de que toque el disco.
            for line in action.literal.splitlines():
                out(f"          {line}")
            continue
        out(action.describe())
        try:
            result = action.run() if callable(action.run) else None
        except Exception as exc:  # una acción fallida no debe abortar el resto
            failures += 1
            out(t("install.action_error", detail=exc))
            continue
        if result:
            out(f"    {result}")
    return failures
