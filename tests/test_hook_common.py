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
import urllib.error
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


def test_the_ab_switch_cannot_turn_anything_on(monkeypatch):
    """Solo apaga. Encender es cosa del registro, y esta es la mitad que se olvidó una vez.

    Cuando la única puerta era la variable, `install --enable-read-hook` registró el script sin
    ponerla: quedó instalado e inerte, en silencio. El control es que el valor por defecto —o sea
    «nadie ha dicho nada»— ya vale `True`, así que no hay nada que la variable pueda encender.
    """
    monkeypatch.delenv("LD_HOOK_ENABLED", raising=False)
    assert common.enabled() is True

    for value in ("0", "false", "no", "off", "OFF", " 0 "):
        monkeypatch.setenv("LD_HOOK_ENABLED", value)
        assert common.enabled() is False, value

    for value in ("1", "true", "cualquier cosa"):
        monkeypatch.setenv("LD_HOOK_ENABLED", value)
        assert common.enabled() is True, value


def _output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)["hookSpecificOutput"]


def test_deny_blocks_the_tool_and_says_which_way_to_go(capsys, monkeypatch, tmp_path):
    """El camino nuevo de F1. El contrato sale de `PreToolUseHookSpecificOutput` del SDK."""
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(tmp_path / "t.jsonl"))
    common.deny("PreToolUse", "usa local_summarize(path=...)", category="read")

    output = _output(capsys)
    assert output["permissionDecision"] == "deny"
    assert output["permissionDecisionReason"] == "usa local_summarize(path=...)"
    assert output["hookEventName"] == "PreToolUse"
    # La reescritura de la entrada NO se usa: el permiso se evalúa sobre la llamada original.
    assert "updatedInput" not in output


def test_emit_still_blocks_nothing(capsys, monkeypatch, tmp_path):
    """Control positivo de lo anterior: el camino consultivo no decide permisos."""
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(tmp_path / "t.jsonl"))
    common.emit("PreToolUse", "este archivo pesa mucho", category="read")

    output = _output(capsys)
    assert "permissionDecision" not in output
    assert output["additionalContext"] == "este archivo pesa mucho"


def test_the_block_is_recorded_and_told_apart_from_the_warning(capsys, monkeypatch, tmp_path):
    """«Ofrecido, aceptado, rechazado» empieza por poder distinguir ofrecido de bloqueado."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))

    common.emit("PreToolUse", "aviso", category="read")
    common.deny("PreToolUse", "bloqueo", category="read")
    capsys.readouterr()

    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [e.get("blocked", False) for e in events] == [False, True]
    assert all(e["suggested"] is True for e in events)


def test_the_switch_off_neither_blocks_nor_records(capsys, monkeypatch, tmp_path):
    """Un experimento en rama baseline no puede bloquear: apagado es apagado."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setenv("LD_HOOK_ENABLED", "0")

    common.deny("PreToolUse", "bloqueo", category="read")

    assert capsys.readouterr().out == ""
    assert not log.exists()


def test_the_script_fingerprint_changes_when_the_script_changes(tmp_path):
    """Es la «versión» del hook, y por eso no hay constante que alguien deba acordarse de subir."""
    script = tmp_path / "hook.py"
    script.write_text("print(1)\n", encoding="utf-8")
    before = common.version_de(str(script))

    script.write_text("print(2)\n", encoding="utf-8")
    after = common.version_de(str(script))

    assert before and after and len(before) == 8
    assert before != after, "dos scripts distintos no pueden tener la misma huella"
    assert common.version_de(str(tmp_path / "no-existe.py")) == ""


def test_the_context_says_which_script_ran_and_in_which_session():
    context = common.context_of({"session_id": "abc-123"}, str(HOOKS / "hook_common.py"))
    assert context["session_id"] == "abc-123"
    assert len(context["version"]) == 8
    # Un payload sin sesión no rompe nada, pero se nota en el dato.
    assert common.context_of({}, "x")["session_id"] == ""


def test_each_identifier_is_distinct():
    ids = {common.new_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(i) == 12 for i in ids)


# --- Salud del backend ----------------------------------------------------------------------


def _mark(tmp_path, ok: bool, age_s: float = 0.0):
    file = tmp_path / "salud.json"
    file.write_text(json.dumps({"ts": time.time() - age_s, "ok": ok}), encoding="utf-8")
    return file


