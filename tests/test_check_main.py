"""`scripts/check_main.py`: checks y alertas de CodeQL de `main` tras mezclar (SDD ci-root-cause).

REQ-010. Las alertas #228 y #231 estuvieron abiertas en `main` sin que nadie las viera, porque solo
se miraban los PR. Los casos con `gh` simulado: verde, un check rojo, una alerta abierta, algo
corriendo y la API caída; los controles son los que NO pueden dar verde.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"

if not (SCRIPTS / "check_main.py").is_file():
    pytest.skip("scripts/ no está en el árbol (sdist)", allow_module_level=True)

spec = importlib.util.spec_from_file_location("_test_check_main", SCRIPTS / "check_main.py")
check_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_main)

GREEN_RUNS = [
    {"name": "ci-gate", "status": "completed", "conclusion": "success"},
    {"name": "Analyze (python)", "status": "completed", "conclusion": "success"},
]
ALERT = {
    "number": 228,
    "html_url": "https://github.com/o/r/security/code-scanning/228",
    "rule": {"id": "py/redos", "severity": "note"},
    "most_recent_instance": {"location": {"path": "src/x.py", "start_line": 12}},
}


def _fake_gh(*, runs=GREEN_RUNS, statuses=(), alerts=(), fail=None):
    calls = []

    def gh(args):
        calls.append(args)
        if fail and any(fail in a for a in args):
            raise check_main.GhError("HTTP 403: Resource not accessible")
        if args[0] == "repo":
            return "o/r\n"
        path = args[1]
        if path.endswith("/commits/main"):
            return json.dumps({"sha": "abcdef1234567890"})
        if "/check-runs" in path:
            return json.dumps({"check_runs": list(runs)})
        if path.endswith("/status"):
            return json.dumps({"statuses": list(statuses)})
        if "code-scanning/alerts" in path:
            return json.dumps(list(alerts))
        raise AssertionError(path)

    return gh, calls


def test_a_green_main_without_alerts_passes(capsys):
    gh, calls = _fake_gh()
    assert check_main.main([], gh=gh) == check_main.OK
    assert "en verde" in capsys.readouterr().out
    alerts_call = next(c for c in calls if "code-scanning" in c[-1])
    assert "state=open" in alerts_call[-1] and "ref=refs/heads/main" in alerts_call[-1]


def test_control_an_open_codeql_alert_of_any_severity_fails(capsys):
    gh, _ = _fake_gh(alerts=[ALERT])
    assert check_main.main([], gh=gh) == check_main.PROBLEMS
    out = capsys.readouterr().out
    assert "#228" in out and "py/redos" in out and "src/x.py:12" in out and "note" in out


def test_control_a_red_check_fails():
    runs = [*GREEN_RUNS, {"name": "perf", "status": "completed", "conclusion": "failure"}]
    gh, _ = _fake_gh(runs=runs)
    assert check_main.main([], gh=gh) == check_main.PROBLEMS


def test_control_a_cancelled_check_or_a_failed_status_fails():
    runs = [*GREEN_RUNS, {"name": "lint", "status": "completed", "conclusion": "cancelled"}]
    assert check_main.evaluate(runs, [], [])[0] == check_main.PROBLEMS
    statuses = [{"context": "socket-security", "state": "failure"}]
    assert check_main.evaluate(GREEN_RUNS, statuses, [])[0] == check_main.PROBLEMS


def test_a_running_check_is_pending_not_green():
    runs = [*GREEN_RUNS, {"name": "test (macos-latest)", "status": "in_progress"}]
    assert check_main.evaluate(runs, [], [])[0] == check_main.PENDING


def test_a_commit_without_checks_is_not_green():
    assert check_main.evaluate([], [], [])[0] == check_main.PENDING


def test_control_without_access_to_the_alerts_nothing_is_green(capsys):
    gh, _ = _fake_gh(fail="code-scanning")
    assert check_main.main([], gh=gh) == check_main.API_FAILURE
    assert "403" in capsys.readouterr().err
