"""llama-swap y `benchmark` en español y en inglés (frente B, ola B1c): REQ-021, REQ-026 y REQ-034.

- **REQ-021:** la vista y los errores de `llamaswap residency`, las negativas y las salidas de la
  vigía, los errores del lector de topología, el detalle del estimador de VRAM y los errores de
  `benchmark` salen en el idioma vigente.
- **REQ-026:** los GiB llevan coma decimal en español y punto en inglés.
- **Valores de máquina:** los motivos de REQ-002 (`topology.NO_CONFIG`…) y las salidas de la vigía
  (`reloaded`…) viajan entre el daemon y el CLI: no cambian con el idioma; a la persona se le
  dicen con `topology.reason_text` y `llamaswap_api.outcome_text`.
- **REQ-034:** humo en inglés sin palabras distintivas del catálogo español ni tildes, con su
  control positivo permanente en español.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

import pytest
from test_residency import TODAY, _copy, _residency, _vram_args, _writes

from local_delegate import benchmark, checks, i18n, residency, topology, turn
from local_delegate import llamaswap_api as api
from local_delegate import llamaswap_config as lc

_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
_ACCENTS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡«»]")
#: Sin `globalTTL` ni `ttl`: los dos modelos son residentes y la vista lleva la explicación, los
#: avisos y el veredicto, es decir, todos sus textos.
_ALL_RESIDENT = (
    b"models:\n  a:\n    cmd: x --model a.gguf\n  b:\n    cmd: x --model b.gguf\n"
    b"groups:\n  g:\n    swap: true\n    exclusive: false\n    members:\n    - a\n    - b\n"
)


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()


def _distinctive_spanish_words() -> set[str]:
    """Palabras del catálogo español de `cli` que no salen en ningún valor inglés."""
    folder = files("local_delegate").joinpath("resources", "i18n")
    es = json.loads(folder.joinpath("es", "cli.json").read_text(encoding="utf-8"))
    en = json.loads(folder.joinpath("en", "cli.json").read_text(encoding="utf-8"))
    english = {w.lower() for text in en.values() for w in _WORD.findall(text)}
    spanish = {
        w.lower() for key, text in es.items() if text != en[key] for w in _WORD.findall(text)
    }
    return spanish - english


def _spanish_in(text: str, words: set[str]) -> list[str]:
    return sorted({w for w in (m.lower() for m in _WORD.findall(text)) if w in words})


def _outputs(tmp_path: Path, capsys) -> dict[str, str]:
    """Las salidas de B1c que ve una persona, en el idioma vigente."""
    outputs: dict[str, str] = {}
    loaded = residency.load(_writes(tmp_path, _ALL_RESIDENT, "all-resident.yaml"))
    outputs["view"] = residency.view(loaded.snapshot, loaded.data).text()

    assert _residency("--config", str(_copy(TODAY, tmp_path))) == 0
    outputs["view_today"] = capsys.readouterr().out

    rc = _residency(
        "--config",
        str(_copy(TODAY, tmp_path, "pin.yaml")),
        "--pin",
        "gemma4-26b-a4b",
        "--vram-gb",
        "16",
        "--reserve-gb",
        "2",
        *_vram_args(),
        "--now",
    )
    assert rc == 2
    outputs["does_not_fit"] = capsys.readouterr().err

    status = api.Status(api.STATE_OK, in_flight={"m": 1}, own_delegations=2)
    status.models = [{"id": "m"}]
    outputs["refusals"] = "; ".join(api.refusals(status))
    outputs["outcomes"] = ", ".join(api.outcome_text(o) for o in sorted(api.OUTCOMES))
    outputs["topology"] = "; ".join(
        topology.validate_like_load_go(
            {"models": {"a": {"ttl": "x"}}, "groups": {"g": {"members": ["a", "a", "z"]}}}
        )
    )
    outputs["reasons"] = ", ".join(topology.reason_text(r) for r in topology._REASON_KEYS)
    outputs["estimate"] = lc.estimate_model_vram("m", {}, override_gb=8.375).detail
    try:
        residency.edit(b"models: {a: {ttl: 1}}\n", [])
    except residency.ResidencyError as e:
        outputs["flow_style"] = str(e)
    try:
        turn.PendingRequest("r1", frozenset(), "m")
    except ValueError as e:
        outputs["turn"] = str(e)
    return outputs


def test_the_b1c_outputs_in_english_have_no_spanish(tmp_path, monkeypatch, capsys):
    words = _distinctive_spanish_words()
    assert len(words) >= 100, "sin palabras distintivas el test no discrimina"
    _set_language(monkeypatch, "en")
    outputs = _outputs(tmp_path, capsys)
    # Guarda de «esto llegó a comprobar algo»: cada salida es la que se quería.
    assert "Verdict: resident: a; resident: b" in outputs["view"]
    assert "no resident (recommended)" in outputs["view_today"]
    assert "does not fit as a resident" in outputs["does_not_fit"]
    assert "there are 2 local-delegate delegations in progress" in outputs["refusals"]
    assert "there is 1 request in flight in llama-swap (m: 1)" in outputs["refusals"]
    assert "member a repeated in group g" in outputs["topology"]
    assert "flow-style node" in outputs["flow_style"]
    assert "request 'r1' without an acceptable set" in outputs["turn"]
    for name, out in outputs.items():
        assert not _spanish_in(out, words), f"{name}: {_spanish_in(out, words)}\n{out}"
        assert not _ACCENTS.search(out), f"{name}: {out}"


def test_the_same_outputs_in_spanish_do_trip_the_detector(tmp_path, monkeypatch, capsys):
    """Control positivo permanente: las mismas salidas en español sí tienen palabras distintivas."""
    words = _distinctive_spanish_words()
    _set_language(monkeypatch, "es")
    outputs = _outputs(tmp_path, capsys)
    tripped = [name for name, out in outputs.items() if _spanish_in(out, words)]
    # `estimate` y `reasons` pueden no tener palabras distintivas («GiB», «matrix»).
    assert len(tripped) >= len(outputs) - 2, tripped


@pytest.mark.parametrize(("lang", "expected"), [("es", "8,38 GiB"), ("en", "8.38 GiB")])
def test_gib_use_the_language_separators(lang, expected, monkeypatch):
    """REQ-026: la coma decimal en español y el punto en inglés, en el estimador y en `--pin`."""
    _set_language(monkeypatch, lang)
    assert lc.estimate_model_vram("m", {}, override_gb=8.375).detail.startswith(expected)
    assert f"{residency._gib(8.375)} GiB" == expected


@pytest.mark.parametrize(
    ("lang", "fits", "short"),
    [("es", "10,29 + 9,88", "faltan 6,17 GiB"), ("en", "10.29 + 9.88", "6.17 GiB short")],
)
def test_pin_that_does_not_fit_in_both_languages(lang, fits, short, tmp_path, monkeypatch):
    _set_language(monkeypatch, lang)
    with pytest.raises(residency.ResidencyError) as caught:
        loaded = residency.load(_copy(TODAY, tmp_path))
        residency.plan_pin(
            loaded.data,
            loaded.snapshot,
            "gemma4-26b-a4b",
            16.0,
            2.0,
            {"gemma4-26b-a4b": 10.29, "qwen36-35b-a3b": 9.88, "gemma3-4b": 3.19}
            | {"gemma4-12b": 8.85, "qwen35-2b": 3.5},
        )
    assert fits in str(caught.value) and short in str(caught.value)


@pytest.mark.parametrize("lang", ["es", "en"])
def test_machine_values_do_not_change_with_the_language(lang, monkeypatch):
    """Los motivos de REQ-002 y las salidas de la vigía son los mismos en cualquier idioma."""
    _set_language(monkeypatch, lang)
    assert topology.read(Path("does-not-matter.yaml")).reason in (
        topology.UNREADABLE,
        topology.NO_PYYAML,
    )
    assert topology.NO_CONFIG == "sin LLAMASWAP_CONFIG"
    assert checks._no_turn_is_fine(topology.NO_CONFIG)
    assert api.OUTCOMES == {"reloaded", "rejected", "not_watching", "down", "unresolved"}
    assert api.Status.from_json({"llamaswap": "ok"}).llamaswap == api.STATE_OK


@pytest.mark.parametrize(
    ("lang", "no_config", "unknown"),
    [("es", "sin LLAMASWAP_CONFIG", "otro motivo"), ("en", "no LLAMASWAP_CONFIG", "otro motivo")],
)
def test_reason_text_says_the_reason_in_the_language(lang, no_config, unknown, monkeypatch):
    _set_language(monkeypatch, lang)
    assert topology.reason_text(topology.NO_CONFIG) == no_config
    # Un motivo que no es de este módulo (el del backend remoto, de `server`) sale tal cual.
    assert topology.reason_text(unknown) == unknown


@pytest.mark.parametrize(("lang", "expected"), [("es", "recargó"), ("en", "reloaded")])
def test_outcome_text_in_both_languages(lang, expected, monkeypatch):
    _set_language(monkeypatch, lang)
    assert api.outcome_text(api.RELOADED) == expected


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("es", "corpus inválido: se esperaba"), ("en", "invalid corpus: expected")],
)
def test_benchmark_corpus_errors_in_both_languages(lang, expected, tmp_path, monkeypatch):
    _set_language(monkeypatch, lang)
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        benchmark.load_corpus(cases)


def test_benchmark_writes_machine_errors_in_the_jsonl():
    """`error` de una fila del JSONL es un valor de máquina, sin idioma (como `http_500`)."""

    class _Response:
        status_code = 200
        text = '{"choices": [{"message": "x"}]}'

        def json(self):
            return json.loads(self.text)

    class _Client:
        def post(self, url, json):
            return _Response()

    attempt = benchmark.post_attempt(_Client(), "http://unused", {})
    assert attempt.error == "unexpected_response: TypeError"


def test_doctor_says_the_reason_in_english(tmp_path, monkeypatch, capsys):
    """`doctor` dice los motivos de REQ-002 con `topology.reason_text`, no con el valor crudo."""
    from test_doctor_english import _doctor_output

    _code, out = _doctor_output(tmp_path, monkeypatch, capsys, "en", complete=True)
    assert "llama-swap residency: no LLAMASWAP_CONFIG in this shell" in out
    assert "no turn: no LLAMASWAP_CONFIG (according to" in out
