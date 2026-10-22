"""The bash and zsh completion scripts, loaded in real shells (SDD cli-completion).

REQ-011 to REQ-017, REQ-021, REQ-022 and REQ-038. One process per shell runs every case and
prints one line per case:

- **bash** (`bash`, and `bash3` = `/bin/bash` 3.2 on macOS): `bash --norc --noprofile` with
  `COMP_WORDS`/`COMP_CWORD` simulated. The runner calls the function that `complete -p <command>`
  names, as readline does, so a case also proves the registration (REQ-011). First the control
  without the script (REQ-038 (b)), then the real script, then one rendered from a test parser
  with an option of optional value (REQ-014; the real CLI gets `--shell-completion` in L3b).
- **zsh, deterministic**: `zsh -f` with doubles of `compdef`, `_describe`, `compadd`, `compset`
  and `_files` that filter by `PREFIX` the way zsh does, and a call to the registered function
  with `words`/`CURRENT` (research-shells §5).
- **zsh, real** (smoke): `zpty` with `compinit -u -D` and Tab, with the script sourced and as a
  `_local-delegate` file in `fpath`, plus a session without the script (control (b)) and the
  `compinit` guard of a bare `source`.

Every process runs in an empty temporary directory with `HOME`/`ZDOTDIR` pointing at it.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path

import pytest
from completion_shells import SHELL_TIMEOUT, require_or_skip

from local_delegate import backend_params, cli, completion, i18n

pytestmark = pytest.mark.xdist_group("completion_posix")

ROLES = list(backend_params.ROLES)
KEYS = list(backend_params.ALLOWED_KEYS)
#: Cursor on the last word.
LAST = -1


def _case(case_id: str, *words: str, cword: int = LAST) -> tuple[str, int, tuple[str, ...]]:
    """A case: the words of the line (the last one is the word under the cursor)."""
    return case_id, cword, ("local-delegate", *words)


# Cases common to both shells: same id, same line, same expectation unless a test says otherwise.
COMMON_CASES = [
    # REQ-011
    ("mcp_alias", LAST, ("local-delegate-mcp", "ins")),
    # REQ-012
    _case("root", ""),
    _case("root_ba", "ba"),
    _case("bp", "backend-params", ""),
    _case("llamaswap", "llamaswap", ""),
    _case("test_window", "test-window", ""),
    _case("case_sensitive", "BACKEND-PARAMS", ""),
    _case("after_flag", "--version", "backend-params", ""),
    # REQ-013
    _case("install_mcp", "install", "--mcp"),
    _case("serve_dashdash", "serve", "--"),
    _case("append_again", "install", "--clients", "claude", "--cli"),
    # REQ-014
    _case("mcp_mode", "install", "--mcp-mode", ""),
    _case("log_level", "serve", "--log-level", "w"),
    _case("benchmark_role", "benchmark", "--role", ""),
    _case("reset_calibration", "recompute-cost", "--reset-calibration", ""),
    # REQ-015
    _case("set_role", "backend-params", "set", ""),
    _case("set_key", "backend-params", "set", "code", ""),
    _case("set_value", "backend-params", "set", "code", "top_p", ""),
    _case("unset_t", "backend-params", "unset", "vision", "t"),
    _case("reset_role", "backend-params", "reset", ""),
    _case("completion", "completion", ""),
    # REQ-016: free value.
    _case("free_value", "install", "--home", ""),
    # REQ-017 / REQ-038 (a)
    _case("no_match_root", "zzz"),
    _case("no_match_set", "backend-params", "set", "zzz"),
    # Cursor in the middle of the line, on `backend-params` (index 1 of COMP_WORDS; 2 in zsh).
    _case("mid_line", "backend-params", "set", "code", cword=1),
]
#: readline splits `--option=value` at `=` (COMP_WORDBREAKS): `=` arrives as a word of its own.
BASH_EQ_CASES = [
    _case("mcp_mode_eq", "install", "--mcp-mode", "=", "h"),
    _case("mcp_mode_eq_empty", "install", "--mcp-mode", "="),
    _case("after_eq_value", "install", "--mcp-mode", "=", "http", "--mcp"),
    # Without `=` in COMP_WORDBREAKS the word stays whole and the answer keeps the prefix.
    _case("mcp_mode_joined", "install", "--mcp-mode=h"),
]
#: zsh keeps `--option=value` as one word; `compset -P '*='` moves `--option=` to IPREFIX.
ZSH_EQ_CASES = [
    _case("mcp_mode_eq", "install", "--mcp-mode=h"),
    _case("mcp_mode_eq_empty", "install", "--mcp-mode="),
    _case("after_eq_value", "install", "--mcp-mode=http", "--mcp"),
]
UNLOADED_CASES = [_case("unloaded_set", "backend-params", "set", "")]
SYNTHETIC_CASES = [
    _case("optional_values", "--shell-x", ""),
    _case("optional_then_option", "--shell-x", "--d"),
    _case("optional_consumed", "--shell-x", "zsh", "--d"),
    _case("optional_consumed_sub", "--shell-x", "zsh", ""),
    # The option right after an optional value is an option, not that value (argparse does so).
    _case("optional_then_option_value", "--shell-x", "--mode", ""),
]


def _synthetic_model() -> completion.Model:
    parser = argparse.ArgumentParser(prog="local-delegate")
    parser.add_argument("--shell-x", nargs="?", choices=("auto", "zsh"), help="optional value")
    parser.add_argument("--dry-run", action="store_true", help="flag")
    parser.add_argument("--mode", choices=("one", "two"), help="required value")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("zeta", help="only subcommand")
    return completion.build_model(parser)


def _root_subcommands() -> list[str]:
    model = completion.build_model(cli.build_parser())
    return [sub.name for sub in model.nodes[()].subcommands]


def _calls(cases: list[tuple[str, int, tuple[str, ...]]], cword_base: int) -> str:
    """`run_case <id> <cword> <words...>` lines; `cword_base` is 0 in bash and 1 in zsh."""
    lines = []
    for case_id, cword, words in cases:
        index = -1 if cword == LAST else cword + cword_base
        lines.append(" ".join(shlex.quote(part) for part in (case_id, str(index), *words)))
    return "\n".join(f"run_case {line}" for line in lines)


def _workdir(tmp_path_factory, name: str) -> tuple[Path, Path]:
    work = tmp_path_factory.mktemp(name)
    empty = work / "empty"
    empty.mkdir()
    return work, empty


def _env(work: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(work)
    env["ZDOTDIR"] = str(work)
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    return env


def _run(command: list[str], work: Path, empty: Path) -> str:
    proc = subprocess.run(
        command,
        cwd=empty,
        env=_env(work),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=SHELL_TIMEOUT,
        check=False,
    )
    stderr = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 0, f"{command[0]} exit={proc.returncode}\n{stderr}"
    return proc.stdout.decode("utf-8")


def _write(path: Path, text: str) -> str:
    path.write_bytes(text.encode("utf-8"))
    return path.as_posix()


def _parse(output: str) -> tuple[dict[str, list[str]], dict[str, str]]:
    """`case<TAB>id<US>entry<US>entry...` lines into `{id: entries}`; other lines into `{tag: rest}`."""
    cases: dict[str, list[str]] = {}
    extra: dict[str, str] = {}
    for line in output.splitlines():
        tag, _, rest = line.partition("\t")
        if tag == "case":
            case_id, *entries = rest.split("\x1f")
            cases[case_id] = entries
        elif tag:
            extra[tag] = rest
    return cases, extra


# --- bash ---------------------------------------------------------------------------------------

# Valid in bash 3.2. Calls the function that `complete -p` registered for the command, like
# readline does, and prints COMPREPLY separated by US (0x1f).
BASH_RUNNER = r"""
run_case() {
    local id="$1" cword="$2" spec func reply
    shift 2
    COMP_WORDS=("$@")
    if [ "$cword" -lt 0 ]; then COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 )); else COMP_CWORD=$cword; fi
    COMP_LINE="$*"
    COMP_POINT=${#COMP_LINE}
    COMPREPLY=()
    spec=$(complete -p "${COMP_WORDS[0]##*/}" 2>/dev/null)
    if [ -n "$spec" ]; then
        func=${spec##*-F }
        func=${func%% *}
        "$func" "${COMP_WORDS[0]}" "${COMP_WORDS[COMP_CWORD]}" "${COMP_WORDS[COMP_CWORD-1]}"
    fi
    printf 'case\t%s' "$id"
    for reply in "${COMPREPLY[@]}"; do printf '\037%s' "$reply"; done
    printf '\n'
}
printf 'major\t%s\n' "${BASH_VERSINFO[0]}"
"""


@pytest.fixture(
    scope="module",
    params=[
        pytest.param("bash", marks=pytest.mark.shell("bash"), id="bash"),
        pytest.param("bash3", marks=pytest.mark.shell("bash3"), id="bash3"),
    ],
)
def bash_run(request, tmp_path_factory):
    name = request.param
    executable = require_or_skip(name)
    work, empty = _workdir(tmp_path_factory, name)
    script = _write(work / "local-delegate.bash", completion.render("bash"))
    synthetic = _write(
        work / "synthetic.bash", completion.render_bash(_synthetic_model(), lang=i18n.lang())
    )
    body = "\n".join(
        [
            BASH_RUNNER,
            _calls(UNLOADED_CASES, 0),
            f"source {shlex.quote(script)}",
            "printf 'spec\\t%s\\n' \"$(complete -p local-delegate)\"",
            "printf 'spec_mcp\\t%s\\n' \"$(complete -p local-delegate-mcp)\"",
            _calls(COMMON_CASES + BASH_EQ_CASES, 0),
            f"source {shlex.quote(synthetic)}",
            _calls([(f"synthetic_{i}", c, w) for i, c, w in SYNTHETIC_CASES], 0),
        ]
    )
    runner = _write(work / "runner.bash", body + "\n")
    output = _run([executable, "--norc", "--noprofile", runner], work, empty)
    cases, extra = _parse(output)
    return name, cases, extra


def test_bash_version(bash_run):
    """REQ-021: `bash3` is really bash 3 (macOS `/bin/bash`), so the 3.2 claim is measured."""
    name, _, extra = bash_run
    if name == "bash3":
        assert extra["major"] == "3"
    else:
        assert extra["major"].isdigit()


def test_bash_registration_uses_default_fallback(bash_run):
    """REQ-016 and REQ-021: `complete -o default -F _local_delegate` for both executables."""
    _, _, extra = bash_run
    for key, command in (("spec", "local-delegate"), ("spec_mcp", "local-delegate-mcp")):
        spec = extra[key].split()
        assert spec[0] == "complete" and spec[-1] == command, extra[key]
        assert "-o" in spec and spec[spec.index("-o") + 1] == "default", extra[key]
        assert spec[spec.index("-F") + 1] == "_local_delegate", extra[key]


def test_bash_registered_names(bash_run):
    """REQ-011."""
    _, cases, _ = bash_run
    assert cases["mcp_alias"] == ["install"]


def test_bash_subcommands_at_every_level(bash_run):
    """REQ-012, including case sensitivity and a flag before the subcommand."""
    _, cases, _ = bash_run
    root = _root_subcommands()
    assert cases["root"] == root
    assert len(root) == 14
    assert cases["root_ba"] == ["backend-params"]
    assert cases["bp"] == ["show", "set", "unset", "reset"]
    assert cases["llamaswap"] == ["residency"]
    assert cases["test_window"] == ["start", "stop", "add", "list"]
    assert cases["case_sensitive"] == root
    assert cases["after_flag"] == ["show", "set", "unset", "reset"]
    assert cases["mid_line"] == ["backend-params"]


def test_bash_options_of_the_node(bash_run):
    """REQ-013."""
    _, cases, _ = bash_run
    assert cases["install_mcp"] == ["--mcp-mode"]
    assert cases["serve_dashdash"] == ["--help", "--host", "--port", "--log-level"]
    assert cases["append_again"] == ["--clients"]


def test_bash_option_values(bash_run):
    """REQ-014: with `=` as a word of its own, and with the whole word."""
    _, cases, _ = bash_run
    assert cases["mcp_mode"] == ["stdio", "http"]
    assert cases["mcp_mode_eq"] == ["http"]
    assert cases["mcp_mode_eq_empty"] == ["stdio", "http"]
    assert cases["after_eq_value"] == ["--mcp-mode"]
    assert cases["mcp_mode_joined"] == ["--mcp-mode=http"]
    assert cases["log_level"] == ["warning"]
    assert cases["benchmark_role"] == ROLES
    assert cases["reset_calibration"] == ["five_hour", "seven_day"]


def test_bash_option_with_optional_value(bash_run):
    """REQ-014: an optional value offers its values, and options when the word starts with `-`."""
    _, cases, _ = bash_run
    assert cases["synthetic_optional_values"] == ["auto", "zsh"]
    assert cases["synthetic_optional_then_option"] == ["--dry-run"]
    assert cases["synthetic_optional_consumed"] == ["--dry-run"]
    assert cases["synthetic_optional_consumed_sub"] == ["zeta"]
    assert cases["synthetic_optional_then_option_value"] == ["one", "two"]


def test_bash_positionals_by_position(bash_run):
    """REQ-015."""
    _, cases, _ = bash_run
    assert cases["set_role"] == ROLES
    assert cases["set_key"] == KEYS
    assert len(KEYS) == 21
    assert cases["set_value"] == []
    assert cases["unset_t"] == ["temperature", "top_k", "top_p", "typical_p"]
    assert cases["reset_role"] == ROLES
    assert cases["completion"] == ["powershell", "zsh", "bash"]


def test_bash_free_value_is_left_to_readline(bash_run):
    """REQ-016: COMPREPLY empty; `-o default` (checked above) gives the paths."""
    _, cases, _ = bash_run
    assert cases["free_value"] == []


def test_bash_no_match_gives_nothing(bash_run):
    """REQ-017 and control (a) of REQ-038."""
    _, cases, _ = bash_run
    assert cases["no_match_root"] == []
    assert cases["no_match_set"] == []


def test_bash_unloaded_completer_gives_nothing(bash_run):
    """Control (b) of REQ-038: without the script, no `mechanical`: the cases measure the script."""
    _, cases, _ = bash_run
    assert cases["unloaded_set"] == []


# --- zsh, deterministic ---------------------------------------------------------------------------

# Doubles of the completion system. Each records what zsh would offer, filtered by PREFIX like
# zsh's own matching: `d<TAB>name<TAB>description` (_describe), `a<TAB>word` (compadd), `f`
# (_files) and `i<TAB>IPREFIX` when compset moved a prefix.
ZSH_STUB_RUNNER = r"""
typeset -A _ld_registered
typeset -a _ld_out
compdef() { local f=$1 c; shift; for c in "$@"; do _ld_registered[$c]=$f; done }
_ld_match() { [[ "${1[1,${#PREFIX}]}" == "$PREFIX" ]] }
_describe() {
    local item tmp name desc
    integer found=1
    for item in "${(@P)4}"; do
        tmp=${item//\\\\/$'\001'}
        tmp=${tmp//\\:/$'\002'}
        name=${tmp%%:*}
        desc=${tmp#*:}
        name=${${name//$'\002'/:}//$'\001'/\\}
        desc=${${desc//$'\002'/:}//$'\001'/\\}
        if _ld_match "$name"; then _ld_out+=("d"$'\t'"$name"$'\t'"$desc"); found=0; fi
    done
    return found
}
compadd() {
    local -a candidates
    integer found=1
    while (( $# )); do
        case $1 in
            -a) candidates+=("${(@P)2}"); shift 2 ;;
            --) shift; candidates+=("$@"); break ;;
            *) shift ;;
        esac
    done
    local word
    for word in "${candidates[@]}"; do
        if _ld_match "$word"; then _ld_out+=("a"$'\t'"$word"); found=0; fi
    done
    return found
}
compset() {
    if [[ $1 == -P && $PREFIX == *=* ]]; then
        IPREFIX="$IPREFIX${PREFIX%%=*}="
        PREFIX=${PREFIX#*=}
        _ld_out+=("i"$'\t'"$IPREFIX")
        return 0
    fi
    return 1
}
_files() { _ld_out+=("f"); return 0 }
show_registered() {
    print -r -- "registered"$'\t'"${_ld_registered[local-delegate]} ${_ld_registered[local-delegate-mcp]}"
}
run_case() {
    local id=$1 f
    integer cword=$2
    shift 2
    words=("$@")
    if (( cword < 0 )); then CURRENT=${#words}; else CURRENT=$cword; fi
    PREFIX=${words[CURRENT]}
    IPREFIX=''
    _ld_out=()
    f=${_ld_registered[${words[1]:t}]}
    if [[ -n $f ]]; then $f; fi
    print -rn -- "case"$'\t'"$id"
    local entry
    for entry in "${_ld_out[@]}"; do print -rn -- $'\037'"$entry"; done
    print
}
"""

# A real interactive zsh in a pseudo terminal (research-shells §2). Each session types a line,
# presses Tab twice and prints what zsh listed or inserted between two markers.
ZSH_PTY_RUNNER = r"""
zmodload zsh/zpty
# The markers are typed split by '' so the echo of the typed line never matches the pattern.
# Each read waits for the prompt (@P@) that follows the marker: a line typed before zle puts the
# terminal in raw mode arrives in cooked mode, with the Tabs as plain text (seen on macOS).
session() {  # session <name> <before compinit> <after compinit>
    local name=$1 before=$2 after=$3 out=''
    zpty -b $name 'TERM=dumb PS1="@P@ " zsh -f -i'
    zpty -w $name "$before"
    zpty -w $name 'autoload -U compinit && compinit -u -D'
    zpty -w $name "$after"
    zpty -w $name 'setopt nolistbeep; unsetopt menucomplete automenu'
    zpty -w $name "print RE''ADY"
    zpty -r -m $name out '*READY*@P@ *'
}
tab() {  # tab <session> <id> <line> [<keys>], by default two Tabs
    local name=$1 id=$2 line=$3 keys=$'\t\t' buf=''
    if (( $# > 3 )); then keys=$4; fi
    zpty -n -w $name "$line$keys"
    zpty -w $name $'\x15'"print -r -- @@E''ND@@"
    zpty -r -m $name buf '*@@END@@*@P@ *'
    buf=${buf//$'\r'/}
    buf=${buf%%print -r -- @@E*}
    print -r -- "pty"$'\t'"$id"$'\t'"${${(f)buf}[*]}"
}
"""


def _zsh_executable() -> str:
    return require_or_skip("zsh")


@pytest.fixture(scope="module")
def zsh_stub_run(tmp_path_factory):
    executable = _zsh_executable()
    work, empty = _workdir(tmp_path_factory, "zsh-stub")
    script = _write(work / "local-delegate.zsh", completion.render("zsh"))
    synthetic = _write(
        work / "synthetic.zsh", completion.render_zsh(_synthetic_model(), lang=i18n.lang())
    )
    body = "\n".join(
        [
            ZSH_STUB_RUNNER,
            _calls(UNLOADED_CASES, 1),
            f"source {shlex.quote(script)}",
            "show_registered",
            _calls(COMMON_CASES + ZSH_EQ_CASES, 1),
            f"source {shlex.quote(synthetic)}",
            _calls([(f"synthetic_{i}", c, w) for i, c, w in SYNTHETIC_CASES], 1),
        ]
    )
    runner = _write(work / "runner.zsh", body + "\n")
    output = _run([executable, "-f", runner], work, empty)
    return _parse(output)


def _names(entries: list[str], kinds: str = "da") -> list[str]:
    """Names offered by `_describe` (d) and `compadd` (a), in order."""
    return [entry.split("\t")[1] for entry in entries if entry[:1] in kinds]


ZSH = pytest.mark.shell("zsh")


@ZSH
def test_zsh_registration(zsh_stub_run):
    """REQ-011 and REQ-022: `compdef _local_delegate` for both executables when sourced."""
    cases, extra = zsh_stub_run
    assert extra["registered"] == "_local_delegate _local_delegate"
    assert _names(cases["mcp_alias"]) == ["install"]


@ZSH
def test_zsh_subcommands_with_descriptions(zsh_stub_run):
    """REQ-008, REQ-012 and REQ-022: `_describe` with the help in the language of the script."""
    cases, _ = zsh_stub_run
    root = _root_subcommands()
    assert _names(cases["root"]) == root
    assert _names(cases["case_sensitive"]) == root
    [entry] = cases["root_ba"]
    assert entry == "d\tbackend-params\t" + i18n.t("cli.help.backend_params")
    assert _names(cases["bp"]) == ["show", "set", "unset", "reset"]
    assert _names(cases["llamaswap"]) == ["residency"]
    assert _names(cases["test_window"]) == ["start", "stop", "add", "list"]
    assert _names(cases["after_flag"]) == ["show", "set", "unset", "reset"]
    assert _names(cases["mid_line"]) == ["backend-params"]


@ZSH
def test_zsh_description_with_colon_survives_the_escape(zsh_stub_run):
    """REQ-022: a `:` in a help text is escaped, so `_describe` shows it whole."""
    cases, _ = zsh_stub_run
    expected = {
        sub.name: sub.help
        for sub in completion.build_model(cli.build_parser()).nodes[()].subcommands
    }
    shown = dict(entry.split("\t")[1:] for entry in cases["root"] if entry[0] == "d")
    assert shown == expected
    assert any(":" in text for text in shown.values()), "control: some root help has a colon"


@ZSH
def test_zsh_options_of_the_node(zsh_stub_run):
    """REQ-013."""
    cases, _ = zsh_stub_run
    assert _names(cases["install_mcp"]) == ["--mcp-mode"]
    assert _names(cases["serve_dashdash"]) == ["--help", "--host", "--port", "--log-level"]
    assert _names(cases["append_again"]) == ["--clients"]


@ZSH
def test_zsh_option_values(zsh_stub_run):
    """REQ-014: `compset -P '*='` and then the values after `=`."""
    cases, _ = zsh_stub_run
    assert cases["mcp_mode"] == ["a\tstdio", "a\thttp"]
    assert cases["mcp_mode_eq"] == ["i\t--mcp-mode=", "a\thttp"]
    assert cases["mcp_mode_eq_empty"] == ["i\t--mcp-mode=", "a\tstdio", "a\thttp"]
    assert _names(cases["after_eq_value"]) == ["--mcp-mode"]
    assert _names(cases["log_level"]) == ["warning"]
    assert _names(cases["benchmark_role"]) == ROLES
    assert _names(cases["reset_calibration"]) == ["five_hour", "seven_day"]


@ZSH
def test_zsh_option_with_optional_value(zsh_stub_run):
    """REQ-014."""
    cases, _ = zsh_stub_run
    assert _names(cases["synthetic_optional_values"]) == ["auto", "zsh"]
    assert _names(cases["synthetic_optional_then_option"]) == ["--dry-run"]
    assert _names(cases["synthetic_optional_consumed"]) == ["--dry-run"]
    assert _names(cases["synthetic_optional_consumed_sub"]) == ["zeta"]
    assert _names(cases["synthetic_optional_then_option_value"]) == ["one", "two"]


@ZSH
def test_zsh_positionals_by_position(zsh_stub_run):
    """REQ-015: fixed values with `compadd`, a free positional to `_files`."""
    cases, _ = zsh_stub_run
    assert cases["set_role"] == [f"a\t{role}" for role in ROLES]
    assert _names(cases["set_key"]) == KEYS
    assert cases["set_value"] == ["f"]
    assert _names(cases["unset_t"]) == ["temperature", "top_k", "top_p", "typical_p"]
    assert _names(cases["reset_role"]) == ROLES
    assert _names(cases["completion"]) == ["powershell", "zsh", "bash"]


@ZSH
def test_zsh_free_value_goes_to_files(zsh_stub_run):
    """REQ-016."""
    cases, _ = zsh_stub_run
    assert cases["free_value"] == ["f"]


@ZSH
def test_zsh_no_match_gives_nothing(zsh_stub_run):
    """REQ-017 and control (a) of REQ-038: nothing offered, and no `_files` either."""
    cases, _ = zsh_stub_run
    assert cases["no_match_root"] == []
    assert cases["no_match_set"] == []


@ZSH
def test_zsh_unloaded_completer_gives_nothing(zsh_stub_run):
    """Control (b) of REQ-038."""
    cases, _ = zsh_stub_run
    assert cases["unloaded_set"] == []


# --- zsh, real ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def zsh_pty_run(tmp_path_factory):
    executable = _zsh_executable()
    work, empty = _workdir(tmp_path_factory, "zsh-pty")
    text = completion.render("zsh")
    script = _write(work / "local-delegate.zsh", text)
    fpath_dir = work / "fpath"
    fpath_dir.mkdir()
    _write(fpath_dir / "_local-delegate", text)
    set_line = "local-delegate backend-params set "
    completion_line = "local-delegate completion "
    add_fpath = f"fpath=({shlex.quote(fpath_dir.as_posix())} $fpath)"
    body = "\n".join(
        [
            ZSH_PTY_RUNNER,
            "session none true true",
            f"tab none none_set {shlex.quote(set_line)}",
            f"session src true {shlex.quote('source ' + shlex.quote(script))}",
            f"tab src src_set {shlex.quote(set_line)}",
            f"tab src src_completion {shlex.quote(completion_line)}",
            f"tab src src_mcp {shlex.quote('local-delegate-mcp backend-params set ')}",
            # compinit reads `fpath` when it starts: the directory goes in before it.
            f"session fp {shlex.quote(add_fpath)} true",
            # ONE Tab: the first call autoloads the file, and only the loadautofunc branch makes
            # that very call complete (a second Tab would hide a missing branch).
            f"tab fp fp_set {shlex.quote(set_line)} $'\\t'",
            f"tab fp fp_set_again {shlex.quote(set_line)}",
            f"tab fp fp_completion {shlex.quote(completion_line)}",
            "zpty -d none src fp",
            # The guard of a bare `source`: compinit loaded by the script itself.
            'print -r -- "guard"$\'\\t\'"$(zsh -f -c '
            + shlex.quote(f"source {shlex.quote(script)}; print -r -- ${{_comps[local-delegate]}}")
            + ')"',
        ]
    )
    runner = _write(work / "runner.zsh", body + "\n")
    output = _run([executable, "-f", runner], work, empty)
    found: dict[str, str] = {}
    guard = ""
    for line in output.splitlines():
        tag, _, rest = line.partition("\t")
        if tag == "pty":
            case_id, _, text_out = rest.partition("\t")
            found[case_id] = text_out
        elif tag == "guard":
            guard = rest
    return found, guard


@ZSH
def test_zsh_real_completion_sourced_and_from_fpath(zsh_pty_run):
    """REQ-022 smoke: the four roles and the three shells, in both ways of loading."""
    found, _ = zsh_pty_run
    for prefix in ("src", "fp"):
        for role in ROLES:
            assert role in found[f"{prefix}_set"], (prefix, found[f"{prefix}_set"])
        for shell in ("bash", "powershell", "zsh"):
            assert shell in found[f"{prefix}_completion"], (prefix, found[f"{prefix}_completion"])
    for role in ROLES:
        assert role in found["src_mcp"], found["src_mcp"]
        assert role in found["fp_set_again"], found["fp_set_again"]


@ZSH
def test_zsh_real_without_the_script_offers_nothing_of_ours(zsh_pty_run):
    """Control (b) of REQ-038 in the real shell: compinit alone does not know the roles."""
    found, _ = zsh_pty_run
    assert "mechanical" not in found["none_set"], found["none_set"]


@ZSH
def test_zsh_source_without_compinit_loads_it(zsh_pty_run):
    """REQ-022: the guard loads compinit when a bare `zsh -f` sources the script."""
    _, guard = zsh_pty_run
    assert guard == "_local_delegate"
