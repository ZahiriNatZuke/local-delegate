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
def _claude_escribe(home: Path, var: str | None) -> None:
    entry: dict = {"type": "http", "url": URL}
    if var:
        entry["headers"] = {"Authorization": f"Bearer ${{{var}}}"}
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {inst.SERVER_NAME: entry}}), encoding="utf-8"
    )


def _claude_lee(home: Path) -> str | None:
    data = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    return (data["mcpServers"][inst.SERVER_NAME].get("headers") or {}).get("Authorization")


def _codex_escribe(home: Path, var: str | None) -> None:
    lineas = [f"[mcp_servers.{inst.SERVER_NAME}]", f"url = {json.dumps(URL)}"]
    if var:
        lineas.append(f"bearer_token_env_var = {json.dumps(var)}")
    # Con marcadores: una entrada gestionada, que `install` reemplaza sin preguntar.
    texto = inst.upsert_codex_mcp("", "\n".join(lineas))
    (home / ".codex" / "config.toml").write_text(texto, encoding="utf-8")


def _codex_lee(home: Path) -> str | None:
    data = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    var = data["mcp_servers"][inst.SERVER_NAME].get("bearer_token_env_var")
    return f"Bearer ${{{var}}}" if var else None


def _opencode_escribe(home: Path, var: str | None) -> None:
    entry: dict = {"type": "remote", "url": URL}
    if var:
        entry["headers"] = {"Authorization": f"Bearer {{env:{var}}}"}
    (inst.opencode_dir(home) / "opencode.json").write_text(
        json.dumps({"$schema": inst.OPENCODE_SCHEMA, "mcp": {inst.SERVER_NAME: entry}}),
        encoding="utf-8",
    )


def _opencode_lee(home: Path) -> str | None:
    entry = inst.opencode_mcp_installed(home)
    assert entry is not None, "la entrada de opencode desapareció"
    valor = (entry.get("headers") or {}).get("Authorization")
    # Se normaliza a la sintaxis de Claude Code para comparar los tres con la misma expectativa.
    return valor.replace("{env:", "${") if valor else None


CLIENTES = {
    "claude": (_claude_escribe, _claude_lee),
    "codex": (_codex_escribe, _codex_lee),
    "opencode": (_opencode_escribe, _opencode_lee),
}


def _home_con(monkeypatch, tmp_path: Path, cliente: str, var: str | None) -> Path:
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(
        tmp_path,
        claude=cliente == "claude",
        codex=cliente == "codex",
        opencode=cliente == "opencode",
        complete=False,
    )
    CLIENTES[cliente][0](home, var)
    return home


def _install(home: Path, cliente: str, *extra: str) -> int:
    argv = ["install", "--home", str(home), "--clients", cliente]
    argv += ["--no-hooks", "--no-skill", "--no-memory", *extra]
    try:
        return cli.run(argv)
    except SystemExit as exc:  # argparse sale así ante un flag que no conoce
        return int(exc.code or 0)


# --- Los tres estados del flag ------------------------------------------------
@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_sin_flag_se_conserva_la_cabecera_que_ya_estaba(monkeypatch, tmp_path, cliente):
    """El caso de la avería: reinstalar sin el flag no deja al cliente en 401."""
    home = _home_con(monkeypatch, tmp_path, cliente, inst.WEB_TOKEN_VAR)

    assert _install(home, cliente, "--mcp-mode", "http") == 0

    assert CLIENTES[cliente][1](home) == f"Bearer ${{{inst.WEB_TOKEN_VAR}}}"


@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_sin_flag_se_conserva_tambien_otro_nombre_de_variable(monkeypatch, tmp_path, cliente):
    """Conservar es no cambiar lo que funcionaba, no sustituirlo por nuestra variable."""
    home = _home_con(monkeypatch, tmp_path, cliente, "OTRA_VARIABLE")

    assert _install(home, cliente, "--mcp-mode", "http") == 0

    assert CLIENTES[cliente][1](home) == "Bearer ${OTRA_VARIABLE}"


@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_no_web_token_env_quita_la_cabecera_a_proposito(monkeypatch, tmp_path, cliente):
    home = _home_con(monkeypatch, tmp_path, cliente, inst.WEB_TOKEN_VAR)

    assert _install(home, cliente, "--mcp-mode", "http", "--no-web-token-env") == 0

    assert CLIENTES[cliente][1](home) is None


@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_sin_flag_y_sin_cabecera_previa_no_aparece_ninguna(monkeypatch, tmp_path, cliente):
    """Control: conservar no es inventar. Quien no usaba token sigue sin él."""
    home = _home_con(monkeypatch, tmp_path, cliente, None)

    assert _install(home, cliente, "--mcp-mode", "http") == 0

    assert CLIENTES[cliente][1](home) is None


@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_web_token_env_la_escribe_aunque_no_hubiera(monkeypatch, tmp_path, cliente):
    """Control del otro lado: el flag explícito sigue mandando sobre lo que hubiera."""
    home = _home_con(monkeypatch, tmp_path, cliente, None)

    assert _install(home, cliente, "--mcp-mode", "http", "--web-token-env") == 0

    assert CLIENTES[cliente][1](home) == f"Bearer ${{{inst.WEB_TOKEN_VAR}}}"


def test_los_dos_flags_a_la_vez_se_rechazan(monkeypatch, tmp_path):
    home = _home_con(monkeypatch, tmp_path, "claude", inst.WEB_TOKEN_VAR)
    antes = (home / ".claude.json").read_bytes()

    codigo = _install(home, "claude", "--mcp-mode", "http", "--web-token-env", "--no-web-token-env")

    assert codigo == 2
    assert (home / ".claude.json").read_bytes() == antes


def test_en_stdio_no_se_conserva_una_cabecera_que_no_pinta_nada(monkeypatch, tmp_path):
    """El token protege el puerto del daemon; una entrada stdio no habla con ese puerto."""
    home = _home_con(monkeypatch, tmp_path, "claude", inst.WEB_TOKEN_VAR)

    assert _install(home, "claude", "--mcp-mode", "stdio") == 0

    entry = json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert "headers" not in entry[inst.SERVER_NAME]


# --- Lo que dice el plan --------------------------------------------------------
def test_el_dry_run_dice_que_conserva_y_no_imprime_un_token_literal(monkeypatch, tmp_path, capsys):
    """Un token escrito a pelo se conserva en disco, pero la pantalla no lo enseña.

    La primera aserción es la guarda: sin ella, la de «no aparece el secreto» pasaría también con
    el defecto, porque una cabecera borrada tampoco se imprime.
    """
    home = _home_con(monkeypatch, tmp_path, "claude", None)
    secreto = "s3cr3t-escrito-a-pelo"
    data = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    data["mcpServers"][inst.SERVER_NAME]["headers"] = {"Authorization": f"Bearer {secreto}"}
    (home / ".claude.json").write_text(json.dumps(data), encoding="utf-8")

    assert _install(home, "claude", "--mcp-mode", "http", "--dry-run") == 0
    salida = capsys.readouterr().out

    assert "conserva la cabecera" in salida
    assert secreto not in salida

    assert _install(home, "claude", "--mcp-mode", "http") == 0
    assert _claude_lee(home) == f"Bearer {secreto}"
