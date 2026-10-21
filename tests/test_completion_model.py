"""Model of the completion generator (SDD cli-completion, REQ-003 to REQ-007).

`completion.build_model` walks the real parser; these tests check it against an independent walk,
the hidden names, the fixed values of `backend-params`, the arity of options and the constructs and
tokens it must refuse. Each refusal has its own test parser, so a check that stops refusing makes
its case fail.
"""

from __future__ import annotations

import argparse

import pytest

from local_delegate import backend_params, cli, completion, deprecations, i18n
from local_delegate.completion import (
    ARITY_FLAG,
    ARITY_OPTIONAL,
    ARITY_REQUIRED,
    UnsafeTokenError,
    UnsupportedConstructError,
    build_model,
)


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()


@pytest.fixture
def real_model():
    return build_model(cli.build_parser())


def _option(node: completion.Node, string: str) -> completion.Option | None:
    return next((o for o in node.options if string in o.strings), None)


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    return next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)),
        None,
    )


def _independent_paths(parser: argparse.ArgumentParser) -> set[tuple[str, ...]]:
    """Paths from the pseudo actions argparse lists in the help, minus the retired commands."""
    retired = {e.old for e in deprecations.cli_entries()}
    paths = {()}
    stack: list[tuple[tuple[str, ...], argparse.ArgumentParser]] = [((), parser)]
    while stack:
        path, current = stack.pop()
        action = _subparsers(current)
        if action is None:
            continue
        listed = {pseudo.metavar for pseudo in action._get_subactions()}
        for name, child in action.choices.items():
            if name in listed and name not in retired:
                paths.add((*path, name))
                stack.append(((*path, name), child))
    return paths


# --- REQ-003: the model comes from the real parser ------------------------------------------------


@pytest.mark.parametrize("lang", ["es", "en"])
def test_real_parser_builds(lang, monkeypatch):
    """Guard: the real parser has no unsupported construct and no unsafe token, in both languages."""
    _set_language(monkeypatch, lang)
    model = build_model(cli.build_parser())
    assert len(model.nodes) >= 20
    for node in model.nodes.values():
        for option in node.options:
            assert option.help and "\n" not in option.help and "%(" not in option.help


def test_paths_match_independent_walk(real_model):
    parser = cli.build_parser()
    expected = _independent_paths(parser)
    assert ("backend-params", "set") in expected  # the independent walk reaches the second level
    assert set(real_model.nodes) == expected
    for path, node in real_model.nodes.items():
        assert node.path == path
        assert {(*path, s.name) for s in node.subcommands} <= set(real_model.nodes)


def test_every_node_lists_help_options(real_model):
    for node in real_model.nodes.values():
        help_option = _option(node, "--help")
        assert help_option is not None and help_option.strings == ("-h", "--help")
        assert help_option.arity == ARITY_FLAG


def test_subcommands_carry_help(real_model):
    root = real_model.nodes[()]
    by_name = {s.name: s.help for s in root.subcommands}
    assert by_name["backend-params"] == i18n.t("cli.help.backend_params")


def test_new_subcommand_appears_without_touching_the_generator():
    parser = cli.build_parser()
    _subparsers(parser).add_parser("brand-new", help="brand_new_help").add_argument(
        "--mode", choices=("one", "two"), help="mode_help"
    )
    node = build_model(parser).nodes[("brand-new",)]
    option = _option(node, "--mode")
    assert option == completion.Option(("--mode",), "mode_help", ARITY_REQUIRED, ("one", "two"))


def test_build_model_does_not_modify_the_parser():
    parser = cli.build_parser()
    action_ids = [id(a) for a in parser._actions]
    before = parser.format_help()
    bp = _subparsers(parser).choices["backend-params"]
    bp_before = bp.format_help()
    build_model(parser)
    assert parser.format_help() == before
    assert bp.format_help() == bp_before
    assert [id(a) for a in parser._actions] == action_ids


# --- REQ-004: hidden things -----------------------------------------------------------------------


def _all_parsers(parser: argparse.ArgumentParser):
    """Every parser with its path, hidden subparsers included."""
    stack = [((), parser)]
    while stack:
        path, current = stack.pop()
        yield path, current
        action = _subparsers(current)
        if action is not None:
            stack.extend(((*path, name), child) for name, child in action.choices.items())


