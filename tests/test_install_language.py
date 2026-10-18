"""`install`, `update` y `uninstall` con el idioma (frente B, ola B5): REQ-047, D11, REQ-029, D12.

Tres bloques:

- **La preferencia** (`language.json`, REQ-047): los cinco casos de la regla de escritura, la
  regla de lectura con el fichero presente, D11 (volver a seguir al sistema) y el sandbox de
  `--home`. La regla del idioma se inyecta con `language_probe`, que llama a la función real
  (`hook_common.resolve_language`) con un entorno y una plataforma fijos: así «el sistema en
  inglés» no depende de la máquina que corre la suite.
- **Lo que se instala en el idioma vigente** (REQ-029): la skill, el bloque de memoria (un bloque
  0.34.0 en español reinstalado en inglés deja uno solo) y el catálogo de los subagentes
  (encabezado español, inglés y bloque 0.34.0).
- **D12 con el inglés:** un bloque o un catálogo al día en cualquier idioma da `OK` y `update` no
  lo reescribe, ni en la primera pasada ni en la segunda.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import OLD_SKILL_NAME, downgrade_to_0_34, make_home, snapshot
from test_update import _ctx, opts_for

from local_delegate import agents, checks, install, update
from local_delegate.resources.hooks import hook_common

SYSTEM_ES = {"LANG": "es_ES.UTF-8"}
SYSTEM_EN = {"LANG": "en_US.UTF-8"}
NO_LANGUAGE = {}  # la sesión no declara idioma: reserva


def probe(env: dict[str, str]):
    """La regla real con un entorno POSIX fijo (en POSIX manda `LANG`, no la API de Windows)."""
    return lambda data_dir: hook_common.resolve_language(data_dir, env=env, platform="linux")


def with_variable(lang: str, system: dict[str, str] = SYSTEM_EN):
    return probe({**system, "LOCAL_DELEGATE_LANG": lang})


def _opts(home: Path, data_dir: Path, env_probe, **kw) -> install.Options:
    base = dict(  # noqa: C408 — kwargs legibles
        home=home,
        components={"hooks", "skill", "memory", "mcp"},
        targets={"claude", "codex"},
        python_exe="python3",
        use_cli=False,
        data_dir=data_dir,
        language_probe=env_probe,
    )
    base.update(kw)
    return install.Options(**base)


def _install(home, data_dir, env_probe, **kw) -> list[str]:
    lines: list[str] = []
    actions = install.plan_install(_opts(home, data_dir, env_probe, **kw))
    assert install.apply(actions, dry_run=False, out=lines.append) == 0, lines
    return lines


def _uninstall(home, data_dir, **kw) -> None:
    actions = install.plan_uninstall(_opts(home, data_dir, probe(SYSTEM_EN), **kw))
    assert install.apply(actions, dry_run=False, out=lambda *_a: None) == 0


def _update_language(home, data_dir, env_probe) -> list[str]:
    """La parte de `update` que escribe la preferencia, aplicada."""
    lines: list[str] = []
    opts = opts_for(home, data_dir=data_dir, language_probe=env_probe)
    install.apply(update.language_actions(opts), dry_run=False, out=lines.append)
    return lines


def _stored(data_dir: Path) -> dict | None:
    path = data_dir / hook_common.LANGUAGE_PREFERENCE_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


@pytest.fixture
def data_dir(tmp_path) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    return path


@pytest.fixture
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    (path / ".claude").mkdir(parents=True)
    (path / ".codex").mkdir()
    return path


# --- REQ-047: la regla de escritura -----------------------------------------------------------


def test_install_with_two_system_languages_changes_the_file(home, data_dir):
    _install(home, data_dir, probe(SYSTEM_ES))
    assert _stored(data_dir) == {"lang": "es", "source": "system"}
    _install(home, data_dir, probe(SYSTEM_EN))
    assert _stored(data_dir) == {"lang": "en", "source": "system"}


def test_an_explicit_choice_survives_update_without_the_variable(home, data_dir):
    _install(home, data_dir, with_variable("es"))
    assert _stored(data_dir) == {"lang": "es", "source": "variable"}
    before = (data_dir / "language.json").read_bytes()

    lines = _update_language(home, data_dir, probe(SYSTEM_EN))

    assert lines == [], "update no debía planificar nada"
    assert (data_dir / "language.json").read_bytes() == before


def test_a_system_choice_survives_update_in_fallback(home, data_dir):
    """El mutante «escribir la reserva» hace fallar este caso."""
    _install(home, data_dir, probe(SYSTEM_ES))
    _update_language(home, data_dir, probe(NO_LANGUAGE))
    assert _stored(data_dir) == {"lang": "es", "source": "system"}


def test_update_with_the_variable_overwrites_the_preference(home, data_dir):
    _install(home, data_dir, with_variable("es"))
    _update_language(home, data_dir, with_variable("en", SYSTEM_ES))
    assert _stored(data_dir) == {"lang": "en", "source": "variable"}


def test_uninstall_deletes_the_preference(home, data_dir):
    _install(home, data_dir, with_variable("es"))
    assert (data_dir / "language.json").is_file()
    _uninstall(home, data_dir)
    assert not (data_dir / "language.json").exists()
    assert not list(data_dir.glob("language.json*")), "ni el fichero ni copias suyas"


def test_a_partial_uninstall_keeps_the_preference(home, data_dir):
    _install(home, data_dir, with_variable("es"))
    _uninstall(home, data_dir, components={"mcp"})
    assert _stored(data_dir) == {"lang": "es", "source": "variable"}


def test_the_stored_preference_wins_over_the_other_system_language(home, data_dir):
    """La lectura (REQ-018, paso 2) con el fichero que dejó `install` de verdad."""
    _install(home, data_dir, with_variable("es"))
    resolution = hook_common.resolve_language(data_dir, env=SYSTEM_EN, platform="linux")
    assert (resolution.lang, resolution.source) == ("es", "preference")
    assert resolution.stored_source == "variable"


def test_install_in_fallback_does_not_create_the_file(home, data_dir):
    lines = _install(home, data_dir, probe(NO_LANGUAGE))
    assert _stored(data_dir) is None
    assert any("no declara idioma" in line for line in lines), lines


def test_the_dry_run_writes_no_preference(home, data_dir):
    actions = install.plan_install(_opts(home, data_dir, with_variable("en")))
    install.apply(actions, dry_run=True, out=lambda *_a: None)
    assert _stored(data_dir) is None


def test_a_second_install_does_not_rewrite_the_file(home, data_dir):
    _install(home, data_dir, with_variable("en"))
    path = data_dir / "language.json"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    lines = _install(home, data_dir, with_variable("en"))
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert any("ya guardado" in line for line in lines), lines


def test_install_over_an_explicit_choice_keeps_it_and_says_how_to_follow_the_system(home, data_dir):
    _install(home, data_dir, with_variable("es"))
    lines = _install(home, data_dir, probe(SYSTEM_EN))
    assert _stored(data_dir) == {"lang": "es", "source": "variable"}
    assert any("para volver a seguir al sistema" in line for line in lines), lines
    # Y lo que se instaló va en el idioma que quedó vigente, no en el de la sesión.
    skill = (home / ".claude" / "skills" / install.SKILL_NAME / "SKILL.md").read_bytes()
    assert skill == install.skill_source("es").read_bytes()


def test_d11_deleting_the_file_follows_the_system_again(home, data_dir):
    _install(home, data_dir, with_variable("es"))
    (data_dir / "language.json").unlink()
    _install(home, data_dir, probe(SYSTEM_EN))
    assert _stored(data_dir) == {"lang": "en", "source": "system"}


def test_a_simulated_home_does_not_touch_the_data_dir(home, monkeypatch, tmp_path):
    """`--home` es un sandbox: sin `LOCAL_DELEGATE_LOG_DIR`, `language.json` no se toca."""
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)
    monkeypatch.setattr(install.config, "LOG_DIR", tmp_path / "real-data")
    opts = _opts(home, None, with_variable("en"))
    assert install.language_dir(opts) is None
    actions = install.plan_install(opts)
    assert not [a for a in actions if a.kind == "language"]
    install.apply(actions, dry_run=False, out=lambda *_a: None)
    assert not (tmp_path / "real-data").exists()
    # Pero lo instalado sigue el idioma de la sesión.
    skill = (home / ".claude" / "skills" / install.SKILL_NAME / "SKILL.md").read_bytes()
    assert skill == install.skill_source("en").read_bytes()


def test_with_the_data_dir_chosen_a_simulated_home_does_write_it(home, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "chosen"))
    monkeypatch.setattr(install.config, "LOG_DIR", tmp_path / "chosen")
    _install(home, None, with_variable("en"))
    assert _stored(tmp_path / "chosen") == {"lang": "en", "source": "variable"}


def test_run_update_writes_the_preference_and_still_says_nothing_to_repair(tmp_path, data_dir):
    """`update` entero: guardar la preferencia no es «reparar» y no tapa el «nada que reparar»."""
    home = make_home(tmp_path)
    lines: list[str] = []
    opts = opts_for(home, version="0.1.0", data_dir=data_dir, language_probe=with_variable("en"))
    update.run_update(opts, out=lines.append)
    assert _stored(data_dir) == {"lang": "en", "source": "variable"}
    lines.clear()
    update.run_update(opts, out=lines.append)
    assert not any("language" in line for line in lines), lines


# --- REQ-029: la skill, el bloque y el catálogo en el idioma vigente --------------------------


def test_the_skill_is_installed_in_english_without_the_variants(home, data_dir):
    _install(home, data_dir, with_variable("en"), targets={"claude", "opencode"})
    for root in (
        home / ".claude" / "skills",
        install.opencode_dir(home) / install.OPENCODE_SKILL_SUBDIR,
    ):
        skill_dir = root / install.SKILL_NAME
        assert (skill_dir / "SKILL.md").read_bytes() == install.skill_source("en").read_bytes()
        assert sorted(p.name for p in skill_dir.iterdir()) == ["SKILL.md"]


def test_a_0_34_spanish_block_reinstalled_in_english_leaves_one_english_block(tmp_path, data_dir):
    home = make_home(tmp_path)
    downgrade_to_0_34(home)
    assert OLD_SKILL_NAME in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")

    _install(home, data_dir, with_variable("en"), targets={"claude", "codex", "opencode"})

    for md in (home / ".claude" / "CLAUDE.md", home / ".codex" / "AGENTS.md"):
        text = md.read_text(encoding="utf-8")
        assert text.count(install.MD_BEGIN) == 1 and text.count(install.MD_END) == 1
        assert "Delegation to local models" in text
        assert "Delegación a modelos locales" not in text
        assert OLD_SKILL_NAME not in text
        assert install.memory_block_is_current(text)


def _agent(heading: str, body: str = "Delega lo mecánico.") -> str:
    return (
        f"---\nname: probe\ntools: Read, {agents.ANCHOR}\n---\n\n"
        f"## {heading}\n\n{body}\n\n## Otra sección\n\nTexto.\n"
    )


def _old_catalog_block() -> str:
    """El bloque de catálogo como lo dejaba la 0.34.0: español y con la skill vieja."""
    block = agents.catalog_block(agents.tool_catalog(install.skill_source("es")), "es")
    return block.replace(install.SKILL_NAME, OLD_SKILL_NAME)


@pytest.mark.parametrize(
    "text",
    [
        _agent("Delegación a modelos locales"),
        _agent("Delegation to local models"),
        _agent("Delegación a modelos locales", _old_catalog_block()),
    ],
    ids=["spanish-heading", "english-heading", "0.34-block"],
)
def test_subagents_get_the_english_catalog(text, home, data_dir):
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir()
    agent = agents_dir / "probe.md"
    agent.write_text(text, encoding="utf-8")

    _install(home, data_dir, with_variable("en"), components={"agents"}, targets={"claude"})

    result = agent.read_text(encoding="utf-8")
    assert result.count(agents.CATALOG_BEGIN) == 1
    assert "**Catalog of `local_*` tools" in result
    assert "Catálogo de tools" not in result
    assert OLD_SKILL_NAME not in result
    assert "Texto." in result, "lo de fuera de los marcadores no se toca"


# --- D12 con el inglés: al día en cualquier idioma, `update` no reescribe ---------------------


def _english_home(tmp_path) -> Path:
    home = make_home(tmp_path)
    english = install.memory_source("en").read_text(encoding="utf-8")
    for md in (home / ".claude" / "CLAUDE.md", home / ".codex" / "AGENTS.md"):
        md.write_text(
            install.upsert_block("", english, install.MD_BEGIN, install.MD_END), encoding="utf-8"
        )
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir()
    for lang in ("en", "es"):
        block = install.catalog_block_for(lang)
        (agents_dir / f"{lang}.md").write_text(
            _agent("Delegation to local models", block), encoding="utf-8"
        )
    return home


def _update_pass(home, data_dir) -> list:
    opts = opts_for(home, data_dir=data_dir, language_probe=with_variable("en"))
    actions, _notes = update.plan_repairs(checks.run_all(_ctx(home)), opts)
    install.apply(actions, dry_run=False, out=lambda *_a: None)
    return actions


def test_an_english_block_up_to_date_is_ok_and_update_does_not_rewrite_it(tmp_path, data_dir):
    home = _english_home(tmp_path)
    by_id = {c.id: r for c, r in checks.run_all(_ctx(home))}
    assert by_id["scaffold.memory"].status == checks.OK, by_id["scaffold.memory"].detail
    before = snapshot(home)

    first = _update_pass(home, data_dir)
    second = _update_pass(home, data_dir)

    assert [a for a in first if a.kind in ("markdown", "agents")] == [], first
    assert second == []
    assert snapshot(home) == before


def test_without_english_in_the_packaged_blocks_the_english_home_is_outdated(tmp_path, monkeypatch):
    """Control positivo de D12: si `packaged_memory_blocks()` pierde el inglés, avisa."""
    home = _english_home(tmp_path)
    spanish_only = (install.memory_source("es").read_text(encoding="utf-8"),)
    monkeypatch.setattr(install, "packaged_memory_blocks", lambda: spanish_only)
    by_id = {c.id: r for c, r in checks.run_all(_ctx(home))}
    assert by_id["scaffold.memory"].status == checks.WARN


def test_without_english_in_the_packaged_catalogs_update_rewrites_the_english_agent(
    tmp_path, data_dir, monkeypatch
):
    """Control positivo de D12: si `packaged_catalog_blocks()` pierde el inglés, se reescribe."""
    home = _english_home(tmp_path)
    spanish_only = (install.catalog_block_for("es"),)
    monkeypatch.setattr(install, "packaged_catalog_blocks", lambda: spanish_only)
    refresh = install.plan_catalog_refresh(home, "es")
    assert refresh and "en.md" in refresh[0].detail
