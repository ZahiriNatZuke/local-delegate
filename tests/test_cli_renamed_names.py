"""Nombres renombrados del CLI y del entorno, con su alias viejo (SDD english-names, ola A1).

REQ-001: `recompute-cost` y `--reset-calibration`, con `recalcular-coste` y
`--reiniciar-calibracion` como alias ocultos que avisan. REQ-002: las cuatro variables, con el
nombre viejo vivo en el paquete y en los hooks instalados. REQ-003: `local_status` dice los
nombres viejos que leyó el proceso servidor.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_install import _install
from test_recompute import _delegation_with_n
from test_transcripts import subagent

from local_delegate import cli, config, deprecations, recompute, server

RENAMED_ENV = (
    ("LD_HOOK_READ_BLOCK", "LD_HOOK_READ_BLOQUEAR"),
    ("LD_HOOK_READ_SWITCH_FILE", "LD_HOOK_READ_INTERRUPTOR"),
    ("LOCAL_DELEGATE_STRUCTURED_SUMMARY", "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO"),
    ("LOCAL_DELEGATE_COST_FALLBACK", "LOCAL_DELEGATE_COSTE_RESPALDO"),
)


def _run(argv: list[str]) -> int:
    try:
        return cli.run(argv)
    except SystemExit as e:
        return int(e.code or 0)


# --- REQ-001: subcomando y opción ------------------------------------------------------------


def _recompute(tmp_path: Path, monkeypatch, capsys, command: str) -> tuple[int, dict, str]:
    claude, log = tmp_path / command / "claude", tmp_path / command / "log"
    _delegation_with_n(subagent(claude, "a1"), "toolu_cli", 3)
    monkeypatch.setattr(config, "LOG_DIR", log)
    code = _run([command, "--claude-dir", str(claude)])
    stderr = capsys.readouterr().err
    written = log / recompute.FILE_NAME
    data = json.loads(written.read_text(encoding="utf-8")) if written.is_file() else {}
    return code, data, stderr


def _without_times(data: dict) -> dict:
    """Lo escrito por dos corridas seguidas, sin lo que depende del reloj."""
    return {k: v for k, v in data.items() if "generated" not in k and "ts" not in k}


def test_legacy_command_writes_the_same_file_and_warns(tmp_path, monkeypatch, capsys):
    code_new, data_new, err_new = _recompute(tmp_path, monkeypatch, capsys, "recompute-cost")
    code_old, data_old, err_old = _recompute(tmp_path, monkeypatch, capsys, "recalcular-coste")

    assert data_new, "el nombre nuevo no escribió el fichero de agregados"
    assert code_old == code_new == 0
    assert _without_times(data_old) == _without_times(data_new)
    assert err_new == "", f"el nombre nuevo no debe avisar: {err_new!r}"
    assert "recalcular-coste" in err_old and "recompute-cost" in err_old


def test_warning_names_the_removal_version_once_released(monkeypatch, capsys):
    """Publicado en la 0.35.0, el alias vive 0.35, 0.36 y 0.37 y se retira en la 0.38.0."""
    released = tuple(
        replace(e, introduced="0.35.0") if e.old == "recalcular-coste" else e
        for e in deprecations.DEPRECATED_NAMES
    )
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", released)
    cli._warn_deprecated("recalcular-coste")
    err = capsys.readouterr().err
    assert "usa recompute-cost" in err
    assert "0.38.0" in err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--reset-calibration", "five_hour"], "five_hour"),
        (["--reiniciar-calibracion", "seven_day"], "seven_day"),
        (["--reset-calibration", "five_hour", "--reiniciar-calibracion", "five_hour"], "five_hour"),
        ([], None),
    ],
)
def test_reset_calibration_and_its_alias_reach_the_same_argument(
    argv, expected, tmp_path, monkeypatch, capsys
):
    seen: list[str | None] = []

    def fake_run(claude_dir, log_dir, *, reset=None, **_kw):
        seen.append(reset)
        return {}

    monkeypatch.setattr(recompute, "run", fake_run)
    monkeypatch.setattr(recompute, "summary_text", lambda _r: "")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    assert _run(["recompute-cost", "--claude-dir", str(tmp_path), *argv]) == 0
    assert seen == [expected]
    err = capsys.readouterr().err
    assert ("--reiniciar-calibracion" in err) == ("--reiniciar-calibracion" in argv)


def test_reset_calibration_with_two_different_values_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        recompute, "run", lambda *a, **k: pytest.fail("no debía llegar a recalcular")
    )
    argv = ["--reset-calibration", "five_hour", "--reiniciar-calibracion", "seven_day"]
    assert _run(["recompute-cost", "--claude-dir", str(tmp_path), *argv]) == 2
    assert "no coinciden" in capsys.readouterr().err


def test_help_shows_only_the_new_names(capsys):
    assert _run(["--help"]) == 0
    top = capsys.readouterr().out
    assert _run(["recompute-cost", "--help"]) == 0
    sub = capsys.readouterr().out
    assert "recompute-cost" in top and "--reset-calibration" in sub
    for old in ("recalcular-coste", "reiniciar-calibracion", "SUPPRESS"):
        assert old not in top + sub, old


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
            "LD_HOOK_READ_INTERRUPTOR": "viejo.flag",
            "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO": "1",
            "LOCAL_DELEGATE_COSTE_RESPALDO": "claude-haiku-4-5",
        }
    )
    assert values[:4] == ["True", "viejo.flag", "True", "claude-haiku-4-5"]
    assert values[4] == repr(sorted(old for _new, old in RENAMED_ENV))


def test_package_reads_the_new_names_without_deprecation():
    values = _config_in_subprocess(
        {
            "LD_HOOK_READ_BLOCK": "1",
            "LD_HOOK_READ_SWITCH_FILE": "nuevo.flag",
            "LOCAL_DELEGATE_STRUCTURED_SUMMARY": "1",
            "LOCAL_DELEGATE_COST_FALLBACK": "claude-opus-5:main",
        }
    )
    assert values == ["True", "nuevo.flag", "True", "claude-opus-5:main", "[]"]


def test_package_prefers_the_new_name_when_both_are_set():
    values = _config_in_subprocess(
        {
            "LD_HOOK_READ_BLOCK": "0",
            "LD_HOOK_READ_BLOQUEAR": "1",
            "LD_HOOK_READ_SWITCH_FILE": "nuevo.flag",
            "LD_HOOK_READ_INTERRUPTOR": "viejo.flag",
            "LOCAL_DELEGATE_STRUCTURED_SUMMARY": "0",
            "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO": "1",
            "LOCAL_DELEGATE_COST_FALLBACK": "nuevo",
            "LOCAL_DELEGATE_COSTE_RESPALDO": "viejo",
        }
    )
    assert values == ["False", "nuevo.flag", "False", "nuevo", "[]"]


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
    switch = {"LD_HOOK_READ_SWITCH_FILE": str(tmp_path / "no-existe")}
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
    switch = tmp_path / "apagado.flag"
    switch.write_text("", encoding="utf-8")
    other = tmp_path / "no-existe"
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
