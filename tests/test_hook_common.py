"""El interruptor del A/B de los hooks.

Este fichero probaba sobre todo `emit_updated_input()`, el camino que reescribía la entrada de una
tool. Ese camino se retiró junto con `output_policy`/`output_stats`: la reescritura de comandos se
descartó por diseño —el permiso del usuario se evalúa sobre el comando original, así que un fallo
ahí no es un consejo malo sino un comando distinto del que se autorizó— y quedaba sin ningún
consumidor. Lo que sigue vivo es `enabled()`, y su lección.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

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


def _salida(capsys) -> dict:
    return json.loads(capsys.readouterr().out)["hookSpecificOutput"]


def test_deny_bloquea_la_tool_y_dice_por_donde_se_pasa(capsys, monkeypatch, tmp_path):
    """El camino nuevo de F1. El contrato sale de `PreToolUseHookSpecificOutput` del SDK."""
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(tmp_path / "t.jsonl"))
    common.deny("PreToolUse", "usa local_summarize(path=...)", category="read")

    salida = _salida(capsys)
    assert salida["permissionDecision"] == "deny"
    assert salida["permissionDecisionReason"] == "usa local_summarize(path=...)"
    assert salida["hookEventName"] == "PreToolUse"
    # La reescritura de la entrada NO se usa: el permiso se evalúa sobre la llamada original.
    assert "updatedInput" not in salida


def test_emit_sigue_sin_bloquear_nada(capsys, monkeypatch, tmp_path):
    """Control positivo de lo anterior: el camino consultivo no decide permisos."""
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(tmp_path / "t.jsonl"))
    common.emit("PreToolUse", "este archivo pesa mucho", category="read")

    salida = _salida(capsys)
    assert "permissionDecision" not in salida
    assert salida["additionalContext"] == "este archivo pesa mucho"


def test_el_bloqueo_queda_registrado_y_se_distingue_del_aviso(capsys, monkeypatch, tmp_path):
    """«Ofrecido, aceptado, rechazado» empieza por poder distinguir ofrecido de bloqueado."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))

    common.emit("PreToolUse", "aviso", category="read")
    common.deny("PreToolUse", "bloqueo", category="read")
    capsys.readouterr()

    eventos = [json.loads(linea) for linea in log.read_text(encoding="utf-8").splitlines()]
    assert [e.get("blocked", False) for e in eventos] == [False, True]
    assert all(e["suggested"] is True for e in eventos)


def test_el_interruptor_apagado_no_bloquea_ni_registra(capsys, monkeypatch, tmp_path):
    """Un experimento en rama baseline no puede bloquear: apagado es apagado."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setenv("LD_HOOK_ENABLED", "0")

    common.deny("PreToolUse", "bloqueo", category="read")

    assert capsys.readouterr().out == ""
    assert not log.exists()


def test_la_huella_del_script_cambia_cuando_el_script_cambia(tmp_path):
    """Es la «versión» del hook, y por eso no hay constante que alguien deba acordarse de subir."""
    script = tmp_path / "hook.py"
    script.write_text("print(1)\n", encoding="utf-8")
    antes = common.version_de(str(script))

    script.write_text("print(2)\n", encoding="utf-8")
    despues = common.version_de(str(script))

    assert antes and despues and len(antes) == 8
    assert antes != despues, "dos scripts distintos no pueden tener la misma huella"
    assert common.version_de(str(tmp_path / "no-existe.py")) == ""


def test_el_contexto_dice_que_script_corrio_y_en_que_sesion():
    contexto = common.contexto_de({"session_id": "abc-123"}, str(HOOKS / "hook_common.py"))
    assert contexto["session_id"] == "abc-123"
    assert len(contexto["version"]) == 8
    # Un payload sin sesión no rompe nada, pero se nota en el dato.
    assert common.contexto_de({}, "x")["session_id"] == ""


def test_cada_identificador_es_distinto():
    ids = {common.nuevo_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(i) == 12 for i in ids)


# --- Salud del backend ----------------------------------------------------------------------


def _marca(tmp_path, ok: bool, antiguedad_s: float = 0.0):
    archivo = tmp_path / "salud.json"
    archivo.write_text(json.dumps({"ts": time.time() - antiguedad_s, "ok": ok}), encoding="utf-8")
    return archivo


def test_una_marca_fresca_se_cree_y_no_se_sondea(monkeypatch, tmp_path):
    sondeos = []
    monkeypatch.setattr(common, "_sondear", lambda t: sondeos.append(t) or True)

    assert common.backend_disponible(marca=_marca(tmp_path, ok=True)) is True
    assert common.backend_disponible(marca=_marca(tmp_path, ok=False)) is False
    assert sondeos == [], "una marca fresca no debería costar un sondeo"


@pytest.mark.parametrize(
    "preparar",
    [
        lambda tmp: _marca(tmp, ok=True, antiguedad_s=3600),
        lambda tmp: tmp / "no-existe.json",
        lambda tmp: (tmp / "rota.json", (tmp / "rota.json").write_text("{", encoding="utf-8"))[0],
        lambda tmp: (
            tmp / "sin-ts.json",
            (tmp / "sin-ts.json").write_text('{"ok": true}', encoding="utf-8"),
        )[0],
    ],
    ids=["vieja", "ausente", "corrupta", "sin ts"],
)
def test_una_marca_que_no_sirve_se_vuelve_a_preguntar(monkeypatch, tmp_path, preparar):
    """Ninguna de estas se interpreta: se sondea otra vez. Interpretarlas es inventar."""
    sondeos = []
    monkeypatch.setattr(common, "_sondear", lambda t: sondeos.append(t) or True)

    assert common.backend_disponible(marca=preparar(tmp_path)) is True
    assert len(sondeos) == 1


def test_el_sondeo_se_guarda_para_no_repetirlo(monkeypatch, tmp_path):
    sondeos = []
    monkeypatch.setattr(common, "_sondear", lambda t: sondeos.append(t) or True)
    archivo = tmp_path / "salud.json"

    common.backend_disponible(marca=archivo)
    common.backend_disponible(marca=archivo)

    assert len(sondeos) == 1, "el segundo debería haber salido de la marca recién escrita"
    assert json.loads(archivo.read_text(encoding="utf-8"))["ok"] is True


def test_si_no_se_puede_escribir_la_marca_igual_se_responde(monkeypatch, tmp_path):
    """Sin caché se sondea más a menudo: es lento, no incorrecto."""
    monkeypatch.setattr(common, "_sondear", lambda t: True)
    inalcanzable = tmp_path / "no" / "existe" / "salud.json"

    assert common.backend_disponible(marca=inalcanzable) is True


def test_un_backend_que_no_esta_da_false_sin_lanzar(monkeypatch, tmp_path):
    """Control positivo del sondeo de verdad: contra un puerto donde no hay nadie."""
    monkeypatch.setenv("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9/v1")
    assert common.backend_disponible(marca=tmp_path / "salud.json", timeout_s=0.2) is False


def test_una_url_invalida_tampoco_lanza(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DELEGATE_BASE_URL", "no-es-una-url")
    assert common.backend_disponible(marca=tmp_path / "salud.json", timeout_s=0.2) is False
