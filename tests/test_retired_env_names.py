"""Variables del paquete con nombre viejo: sin efecto y con aviso (SDD retire-legacy-aliases, L4).

REQ-009: `config` lee solo los nombres nuevos; el viejo sigue en `DEPRECATED_ENV_VALUES` (por la
puerta `_read`, así que la suite lo aísla) solo para avisar.
REQ-011, filas 4 y 5: control positivo en un proceso nuevo, viejo y gemelo nuevo con el mismo valor.
REQ-013: `local_status` lista los nombres viejos con sucesor puestos en el entorno de su proceso,
sin imprimir el valor.

Los nombres viejos salen del registro (`deprecations.DEPRECATED_NAMES`), no de literales.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from local_delegate import config, deprecation_notices, deprecations, i18n, server
from local_delegate.deprecations import DeprecatedName

NEW_NAMES = (
    "LD_HOOK_READ_BLOCK",
    "LD_HOOK_READ_SWITCH_FILE",
    "LOCAL_DELEGATE_STRUCTURED_SUMMARY",
    "LOCAL_DELEGATE_COST_FALLBACK",
)


def _old(new: str) -> str:
    return next(e.old for e in deprecations.DEPRECATED_NAMES if e.new == new)


OLD = {new: _old(new) for new in NEW_NAMES}

_PRINT_CONFIG = (
    "from local_delegate import config; "
    "print(config.HOOK_READ_BLOCK, config.HOOK_READ_SWITCH_FILE, config.STRUCTURED_SUMMARY, "
    "config.COST_FALLBACK, sep='|')"
)


def _config_in_subprocess(variables: dict[str, str]) -> list[str]:
    """`config` cargado en un proceso nuevo con solo `variables` de entre los ocho nombres."""
    names = set(NEW_NAMES) | set(OLD.values())
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


_VALUES = {
    "LD_HOOK_READ_BLOCK": "1",
    "LD_HOOK_READ_SWITCH_FILE": "some.flag",
    "LOCAL_DELEGATE_STRUCTURED_SUMMARY": "1",
    "LOCAL_DELEGATE_COST_FALLBACK": "claude-haiku-4-5",
}


# --- REQ-011 filas 4 y 5 (y las dos variables del bloqueo en el paquete) ---------------------


def test_old_names_alone_have_no_effect_in_a_new_process():
    values = _config_in_subprocess({OLD[new]: value for new, value in _VALUES.items()})
    assert values == ["False", "", "False", ""]


def test_new_names_take_effect_in_a_new_process():
    """Gemelo de la prueba anterior: los mismos valores con el nombre nuevo sí cuentan."""
    values = _config_in_subprocess(dict(_VALUES))
    assert values == ["True", "some.flag", "True", "claude-haiku-4-5"]


def test_old_name_does_not_override_the_new_one():
    values = _config_in_subprocess(
        {
            "LD_HOOK_READ_BLOCK": "0",
            "LOCAL_DELEGATE_STRUCTURED_SUMMARY": "0",
            **{OLD[new]: value for new, value in _VALUES.items()},
        }
    )
    assert values == ["False", "", "False", ""]


def test_old_names_stay_readable_only_to_warn(reload_config):
    """`DEPRECATED_ENV_VALUES` sigue viendo el viejo (para el aviso) y el inventario lo aísla."""
    old = OLD["LOCAL_DELEGATE_COST_FALLBACK"]
    reload_config(**{old: "claude-haiku-4-5"})
    assert config.DEPRECATED_ENV_VALUES[old] == "claude-haiku-4-5"
    assert config.COST_FALLBACK == ""
    for new, old in OLD.items():
        assert new in config.ENVIRONMENT_VARIABLES, new
        assert old in config.ENVIRONMENT_VARIABLES, old


# --- REQ-013: `local_status` -----------------------------------------------------------------


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


def test_local_status_lists_a_retired_variable(reload_config, offline_status):
    old = OLD["LOCAL_DELEGATE_COST_FALLBACK"]
    entry = deprecations.find(old)
    reload_config(**{old: "secret-value"})
    text = server.local_status()
    assert i18n.t("mcp.status.deprecated") in text
    assert deprecation_notices.warning_text(entry) in text
    assert old in text and "LOCAL_DELEGATE_COST_FALLBACK" in text
    assert "secret-value" not in text


@pytest.mark.parametrize(
    ("language", "header"),
    [
        ("es", "Nombres retirados puestos en el entorno de este proceso (sin efecto):"),
        ("en", "Retired names set in this process's environment (no effect):"),
    ],
)
def test_local_status_header_says_the_names_have_no_effect(language, header):
    assert i18n.t_lang(language, "mcp.status.deprecated") == header


def test_local_status_says_nothing_with_the_new_names(reload_config, offline_status):
    """Gemelo: con el nombre nuevo no hay sección (y el valor sí se aplica)."""
    reload_config(LOCAL_DELEGATE_COST_FALLBACK="claude-haiku-4-5")
    assert config.COST_FALLBACK == "claude-haiku-4-5"
    assert i18n.t("mcp.status.deprecated") not in server.local_status()


def test_describe_lists_only_retired_names_with_a_new_name(monkeypatch):
    """Registro sintético: un retirado con sucesor sale; uno sin sucesor y uno sin valor, no."""
    with_new = DeprecatedName(
        "retired", "LD_OLD_TEST_VAR", "LD_NEW_TEST_VAR", "0.38.0", "0.40.0", retired_from="env_var"
    )
    without_new = DeprecatedName("retired", "LD_GONE_TEST_VAR", None, "0.38.0", "0.40.0")
    unset = DeprecatedName(
        "retired",
        "LD_UNSET_TEST_VAR",
        "LD_SET_TEST_VAR",
        "0.38.0",
        "0.40.0",
        retired_from="env_var",
    )
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", (with_new, without_new, unset))
    monkeypatch.setattr(
        config,
        "DEPRECATED_ENV_VALUES",
        {"LD_OLD_TEST_VAR": "secret-value", "LD_GONE_TEST_VAR": "1", "LD_UNSET_TEST_VAR": None},
    )
    lines = server._describe_deprecated_names()
    assert lines == [
        "",
        i18n.t("mcp.status.deprecated"),
        f"  {deprecation_notices.warning_text(with_new)}",
    ]
    assert "secret-value" not in "\n".join(lines)
