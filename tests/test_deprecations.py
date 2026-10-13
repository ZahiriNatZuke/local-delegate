"""El registro único de nombres obsoletos (`deprecations.py`, D1) y sus guardianes (REQ-004).

Tres guardianes que no dependen de que alguien se acuerde:

- **horizonte**: un alias vive en la versión que lo publica y en las dos menores siguientes, y
  desaparece en la tercera; un nombre retirado se avisa hasta su `warn_until`. Cuando la versión
  del paquete llega ahí, la suite falla y nombra lo que hay que quitar;
- **CHANGELOG**: la versión que registra cada entrada es la de la sección del CHANGELOG que la
  anuncia, y esa sección nombra el nombre viejo y el nuevo;
- **paridad con los hooks**: los hooks no importan el paquete y llevan su propia tabla; tiene que
  ser igual al subconjunto `used_by_hooks` del registro.

Además: `config._env_alias`, el esqueleto de `legacy_names` (D2) y el stamped de `UNRELEASED` que
hace `scripts/bump_version.py` al publicar.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from pathlib import Path

import pytest

from local_delegate import config, deprecations, legacy_names
from local_delegate.deprecations import DeprecatedName
from local_delegate.resources.hooks import hook_common

ROOT = Path(__file__).parents[1]


def _package_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _assert_horizon(version: str, entries=deprecations.DEPRECATED_NAMES) -> None:
    overdue = deprecations.overdue(version, entries)
    assert not overdue, overdue


# --- Forma del registro -------------------------------------------------------
def test_each_entry_follows_the_rule_of_its_class():
    for e in deprecations.DEPRECATED_NAMES:
        assert e.kind in deprecations.KINDS, e
        if e.is_retired:
            assert e.new is None and e.warn_until, f"{e.old}: un retirado lleva warn_until y no new"
        else:
            assert e.new and e.warn_until is None, f"{e.old}: un alias lleva new y no warn_until"
        assert e.introduced == deprecations.UNRELEASED or re.fullmatch(
            r"\d+\.\d+\.\d+", e.introduced
        ), e


def test_old_names_are_unique():
    old_names = [e.old for e in deprecations.DEPRECATED_NAMES]
    assert len(old_names) == len(set(old_names))


def test_registry_holds_the_three_fast_role_variables_as_retired():
    fast = {e.old: e for e in deprecations.DEPRECATED_NAMES if e.old.endswith("_FAST")}
    assert set(fast) == {
        "LOCAL_DELEGATE_MODEL_FAST",
        "LOCAL_DELEGATE_MAX_CHARS_FAST",
        "LOCAL_DELEGATE_FALLBACK_FAST",
    }
    for e in fast.values():
        assert (e.kind, e.new, e.introduced, e.warn_until) == ("retired", None, "0.30.0", "0.37.0")


# --- Horizonte (REQ-004) ------------------------------------------------------
def test_horizon_no_deprecated_name_is_overdue_in_the_current_version():
    """EL guardián: cuando la versión del paquete alcanza la retirada, esto falla con el nombre."""
    _assert_horizon(_package_version())


ALIAS = DeprecatedName("env_var", "LD_OLD_TEST_ALIAS", "LD_TEST_ALIAS", "0.35.0")
RETIRED = DeprecatedName("retired", "LD_RETIRED_TEST_VAR", None, "0.30.0", "0.37.0")


@pytest.mark.parametrize("version", ["0.35.0", "0.36.4", "0.37.0", "0.37.9"])
def test_alias_lives_three_minors_and_retired_until_warn_until(version):
    _assert_horizon(version, (ALIAS, RETIRED))


def test_alias_expires_at_introduced_plus_three_and_failure_names_it():
    """Control positivo del guardián: subir la versión a 0.38.0 lo pone en rojo."""
    with pytest.raises(AssertionError, match="LD_OLD_TEST_ALIAS"):
        _assert_horizon("0.38.0", (ALIAS,))
    assert deprecations.removal_version(ALIAS) == "0.38.0"


def test_retired_expires_after_warn_until_and_failure_names_it():
    with pytest.raises(AssertionError, match="LD_RETIRED_TEST_VAR"):
        _assert_horizon("0.38.0", (RETIRED,))


def test_real_fast_variables_expire_in_0_38_0():
    with pytest.raises(AssertionError, match="LOCAL_DELEGATE_MODEL_FAST"):
        _assert_horizon("0.38.0")


def test_unreleased_alias_never_expires():
    unreleased_entry = DeprecatedName("env_var", "LD_X", "LD_Y", deprecations.UNRELEASED)
    _assert_horizon("9.99.0", (unreleased_entry,))
    assert deprecations.removal_version(unreleased_entry) is None


def test_warning_names_old_new_and_removal_version():
    assert deprecations.warning_text(ALIAS) == (
        "LD_OLD_TEST_ALIAS está obsoleto: usa LD_TEST_ALIAS (se retira en la 0.38.0)"
    )
    retired_text = deprecations.warning_text(RETIRED)
    assert "LD_RETIRED_TEST_VAR" in retired_text and "0.30.0" in retired_text


# --- CHANGELOG (REQ-004) ------------------------------------------------------
def _changelog_sections(text: str) -> dict[str, str]:
    """`{versión: cuerpo}` por cada `## [versión]`; `Unreleased` incluida."""
    parts = re.split(r"(?m)^## \[([^\]]+)\][^\n]*\n", text)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def changelog_problems(text: str, entries) -> list[str]:
    sections = _changelog_sections(text)
    problems = []
    for e in entries:
        version = "Unreleased" if e.introduced == deprecations.UNRELEASED else e.introduced
        body = sections.get(version)
        if body is None:
            problems.append(f"{e.old}: no hay sección ## [{version}] en el CHANGELOG")
            continue
        for name in (e.old, e.new):
            if name and name not in body:
                problems.append(f"{e.old}: la sección [{version}] no nombra {name}")
    return problems


def test_each_entry_matches_the_changelog_section_that_announces_it():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog_problems(text, deprecations.DEPRECATED_NAMES) == []


TEST_CHANGELOG = """# Changelog

