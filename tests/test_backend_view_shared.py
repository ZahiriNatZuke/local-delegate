"""El panel y la banda del mod deciden el estado del backend con la MISMA regla (issue #612).

La histéresis del panel (REQ-028: un fallo tras un sondeo bueno conserva lo que se pintaba; el
segundo fallo seguido es «caído») vive en una sola fuente, `mod/common.js`, y `web/metrics.py` sirve
ese mismo bloque. Aquí se comprueba que:

- el panel sirve exactamente el texto de `common.js` (sin `export`), y una sola vez;
- ante las mismas secuencias de sondeos, el estado que pinta el panel (`visibleState`) y el que
  pinta la banda (`statusShownBackend` + `statusSnapshot` del mod) coinciden paso a paso.

Las dos partes se EJECUTAN con node: el panel desde `metrics.HTML`, el mod desde sus módulos.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_dashboard_js import _extract

from local_delegate.web import metrics

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "local_delegate" / "resources" / "claude-plugin" / "local-delegate" / "mod"

GOOD = {"available": True, "running": [{"model": "qwen3-8b", "state": "ready"}], "models": []}
BAD = {
    "available": False,
    "running": [],
    "models": [],
    "cause": "timeout",
    "label": "sin respuesta",
}
# `None`: `/api/backend` did not answer at all (not a probe, in either of them).
RUNS = [
    [GOOD, BAD, GOOD],
    [GOOD, BAD, BAD, GOOD],
    [BAD, BAD, GOOD, BAD, None, BAD],
    [BAD, GOOD, BAD, None, GOOD, BAD, BAD, BAD],
]
_rng = random.Random(612)
RUNS += [[_rng.choice([GOOD, BAD, None]) for _ in range(8)] for _ in range(150)]


def _shared_block() -> str:
    source = (MOD / "common.js").read_text(encoding="utf-8")
    start = source.index(metrics.BACKEND_VIEW_START)
    end = source.index(metrics.BACKEND_VIEW_END, start)
    block = source[source.index("\n", start) + 1 : end]
    return re.sub(r"^export ", "", block, flags=re.MULTILINE).rstrip("\n")


def test_the_panel_serves_the_mod_block_once():
    block = _shared_block()
    assert "function visibleState(prev, bj){" in block
    assert block in metrics.HTML
    for header in ("function visibleState(", "function initialView("):
        assert metrics.HTML.count(header) == 1, header
    assert "__BACKEND_VIEW__" not in metrics.HTML


def _node(tmp_path: Path, program: str) -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    path = tmp_path / "tie.mjs"
    path.write_text(program, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, timeout=60, cwd=tmp_path)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return json.loads(done.stdout.decode("utf-8"))


def test_panel_and_band_say_the_same(tmp_path):
    # The mod's own modules, as the engine loads them (an ES module that imports `./common.js`).
    (tmp_path / "common.mjs").write_text(
        (MOD / "common.js").read_text(encoding="utf-8"), encoding="utf-8"
    )
    status = (
        (MOD / "status.js").read_text(encoding="utf-8").replace("'./common.js'", "'./common.mjs'")
    )
    (tmp_path / "status.mjs").write_text(status, encoding="utf-8")
    panel = "\n".join(_extract(f"function {name}(") for name in ("initialView", "visibleState"))
    program = f"""
import {{ statusShownBackend, statusSnapshot }} from './status.mjs'
import {{ visibleState }} from './common.mjs'
const panelView = (() => {{ {panel}; return {{ initialView, visibleState }} }})()
const RUNS = {json.dumps(RUNS)}
const STATS = {{ tokens_context_net: 100, total: {{ calls: 1 }} }}
const out = []
for (const sequence of RUNS) {{
  let pv = panelView.initialView()
  const mod = {{ backend: null, backendView: null }}
  const steps = []
  for (const bj of sequence) {{
    if (bj === null) {{ steps.push(null); continue }}   // neither of them counts it
    pv = panelView.visibleState(pv, bj)
    // What the band does with each answer of /api/backend (statusRead + statusApply).
    mod.backend = bj
    mod.backendView = visibleState(mod.backendView, bj)
    const band = statusSnapshot(STATS, statusShownBackend(mod), null).backend
    steps.push([pv.status, band])
  }}
  out.push(steps)
}}
console.log(JSON.stringify(out))
"""
    results = _node(tmp_path, program)
    # The panel's three states and the band's: «connected» is ready, «down» is down, «checking» is
    # no backend state at all.
    same = {"connected": "ready", "down": "down", "checking": None}
    checked = 0
    for sequence, steps in zip(RUNS, results, strict=True):
        for bj, step in zip(sequence, steps, strict=True):
            if bj is None:
                continue
            panel_status, band = step
            assert band == same[panel_status], (sequence, steps)
            checked += 1
    assert checked > 500, "las secuencias no llegaron a comprobar nada"
    # The issue's case: one slow probe after a good one is not «down» in either.
    assert results[0] == [["connected", "ready"], ["connected", "ready"], ["connected", "ready"]]
    assert results[1][2] == ["down", "down"]
