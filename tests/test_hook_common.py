"""El interruptor del A/B de los hooks.

Este fichero probaba sobre todo `emit_updated_input()`, el camino que reescribía la entrada de una
tool. Ese camino se retiró junto con `output_policy`/`output_stats`: la reescritura de comandos se
descartó por diseño —el permiso del usuario se evalúa sobre el comando original, así que un fallo
ahí no es un consejo malo sino un comando distinto del que se autorizó— y quedaba sin ningún
consumidor. Lo que sigue vivo es `enabled()`, y su lección.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = _load("hook_common")


def test_el_interruptor_del_ab_no_puede_encender_nada(monkeypatch):
    """Solo apaga. Encender es cosa del registro, y esta es la mitad que se olvidó una vez.

    Cuando la única puerta era la variable, `install --enable-read-hook` registró el script sin
    ponerla: quedó instalado e inerte, en silencio. El control es que el valor por defecto —o sea
    «nadie ha dicho nada»— ya vale `True`, así que no hay nada que la variable pueda encender.
    """
    monkeypatch.delenv("LD_HOOK_ENABLED", raising=False)
    assert common.enabled() is True

    for valor in ("0", "false", "no", "off", "OFF", " 0 "):
        monkeypatch.setenv("LD_HOOK_ENABLED", valor)
        assert common.enabled() is False, valor

    for valor in ("1", "true", "cualquier cosa"):
        monkeypatch.setenv("LD_HOOK_ENABLED", valor)
        assert common.enabled() is True, valor