## [Unreleased]

- `LD_X` pasa a llamarse `LD_Y`.

## [0.30.0] - 2026-09-15

- Se retira `LD_RETIRED_TEST_VAR`.
"""


def test_changelog_check_detects_the_missing_line():
    unreleased_entry = DeprecatedName("env_var", "LD_X", "LD_Y", deprecations.UNRELEASED)
    assert changelog_problems(TEST_CHANGELOG, (unreleased_entry, RETIRED)) == []
    # Mutante del fixture: se borra la línea que anuncia el retirado.
    mutated = TEST_CHANGELOG.replace("- Se retira `LD_RETIRED_TEST_VAR`.\n", "")
    problems = changelog_problems(mutated, (RETIRED,))
    assert problems == ["LD_RETIRED_TEST_VAR: la sección [0.30.0] no nombra LD_RETIRED_TEST_VAR"]
    # Y una versión registrada que no tiene sección.
    assert "no hay sección" in changelog_problems(mutated, (ALIAS,))[0]


# --- Paridad con los hooks (D1) -----------------------------------------------
def test_hook_table_is_the_registry_subset():
    """`hook_common` declarará `DEPRECATED_HOOK_NAMES` con `(kind, old, new)` (ola A2).

    Hasta entonces las dos partes están vacías y el test ya vigila que sigan siendo iguales.
    """
    from_hooks = tuple(getattr(hook_common, "DEPRECATED_HOOK_NAMES", ()))
    assert from_hooks == deprecations.hook_names()


# --- config._env_alias --------------------------------------------------------
@pytest.fixture
def isolated_alias(monkeypatch):
    """Lecturas de prueba fuera del inventario real de variables y del registro de vistas."""
    monkeypatch.setattr(config, "_READ_VARIABLES", set())
    monkeypatch.setattr(config, "DEPRECATED_SEEN", set())
    monkeypatch.delenv("LD_NEW_TEST_VAR", raising=False)
    monkeypatch.delenv("LD_OLD_TEST_VAR", raising=False)
    return monkeypatch


def test_env_alias_new_wins_when_both_are_set(isolated_alias):
    isolated_alias.setenv("LD_NEW_TEST_VAR", "nueva")
    isolated_alias.setenv("LD_OLD_TEST_VAR", "vieja")
    assert config._env_alias("LD_NEW_TEST_VAR", "LD_OLD_TEST_VAR") == "nueva"
    assert config.DEPRECATED_SEEN == set()


def test_env_alias_old_alone_takes_effect_and_is_recorded(isolated_alias):
    isolated_alias.setenv("LD_OLD_TEST_VAR", "vieja")
    assert config._env_alias("LD_NEW_TEST_VAR", "LD_OLD_TEST_VAR") == "vieja"
    assert config.DEPRECATED_SEEN == {"LD_OLD_TEST_VAR"}


def test_env_alias_reads_both_through_the_registered_gate(isolated_alias):
    assert config._env_alias("LD_NEW_TEST_VAR", "LD_OLD_TEST_VAR") is None
    assert {"LD_NEW_TEST_VAR", "LD_OLD_TEST_VAR"} <= config._READ_VARIABLES


# --- legacy_names (D2): API fijada, tablas vacías ------------------------------
def test_read_key_prefers_new_key_and_falls_back_to_old():
    assert legacy_names.read_key({"block_id": 1, "bloqueo_id": 2}, "block_id", "bloqueo_id") == 1
    assert legacy_names.read_key({"bloqueo_id": 2}, "block_id", "bloqueo_id") == 2
    assert legacy_names.read_key({}, "block_id", "bloqueo_id", "x") == "x"


def test_normalize_translates_keys_and_values_of_the_format(monkeypatch):
    monkeypatch.setitem(
        legacy_names.FORMATS,
        "prueba",
        {"keys": {"motivo": "reason"}, "values": {"reason": {"pequeno": "small"}}},
    )
    assert legacy_names.normalize("prueba", {"motivo": "pequeno", "n": 1}) == {
        "reason": "small",
        "n": 1,
    }
    # Con las dos claves, manda la nueva.
    assert legacy_names.normalize("prueba", {"motivo": "pequeno", "reason": "x"}) == {"reason": "x"}
    # Un formato sin tabla deja la fila igual.
    assert legacy_names.normalize("no-table", {"a": 1}) == {"a": 1}


# --- scripts/bump_version.py sella UNRELEASED ---------------------------------
def _bump_module():
    path = ROOT / "scripts" / "bump_version.py"
    if not path.is_file():
        pytest.skip("scripts/ no está en el árbol (sdist)")
    spec = importlib.util.spec_from_file_location("bump_version_a0", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bump_version_a0"] = module
    spec.loader.exec_module(module)
    return module


TEST_DEPRECATIONS = """UNRELEASED = "UNRELEASED"

