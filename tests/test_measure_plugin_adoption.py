"""`scripts/measure_plugin_adoption.py`: la medición de REQ-024 de `claude-plugin-and-mods`.

Mide el % de sesiones interactivas de Claude Code con al menos una delegación decidida por el
modelo. No cuentan las llamadas del mod (`toolu_plugin_…`, REQ-015), las pruebas (la regla común y
las ventanas de `local-delegate test-window`), los subagentes ni las sesiones `-p` (`sdk-cli`). La
base empieza el 2026-10-08: antes faltan los `tool_use_id`.

Cada escenario arma un `LOG_DIR` y un `~/.claude/projects` de mentira en `tmp_path`: el script
nunca lee los reales en la suite.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from local_delegate import test_windows

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "measure_plugin_adoption", ROOT / "scripts" / "measure_plugin_adoption.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_plugin_adoption"] = module
    spec.loader.exec_module(module)
    return module


measure_plugin_adoption = _load()

SINCE = "2026-10-10T00:00:00Z"
UNTIL = "2026-10-20T00:00:00Z"


class World:
    """Un `LOG_DIR` y un `projects/` en `tmp_path`, con ayudas para sembrar filas y sesiones."""

    def __init__(self, root: Path) -> None:
        self.log_dir = root / "logs"
        self.projects = root / "projects"
        self.log_dir.mkdir()
        self.projects.mkdir()
        self._rows: list[dict] = []

    def delegation(self, tool_use_id: str | None, ts: str, client: str = "claude-code") -> None:
        row = {"ts": ts, "tool": "local_summarize", "ok": True, "client": client}
        if tool_use_id:
            row["tool_use_id"] = tool_use_id
        self._rows.append(row)
        (self.log_dir / "usage-202610.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in self._rows), encoding="utf-8"
        )

    def session(
        self,
        name: str,
        start: str,
        ids: list[str],
        *,
        entrypoint: str = "cli",
        subagent_ids: list[str] | None = None,
    ) -> None:
        lines = [{"type": "user", "entrypoint": entrypoint, "timestamp": start, "sessionId": name}]
        for tid in ids:
            lines.append(
                {
                    "type": "assistant",
                    "timestamp": start,
                    "message": {"content": [{"type": "tool_use", "id": tid, "name": "x"}]},
                }
            )
        project = self.projects / "D--proj"
        project.mkdir(exist_ok=True)
        (project / f"{name}.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8"
        )
        if subagent_ids:
            sub = project / name / "subagents"
            sub.mkdir(parents=True)
            # Como los reales: la cabecera repite `entrypoint` y `timestamp`, con `isSidechain`.
            body = [
                {
                    "type": "user",
                    "entrypoint": entrypoint,
                    "isSidechain": True,
                    "timestamp": start,
                    "sessionId": name,
                }
            ] + [
                {
                    "type": "assistant",
                    "timestamp": start,
                    "message": {"content": [{"type": "tool_use", "id": tid, "name": "x"}]},
                }
                for tid in subagent_ids
            ]
            (sub / "agent-a1.jsonl").write_text(
                "".join(json.dumps(x) + "\n" for x in body), encoding="utf-8"
            )

    def measure(self, since: str = SINCE, until: str = UNTIL) -> dict:
        return measure_plugin_adoption.measure(
            self.log_dir,
            self.projects,
            since=test_windows.parse_instant(since),
            until=test_windows.parse_instant(until),
        )


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def test_plugin_calls_excluded(world):
    """Una sesión cuya única delegación es del mod no cuenta como «con delegación».

    Guarda: la misma sesión con una del modelo sí cuenta. Mutante: no apartar `toolu_plugin_` →
    `with_delegation` sale 2.
    """
    world.delegation("toolu_plugin_ab12", "2026-10-12T10:00:00Z")
    world.session("s-mod", "2026-10-12T09:00:00Z", ["toolu_plugin_ab12"])
    world.delegation("toolu_01Model", "2026-10-12T11:00:00Z")
    world.session("s-model", "2026-10-12T10:30:00Z", ["toolu_01Model"])

    m = world.measure()
    assert m["sessions"] == 2
    assert m["with_delegation"] == 1
    assert m["excluded_rows"].get("plugin") == 1


def test_test_windows_excluded(world):
    """Una delegación dentro de una ventana de prueba no hace «con delegación» a su sesión.

    También la regla común (`attribution.test_reason`): el cliente `mcp` de los scripts.
    """
    world.delegation("toolu_01InWindow", "2026-10-12T10:00:00Z")
    world.session("s-window", "2026-10-12T09:00:00Z", ["toolu_01InWindow"])
    world.delegation("toolu_01Script", "2026-10-12T12:00:00Z", client="mcp")
    world.session("s-script", "2026-10-12T11:30:00Z", ["toolu_01Script"])
    world.delegation("toolu_01Real", "2026-10-13T10:00:00Z")
    world.session("s-real", "2026-10-13T09:00:00Z", ["toolu_01Real"])
    before = world.measure()
    assert before["with_delegation"] == 2, "guarda: sin ventana cuenta la de la ventana"
    assert before["excluded_rows"] == {"tests": 1}

    test_windows.add(world.log_dir, "2026-10-12T09:59:00Z", "2026-10-12T10:01:00Z", "prueba")
    world.delegation(None, "2026-10-01T00:00:00Z")  # tocar el log no cambia nada
    m = world.measure()
    assert m["with_delegation"] == 1
    assert m["sessions"] == 3
    assert m["excluded_rows"] == {"test_window": 1, "tests": 1}


def test_base_starts_2026_10_08(world):
    """Antes del 2026-10-08 no se mide nada, aunque se pida: faltan los `tool_use_id`."""
    world.delegation("toolu_01Old", "2026-10-05T10:00:00Z")
    world.session("s-old", "2026-10-05T09:00:00Z", ["toolu_01Old"])
    world.delegation("toolu_01New", "2026-10-09T10:00:00Z")
    world.session("s-new", "2026-10-09T09:00:00Z", ["toolu_01New"])

    m = world.measure(since="2026-09-01T00:00:00Z")
    assert measure_plugin_adoption.BASE_START == test_windows.parse_instant("2026-10-08T00:00:00Z")
    assert m["since"] == "2026-10-08T00:00:00+00:00"
    assert (m["sessions"], m["with_delegation"]) == (1, 1)


def test_counts_sessions_not_calls(world):
    """Tres delegaciones en una sesión y ninguna en otra: 1 de 2 sesiones, el 50 %."""
    ids = ["toolu_01A", "toolu_01B", "toolu_01C"]
    for tid in ids:
        world.delegation(tid, "2026-10-14T10:00:00Z")
    world.session("s-busy", "2026-10-14T09:00:00Z", ids)
    world.session("s-idle", "2026-10-14T12:00:00Z", [])

    m = world.measure()
    assert (m["sessions"], m["with_delegation"]) == (2, 1)
    assert m["pct"] == 50.0
    assert m["counted_delegations"] == 3


def test_subagent_and_print_sessions_excluded(world):
    """Ni los subagentes ni las sesiones `-p` (`sdk-cli`) entran en el numerador ni en la base.

    La sesión interactiva cuya única delegación la pidió su subagente cuenta como sesión, pero
    no como «con delegación»: la decidió otro modelo.
    """
    world.delegation("toolu_01Sub", "2026-10-15T10:00:00Z")
    world.session("s-parent", "2026-10-15T09:00:00Z", [], subagent_ids=["toolu_01Sub"])
    world.delegation("toolu_01Print", "2026-10-15T11:00:00Z")
    world.session("s-print", "2026-10-15T10:59:00Z", ["toolu_01Print"], entrypoint="sdk-cli")
    world.delegation("toolu_01Desktop", "2026-10-15T12:00:00Z")
    world.session(
        "s-desktop", "2026-10-15T11:30:00Z", ["toolu_01Desktop"], entrypoint="claude-desktop"
    )

    m = world.measure()
    assert m["sessions"] == 2  # s-parent y s-desktop; s-print no es interactiva
    assert m["with_delegation"] == 1
    assert m["sessions_by_entrypoint"] == {"claude-desktop": 1, "cli": 1}


def test_main_prints_the_criterion(world, capsys):
    """`main()` de punta a punta: la base, el después y el criterio fijado antes (REQ-024)."""
    world.delegation("toolu_01Base", "2026-10-12T10:00:00Z")
    world.session("s-base", "2026-10-12T09:00:00Z", ["toolu_01Base"])
    world.session("s-base-idle", "2026-10-13T09:00:00Z", [])
    world.session("s-after", "2026-10-22T09:00:00Z", [])

    code = measure_plugin_adoption.main(
        [
            "--log-dir",
            str(world.log_dir),
            "--projects",
            str(world.projects),
            "--install",
            "2026-10-21T20:00:00Z",
            "--now",
            "2026-10-25T00:00:00Z",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert (out["base"]["sessions"], out["base"]["pct"]) == (2, 50.0)
    assert out["after"]["sessions"] == 1
    assert out["criterion"]["min_delta_points"] == 10
    assert out["criterion"]["min_sessions"] == 30
    assert out["criterion"]["days"] == 14
    assert out["criterion"]["due"] == "2026-11-04T20:00:00+00:00"
    assert out["criterion"]["status"] == "too_early"
