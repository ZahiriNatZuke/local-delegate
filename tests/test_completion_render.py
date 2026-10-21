"""Rendering of the completion scripts, without launching any shell (SDD cli-completion).

REQ-002 (static script, allow-list), REQ-004 (hidden names), REQ-008 (descriptions in the
requested language), REQ-009 (header), REQ-010 (deterministic output), REQ-018 (ASCII only),
REQ-019 (syntax that Windows PowerShell 5.1 does not have), REQ-021 (nothing newer than bash
3.2), REQ-022 (shape of the zsh script) and REQ-042 (`render(..., lang=)`). It runs also in `cli-python-matrix` (Python 3.11 to 3.15).
"""

from __future__ import annotations

import importlib.resources
import re

import pytest

from local_delegate import completion, deprecations, i18n
from local_delegate.version import get_version

EXECUTABLE_NAMES = ("local-delegate", "python", "py", "uv")


# --- Allow-list analyzer (REQ-002) ------------------------------------------------------------

_PS_CHAR = re.compile(r"\$\(\[char\]0x[0-9A-F]{4}\)")


def _ps_code_and_strings(script: str) -> tuple[str, list[str]]:
    """Splits a PowerShell script into code (string contents blanked) and its string literals.

    Double-quoted strings honour the backtick escape; single-quoted ones double the quote.
    Comments (`#` outside a string, to the end of the line) are dropped from the code.
    """
    code: list[str] = []
    strings: list[str] = []
    index = 0
    while index < len(script):
        char = script[index]
        if char == "#":
            end = script.find("\n", index)
            index = len(script) if end < 0 else end
            continue
        if char in "\"'":
            quote = char
            index += 1
            start = index
            while index < len(script):
                if quote == '"' and script[index] == "`":
                    index += 2
                    continue
                if script[index] == quote:
                    if quote == "'" and script[index + 1 : index + 2] == "'":
                        index += 2
                        continue
                    break
                index += 1
            strings.append(script[start:index])
            code.append(quote + quote)
            index += 1
            continue
        code.append(char)
        index += 1
    return "".join(code), strings


def _unescaped_subexpressions(text: str) -> list[str]:
    """Each `$(` not preceded by a backtick, with the rest of its line."""
    found = []
    for match in re.finditer(r"\$\(", text):
        if match.start() > 0 and text[match.start() - 1] == "`":
            continue
        found.append(text[match.start() : text.find("\n", match.start()) % (len(text) + 1)])
    return found


def ps_violations(script: str) -> list[str]:
    """What the allow-list rejects in a PowerShell script."""
    problems = []
    code, strings = _ps_code_and_strings(script)
    # Command substitution runs in code and inside double-quoted strings alike.
    for chunk in [code, *strings]:
        for found in _unescaped_subexpressions(chunk):
            if not _PS_CHAR.match(found):
                problems.append(f"subexpression: {found[:60]}")
    for word in ("Invoke-Expression", "iex", "Invoke-Command", "Start-Process"):
        if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", code, re.IGNORECASE):
            problems.append(f"command: {word}")
    if re.search(r"(?<![\w-])&\s*[\"'$(]", code) or re.search(r"(?<![\w-])&\s*\w", code):
        problems.append("call operator")
    for line in code.splitlines():
        for name in EXECUTABLE_NAMES:
            if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", line):
                problems.append(f"executable: {name}")
    # Names inside string literals: only on the registration line (and the header comment, which
    # is not code). Help texts are data and may mention the CLI.
    for line in script.splitlines():
        if "-CommandName" in line or line.startswith("#"):
            continue
        _, line_strings = _ps_code_and_strings(line)
        for text in line_strings:
            if text in EXECUTABLE_NAMES:
                problems.append(f"executable string: {text}")
    return problems