DEPRECATED_NAMES: tuple[DeprecatedName, ...] = (
    DeprecatedName("env_var", "LD_A", "LD_B", "UNRELEASED"),
    DeprecatedName("retired", "LD_C", None, "0.30.0", "0.37.0"),
)


def f(e):
    return e.introduced == "UNRELEASED"
"""


def test_bump_stamps_only_registry_entries():
    bump = _bump_module()
    stamped = bump.stamp_unreleased(TEST_DEPRECATIONS, "0.35.0")
    assert 'DeprecatedName("env_var", "LD_A", "LD_B", "0.35.0")' in stamped
    assert stamped.startswith('UNRELEASED = "UNRELEASED"\n')
    assert 'return e.introduced == "UNRELEASED"' in stamped


def test_bump_plans_deprecations_only_when_there_is_something_to_stamp(tmp_path):
    bump = _bump_module()
    for name in ("pyproject.toml", "server.json"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    target = tmp_path / "src" / "local_delegate" / "deprecations.py"
    target.parent.mkdir(parents=True)
    target.write_text(TEST_DEPRECATIONS, encoding="utf-8")
    changes = bump.plan("0.35.0", tmp_path)
    assert target in changes
    assert '"LD_B", "0.35.0")' in changes[target][0]

    target.write_text(TEST_DEPRECATIONS.replace('"LD_B", "UNRELEASED"', '"LD_B", "0.34.0"'))
    assert target not in bump.plan("0.35.0", tmp_path)
