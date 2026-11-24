"""Issue #724 (from #670): the write guard of Codex sees the shell writes PowerShell, cmd and bash make.

Codex on Windows edits with PowerShell inside ``exec_command`` (``tool_name: Bash`` for the hook):
``[System.IO.File]::WriteAllText(...)`` with the path in a variable, besides the forms the shared
classifier already saw. Each write is checked both ways: refused once the file is guarded, and the
controls (a read, a write to another file, what cannot be analyzed) pass. The world, the payloads
and the hook process are those of ``test_codex_reads``.
"""

from __future__ import annotations

import json
import random
import re

import perf
import pytest
import test_codex_reads as base

from local_delegate import codex_reads
from local_delegate.resources.hooks import read_classifier

world = base.world

#: The command of #724, as Codex sent it (path in a variable, .NET read and write).
ISSUE_724 = (
    "$p = 'notes.md'\n"
    "$s = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $p))\n"
    "$s = [regex]::Replace($s, '^.*', 'Titulo nuevo')\n"
    "[System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $p), $s)\n"
    "Get-Content -LiteralPath $p -TotalCount 1"
)
#: What Codex puts before every PowerShell command on Windows (#670, sandbox log).
PREAMBLE = "try { [Console]::OutputEncoding=[System.Text.Encoding]::UTF8 } catch {}\n"


def _guard(world) -> None:
    base._prose(world["work"] / "notes.md")
    base._prose(world["work"] / "other.md", lines=10)
    base._denied(base._bash(world, "cat notes.md"))


def _refused(world, command: str) -> None:
    reason = base._denied(base._bash(world, command))
    assert "solo se ha leido resumido" in reason and "notes.md" in reason


def _passes(out) -> None:
    spec = (out or {}).get("hookSpecificOutput", {})
    assert spec.get("permissionDecision") != "deny", spec.get("permissionDecisionReason")


DOTNET = [
    "[System.IO.File]::WriteAllText('notes.md', 'x')",
    '[IO.File]::WriteAllLines("notes.md", @("a", "b"))',
    "[io.file]::appendalltext('notes.md', 'x')",
    "[System.IO.File]::AppendAllLines('notes.md', [string[]]@('a'))",
    "[System.IO.File]::WriteAllBytes('notes.md', $bytes)",
    "[File]::WriteAllText('notes.md', 'x')",
    "[IO.File]::Copy('other.md', 'notes.md', $true)",
    "[IO.File]::Move('other.md', 'notes.md')",
    "[IO.File]::Replace('other.md', 'notes.md', 'notes.bak')",
    "$w = [IO.File]::CreateText('notes.md'); $w.Write('x'); $w.Close()",
    "$f = [IO.File]::OpenWrite('notes.md'); $f.Close()",
    "[System.IO.File]::WriteAllText((Resolve-Path -LiteralPath 'notes.md'), 'x')",
    "[System.IO.File]::WriteAllText((Resolve-Path notes.md).Path, 'x')",
    "[System.IO.File]::WriteAllText( ( Convert-Path -Path 'notes.md' ).ProviderPath , 'x' )",
    PREAMBLE + "[System.IO.File]::WriteAllText('notes.md', 'x')",
    "[IO.File]::Create('notes.md').Close()",
    "$w = [IO.File]::AppendText('notes.md')",
    "$p = 'notes.md'; $s = \"don't\"; [IO.File]::WriteAllText($p, $s)",
    "# it's fine\n[IO.File]::WriteAllText('notes.md', 'x')",
    ISSUE_724,
    PREAMBLE + ISSUE_724,
]


@pytest.mark.parametrize("command", DOTNET)
def test_a_dotnet_write_on_a_summarized_file_is_refused(world, command):
    """REQ-001: the .NET writes of `[System.IO.File]`, with their control (unguarded: pass)."""
    base._prose(world["work"] / "notes.md")
    _passes(base._bash(world, command))
    _guard(world)
    _refused(world, command)


def test_a_dotnet_write_with_an_absolute_path_is_refused(world):
    _guard(world)
    notes = world["work"] / "notes.md"
    _refused(world, f"[IO.File]::WriteAllText('{notes}', 'x')")
    _refused(world, f'[IO.File]::WriteAllText("{notes}", "x")')


