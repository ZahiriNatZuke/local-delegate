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

from local_delegate import config, deprecation_notices, deprecations, i18n, legacy_names
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
# Un caso de cada clase y uno inválido por regla (REQ-002). Nombres de mentira, no del registro.
VALID_BY_CLASS = (
    DeprecatedName("env_var", "LD_OLD_TEST_ALIAS", "LD_TEST_ALIAS", "0.35.0"),
    DeprecatedName("retired", "LD_RETIRED_TEST_VAR", None, "0.30.0", "0.37.0"),
    DeprecatedName(
        "retired",
        "LD_OLD_TEST_GONE",
        "LD_TEST_GONE",
        "UNRELEASED",
        "0.40.0",
        retired_from="env_var",
    ),
)
INVALID_BY_RULE = {
    "retired_from": DeprecatedName(
        "retired", "LD_OLD_TEST_NO_FROM", "LD_TEST_NO_FROM", "0.38.0", "0.40.0"
    ),
    "alias_with_warn_until": DeprecatedName(
        "env_var", "LD_OLD_TEST_WU", "LD_TEST_WU", "0.35.0", "0.40.0"
    ),
    "retired_from_retired": DeprecatedName(
        "retired", "LD_OLD_TEST_RR", "LD_TEST_RR", "0.38.0", "0.40.0", retired_from="retired"
    ),
    "alias_with_retired_from": DeprecatedName(
        "env_var", "LD_OLD_TEST_AF", "LD_TEST_AF", "0.35.0", retired_from="env_var"
    ),
    "retired_without_warn_until": DeprecatedName(
        "retired", "LD_OLD_TEST_NO_WARN", "LD_TEST_NO_WARN", "0.38.0", retired_from="env_var"
    ),
    "retired_from_without_new": DeprecatedName(
        "retired", "LD_RETIRED_TEST_RF", None, "0.30.0", "0.37.0", retired_from="env_var"
    ),
}


def test_every_entry_follows_its_class_rule():
    """REQ-002: el registro real y uno de cada clase pasan; cada caso inválido se rechaza."""
    assert deprecations.class_problems() == []
    assert deprecations.class_problems(VALID_BY_CLASS) == []
    for rule, entry in INVALID_BY_RULE.items():
        problems = deprecations.class_problems((entry,))
        assert problems, f"{rule}: la regla no rechaza {entry}"
        assert all(p.startswith(f"{entry.old}: ") for p in problems), problems


def test_effective_kind_is_retired_from_only_for_a_retired_renamed():
    alias, retired, retired_renamed = VALID_BY_CLASS
    assert deprecations.effective_kind(alias) == "env_var"
    assert deprecations.effective_kind(retired) == "retired"
    assert deprecations.effective_kind(retired_renamed) == "env_var"


# --- Lectores por clase efectiva (REQ-003) -------------------------------------
_SURFACES = {
    "cli_command": ("old-test-command", "test-command"),
    "cli_option": ("--old-test-option", "--test-option"),
    "env_var": ("LD_OLD_TEST_SURFACE", "LD_TEST_SURFACE"),
    "switch_file": ("old-test-switch-file", "test-switch-file"),
}
_FUNCTION_BY_KIND = {
    "env_var": "env_vars",
    "switch_file": "switch_files",
    "cli_command": "cli_entries",
    "cli_option": "cli_entries",
}


def _synthetic_registry() -> tuple[DeprecatedName, ...]:
    entries: list[DeprecatedName] = []
    for kind, (old, new) in _SURFACES.items():
        entries.append(DeprecatedName(kind, old, new, "0.35.0"))
        entries.append(
            DeprecatedName(
                "retired", f"{old}-gone", f"{new}-gone", "0.38.0", "0.40.0", retired_from=kind
            )
        )
    # Retirado sin sucesor con forma de variable: no tiene superficie, no sale en ningún lector.
    entries.append(DeprecatedName("retired", "LD_RETIRED_TEST_VAR", None, "0.30.0", "0.37.0"))
    return tuple(entries)


