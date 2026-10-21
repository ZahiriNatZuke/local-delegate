"""Nombres renombrados del entorno, con su alias viejo (SDD english-names, ola A1).

REQ-002: las cuatro variables, con el nombre viejo vivo en el paquete y en los hooks instalados.
REQ-003: `local_status` dice los nombres viejos que leyó el proceso servidor. La parte del CLI
está en `tests/test_retired_cli_names.py` (SDD retire-legacy-aliases, L3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_install import _install

from local_delegate import config, server

RENAMED_ENV = (
    ("LD_HOOK_READ_BLOCK", "LD_HOOK_READ_BLOQUEAR"),
    ("LD_HOOK_READ_SWITCH_FILE", "LD_HOOK_READ_INTERRUPTOR"),
    ("LOCAL_DELEGATE_STRUCTURED_SUMMARY", "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO"),
    ("LOCAL_DELEGATE_COST_FALLBACK", "LOCAL_DELEGATE_COSTE_RESPALDO"),
)


# --- REQ-002: variables en el paquete --------------------------------------------------------

_PRINT_CONFIG = (
    "from local_delegate import config; "
    "print(config.HOOK_READ_BLOCK, config.HOOK_READ_SWITCH_FILE, config.STRUCTURED_SUMMARY, "
    "config.COST_FALLBACK, sorted(config.DEPRECATED_SEEN), sep='|')"
)


def _config_in_subprocess(variables: dict[str, str]) -> list[str]:
    names = {n for pair in RENAMED_ENV for n in pair}
    env = {k: v for k, v in os.environ.items() if k not in names}
    env.update(variables)
    out = subprocess.run(
        [sys.executable, "-c", _PRINT_CONFIG],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return out.stdout.strip().split("|")


def test_package_reads_the_old_names_alone():
    values = _config_in_subprocess(
        {
            "LD_HOOK_READ_BLOQUEAR": "1",
            "LD_HOOK_READ_INTERRUPTOR": "old.flag",
            "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO": "1",
            "LOCAL_DELEGATE_COSTE_RESPALDO": "claude-haiku-4-5",
        }
    )
    assert values[:4] == ["True", "old.flag", "True", "claude-haiku-4-5"]
    assert values[4] == repr(sorted(old for _new, old in RENAMED_ENV))


def test_package_reads_the_new_names_without_deprecation():
    values = _config_in_subprocess(
        {
            "LD_HOOK_READ_BLOCK": "1",
            "LD_HOOK_READ_SWITCH_FILE": "new.flag",
            "LOCAL_DELEGATE_STRUCTURED_SUMMARY": "1",
            "LOCAL_DELEGATE_COST_FALLBACK": "claude-opus-5:main",
        }
    )
    assert values == ["True", "new.flag", "True", "claude-opus-5:main", "[]"]


def test_package_prefers_the_new_name_when_both_are_set():
    values = _config_in_subprocess(
        {
            "LD_HOOK_READ_BLOCK": "0",
            "LD_HOOK_READ_BLOQUEAR": "1",
            "LD_HOOK_READ_SWITCH_FILE": "new.flag",
            "LD_HOOK_READ_INTERRUPTOR": "old.flag",
            "LOCAL_DELEGATE_STRUCTURED_SUMMARY": "0",
            "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO": "1",
            "LOCAL_DELEGATE_COST_FALLBACK": "nuevo",
            "LOCAL_DELEGATE_COSTE_RESPALDO": "viejo",
        }
    )
    assert values == ["False", "new.flag", "False", "nuevo", "[]"]


def test_both_names_are_in_the_isolated_inventory():
    for new, old in RENAMED_ENV:
        assert new in config.ENVIRONMENT_VARIABLES, new
        assert old in config.ENVIRONMENT_VARIABLES, old


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


# --- REQ-003: `local_status` dice lo que leyó el proceso -------------------------------------


@pytest.fixture
def offline_status(monkeypatch):
    monkeypatch.setattr(
        server,
        "probe_backend",
        lambda: server.BackendState(False, [], True, "rechazada", "sin red en los tests", None),
    )
    for name in ("_vram_info", "_ram_info", "_llamaswap_groups"):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)


def test_local_status_lists_the_old_names_read_by_the_server(reload_config, offline_status):
    reload_config(LOCAL_DELEGATE_COSTE_RESPALDO="claude-haiku-4-5")
    text = server.local_status()
    assert "Nombres obsoletos leídos por este proceso:" in text
    assert "LOCAL_DELEGATE_COSTE_RESPALDO está obsoleto: usa LOCAL_DELEGATE_COST_FALLBACK" in text


def test_local_status_says_nothing_with_the_new_names(reload_config, offline_status):
    reload_config(LOCAL_DELEGATE_COST_FALLBACK="claude-haiku-4-5")
    assert "Nombres obsoletos" not in server.local_status()