VARIABLES = [
    "$p = 'notes.md'; Set-Content -Path $p -Value x",
    "$p='notes.md'; 'x' | Out-File $p",
    '$P = "notes.md"\n[IO.File]::WriteAllText($p, "x")',
    "$p = 'notes.md'; [IO.File]::WriteAllText(${p}, 'x')",
    "$p = 'notes.md'; [IO.File]::WriteAllText(\"$p\", 'x')",
    "$p = 'notes.md'\n$p = 'notes.md'\nAdd-Content $p x",
    'p=notes.md; echo x > "$p"',
    "p=notes.md && sed -i 's/a/b/' $p",
    "export p=notes.md; cp other.md ${p}",
]


@pytest.mark.parametrize("command", VARIABLES)
def test_a_path_in_a_literal_variable_is_resolved_for_writes(world, command):
    """REQ-002: a variable set to a literal in the same command names the file it writes."""
    base._prose(world["work"] / "notes.md")
    _passes(base._bash(world, command))
    _guard(world)
    _refused(world, command)


@pytest.mark.parametrize(
    "command",
    [
        "$p = 'notes.md'; Get-Content $p -TotalCount 40",
        "$p = 'notes.md'; Get-Content -LiteralPath $p | Select-Object -First 40",
        "p=notes.md; sed -n '1,40p' \"$p\"",
    ],
)
def test_a_literal_read_through_a_variable_lifts_the_guard(world, command):
    """REQ-002: the read through the variable is the literal read the guard asks for."""
    _guard(world)
    _passes(base._bash(world, command))
    assert base._patch(world, "*** Update File: notes.md\n@@\n-a\n+b") is None


def test_the_read_through_a_variable_control(world):
    """Control of the test above: without the read, the same patch is refused."""
    _guard(world)
    base._denied(base._patch(world, "*** Update File: notes.md\n@@\n-a\n+b"))


MORE_POWERSHELL = [
    "New-Item notes.md -Value x -Force",
    "New-Item -Path notes.md -ItemType File -Force",
    "ni notes.md -Value x",
    "New-Item -Name notes.md -Value x",
    "Clear-Content notes.md",
    "clc -Path notes.md",
    "'x' | Tee-Object -FilePath notes.md",
    "Add-Content notes.md x",
    "Add-Content -Path notes.md -Value x",
    "Set-Content -LiteralPath notes.md -Value x",
    "Get-Date | Out-File -Append notes.md",
    "'x' > notes.md",
    "echo x >> notes.md",
    "Copy-Item other.md notes.md",
    "Copy-Item -Path other.md -Destination notes.md -Force",
    "Move-Item -Path other.md -Destination notes.md -Force",
    "$null = New-Item -ItemType File -Force notes.md",
    "$f = New-Item notes.md -Value x",
    "$null=New-Item notes.md -Force",
    "if (Test-Path notes.md) { Set-Content notes.md x }",
    "try { 'x' | Out-File notes.md } catch { Write-Error $_ }",
    "Get-ChildItem *.md | ForEach-Object { Add-Content notes.md $_.Name }",
]
CMD = [
    "copy /y other.md notes.md",
    "move /y other.md notes.md",
    "type other.md > notes.md",
    "echo x >> notes.md",
]
BASH = [
    "echo x | tee notes.md",
    "echo x | tee -a notes.md",
    "sed -i.bak 's/a/b/' notes.md",
    "sed --in-place -e 's/a/b/' notes.md",
    "cat other.md > notes.md",
    "printf 'x\\n' >> notes.md",
    "cp -f other.md notes.md",
    "mv other.md notes.md",
    "{ echo x; echo y; } > notes.md",
    "if true; then { echo x > notes.md; }; fi",
]


@pytest.mark.parametrize("command", MORE_POWERSHELL + CMD + BASH)
def test_every_shell_write_on_a_summarized_file_is_refused(world, command):
    """REQ-003: the PowerShell writes the classifier did not see, and the ones it already saw."""
    base._prose(world["work"] / "notes.md")
    _passes(base._bash(world, command))
    _guard(world)
    _refused(world, command)


