"""La entrada `local-delegate` de `claude_desktop_config.json`: escribirla, quitarla y revisarla.

El chat de Claude Desktop no ve el plugin de Claude Code: carga los MCP de este fichero. La entrada
que escribimos lanza el puente (`local-delegate desktop-bridge`), que lee el token él mismo; por eso
la entrada no lleva token ni `${VAR}` (Desktop no la expande: medido el 2026-10-21).

Reglas, todas de REQ-012:

- Solo se toca la clave `mcpServers.local-delegate`; el resto del fichero queda igual, en orden.
- Antes de cambiar el fichero se hace **una** copia en la misma carpeta, rotada (`MAX_BACKUPS`).
  En Windows hereda la ACL de `%APPDATA%\\Claude`, que ya es solo del usuario; la librería estándar
  no pone ACL y no se añaden dependencias para eso.
- Una entrada que no es la del puente (en esta PC, `mcp-remote` con el token literal, puesta a
  mano) es **ajena**: solo se reemplaza si quien llama lo pide expresamente.
- La revisión dice si hay `${…}` sin expandir o un token literal, **sin** devolver el valor.

Quien decide cuándo escribir es `install --desktop` (otro módulo); este no imprime nada.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import i18n

FILE_NAME = "claude_desktop_config.json"
ENTRY_KEY = "local-delegate"
BRIDGE_SUBCOMMAND = "desktop-bridge"
EXECUTABLE_NAME = "local-delegate"
MAX_BACKUPS = 3
BACKUP_SUFFIX = ".local-delegate.bak"

# `Bearer <algo>` donde <algo> no es una referencia `${…}`: un token escrito tal cual.
_LITERAL_BEARER = re.compile(r"Bearer\s+(?!\$\{)\S+", re.IGNORECASE)
_UNEXPANDED = re.compile(r"\$\{([^}]*)\}")
_TOKEN_ENV_NAMES = frozenset({"LOCAL_DELEGATE_WEB_TOKEN", "AUTH_HEADER", "AUTHORIZATION"})


class DesktopConfigError(Exception):
    """El fichero existe pero no se puede usar (no es JSON, no es un objeto…). No se reescribe."""


class ForeignEntryError(DesktopConfigError):
    """Ya hay una entrada `local-delegate` que no es la del puente y no se pidió reemplazarla."""


@dataclass(frozen=True)
class WriteResult:
    changed: bool
    backup: Path | None = None
    replaced_foreign: bool = False


@dataclass(frozen=True)
class EntryReport:
    """Lo que se sabe de la entrada sin exponer su contenido (nunca lleva el token)."""

    present: bool
    is_bridge: bool
    unexpanded_variable: bool
    literal_token: bool


def config_path(base_dir: Path | str | None = None) -> Path:
    """`%APPDATA%\\Claude\\claude_desktop_config.json`, o bajo la carpeta `base_dir` que se pase."""
    base = Path(base_dir) if base_dir is not None else Path(os.environ.get("APPDATA", ""))
    return base / "Claude" / FILE_NAME


def bridge_entry(executable: Path | str) -> dict:
    """La entrada del puente: ruta absoluta del ejecutable y el subcomando; sin `env` ni token."""
    return {"command": str(executable), "args": [BRIDGE_SUBCOMMAND]}


def is_bridge_entry(entry: object) -> bool:
    """¿Es una entrada del puente, aunque apunte a otra ruta del ejecutable (versión anterior)?"""
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    if not isinstance(command, str) or entry.get("args") != [BRIDGE_SUBCOMMAND]:
        return False
    name = command.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name in (EXECUTABLE_NAME, f"{EXECUTABLE_NAME}.exe")


def _load(path: Path) -> dict | None:
    """El objeto del fichero, `None` si no existe. Lanza si existe y no se puede usar."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DesktopConfigError(i18n.t("bridge.config.unreadable", path=path, detail=exc)) from exc
    try:
        # `utf-8-sig`: un editor de Windows puede haber dejado BOM, y Desktop lo acepta.
        data = json.loads(raw.decode("utf-8-sig")) if raw.strip() else {}
    except (UnicodeDecodeError, ValueError) as exc:
        raise DesktopConfigError(i18n.t("bridge.config.invalid_json", path=path)) from exc
    if not isinstance(data, dict):
        raise DesktopConfigError(i18n.t("bridge.config.not_object", path=path))
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise DesktopConfigError(i18n.t("bridge.config.not_object", path=path))
    return data