def posix_code(script: str) -> str:
    """bash/zsh code with comments dropped and single-quoted strings blanked to `''`.

    Single-quoted text is data (help texts, keys, values): nothing in it is expanded. Double-quoted
    text stays as code, because `$(...)` runs inside double quotes. A backslash outside quotes
    escapes the next character; `#` starts a comment only at the start of a word.
    """
    out: list[str] = []
    index = 0
    while index < len(script):
        char = script[index]
        if char == "\\":
            out.append(script[index : index + 2])
            index += 2
        elif char == "'":
            index = script.index("'", index + 1) + 1
            out.append("''")
        elif char == '"':
            end = index + 1
            while script[end] != '"':
                end += 2 if script[end] == "\\" else 1
            out.append(script[index : end + 1])
            index = end + 1
        elif char == "#" and (index == 0 or script[index - 1] in " \t\n;"):
            end = script.find("\n", index)
            index = len(script) if end < 0 else end
        else:
            out.append(char)
            index += 1
    return "".join(out)


def posix_violations(script: str, shell: str) -> list[str]:
    """What the allow-list rejects in a bash or zsh script (REQ-002)."""
    problems = []
    code = posix_code(script)
    without_arithmetic = re.sub(r"\$\(\((?:[^()]|\([^()]*\))*\)\)", "", code)
    for match in re.finditer(r"\$\(\s*([^\s)]*)", without_arithmetic):
        first = match.group(1)
        if shell == "bash" and first == "compgen":
            continue
        problems.append(f"command substitution: $({first}")
    if "`" in without_arithmetic:
        problems.append("backtick")
    if re.search(r"(?<![\w-])eval(?![\w-])", without_arithmetic):
        problems.append("eval")
    # Executable names: only on the registration line (the header is a comment).
    for line in code.splitlines():
        if line.lstrip().startswith(("complete ", "compdef ")):
            continue
        for name in EXECUTABLE_NAMES:
            if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", line):
                problems.append(f"executable: {name}")
    return problems


def test_powershell_script_passes_the_allow_list():
    for lang in i18n.LANGUAGES:
        assert ps_violations(completion.render("powershell", lang=lang)) == []


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_posix_scripts_pass_the_allow_list(shell):
    """REQ-002: only `$(compgen ...)` in bash, no command substitution at all in zsh."""
    for lang in i18n.LANGUAGES:
        script = completion.render(shell, lang=lang)
        assert posix_violations(script, shell) == []
        # Control: the analyzer does see the code of the real script.
        assert "_local_delegate()" in posix_code(script)
    assert "$(compgen" in posix_code(completion.render("bash", lang="es"))
    assert "$(" not in re.sub(r"\$\(\(", "", posix_code(completion.render("zsh", lang="es")))


def test_allow_list_flags_its_positive_controls():
    """REQ-002: the two controls of the spec, plus the forms the analyzer has to tell apart."""
    assert ps_violations('$x = "$(Get-Date)"\n')
    assert ps_violations("$x = $(Get-Date)\n")
    assert ps_violations("Invoke-Expression $y\n")
    assert ps_violations("& local-delegate --version\n")
    assert ps_violations('$help["|x"] = "a`$(b)"\n') == []  # escaped: plain text
    assert ps_violations('$help["|x"] = "$([char]0x00F3)"\n') == []
    assert posix_violations("x=$(local-delegate --version)\n", "bash")
    assert posix_violations("x=`local-delegate --version`\n", "bash")
    assert posix_violations("eval x\n", "zsh")
    assert posix_violations('x=$(compgen -W "a b" -- "$cur")\n', "bash") == []
    assert posix_violations("x=$(compgen -W a)\n", "zsh")
    assert posix_violations("n=$(( i + 1 ))\n", "zsh") == []
    assert posix_violations('x="$(uv run y)"\n', "bash")  # inside double quotes it runs
    assert posix_violations("local-delegate --version\n", "bash")
    assert posix_violations("x='$(local-delegate) `uv` eval'\n", "zsh") == []  # data only
    assert posix_violations("complete -F f local-delegate\n", "bash") == []
    assert posix_violations("# local-delegate header\n", "bash") == []


# --- Static checks of the PowerShell script ---------------------------------------------------

_FORBIDDEN_51 = {
    "ternary": re.compile(r"\s\?\s[^:\n]*\s:\s"),
    "null coalescing": re.compile(r"\?\?"),
    "null conditional": re.compile(r"\?\.|\?\["),
    "pipeline chain": re.compile(r"&&|\|\|"),
    "unicode escape": re.compile(r"`u\{"),
    "using namespace": re.compile(r"(?im)^\s*using\s+namespace"),
    "::new": re.compile(r"\[[\w.]*CompletionResult\]::new", re.IGNORECASE),
}


