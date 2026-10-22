"""The PowerShell completion script, loaded in real pwsh 7 and Windows PowerShell 5.1.

SDD cli-completion, REQ-011 to REQ-020 and REQ-038. One process per edition runs every case with
`TabExpansion2` and writes the results as JSON, in four phases:

1. `unloaded`: the completer is NOT loaded yet (control (b) of REQ-038);
2. `dot`: the real script loaded with dot-source, counting the variables it leaves (REQ-019);
3. `synthetic`: a script rendered from a test parser with an option of optional value (REQ-014;
   the real CLI gets its first one, `--shell-completion`, in L3b);
4. `iex`: the real script again, loaded with `<cli> | Out-String | Invoke-Expression` from a real
   Python process, which replaces the synthetic completer (REQ-018).

Every process runs in an empty temporary directory: with no answer from the completer,
PowerShell completes paths, and files around would fake the controls (REQ-038).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest
from completion_shells import (
    SHELL_TIMEOUT,
    powershell_command,
    powershell_env,
    require_or_skip,
)

from local_delegate import backend_params, cli, completion, i18n

pytestmark = pytest.mark.xdist_group("completion_powershell")

EDITIONS = (
    pytest.param("pwsh", marks=pytest.mark.shell("pwsh"), id="pwsh"),
    pytest.param("powershell", marks=pytest.mark.shell("powershell"), id="powershell"),
)
WINDOWS = sys.platform == "win32"

# ASCII on purpose: Windows PowerShell 5.1 reads a BOM-less script in the ANSI code page.
RUNNER = r"""
param([string]$SpecPath, [string]$OutPath)
$ErrorActionPreference = 'Stop'
$spec = Get-Content -Raw -LiteralPath $SpecPath | ConvertFrom-Json

function Invoke-Cases($cases) {
    $rows = New-Object System.Collections.ArrayList
    foreach ($case in $cases) {
        if ($case.cwd) { Set-Location -LiteralPath $case.cwd } else { Set-Location -LiteralPath $spec.empty }
        $column = [int]$case.col
        if ($column -lt 0) { $column = $case.line.Length }
        $result = TabExpansion2 -inputScript $case.line -cursorColumn $column
        $found = New-Object System.Collections.ArrayList
        foreach ($match in $result.CompletionMatches) {
            [void]$found.Add(@{ text = $match.CompletionText; list = $match.ListItemText; type = $match.ResultType.ToString(); tip = $match.ToolTip })
        }
        [void]$rows.Add(@{ id = $case.id; matches = $found })
    }
    return ,$rows
}