def _backup_names(path: Path) -> list[Path]:
    """Los nombres de las copias, de la más reciente a la más vieja (existan o no)."""
    first = path.with_name(path.name + BACKUP_SUFFIX)
    return [first] + [first.with_name(f"{first.name}.{n}") for n in range(1, MAX_BACKUPS)]


def backups(path: Path) -> list[Path]:
    """Las copias que existen, de la más reciente a la más vieja."""
    return [name for name in _backup_names(path) if name.exists()]


def _backup(path: Path) -> Path:
    """Copia el fichero actual a `<nombre>.local-delegate.bak`, rotando las anteriores."""
    rotated = _backup_names(path)
    first = rotated[0]
    for older, newer in zip(reversed(rotated[1:]), reversed(rotated[:-1]), strict=True):
        if newer.exists():
            newer.replace(older)
    first.write_bytes(path.read_bytes())
    return first


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            # Si `replace` funcionó ya no existe; si no, un antivirus puede tenerlo abierto, y
            # lanzar aquí taparía el error real del `try`.
            pass


def write_entry(
    path: Path, executable: Path | str, *, replace_foreign: bool = False, owned: bool = False
) -> WriteResult:
    """Deja `mcpServers.local-delegate` apuntando al puente de `executable`.

    `owned`: el estado de `install` dice que la entrada la escribió él, aunque ya no tenga la
    forma del puente. `replace_foreign`: el usuario pidió reemplazar una entrada ajena.
    """
    data = _load(path)
    wanted = bridge_entry(executable)
    if data is None:
        _save(path, {"mcpServers": {ENTRY_KEY: wanted}})
        return WriteResult(changed=True)

    servers = data.get("mcpServers") or {}
    current = servers.get(ENTRY_KEY)
    if current == wanted:
        return WriteResult(changed=False)
    foreign = current is not None and not owned and not is_bridge_entry(current)
    if foreign and not replace_foreign:
        raise ForeignEntryError(i18n.t("bridge.config.foreign_entry", path=path, key=ENTRY_KEY))

    backup = _backup(path)
    servers = dict(servers)
    servers[ENTRY_KEY] = wanted
    data["mcpServers"] = servers
    _save(path, data)
    return WriteResult(changed=True, backup=backup, replaced_foreign=foreign)


def remove_entry(path: Path) -> WriteResult:
    """Quita `mcpServers.local-delegate` (sea cual sea), con copia previa. No toca nada más."""
    data = _load(path)
    servers = (data or {}).get("mcpServers") or {}
    if ENTRY_KEY not in servers:
        return WriteResult(changed=False)
    backup = _backup(path)
    data["mcpServers"] = {key: value for key, value in servers.items() if key != ENTRY_KEY}
    _save(path, data)
    return WriteResult(changed=True, backup=backup)


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def check_entry(path: Path, token: str | None) -> EntryReport:
    """Revisa la entrada sin leer en voz alta nada de ella.

    `token`: el token vigente, si se conoce, para reconocerlo escrito tal cual. Sin él se detecta
    igual un `Bearer <valor>` literal o una variable de token con valor en el bloque `env`.
    """
    try:
        data = _load(path)
    except DesktopConfigError:
        data = None
    entry = ((data or {}).get("mcpServers") or {}).get(ENTRY_KEY)
    if not isinstance(entry, dict):
        return EntryReport(
            present=False, is_bridge=False, unexpanded_variable=False, literal_token=False
        )

    texts = list(_strings(entry))
    env = entry.get("env")
    # A `${VAR}` whose VAR the entry's own `env` gives a value is not unexpanded: `mcp-remote`
    # substitutes it from that env (`--header Authorization:${AUTH_HEADER}` with `AUTH_HEADER` in
    # `env`, its documented form). What Desktop never expands is a variable from nowhere (#511).
    defined = (
        {
            key
            for key, value in env.items()
            if isinstance(value, str) and value.strip() and not _UNEXPANDED.search(value)
        }
        if isinstance(env, dict)
        else set()
    )
    unexpanded = any(
        match.group(1).strip() not in defined
        for text in texts
        for match in _UNEXPANDED.finditer(text)
    )
    literal = bool(token) and any(token in text for text in texts)
    literal = literal or any(_LITERAL_BEARER.search(text) for text in texts)
    if isinstance(env, dict):
        literal = literal or any(
            key.upper() in _TOKEN_ENV_NAMES
            and isinstance(value, str)
            and value.strip()
            and not _UNEXPANDED.search(value)
            for key, value in env.items()
        )
    return EntryReport(
        present=True,
        is_bridge=is_bridge_entry(entry),
        unexpanded_variable=unexpanded,
        literal_token=literal,
    )