def test_hidden_real_names(real_model):
    """The real old CLI names (from the registry) and `benchmark --api-key` are not offered.

    REQ-022 (SDD retire-legacy-aliases): the old names are gone from the parser too, so neither
    the parser nor the model has them.
    """
    parsers = list(_all_parsers(cli.build_parser()))
    commands = {path[-1] for path, _ in parsers if path}
    options = {s for _, p in parsers for s in p._option_string_actions}
    offered_commands = {s.name for node in real_model.nodes.values() for s in node.subcommands}
    offered_options = {
        s for node in real_model.nodes.values() for o in node.options for s in o.strings
    }
    checked = 0
    for entry in deprecations.cli_entries():
        if deprecations.effective_kind(entry) == "cli_command":
            # Control: the successor is in the parser and offered, so the search finds names.
            assert entry.new in commands and entry.new in offered_commands
            assert entry.old not in commands
            assert entry.old not in offered_commands
            assert not any(entry.old in path for path in real_model.nodes)
        else:
            assert entry.new in options and entry.new in offered_options
            assert entry.old not in options
            assert entry.old not in offered_options
        checked += 1
    assert checked >= 2  # today: the old `recompute-cost` command and its old option
    assert "--api-key" in dict(parsers)[("benchmark",)]._option_string_actions
    assert _option(real_model.nodes[("benchmark",)], "--api-key") is None
    assert _option(real_model.nodes[("recompute-cost",)], "--reset-calibration") is not None


def _parser_with_named_things() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-delegate")
    sub = parser.add_subparsers(dest="command")
    old = sub.add_parser("old-cmd", help="old_cmd_help")
    old.add_argument("--flag", action="store_true", help="flag_help")
    keep = sub.add_parser("keep", help="keep_help")
    keep.add_argument("--old-opt", "--new-opt", help="opt_help")
    keep.add_argument("--only-old", help="only_old_help")
    sub.add_parser("no-help")  # without help: hidden
    return parser


def test_hidden_deprecated_names_even_with_help(monkeypatch):
    # Control: without the registry entries everything with help is offered.
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", ())
    model = build_model(_parser_with_named_things())
    assert {s.name for s in model.nodes[()].subcommands} == {"old-cmd", "keep"}
    assert _option(model.nodes[("keep",)], "--old-opt").strings == ("--old-opt", "--new-opt")

    monkeypatch.setattr(
        deprecations,
        "DEPRECATED_NAMES",
        (
            deprecations.DeprecatedName("cli_command", "old-cmd", "keep", "UNRELEASED"),
            deprecations.DeprecatedName("cli_option", "--old-opt", "--new-opt", "UNRELEASED"),
            deprecations.DeprecatedName("cli_option", "--only-old", "--new-opt", "UNRELEASED"),
            # Other kinds do not hide a CLI name.
            deprecations.DeprecatedName("env_var", "keep", "OTHER", "UNRELEASED"),
        ),
    )
    model = build_model(_parser_with_named_things())
    assert [s.name for s in model.nodes[()].subcommands] == ["keep"]
    assert ("old-cmd",) not in model.nodes and ("no-help",) not in model.nodes
    keep = model.nodes[("keep",)]
    assert _option(keep, "--new-opt").strings == ("--new-opt",)
    assert _option(keep, "--only-old") is None


def test_hidden_retired_names_with_a_new_name(monkeypatch):
    """REQ-022: a retired entry hides its old name by its former surface (`retired_from`)."""
    retired = {"kind": "retired", "warn_until": "0.40.0"}
    monkeypatch.setattr(
        deprecations,
        "DEPRECATED_NAMES",
        (
            deprecations.DeprecatedName(
                old="old-cmd",
                new="keep",
                introduced="0.38.0",
                retired_from="cli_command",
                **retired,
            ),
            deprecations.DeprecatedName(
                old="--old-opt",
                new="--new-opt",
                introduced="0.38.0",
                retired_from="cli_option",
                **retired,
            ),
            # Retired from another surface: it does not hide a CLI name.
            deprecations.DeprecatedName(
                old="--only-old",
                new="OTHER",
                introduced="0.38.0",
                retired_from="env_var",
                **retired,
            ),
        ),
    )
    assert deprecations.class_problems() == []
    model = build_model(_parser_with_named_things())
    assert [s.name for s in model.nodes[()].subcommands] == ["keep"]
    keep = model.nodes[("keep",)]
    assert _option(keep, "--new-opt").strings == ("--new-opt",)
    assert _option(keep, "--only-old") is not None