def test_a_fresh_mark_is_trusted_and_not_probed(monkeypatch, tmp_path):
    probes = []
    monkeypatch.setattr(common, "_probe", lambda t: probes.append(t) or True)

    assert common.backend_available(marker=_mark(tmp_path, ok=True)) is True
    assert common.backend_available(marker=_mark(tmp_path, ok=False)) is False
    assert probes == [], "una marca fresca no debería costar un sondeo"


@pytest.mark.parametrize(
    "prepare",
    [
        lambda tmp: _mark(tmp, ok=True, age_s=3600),
        lambda tmp: tmp / "no-existe.json",
        lambda tmp: (tmp / "rota.json", (tmp / "rota.json").write_text("{", encoding="utf-8"))[0],
        lambda tmp: (
            tmp / "sin-ts.json",
            (tmp / "sin-ts.json").write_text('{"ok": true}', encoding="utf-8"),
        )[0],
    ],
    ids=["vieja", "ausente", "corrupta", "sin ts"],
)
def test_an_unusable_mark_is_asked_again(monkeypatch, tmp_path, prepare):
    """Ninguna de estas se interpreta: se sondea otra vez. Interpretarlas es inventar."""
    probes = []
    monkeypatch.setattr(common, "_probe", lambda t: probes.append(t) or True)

    assert common.backend_available(marker=prepare(tmp_path)) is True
    assert len(probes) == 1


def test_the_probe_is_stored_so_it_is_not_repeated(monkeypatch, tmp_path):
    probes = []
    monkeypatch.setattr(common, "_probe", lambda t: probes.append(t) or True)
    file = tmp_path / "salud.json"

    common.backend_available(marker=file)
    common.backend_available(marker=file)

    assert len(probes) == 1, "el segundo debería haber salido de la marca recién escrita"
    assert json.loads(file.read_text(encoding="utf-8"))["ok"] is True


def test_if_the_mark_cannot_be_written_it_still_answers(monkeypatch, tmp_path):
    """Sin caché se sondea más a menudo: es lento, no incorrecto."""
    monkeypatch.setattr(common, "_probe", lambda t: True)
    unreachable = tmp_path / "no" / "existe" / "salud.json"

    assert common.backend_available(marker=unreachable) is True


def test_a_backend_that_is_not_there_gives_false_without_raising(monkeypatch, tmp_path):
    """Control positivo del sondeo de verdad: contra un puerto donde no hay nadie."""
    monkeypatch.setenv("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9/v1")
    assert common.backend_available(marker=tmp_path / "salud.json", timeout_s=0.2) is False


def test_an_invalid_url_does_not_raise_either(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DELEGATE_BASE_URL", "no-es-una-url")
    assert common.backend_available(marker=tmp_path / "salud.json", timeout_s=0.2) is False


def test_a_401_means_the_backend_IS_there(monkeypatch, tmp_path):
    """El hook casi nunca tiene la credencial: la tiene el lanzador del daemon.

    Se midio en vivo instalando los hooks y ejecutandolos como los ejecuta el cliente: el backend
    de esta maquina responde 401 a `GET /v1/models` sin credencial, y estaba perfectamente. Leer
    eso como «no hay backend» dejaria el bloqueo apagado para siempre en cualquier maquina con el
    backend protegido, que es justo la configuracion recomendada.
    """

    class _Http401(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("http://x/v1/models", 401, "Unauthorized", {}, None)

    def _raises_401(request, timeout=None):
        raise _Http401()

    monkeypatch.setattr(common.urllib.request, "urlopen", _raises_401)

    assert common.backend_available(marker=tmp_path / "salud.json") is True


def test_a_500_does_not_count_as_a_healthy_backend(monkeypatch, tmp_path):
    """Control positivo: contesta, pero no esta en condiciones de atender una delegacion."""

    class _Response:
        status = 503

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(common.urllib.request, "urlopen", lambda *a, **k: _Response())

    assert common.backend_available(marker=tmp_path / "salud.json") is False


def test_each_endpoint_has_its_own_health_mark(monkeypatch):
    """Con una marca global, cambiar de backend heredaba el «esta vivo» del anterior.

    Lo caza un test de instalacion que apunta a un puerto donde no hay nadie: con la marca del
    backend de verdad todavia fresca, recibia un bloqueo que no tocaba.
    """
    monkeypatch.setenv("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9292/v1")
    one = common._health_path()

    monkeypatch.setenv("LOCAL_DELEGATE_BASE_URL", "http://127.0.0.1:9/v1")
    other = common._health_path()

    assert one != other
    assert one.parent == other.parent
