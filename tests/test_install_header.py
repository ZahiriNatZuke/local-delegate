"""`install` no borra la cabecera de autorización que ya tenía una entrada MCP.

Sale de una avería real (2026-08-18, backlog 1.2): reinstalar con `--mcp-mode http` **sin**
`--web-token-env` reescribía la entrada sin `Authorization` aunque la de antes la llevara, y contra
un daemon con token el cliente pasaba a 401 al instante. `doctor` lo hace visible desde la 0.26.0;
esto lo previene.

El flag tiene tres estados y cada uno es una orden distinta:

- sin flag: se conserva lo que hubiera, **tal cual** (también el nombre de la variable);
- `--web-token-env`: se escribe la cabecera;
- `--no-web-token-env`: se quita, a propósito.

Se ejercita el CLI entero con un HOME simulado, para los tres clientes, porque cada uno guarda la
cabecera en una forma distinta y el defecto podía vivir en cualquiera de las tres lecturas.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from conftest import make_home

from local_delegate import cli
from local_delegate import install as inst

URL = "http://127.0.0.1:9393/mcp"


def _home_real(monkeypatch, path: Path) -> None:
    """Dobla el HOME real para que el de la prueba cuente como simulado (y no toque el daemon)."""
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))


# --- Cómo guarda la cabecera cada cliente -------------------------------------
# `var` es el NOMBRE de la variable; `None` significa entrada HTTP sin cabecera.
def _claude_write(home: Path, var: str | None) -> None:
    entry: dict = {"type": "http", "url": URL}
    if var:
        entry["headers"] = {"Authorization": f"Bearer ${{{var}}}"}
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {inst.SERVER_NAME: entry}}), encoding="utf-8"
    )


def _claude_read(home: Path) -> str | None:
    data = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    return (data["mcpServers"][inst.SERVER_NAME].get("headers") or {}).get("Authorization")


def _codex_write(home: Path, var: str | None) -> None:
    lines = [f"[mcp_servers.{inst.SERVER_NAME}]", f"url = {json.dumps(URL)}"]
    if var:
        lines.append(f"bearer_token_env_var = {json.dumps(var)}")
    # Con marcadores: una entrada gestionada, que `install` reemplaza sin preguntar.
    text = inst.upsert_codex_mcp("", "\n".join(lines))
    (home / ".codex" / "config.toml").write_text(text, encoding="utf-8")


def _codex_read(home: Path) -> str | None:
    data = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    var = data["mcp_servers"][inst.SERVER_NAME].get("bearer_token_env_var")
    return f"Bearer ${{{var}}}" if var else None


def _opencode_write(home: Path, var: str | None) -> None:
    entry: dict = {"type": "remote", "url": URL}
    if var:
        entry["headers"] = {"Authorization": f"Bearer {{env:{var}}}"}
    (inst.opencode_dir(home) / "opencode.json").write_text(
        json.dumps({"$schema": inst.OPENCODE_SCHEMA, "mcp": {inst.SERVER_NAME: entry}}),
        encoding="utf-8",
    )


def _opencode_read(home: Path) -> str | None:
    entry = inst.opencode_mcp_installed(home)
    assert entry is not None, "la entrada de opencode desapareció"
    value = (entry.get("headers") or {}).get("Authorization")
    # Se normaliza a la sintaxis de Claude Code para comparar los tres con la misma expectativa.
    return value.replace("{env:", "${") if value else None


CLIENTS = {
    "claude": (_claude_write, _claude_read),
    "codex": (_codex_write, _codex_read),
    "opencode": (_opencode_write, _opencode_read),
}


def _home_with(monkeypatch, tmp_path: Path, client: str, var: str | None) -> Path:
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(
        tmp_path,
        claude=client == "claude",
        codex=client == "codex",
        opencode=client == "opencode",
        complete=False,
    )
    CLIENTS[client][0](home, var)
    return home


def _install(home: Path, client: str, *extra: str) -> int:
    argv = ["install", "--home", str(home), "--clients", client]
    argv += ["--no-hooks", "--no-skill", "--no-memory", *extra]
    try:
        return cli.run(argv)
    except SystemExit as exc:  # argparse sale así ante un flag que no conoce
        return int(exc.code or 0)


# --- Los tres estados del flag ------------------------------------------------
@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_without_flag_the_existing_header_is_kept(monkeypatch, tmp_path, client):
    """El caso de la avería: reinstalar sin el flag no deja al cliente en 401."""
    home = _home_with(monkeypatch, tmp_path, client, inst.WEB_TOKEN_VAR)

    assert _install(home, client, "--mcp-mode", "http") == 0

    assert CLIENTS[client][1](home) == f"Bearer ${{{inst.WEB_TOKEN_VAR}}}"


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_without_flag_another_variable_name_is_also_kept(monkeypatch, tmp_path, client):
    """Conservar es no cambiar lo que funcionaba, no sustituirlo por nuestra variable."""
    home = _home_with(monkeypatch, tmp_path, client, "OTHER_VARIABLE")

    assert _install(home, client, "--mcp-mode", "http") == 0

    assert CLIENTS[client][1](home) == "Bearer ${OTHER_VARIABLE}"


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_no_web_token_env_removes_the_header_on_purpose(monkeypatch, tmp_path, client):
    home = _home_with(monkeypatch, tmp_path, client, inst.WEB_TOKEN_VAR)

    assert _install(home, client, "--mcp-mode", "http", "--no-web-token-env") == 0

    assert CLIENTS[client][1](home) is None


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_without_flag_or_previous_header_none_appears(monkeypatch, tmp_path, client):
    """Control: conservar no es inventar. Quien no usaba token sigue sin él."""
    home = _home_with(monkeypatch, tmp_path, client, None)

    assert _install(home, client, "--mcp-mode", "http") == 0

    assert CLIENTS[client][1](home) is None


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_web_token_env_writes_it_even_if_there_was_none(monkeypatch, tmp_path, client):
    """Control del otro lado: el flag explícito sigue mandando sobre lo que hubiera."""
    home = _home_with(monkeypatch, tmp_path, client, None)

    assert _install(home, client, "--mcp-mode", "http", "--web-token-env") == 0

    assert CLIENTS[client][1](home) == f"Bearer ${{{inst.WEB_TOKEN_VAR}}}"


def test_both_flags_at_once_are_rejected(monkeypatch, tmp_path):
    home = _home_with(monkeypatch, tmp_path, "claude", inst.WEB_TOKEN_VAR)
    before = (home / ".claude.json").read_bytes()

    exit_code = _install(
        home, "claude", "--mcp-mode", "http", "--web-token-env", "--no-web-token-env"
    )

    assert exit_code == 2
    assert (home / ".claude.json").read_bytes() == before


def test_in_stdio_a_header_that_does_nothing_is_not_kept(monkeypatch, tmp_path):
    """El token protege el puerto del daemon; una entrada stdio no habla con ese puerto."""
    home = _home_with(monkeypatch, tmp_path, "claude", inst.WEB_TOKEN_VAR)

    assert _install(home, "claude", "--mcp-mode", "stdio") == 0

    entry = json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert "headers" not in entry[inst.SERVER_NAME]


# --- Lo que dice el plan --------------------------------------------------------
def test_the_dry_run_says_it_keeps_it_and_prints_no_literal_token(monkeypatch, tmp_path, capsys):
    """Un token escrito a pelo se conserva en disco, pero la pantalla no lo enseña.

    La primera aserción es la guarda: sin ella, la de «no aparece el secreto» pasaría también con
    el defecto, porque una cabecera borrada tampoco se imprime.
    """
    home = _home_with(monkeypatch, tmp_path, "claude", None)
    secret = "s3cr3t-hardcoded"
    data = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    data["mcpServers"][inst.SERVER_NAME]["headers"] = {"Authorization": f"Bearer {secret}"}
    (home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")

    assert _install(home, "claude", "--mcp-mode", "http", "--dry-run") == 0
    output = capsys.readouterr().out

    assert "conserva la cabecera" in output
    assert secret not in output

    assert _install(home, "claude", "--mcp-mode", "http") == 0
    assert _claude_read(home) == f"Bearer {secret}"


# --- Codex con cadena literal TOML (comillas simples) -------------------------
# `bearer_token_env_var = 'VAR'` es TOML válido y es como lo deja quien edita a mano u otro programa
# que reescribe el fichero. La lectura solo reconocía comillas dobles: `existing_header` devolvía
# `None`, `install`/`update` reescribían la entrada sin la variable y Codex pasaba a 401.
def _codex_write_single_quotes(home: Path, var: str, *, url_line: str | None = None) -> None:
    lines = [
        f"[mcp_servers.{inst.SERVER_NAME}]",
        url_line or f"url = '{URL}'",
        f"bearer_token_env_var = '{var}'",
    ]
    text = inst.upsert_codex_mcp("", "\n".join(lines))
    (home / ".codex" / "config.toml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("var", ["LOCAL_DELEGATE_WEB_TOKEN", "OTHER_VARIABLE"])
def test_existing_header_reads_a_codex_literal_string(monkeypatch, tmp_path, var):
    home = _home_with(monkeypatch, tmp_path, "codex", None)
    _codex_write_single_quotes(home, var)

    assert inst.existing_header(home, "codex") == f"Bearer ${{{var}}}"


@pytest.mark.parametrize("var", ["LOCAL_DELEGATE_WEB_TOKEN", "OTHER_VARIABLE"])
def test_install_keeps_a_codex_variable_written_with_single_quotes(monkeypatch, tmp_path, var):
    """El caso de la avería: un `install` sin flag no deja a Codex en 401."""
    home = _home_with(monkeypatch, tmp_path, "codex", None)
    _codex_write_single_quotes(home, var)

    assert _install(home, "codex", "--mcp-mode", "http") == 0

    assert _codex_read(home) == f"Bearer ${{{var}}}"


def test_a_codex_variable_inside_a_comment_is_not_kept(monkeypatch, tmp_path):
    """Una línea comentada no es la configuración de Codex: no se resucita al reinstalar."""
    home = _home_with(monkeypatch, tmp_path, "codex", None)
    lines = [
        f"[mcp_servers.{inst.SERVER_NAME}]",
        f'url = "{URL}"',
        '# bearer_token_env_var = "OTHER_VARIABLE"',
    ]
    (home / ".codex" / "config.toml").write_text(
        inst.upsert_codex_mcp("", "\n".join(lines)), encoding="utf-8"
    )

    assert inst.existing_header(home, "codex") is None
