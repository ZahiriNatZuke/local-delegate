"""`local_status` and this repo's own use (usage-log-project-and-own-repo-exclusion, REQ-021;
dashboard-project-filter).

The month's figures (events, net and gross saving) stay exactly as they are, with or without the
project fields. Since dashboard-project-filter there is no line about "this repo's" events: it only
meant something to whoever develops local-delegate, so `local_status` no longer says it, in
Spanish or English. A test row is still out of the events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import backend_mock
import httpx2

from local_delegate import config, i18n, server

SELF_ES = "del propio repo (local-delegate)"
SELF_EN = "from this repo (local-delegate)"


def _row(minutes: int, kind: str | None, client: str = "claude-code") -> dict:
    row = {
        "ts": (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(),
        "tool": "local_summarize",
        "source": "path",
        "chars_in": 4000 + minutes,
        "ok": True,
        "client": client,
    }
    if kind is not None:
        row["caller_project"] = f"{minutes:016x}"
        row["caller_project_kind"] = kind
    return row


#: Two own rows, one of another project, one without kind and an own TEST row (client `mcp`).
MONTH = [
    _row(10, "self"),
    _row(11, "self"),
    _row(12, "other"),
    _row(13, None),
    _row(14, "self", client="mcp"),
]


def _status(monkeypatch, tmp_path, rows: list[dict]) -> str:
    log = tmp_path / f"usage-{datetime.now(UTC):%Y%m}.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get("http://test-backend/running").mock(side_effect=httpx2.ConnectError("down"))
    return server.local_status()


def _events_line(text: str, marker: str) -> str:
    (line,) = [line for line in text.splitlines() if marker in line]
    return line


def _without_kind(rows: list[dict]) -> list[dict]:
    return [
        {k: v for k, v in row.items() if k not in ("caller_project", "caller_project_kind")}
        for row in rows
    ]


@backend_mock.mock
def test_there_is_no_own_repo_line_and_the_figures_do_not_change(monkeypatch, tmp_path):
    """Mutant: the own-repo line comes back; the `self` rows are there, so it would show."""
    text = _status(monkeypatch, tmp_path, MONTH)
    assert "eventos: 4 " in text
    assert "(1 de pruebas fuera)" in text
    assert SELF_ES not in text
    assert "propio repo" not in text
    # The same month without the new fields: the events line (events, calls, net, gross) is the same.
    with_kind = _events_line(text, "eventos:")
    before = _events_line(_status(monkeypatch, tmp_path, _without_kind(MONTH)), "eventos:")
    assert with_kind == before


@backend_mock.mock
def test_the_figures_without_own_events(monkeypatch, tmp_path):
    rows = [_row(10, "other"), _row(11, None), _row(12, "self", client="mcp")]
    text = _status(monkeypatch, tmp_path, rows)
    assert "eventos: 2 " in text
    assert SELF_ES not in text


@backend_mock.mock
def test_no_own_repo_line_in_english_either(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    text = _status(monkeypatch, tmp_path, MONTH)
    assert "events: 4 " in text
    assert SELF_EN not in text
    assert "this repo" not in text