WRAPPED = [
    'cmd /c "echo x > notes.md"',
    'cmd.exe /C "copy /y other.md notes.md"',
    "bash -c 'echo x > notes.md'",
    'bash -lc "sed -i s/a/b/ notes.md"',
    "sh -c 'cp other.md notes.md'",
    'powershell -NoProfile -Command "Set-Content notes.md x"',
    "pwsh -c \"[IO.File]::WriteAllText('notes.md','x')\"",
    'powershell.exe -NoProfile -Command "& { Set-Content -Path notes.md -Value x }"',
    'cmd /k "echo x > notes.md"',
    'powershell -Command "& {Set-Content notes.md x}"',
]


@pytest.mark.parametrize("command", WRAPPED)
def test_a_wrapped_write_is_analyzed_inside(world, command):
    """REQ-004: `cmd /c`, `bash -c` and `powershell -Command` are looked into."""
    base._prose(world["work"] / "notes.md")
    _passes(base._bash(world, command))
    _guard(world)
    _refused(world, command)


@pytest.mark.parametrize(
    "command",
    [
        "bash -c \"sed -n '1,40p' notes.md\"",
        'powershell -Command "Get-Content notes.md -TotalCount 40"',
    ],
)
def test_a_wrapped_literal_read_lifts_the_guard(world, command):
    _guard(world)
    _passes(base._bash(world, command))
    assert base._patch(world, "*** Update File: notes.md\n@@\n-a\n+b") is None


CONTROLS = [
    # Reads of the guarded file.
    "$s = [System.IO.File]::ReadAllText('notes.md')",
    "[IO.File]::ReadAllLines('notes.md').Count",
    "Get-Content notes.md -TotalCount 5",
    "[IO.File]::Copy('notes.md', 'other.md', $true)",
    # Writes to another file.
    "[System.IO.File]::WriteAllText('other.md', 'x')",
    "$p = 'other.md'; [IO.File]::WriteAllText($p, 'x')",
    "$p = 'other.md'; Set-Content $p x",
    "New-Item -Path notes2.md -Value x",
    'cmd /c "echo x > other.md"',
    "bash -c 'echo x > other.md'",
    # What cannot be analyzed.
    "Write-Output '[IO.File]::WriteAllText(\"notes.md\", 1)'",
    "[IO.File]::WriteAllText(\"$dir\\notes.md\", 'x')",
    "[IO.File]::WriteAllText((Join-Path $PWD 'notes.md'), 'x')",
    "$p = Join-Path $PWD 'notes.md'; Set-Content $p x",
    "$p = 'notes.md'; $p = 'other.md'; Set-Content $p x",
    "$p = 'other.md'; Set-Content $p x; $p = 'notes.md'; Get-Content $p -TotalCount 1",
    "$p = 'notes.md'; $p += '.bak'; Set-Content $p x",
    "foreach ($p in @('x')) { Set-Content $p x }",
    "$p = 'notes.md'; foreach ($p in @('x')) { Set-Content $p x }",
    "$p = 'notes.md'; Get-Item x -OutVariable p; Set-Content $p x",
    "p=notes.md; for p in a b; do echo x > $p; done",
    "p=notes.md; read p; echo x > $p",
    "[IO.File]::WriteAllText('notes.md'",
    "Set-Location sub; [IO.File]::WriteAllText('notes.md', 'x')",
    "New-Item notes.md",
    "New-Item -ItemType Directory -Force notes.md",
    "powershell -EncodedCommand ZQBjAGgAbwAgAHgA",
    "[IO.File]::Open('notes.md', 'Open')",
    "Write-Output \"[IO.File]::WriteAllText('notes.md', 1)\"",
    "git commit -m \"usar [IO.File]::Copy('a', 'notes.md')\"",
    "# [IO.File]::WriteAllText('notes.md', 'x')",
    'echo "it\'s"; Write-Output \'[IO.File]::WriteAllText("notes.md", 1)\'',
    "$p = 'notes.md'; function f($p) { Set-Content $p x }; f 'other.md'",
    "$p = 'notes.md'; Set-Variable -Name p -Value other.md; Set-Content $p x",
    "$p = 'notes.md'; Set-Ref ([ref]$p); Set-Content $p x",
    "Push-Location sub; Clear-Content notes.md",
    "Set-Location -Path sub; New-Item notes.md -Force",
    "cp notes.md{,.bak}",
    "awk '{ print > \"notes.md\" }' other.md",
    'Write-Output "{ Set-Content notes.md x }"',
]


@pytest.mark.parametrize("command", CONTROLS)
def test_reads_other_files_and_what_cannot_be_analyzed_pass(world, command):
    """REQ-005: no false positive on the guarded file."""
    _guard(world)
    _passes(base._bash(world, command))


