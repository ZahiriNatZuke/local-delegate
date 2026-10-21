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
in `_choices_actions` and any name registered in `deprecations` as `cli_command`/`cli_option`.

Fixed values come from the action's own `completion_values` attribute (read only here) or from
its `choices` (REQ-005).
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass

from . import deprecations

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

_HIDDEN_KINDS = frozenset({"cli_command", "cli_option"})


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
    entries = deprecations.DEPRECATED_NAMES
    hidden = frozenset(entry.old for entry in entries if entry.kind in _HIDDEN_KINDS)
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
