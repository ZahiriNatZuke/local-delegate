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
URL_VIEJA = "http://127.0.0.1:1/mcp"
VIEJA = "0.1.0"
NUEVA = "0.99.0"

# Lo que «pone el usuario» en cada cliente, y lo que se espera leer después.
PLAZOS = {
    "claude": {"timeout": 900000},
    "opencode": {"timeout": 900000},
    "codex": {"tool_timeout_sec": 900, "startup_timeout_sec": 30},
}
MODOS = ("stdio", "http")


def _home_real(monkeypatch, path: Path) -> None:
    """Dobla el HOME real para que el de la prueba cuente como simulado (y no toque el daemon)."""
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))


# --- Cómo deja cada cliente la entrada que el usuario editó a mano -------------
def _vieja(entry: dict) -> dict:
    return {**entry, "url": URL_VIEJA} if "url" in entry else entry


def _claude_escribe(home: Path, modo: str, plazos: dict) -> None:
    entry = _vieja(inst.mcp_entry(modo, None, False, VIEJA))
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {inst.SERVER_NAME: {**entry, **plazos}}}), encoding="utf-8"
    )


def _claude_lee(home: Path) -> dict:
    return json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"][
        inst.SERVER_NAME
    ]


def _codex_escribe(home: Path, modo: str, plazos: dict) -> None:
    # Como lo haría una persona: la línea metida DENTRO del bloque gestionado, entre las nuestras
    # y con un comentario detrás — no al final, que es donde la deja el propio `install`.
    lineas = inst.codex_mcp_block(_vieja(inst.mcp_entry(modo, None, False, VIEJA))).split("\n")
    extra = [f"{k} = {v}   # subido a mano" for k, v in plazos.items()]
    texto = "\n".join([inst.TOML_BEGIN, lineas[0], *extra, *lineas[1:], inst.TOML_END, ""])
    (home / ".codex" / "config.toml").write_text(texto, encoding="utf-8")


def _codex_lee(home: Path) -> dict:
    data = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    return data["mcp_servers"][inst.SERVER_NAME]


def _opencode_escribe(home: Path, modo: str, plazos: dict) -> None:
    entry = _vieja(inst.opencode_mcp_entry(modo, None, False, VIEJA))
    (inst.opencode_dir(home) / "opencode.json").write_text(
        json.dumps(
            {"$schema": inst.OPENCODE_SCHEMA, "mcp": {inst.SERVER_NAME: {**entry, **plazos}}}
        ),
        encoding="utf-8",
    )


def _opencode_lee(home: Path) -> dict:
    entry = inst.opencode_mcp_installed(home)
    assert entry is not None, "la entrada de opencode desapareció"
    return entry


CLIENTES = {
    "claude": (_claude_escribe, _claude_lee),
    "codex": (_codex_escribe, _codex_lee),
    "opencode": (_opencode_escribe, _opencode_lee),
}


def _home_con(monkeypatch, tmp_path: Path, cliente: str, modo: str, plazos: dict) -> Path:
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(
        tmp_path,
        claude=cliente == "claude",
        codex=cliente == "codex",
        opencode=cliente == "opencode",
        complete=False,
    )
    CLIENTES[cliente][0](home, modo, plazos)
    return home


def _install(home: Path, cliente: str, modo: str, *extra: str) -> int:
    argv = ["install", "--home", str(home), "--clients", cliente, "--mcp-mode", modo]
    argv += ["--no-hooks", "--no-skill", "--no-memory", *extra]
    return cli.run(argv)


def _plazos_de(entrada: dict, cliente: str) -> dict:
    return {k: entrada[k] for k in inst.TIMEOUT_KEYS[cliente] if k in entrada}


# --- install --------------------------------------------------------------------
@pytest.mark.parametrize("modo", MODOS)
@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_install_conserva_el_plazo_puesto_a_mano(monkeypatch, tmp_path, cliente, modo):
    home = _home_con(monkeypatch, tmp_path, cliente, modo, PLAZOS[cliente])

    assert _install(home, cliente, modo) == 0

    entrada = CLIENTES[cliente][1](home)
    # Guarda: la entrada se reescribió de verdad (el pin viejo ya no está, o es otra forma). Sin
    # ella, un `install` que no tocase nada también «conservaría» el plazo.
    assert VIEJA not in json.dumps(entrada)
    assert URL_VIEJA not in json.dumps(entrada)
    assert _plazos_de(entrada, cliente) == PLAZOS[cliente]


@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_el_plazo_sobrevive_al_cambio_de_modo_y_a_dos_pasadas(monkeypatch, tmp_path, cliente):
    """Un plazo vale igual en stdio que en http: pasar de uno a otro no lo pierde."""
    home = _home_con(monkeypatch, tmp_path, cliente, "stdio", PLAZOS[cliente])

    assert _install(home, cliente, "http") == 0
    assert _install(home, cliente, "http") == 0

    entrada = CLIENTES[cliente][1](home)
    assert entrada.get("url") == URL
    assert _plazos_de(entrada, cliente) == PLAZOS[cliente]


@pytest.mark.parametrize("modo", MODOS)
@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_sin_plazo_previo_no_aparece_uno_inventado(monkeypatch, tmp_path, cliente, modo):
    home = _home_con(monkeypatch, tmp_path, cliente, modo, {})

    assert _install(home, cliente, modo) == 0

    assert _plazos_de(CLIENTES[cliente][1](home), cliente) == {}