def test_each_reader_lists_the_alias_and_the_retired_of_its_surface_only(monkeypatch):
    """REQ-003: un alias y un retirado con sucesor de cada clase salen en su lector y en ningún otro."""
    registry = _synthetic_registry()
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", registry)
    listed = {
        name: {e.old for e in getattr(deprecations, name)()}
        for name in set(_FUNCTION_BY_KIND.values())
    }
    for kind, (old, _new) in _SURFACES.items():
        for name in (old, f"{old}-gone"):
            found_in = sorted(function for function, names in listed.items() if name in names)
            assert found_in == [_FUNCTION_BY_KIND[kind]], (name, found_in)
    assert all("LD_RETIRED_TEST_VAR" not in names for names in listed.values())


def test_old_names_are_unique():
    old_names = [e.old for e in deprecations.DEPRECATED_NAMES]
    assert len(old_names) == len(set(old_names))


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


def test_unreleased_alias_never_expires():
    unreleased_entry = DeprecatedName("env_var", "LD_X", "LD_Y", deprecations.UNRELEASED)
    _assert_horizon("9.99.0", (unreleased_entry,))
    assert deprecations.removal_version(unreleased_entry) is None


def test_warning_names_old_new_and_removal_version():
    assert deprecation_notices.warning_text(ALIAS) == (
        "LD_OLD_TEST_ALIAS está obsoleto: usa LD_TEST_ALIAS (se retira en la 0.38.0)"
    )
    retired_text = deprecation_notices.warning_text(RETIRED)
    assert "LD_RETIRED_TEST_VAR" in retired_text and "0.30.0" in retired_text


RETIRED_RENAMED = DeprecatedName(
    "retired", "LD_OLD_TEST_GONE", "LD_TEST_GONE", "0.38.0", "0.40.0", retired_from="env_var"
)
RETIRED_RENAMED_UNRELEASED = DeprecatedName(
    "retired",
    "LD_OLD_TEST_GONE",
    "LD_TEST_GONE",
    deprecations.UNRELEASED,
    "0.40.0",
    retired_from="env_var",
)


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("es", "LD_OLD_TEST_GONE ya no tiene efecto desde la 0.38.0: usa LD_TEST_GONE"),
        ("en", "LD_OLD_TEST_GONE has had no effect since 0.38.0: use LD_TEST_GONE"),
    ],
)
def test_warning_text_retired_renamed_names_old_new_and_version(language, expected):
    with i18n.override(language):
        assert deprecation_notices.warning_text(RETIRED_RENAMED) == expected


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("es", "LD_OLD_TEST_GONE ya no tiene efecto: usa LD_TEST_GONE"),
        ("en", "LD_OLD_TEST_GONE has no effect: use LD_TEST_GONE"),
    ],
)
def test_warning_text_retired_renamed_unreleased_never_says_unreleased(language, expected):
    with i18n.override(language):
        text = deprecation_notices.warning_text(RETIRED_RENAMED_UNRELEASED)
    assert text == expected
    assert deprecations.UNRELEASED not in text


@pytest.mark.parametrize("language", ["es", "en"])
def test_warning_text_alias_and_retired_without_new_keep_their_text(language):
    """Las otras dos clases no cambian: el alias da su retirada; el retirado, su versión."""
    unreleased_alias = DeprecatedName("env_var", "LD_X", "LD_Y", deprecations.UNRELEASED)
    with i18n.override(language):
        alias_text = deprecation_notices.warning_text(ALIAS)
        retired_text = deprecation_notices.warning_text(RETIRED)
        unreleased_text = deprecation_notices.warning_text(unreleased_alias)
    assert "LD_OLD_TEST_ALIAS" in alias_text and "LD_TEST_ALIAS" in alias_text
    assert "0.38.0" in alias_text
    assert "LD_RETIRED_TEST_VAR" in retired_text and "0.30.0" in retired_text
    for text in (alias_text, retired_text, unreleased_text):
        assert deprecations.UNRELEASED not in text


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


def test_deprecations_imports_nothing_from_the_package():
    """`config` importa `deprecations` e `i18n` importa `config`: si `deprecations` importara `i18n`
    (aunque fuera dentro de una función) habría un ciclo, y CodeQL lo marca (`py/cyclic-import`,
    PR #311). Por eso la redacción del aviso vive en `deprecation_notices`."""
    import ast

    tree = ast.parse(Path(deprecations.__file__).read_text(encoding="utf-8"))
    relative = [
        node.module or "."
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.level or "local_delegate" in (node.module or ""))
    ]
    assert relative == []
