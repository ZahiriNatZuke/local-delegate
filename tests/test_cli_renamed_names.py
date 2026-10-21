"""Nombres renombrados del entorno, con su alias viejo en los hooks instalados (SDD english-names).

REQ-002: las variables del bloqueo, con el nombre viejo vivo en los hooks instalados (se retira en
el lote L5 de retire-legacy-aliases). La parte del CLI está en `tests/test_retired_cli_names.py` y
la del paquete y `local_status` en `tests/test_retired_env_names.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_install import _install

RENAMED_ENV = (
    ("LD_HOOK_READ_BLOCK", "LD_HOOK_READ_BLOQUEAR"),
    ("LD_HOOK_READ_SWITCH_FILE", "LD_HOOK_READ_INTERRUPTOR"),
    ("LOCAL_DELEGATE_STRUCTURED_SUMMARY", "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO"),
    ("LOCAL_DELEGATE_COST_FALLBACK", "LOCAL_DELEGATE_COSTE_RESPALDO"),
)


# --- REQ-002: variables en un hook instalado -------------------------------------------------


def _installed_prompt_hook_state(home: Path, variables: dict[str, str]) -> str:
    """Estado del bloqueo que escribe el hook de prompt INSTALADO, lanzado como subproceso."""
    _install(home, components={"hooks"}, targets={"claude"})
    hooks_dir = home / ".claude" / "hooks" / "local-delegate"
    log = home / "hooks.jsonl"
    names = {n for pair in RENAMED_ENV for n in pair}
    env = {k: v for k, v in os.environ.items() if k not in names}
    env.update({"LD_HOOK_TELEMETRY_LOG": str(log), "PYTHONPATH": str(hooks_dir), **variables})
    proc = subprocess.run(
        [sys.executable, str(hooks_dir / "suggest_delegate_prompt.py")],
        input=json.dumps({"prompt": "Hola", "session_id": "s-a1"}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["block"]


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ({"LD_HOOK_READ_BLOQUEAR": "1"}, "on"),
        ({"LD_HOOK_READ_BLOCK": "1"}, "on"),
        ({"LD_HOOK_READ_BLOCK": "0", "LD_HOOK_READ_BLOQUEAR": "1"}, "off_variable"),
        ({}, "off_variable"),
    ],
    ids=["old-only", "new-only", "both-new-wins", "none"],
)
def test_installed_hook_reads_block_variable_and_alias(tmp_path, variables, expected):
    switch = {"LD_HOOK_READ_SWITCH_FILE": str(tmp_path / "missing")}
    assert _installed_prompt_hook_state(tmp_path, {**switch, **variables}) == expected


@pytest.mark.parametrize(
    "variables",
    [
        {"LD_HOOK_READ_INTERRUPTOR": "{switch}"},
        {"LD_HOOK_READ_SWITCH_FILE": "{switch}"},
        {"LD_HOOK_READ_SWITCH_FILE": "{switch}", "LD_HOOK_READ_INTERRUPTOR": "{other}"},
    ],
    ids=["old-only", "new-only", "both-new-wins"],
)
def test_installed_hook_reads_switch_file_variable_and_alias(tmp_path, variables):
    switch = tmp_path / "off.flag"
    switch.write_text("", encoding="utf-8")
    other = tmp_path / "missing"
    resolved = {k: v.format(switch=switch, other=other) for k, v in variables.items()}
    state = _installed_prompt_hook_state(tmp_path, {"LD_HOOK_READ_BLOCK": "1", **resolved})
    assert state == "off_file"