def _forbidden_51(script: str) -> list[str]:
    """Checked on the code with strings blanked; the `u{} escape also inside double quotes."""
    code, _ = _ps_code_and_strings(script)
    found = [name for name, pattern in _FORBIDDEN_51.items() if pattern.search(code)]
    if "unicode escape" not in found and _FORBIDDEN_51["unicode escape"].search(script):
        found.append("unicode escape")
    return found


def test_powershell_script_has_no_syntax_missing_in_windows_powershell():
    """REQ-019: none of the PowerShell 7 constructs that 5.1 cannot parse."""
    assert _forbidden_51(completion.render("powershell", lang="es")) == []


def test_forbidden_syntax_check_flags_its_controls():
    assert _forbidden_51("$a = $b ? 1 : 2\n") == ["ternary"]
    assert _forbidden_51("$a = $b ?? 1\n") == ["null coalescing"]
    assert _forbidden_51("$a = $b?.c\n") == ["null conditional"]
    assert _forbidden_51("a && b\n") == ["pipeline chain"]
    assert _forbidden_51('$a = "`u{1F600}"\n') == ["unicode escape"]
    assert _forbidden_51('$a = "a ? b : c && d"\n') == []  # plain text inside a string
    assert _forbidden_51("$a = `u{1F600}\n") == ["unicode escape"]
    assert _forbidden_51("using namespace System\n") == ["using namespace"]
    assert _forbidden_51("[CompletionResult]::new(1)\n") == ["::new"]


def test_powershell_script_is_ascii_only():
    """REQ-018: every byte below 0x80, so 5.1 reads it right without BOM."""
    data = completion.render("powershell", lang="es").encode("utf-8")
    assert max(data) < 0x80
    assert b"\r" not in data
    assert "Par$([char]0x00E1)metros" in data.decode("ascii")


def test_powershell_registers_both_executables():
    """REQ-011: `local-delegate` and `local-delegate-mcp`, without `.exe` variants."""
    script = completion.render("powershell", lang="es")
    [line] = [line for line in script.splitlines() if "-CommandName" in line]
    assert '@("local-delegate", "local-delegate-mcp")' in line
    assert ".exe" not in line


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_hidden_names_do_not_appear(shell):
    """REQ-004: SUPPRESS help, subparsers without help and deprecated names stay out."""
    script = completion.render(shell, lang="es")
    retired = [entry.old for entry in deprecations.cli_entries()]
    assert len(retired) >= 2  # the old subcommand and the old option of recompute-cost
    # Whole words: quotes delimit them in PowerShell, spaces and quotes in the case tables.
    words = set(re.findall(r"[A-Za-z0-9_.:/+-]+", script))
    for hidden in [*retired, "--api-key"]:  # `benchmark --api-key` has help=SUPPRESS
        assert hidden not in words, hidden
    assert "--api-key-env" in words  # control: the same search does find a real option


# --- ps_literal --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain", '"plain"'),
        ('a"b', '"a`"b"'),
        ("a$b", '"a`$b"'),
        ("a`b", '"a``b"'),
        ("ó", '"$([char]0x00F3)"'),
        ("\U0001f680", '"$([char]0xD83D)$([char]0xDE80)"'),
        ("a\tb", '"a$([char]0x0009)b"'),
    ],
)
def test_ps_literal(text, expected):
    assert completion.ps_literal(text) == expected


# --- Header, determinism and language ----------------------------------------------------------


def test_header_shape_and_version():
    """REQ-009."""
    script = completion.render("powershell", lang="en")
    first = script.splitlines()[0]
    assert first == (
        f"# local-delegate {get_version()} completion powershell lang=en (generated; do not edit)"
    )
    assert first.isascii()
    assert completion.header_version(script) == get_version()
    assert completion.header_version("#compdef local-delegate\n" + first + "\n") == get_version()
    assert completion.header_version("Register-ArgumentCompleter\n") is None
    assert completion.header_version("") is None
    assert completion.header_version("#a\n#b\n" + first) is None  # only lines 1 and 2


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_output_is_deterministic(shell):
    """REQ-010."""
    for lang in i18n.LANGUAGES:
        assert completion.render(shell, lang=lang) == completion.render(shell, lang=lang)


