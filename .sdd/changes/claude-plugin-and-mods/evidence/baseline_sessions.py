"""Baseline: sessions with >=1 model-decided delegation in the last N days, tests excluded.

Prints only counts. Transcript contents never leave this process: files are scanned for
`toolu_...` ids and for the `entrypoint` key of their first lines, nothing else is printed.

Run with the repo venv:  .venv/Scripts/python.exe baseline_sessions.py [--days 28]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_delegate import attribution, config, test_windows

TOOLU = re.compile(r"toolu_[A-Za-z0-9]+")


def load_rows(log_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for f in sorted(log_dir.glob("usage-*.jsonl")):
        month = f.stem.split("-")[1]
        file_rows = []
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                file_rows.append(json.loads(line))
            except ValueError:
                continue
        entries = attribution._load_entries(attribution.backfill_path(log_dir, month)) or {}
        for key, row in zip(attribution.file_keys(file_rows), file_rows, strict=True):
            row["_bf"] = entries.get(key)
            rows.append(row)
    return rows


def session_of(path: Path, projects: Path) -> tuple[str, str]:
    """(project dir, session id) of a transcript; subagent files map to their parent session."""
    rel = path.relative_to(projects).parts
    project = rel[0]
    if len(rel) == 2:
        return project, Path(rel[1]).stem
    return project, rel[1]  # <project>/<session>/subagents/agent-*.jsonl


def entrypoint(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                try:
                    ep = json.loads(line).get("entrypoint")
                except ValueError:
                    continue
                if ep:
                    return str(ep)
    except OSError:
        # An unreadable transcript just has an unknown entrypoint.
        return "?"
    return "?"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    args = ap.parse_args()
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=args.days)
    log_dir = Path(config.LOG_DIR)
    windows = test_windows.load(log_dir)

    reasons = collections.Counter()
    by_client = collections.Counter()
    model_ids: set[str] = set()
    no_id = 0
    for row in load_rows(log_dir):
        try:
            ts = test_windows.parse_instant(row.get("ts"))
        except ValueError:  # parse_instant only raises ValueError on a bad timestamp
            continue
        if ts < cutoff:
            continue
        reason = attribution.test_reason(row, row["_bf"])
        if not reason and windows.find(row.get("ts")):
            reason = "test_window"
        if reason:
            reasons[reason] += 1
            continue
        client = str(row.get("client") or "None")
        by_client[client] += 1
        if client == "claude-code":
            tid = row.get("tool_use_id")
            if isinstance(tid, str) and tid:
                model_ids.add(tid)
            else:
                no_id += 1

    projects = Path.home() / ".claude" / "projects"
    cut_s = cutoff.timestamp()
    top_sessions: dict[tuple[str, str], str] = {}
    hit_sessions: set[tuple[str, str]] = set()
    found_ids: set[str] = set()
    for path in projects.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < cut_s:
                continue
        except OSError:
            continue
        key = session_of(path, projects)
        if len(path.relative_to(projects).parts) == 2:
            top_sessions[key] = entrypoint(path)
        if not model_ids:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        ids = model_ids.intersection(TOOLU.findall(text))
        if ids:
            found_ids |= ids
            hit_sessions.add(key)

    codex = Path.home() / ".codex" / "sessions"
    codex_n = (
        sum(1 for p in codex.rglob("*.jsonl") if p.stat().st_mtime >= cut_s)
        if codex.exists()
        else 0
    )

    eps = collections.Counter(top_sessions.values())
    hit_eps = collections.Counter(top_sessions.get(k, "?(no top file)") for k in hit_sessions)
    print(
        json.dumps(
            {
                "window": [cutoff.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")],
                "excluded_rows": dict(reasons),
                "counted_rows_by_client": dict(by_client),
                "claude_code_rows_with_tool_use_id": len(model_ids),
                "claude_code_rows_without_id": no_id,
                "ids_found_in_transcripts": len(found_ids),
                "claude_sessions_with_delegation": len(hit_sessions),
                "claude_sessions_with_delegation_by_entrypoint": dict(hit_eps),
                "claude_sessions_total_touched": len(top_sessions),
                "claude_sessions_total_by_entrypoint": dict(eps),
                "codex_session_files_touched": codex_n,
                "codex_rows_counted": by_client.get("codex-mcp-client", 0),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