$report = @{ major = $PSVersionTable.PSVersion.Major }
$report.unloaded = Invoke-Cases $spec.unloaded
Set-Location -LiteralPath $spec.empty
$before = @(Get-Variable | ForEach-Object { $_.Name })
. $spec.script
$after = @(Get-Variable | ForEach-Object { $_.Name })
$report.leaked = @($after | Where-Object { ($before -notcontains $_) -and ($_ -ne 'before') })
$report.dot = Invoke-Cases $spec.cases
. $spec.synthetic
$report.synthetic = Invoke-Cases $spec.synthetic_cases
Set-Location -LiteralPath $spec.empty
& $env:LD_TEST_PYTHON -c 'import sys; from local_delegate import cli; sys.exit(cli.run([''completion'', ''powershell'']))' | Out-String | Invoke-Expression
$report.iex = Invoke-Cases $spec.iex_cases
$json = $report | ConvertTo-Json -Depth 8 -Compress
[System.IO.File]::WriteAllText($OutPath, $json, (New-Object System.Text.UTF8Encoding $false))
"""

ROLES = list(backend_params.ROLES)
KEYS = list(backend_params.ALLOWED_KEYS)
EXE_PATH_LINE = '& "C:\\x y\\local-delegate.exe" ins' if WINDOWS else '& "/x y/local-delegate" ins'


def _case(case_id: str, line: str, col: int = -1, cwd: str | None = None) -> dict:
    return {"id": case_id, "line": line, "col": col, "cwd": cwd}


def _cases(files_dir: Path) -> list[dict]:
    return [
        # REQ-011: names registered and how PowerShell resolves them.
        _case("mcp_alias", "local-delegate-mcp ins"),
        _case("exe_name", "local-delegate.exe ins"),
        _case("exe_path", EXE_PATH_LINE),
        # REQ-012
        _case("root", "local-delegate "),
        _case("root_ba", "local-delegate ba"),
        _case("bp", "local-delegate backend-params "),
        _case("llamaswap", "local-delegate llamaswap "),
        _case("test_window", "local-delegate test-window "),
        _case("case_sensitive", "local-delegate BACKEND-PARAMS "),
        _case("after_flag", "local-delegate --version backend-params "),
        # REQ-013
        _case("install_mcp", "local-delegate install --mcp"),
        _case("serve_dashdash", "local-delegate serve --"),
        _case("serve_l", "local-delegate serve --l"),
        _case("append_again", "local-delegate install --clients claude --cli"),
        # REQ-014
        _case("mcp_mode", "local-delegate install --mcp-mode "),
        _case("mcp_mode_eq", "local-delegate install --mcp-mode=h"),
        _case("log_level", "local-delegate serve --log-level w"),
        _case("benchmark_role", "local-delegate benchmark --role "),
        _case("reset_calibration", "local-delegate recompute-cost --reset-calibration "),
        # REQ-015
        _case("set_role", "local-delegate backend-params set "),
        _case("set_key", "local-delegate backend-params set code "),
        _case("set_value", "local-delegate backend-params set code top_p "),
        _case("unset_t", "local-delegate backend-params unset vision t"),
        _case("reset_role", "local-delegate backend-params reset "),
        _case("completion", "local-delegate completion "),
        # REQ-016: free value -> PowerShell's own path completion.
        _case("free_value", "local-delegate install --home ", cwd=str(files_dir)),
        # REQ-017 / REQ-038 (a)
        _case("no_match_root", "local-delegate zzz"),
        _case("no_match_set", "local-delegate backend-params set zzz"),
        # REQ-019: cursor in the middle of the line, right after `backend-params`.
        _case("mid_line", "local-delegate backend-params set code", col=29),
    ]


SYNTHETIC_CASES = [
    _case("optional_values", "local-delegate --shell-x "),
    _case("optional_then_option", "local-delegate --shell-x --d"),
    _case("optional_consumed", "local-delegate --shell-x zsh --d"),
    _case("optional_consumed_sub", "local-delegate --shell-x zsh "),
    _case("optional_eq", "local-delegate --shell-x=z"),
    # The option right after an optional value is an option, not that value (argparse does so).
    _case("optional_then_option_value", "local-delegate --shell-x --mode "),
]


def _synthetic_script(language: str) -> str:
    parser = argparse.ArgumentParser(prog="local-delegate")
    parser.add_argument("--shell-x", nargs="?", choices=("auto", "zsh"), help="optional value")
    parser.add_argument("--dry-run", action="store_true", help="flag")
    parser.add_argument("--mode", choices=("one", "two"), help="required value")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("zeta", help="only subcommand")
    return completion.render_powershell(completion.build_model(parser), lang=language)


@pytest.fixture(scope="module", params=EDITIONS)
def ps_run(request, tmp_path_factory):
    """Runs every phase once per edition and returns the parsed report."""
    edition = request.param
    executable = require_or_skip(edition)
    work = tmp_path_factory.mktemp(f"ps-{edition}")
    empty = work / "empty"
    empty.mkdir()
    files_dir = work / "files"
    files_dir.mkdir()
    (files_dir / "known-file.txt").write_bytes(b"x")
    script = work / "local-delegate.ps1"
    script.write_bytes(completion.render("powershell").encode("utf-8"))
    synthetic = work / "synthetic.ps1"
    synthetic.write_bytes(_synthetic_script(i18n.lang()).encode("utf-8"))
    runner = work / "runner.ps1"
    runner.write_bytes(RUNNER.encode("ascii"))
    spec = {
        "empty": str(empty),
        "script": str(script),
        "synthetic": str(synthetic),
        "unloaded": [_case("unloaded_set", "local-delegate backend-params set ")],
        "cases": _cases(files_dir),
        "synthetic_cases": SYNTHETIC_CASES,
        "iex_cases": [_case("iex_tip", "local-delegate backend-p")],
    }
    spec_file = work / "spec.json"
    spec_file.write_bytes(json.dumps(spec).encode("utf-8"))
    out = work / "out.json"
    env = powershell_env(edition)
    env["LD_TEST_PYTHON"] = sys.executable
    # Module scope runs before the per-test isolation: point the Python child at the work dir.
    env["LOCAL_DELEGATE_LOG_DIR"] = str(work)
    proc = subprocess.run(
        powershell_command(executable, runner, str(spec_file), str(out)),
        cwd=empty,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=SHELL_TIMEOUT,
        check=False,
    )
    stderr = proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 0, f"{edition} exit={proc.returncode}\n{stderr}"
    report = json.loads(out.read_bytes().decode("utf-8"))
    return edition, report


def _rows(report: dict, phase: str) -> dict[str, list[dict]]:
    rows = report[phase]
    if isinstance(rows, dict):  # ConvertTo-Json in 5.1 unwraps a one-element list
        rows = [rows]
    result = {}
    for row in rows:
        found = row["matches"] or []
        if isinstance(found, dict):
            found = [found]
        result[row["id"]] = found
    return result


def _texts(report: dict, phase: str, case_id: str) -> list[str]:
    return [match["text"] for match in _rows(report, phase)[case_id]]


def _root_subcommands() -> list[str]:
    model = completion.build_model(cli.build_parser())
    return [sub.name for sub in model.nodes[()].subcommands]


def test_registered_names(ps_run):
    """REQ-011: the alias, the `.exe` name and a full path all reach the completer."""
    _, report = ps_run
    for case_id in ("mcp_alias", "exe_name", "exe_path"):
        assert _texts(report, "dot", case_id) == ["install"], case_id


def test_subcommands_at_every_level(ps_run):
    """REQ-012."""
    _, report = ps_run
    root = _texts(report, "dot", "root")
    assert root == _root_subcommands()
    assert len(root) == 14
    assert "completion" in root
    assert _texts(report, "dot", "root_ba") == ["backend-params"]
    assert _texts(report, "dot", "bp") == ["show", "set", "unset", "reset"]
    assert _texts(report, "dot", "llamaswap") == ["residency"]
    assert _texts(report, "dot", "test_window") == ["start", "stop", "add", "list"]
    assert _texts(report, "dot", "after_flag") == ["show", "set", "unset", "reset"]


def test_subcommands_are_case_sensitive(ps_run):
    """REQ-012: `BACKEND-PARAMS` is not `backend-params` for argparse, so it does not go down."""
    _, report = ps_run
    texts = _texts(report, "dot", "case_sensitive")
    assert "show" not in texts
    assert texts == _root_subcommands()


def test_options_of_the_node(ps_run):
    """REQ-013; `serve --` only in pwsh 7 (REQ-020 covers 5.1)."""
    edition, report = ps_run
    assert _texts(report, "dot", "install_mcp") == ["--mcp-mode"]
    assert _texts(report, "dot", "serve_l") == ["--log-level"]
    assert _texts(report, "dot", "append_again") == ["--clients"]
    if edition == "pwsh":
        # Declaration order: argparse adds `-h/--help` first.
        assert _texts(report, "dot", "serve_dashdash") == [
            "--help",
            "--host",
            "--port",
            "--log-level",
        ]


def test_known_limit_of_windows_powershell_with_dashdash(ps_run):
    """REQ-020: 5.1 does not call the completer for a bare `--`; with one letter it does.

    If a future 5.1 did complete `--`, this test would say so.
    """
    edition, report = ps_run
    if edition != "powershell":
        pytest.skip("the limit is of Windows PowerShell 5.1")
    assert _texts(report, "dot", "serve_dashdash") == []
    assert _texts(report, "dot", "serve_l") == ["--log-level"]


def test_option_values(ps_run):
    """REQ-014 (the `--shell-completion` cases arrive with the option, in L3b)."""
    _, report = ps_run
    assert _texts(report, "dot", "mcp_mode") == ["stdio", "http"]
    assert _texts(report, "dot", "mcp_mode_eq") == ["--mcp-mode=http"]
    assert _texts(report, "dot", "log_level") == ["warning"]
    assert _texts(report, "dot", "benchmark_role") == ROLES
    assert _texts(report, "dot", "reset_calibration") == ["five_hour", "seven_day"]


def test_option_with_optional_value(ps_run):
    """REQ-014: an optional value offers its values, and options when the word starts with `-`."""
    _, report = ps_run
    assert _texts(report, "synthetic", "optional_values") == ["auto", "zsh"]
    assert _texts(report, "synthetic", "optional_then_option") == ["--dry-run"]
    assert _texts(report, "synthetic", "optional_consumed") == ["--dry-run"]
    assert _texts(report, "synthetic", "optional_consumed_sub") == ["zeta"]
    assert _texts(report, "synthetic", "optional_eq") == ["--shell-x=zsh"]
    assert _texts(report, "synthetic", "optional_then_option_value") == ["one", "two"]


def test_positionals_by_position(ps_run):
    """REQ-015."""
    _, report = ps_run
    assert _texts(report, "dot", "set_role") == ROLES
    assert _texts(report, "dot", "set_key") == KEYS
    assert len(KEYS) == 21
    assert _texts(report, "dot", "set_value") == []
    assert _texts(report, "dot", "unset_t") == ["temperature", "top_k", "top_p", "typical_p"]
    assert _texts(report, "dot", "reset_role") == ROLES
    assert _texts(report, "dot", "completion") == ["powershell", "zsh", "bash"]


def test_free_value_falls_back_to_paths(ps_run):
    """REQ-016: the script offers nothing and PowerShell completes the paths of the directory."""
    _, report = ps_run
    texts = _texts(report, "dot", "free_value")
    assert any("known-file.txt" in text for text in texts), texts


def test_no_match_gives_nothing(ps_run):
    """REQ-017 and control (a) of REQ-038."""
    _, report = ps_run
    assert _texts(report, "dot", "no_match_root") == []
    assert _texts(report, "dot", "no_match_set") == []


def test_unloaded_completer_gives_nothing(ps_run):
    """Control (b) of REQ-038: without the script, no `mechanical`: the cases measure the script."""
    _, report = ps_run
    assert _texts(report, "unloaded", "unloaded_set") == []


def test_cursor_in_the_middle_of_the_line(ps_run):
    """REQ-019: only the words before the cursor count."""
    _, report = ps_run
    assert _texts(report, "dot", "mid_line") == ["backend-params"]


def test_loading_leaves_no_variables(ps_run):
    """REQ-019: the tables live inside the script block."""
    _, report = ps_run
    assert report["leaked"] in ([], None), report["leaked"]


def test_result_objects(ps_run):
    """REQ-019: list text, kind (ParameterName for options, ParameterValue otherwise), tooltip."""
    _, report = ps_run
    [option] = _rows(report, "dot")["install_mcp"]
    assert option["type"] == "ParameterName"
    assert option["list"] == "--mcp-mode"
    assert option["tip"] == i18n.t("cli.help.install.mcp_mode")
    [value] = _rows(report, "dot")["mcp_mode_eq"]
    assert value["type"] == "ParameterValue"
    assert value["list"] == "http"
    assert value["tip"] == "http"


def test_tooltip_with_accents_by_dot_source_and_invoke_expression(ps_run):
    """REQ-018: the ASCII script gives the same accented help through both loading paths."""
    edition, report = ps_run
    expected = i18n.t("cli.help.backend_params")
    assert i18n.lang() == "es"
    assert any(ord(char) > 127 for char in expected)
    [by_dot] = _rows(report, "dot")["root_ba"]
    [by_iex] = _rows(report, "iex")["iex_tip"]
    assert by_dot["tip"] == expected, edition
    assert by_iex["tip"] == expected, edition
    assert by_iex["text"] == "backend-params"
