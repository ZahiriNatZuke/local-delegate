"""El corte por backend inalcanzable (issue #436, punto 3).

Con la VPN corporativa puesta, el nombre del backend no resuelve y cada `local_*` falla en ~22 ms,
pero el agente sigue llamándolas: 14 intentos fallidos en una sesión. Tras N fallos de CONEXIÓN
seguidos, las tools responden al momento que el backend no está, sin llamarlo y sin registrar una
delegación; al vencer la espera, la siguiente llamada va de verdad y, si conecta, se cierra. Los
hooks de sugerencia callan mientras dure.

Cada test mira el uso: cuántas veces llegó una petición al backend, qué quedó en el log de uso y qué
ve otro proceso.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import config, cooldown, hook_entry, server
from local_delegate.failures import FailureClass

CHAT = "http://test-backend/v1/chat/completions"
MODELS = "http://test-backend/v1/models"
KEY = "test-backend"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "BACKEND_BREAKER", True)
    monkeypatch.setattr(config, "BACKEND_BREAKER_FAILURES", 3)
    monkeypatch.setattr(config, "BACKEND_BREAKER_S", 60.0)
    monkeypatch.setattr(config, "BACKEND_BREAKER_MAX_S", 600.0)
    # Sin respaldo ni enfriamiento por modelo: aquí solo se mira la conexión.
    monkeypatch.setattr(config, "FALLBACK", False)
    monkeypatch.setattr(config, "COOLDOWN", False)
    return tmp_path


def _usage(tmp_path: Path) -> list[dict]:
    """Los eventos del log de uso (`usage*.jsonl`, rote por mes o no)."""
    rows: list[dict] = []
    for log in sorted(tmp_path.glob("usage*.jsonl")):
        rows += [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    return rows


def _breaker_events(tmp_path: Path) -> list[dict]:
    log = tmp_path / cooldown.BREAKER_EVENTS_FILE
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def _ok() -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": {"content": "resumen"}, "finish_reason": "stop"}]}
    )


def _summarize() -> str:
    return server.local_summarize(text="un texto corto que resumir", max_words=20)


def _expire(tmp_path: Path) -> None:
    """Simula que pasó la espera: el `until` del corte queda en el pasado."""
    state_file = tmp_path / cooldown.BREAKER_STATE_FILE
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data[KEY]["until"] = time.time() - 1
    state_file.write_text(json.dumps(data), encoding="utf-8")


# --- N-1 no cortan, N sí; y la llamada cortada no llega al backend ni al log ----------------------


@backend_mock.mock
def test_two_connection_failures_do_not_cut_and_the_third_does(env):
    route = backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectError("getaddrinfo failed"))

    for _ in range(2):
        assert "[local-delegate error]" in _summarize()
    assert cooldown.backend_breaker().lookup(KEY) is None, "N-1 fallos no cortan"
    assert route.call_count == 2

    _summarize()
    assert cooldown.backend_breaker().lookup(KEY) is not None, "el N-ésimo corta"
    assert route.call_count == 3

    text = _summarize()
    assert route.call_count == 3, "con el corte abierto no se llama al backend"
    assert text.startswith(server.ERROR_PREFIX)
    assert "test-backend" in text and "local_status" in text
    # La llamada cortada no es una delegación ni un fallo nuevo: el log de uso sigue con 3.
    assert len(_usage(env)) == 3
    assert all(row["connection_failure"] for row in _usage(env))
    # Queda contada aparte, en el registro del corte.
    kinds = [event["event"] for event in _breaker_events(env)]
    assert kinds == ["enter", "skip"]


@backend_mock.mock
@pytest.mark.parametrize(
    ("language", "phrase"), [("es", "haz tú esta tarea"), ("en", "do this task yourself")]
)
def test_the_cut_message_follows_the_language(env, language, phrase):
    from local_delegate import i18n

    backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectError("down"))
    for _ in range(3):
        _summarize()
    with i18n.override(language):
        assert phrase in _summarize()


# --- Solo cuentan los fallos de conexión ---------------------------------------------------------


@backend_mock.mock
@pytest.mark.parametrize("status", [503, 500])
def test_errors_with_an_answer_never_cut(env, status):
    route = backend_mock.post(CHAT).mock(return_value=httpx2.Response(status, text="cargado"))
    for _ in range(6):
        _summarize()
    assert route.call_count == 6, "un backend que contesta, aunque sea con error, se sigue llamando"
    assert cooldown.backend_breaker().lookup(KEY) is None


@backend_mock.mock
def test_an_answer_in_between_resets_the_streak(env):
    route = backend_mock.post(CHAT).mock(
        side_effect=[
            httpx2.ConnectError("down"),
            httpx2.ConnectError("down"),
            httpx2.Response(500, text="boom"),
            httpx2.ConnectError("down"),
            httpx2.ConnectError("down"),
        ]
    )
    for _ in range(5):
        _summarize()
    assert route.call_count == 5
    assert cooldown.backend_breaker().lookup(KEY) is None, "la racha empieza de cero tras responder"


# --- Recuperación: al vencer, la siguiente llamada es la prueba ---------------------------------


@backend_mock.mock
def test_after_the_wait_one_call_goes_through_and_closes_the_cut(env):
    route = backend_mock.post(CHAT).mock(
        side_effect=[httpx2.ConnectError("down")] * 3 + [_ok(), _ok()]
    )
    for _ in range(3):
        _summarize()
    _summarize()  # cortada
    assert route.call_count == 3

    _expire(env)
    assert _summarize() == "resumen"
    assert route.call_count == 4, "vencido, la llamada va de verdad"
    assert cooldown.backend_breaker().lookup(KEY) is None
    assert _summarize() == "resumen"
    assert route.call_count == 5
    assert [e["event"] for e in _breaker_events(env)] == ["enter", "skip", "clear"]


@backend_mock.mock
def test_a_failed_probe_cuts_again_with_the_wait_doubled(env):
    route = backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectError("down"))
    for _ in range(3):
        _summarize()
    _expire(env)
    _summarize()  # la prueba, que falla
    assert route.call_count == 4
    cut = cooldown.backend_breaker().lookup(KEY)
    assert cut is not None and cut.reentries == 2
    assert cut.remaining_s == pytest.approx(120.0, abs=5)
    _summarize()
    assert route.call_count == 4


@backend_mock.mock
def test_a_good_status_probe_closes_the_cut(env):
    backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(200, json={"data": [{"id": "m"}]}))
    backend_mock.get("http://test-backend/running").mock(return_value=httpx2.Response(404))
    for _ in range(3):
        _summarize()
    assert cooldown.backend_breaker().lookup(KEY) is not None
    status = server.local_status()
    assert cooldown.backend_breaker().lookup(KEY) is None, "local_status ve el backend y lo cierra"
    assert "LOCAL_DELEGATE_BACKEND_BREAKER" not in status  # encendido: no dice cómo apagarlo


@backend_mock.mock
def test_status_shows_the_open_cut(env):
    backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get(MODELS).mock(side_effect=httpx2.ConnectError("down"))
    for _ in range(3):
        _summarize()
    lines = server._describe_backend_breaker()
    assert len(lines) == 2, lines


@backend_mock.mock
def test_disabled_never_cuts(env, monkeypatch):
    monkeypatch.setattr(config, "BACKEND_BREAKER", False)
    route = backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectError("down"))
    for _ in range(5):
        _summarize()
    assert route.call_count == 5
    assert not (env / cooldown.BREAKER_STATE_FILE).exists()


# --- Las operaciones troceadas también se cortan antes de empezar --------------------------------


@backend_mock.mock
def test_chunked_and_map_reduce_operations_are_cut_too(env):
    route = backend_mock.post(CHAT).mock(side_effect=httpx2.ConnectError("down"))
    for _ in range(3):
        _summarize()
    before = route.call_count
    big = "Párrafo de prueba con algo de texto.\n\n" * 3000
    assert "haz tú esta tarea" in server.local_translate("inglés", text=big)
    assert "haz tú esta tarea" in server.local_summarize(text=big, max_words=50)
    assert route.call_count == before
    assert len(_usage(env)) == 3


# --- Dos procesos ven el mismo estado ------------------------------------------------------------


def test_a_cut_opened_by_another_process_is_seen_here(env):
    code = (
        "from local_delegate import config, cooldown\n"
        "from local_delegate.failures import FailureClass\n"
        "from pathlib import Path\n"
        "import sys\n"
        "config.LOG_DIR = Path(sys.argv[1])\n"
        "config.BACKEND_BREAKER_FAILURES = 3\n"
        "b = cooldown.backend_breaker()\n"
        "[b.record_failure('test-backend', FailureClass.ENDPOINT) for _ in range(3)]\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code, str(env)], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    assert cooldown.backend_breaker().lookup(KEY) is not None


def test_only_the_endpoint_class_counts(tmp_path):
    """El estado filtra la clase: `capacity_or_load` o un fallo del modelo no suman nunca."""
    state = cooldown.CooldownState(
        tmp_path / cooldown.BREAKER_STATE_FILE,
        failures=1,
        wait_s=60,
        max_wait_s=600,
        counting=frozenset({FailureClass.ENDPOINT}),
        events_file=cooldown.BREAKER_EVENTS_FILE,
        legacy_file=None,
    )
    for other in (FailureClass.CAPACITY, FailureClass.MODEL, FailureClass.READ_TIMEOUT):
        state.record_failure(KEY, other)
    assert state.lookup(KEY) is None
    state.record_failure(KEY, FailureClass.ENDPOINT)
    assert state.lookup(KEY) is not None


# --- Hooks de sugerencia: callan mientras dure ---------------------------------------------------


@pytest.fixture
def cut_open(env, monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(env))
    for _ in range(3):
        cooldown.backend_breaker().record_failure(KEY, FailureClass.ENDPOINT)
    return env


def test_the_hook_copy_of_the_file_name_is_the_package_one():
    from local_delegate.resources.hooks import hook_common

    assert hook_common.BACKEND_BREAKER_FILE == cooldown.BREAKER_STATE_FILE


def test_the_hook_sees_the_cut_and_its_expiry(cut_open):
    from local_delegate.resources.hooks import hook_common

    assert hook_common.backend_down() is True
    _expire(cut_open)
    assert hook_common.backend_down() is False


def test_the_hook_reads_nothing_as_not_down(env, monkeypatch):
    from local_delegate.resources.hooks import hook_common

    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(env))
    assert hook_common.backend_down() is False
    (env / cooldown.BREAKER_STATE_FILE).write_text("{roto", encoding="utf-8")
    assert hook_common.backend_down() is False


def _classify(env_vars: dict, file: Path) -> dict:
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(file)}, "cwd": str(file.parent)}
    return json.loads(hook_entry.classify_text(payload, env_vars))


def test_the_read_mod_steps_aside_while_the_cut_is_open(cut_open, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("prosa larga\n" * 4000, encoding="utf-8")
    switch = tmp_path / "no-switch-file"
    env_vars = {
        "LD_HOOK_READ_ENABLED": "1",
        "LD_HOOK_READ_BLOCK": "1",
        "LD_HOOK_READ_SWITCH_FILE": str(switch),
        "LOCAL_DELEGATE_LOG_DIR": str(cut_open),
    }
    # El mod solo resume o avisa con `read_switch == "on"` (mod/read.js).
    assert _classify(env_vars, doc)["read_switch"] == "backend_down"
    _expire(cut_open)
    assert _classify(env_vars, doc)["read_switch"] == "on"


HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"


def _load_hook(name: str):
    import importlib.util

    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _telemetry(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.parametrize("down", [True, False], ids=["cut", "control"])
def test_the_prompt_hook_does_not_suggest_while_the_cut_is_open(
    cut_open, monkeypatch, capsys, tmp_path, down
):
    if not down:
        _expire(cut_open)
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    hook = _load_hook("suggest_delegate_prompt")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "resume este log"})))
    hook.main()
    out = capsys.readouterr().out
    if down:
        assert out.strip() == ""
        assert _telemetry(log)[-1]["reason"] == "backend_down"
    else:
        assert "local_" in out, "control positivo: sin corte, sí sugiere"


@pytest.mark.parametrize("down", [True, False], ids=["cut", "control"])
def test_the_shell_hook_does_not_block_while_the_cut_is_open(
    cut_open, monkeypatch, capsys, tmp_path, down
):
    if not down:
        _expire(cut_open)
    doc = tmp_path / "report.md"
    doc.write_text("x" * 40 * 1024, encoding="utf-8")
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    monkeypatch.setenv("LD_HOOK_READ_SWITCH_FILE", str(tmp_path / "no-switch"))
    hook = _load_hook("suggest_delegate_shell")
    monkeypatch.setattr(hook, "backend_available", lambda **k: True)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": f"cat {doc}"}}))
    )
    hook.main()
    out = capsys.readouterr().out
    if down:
        assert out.strip() == ""
        assert _telemetry(log)[-1]["reason"] == "backend_down"
    else:
        assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