def test_suppressed_actions_are_hidden():
    parser = argparse.ArgumentParser(prog="local-delegate")
    parser.add_argument("--secret", help=argparse.SUPPRESS)
    parser.add_argument("hidden_positional", nargs="?", help=argparse.SUPPRESS)
    node = build_model(parser).nodes[()]
    assert _option(node, "--secret") is None
    assert node.positionals == ()


# --- REQ-005: fixed values ------------------------------------------------------------------------


def test_backend_params_positionals(real_model):
    roles = tuple(backend_params.ROLES)
    keys = tuple(backend_params.ALLOWED_KEYS)
    values = {
        path[1]: [p.values for p in node.positionals]
        for path, node in real_model.nodes.items()
        if path[:1] == ("backend-params",) and len(path) == 2
    }
    assert values == {
        "show": [],
        "set": [roles, keys, None],
        "unset": [roles, keys],
        "reset": [roles],
    }


def test_completion_values_win_over_choices():
    parser = argparse.ArgumentParser(prog="local-delegate")
    action = parser.add_argument("--pick", choices=("a", "b"), help="pick_help")
    action.completion_values = ("x", "y")
    parser.add_argument("--number", type=int, choices=(1, 2), help="number_help")
    node = build_model(parser).nodes[()]
    assert _option(node, "--pick").values == ("x", "y")
    assert _option(node, "--number").values == ("1", "2")


# --- arity ----------------------------------------------------------------------------------------


def test_update_version_requires_a_value_and_root_version_is_a_flag(real_model):
    assert _option(real_model.nodes[()], "--version").arity == ARITY_FLAG
    assert _option(real_model.nodes[("update",)], "--version").arity == ARITY_REQUIRED


def test_arity_of_each_supported_action():
    parser = argparse.ArgumentParser(prog="local-delegate")
    parser.add_argument("--store", help="h")
    parser.add_argument("--maybe", nargs="?", const="c", help="h")
    parser.add_argument("--yes", action="store_true", help="h")
    parser.add_argument("--no", action="store_false", help="h")
    parser.add_argument("--const", action="store_const", const=1, help="h")
    parser.add_argument("--many", action="append", help="h")
    parser.add_argument("--tag", action="append_const", const=1, help="h")
    parser.add_argument("--verbose", action="count", help="h")
    parser.add_argument("--version", action="version", version="1")
    node = build_model(parser).nodes[()]
    arity = {o.strings[-1]: o.arity for o in node.options}
    assert arity == {
        "--help": ARITY_FLAG,
        "--store": ARITY_REQUIRED,
        "--maybe": ARITY_OPTIONAL,
        "--yes": ARITY_FLAG,
        "--no": ARITY_FLAG,
        "--const": ARITY_FLAG,
        "--many": ARITY_REQUIRED,
        "--tag": ARITY_FLAG,
        "--verbose": ARITY_FLAG,
        "--version": ARITY_FLAG,
    }
    assert all(o.values is None for o in node.options)


# --- help text ------------------------------------------------------------------------------------


def test_help_is_expanded_collapsed_and_falls_back_to_the_name():
    parser = argparse.ArgumentParser(prog="local-delegate")
    parser.add_argument("--port", type=int, default=8080, help="port,\n   default %(default)s")
    parser.add_argument("--bare")
    parser.add_argument("target", metavar="TARGET")
    parser.add_argument("name")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="run %(prog)s  now")
    node = build_model(parser).nodes[()]
    assert _option(node, "--port").help == "port, default 8080"
    assert _option(node, "--bare").help == "--bare"
    assert [p.help for p in node.positionals] == ["TARGET", "name"]
    assert node.subcommands[0].help.startswith("run local-delegate")
    assert "  " not in node.subcommands[0].help


# --- REQ-006: unsupported constructs --------------------------------------------------------------


