#!/usr/bin/env python3
"""Después de mezclar: ¿está `main` de verdad en verde? (SDD ci-root-cause, REQ-010).

Mirar los checks y los hilos del PR no basta. Las alertas de CodeQL #228 y #231 (nivel bajo)
llevaban días abiertas en `main` sin que nadie las viera, porque nadie miraba la lista de alertas
de la rama, solo los PR. Y los checks que no son workflows (code scanning, Socket, GitGuardian)
no salen en `gh run list`.

Este script mira, para el último commit de `main`:

- todos sus check runs y sus estados de commit, con los que no estén en verde;
- las alertas **abiertas** de code scanning de `main` (`code-scanning/alerts?state=open&ref=...`),
  de cualquier gravedad.

Uso (necesita `gh` con sesión iniciada; solo lee):

    uv run python scripts/check_main.py
    uv run python scripts/check_main.py --repo owner/repo --branch main

Códigos de salida:

    0  todo en verde y ninguna alerta abierta
    1  algún check falló o hay alertas abiertas
    2  ninguno falló, pero alguno sigue corriendo: vuelve a mirar
    3  no se pudo consultar GitHub (sin `gh`, sin red o sin permiso): nada se da por bueno
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable

GOOD = frozenset({"success", "skipped", "neutral"})

OK = 0
PROBLEMS = 1
PENDING = 2
API_FAILURE = 3


class GhError(RuntimeError):
    """`gh` no devolvió nada utilizable."""


def _gh(args: list[str]) -> str:
    try:
        done = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GhError(f"{type(exc).__name__}: {exc}") from exc
    if done.returncode != 0:
        raise GhError(done.stderr.strip() or f"gh salió con {done.returncode}")
    return done.stdout


def _api(gh: Callable[[list[str]], str], path: str) -> object:
    try:
        return json.loads(gh(["api", path]))
    except json.JSONDecodeError as exc:
        raise GhError(f"respuesta ilegible de {path}: {exc}") from exc


def check_runs(gh, repo: str, sha: str) -> list[dict]:
    data = _api(gh, f"repos/{repo}/commits/{sha}/check-runs?per_page=100")
    return list(data.get("check_runs", []))


def commit_statuses(gh, repo: str, sha: str) -> list[dict]:
    data = _api(gh, f"repos/{repo}/commits/{sha}/status")
    return list(data.get("statuses", []))


def open_alerts(gh, repo: str, branch: str) -> list[dict]:
    data = _api(
        gh, f"repos/{repo}/code-scanning/alerts?state=open&ref=refs/heads/{branch}&per_page=100"
    )
    return list(data)


def evaluate(runs: list[dict], statuses: list[dict], alerts: list[dict]) -> tuple[int, list[str]]:
    """(código de salida, líneas del informe)."""
    bad: list[str] = []
    pending: list[str] = []
    for run in runs:
        name = run.get("name")
        if run.get("status") != "completed":
            pending.append(f"check `{name}`: {run.get('status')}")
        elif run.get("conclusion") not in GOOD:
            bad.append(f"check `{name}`: {run.get('conclusion')} — {run.get('html_url', '')}")
    for status in statuses:
        context = status.get("context")
        state = status.get("state")
        if state == "pending":
            pending.append(f"estado `{context}`: pending")
        elif state != "success":
            bad.append(f"estado `{context}`: {state} — {status.get('target_url', '')}")
    for alert in alerts:
        rule = alert.get("rule") or {}
        where = (alert.get("most_recent_instance") or {}).get("location") or {}
        severity = rule.get("security_severity_level") or rule.get("severity") or "?"
        bad.append(
            f"alerta #{alert.get('number')} de code scanning ({severity}) `{rule.get('id')}` en "
            f"{where.get('path')}:{where.get('start_line')} — {alert.get('html_url', '')}"
        )

    lines = [f"- {line}" for line in bad + pending]
    if bad:
        return PROBLEMS, lines
    if pending:
        return PENDING, lines
    if not runs:
        # Un commit sin ningún check no se ha comprobado; no es verde.
        return PENDING, ["- el commit todavía no tiene checks"]
    return OK, lines


def main(argv: list[str] | None = None, *, gh: Callable[[list[str]], str] = _gh) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/repo (por defecto, el del directorio actual)")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args(argv)

    try:
        repo = (
            args.repo
            or gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()
        )
        sha = _api(gh, f"repos/{repo}/commits/{args.branch}")["sha"]
        runs = check_runs(gh, repo, sha)
        statuses = commit_statuses(gh, repo, sha)
        alerts = open_alerts(gh, repo, args.branch)
    except (GhError, KeyError, TypeError) as exc:
        print(f"No se pudo consultar GitHub: {exc}", file=sys.stderr)
        print("Nada se da por bueno sin mirarlo.", file=sys.stderr)
        return API_FAILURE

    code, lines = evaluate(runs, statuses, alerts)
    title = {
        OK: f"`{args.branch}` ({sha[:10]}) en verde: {len(runs)} checks, ninguna alerta abierta",
        PROBLEMS: f"`{args.branch}` ({sha[:10]}) NO está en verde:",
        PENDING: f"`{args.branch}` ({sha[:10]}) todavía no tiene veredicto:",
    }[code]
    print(title)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