def test_descriptions_follow_the_requested_language():
    """REQ-008 and REQ-042: the help comes out in `lang`, whatever the language in force."""
    assert i18n.lang() == "es"
    spanish = completion.render("powershell", lang="es")
    english = completion.render("powershell", lang="en")
    assert spanish != english
    assert completion.ps_literal(i18n.t_lang("es", "cli.help.backend_params")) in spanish
    assert completion.ps_literal(i18n.t_lang("en", "cli.help.backend_params")) in english
    # The argparse scaffold (`-h`) too, not only the catalog texts of the CLI.
    assert '"show this help message and exit"' in english
    assert '"show this help message and exit"' not in spanish
    assert i18n.lang() == "es"


def test_render_without_lang_uses_the_language_in_force(monkeypatch):
    assert completion.render("powershell") == completion.render("powershell", lang="es")
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    assert (
        completion.render("powershell").splitlines()[0].endswith("lang=en (generated; do not edit)")
    )


def test_render_rejects_an_unknown_shell():
    with pytest.raises(ValueError, match="fish"):
        completion.render("fish")


def test_template_with_carriage_return_is_rejected(monkeypatch):
    """REQ-001: a CRLF template (a Windows checkout without `-text`) must not reach the output."""

    class FakeEntry:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def joinpath(self, *parts: str) -> FakeEntry:
            return self

        def read_bytes(self) -> bytes:
            return self.data

    monkeypatch.setattr(
        importlib.resources, "files", lambda package: FakeEntry(b"@@HEADER@@\r\n@@TABLES@@\r\n")
    )
    with pytest.raises(completion.CompletionTemplateError, match="carriage_return"):
        completion.render("powershell", lang="es")


@pytest.mark.parametrize("name", ["powershell.ps1", "bash.bash", "zsh.zsh"])
def test_packaged_template_has_its_slots_and_no_carriage_return(name):
    entry = importlib.resources.files("local_delegate").joinpath("resources", "completion", name)
    raw = entry.read_bytes()
    assert b"\r" not in raw
    assert max(raw) < 0x80
    assert raw.count(b"@@HEADER@@") == 1
    assert raw.count(b"@@TABLES@@") == 1


# --- bash and zsh --------------------------------------------------------------------------------

_FORBIDDEN_BASH32 = {
    "associative array": re.compile(r"(?<![\w-])(declare|typeset|local)\s+-[A-Za-z]*A"),
    "compopt": re.compile(r"(?<![\w-])compopt(?![\w-])"),
    "mapfile": re.compile(r"(?<![\w-])(mapfile|readarray)(?![\w-])"),
    "case conversion": re.compile(r"\$\{[A-Za-z_]\w*(\[[^]]*\])?(\^\^?|,,?)"),
    "nosort": re.compile(r"-o\s+nosort"),
    "case fallthrough": re.compile(r";;&|;&"),
    "coproc": re.compile(r"(?<![\w-])coproc(?![\w-])"),
    "stderr pipe": re.compile(r"\|&"),
    "negative index": re.compile(r"\$\{\w+\[-\d+\]\}"),
}


def _forbidden_bash32(script: str) -> list[str]:
    code = posix_code(script)
    return [name for name, pattern in _FORBIDDEN_BASH32.items() if pattern.search(code)]


def test_bash_script_has_nothing_newer_than_bash_32():
    """REQ-021: no construct of bash 4 or later (the integration test runs it in 3.2 too)."""
    for lang in i18n.LANGUAGES:
        assert _forbidden_bash32(completion.render("bash", lang=lang)) == []


