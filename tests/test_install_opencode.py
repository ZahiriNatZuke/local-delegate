"""Tests de la integración con opencode: dónde vive su config, qué se le escribe y qué NO.

Están aparte de `test_install.py` y `test_install_clients.py` porque lo que se prueba aquí es
distinto de lo que se prueba allí: no «el planificador emite la acción», sino **que la escritura
no destruya un fichero cuyo formato mal escrito deja al usuario sin cliente**. Todo lo que se
afirma sobre el comportamiento de opencode está medido contra la 1.18.11 y anotado en
`.sdd/changes/opencode-tercer-cliente/research.md`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import make_home, snapshot

from local_delegate import cli
from local_delegate import install as inst


# --- Dónde está el config: la función, no una ruta escrita a mano -------------
def test_opencode_dir_comes_from_home_when_there_is_no_xdg(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert inst.opencode_dir(tmp_path) == tmp_path / ".config" / "opencode"


def test_opencode_dir_respects_xdg_config_home_in_the_real_home(tmp_path, monkeypatch):
    """Medido: `XDG_CONFIG_HOME` gana sobre `HOME` (`opencode debug paths`).

    Sin esto, en una máquina que exporte la variable `install` escribiría un fichero que el
    cliente nunca lee, y `doctor` diría que falta la entrada recién escrita.
    """
    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: real))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert inst.opencode_dir(real) == tmp_path / "xdg" / "opencode"


def test_the_simulated_home_ignores_xdg(tmp_path, monkeypatch):
    """`--home` tiene que seguir siendo un sandbox aunque quien ejecuta tenga la variable puesta."""
    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: real))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    sim = tmp_path / "sim"
    assert inst.opencode_dir(sim) == sim / ".config" / "opencode"


# --- El escáner de JSONC ------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # El caso que hace falso el atajo `"//" in texto`, y el que más nos toca: una entrada
        # HTTP legítima lleva `http://…` dentro de una cadena.
        ('{"url": "http://127.0.0.1:9393/mcp"}', False),
        ('{"x": "no // es comentario"}', False),
        ('{"x": "una \\" comilla y // luego"}', False),
        ('{"x": "/* tampoco */"}', False),
        ("{} // esto sí", True),
        ("{ // esto sí\n}", True),
        ("/* y esto */ {}", True),
        ("{}", False),
        ("", False),
    ],
)
def test_has_comments_tells_strings_from_comments(text, expected):
    assert inst.has_comments(text) is expected


def test_strip_jsonc_leaves_parseable_json_and_keeps_the_lines():
    text = '{\n  // uno\n  "a": 1,\n  /* dos\n     sigue */\n  "b": "http://x"\n}'
    clean = inst.strip_jsonc(text)
    assert json.loads(clean) == {"a": 1, "b": "http://x"}
    # Mismo número de líneas: si `json.loads` fallara, el error señalaría el sitio de verdad.
    assert clean.count("\n") == text.count("\n")


# --- La forma de la entrada ---------------------------------------------------
def test_stdio_entry_has_the_opencode_shape():
    entry = inst.opencode_mcp_entry("stdio", None, False, "0.21.0")
    assert entry["type"] == "local"
    # `command` es SIEMPRE un array en opencode; en Claude Code es command + args.
    assert entry["command"] == ["uvx", "--from", "local-delegate-mcp==0.21.0", "local-delegate-mcp"]
    # `enabled: true` NO se escribe: la CLI del cliente tampoco lo hace, y el `--dry-run` no debe
    # prometer una clave que luego no aparece en el fichero.
    assert "enabled" not in entry


def test_http_entry_is_remote_with_the_daemon_url():
    entry = inst.opencode_mcp_entry("http", None, False, None)
    assert entry["type"] == "remote"
    assert entry["url"] == inst.daemon_mcp_url()


def test_the_key_is_referenced_with_opencode_syntax_and_never_written(monkeypatch):
    """`${VAR}` no se sustituye en opencode (medido): escribirla dejaría la variable literal."""
    monkeypatch.setenv("LOCAL_DELEGATE_API_KEY", "fake-secret")
    text = json.dumps(inst.opencode_mcp_entry("stdio", None, True, None))
    assert "{env:LOCAL_DELEGATE_API_KEY}" in text
    assert "${LOCAL_DELEGATE_API_KEY}" not in text
    assert "fake-secret" not in text


def test_the_port_token_is_not_written_either(monkeypatch):
    monkeypatch.setenv(inst.WEB_TOKEN_VAR, "fake-token")
    text = json.dumps(inst.opencode_mcp_entry("http", None, False, None, web_token_env=True))
    assert f"Bearer {{env:{inst.WEB_TOKEN_VAR}}}" in text
    assert "fake-token" not in text


def test_the_cli_arguments_reproduce_the_entry():
    """El comando va tras `--`, no como valor de una opción: así lo exige la CLI (medido)."""
    local = inst.opencode_mcp_add_args(inst.opencode_mcp_entry("stdio", None, True, None))
    assert local[:3] == ["mcp", "add", inst.SERVER_NAME]
    assert "--env" in local and "LOCAL_DELEGATE_API_KEY={env:LOCAL_DELEGATE_API_KEY}" in local
    assert local[local.index("--") + 1] == "uvx"

    remote = inst.opencode_mcp_add_args(
        inst.opencode_mcp_entry("http", None, False, None, web_token_env=True)
    )
    assert "--url" in remote and "--" not in remote
    assert any(a.startswith("Authorization=Bearer ") for a in remote)


# --- A qué fichero se escribe -------------------------------------------------
def _oc(home: Path) -> Path:
    d = inst.opencode_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_picks_json_if_it_exists_and_jsonc_otherwise(tmp_path):
    """Misma regla que usa el propio `opencode mcp add` (medida).

    Coincidir con él no es cosmético: si eligiéramos otro fichero, una instalación por CLI y otra
    por fichero acabarían en sitios distintos y la segunda parecería no haber hecho nada.
    """
    home = tmp_path / "home"
    d = _oc(home)
    assert inst.opencode_config_target(home).name == "opencode.jsonc"  # ninguno existe
    (d / "opencode.jsonc").write_text("{}", encoding="utf-8")
    assert inst.opencode_config_target(home).name == "opencode.jsonc"
    (d / "opencode.json").write_text("{}", encoding="utf-8")
    assert inst.opencode_config_target(home).name == "opencode.json"


def test_the_entry_is_found_in_either_of_the_two(tmp_path):
    """opencode los lee y los fusiona: mirar solo uno daría por ausente lo que está en el otro."""
    home = tmp_path / "home"
    d = _oc(home)
    (d / "opencode.json").write_text('{"theme": "x"}', encoding="utf-8")
    (d / "opencode.jsonc").write_text(
        '{"mcp": {"local-delegate": {"type": "remote", "url": "http://x/mcp"}}}', encoding="utf-8"
    )
    assert inst.opencode_mcp_installed(home) == {"type": "remote", "url": "http://x/mcp"}


# --- Escribir sin destruir ----------------------------------------------------
def _install(home: Path, *extra: str) -> int:
    return cli.run(["install", "--home", str(home), "--clients", "opencode", *extra])


def test_installing_only_opencode_does_not_create_the_other_two(tmp_path):
    home = tmp_path / "home"
    _oc(home)
    assert _install(home) == 0
    assert not (home / ".claude").exists()
    assert not (home / ".codex").exists()
    assert inst.opencode_mcp_installed(home) is not None


def test_installing_leaves_memory_and_skill_where_opencode_expects(tmp_path):
    home = tmp_path / "home"
    d = _oc(home)
    assert _install(home) == 0
    agents = (d / "AGENTS.md").read_text(encoding="utf-8")
    assert inst.MD_BEGIN in agents and inst.MD_END in agents
    assert (d / inst.OPENCODE_SKILL_SUBDIR / inst.SKILL_NAME / "SKILL.md").is_file()


def test_reinstalling_is_idempotent_and_keeps_foreign_content(tmp_path):
    home = tmp_path / "home"
    d = _oc(home)
    (d / "opencode.json").write_text(
        json.dumps(
            {"$schema": inst.OPENCODE_SCHEMA, "theme": "mio", "mcp": {"other": {"type": "local"}}}
        ),
        encoding="utf-8",
    )
    assert _install(home) == 0
    assert _install(home) == 0
    data = json.loads((d / "opencode.json").read_text(encoding="utf-8"))
    assert data["theme"] == "mio"
    assert set(data["mcp"]) == {"other", inst.SERVER_NAME}


def test_a_top_level_key_outside_the_schema_is_never_written(tmp_path):
    """Escribir fuera de `mcp` puede dejar al usuario sin cliente, y cuánto depende de la versión.

    Medido el 2026-09-08 con los dos binarios el mismo día: opencode 1.18.11 rechaza el config
    entero ante una clave de primer nivel desconocida (`Unrecognized key`) y 1.18.29 ya la tolera.
    La invariante se queda en su forma estricta porque la versión la elige el usuario.
    """
    home = tmp_path / "home"
    d = _oc(home)
    assert _install(home) == 0
    data = json.loads((d / "opencode.jsonc").read_text(encoding="utf-8"))
    assert set(data) <= {"$schema", "mcp"}


def test_with_comments_and_no_cli_the_file_is_not_touched(tmp_path, capsys):
    """La regla de la casa: no se pisa configuración escrita por una persona.

    Un `json.dumps` de ida y vuelta borraría los comentarios **sin que el fichero pareciera roto**,
    así que el lado seguro es no escribir, decirlo, y seguir con el resto de componentes.
    """
    home = tmp_path / "home"
    d = _oc(home)
    path = d / "opencode.jsonc"
    path.write_text('{\n  // lo escribí yo\n  "theme": "mio"\n}\n', encoding="utf-8")
    before = path.read_bytes()

    assert _install(home) == 0  # el aviso NO sube el exit code
    assert path.read_bytes() == before
    output = capsys.readouterr().out
    assert "no se tocó" in output and "comentarios" in output
    # Lo demás sí se instaló: el aviso es de una acción, no de la instalación entera.
    assert (d / "AGENTS.md").is_file()


def test_an_unreadable_config_is_not_replaced(tmp_path, capsys, monkeypatch):
    """El caso que un `_read_text` tolerante convertiría en destrucción silenciosa.

    Una lectura que devuelve `""` tanto para un fichero vacío como para uno sin permisos hace que
    el segundo parezca escribible, y entonces se escribe un config nuevo **encima del que no se
    pudo leer**. Un fichero ilegible es justo el caso en el que no hay que tocar nada.

    El fallo se **simula** en vez de hacer `chmod 000`, y no por comodidad: el `chmod` no quita la
    lectura ni en Windows ni cuando la suite corre como root, así que el test pasaría por no haber
    reproducido el caso. Es el mismo criterio que `test_unreadable_file_is_unknown_via_read_helpers`.
    """
    home = tmp_path / "home"
    d = _oc(home)
    path = d / "opencode.json"
    path.write_text('{"theme": "mio"}', encoding="utf-8")
    before = path.read_bytes()

    real = Path.read_text

    def _fails(self, *a, **kw):
        if self.name == "opencode.json":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _fails)
    assert _install(home) == 0
    output = capsys.readouterr().out
    monkeypatch.undo()

    assert path.read_bytes() == before
    assert "no se tocó" in output and "no se pudo leer" in output


def test_a_broken_config_is_not_replaced(tmp_path, capsys):
    home = tmp_path / "home"
    d = _oc(home)
    path = d / "opencode.json"
    path.write_text('{ "mcp": { roto', encoding="utf-8")
    before = path.read_bytes()

    assert _install(home) == 0
    assert path.read_bytes() == before
    assert "no se tocó" in capsys.readouterr().out


# --- Desinstalar --------------------------------------------------------------
def test_uninstall_removes_ours_and_leaves_foreign_content(tmp_path):
    home = tmp_path / "home"
    d = _oc(home)
    (d / "opencode.json").write_text(
        json.dumps({"$schema": inst.OPENCODE_SCHEMA, "mcp": {"foreign": {"type": "local"}}}),
        encoding="utf-8",
    )
    assert _install(home) == 0
    assert cli.run(["uninstall", "--home", str(home), "--clients", "opencode"]) == 0

    data = json.loads((d / "opencode.json").read_text(encoding="utf-8"))
    assert set(data["mcp"]) == {"foreign"}
    assert not (d / inst.OPENCODE_SKILL_SUBDIR / inst.SKILL_NAME).exists()
    assert inst.MD_BEGIN not in (d / "AGENTS.md").read_text(encoding="utf-8")


def test_uninstall_removes_the_mcp_key_if_left_empty(tmp_path):
    """Dejar un `"mcp": {}` sería válido, pero es basura nuestra en un fichero ajeno."""
    home = tmp_path / "home"
    d = _oc(home)
    assert _install(home) == 0
    assert cli.run(["uninstall", "--home", str(home), "--clients", "opencode"]) == 0
    data = json.loads((d / "opencode.jsonc").read_text(encoding="utf-8"))
    assert "mcp" not in data


def test_uninstall_does_not_overwrite_a_file_with_comments_either(tmp_path):
    home = tmp_path / "home"
    d = _oc(home)
    path = d / "opencode.jsonc"
    path.write_text(
        '{\n  // mio\n  "mcp": { "local-delegate": { "type": "local", "command": ["x"] } }\n}\n',
        encoding="utf-8",
    )
    before = path.read_bytes()
    assert cli.run(["uninstall", "--home", str(home), "--clients", "opencode"]) == 0
    assert path.read_bytes() == before


# --- El camino por la CLI del cliente -----------------------------------------
@pytest.fixture
def opencode_spy(monkeypatch):
    """Finge el binario `opencode`: anota la invocación y escribe lo que la CLI escribiría."""
    calls: list[dict] = []
    real_which = inst.shutil.which

    def _which(name, *a, **kw):
        return "/fake/opencode" if name == "opencode" else real_which(name, *a, **kw)

    def _run(argv, **kwargs):
        calls.append({"argv": list(argv), "env": kwargs.get("env") or {}})
        return subprocess.CompletedProcess(list(argv), returncode=0, stdout="", stderr="")

    monkeypatch.setattr(inst.shutil, "which", _which)
    monkeypatch.setattr(inst.subprocess, "run", _run)
    return calls


def test_uses_the_client_cli_and_sets_where_it_writes(tmp_path, opencode_spy):
    home = tmp_path / "home"
    d = _oc(home)
    opts = inst.Options(
        home=home, components={"mcp"}, targets={"opencode"}, python_exe="python3", use_cli=True
    )
    entry = inst.opencode_mcp_entry("stdio", None, False, None)
    inst._register_opencode_mcp(opts, entry)

    assert opencode_spy, "no se invocó el binario `opencode`"
    call = opencode_spy[0]
    assert call["argv"][:4] == ["opencode", "mcp", "add", inst.SERVER_NAME]
    # `XDG_CONFIG_HOME` se fija SIEMPRE: es lo único que garantiza que el cliente escriba donde
    # nosotros creemos que está su config, en los tres sistemas.
    assert call["env"]["XDG_CONFIG_HOME"] == str(d.parent)
    assert call["env"]["HOME"] == str(home)


def test_an_exit_0_without_entry_does_not_count_as_registered(tmp_path, opencode_spy):
    """Medido: el binario devuelve 0 también para subcomandos que no existen (`mcp remove`).

    Fiarse del `returncode` daría por hecho un registro que no ocurrió, y el fallback nunca
    correría: la entrada quedaría sin escribir y el install diría que fue bien.
    """
    home = tmp_path / "home"
    d = _oc(home)
    opts = inst.Options(
        home=home, components={"mcp"}, targets={"opencode"}, python_exe="python3", use_cli=True
    )
    detail = inst._register_opencode_mcp(opts, inst.opencode_mcp_entry("stdio", None, False, None))

    assert "escrito en" in detail, detail  # cayó al camino de fichero
    assert inst.opencode_mcp_installed(home) is not None
    assert (d / "opencode.jsonc").is_file()


# --- El diagnóstico no escribe ------------------------------------------------
def test_the_opencode_probe_writes_nothing(tmp_path):
    from local_delegate import checks

    home = make_home(tmp_path)
    before = snapshot(home)
    ctx = checks.Context(home=home, latest_release=checks.SKIP_PYPI)
    result = next(
        r for c, r in checks.run_all(ctx, groups=("scaffold",)) if c.id.endswith("opencode")
    )
    assert result.status == checks.OK
    assert snapshot(home) == before


# --- La skill de opencode también se diagnostica y se repone -------------------
# El probe miraba SOLO `~/.claude/skills/` mientras `plan_install` escribía la skill en los dos
# clientes. Con Claude Code presente eso no era un hueco de cobertura sino un **falso OK**: la
# skill de opencode borrada y `doctor` diciendo «instalada». Estos tres lo atan por el lado que
# fallaba — el dato que distingue es que la de Claude Code esté BIEN.
def _delete_the_opencode_skill(home: Path) -> Path:
    path = inst.opencode_dir(home) / inst.OPENCODE_SKILL_SUBDIR / inst.SKILL_NAME
    shutil.rmtree(path)
    return path


def _skill(home: Path):
    from local_delegate import checks

    ctx = checks.Context(home=home, latest_release=checks.SKIP_PYPI)
    return next(r for c, r in checks.run_all(ctx, groups=("scaffold",)) if c.id == "scaffold.skill")


def test_the_deleted_opencode_skill_is_not_masked_by_the_claude_code_one(tmp_path):
    from local_delegate import checks

    home = make_home(tmp_path)  # los tres clientes, y la skill de Claude Code intacta
    _delete_the_opencode_skill(home)

    result = _skill(home)
    assert result.status == checks.MISSING, result.detail
    assert "Claude Code: instalada" in result.detail  # el dato que distingue: aquélla está bien
    assert "opencode: no existe" in result.detail


def test_codex_does_not_drag_the_skill_check(tmp_path):
    """Codex no tiene skills: `plan_install` no se la escribe y el probe no puede exigírsela."""
    from local_delegate import checks

    home = make_home(tmp_path, claude=False, opencode=False)  # solo Codex, y completo
    result = _skill(home)
    assert result.status == checks.UNKNOWN, result.detail
    assert "Codex" not in result.detail


def test_update_restores_the_opencode_skill(tmp_path):
    """Sin esto el check la veía faltar y la tabla de reparaciones no tenía a quién escribirle."""
    # `opts_for` viene de `test_update` y no se copia aquí: es donde están doblados el runner, el
    # reloj y el arranque del daemon, y una segunda copia de esos dobles se queda vieja sola.
    from test_update import opts_for

    from local_delegate import update

    home = make_home(tmp_path)
    path = _delete_the_opencode_skill(home)

    update.run_update(opts_for(home), out=lambda *a: None)

    assert (path / "SKILL.md").is_file()
