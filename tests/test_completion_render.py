"""Rendering of the completion scripts, without launching any shell (SDD cli-completion).

REQ-002 (static script, allow-list), REQ-004 (hidden names), REQ-008 (descriptions in the
requested language), REQ-009 (header), REQ-010 (deterministic output), REQ-018 (ASCII only),
REQ-019 (syntax that Windows PowerShell 5.1 does not have) and REQ-042 (`render(..., lang=)`).
It runs also in `cli-python-matrix` (Python 3.11 to 3.15).
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


def posix_violations(script: str, shell: str) -> list[str]:
    """What the allow-list rejects in a bash or zsh script (L2b renders them)."""
    problems = []
    body = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    without_arithmetic = re.sub(r"\$\(\((?:[^()]|\([^()]*\))*\)\)", "", body)
    for match in re.finditer(r"\$\(\s*([^\s)]*)", without_arithmetic):
        first = match.group(1)
        if shell == "bash" and first == "compgen":
            continue
        problems.append(f"command substitution: $({first}")
    if "`" in without_arithmetic:
        problems.append("backtick")
    if re.search(r"(?<![\w-])eval(?![\w-])", without_arithmetic):
        problems.append("eval")
    return problems


def test_powershell_script_passes_the_allow_list():
    for lang in i18n.LANGUAGES:
        assert ps_violations(completion.render("powershell", lang=lang)) == []


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


def test_hidden_names_do_not_appear():
    """REQ-004: SUPPRESS help, subparsers without help and deprecated names stay out."""
    script = completion.render("powershell", lang="es")
    retired = [
        entry.old
        for entry in deprecations.DEPRECATED_NAMES
        if entry.kind in ("cli_command", "cli_option")
    ]
    assert len(retired) >= 2  # the old subcommand and the old option of recompute-cost
    for hidden in [*retired, "--api-key"]:  # `benchmark --api-key` has help=SUPPRESS
        assert f'"{hidden}"' not in script, hidden
    assert '"--api-key-env"' in script  # control: the quoted form does find a real option


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


def test_output_is_deterministic():
    """REQ-010."""
    for lang in i18n.LANGUAGES:
        assert completion.render("powershell", lang=lang) == completion.render(
            "powershell", lang=lang
        )


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


def test_packaged_template_has_its_slots_and_no_carriage_return():
    raw = (
        importlib.resources.files("local_delegate")
        .joinpath("resources", "completion", "powershell.ps1")
        .read_bytes()
    )
    assert b"\r" not in raw
    assert max(raw) < 0x80
    assert raw.count(b"@@HEADER@@") == 1
    assert raw.count(b"@@TABLES@@") == 1
