"""Espera frente a lentitud: lo que el log dice de cada llamada (T14, REQ-024 a REQ-028).

Una llamada que tarda puede haber **esperado** (turno, plaza, cola de llama-swap, carga) o haber
**generado lento**. Con los `timings` de llama-server el evento separa las dos cosas
(`inference_ms`, `wait_ms`) y compara la generación con la velocidad normal del modelo
(`pace_rel`, `slow`). Sin `timings`, los campos se omiten: nunca valen 0.

Los requisitos están en `.sdd/changes/daemon-reparte-el-backend/spec.md` (bloque D) y los nombres,
en su tabla de renombrado.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import backend_mock
import httpx2
import pytest
from backend_mock import chat_response, llama_timings
from test_respaldo import CODIGO, LARGO, _fallo, _texto

from local_delegate import config, pace, server
from local_delegate.web import sysinfo

URL = "http://test-backend/v1/chat/completions"
#: Los campos de espera y ritmo que añade el bloque D del log.
SLOWNESS_FIELDS = (
    "inference_ms",
    "wait_ms",
    "tok_s",
    "prefill_tok_s",
    "pace_rel",
    "slow",
    "free_ram_mb",
)
#: Las líneas sembradas llevan esta tool para no confundirlas con el evento del test.
SEED_TOOL = "seed"


# --- piezas comunes ------------------------------------------------------------------------


def _seed_log(
    tmp_path: Path, model: str = LARGO, count: int = 20, speeds: tuple[float, float] = (40.0, 41.0)
) -> None:
    """`count` eventos previos de `model`, mitad a cada velocidad de `speeds` (mediana: la media).

    Se añaden al log del mes, así que se puede sembrar más de un modelo.
    """
    log = tmp_path / f"usage-{server._utcnow():%Y%m}.jsonl"
    lines = [
        json.dumps(
            {
                "ts": "2026-10-01T10:00:00+00:00",
                "tool": SEED_TOOL,
                "model": model,
                "ok": True,
                "tokens_out": 200,
                "tok_s": speeds[0] if i % 2 else speeds[1],
            }
        )
        for i in range(count)
    ]
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _own_event(tmp_path: Path) -> dict:
    """El último evento que NO es de la siembra; `{}` si la operación no llegó a registrarse."""
    lines: list[str] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        lines += file.read_text(encoding="utf-8").splitlines()
    own = [json.loads(line) for line in lines if line.strip()]
    own = [e for e in own if e.get("tool") != SEED_TOOL]
    return own[-1] if own else {}


class _Clock:
    """El módulo `time` de `server` con un reloj monótono que el test adelanta a mano."""

    def __init__(self) -> None:
        self.offset_s = 0.0

    def __getattr__(self, name: str):
        return getattr(time, name)

    def monotonic(self) -> float:
        return time.monotonic() + self.offset_s


@pytest.fixture
def free_ram(monkeypatch):
    """RAM libre fija: el dato es best-effort y en macOS `ram_stats` no lo da."""
    monkeypatch.setattr(
        sysinfo,
        "ram_stats",
        lambda: {"used_gb": 24.5, "total_gb": 32.0, "free_gb": 7.5, "pct": 76.6},
    )


def _slow_answer(clock: _Clock | None = None, wait_s: float = 47.0):
    """El backend: espera `wait_s` (reloj inyectado), luego genera 150 tokens en 10 s (15 tok/s)."""
    timings = llama_timings(prompt_n=2500, prompt_ms=500.0, predicted_n=150, predicted_ms=10_000.0)

    def respond(_request):
        if clock is not None:
            clock.offset_s += wait_s + 10.5
        return chat_response("resumen", timings=timings, tokens_in=2500, tokens_out=150)

    backend_mock.post(URL).mock(side_effect=respond)


# --- Escenario: una llamada lenta se distingue de una espera --------------------------------


@backend_mock.mock
def test_a_slow_call_is_told_apart_from_a_wait(recargar_config, tmp_path, monkeypatch, free_ram):
    """Escenario de la spec: 20 eventos previos a 40,5 tok/s, 47 s de espera y 15 tok/s.

    Control (a): hoy el evento no lleva `pace_rel`.
    """
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    _seed_log(tmp_path)
    clock = _Clock()
    monkeypatch.setattr(server, "time", clock)
    _slow_answer(clock)

    server.local_summarize(text=_texto(10_000))

    line = _own_event(tmp_path)
    assert line.get("pace_rel") == 0.37
    assert line["model"] == LARGO and line["backend"] == "local"
    assert line["inference_ms"] == 10_500
    assert abs(line["wait_ms"] - 47_000) < 1_000, line["wait_ms"]
    assert line["tok_s"] == 15.0
    assert line["prefill_tok_s"] == 5000.0
    assert line["slow"] is True
    assert line["free_ram_mb"] == 7680


@backend_mock.mock
def test_the_event_feeds_the_window_after_being_measured(recargar_config, tmp_path, free_ram):
    """Medir antes de registrar: la llamada no se compara consigo misma, y luego entra."""
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    _seed_log(tmp_path)
    _slow_answer()

    server.local_summarize(text=_texto(10_000))

    window = server._pace_references().window(LARGO)
    assert len(window) == 21
    assert window[-1] == 15.0


# --- Sin `timings`, nada -----------------------------------------------------------------------


@backend_mock.mock
def test_without_timings_no_slowness_field(recargar_config, tmp_path, free_ram):
    """Mutante (b): poner 0 cuando no hay `timings` → falla `assert "tok_s" not in line`."""
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    _seed_log(tmp_path)
    backend_mock.post(URL).mock(return_value=chat_response("resumen", tokens_out=150))

    server.local_summarize(text=_texto(10_000))

    line = _own_event(tmp_path)
    assert line.get("ok") is True, "guarda: la operación se registró"
    assert "tok_s" not in line
    assert not [field for field in SLOWNESS_FIELDS if field in line], line


@backend_mock.mock
def test_incomplete_timings_omit_what_depends_on_them(recargar_config, tmp_path):
    """Sin `predicted_ms`: ni inferencia, ni espera, ni `tok_s`; el prefill sí se puede dar."""
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    timings = {"prompt_n": 1000, "prompt_ms": 500.0, "predicted_n": 150}
    backend_mock.post(URL).mock(
        return_value=chat_response("resumen", timings=timings, tokens_out=150)
    )

    server.local_summarize(text=_texto(10_000))

    line = _own_event(tmp_path)
    assert line.get("ok") is True
    assert line["prefill_tok_s"] == 2000.0
    assert not [f for f in ("inference_ms", "wait_ms", "tok_s", "pace_rel", "slow") if f in line]


# --- Backend remoto: lento, pero sin RAM ------------------------------------------------------


@backend_mock.mock
def test_remote_backend_slow_without_free_ram(recargar_config, tmp_path, free_ram):
    """Mutante (b): sin mirar el origen → falla `assert "free_ram_mb" not in line`."""
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="remote")
    _seed_log(tmp_path)
    _slow_answer()

    server.local_summarize(text=_texto(10_000))

    line = _own_event(tmp_path)
    assert line["backend"] == "remote"
    assert line["slow"] is True, "guarda: la llamada sí salió lenta"
    assert "free_ram_mb" not in line


# --- Operación troceada: la suma de las llamadas reales ---------------------------------------


@backend_mock.mock
def test_chunked_operation_sums_every_real_call_including_a_hop(recargar_config, tmp_path):
    """Mutante (b): solo la última llamada → falla `assert line["inference_ms"] == 300`.

    Cuatro trozos: el primero lo hace el largo (120 ms de inferencia), el segundo falla en el largo
    con un 500 (sin `timings`) y salta al de código, que hace ese y los dos siguientes (60 ms cada
    uno): 120 + 3 × 60 = 300.
    """
    recargar_config()
    long_ok = chat_response("uno", timings=llama_timings(prompt_ms=20.0, predicted_ms=100.0))
    code_ok = chat_response("otro", timings=llama_timings(prompt_ms=10.0, predicted_ms=50.0))
    requested: list[str] = []
    long_answers = [long_ok, _fallo(500)]

    def respond(request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == LARGO:
            return long_answers.pop(0) if len(long_answers) > 1 else long_answers[0]
        assert model == CODIGO, model
        return code_ok

    backend_mock.post(URL).mock(side_effect=respond)

    server.local_translate(target_lang="inglés", text=_texto(12_000))

    line = _own_event(tmp_path)
    assert requested == [LARGO, LARGO, CODIGO, CODIGO, CODIGO], "guarda: hubo salto"
    assert line["chunks"] == 5
    assert line["inference_ms"] == 300


@backend_mock.mock
def test_a_useless_200_counts_its_inference(recargar_config, tmp_path):
    """Un 200 con `content: null` también ocupó la GPU: su inferencia entra en la suma.

    Mutante (b): `_fallo_de_cuerpo` sin los `timings` → falla `assert line["inference_ms"] == 150`.
    """
    recargar_config()
    useless = httpx2.Response(
        200,
        json={
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
            "timings": llama_timings(prompt_ms=40.0, predicted_ms=60.0),
        },
    )
    code_ok = chat_response("resumen", timings=llama_timings(prompt_ms=10.0, predicted_ms=40.0))

    def respond(request):
        return useless if json.loads(request.content)["model"] == LARGO else code_ok

    backend_mock.post(URL).mock(side_effect=respond)

    server.local_summarize(text=_texto(10_000))

    line = _own_event(tmp_path)
    assert line["model_requested"] == LARGO and line["model"] == CODIGO, "guarda: hubo salto"
    assert line["inference_ms"] == 150


# --- Con salto, el ritmo es el del modelo que respondió (aclaración T14) ----------------------


def _useless_long_then_fast_code() -> list[str]:
    """El largo genera 4096 tokens a 40 tok/s y devuelve un 200 sin contenido; salta al de código,
    que genera 200 tokens a 100 tok/s. Devuelve la lista de modelos pedidos."""
    useless = httpx2.Response(
        200,
        json={
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
            "timings": llama_timings(
                prompt_n=2500, prompt_ms=500.0, predicted_n=4096, predicted_ms=102_400.0
            ),
        },
    )
    code_ok = chat_response(
        "resumen",
        timings=llama_timings(
            prompt_n=2500, prompt_ms=250.0, predicted_n=200, predicted_ms=2_000.0
        ),
        tokens_in=2500,
        tokens_out=200,
    )
    requested: list[str] = []

    def respond(request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        return useless if model == LARGO else code_ok

    backend_mock.post(URL).mock(side_effect=respond)
    return requested


@backend_mock.mock
def test_hop_pace_is_the_answering_models(recargar_config, tmp_path, free_ram):
    """Mutante (b): sumar los dos modelos → `tok_s` ≈ 41,2 contra 100 → falla
    `assert line.get("pace_rel") == 1.0` (y saldría `slow: true` sin que el de código fuera lento).
    """
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    _seed_log(tmp_path, model=CODIGO, speeds=(99.0, 101.0))
    requested = _useless_long_then_fast_code()

    server.local_summarize(text=_texto(10_000))

    line = _own_event(tmp_path)
    assert requested == [LARGO, CODIGO] and line["model"] == CODIGO, "guarda: hubo salto"
    assert line.get("pace_rel") == 1.0
    assert line.get("slow") is not True
    assert "free_ram_mb" not in line
    assert line["tok_s"] == 100.0, "el ritmo del evento es el del modelo que respondió"
    assert line["inference_ms"] == 500 + 102_400 + 250 + 2_000, "la inferencia suma las dos"


@backend_mock.mock
def test_hop_does_not_pollute_the_fallback_window(recargar_config, tmp_path, free_ram):
    """Mutante (b): sumar los dos modelos → la ventana del de código recibe ~41 → falla
    `assert window[-1] == 100.0`."""
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    _seed_log(tmp_path, model=CODIGO, speeds=(99.0, 101.0))
    _useless_long_then_fast_code()

    server.local_summarize(text=_texto(10_000))

    window = server._pace_references().window(CODIGO)
    assert len(window) == 21, "guarda: el evento entró en la ventana"
    assert window[-1] == 100.0
    assert server._pace_references().window(LARGO) == [], "el pedido no respondió: no se registra"


@backend_mock.mock
def test_chunked_hop_at_the_end_measures_only_the_answering_model(
    recargar_config, tmp_path, free_ram
):
    """Tres trozos del largo a 40 tok/s y el último salta al de código a 100 tok/s.

    Mutante (b): sumar todos los modelos → `tok_s` 43,75 contra 100 → falla
    `assert line.get("pace_rel") == 1.0`.
    """
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    _seed_log(tmp_path, model=CODIGO, speeds=(99.0, 101.0))
    long_ok = chat_response(
        "uno",
        timings=llama_timings(prompt_ms=100.0, predicted_n=400, predicted_ms=10_000.0),
        tokens_out=400,
    )
    code_ok = chat_response(
        "otro",
        timings=llama_timings(prompt_ms=50.0, predicted_n=200, predicted_ms=2_000.0),
        tokens_out=200,
    )
    long_answers = [long_ok, long_ok, long_ok, _fallo(500)]
    requested: list[str] = []

    def respond(request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model == LARGO:
            return long_answers.pop(0) if len(long_answers) > 1 else long_answers[0]
        return code_ok

    backend_mock.post(URL).mock(side_effect=respond)

    server.local_translate(target_lang="inglés", text=_texto(12_000))

    line = _own_event(tmp_path)
    assert requested == [LARGO, LARGO, LARGO, LARGO, CODIGO], "guarda: saltó en el último trozo"
    assert line["model"] == CODIGO
    assert line.get("pace_rel") == 1.0
    assert line.get("slow") is not True
    assert line["inference_ms"] == 3 * 10_100 + 2_050


# --- La siembra va atada a lo que se siembra -------------------------------------------------


def test_fixed_log_reseeds_when_usage_log_changes(tmp_path, monkeypatch):
    """Log fijo: se siembra con el fichero entero, y otro `USAGE_LOG` en el mismo directorio
    vuelve a sembrar.

    Mutante (b): la caché atada solo al tipo de log (equivale a `LOG_DIR` aquí) → falla
    `assert references.window(LARGO) == []`.
    """
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    _seed_log(tmp_path)
    (tmp_path / f"usage-{server._utcnow():%Y%m}.jsonl").rename(first)
    second.write_text("", encoding="utf-8")

    monkeypatch.setattr(config, "USAGE_LOG", first)
    assert len(server._pace_references().window(LARGO)) == 20, "guarda: el log fijo sembró"

    monkeypatch.setattr(config, "USAGE_LOG", second)
    references = server._pace_references()
    assert references.window(LARGO) == []


# --- Medir antes de registrar -----------------------------------------------------------------


@backend_mock.mock
def test_measured_before_recorded(recargar_config, tmp_path, free_ram):
    """Con 9 muestras previas (una menos que el mínimo), medir antes de registrar da «sin
    referencia»; al revés, la propia llamada completaría las 10 y se compararía consigo misma.

    Mutante (b): registrar antes de medir → falla `assert "pace_rel" not in line`.
    """
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    _seed_log(tmp_path, count=9)
    _slow_answer()

    server.local_summarize(text=_texto(10_000))

    line = _own_event(tmp_path)
    assert line.get("tok_s") == 15.0, "guarda: hubo ritmo que medir"
    assert "pace_rel" not in line
    assert "slow" not in line
    assert len(server._pace_references().window(LARGO)) == 10, "y después sí entra"


# --- REQ-028: observar no rompe la tool -------------------------------------------------------


@backend_mock.mock
def test_a_failing_measure_does_not_break_the_tool(recargar_config, tmp_path, monkeypatch):
    """Mutante (b): sin el `try` → falla `assert line.get("ok") is True`.

    La excepción que se escapara del `_chat` se recoge aquí y se convierte en un evento vacío, así
    que el mutante cae en el assert y no en un error del test.
    """
    recargar_config(LOCAL_DELEGATE_BACKEND_ORIGIN="local")
    _seed_log(tmp_path)
    _slow_answer()

    def boom(*_args, **_kwargs):
        raise RuntimeError("la referencia se rompió")

    monkeypatch.setattr(pace.References, "measure", boom)

    try:
        server.local_summarize(text=_texto(10_000))
        line = _own_event(tmp_path)
    except Exception:
        line = {}

    assert line.get("ok") is True
    assert "pace_rel" not in line
    assert not [field for field in SLOWNESS_FIELDS if field in line], (
        "si falla el bloque, el evento va sin ninguno de sus campos"
    )


# --- local_status muestra la referencia ------------------------------------------------------


def test_local_status_shows_reference_and_samples(tmp_path, monkeypatch):
    """Control (a): hoy `local_status` no dice nada del ritmo de referencia."""
    monkeypatch.setattr(
        server,
        "sondear_backend",
        lambda: server.EstadoBackend(False, [], True, "rechazada", "sin red en los tests", None),
    )
    for name in ("_vram_info", "_ram_info", "_llamaswap_groups"):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    _seed_log(tmp_path)

    text = server.local_status()

    assert "Ritmo de referencia" in text
    assert "gemma4-26b-a4b 40,5 tok/s (20 muestras)" in text
