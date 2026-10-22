"""Fuente del token del puerto para el puente de Claude Desktop (SDD claude-plugin-and-mods, REQ-012).

Desktop no pasa su entorno a los MCP ni expande `${VAR}`: el puente lee él mismo la variable de
usuario del registro de Windows. Aquí el registro es simulado: la suite no lee el real.
"""

from __future__ import annotations

import types

import pytest

from local_delegate import config, token_source

REG_SZ = 1
REG_EXPAND_SZ = 2


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_winreg(values: dict[str, tuple[str, int]], opened: list):
    """Un `winreg` mínimo: solo `HKCU\\Environment`, con los valores dados."""

    def open_key(root, path):
        opened.append((root, path))
        if (root, path) != ("HKCU", "Environment"):
            raise OSError("no such key")
        return _FakeKey()

    def query_value_ex(_key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name]

    return types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        REG_SZ=REG_SZ,
        REG_EXPAND_SZ=REG_EXPAND_SZ,
        OpenKey=open_key,
        QueryValueEx=query_value_ex,
        ExpandEnvironmentStrings=lambda value: value.replace("%PART%", "expanded"),
    )


@pytest.fixture
def registry(monkeypatch):
    """Simula Windows con un registro propio; devuelve el dict de valores y las claves abiertas."""
    values: dict[str, tuple[str, int]] = {}
    opened: list = []
    monkeypatch.setattr(token_source.sys, "platform", "win32")
    monkeypatch.setattr(token_source, "_winreg", lambda: _fake_winreg(values, opened))
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    return values, opened


def test_reads_registry_user_env_on_windows(registry):
    values, opened = registry
    values[token_source.TOKEN_VARIABLE] = ("tok-from-registry", REG_SZ)

    assert token_source.web_token() == "tok-from-registry"
    assert ("HKCU", "Environment") in opened


def test_registry_wins_over_a_stale_process_environment(registry, monkeypatch):
    values, _ = registry
    values[token_source.TOKEN_VARIABLE] = ("fresh", REG_SZ)
    monkeypatch.setattr(config, "WEB_TOKEN", "stale")

    assert token_source.web_token() == "fresh"


def test_registry_values_with_variables_are_expanded(registry):
    values, _ = registry
    values[token_source.TOKEN_VARIABLE] = ("pre-%PART%", REG_EXPAND_SZ)

    assert token_source.web_token() == "pre-expanded"


@pytest.mark.parametrize("stored", [None, "", "   "])
def test_missing_or_blank_registry_value_falls_back_to_the_process(registry, monkeypatch, stored):
    values, _ = registry
    if stored is not None:
        values[token_source.TOKEN_VARIABLE] = (stored, REG_SZ)
    monkeypatch.setattr(config, "WEB_TOKEN", "from-process")

    assert token_source.web_token() == "from-process"


def test_no_token_at_all_is_empty(registry):
    assert token_source.web_token() == ""


def test_outside_windows_the_registry_is_not_read(monkeypatch):
    def boom():
        raise AssertionError("winreg must not be loaded outside Windows")

    monkeypatch.setattr(token_source.sys, "platform", "darwin")
    monkeypatch.setattr(token_source, "_winreg", boom)
    monkeypatch.setattr(config, "WEB_TOKEN", "")

    assert token_source.read_user_environment(token_source.TOKEN_VARIABLE) is None
    assert token_source.web_token() == ""
