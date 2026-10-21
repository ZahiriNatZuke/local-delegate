"""completion.py — model of the CLI for the shell completion scripts (SDD cli-completion).

`build_model(parser)` walks the real `argparse` parser (`cli.build_parser()`) and returns a
`Model`: one `Node` per path of subcommands, with its visible subcommands, its option strings
(with help, arity and fixed values) and its positionals in order. The three scripts (PowerShell,
bash, zsh) come out of this model, so nothing here lists subcommands or options by hand.

The walk only reads the parser: it never adds, removes or changes an action. It refuses what the
scripts cannot complete correctly instead of emitting a partial script:

- `UnsupportedConstructError` for an action class or `nargs` outside REQ-006, a subparser alias,
  `prefix_chars` other than `-` or a short option other than `-h`;
- `UnsafeTokenError` for a subcommand name, fixed value or option string that does not match the
  safe patterns of REQ-007 (the scripts embed them without quoting).

Hidden things are left out (REQ-004): actions with `help=SUPPRESS`, subparsers without an entry
in `_choices_actions` and the old name of every entry in `deprecations.cli_entries()` (CLI
surface, alias or retired: an alias still works but is not offered).

Fixed values come from the action's own `completion_values` attribute (read only here) or from
its `choices` (REQ-005).
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import deprecations, i18n

#: Arity of an option: takes no value, a required value or an optional value.
ARITY_FLAG = "flag"
ARITY_REQUIRED = "required"
ARITY_OPTIONAL = "optional"

#: Action classes the scripts know how to complete (REQ-006). Exact classes, not `isinstance`:
#: `_ExtendAction` subclasses `_AppendAction` but takes several values.
SUPPORTED_ACTIONS: frozenset[type[argparse.Action]] = frozenset(
    {
        argparse._StoreAction,
        argparse._StoreTrueAction,
        argparse._StoreFalseAction,
        argparse._StoreConstAction,
        argparse._AppendAction,
        argparse._AppendConstAction,
        argparse._CountAction,
        argparse._HelpAction,
        argparse._VersionAction,
        argparse._SubParsersAction,
    }
)
#: The only short option allowed: everything else is a long option.
ALLOWED_SHORT_OPTIONS = frozenset({"-h"})

#: Subcommand names and fixed values (REQ-007).
SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:/+-]+$")
#: Option strings (REQ-007).
SAFE_OPTION = re.compile(r"^--?[A-Za-z0-9][A-Za-z0-9_-]*$")


class CompletionModelError(ValueError):
    """Base class: the parser cannot be turned into completion scripts."""


class UnsupportedConstructError(CompletionModelError):
    """An argparse construct outside REQ-006, at `path`."""

    def __init__(self, path: tuple[str, ...], action: str, reason: str) -> None:
        self.path = path
        self.action = action
        self.reason = reason
        super().__init__(f"{_route(path)} {action}: {reason}")


class UnsafeTokenError(CompletionModelError):
    """A token that the scripts cannot embed safely (REQ-007), at `path`."""

    def __init__(self, path: tuple[str, ...], value: str) -> None:
        self.path = path
        self.value = value
        super().__init__(f"{_route(path)}: unsafe_token={value!r}")


@dataclass(frozen=True)
class Option:
    """One option action: all its visible strings share help, arity and values."""

    strings: tuple[str, ...]
    help: str
    arity: str
    values: tuple[str, ...] | None


@dataclass(frozen=True)
class Positional:
    help: str
    values: tuple[str, ...] | None


@dataclass(frozen=True)
class Subcommand:
    name: str
    help: str


@dataclass(frozen=True)
class Node:
    path: tuple[str, ...]
    subcommands: tuple[Subcommand, ...]
    options: tuple[Option, ...]
    positionals: tuple[Positional, ...]


@dataclass(frozen=True)
class Model:
    nodes: dict[tuple[str, ...], Node]


def build_model(parser: argparse.ArgumentParser) -> Model:
    """Model of `parser` and all its subparsers; raises instead of returning a partial model.

    The deprecation registry is read at call time, so a test can monkeypatch it.
    """
    hidden = frozenset(entry.old for entry in deprecations.cli_entries())
    nodes: dict[tuple[str, ...], Node] = {}
    _walk(parser, (), hidden, nodes)
    return Model(nodes)


def _walk(
    parser: argparse.ArgumentParser,
    path: tuple[str, ...],
    hidden: frozenset[str],
    nodes: dict[tuple[str, ...], Node],
) -> None:
    if parser.prefix_chars != "-":
        raise UnsupportedConstructError(
            path, "prefix_chars", f"prefix_chars={parser.prefix_chars!r}"
        )
    formatter = parser._get_formatter()
    subcommands: list[Subcommand] = []
    options: list[Option] = []
    positionals: list[Positional] = []
    children: list[tuple[str, argparse.ArgumentParser]] = []
    for action in parser._actions:
        if action.help == argparse.SUPPRESS:
            continue
        if type(action) not in SUPPORTED_ACTIONS:
            raise UnsupportedConstructError(
                path, _describe(action), f"action_class={type(action).__name__}"
            )
        if isinstance(action, argparse._SubParsersAction):
            for name, help_text, child in _visible_subparsers(path, action, formatter, hidden):
                subcommands.append(Subcommand(name, help_text))
                children.append((name, child))
            continue
        if action.option_strings:
            option = _option(path, action, formatter, hidden)
            if option is not None:
                options.append(option)
        else:
            positionals.append(_positional(path, action, formatter))
    nodes[path] = Node(path, tuple(subcommands), tuple(options), tuple(positionals))
    for name, child in children:
        _walk(child, (*path, name), hidden, nodes)


def _visible_subparsers(
    path: tuple[str, ...],
    action: argparse._SubParsersAction,
    formatter: argparse.HelpFormatter,
    hidden: frozenset[str],
) -> list[tuple[str, str, argparse.ArgumentParser]]:
    names_by_parser: dict[int, list[str]] = {}
    for name, child in action.choices.items():
        names_by_parser.setdefault(id(child), []).append(name)
    for names in names_by_parser.values():
        if len(names) > 1:
            raise UnsupportedConstructError(path, names[0], f"subparser_alias={names[1:]!r}")
    visible = []
    # Only subparsers added with `help` have a pseudo action; the rest are hidden (REQ-004).
    for pseudo in action._choices_actions:
        name = pseudo.dest
        if name in hidden:
            continue
        _check_value(path, name)
        visible.append((name, _help(formatter, pseudo, name), action.choices[name]))
    return visible


def _option(
    path: tuple[str, ...],
    action: argparse.Action,
    formatter: argparse.HelpFormatter,
    hidden: frozenset[str],
) -> Option | None:
    strings = tuple(s for s in action.option_strings if s not in hidden)
    if not strings:
        return None
    for string in strings:
        if not string.startswith("--") and string not in ALLOWED_SHORT_OPTIONS:
            raise UnsupportedConstructError(path, string, "short_option")
        if not SAFE_OPTION.match(string):
            raise UnsafeTokenError(path, string)
    arity = _arity(path, action)
    values = None if arity == ARITY_FLAG else _values(path, action)
    return Option(strings, _help(formatter, action, strings[-1]), arity, values)


def _positional(
    path: tuple[str, ...], action: argparse.Action, formatter: argparse.HelpFormatter
) -> Positional:
    if action.nargs not in (None, "?"):
        raise UnsupportedConstructError(path, _describe(action), f"nargs={action.nargs!r}")
    name = action.metavar if isinstance(action.metavar, str) else action.dest
    return Positional(_help(formatter, action, name), _values(path, action))


def _arity(path: tuple[str, ...], action: argparse.Action) -> str:
    if action.nargs == 0:
        return ARITY_FLAG
    if action.nargs is None:
        return ARITY_REQUIRED
    if action.nargs == "?":
        return ARITY_OPTIONAL
    raise UnsupportedConstructError(path, _describe(action), f"nargs={action.nargs!r}")


def _values(path: tuple[str, ...], action: argparse.Action) -> tuple[str, ...] | None:
    raw = getattr(action, "completion_values", None) or action.choices
    if not raw:
        return None
    values = tuple(str(value) for value in raw)
    for value in values:
        _check_value(path, value)
    return values


def _check_value(path: tuple[str, ...], value: str) -> None:
    if not SAFE_VALUE.match(value):
        raise UnsafeTokenError(path, value)


def _help(formatter: argparse.HelpFormatter, action: argparse.Action, fallback: str) -> str:
    """Help as argparse prints it (`%` expanded), on one line; the name when there is none."""
    if not action.help:
        return fallback
    text = formatter._expand_help(action)
    return " ".join(text.split()) or fallback


def _describe(action: argparse.Action) -> str:
    if action.option_strings:
        return "/".join(action.option_strings)
    return str(action.dest)


def _route(path: tuple[str, ...]) -> str:
    return " ".join(("local-delegate", *path))


# --- Rendering --------------------------------------------------------------------------------

#: Shells that `render` knows, in the order of the `completion` subcommand.
SHELLS = ("powershell", "zsh", "bash")
#: Executables registered by every script (REQ-011): the two entry points of the package.
EXECUTABLES = ("local-delegate", "local-delegate-mcp")

_HEADER_FORMAT = (
    "# local-delegate {version} completion {shell} lang={lang} (generated; do not edit)"
)
_HEADER_RE = re.compile(
    r"^# local-delegate (\S+) completion [a-z]+ lang=[a-z]+ \(generated; do not edit\)$"
)
_HEADER_SLOT = "@@HEADER@@"
_TABLES_SLOT = "@@TABLES@@"
_TEMPLATES = {"powershell": "powershell.ps1", "zsh": "zsh.zsh", "bash": "bash.bash"}
_PS_INDENT = "    "
#: Names of the data functions of the bash and zsh scripts (one `case` per table).
_POSIX_PREFIX = "__local_delegate"


class CompletionTemplateError(RuntimeError):
    """A packaged template is not usable as is (carriage return, missing slot)."""


def render(shell: str, *, lang: str | None = None) -> str:
    """The completion script of `shell`, in `lang` or in the language in force (REQ-042).

    The parser is built inside `i18n.override`, with the argparse scaffold in that language, so
    every help text (including `-h`) comes out in `lang`. Nothing is read from the network or
    written to disk.
    """
    # The parser lives in `cli`, which imports this module for the `completion` subcommand.
    # Resolved by name at call time, so the two modules do not import each other.
    cli = importlib.import_module(f"{__package__}.cli")
    if shell not in SHELLS:
        raise ValueError(f"shell={shell!r}")
    language = lang or i18n.lang()
    with i18n.override(language), cli._argparse_in_language():
        model = build_model(cli.build_parser())
    return _RENDERERS[shell](model, lang=language)


def header(shell: str, lang: str) -> str:
    """First comment line of a script (REQ-009): ASCII, with version, shell and language."""
    from .version import get_version

    return _HEADER_FORMAT.format(version=get_version(), shell=shell, lang=lang)


def header_version(text: str) -> str | None:
    """Version written in the header of a script, or `None` if it has none (REQ-009).

    The header is the first line, or the second one when the first is `#compdef` (zsh).
    """
    for line in text.splitlines()[:2]:
        match = _HEADER_RE.match(line)
        if match:
            return match.group(1)
    return None


def ps_literal(text: str) -> str:
    """ASCII-only PowerShell double-quoted literal (REQ-018).

    Each non-ASCII character goes as `$([char]0xNNNN)`, one per UTF-16 unit (surrogate pairs out
    of the BMP); backtick, double quote and dollar are escaped. So the script reads the same in
    Windows PowerShell 5.1 without BOM and through `Invoke-Expression` with any console code page.
    """
    out = []
    for char in text:
        if char in '`"$':
            out.append("`" + char)
        elif 32 <= ord(char) < 127:
            out.append(char)
        else:
            units = char.encode("utf-16-le")
            for index in range(0, len(units), 2):
                code = int.from_bytes(units[index : index + 2], "little")
                out.append(f"$([char]0x{code:04X})")
    return '"' + "".join(out) + '"'


def _ps_array(items: tuple[str, ...] | list[str]) -> str:
    return "@(" + ", ".join(ps_literal(item) for item in items) + ")"


def render_powershell(model: Model, *, lang: str) -> str:
    """PowerShell script of `model`: header and data tables poured into the template."""
    lines: list[str] = []

    def put(table: str, key: str, value: str) -> None:
        lines.append(f"{_PS_INDENT}${table}[{ps_literal(key)}] = {value}")

    for path, node in model.nodes.items():
        route = " ".join(path)
        put("subs", route, _ps_array([sub.name for sub in node.subcommands]))
        put("opts", route, _ps_array([s for option in node.options for s in option.strings]))
        for sub in node.subcommands:
            put("help", f"{route}|{sub.name}", ps_literal(sub.help))
        for option in node.options:
            for string in option.strings:
                key = f"{route}|{string}"
                put("help", key, ps_literal(option.help))
                if option.arity != ARITY_FLAG:
                    put("arity", key, ps_literal(option.arity))
                    if option.values:
                        put("values", key, _ps_array(option.values))
        for index, positional in enumerate(node.positionals):
            if positional.values:
                put("values", f"{route}|#{index}", _ps_array(positional.values))
    return _fill(_template("powershell"), header("powershell", lang), "\n".join(lines))


def _template(shell: str) -> str:
    """Packaged template, read as bytes: a carriage return would break the scripts (REQ-001)."""
    from importlib.resources import files

    raw = (
        files("local_delegate").joinpath("resources", "completion", _TEMPLATES[shell]).read_bytes()
    )
    if b"\r" in raw:
        raise CompletionTemplateError(f"{_TEMPLATES[shell]}: carriage_return")
    return raw.decode("utf-8")


def _fill(template: str, header_line: str, tables: str) -> str:
    for slot in (_HEADER_SLOT, _TABLES_SLOT):
        if template.count(slot) != 1:
            raise CompletionTemplateError(f"slot={slot}")
    return template.replace(_HEADER_SLOT, header_line).replace(_TABLES_SLOT, tables)


def sh_quote(text: str) -> str:
    """POSIX single-quoted word: nothing inside is expanded, in bash 3.2 and in zsh alike."""
    return "'" + text.replace("'", "'\\''") + "'"


def zsh_describe_item(name: str, description: str) -> str:
    """`name:description` element of `_describe`, with backslash and `:` escaped (REQ-022)."""

    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace(":", "\\:")

    return f"{escape(name)}:{escape(description)}"


def _posix_tables(model: Model) -> dict[str, list[tuple[str, list[str]]]]:
    """Tables shared by bash and zsh: `table -> [(key, words)]`, in declaration order.

    Keys are `<path>` or `<path>|<name>` (`<path>|#<index>` for positionals), with the path joined
    by spaces (`""` is the root), as in the PowerShell script.
    """
    tables: dict[str, list[tuple[str, list[str]]]] = {
        "subs": [],
        "opts": [],
        "arity": [],
        "values": [],
    }
    for path, node in model.nodes.items():
        route = " ".join(path)
        if node.subcommands:
            tables["subs"].append((route, [sub.name for sub in node.subcommands]))
        strings = [s for option in node.options for s in option.strings]
        if strings:
            tables["opts"].append((route, strings))
        for option in node.options:
            if option.arity == ARITY_FLAG:
                continue
            for string in option.strings:
                key = f"{route}|{string}"
                tables["arity"].append((key, [option.arity]))
                if option.values:
                    tables["values"].append((key, list(option.values)))
        for index, positional in enumerate(node.positionals):
            if positional.values:
                tables["values"].append((f"{route}|#{index}", list(positional.values)))
    return tables


def _case_function(name: str, rows: list[tuple[str, str]], default: str) -> list[str]:
    """`name() { case "$1" in 'key') <body> ;; ... *) <default> ;; esac; }`, valid in bash and zsh."""
    lines = [f"{_POSIX_PREFIX}_{name}() {{", '    case "$1" in']
    for key, body in rows:
        lines.append(f"        {sh_quote(key)}) {body} ;;")
    lines += [f"        *) {default} ;;", "    esac", "}"]
    return lines


def render_bash(model: Model, *, lang: str) -> str:
    """bash script of `model` (bash 3.2 and later): data as `case` functions, no descriptions.

    Each function leaves its answer in `_ld_reply`, a local of `_local_delegate` (dynamic scope),
    as one string of words for `compgen -W`. The body is the same in both languages (REQ-008):
    only the header says `lang=`.
    """
    lines: list[str] = []
    for table, rows in _posix_tables(model).items():
        quoted = [(key, f"_ld_reply={sh_quote(' '.join(words))}") for key, words in rows]
        lines += _case_function(table, quoted, "_ld_reply=''")
    return _fill(_template("bash"), header("bash", lang), "\n".join(lines))


def render_zsh(model: Model, *, lang: str) -> str:
    """zsh script of `model`: the bash tables as arrays, plus the `_describe` lists (REQ-022)."""
    lines: list[str] = []
    for table, rows in _posix_tables(model).items():
        arrays = [
            (key, "_ld_reply=(" + " ".join(sh_quote(word) for word in words) + ")")
            for key, words in rows
        ]
        lines += _case_function(table, arrays, "_ld_reply=()")
    described: list[tuple[str, str]] = []
    for path, node in model.nodes.items():
        route = " ".join(path)
        subs = [zsh_describe_item(sub.name, sub.help) for sub in node.subcommands]
        opts = [
            zsh_describe_item(string, option.help)
            for option in node.options
            for string in option.strings
        ]
        for kind, items in (("subs", subs), ("opts", opts)):
            if items:
                body = "_ld_reply=(" + " ".join(sh_quote(item) for item in items) + ")"
                described.append((f"{route}|{kind}", body))
    lines += _case_function("describe", described, "_ld_reply=()")
    return _fill(_template("zsh"), header("zsh", lang), "\n".join(lines))


_RENDERERS = {"powershell": render_powershell, "zsh": render_zsh, "bash": render_bash}


# --- Installation manifest (REQ-043) ----------------------------------------------------------

#: Name of the manifest inside the completion directory (`shell_profiles.completion_dir`).
MANIFEST_NAME = "installed.json"
#: Schema version of the manifest.
MANIFEST_VERSION = 1


class ManifestUnreadableError(ValueError):
    """The manifest exists but cannot be read or does not follow the schema of REQ-043."""


def manifest_path(directory: Path) -> Path:
    return Path(directory) / MANIFEST_NAME


def read_manifest(directory: Path) -> dict | None:
    """The manifest of `directory`, `None` if there is none.

    Raises `ManifestUnreadableError` when it exists but is not valid JSON or not the schema of
    REQ-043; whoever reads it decides what to do (`uninstall` goes on with the candidates, the
    check of `doctor` says `unknown`). Nothing else is raised.
    """
    path = manifest_path(directory)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ManifestUnreadableError(f"{path}: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ManifestUnreadableError(f"{path}: {exc}") from exc
    if not _valid_manifest(data):
        raise ManifestUnreadableError(f"{path}: schema")
    return data


def _valid_manifest(data: object) -> bool:
    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        return False
    if not isinstance(data.get("lang"), str) or not isinstance(data.get("generator"), str):
        return False
    shells = data.get("shells")
    if not isinstance(shells, list):
        return False
    for entry in shells:
        if not isinstance(entry, dict) or entry.get("shell") not in SHELLS:
            return False
        if not isinstance(entry.get("file"), str) or not isinstance(entry.get("profiles"), list):
            return False
        for profile in entry["profiles"]:
            if not isinstance(profile, dict) or not isinstance(profile.get("path"), str):
                return False
            if not all(isinstance(profile.get(k), bool) for k in ("created", "created_parent")):
                return False
    return True


def merge_manifest(
    existing: dict | None,
    *,
    generator: str,
    lang: str,
    written: dict[str, tuple[str, list[dict]]],
) -> dict:
    """The manifest after an `install`: `existing` plus the shells in `written`.

    `written` maps a shell to its completion file and the profiles that carry its block. The
    shells not in `written` keep their entry; a profile already listed keeps its original
    `created`/`created_parent` (REQ-043), and one listed before but not touched now stays listed,
    so that `uninstall` still cleans it.
    """
    previous = {entry["shell"]: entry for entry in (existing or {}).get("shells", [])}
    shells = []
    for shell in SHELLS:
        if shell in written:
            file, profiles = written[shell]
            merged = [dict(p) for p in previous.get(shell, {}).get("profiles", [])]
            listed = {p["path"] for p in merged}
            merged += [dict(p) for p in profiles if p["path"] not in listed]
            shells.append({"shell": shell, "file": file, "profiles": merged})
        elif shell in previous:
            shells.append(previous[shell])
    return {"version": MANIFEST_VERSION, "generator": generator, "lang": lang, "shells": shells}


def manifest_without(manifest: dict, shells: tuple[str, ...] | list[str]) -> dict | None:
    """`manifest` without the entries of `shells`; `None` when no entry is left (REQ-032)."""
    left = [entry for entry in manifest.get("shells", []) if entry.get("shell") not in shells]
    if not left:
        return None
    return {**manifest, "shells": left}


def manifest_bytes(data: dict) -> bytes:
    """The manifest as written to disk: UTF-8, LF, two-space indent, final newline."""
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