def _sub(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    return parser.add_subparsers(dest="command").add_parser("nested", help="nested_help")


def _nargs(value):
    def build(p):
        p.add_argument("--opt", nargs=value, help="h")

    return build


def _positional_nargs(value):
    def build(p):
        p.add_argument("items", nargs=value, help="h")

    return build


UNSUPPORTED = {
    "nargs_star": _nargs("*"),
    "nargs_plus": _nargs("+"),
    "nargs_two": _nargs(2),
    "nargs_remainder": _nargs(argparse.REMAINDER),
    "positional_star": _positional_nargs("*"),
    "positional_plus": _positional_nargs("+"),
    "positional_two": _positional_nargs(2),
    "extend": lambda p: p.add_argument("--opt", action="extend", help="h"),
    "boolean_optional": lambda p: p.add_argument(
        "--opt", action=argparse.BooleanOptionalAction, help="h"
    ),
    "short_option": lambda p: p.add_argument("-v", "--verbose", action="store_true", help="h"),
    "subparser_alias": lambda p: p.add_subparsers().add_parser("x", aliases=["y"], help="h"),
}


@pytest.mark.parametrize("build", UNSUPPORTED.values(), ids=UNSUPPORTED.keys())
def test_unsupported_construct_raises_with_its_path(build):
    parser = argparse.ArgumentParser(prog="local-delegate")
    build(_sub(parser))
    with pytest.raises(UnsupportedConstructError) as excinfo:
        build_model(parser)
    assert excinfo.value.path == ("nested",)
    assert "local-delegate nested" in str(excinfo.value)


def test_unsupported_prefix_chars_raises_with_its_path():
    parser = argparse.ArgumentParser(prog="local-delegate")
    parser.add_subparsers(dest="command").add_parser("nested", help="nested_help", prefix_chars="+")
    with pytest.raises(UnsupportedConstructError) as excinfo:
        build_model(parser)
    assert excinfo.value.path == ("nested",)
    assert "prefix_chars" in str(excinfo.value)


def test_unsupported_construct_names_the_action():
    parser = argparse.ArgumentParser(prog="local-delegate")
    _sub(parser).add_argument("--opt", nargs="*", help="h")
    with pytest.raises(UnsupportedConstructError, match=r"local-delegate nested --opt: nargs='\*'"):
        build_model(parser)


# --- REQ-007: safe tokens -------------------------------------------------------------------------

UNSAFE_VALUES = ["a b", "x;y", "ñ", "a'b", 'a"b', "a$b", "a`b", ""]


@pytest.mark.parametrize("value", UNSAFE_VALUES)
def test_unsafe_choice_raises(value):
    parser = argparse.ArgumentParser(prog="local-delegate")
    _sub(parser).add_argument("--opt", choices=["ok", value], help="h")
    with pytest.raises(UnsafeTokenError) as excinfo:
        build_model(parser)
    assert excinfo.value.path == ("nested",) and excinfo.value.value == value
    assert "local-delegate nested" in str(excinfo.value)


def test_unsafe_completion_values_raise():
    parser = argparse.ArgumentParser(prog="local-delegate")
    _sub(parser).add_argument("role", help="h").completion_values = ("ok", "x;y")
    with pytest.raises(UnsafeTokenError, match="x;y"):
        build_model(parser)


def test_unsafe_subcommand_name_raises():
    parser = argparse.ArgumentParser(prog="local-delegate")
    parser.add_subparsers(dest="command").add_parser("bad name", help="h")
    with pytest.raises(UnsafeTokenError) as excinfo:
        build_model(parser)
    assert excinfo.value.path == () and excinfo.value.value == "bad name"


@pytest.mark.parametrize("string", ["--a.b", "--ñame", "---x", "--_x"])
def test_unsafe_option_string_raises(string):
    parser = argparse.ArgumentParser(prog="local-delegate")
    _sub(parser).add_argument(string, help="h")
    with pytest.raises(UnsafeTokenError) as excinfo:
        build_model(parser)
    assert excinfo.value.value == string


def test_safe_tokens_pass():
    parser = argparse.ArgumentParser(prog="local-delegate")
    _sub(parser).add_argument(
        "--opt-2_x", choices=["a-b", "c_d", "e.f", "g:h", "i/j", "k+l", "M9"], help="h"
    )
    node = build_model(parser).nodes[("nested",)]
    assert _option(node, "--opt-2_x").values == ("a-b", "c_d", "e.f", "g:h", "i/j", "k+l", "M9")
