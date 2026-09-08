"""El camino de salida que REESCRIBE la entrada de una tool.

`emit()` es consultivo y `emit_updated_input()` no: sustituye lo que se va a ejecutar, y el
permiso del usuario ya se evaluó sobre el comando original. Un fallo aquí no es un consejo malo,
es un comando distinto del que se autorizó, así que la forma exacta de la salida y la huella en
la telemetría se prueban una a una.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = _load("hook_common")


def _salida(capsys) -> dict:
    out = capsys.readouterr().out.strip()
    assert out, "no se imprimió nada"
    return json.loads(out)


def test_reescribe_con_la_forma_que_espera_el_cliente(capsys):
    common.emit_updated_input("PreToolUse", {"command": "( make ) > /tmp/x 2>&1"})

    bloque = _salida(capsys)["hookSpecificOutput"]
    assert bloque["hookEventName"] == "PreToolUse"
    assert bloque["updatedInput"] == {"command": "( make ) > /tmp/x 2>&1"}
    # Sin contexto no se inventa la clave: un `additionalContext` vacío es ruido en el prompt.
    assert "additionalContext" not in bloque


def test_el_contexto_viaja_junto_a_la_reescritura(capsys):
    common.emit_updated_input(
        "PreToolUse",
        {"command": "( make ) > /tmp/x 2>&1"},
        context="La salida entera está en /tmp/x",
    )

    bloque = _salida(capsys)["hookSpecificOutput"]
    assert bloque["updatedInput"]["command"].startswith("( make )")
    assert bloque["additionalContext"] == "La salida entera está en /tmp/x"


def test_una_reescritura_siempre_deja_huella(tmp_path, monkeypatch, capsys):
    """Auditable a posteriori: si cambió lo que se ejecutó, tiene que constar."""
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))

    common.emit_updated_input("PreToolUse", {"command": "( make ) > f 2>&1"}, category="bash")

    capsys.readouterr()
    evento = json.loads(log.read_text(encoding="utf-8").strip())
    assert evento["rewritten"] is True
    assert evento["category"] == "bash"
    # La misma política de siempre: ni comandos, ni rutas, ni argumentos en el log.
    assert "command" not in evento
    assert "make" not in log.read_text(encoding="utf-8")


def test_la_rama_baseline_del_ab_no_reescribe_ni_registra(tmp_path, monkeypatch, capsys):
    """`LD_HOOK_ENABLED=0` deja la sesión limpia del todo, también para el camino que reescribe.

    Si la baseline reescribiera comandos no sería una baseline, y si registrara contaminaría el
    log de la rama piloto — que es justo para lo que existe la variable.
    """
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_ENABLED", "0")
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))

    common.emit_updated_input("PreToolUse", {"command": "( make ) > f 2>&1"})

    assert capsys.readouterr().out == ""
    assert not log.exists()


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