def test_bash_32_check_flags_its_controls():
    assert _forbidden_bash32("declare -A t\n") == ["associative array"]
    assert _forbidden_bash32("local -gA t\n") == ["associative array"]
    assert _forbidden_bash32("compopt -o nospace\n") == ["compopt"]
    assert _forbidden_bash32("mapfile -t a\n") == ["mapfile"]
    assert _forbidden_bash32('x="${cur,,}"\n') == ["case conversion"]
    assert _forbidden_bash32('x="${cur^}"\n') == ["case conversion"]
    assert _forbidden_bash32("complete -o nosort -F f c\n") == ["nosort"]
    assert _forbidden_bash32("case x in a) ;& esac\n") == ["case fallthrough"]
    assert _forbidden_bash32("a |& b\n") == ["stderr pipe"]
    assert _forbidden_bash32('x="${a[-1]}"\n') == ["negative index"]
    assert _forbidden_bash32("x='declare -A ${a,,}'\n") == []  # data, not code


def test_bash_registers_both_executables_with_default():
    """REQ-011, REQ-016 and REQ-021: the last line registers both names with `-o default`."""
    script = completion.render("bash", lang="es")
    [line] = [line for line in script.splitlines() if line.startswith("complete ")]
    assert line == "complete -o default -F _local_delegate local-delegate local-delegate-mcp"
    assert script.endswith(line + "\n")


def test_zsh_script_shape():
    """REQ-009 and REQ-022: `#compdef`, header, guard before `compdef`, loadautofunc pattern."""
    script = completion.render("zsh", lang="es")
    lines = script.splitlines()
    assert lines[0] == "#compdef local-delegate local-delegate-mcp"
    assert lines[1] == (
        f"# local-delegate {get_version()} completion zsh lang=es (generated; do not edit)"
    )
    assert completion.header_version(script) == get_version()
    code = posix_code(script)
    guard = "(( $+functions[compdef] )) || { autoload -Uz compinit && compinit -i; }"
    register = "compdef _local_delegate local-delegate local-delegate-mcp"
    assert code.index(guard) < code.index(register)
    assert 'if [[ "${zsh_eval_context[-1]}" == loadautofunc ]]; then' in code
    for call in ("_describe -t", "compadd -a", "compset -P", "_files"):
        assert call in code, call


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_posix_header(shell):
    """REQ-009: the header names the shell and the language, also in bash."""
    script = completion.render(shell, lang="en")
    expected = (
        f"# local-delegate {get_version()} completion {shell} lang=en (generated; do not edit)"
    )
    assert expected in script.splitlines()[:2]
    assert completion.header_version(script) == get_version()


def test_bash_is_the_same_in_both_languages_but_the_header():
    """REQ-008: bash shows no descriptions, so only the first line changes."""
    spanish = completion.render("bash", lang="es").splitlines()
    english = completion.render("bash", lang="en").splitlines()
    assert spanish[0].endswith("lang=es (generated; do not edit)")
    assert english[0].endswith("lang=en (generated; do not edit)")
    assert spanish[1:] == english[1:]


def test_zsh_descriptions_follow_the_requested_language():
    """REQ-008 and REQ-042: the `_describe` items carry the help in `lang`."""
    assert i18n.lang() == "es"
    spanish = completion.render("zsh", lang="es")
    english = completion.render("zsh", lang="en")
    assert spanish != english
    for lang, script in (("es", spanish), ("en", english)):
        item = completion.zsh_describe_item(
            "backend-params", i18n.t_lang(lang, "cli.help.backend_params")
        )
        assert completion.sh_quote(item) in script, lang
    assert "show this help message and exit" in english
    assert "show this help message and exit" not in spanish
    assert i18n.lang() == "es"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain", "'plain'"),
        ("it's", "'it'\\''s'"),
        ("$(x) `y` \\z", "'$(x) `y` \\z'"),
        ("", "''"),
    ],
)
def test_sh_quote(text, expected):
    assert completion.sh_quote(text) == expected


@pytest.mark.parametrize(
    ("name", "description", "expected"),
    [
        ("set", "Fija un valor", "set:Fija un valor"),
        ("a:b", "c:d", "a\\:b:c\\:d"),
        ("x", "back\\slash", "x:back\\\\slash"),
    ],
)
def test_zsh_describe_item_escapes_colon_and_backslash(name, description, expected):
    assert completion.zsh_describe_item(name, description) == expected