def test_el_bloque_de_codex_lleva_el_plazo_una_sola_vez_y_sigue_siendo_toml(monkeypatch, tmp_path):
    """Duplicar la clave haría el TOML inválido y Codex se quedaría sin NINGÚN MCP."""
    home = _home_con(monkeypatch, tmp_path, "codex", "http", PLAZOS["codex"])

    assert _install(home, "codex", "http") == 0
    assert _install(home, "codex", "http") == 0

    texto = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert texto.count("tool_timeout_sec") == 1
    tomllib.loads(texto)  # no lanza


def test_el_dry_run_dice_que_conserva_el_plazo(monkeypatch, tmp_path, capsys):
    home = _home_con(monkeypatch, tmp_path, "codex", "http", PLAZOS["codex"])
    antes = (home / ".codex" / "config.toml").read_bytes()

    assert _install(home, "codex", "http", "--dry-run") == 0

    salida = capsys.readouterr().out
    assert "conserva el plazo" in salida
    assert "tool_timeout_sec = 900" in salida
    assert (home / ".codex" / "config.toml").read_bytes() == antes


# --- Los caminos por CLI del cliente --------------------------------------------
def _opts(home: Path, target: str) -> inst.Options:
    return inst.Options(
        home=home, components={"mcp"}, targets={target}, python_exe="python", use_cli=True
    )


def test_opencode_con_plazo_no_usa_la_cli_que_lo_perderia(monkeypatch, tmp_path):
    """`opencode mcp add` no tiene opción para el plazo: se escribe el fichero."""
    home = _home_con(monkeypatch, tmp_path, "opencode", "http", PLAZOS["opencode"])
    llamadas: list = []
    monkeypatch.setattr(inst.shutil, "which", lambda name: f"/bin/{name}")

    def run(argv, **kwargs):
        llamadas.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(inst.subprocess, "run", run)

    entry = {**inst.opencode_mcp_entry("http", None, False, None), **PLAZOS["opencode"]}
    inst._register_opencode_mcp(_opts(home, "opencode"), entry)

    assert llamadas == []
    assert _plazos_de(_opencode_lee(home), "opencode") == PLAZOS["opencode"]


def test_claude_si_la_cli_descarta_el_plazo_se_escribe_el_fichero(monkeypatch, tmp_path):
    """Una CLI que dice «ok» pero no deja el plazo no cuenta como registro hecho."""
    home = _home_con(monkeypatch, tmp_path, "claude", "http", {})
    monkeypatch.setattr(inst.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        inst.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", "")
    )

    entry = {**inst.mcp_entry("http", None, False, None), **PLAZOS["claude"]}
    detalle = inst._register_claude_mcp(_opts(home, "claude"), entry)

    assert "escrito en" in detalle
    assert _plazos_de(_claude_lee(home), "claude") == PLAZOS["claude"]


# --- doctor y update --------------------------------------------------------------
def _ctx(home: Path) -> checks.Context:
    return checks.Context(
        home=home, daemon_status=lambda host, port: None, latest_release=checks.SKIP_PYPI
    )


@pytest.mark.parametrize("cliente", sorted(CLIENTES))
def test_doctor_ensena_el_plazo_puesto(monkeypatch, tmp_path, cliente):
    home = _home_con(monkeypatch, tmp_path, cliente, "http", PLAZOS[cliente])
    probe = {c.id: c for c in checks.CHECKS}[f"scaffold.mcp_{cliente}"].probe

    detalle = probe(_ctx(home)).detail

    clave, valor = next(iter(PLAZOS[cliente].items()))
    assert f"plazo {clave} = {valor}" in detalle


def test_update_conserva_el_plazo_de_los_tres_clientes(monkeypatch, tmp_path):
    """`update` cambia el pin y repara lo que falta; ninguna de las dos cosas borra el plazo."""
    _home_real(monkeypatch, tmp_path / "real")
    home = make_home(tmp_path, complete=False)
    for cliente, (escribe, _lee) in CLIENTES.items():
        escribe(home, "stdio", PLAZOS[cliente])

    opts = update.Options(
        home=home,
        version=NUEVA,
        no_restart=True,
        runner=lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
        daemon_status=lambda host, port: None,
        sleep=lambda s: None,
        spawn=lambda argv: None,
    )
    update.run_update(opts, out=lambda *a: None)

    # Guarda: `update` sí reescribió el pin de las entradas que lo llevan.
    assert f"local-delegate-mcp=={NUEVA}" in json.dumps(_claude_lee(home))
    assert f"local-delegate-mcp=={NUEVA}" in json.dumps(_codex_lee(home))
    for cliente, (_escribe, lee) in CLIENTES.items():
        assert _plazos_de(lee(home), cliente) == PLAZOS[cliente], cliente


def test_update_que_repara_la_entrada_conserva_el_plazo_de_la_otra_forma(monkeypatch, tmp_path):
    """El caso en que `update` llama a `install`: la entrada de Claude se reescribe entera.

    Se fuerza con el probe en `missing` (el plan lo decide el diagnóstico) sobre una entrada que
    sí tiene plazo, para ejercer el camino de reparación con algo que conservar.
    """
    home = _home_con(monkeypatch, tmp_path, "claude", "stdio", PLAZOS["claude"])
    resultados = [
        (
            check,
            checks.Result(checks.MISSING if check.id == "scaffold.mcp_claude" else checks.OK, "x"),
        )
        for check in checks.CHECKS
    ]
    acciones, _notas = update.plan_repairs(resultados, update.Options(home=home))
    assert any(a.kind == "mcp" and a.target == "claude" for a in acciones)

    inst.apply(acciones, dry_run=False, out=lambda *a: None)

    assert _plazos_de(_claude_lee(home), "claude") == PLAZOS["claude"]
