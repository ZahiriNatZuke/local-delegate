"""Tarea 28 de F3: el salto al respaldo, dentro de la plaza de concurrencia.

Los escenarios de la spec (REQ-002 a REQ-019) sobre `backend_mock`, con un backend que responde
**según el modelo pedido**: así cada test ve a qué modelos se llamó y en qué orden, que es lo único
que distingue un salto de un reintento. Los nombres son los defectos del paquete. Desde T12 de
`daemon-reparte-el-backend` (REQ-019 a REQ-021) no hay residente: las cadenas por defecto son
`code -> loaded -> long`, `long -> loaded -> code` y `mechanical -> loaded -> long`, y sin bloque B
`loaded` no tiene miembros, así que código y largo nunca caen al mecánico. Los tests que miden la
mecánica de varios saltos fijan la cadena a mano con la variable del rol.

La batería de tools en camino feliz no sirve aquí: da lo mismo con el interruptor roto. Cada test
fija un fallo concreto y mira las llamadas.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import backend_mock
import httpx2

from local_delegate import chains, config, cooldown, questions, server
from local_delegate.failures import FailureClass

URL = "http://test-backend/v1/chat/completions"
MECHANICAL = "gemma3-4b"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"
VISION = "gemma4-12b"
CAPACITY_ERROR = '{"error":{"message":"unspecific error: upstream command exited prematurely"}}'


def _ok(content: str = "hecho") -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    )


def _failure(status: int = 500, text: str = "boom") -> httpx2.Response:
    return httpx2.Response(status, text=text)


def _backend(responses: dict) -> list[str]:
    """Registra el POST de chat con una respuesta por modelo; devuelve la lista de modelos pedidos.

    El valor puede ser una respuesta, una excepción o una lista que se consume en orden (la
    última se repite).
    """
    # `backend_mock` atiende con la PRIMERA ruta que casa: sin limpiar, un segundo `_backend` en el
    # mismo test no recibiría ninguna llamada.
    backend_mock._routes.clear()
    requested: list[str] = []
    pending = {m: list(r) if isinstance(r, list) else [r] for m, r in responses.items()}

    def effect(request: httpx2.Request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        queue = pending.get(model)
        if queue is None:
            raise AssertionError(f"se llamó a un modelo sin respuesta: {model}")
        return queue.pop(0) if len(queue) > 1 else queue[0]

    backend_mock.post(URL).mock(side_effect=effect)
    return requested


def _state_file(tmp_path: Path) -> Path:
    return tmp_path / "enfriamiento.json"


def _cool_down(tmp_path: Path, model: str) -> None:
    cooldown.CooldownState(
        _state_file(tmp_path), failures=1, wait_s=120, max_wait_s=900
    ).record_failure(model, FailureClass.MODEL)


def _entries(tmp_path: Path) -> dict:
    path = _state_file(tmp_path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _last_event(tmp_path: Path) -> dict:
    lines = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        lines += file.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def _text(chars: int) -> str:
    paragraph = ("palabra " * 375).strip() + "\n\n"  # 3 000 chars por párrafo
    return (paragraph * (chars // len(paragraph) + 1))[:chars]


# --- Escenario: el modelo largo falla y responde el de código (T12: ya no el residente) --------


@backend_mock.mock
def test_long_fails_and_code_answers(reload_config, tmp_path):
    reload_config()
    requested = _backend(
        {LONG: _failure(500), CODE: _ok("resumen del respaldo"), MECHANICAL: _ok("del 4B")}
    )

    output = server.local_summarize(text=_text(10_000))

    assert requested == [LONG, CODE], "`loaded` vacío se salta y el 4B no es candidato"
    assert "resumen del respaldo" in output
    warning = output.split("resumen del respaldo", 1)[1]
    assert CODE in warning and LONG in warning and "http_500" in warning
    assert _last_event(tmp_path)["model"] == CODE


# --- Escenario: la entrada no cabe en el respaldo ---------------------------------------------


@backend_mock.mock
def test_the_input_that_does_not_fit_the_fallback_gives_todays_error(reload_config, tmp_path):
    text = _text(30_000)  # cabe en largo (48 000); ni residente ni código (20 000) la admiten

    reload_config(LOCAL_DELEGATE_FALLBACK="0", LOCAL_DELEGATE_COOLDOWN="0")
    todays_requests = _backend({LONG: _failure(500)})
    todays_error = server.local_summarize(text=text)

    # Las variables se ENCIENDEN a mano: `reload_config` solo añade, y sin esto la segunda pasada
    # seguiría con el mecanismo apagado y el test no distinguiría nada.
    reload_config(LOCAL_DELEGATE_FALLBACK="1", LOCAL_DELEGATE_COOLDOWN="1")
    assert config.FALLBACK and config.COOLDOWN
    requested = _backend({LONG: _failure(500), MECHANICAL: _ok(), CODE: _ok()})
    output = server.local_summarize(text=text)

    assert todays_requests == [LONG]
    assert requested == [LONG], "no se llama a un candidato que no admite la entrada"
    assert output == todays_error


# --- Escenario: un 400 no dispara el respaldo -------------------------------------------------


@backend_mock.mock
def test_a_400_neither_hops_nor_counts_and_keeps_the_retry_without_schema(reload_config, tmp_path):
    reload_config()
    requested = _backend({MECHANICAL: _failure(400, "schema no soportado"), LONG: _ok('{"a": 1}')})

    output = server.local_extract(fields=["a"], text="texto corto")

    assert requested == [MECHANICAL, MECHANICAL], "el reintento sin schema sigue; no hay salto"
    assert "_local_delegate" in output
    assert _entries(tmp_path) == {}


# --- Escenario: el backend está caído ---------------------------------------------------------


@backend_mock.mock
def test_the_down_backend_neither_hops_nor_cools_down(reload_config, tmp_path, monkeypatch):
    reload_config()
    monkeypatch.setattr(questions, "ask", lambda *a, **k: None)
    requested = _backend({MECHANICAL: httpx2.ConnectError("x"), LONG: _ok()})

    output = server.local_classify(text="hola", labels=["a", "b"])

    assert requested == [MECHANICAL]
    assert "no se pudo conectar" in output
    assert _entries(tmp_path) == {}


# --- Escenario: tres fallos seguidos enfrían el modelo ----------------------------------------


@backend_mock.mock
def test_three_failures_from_two_processes_cool_down_and_the_fourth_goes_direct(
    reload_config, tmp_path
):
    reload_config()
    requested = _backend({CODE: _failure(500), LONG: _ok("explicado")})

    server.local_explain_code(code="x = 1")
    server.local_explain_code(code="x = 2")
    # El tercer fallo lo registra «otro proceso»: otra instancia sobre el mismo fichero.
    cooldown.from_config().record_failure(CODE, FailureClass.MODEL)
    assert cooldown.from_config().lookup(CODE) is not None

    requested.clear()
    output = server.local_explain_code(code="x = 3")

    assert requested == [LONG], "el modelo enfriado no recibe la cuarta llamada"
    assert "explicado" in output and "enfriamiento" in output


# --- Escenario: en enfriamiento y sin alternativa, falla al momento ---------------------------


@backend_mock.mock
def test_cooled_down_without_alternative_fails_at_once(reload_config, tmp_path):
    reload_config(LOCAL_DELEGATE_FALLBACK_MECHANICAL="none")
    _cool_down(tmp_path, MECHANICAL)
    requested = _backend({MECHANICAL: _ok()})

    start = time.monotonic()
    output = server.local_classify(text="hola", labels=["a", "b"])

    assert time.monotonic() - start < 1.0
    assert requested == []
    assert output.startswith("[local-delegate error]")
    assert MECHANICAL in output and "enfriamiento" in output and "hasta" in output


# --- Escenarios: vence el enfriamiento --------------------------------------------------------


def _expired(tmp_path: Path, model: str, wait_s: float = 120.0) -> None:
    data = {model: {"fallos": 0, "espera_s": wait_s, "hasta": time.time() - 1, "reentradas": 1}}
    _state_file(tmp_path).write_text(json.dumps(data), encoding="utf-8")


@backend_mock.mock
def test_cooldown_expires_and_the_probe_succeeds(reload_config, tmp_path):
    reload_config()
    _expired(tmp_path, MECHANICAL)
    requested = _backend({MECHANICAL: _ok("a")})

    server.local_classify(text="hola", labels=["a", "b"])

    assert requested == [MECHANICAL]
    assert MECHANICAL not in _entries(tmp_path)


@backend_mock.mock
def test_cooldown_expires_and_the_failing_probe_doubles_the_wait(reload_config, tmp_path):
    reload_config()
    _expired(tmp_path, MECHANICAL)
    requested = _backend({MECHANICAL: _failure(500), LONG: _ok("a")})

    server.local_classify(text="hola", labels=["a", "b"])

    assert requested == [MECHANICAL, LONG]
    assert _entries(tmp_path)[MECHANICAL]["espera_s"] == 240.0


# --- Escenario: traducción en trozos con respaldo a mitad (REQ-006) ---------------------------


@backend_mock.mock
def test_translation_in_four_chunks_switches_model_only_once(reload_config, tmp_path):
    reload_config()
    requested = _backend({LONG: [_ok("uno"), _failure(500), _ok("NO")], CODE: _ok("otro")})

    output = server.local_translate(target_lang="inglés", text=_text(12_000))

    assert requested == [LONG, LONG, CODE, CODE, CODE]
    assert "NO" not in output
    assert "trozo 2" in output and CODE in output


@backend_mock.mock
def test_commit_in_map_reduce_hops_and_continues_with_the_fallback(reload_config, tmp_path):
    reload_config()
    requested = _backend({CODE: _failure(500), LONG: _ok("- a: cambia")})
    diff = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n" + "+linea de codigo nueva\n" * 200 for i in range(6)
    )
    assert len(diff) > config.max_chars_for_role("code")

    output = server.local_commit_msg(diff=diff)

    assert requested.count(CODE) == 1, "tras el salto, los trozos siguientes van al respaldo"
    assert set(requested) == {CODE, LONG}
    assert not output.startswith("[local-delegate error]")


@backend_mock.mock
def test_in_long_map_reduce_the_fallback_is_dead_by_construction(reload_config, tmp_path):
    # Los trozos miden 0,8 x 48 000 = 38 400 chars y ningún candidato de 20 000 los admite
    # (REQ-003): el salto no puede ocurrir con los topes de hoy. Se fija para no descubrirlo en
    # producción.
    reload_config()
    requested = _backend({LONG: _failure(500), MECHANICAL: _ok(), CODE: _ok()})

    output = server.local_summarize(text=_text(60_000))

    assert requested == [LONG]
    assert output.startswith("[local-delegate error]")


# --- Escenario: el modelo no cabe en la VRAM (REQ-018 de F3, enmendado por REQ-021) -----------


@backend_mock.mock
def test_capacity_only_hops_to_loaded_without_second_hop(reload_config, tmp_path):
    """Con un miembro en `loaded` (el proveedor lo pone T15; aquí, a mano), capacidad salta a él y
    a nada más. Sin miembros no salta: `test_chains.py::test_capacity_failure_with_nothing_loaded`.
    """
    reload_config()
    previous_provider = chains._loaded_provider
    chains.register_loaded_provider(lambda *_: (MECHANICAL,))
    try:
        requested = _backend(
            {CODE: _failure(500, CAPACITY_ERROR), MECHANICAL: _failure(500), LONG: _ok()}
        )
        output = server.local_explain_code(code="x = 1")
    finally:
        chains.register_loaded_provider(previous_provider)

    assert requested == [CODE, MECHANICAL], "tras capacidad, `loaded` y nada más"
    assert output.startswith("[local-delegate error]")
    assert CODE not in _entries(tmp_path), "capacidad no enfría"


@backend_mock.mock
def test_resident_capacity_does_not_hop_to_a_large_model(reload_config, tmp_path):
    reload_config()
    requested = _backend({MECHANICAL: _failure(500, CAPACITY_ERROR), LONG: _ok()})

    server.local_classify(text="hola", labels=["a", "b"])

    assert requested == [MECHANICAL]


# --- Escenario: un modelo de razonamiento agota max_tokens (REQ-019) --------------------------


@backend_mock.mock
def test_exhausted_reasoning_neither_hops_nor_cools_down(reload_config, tmp_path):
    reload_config()
    exhausted = httpx2.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": "", "reasoning_content": "pienso"},
                    "finish_reason": "length",
                }
            ]
        },
    )
    requested = _backend({MECHANICAL: exhausted, LONG: _ok()})

    output = server.local_classify(text="hola", labels=["a", "b"])

    assert requested == [MECHANICAL]
    assert "max_tokens" in output
    assert _entries(tmp_path) == {}


@backend_mock.mock
def test_length_without_reasoning_is_unclassified_and_does_not_hop(reload_config, tmp_path):
    reload_config()
    null = httpx2.Response(
        200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}]}
    )
    requested = _backend({MECHANICAL: null, LONG: _ok()})

    server.local_classify(text="hola", labels=["a", "b"])

    assert requested == [MECHANICAL]


# --- Escenario: timeout mientras el modelo carga ----------------------------------------------


@backend_mock.mock
def test_timeout_during_load_does_not_cool_down(reload_config, tmp_path):
    reload_config(LOCAL_DELEGATE_FALLBACK="0")
    _backend({MECHANICAL: httpx2.ReadTimeout("x")})

    server.local_classify(text="hola", labels=["a", "b"])

    assert _entries(tmp_path) == {}


@backend_mock.mock
def test_timeout_with_the_model_loaded_counts_and_does_not_hop(
    reload_config, tmp_path, monkeypatch
):
    reload_config()
    monkeypatch.setattr(server._LoadProbe, "model_loaded", lambda self, **_: True)
    requested = _backend({MECHANICAL: httpx2.ReadTimeout("x"), LONG: _ok()})

    server.local_classify(text="hola", labels=["a", "b"])

    assert requested == [MECHANICAL], "D-2: un timeout de lectura no dispara el respaldo"
    assert _entries(tmp_path)[MECHANICAL]["fallos"] == 1


# --- Escenario: benchmark con el mecanismo apagado --------------------------------------------


@backend_mock.mock
def test_with_the_fallback_off_no_failure_hops(reload_config, tmp_path):
    reload_config(LOCAL_DELEGATE_FALLBACK="0")
    requested = _backend({CODE: _failure(500), MECHANICAL: _ok()})

    server.local_explain_code(code="x = 1")

    assert requested == [CODE]


# --- Escenario: modelo explícito (REQ-005) ----------------------------------------------------


@backend_mock.mock
def test_explicit_model_is_sent_even_if_cooled_down_and_updates_its_state(reload_config, tmp_path):
    reload_config()
    _cool_down(tmp_path, LONG)
    requested = _backend({LONG: _ok("hecho por el largo"), MECHANICAL: _ok()})

    output = server.local_delegate(task="t", input="x", output_format="texto", model=LONG)

    assert requested == [LONG]
    assert "hecho por el largo" in output
    assert LONG not in _entries(tmp_path), "el éxito lo deja limpio"


@backend_mock.mock
def test_failing_explicit_model_does_not_hop(reload_config, tmp_path):
    reload_config()
    requested = _backend({LONG: _failure(500), MECHANICAL: _ok()})

    server.local_delegate(task="t", input="x", output_format="texto", model=LONG)

    assert requested == [LONG]


@backend_mock.mock
def test_the_model_chosen_in_the_question_counts_as_explicit(reload_config, tmp_path, monkeypatch):
    reload_config()
    _cool_down(tmp_path, LONG)

    class _Choice:
        model = LONG

    monkeypatch.setattr(questions, "ask", lambda *a, **k: _Choice())
    requested = _backend({LONG: _ok(), MECHANICAL: _ok()})

    server.local_delegate(task="t", input="x", output_format="texto", model="missing")

    assert requested == [LONG]


# --- Escenario: mecanismo apagado. El caso que distingue el interruptor -----------------------


@backend_mock.mock
def test_with_both_variables_off_it_is_todays_behavior(reload_config, tmp_path):
    reload_config(LOCAL_DELEGATE_FALLBACK="0", LOCAL_DELEGATE_COOLDOWN="0")
    _cool_down(tmp_path, CODE)
    before = _state_file(tmp_path).read_bytes()
    requested = _backend({CODE: _failure(500), MECHANICAL: _ok()})

    output = server.local_explain_code(code="x = 1")

    assert requested == [CODE], "una sola llamada, al principal, aunque el fichero lo enfríe"
    assert output == f"[local-delegate error] {CODE} respondió 500: boom"
    assert _state_file(tmp_path).read_bytes() == before


@backend_mock.mock
def test_the_same_case_with_the_mechanism_on_hops(reload_config, tmp_path):
    reload_config()
    _cool_down(tmp_path, CODE)
    requested = _backend({CODE: _failure(500), LONG: _ok("explicado")})

    output = server.local_explain_code(code="x = 1")

    assert requested == [LONG]
    assert "explicado" in output


# --- Escenario: estado ilegible ---------------------------------------------------------------


@backend_mock.mock
def test_with_corrupt_state_it_continues_without_cooldown(reload_config, tmp_path):
    reload_config()
    _state_file(tmp_path).write_text("{no es json", encoding="utf-8")
    requested = _backend({MECHANICAL: _ok("a")})

    output = server.local_classify(text="hola", labels=["a", "b"])

    assert requested == [MECHANICAL]
    assert output == "a"


# --- REQ-002: tope de saltos y clase que corta la cadena --------------------------------------


@backend_mock.mock
def test_walks_both_hops_of_the_chain(reload_config, tmp_path):
    """Con el rol `fast` retirado (0.30.0) quedan tres modelos de texto, así que una cadena no
    puede tener más de dos candidatos distintos del principal: este test pasa a comprobar que los
    **recorre los dos** y que ahí se acaba. Que el tope CORTA lo prueba el de abajo, bajándolo a 1.
    Desde T12 las cadenas por defecto solo tienen un modelo concreto (`loaded` sale vacío sin bloque
    B), así que la cadena de dos se fija a mano: el mecánico, por variable, sí se puede pedir.
    """
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="mechanical,long")
    requested = _backend({CODE: _failure(500), MECHANICAL: _failure(500), LONG: _failure(500)})

    server.local_explain_code(code="x = 1")

    assert requested == [CODE, MECHANICAL, LONG]


@backend_mock.mock
def test_the_hop_cap_is_configurable(reload_config, tmp_path):
    reload_config(
        LOCAL_DELEGATE_FALLBACK_MAX_HOPS="1", LOCAL_DELEGATE_FALLBACK_CODE="mechanical,long"
    )
    requested = _backend({CODE: _failure(500), MECHANICAL: _failure(500), LONG: _ok()})

    server.local_explain_code(code="x = 1")

    assert requested == [CODE, MECHANICAL]


@backend_mock.mock
def test_a_failure_of_another_class_in_the_fallback_cuts_the_chain(reload_config, tmp_path):
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="mechanical,long")
    requested = _backend({CODE: _failure(500), MECHANICAL: _failure(400, "malo"), LONG: _ok()})

    server.local_explain_code(code="x = 1")

    assert requested == [CODE, MECHANICAL]


# --- REQ-008: fallan también los respaldos ----------------------------------------------------


@backend_mock.mock
def test_if_the_fallbacks_fail_the_original_error_and_the_list_come_back(reload_config, tmp_path):
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="mechanical,long")
    _backend({CODE: _failure(500, "original"), MECHANICAL: _failure(502), LONG: _failure(503)})

    output = server.local_explain_code(code="x = 1")

    first, *rest = output.splitlines()
    assert first == f"[local-delegate error] {CODE} respondió 500: original"
    detail = "\n".join(rest)
    assert f"{MECHANICAL} (http_502)" in detail and f"{LONG} (http_503)" in detail
    entries = _entries(tmp_path)
    assert all(entries[m]["fallos"] == 1 for m in (CODE, MECHANICAL, LONG))


# --- REQ-007: el aviso nunca se mezcla con el contenido ---------------------------------------


@backend_mock.mock
def test_in_extract_the_warning_goes_in_the_metadata(reload_config, tmp_path):
    reload_config()
    _backend({MECHANICAL: _failure(500), LONG: _ok('{"a": 1}')})

    data = server.local_extract(fields=["a"], text="texto corto")

    assert data["a"] == 1
    fallback = data["_local_delegate"]["fallback"]
    assert fallback["answered_by"] == LONG and fallback["instead_of"] == MECHANICAL
    assert fallback["reason"] == "http_500"


@backend_mock.mock
def test_in_boilerplate_the_warning_goes_in_the_receipt_and_not_the_file(reload_config, tmp_path):
    reload_config()
    _backend({CODE: _failure(500), LONG: _ok("def f():\n    return 1")})
    dest = tmp_path / "gen.py"

    receipt = server.local_boilerplate(spec="f", language="python", target=str(dest))

    # `_write_target` termina el fichero en salto de línea; lo que importa es que no hay aviso.
    assert dest.read_text(encoding="utf-8") == "def f():\n    return 1\n"
    assert LONG in receipt and CODE in receipt


@backend_mock.mock
def test_in_boilerplate_nothing_is_written_if_all_fail(reload_config, tmp_path):
    reload_config()
    _backend({CODE: _failure(500), MECHANICAL: _failure(500), LONG: _failure(500)})
    dest = tmp_path / "gen.py"

    server.local_boilerplate(spec="f", language="python", target=str(dest))

    assert not dest.exists()


# --- Visión: enfriamiento sí, respaldo no -----------------------------------------------------


@backend_mock.mock
def test_cooled_down_vision_fails_at_once_without_fallback(reload_config, tmp_path):
    reload_config()
    _cool_down(tmp_path, VISION)
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    requested = _backend({VISION: _ok(), MECHANICAL: _ok()})

    output = server.local_describe_image(path=str(image))

    assert requested == []
    assert VISION in output and "enfriamiento" in output


@backend_mock.mock
def test_failing_vision_does_not_hop(reload_config, tmp_path):
    reload_config()
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    requested = _backend({VISION: _failure(500), MECHANICAL: _ok()})

    server.local_describe_image(path=str(image))

    assert requested == [VISION]


# --- REQ-006 (enmienda REQ-017 de F3): el salto suelta la plaza y el tope se sigue cumpliendo ----


def test_hop_releases_slot_between_primary_and_fallback(reload_config, tmp_path, monkeypatch):
    """Sustituye al test de REQ-017 de F3 («el salto no suelta la plaza»), con el mismo escenario.

    Una sola plaza; A falla en su principal mientras B ya espera la plaza. Con REQ-006 el salto de
    A suelta la plaza ANTES de decidir y volver a pedirla, así que B entra entre el principal y el
    respaldo de A; y aun así nunca hay dos llamadas a la vez (el tope de `MAX_CONCURRENT_REQUESTS`).
    La decisión del salto de A espera (con tope) a que B haya entrado: sin eso, que A recupere la
    plaza antes que B dependería del planificador. Con el salto DENTRO de la plaza, B no puede
    entrar, la espera agota su tope y el orden sale A, A, B, B.
    """
    reload_config()
    order: list[tuple[str, str]] = []
    inside = 0
    peak = 0
    lock = threading.Lock()
    primary_of_a = threading.Event()
    b_entered = threading.Event()

    def post_chat(model, _payload):
        nonlocal inside, peak
        with lock:
            inside += 1
            peak = max(peak, inside)
            order.append((threading.current_thread().name, model))
        if threading.current_thread().name == "A" and model == CODE:
            primary_of_a.set()
        if threading.current_thread().name == "B":
            b_entered.set()
        time.sleep(0.1)
        with lock:
            inside -= 1
        if model == CODE:
            return server.ChatResult(
                text="x", ok=False, error="http_500", error_class=FailureClass.MODEL
            )
        return server.ChatResult(text="ok", ok=True, finish_reason="stop")

    decide = server._next_hop

    def next_hop(*args, **kwargs):
        if threading.current_thread().name == "A" and kwargs.get("last") is None:
            b_entered.wait(timeout=2)
        return decide(*args, **kwargs)

    monkeypatch.setattr(server, "_post_chat", post_chat)
    monkeypatch.setattr(server, "_next_hop", next_hop)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(1))

    def call_fn() -> None:
        server._chat(CODE, "s", "u", 8, role="code")

    a = threading.Thread(target=call_fn, name="A")
    b = threading.Thread(target=call_fn, name="B")
    a.start()
    assert primary_of_a.wait(timeout=5)
    b.start()  # B ya espera la plaza cuando A falla: como A la suelta para saltar, B entra
    a.join(timeout=10)
    b.join(timeout=10)

    assert not a.is_alive() and not b.is_alive()
    assert peak == 1
    assert [thread for thread, _ in order[:2]] == ["A", "B"], order
    assert sorted(order) == sorted([("A", CODE), ("A", LONG), ("B", CODE), ("B", LONG)])


# --- El camino feliz no escribe el estado -----------------------------------------------------


@backend_mock.mock
def test_the_happy_path_does_not_create_the_state_file(reload_config, tmp_path):
    reload_config()
    _backend({MECHANICAL: _ok("a")})

    server.local_classify(text="hola", labels=["a", "b"])

    assert not _state_file(tmp_path).exists()