def test_the_controls_do_not_lift_the_guard_by_accident(world):
    """The guard is still there after the controls that do not read it literally."""
    _guard(world)
    _passes(base._bash(world, "[System.IO.File]::WriteAllText('other.md', 'x')"))
    _refused(world, "[System.IO.File]::WriteAllText('notes.md', 'x')")


@pytest.mark.parametrize(
    "command",
    [
        "{ cat notes.md; } | head -n 40",
        "& { Get-Content notes.md } | Select-Object -First 5",
        "Get-Content notes.md | Where-Object { $_ -like '*x*' } | Set-Content out.md",
        "bash -c 'cat notes.md' | head -5",
        "cmd /c type notes.md > out.txt",
    ],
)
def test_a_read_whose_output_goes_on_does_not_lift_the_guard(world, command):
    """Review of #724: a read in a block or a wrapped command whose output is piped or redirected
    outside does not put the file in the context, so the patch after it is still refused."""
    _guard(world)
    base._bash(world, command)
    base._denied(base._patch(world, "*** Update File: notes.md\n@@\n-a\n+b"))


HOSTILE = [
    lambda n: "[IO.File]::WriteAllText(" * n,
    lambda n: "[IO.File]::WriteAllText(" + "(" * (5 * n) + "'notes.md'" + ")" * (5 * n - 1),
    lambda n: "$p = " * (2 * n) + "'notes.md'",
    lambda n: "cmd /c " * n + "echo x",
    lambda n: "[IO.File]::WriteAllText('" + "'" * (5 * n),
    lambda n: "$p = 'notes.md'\n" + "[IO.File]::WriteAllText($p, 'x')\n" * (n // 3),
    lambda n: "@'x" * (2 * n),
    lambda n: ";".join(f"echo x > a{i}" for i in range(n)),
    lambda n: 'Write-Output "' + "[IO.File]::WriteAllText(" * n,
]


def _analyse(command: str, cwd: str) -> None:
    codex_reads.write_targets("Bash", {"command": command}, cwd, {})
    codex_reads.literal_reads({"command": command}, cwd, {})


@pytest.mark.perf
@pytest.mark.parametrize("build", HOSTILE)
def test_the_analysis_is_linear(build, tmp_path):
    """REQ-006: no backtracking and no rescans. Four times the command costs about four times
    (a quadratic cost would be sixteen), measured with `tests/perf.py` (garbage collector off)."""
    small, large = build(5_000), build(20_000)
    perf.assert_linear(
        lambda: _analyse(small, str(tmp_path)),
        lambda: _analyse(large, str(tmp_path)),
        size_ratio=4,
    )


def test_the_here_strings_are_found_as_the_old_regex_found_them():
    """`herestring_spans` replaced a lazy regex that was quadratic: same matches on random text."""
    old = re.compile(r"@'.*?'@|@\".*?\"@", re.DOTALL)
    rng = random.Random(724)
    for _ in range(5_000):
        text = "".join(rng.choice("@'\"x\n") for _ in range(rng.randint(0, 30)))
        assert read_classifier.herestring_spans(text) == [m.span() for m in old.finditer(text)]


def test_the_hook_process_refuses_the_write_of_issue_724(world, tmp_path):
    """REQ-007: the real hook, fed by stdin the `PreToolUse` event Codex sends, with #724's command."""
    _guard(world)
    payload = base._payload(world, "Bash", {"command": PREAMBLE + ISSUE_724})
    assert set(base._fixture("pre_tool_use_bash")) <= set(payload)
    result = base._hook(json.dumps(payload).encode("utf-8"), base._sandbox(tmp_path, world))
    assert result.returncode == 0, result.stderr
    assert "solo se ha leido resumido" in base._denied(json.loads(result.stdout))


def test_the_hook_process_control_another_file_passes(world, tmp_path):
    _guard(world)
    command = PREAMBLE + ISSUE_724.replace("'notes.md'", "'other.md'")
    payload = base._payload(world, "Bash", {"command": command})
    result = base._hook(json.dumps(payload).encode("utf-8"), base._sandbox(tmp_path, world))
    assert result.returncode == 0, result.stderr
    if result.stdout:
        _passes(json.loads(result.stdout))
