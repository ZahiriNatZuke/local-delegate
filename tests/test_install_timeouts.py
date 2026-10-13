"""`install` y `update` no borran el plazo (timeout) que el usuario subió a mano.

Con el turno del daemon una espera puede pasar de los 60 s con los que Codex corta, y la wiki
manda subir el plazo en la propia entrada `local-delegate` de cada cliente. Hasta la 0.33.0 el
siguiente `install` (o `update`) reescribía la entrada y se lo llevaba.

Se cubre cliente × modo, porque cada cliente guarda el plazo con su propia clave y en su propio
formato, y la entrada que se reescribe es distinta en `stdio` y en `http`. El control del otro
lado está igual de cubierto: sin plazo previo no aparece uno inventado.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import make_home

from local_delegate import checks, cli, update
from local_delegate import install as inst

URL = "http://127.0.0.1:9393/mcp"
# La entrada «de antes» apunta a otro sitio y lleva otro pin: así se ve que `install` la reescribió.
OLD_URL = "http://127.0.0.1:1/mcp"
OLD_VERSION = "0.1.0"
NEW_VERSION = "0.99.0"

# Lo que «pone el usuario» en cada cliente, y lo que se espera leer después.
TIMEOUTS = {
    "claude": {"timeout": 900000},
    "opencode": {"timeout": 900000},
    "codex": {"tool_timeout_sec": 900, "startup_timeout_sec": 30},
}
MODES = ("stdio", "http")


def _home_real(monkeypatch, path: Path) -> None:
    """Dobla el HOME real para que el de la prueba cuente como simulado (y no toque el daemon)."""
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))


# --- Cómo deja cada cliente la entrada que el usuario editó a mano -------------
def _old_entry(entry: dict) -> dict:
    return {**entry, "url": OLD_URL} if "url" in entry else entry


def _claude_write(home: Path, mode: str, timeouts: dict) -> None:
    entry = _old_entry(inst.mcp_entry(mode, None, False, OLD_VERSION))
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {inst.SERVER_NAME: {**entry, **timeouts}}}), encoding="utf-8"
    )


def _claude_read(home: Path) -> dict:
    return json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"][
        inst.SERVER_NAME
    ]


def _codex_write(home: Path, mode: str, timeouts: dict) -> None:
    # Como lo haría una persona: la línea metida DENTRO del bloque gestionado, entre las nuestras
    # y con un comentario detrás — no al final, que es donde la deja el propio `install`.
    lines = inst.codex_mcp_block(_old_entry(inst.mcp_entry(mode, None, False, OLD_VERSION))).split(
        "\n"
    )
    extra = [f"{k} = {v}   # subido a mano" for k, v in timeouts.items()]
    text = "\n".join([inst.TOML_BEGIN, lines[0], *extra, *lines[1:], inst.TOML_END, ""])
    (home / ".codex" / "config.toml").write_text(text, encoding="utf-8")


def _codex_read(home: Path) -> dict:
    data = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    return data["mcp_servers"][inst.SERVER_NAME]


def _opencode_write(home: Path, mode: str, timeouts: dict) -> None:
    entry = _old_entry(inst.opencode_mcp_entry(mode, None, False, OLD_VERSION))
    (inst.opencode_dir(home) / "opencode.json").write_text(
        json.dumps(
            {"$schema": inst.OPENCODE_SCHEMA, "mcp": {inst.SERVER_NAME: {**entry, **timeouts}}}
        ),
        encoding="utf-8",
    )


def _opencode_read(home: Path) -> dict:
    entry = inst.opencode_mcp_installed(home)
    assert entry is not None, "la entrada de opencode desapareció"
    return entry


CLIENTS = {
    "claude": (_claude_write, _claude_read),
    "codex": (_codex_write, _codex_read),
    "opencode": (_opencode_write, _opencode_read),
}


def _home_with(monkeypatch, tmp_path: Path, client: str, mode: str, timeouts: dict) -> Path:
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(
        tmp_path,
        claude=client == "claude",
        codex=client == "codex",
        opencode=client == "opencode",
        complete=False,
    )
    CLIENTS[client][0](home, mode, timeouts)
    return home


def _install(home: Path, client: str, mode: str, *extra: str) -> int:
    argv = ["install", "--home", str(home), "--clients", client, "--mcp-mode", mode]
    argv += ["--no-hooks", "--no-skill", "--no-memory", *extra]
    return cli.run(argv)


def _timeouts_of(entry: dict, client: str) -> dict:
    return {k: entry[k] for k in inst.TIMEOUT_KEYS[client] if k in entry}


# --- install --------------------------------------------------------------------
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_install_keeps_the_hand_set_timeout(monkeypatch, tmp_path, client, mode):
    home = _home_with(monkeypatch, tmp_path, client, mode, TIMEOUTS[client])

    assert _install(home, client, mode) == 0

    entry = CLIENTS[client][1](home)
    # Guarda: la entrada se reescribió de verdad (el pin viejo ya no está, o es otra forma). Sin
    # ella, un `install` que no tocase nada también «conservaría» el plazo.
    assert OLD_VERSION not in json.dumps(entry)
    assert OLD_URL not in json.dumps(entry)
    assert _timeouts_of(entry, client) == TIMEOUTS[client]


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_the_timeout_survives_the_mode_change_and_two_passes(monkeypatch, tmp_path, client):
    """Un plazo vale igual en stdio que en http: pasar de uno a otro no lo pierde."""
    home = _home_with(monkeypatch, tmp_path, client, "stdio", TIMEOUTS[client])

    assert _install(home, client, "http") == 0
    assert _install(home, client, "http") == 0

    entry = CLIENTS[client][1](home)
    assert entry.get("url") == URL
    assert _timeouts_of(entry, client) == TIMEOUTS[client]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_without_a_previous_timeout_no_made_up_one_appears(monkeypatch, tmp_path, client, mode):
    home = _home_with(monkeypatch, tmp_path, client, mode, {})

    assert _install(home, client, mode) == 0

    assert _timeouts_of(CLIENTS[client][1](home), client) == {}


def test_the_codex_block_carries_the_timeout_once_and_is_still_toml(monkeypatch, tmp_path):
    """Duplicar la clave haría el TOML inválido y Codex se quedaría sin NINGÚN MCP."""
    home = _home_with(monkeypatch, tmp_path, "codex", "http", TIMEOUTS["codex"])

    assert _install(home, "codex", "http") == 0
    assert _install(home, "codex", "http") == 0

    text = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert text.count("tool_timeout_sec") == 1
    tomllib.loads(text)  # no lanza


def test_the_dry_run_says_it_keeps_the_timeout(monkeypatch, tmp_path, capsys):
    home = _home_with(monkeypatch, tmp_path, "codex", "http", TIMEOUTS["codex"])
    before = (home / ".codex" / "config.toml").read_bytes()

    assert _install(home, "codex", "http", "--dry-run") == 0

    output = capsys.readouterr().out
    assert "conserva el plazo" in output
    assert "tool_timeout_sec = 900" in output
    assert (home / ".codex" / "config.toml").read_bytes() == before


# --- Los caminos por CLI del cliente --------------------------------------------
def _opts(home: Path, target: str) -> inst.Options:
    return inst.Options(
        home=home, components={"mcp"}, targets={target}, python_exe="python", use_cli=True
    )


def test_opencode_with_timeout_does_not_use_the_cli_that_would_lose_it(monkeypatch, tmp_path):
    """`opencode mcp add` no tiene opción para el plazo: se escribe el fichero."""
    home = _home_with(monkeypatch, tmp_path, "opencode", "http", TIMEOUTS["opencode"])
    calls: list = []
    monkeypatch.setattr(inst.shutil, "which", lambda name: f"/bin/{name}")

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(inst.subprocess, "run", run)

    entry = {**inst.opencode_mcp_entry("http", None, False, None), **TIMEOUTS["opencode"]}
    inst._register_opencode_mcp(_opts(home, "opencode"), entry)

    assert calls == []
    assert _timeouts_of(_opencode_read(home), "opencode") == TIMEOUTS["opencode"]


def test_claude_if_the_cli_drops_the_timeout_the_file_is_written(monkeypatch, tmp_path):
    """Una CLI que dice «ok» pero no deja el plazo no cuenta como registro hecho."""
    home = _home_with(monkeypatch, tmp_path, "claude", "http", {})
    monkeypatch.setattr(inst.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        inst.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", "")
    )

    entry = {**inst.mcp_entry("http", None, False, None), **TIMEOUTS["claude"]}
    detail = inst._register_claude_mcp(_opts(home, "claude"), entry)

    assert "escrito en" in detail
    assert _timeouts_of(_claude_read(home), "claude") == TIMEOUTS["claude"]


# --- doctor y update --------------------------------------------------------------
def _ctx(home: Path) -> checks.Context:
    return checks.Context(
        home=home, daemon_status=lambda host, port: None, latest_release=checks.SKIP_PYPI
    )


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_doctor_shows_the_set_timeout(monkeypatch, tmp_path, client):
    home = _home_with(monkeypatch, tmp_path, client, "http", TIMEOUTS[client])
    probe = {c.id: c for c in checks.CHECKS}[f"scaffold.mcp_{client}"].probe

    detail = probe(_ctx(home)).detail

    key, value = next(iter(TIMEOUTS[client].items()))
    assert f"plazo {key} = {value}" in detail


def test_update_keeps_the_timeout_of_the_three_clients(monkeypatch, tmp_path):
    """`update` cambia el pin y repara lo que falta; ninguna de las dos cosas borra el plazo."""
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, complete=False)
    for client, (write, _read) in CLIENTS.items():
        write(home, "stdio", TIMEOUTS[client])

    opts = update.Options(
        home=home,
        version=NEW_VERSION,
        no_restart=True,
        runner=lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
        daemon_status=lambda host, port: None,
        sleep=lambda s: None,
        spawn=lambda argv: None,
    )
    update.run_update(opts, out=lambda *a: None)

    # Guarda: `update` sí reescribió el pin de las entradas que lo llevan.
    assert f"local-delegate-mcp=={NEW_VERSION}" in json.dumps(_claude_read(home))
    assert f"local-delegate-mcp=={NEW_VERSION}" in json.dumps(_codex_read(home))
    for client, (_write, read) in CLIENTS.items():
        assert _timeouts_of(read(home), client) == TIMEOUTS[client], client


def test_update_that_repairs_the_entry_keeps_the_timeout_the_other_way(monkeypatch, tmp_path):
    """El caso en que `update` llama a `install`: la entrada de Claude se reescribe entera.

    Se fuerza con el probe en `missing` (el plan lo decide el diagnóstico) sobre una entrada que
    sí tiene plazo, para ejercer el camino de reparación con algo que conservar.
    """
    home = _home_with(monkeypatch, tmp_path, "claude", "stdio", TIMEOUTS["claude"])
    results = [
        (
            check,
            checks.Result(checks.MISSING if check.id == "scaffold.mcp_claude" else checks.OK, "x"),
        )
        for check in checks.CHECKS
    ]
    actions, _notes = update.plan_repairs(results, update.Options(home=home))
    assert any(a.kind == "mcp" and a.target == "claude" for a in actions)

    inst.apply(actions, dry_run=False, out=lambda *a: None)

    assert _timeouts_of(_claude_read(home), "claude") == TIMEOUTS["claude"]
