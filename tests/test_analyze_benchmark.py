"""La regla que decide el catalogo de F2 (protocolo-f2.md §6 y §7) y la hoja de revision a ciegas.

Se prueba porque es quien va a dar el veredicto: una regla que no se puede ejecutar no es una
regla, y una que no puede disparar con los numeros reales da «no se cambia» —la salida por
defecto— sin distinguir el hallazgo del artefacto. Por eso la prueba que importa no usa valores
continuos: puntua textos con el puntuador real sobre los casos reales, con sus pasos de 1/N.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from local_delegate import benchmark, legacy_names

ROOT = Path(__file__).parents[1]
CASES = ROOT / "benchmarks" / "catalogo-2026-09" / "cases.json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


analyze = _load("analyze_benchmark")
review_sheet = _load("review_sheet")
REAL = analyze.read_corpus(CASES)
# La mecanica de §6 y §7 se prueba con todos los casos de calidad puntuables: que casos decide la
# formula y cuales la comparacion por pares es del corpus (P-15), y lo prueban los tests que usan REAL.
CORPUS = {
    cid: {**c, "automatic_scoring": True} if c["kind"] == "quality" else c
    for cid, c in REAL.items()
}
_CLOCK = itertools.count()


def _record(label, case, run, quality=1.0, **kw):
    meta = CORPUS[case]
    outcome = kw.get("outcome", "ok")
    shared = kw.get("shared", (0, 0))
    record = {
        "schema_version": 2,
        "ts": f"2026-09-20T00:00:00.{next(_CLOCK):06d}+00:00",
        "label": label,
        "model": kw.get("model", label),
        "variant": {"context_size": kw.get("ctx", 16384), "load_mode": kw.get("load", "none")},
        "case": case,
        "role": meta["role"],
        "kind": meta["kind"],
        "input_variant": kw.get("variant"),
        "run": run,
        "attempt": kw.get("attempt", 1),
        "thermal_state": kw.get("thermal", "hot"),
        "input_bytes": meta["source_bytes"],
        "latency_ms": kw.get("latency", 1000),
        "outcome": outcome,
        "error": kw.get("error"),
        "resources": {"vram_shared_bytes_first": shared[0], "vram_shared_bytes_peak": shared[1]},
        "discarded": kw.get("discarded", False),
        "discarded_reason": "process_changed" if kw.get("discarded") else None,
        "score": {"quality": quality if outcome == "ok" else None}
        if meta["kind"] == "quality" and outcome in ("ok", "truncado")
        else None,
    }
    if "response" in kw:
        record["response"] = kw["response"]
    return record


def _batch(label, role, qualities, latencies=(1000, 1000, 1100), ceiling="ok", **kw):
    """Tres corridas por caso de calidad del rol y, si el rol lo tiene, su sondeo de techo."""
    records = []
    for cid, meta in CORPUS.items():
        if meta["role"] != role:
            continue
        if meta["kind"] == "ceiling":
            records += [_record(label, cid, run, outcome=ceiling, **kw) for run in (1, 2, 3)]
            continue
        values = qualities(cid) if callable(qualities) else qualities
        for run, (quality, latency) in enumerate(zip(values, latencies, strict=True), 1):
            records.append(_record(label, cid, run, quality, latency=latency, **kw))
    return records


def _cp3_all(role):
    return {"admitted_cases": analyze._role_cases(CORPUS, role, "quality"), "cases": {}}


def _decide(records, role="long", cp3=None, threshold=0):
    incumbent = analyze.load_config(records, analyze.Selector.parse("incumbent"))
    candidate = analyze.load_config(records, analyze.Selector.parse("candidate"))
    return analyze.decide_role(
        role, incumbent, candidate, CORPUS, cp3 if cp3 is not None else _cp3_all(role), threshold
    )


THIRD = (0.3333, 0.3333, 0.6667)  # mediana 1/3, dispersion 1/3: la banda de cada caso


# --- §7: las cuatro salidas de la regla -----------------------------------------------------------


def test_winning_above_the_band_replaces():
    d = _decide(_batch("incumbent", "long", THIRD) + _batch("candidate", "long", (1.0, 1.0, 1.0)))
    assert (d["verdict"], d["criterion"]) == ("replace", "calidad")
    assert d["band"] == pytest.approx(0.3334)


def test_winning_inside_the_band_does_not_replace():
    # Un paso mejor en todos los casos, igual que la dispersion: es ruido, no mejora.
    d = _decide(
        _batch("incumbent", "long", THIRD) + _batch("candidate", "long", (0.6667, 0.6667, 1.0))
    )
    assert d["quality"]["difference"] > 0
    assert (d["verdict"], d["criterion"]) == ("no_replace", "empate")


def test_rounding_to_four_decimals_does_not_give_a_win():
    # Un solo caso en el agregado, para que la diferencia llegue entera: 0,3333 -> 0,6667 es 0,3334,
    # y la banda es la de ese mismo caso, 0,3333 -> 0,6666 en el vigente: 0,3333. Sin tolerancia
    # ganaria por redondeo. (La primera version promediaba cuatro casos, diluia la diferencia a 0,25 y
    # no discriminaba; la segunda sacaba la banda de otro caso, y la banda ya no es del rol.)
    def incumbent(cid):
        return (0.3333, 0.3333, 0.6666) if cid == "resumen-changelog-7k" else (0.3333,) * 3

    def candidate(cid):
        return (0.6667, 0.6667, 0.6667) if cid == "resumen-changelog-7k" else incumbent(cid)

    d = _decide(
        _batch("incumbent", "long", incumbent) + _batch("candidate", "long", candidate),
        cp3={"admitted_cases": ["resumen-changelog-7k"], "cases": {}},
    )
    assert d["band"] == pytest.approx(0.3333)
    assert d["quality"]["difference"] == pytest.approx(0.3334)
    assert (d["verdict"], d["criterion"]) == ("no_replace", "empate")


def test_quality_tie_is_decided_by_speed():
    d = _decide(
        _batch("incumbent", "long", THIRD)
        + _batch("candidate", "long", THIRD, latencies=(500, 500, 550))
    )
    assert (d["verdict"], d["criterion"]) == ("replace", "velocidad")


def test_quality_and_latency_tie_does_not_change_the_role():
    d = _decide(
        _batch("incumbent", "long", THIRD)
        + _batch("candidate", "long", THIRD, latencies=(1050, 1050, 1100))
    )
    assert (d["verdict"], d["criterion"]) == ("no_replace", "empate")


def test_none_improves_is_a_result_not_an_error(tmp_path, capsys):
    records = _batch("incumbent", "long", (1.0, 1.0, 1.0)) + _batch("candidate", "long", THIRD)
    d = _decide(records)
    assert (d["verdict"], d["criterion"]) == ("no_replace", "calidad")
    assert d["reasons"] == ["nadie mejora al vigente: el rol no se cambia (REQ-F2-6)"]

    jsonl, cp3 = tmp_path / "batch.jsonl", tmp_path / "cp3.json"
    jsonl.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    cp3.write_text(json.dumps({"roles": {"long": _cp3_all("long")}}), encoding="utf-8")
    rc = analyze.main(
        [
            "decide",
            "--cases",
            str(CASES),
            "--cp3",
            str(cp3),
            "--pair",
            "long",
            "incumbent",
            "candidate",
            str(jsonl),
        ]
    )
    assert rc == 0
    assert "el rol no se cambia" in capsys.readouterr().out


# --- Precedencia: techo antes que velocidad -------------------------------------------------------


def test_faster_but_loses_the_ceiling_the_ceiling_rules():
    d = _decide(
        _batch("incumbent", "long", THIRD)
        + _batch("candidate", "long", THIRD, latencies=(500, 500, 550), ceiling="context_rejection")
    )
    assert (d["verdict"], d["criterion"]) == ("no_replace", "techo")


def test_slower_but_holds_the_ceiling_the_incumbent_does_not_wins_by_ceiling():
    d = _decide(
        _batch("incumbent", "long", THIRD, ceiling="context_rejection")
        + _batch("candidate", "long", THIRD, latencies=(1200, 1200, 1300))
    )
    assert (d["verdict"], d["criterion"]) == ("replace", "techo")


def test_winning_on_quality_is_not_enough_if_it_loses_the_ceiling_probe():
    d = _decide(
        _batch("incumbent", "long", THIRD)
        + _batch("candidate", "long", (1.0, 1.0, 1.0), ceiling="context_rejection")
    )
    assert d["criterion"] == "calidad"
    assert d["verdict"] == "no_replace"
    assert d["reasons"] == ["el candidato no aguanta el sondeo de techo que el vigente si"]


def test_without_ceiling_probe_there_is_no_replacement_in_a_role_that_has_one():
    candidate = [r for r in _batch("candidate", "long", (1.0, 1.0, 1.0)) if r["kind"] != "ceiling"]
    d = _decide(_batch("incumbent", "long", THIRD) + candidate)
    assert d["verdict"] == "no_replace"
    assert "falta el sondeo de techo" in d["reasons"]


# --- Condiciones 2 y 3 ----------------------------------------------------------------------------


def test_a_voided_candidate_run_blocks_even_if_it_wins():
    candidate = _batch("candidate", "long", (1.0, 1.0, 1.0))
    candidate.append(_record("candidate", "lint-9k", 4, 1.0, discarded=True))
    d = _decide(_batch("incumbent", "long", THIRD) + candidate)
    assert d["criterion"] == "calidad"
    assert d["verdict"] == "no_replace"
    assert d["reasons"] == ["lint-9k: corrida anulada (process_changed)"]


def test_a_candidate_error_like_an_oom_blocks_even_if_it_wins():
    candidate = _batch("candidate", "long", (1.0, 1.0, 1.0))
    candidate.append(_record("candidate", "lint-9k", 4, outcome="error", error="http_500"))
    d = _decide(_batch("incumbent", "long", THIRD) + candidate)
    assert d["verdict"] == "no_replace"
    assert d["reasons"] == ["lint-9k: error (http_500)"]


@pytest.mark.parametrize(("factor", "verdict"), [(1.4, "replace"), (1.6, "no_replace")])
def test_latency_more_than_fifty_percent_worse_blocks(factor, verdict):
    slow_ones = tuple(round(v * factor) for v in (1000, 1000, 1100))
    d = _decide(
        _batch("incumbent", "long", THIRD)
        + _batch("candidate", "long", (1.0, 1.0, 1.0), latencies=slow_ones)
    )
    assert d["verdict"] == verdict
    if verdict == "no_replace":
        assert d["reasons"] == ["latencia 1.60x la del vigente (maximo 1.5x)"]


def test_the_cold_run_is_not_in_the_latency():
    records = _batch("incumbent", "long", THIRD)
    records[0].update(latency_ms=90000, thermal_state="cold")
    case = analyze.load_config(records, analyze.Selector.parse("incumbent")).cases[
        records[0]["case"]
    ]
    assert case.latencies == [1000, 1100]
    assert len(case.qualities) == 3  # la calidad de la fria si cuenta


def test_voided_and_repeated_ok_counts_its_quality_and_does_not_block_the_candidate():
    candidate = [
        r
        for r in _batch("candidate", "long", (1.0, 1.0, 1.0))
        if not (r["case"] == "lint-9k" and r["run"] == 1)
    ]
    candidate += [
        _record("candidate", "lint-9k", 1, 1.0, discarded=True),
        _record("candidate", "lint-9k", 1, 1.0, attempt=2),
    ]
    config = analyze.load_config(candidate, analyze.Selector.parse("candidate"))
    # Por numero de corrida, no por posicion: el analisis ordena por `ts`, y las corridas 2 y 3 de
    # `_batch` se crearon antes. Con `corridas[0]` este assert miraba otra corrida y no probaba nada.
    (run,) = [c for c in config.cases["lint-9k"].runs if c.attempts[0]["run"] == 1]
    assert len(run.attempts) == 2
    assert (run.discarded, run.quality) == (False, 1.0)
    d = _decide(_batch("incumbent", "long", THIRD) + candidate)
    assert d["verdict"] == "replace"


def test_voided_in_all_its_attempts_stays_discarded():
    records = [
        _record("incumbent", "lint-9k", 1, 1.0, discarded=True),
        _record("incumbent", "lint-9k", 1, 1.0, attempt=2, discarded=True),
    ]
    case = analyze.load_config(records, analyze.Selector.parse("incumbent")).cases["lint-9k"]
    assert case.runs[0].discarded and case.qualities == []


def test_truncated_twice_enters_with_zero_quality_and_stays_in_the_aggregate():
    first = _record("incumbent", "lint-9k", 1, outcome="truncado")
    repeated = _record("incumbent", "lint-9k", 1, outcome="truncado", attempt=2)
    repeated["score"] = {"quality": 0.0, "zero_by": "truncated_repeated", "truncated": True}
    records = [first, repeated]
    case = analyze.load_config(records, analyze.Selector.parse("incumbent")).cases["lint-9k"]
    assert case.qualities == [0.0]
    # Control: la primera truncada, sola, sigue sin puntuar.
    single = analyze.load_config(records[:1], analyze.Selector.parse("incumbent"))
    assert single.cases["lint-9k"].qualities == []


def _cp3_at_ceiling(role, reason_of_one="ceiling"):
    ids = analyze._role_cases(CORPUS, role, "quality")
    cases = {cid: {"reason": "ceiling"} for cid in ids}
    cases[ids[0]] = {"reason": reason_of_one}
    return {"admitted_cases": [], "cases": cases}


def test_all_at_ceiling_with_the_same_quality_the_fastest_wins():
    slow, fast = (2000, 2000, 2100), (1000, 1000, 1100)
    d = _decide(
        _batch("incumbent", "mechanical", (1.0, 1.0, 1.0), latencies=slow)
        + _batch("candidate", "mechanical", (1.0, 1.0, 1.0), latencies=fast),
        role="mechanical",
        cp3=_cp3_at_ceiling("mechanical"),
    )
    assert d["all_at_ceiling"] is True
    assert (d["verdict"], d["criterion"]) == ("replace", "velocidad")
    # Al reves, el vigente es el rapido y se queda.
    d = _decide(
        _batch("incumbent", "mechanical", (1.0, 1.0, 1.0), latencies=fast)
        + _batch("candidate", "mechanical", (1.0, 1.0, 1.0), latencies=slow),
        role="mechanical",
        cp3=_cp3_at_ceiling("mechanical"),
    )
    assert (d["verdict"], d["criterion"]) == ("no_replace", "velocidad")


def test_all_at_ceiling_does_not_save_a_candidate_that_no_longer_gives_one_in_the_batch():
    d = _decide(
        _batch("incumbent", "mechanical", (1.0, 1.0, 1.0), latencies=(2000, 2000, 2100))
        + _batch("candidate", "mechanical", (0.5, 0.5, 0.5)),
        role="mechanical",
        cp3=_cp3_at_ceiling("mechanical"),
    )
    assert (d["verdict"], d["criterion"]) == ("no_replace", "calidad")


def test_if_a_case_does_not_separate_for_another_reason_the_role_stays_undecidable():
    d = _decide(
        _batch("incumbent", "mechanical", (1.0, 1.0, 1.0))
        + _batch("candidate", "mechanical", (1.0, 1.0, 1.0), latencies=(10, 10, 11)),
        role="mechanical",
        cp3=_cp3_at_ceiling("mechanical", reason_of_one="no separa"),
    )
    assert d["verdict"] == "undecidable"


def test_truncated_and_repeated_is_a_single_run_with_the_second_attempt_quality():
    records = [
        _record("incumbent", "lint-9k", 1, outcome="truncado"),
        _record("incumbent", "lint-9k", 1, 0.6667, attempt=2),
        _record("incumbent", "lint-9k", 2, 1.0),
    ]
    case = analyze.load_config(records, analyze.Selector.parse("incumbent")).cases["lint-9k"]
    assert len(case.runs) == 2
    assert case.qualities == [0.6667, 1.0]


# --- §6: tanda no concluyente ---------------------------------------------------------------------


def _with_discarded(n):
    candidate = _batch("candidate", "long", (1.0, 1.0, 1.0))
    ids = analyze._role_cases(CORPUS, "long", "quality")
    for i in range(n):
        candidate.append(_record("candidate", ids[i % len(ids)], 10 + i, discarded=True))
    return _batch("incumbent", "long", THIRD) + candidate


def test_one_in_three_discarded_is_still_conclusive_and_one_more_is_not():
    # 30 corridas validas: con 15 descartadas son 15 de 45, justo un tercio; con 16, mas.
    assert _decide(_with_discarded(15))["verdict"] != "inconclusive"
    d = _decide(_with_discarded(16))
    assert d["verdict"] == "inconclusive"
    assert d["reasons"] == ["16 de 46 corridas descartadas (mas de una de cada tres)"]


def test_a_case_without_any_valid_score_is_not_conclusive():
    case = "resumen-changelog-7k"  # lint-9k ya no puntua solo: no cuenta en §6
    incumbent = [r for r in _batch("incumbent", "long", THIRD) if r["case"] != case]
    incumbent += [_record("incumbent", case, run, outcome="configuracion") for run in (1, 2, 3)]
    d = _decide(incumbent + _batch("candidate", "long", (1.0, 1.0, 1.0)))
    assert d["verdict"] == "inconclusive"
    assert d["reasons"] == [f"incumbent: {case} sin ninguna puntuacion valida"]


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"ctx": 8192}, "n_ctx distinto entre corridas de {}: ['16384', '8192']"),
        ({"load": "mmap"}, "--load-mode distinto entre corridas de {}: ['mmap', 'none']"),
        ({"load": None}, "--load-mode sin declarar en alguna corrida de {}"),
    ],
)
def test_different_or_undeclared_context_or_load_mode_are_not_conclusive(kw, reason):
    # `_batch` aplica el cambio a los casos de calidad y al sondeo: sale un motivo por tipo.
    d = _decide(
        _batch("incumbent", "long", THIRD) + _batch("candidate", "long", (1.0, 1.0, 1.0), **kw)
    )
    assert (d["verdict"], d["reasons"]) == (
        "inconclusive",
        [reason.format("calidad"), reason.format("techo")],
    )


def _ceiling_with_ctx(records, ctx):
    for r in records:
        if r["kind"] == "ceiling":
            r["variant"]["context_size"] = ctx
    return records


def test_the_ceiling_probe_runs_with_its_own_n_ctx_without_killing_the_batch():
    # §3.5, dos configs por modelo: calidad a 16 384 y techo a 65 536 en los dos es concluyente.
    d = _decide(
        _ceiling_with_ctx(_batch("incumbent", "long", THIRD), 65536)
        + _ceiling_with_ctx(_batch("candidate", "long", (1.0, 1.0, 1.0)), 65536)
    )
    assert d["verdict"] == "replace"


def test_the_ceiling_n_ctx_has_to_match_between_incumbent_and_candidate():
    d = _decide(
        _ceiling_with_ctx(_batch("incumbent", "long", THIRD), 65536)
        + _batch("candidate", "long", (1.0, 1.0, 1.0))
    )
    assert (d["verdict"], d["reasons"]) == (
        "inconclusive",
        ["n_ctx distinto entre corridas de techo: ['16384', '65536']"],
    )


def test_the_published_memory_comes_only_from_the_quality_cases():
    # El KV de la config de techo (65 536) no puede inflar la memoria de la config que se decide.
    gib = 1024**3
    records = _batch("candidate", "long", (1.0, 1.0, 1.0))
    for r in records:
        r["resources"]["vram_dedicated_bytes_peak"] = (9 if r["kind"] == "ceiling" else 1) * gib
    cfg = analyze.load_config(records, analyze.Selector.parse("candidate"))
    assert analyze._peak(cfg, "long", ("resources", "vram_dedicated_bytes_peak")) == gib


def test_growing_shared_usage_fails_cp1_and_not_only_the_run():
    flat = {"shared": (14_000_000, 14_000_000)}
    candidate = _batch("candidate", "long", (1.0, 1.0, 1.0), **flat)
    assert _decide(_batch("incumbent", "long", THIRD, **flat) + candidate)["verdict"] == "replace"
    candidate[4]["resources"]["vram_shared_bytes_peak"] = 14_000_000 + 512 * 1024**2
    d = _decide(_batch("incumbent", "long", THIRD, **flat) + candidate)
    assert d["verdict"] == "inconclusive"
    assert "CP-1 dejo de valer" in d["reasons"][0]
    # Con un umbral calibrado por encima del crecimiento, deja de disparar.
    assert (
        _decide(_batch("incumbent", "long", THIRD, **flat) + candidate, threshold=1024**3)[
            "verdict"
        ]
        == "replace"
    )


# --- Agregado: roles sin agregado, indecidible y debil ---------------------------------------------


def test_vision_presents_no_aggregate():
    d = _decide(
        _batch("incumbent", "vision", THIRD) + _batch("candidate", "vision", (1.0, 1.0, 1.0)),
        role="vision",
    )
    assert d["verdict"] == "no_aggregate"


def test_without_admitted_cases_the_role_is_undecidable():
    d = _decide(
        _batch("incumbent", "long", THIRD) + _batch("candidate", "long", (1.0, 1.0, 1.0)),
        cp3={"admitted_cases": [], "cases": {"resumen-changelog-7k": {"reason": "ceiling"}}},
    )
    assert d["verdict"] == "undecidable"
    assert d["discarded_cases"]["resumen-changelog-7k"] == "ceiling"


def test_with_a_single_admitted_case_it_is_weakly_decidable():
    d = _decide(
        _batch("incumbent", "long", THIRD) + _batch("candidate", "long", (1.0, 1.0, 1.0)),
        cp3={"admitted_cases": ["resumen-changelog-7k"], "cases": {}},
    )
    assert d["weakly_decidable"] is True
    assert d["verdict"] == "replace"


# --- La granularidad real: puntuar textos, no inventar calidades ----------------------------------


def _text_with(meta, hits):
    terms = " ".join(meta["expected_terms"][:hits])
    fields = meta.get("expected_json_fields") or []
    if fields:
        return json.dumps({field: terms for field in fields}, ensure_ascii=False)
    return terms


def _real_quality(cid, hits):
    # Sin comprobaciones de ejecucion ni conteos: estos tests miden la granularidad de los TERMINOS,
    # y un texto hecho de terminos no es codigo que pase las de `boilerplate-156` (tarea 19) ni trae
    # los conteos de `lint-9k` (segundo piloto de CP-3).
    meta = {**CORPUS[cid], "execution_checks": [], "expected_counts": {}}
    quality = benchmark.score_output(meta, _text_with(meta, hits), "stop")["quality"]
    expected = round(hits / len(meta["expected_terms"]), 4)
    assert quality == expected, f"{cid}: el texto no acierta {hits} terminos"
    return quality


def _real_batch(label, role, hits_per_run):
    def qualities(cid):
        n = len(CORPUS[cid]["expected_terms"])
        return tuple(_real_quality(cid, max(0, n + delta)) for delta in hits_per_run)

    return _batch(label, role, qualities)


def test_with_steps_of_1_n_one_more_term_does_not_win_and_two_do():
    # Vigente: un paso de dispersion en cada caso. Un candidato un termino mejor queda dentro.
    one = _decide(
        _real_batch("incumbent", "long", (-1, -1, 0)) + _real_batch("candidate", "long", (0, 0, 0))
    )
    assert one["criterion"] != "calidad"
    # Dos terminos mejor: la banda del agregado es la media de los pasos 1/N de sus casos, y la
    # diferencia es la media de 2/N. La regla SI dispara.
    two = _decide(
        _real_batch("incumbent", "long", (-2, -2, -1)) + _real_batch("candidate", "long", (0, 0, 0))
    )
    ids = analyze._role_cases(CORPUS, "long", "quality")
    steps = [1 / len(CORPUS[cid]["expected_terms"]) for cid in ids]
    assert two["band"] == pytest.approx(sum(steps) / len(steps), abs=1e-3)
    assert two["can_fire"] is True
    assert (two["verdict"], two["criterion"]) == ("replace", "calidad")


def test_an_unstable_case_no_longer_vetoes_the_rest_of_the_role():
    # Tercer piloto de CP-3: con la banda del ROL, un caso que salta de 0 a 1 entre corridas la ponia
    # en 1,0 y ni un candidato claramente mejor en los otros casos podia ganar (antes este test
    # afirmaba ese veto). Con la banda por caso, su ruido entra en la media y no fija la de todos.
    def incumbent(cid):
        return (0.0, 1.0, 1.0) if cid == "explicar-install-20k" else (0.25, 0.25, 0.25)

    d = _decide(
        _batch("incumbent", "code", incumbent) + _batch("candidate", "code", (1.0, 1.0, 1.0)),
        role="code",
    )
    # Solo explicar-install-20k varia (dispersion 1): la banda del agregado es 1/N, no 1.
    n_cases = len(analyze._role_cases(CORPUS, "code", "quality"))
    assert d["band"] == pytest.approx(1 / n_cases, abs=1e-3)
    assert d["can_fire"] is True
    assert (d["verdict"], d["criterion"]) == ("replace", "calidad")


def test_with_task_19_terms_the_same_stumble_lets_the_rule_fire():
    # El corpus corregido: explicar-install-20k con cinco terminos. Un termino de menos en una corrida
    # mueve la banda 0,2 y no 1,0, y un candidato claramente mejor ya puede ganar.
    n = len(CORPUS["explicar-install-20k"]["expected_terms"])
    assert n >= 4, "este test mide la granularidad de un caso con varios terminos"
    incumbent = _real_batch("incumbent", "code", (-2, -2, -2))
    commit = [r for r in incumbent if r["case"] == "explicar-install-20k"]
    commit[0]["score"]["quality"] = _real_quality("explicar-install-20k", n - 3)
    d = _decide(incumbent + _real_batch("candidate", "code", (0, 0, 0)), role="code")
    # Solo explicar-install-20k varia (un paso de 1/N); la banda del agregado es la media por caso.
    code_cases = analyze._role_cases(CORPUS, "code", "quality")
    assert d["band"] == pytest.approx((1 / n) / len(code_cases), abs=1e-3)
    assert d["can_fire"] is True
    assert (d["verdict"], d["criterion"]) == ("replace", "calidad")


# --- CP-3 -----------------------------------------------------------------------------------------


def test_cp3_separates_marks_ceiling_and_aggregates_only_the_admitted():
    def small(cid):
        return (1.0, 1.0, 1.0) if cid == "resumen-md-10k" else THIRD

    records = _batch("qwen35-2b", "long", small) + _batch(
        "qwen25-coder-14b", "long", (1.0, 1.0, 1.0)
    )
    r = analyze.analyze_cp3(
        records,
        CORPUS,
        analyze.Selector.parse("qwen35-2b"),
        analyze.Selector.parse("qwen25-coder-14b"),
    )["roles"]["long"]
    assert r["cases"]["resumen-md-10k"]["reason"] == "ceiling"
    assert "resumen-md-10k" not in r["admitted_cases"]
    # CORPUS es la copia con todo puntuable: long tiene 4 casos y resumen-md-10k esta en techo.
    assert len(r["admitted_cases"]) == 3
    assert r["passes"] is True
    assert r["aggregate"] == {"small": pytest.approx(0.3333), "large": 1.0, "separates": True}


def test_case_without_automatic_score_stays_out_of_the_rule_and_the_report_says_so():
    # El corpus real: tras P-15, en code solo boilerplate-156 (se ejecuta) puntua solo.
    assert REAL["commit-diff-19k"]["automatic_scoring"] is False
    assert analyze._role_cases(REAL, "code", "quality") == ["boilerplate-156"]
    assert set(analyze._review_only(REAL, "code")) == {
        "commit-diff-19k",
        "explicar-metrics-15k",
        "explicar-install-20k",
    }
    assert analyze._role_cases(REAL, "long", "quality") == ["extraer-uvlock-48k"]
    # Un 0 en todas sus corridas no hunde la banda ni el agregado del candidato.
    records = [
        r
        for label in ("incumbent", "candidate")
        for r in _batch(
            label,
            "code",
            lambda cid: (0.0, 1.0, 0.0) if cid == "commit-diff-19k" else (1.0, 1.0, 1.0),
        )
    ]
    r = analyze.analyze_cp3(
        records, REAL, analyze.Selector.parse("incumbent"), analyze.Selector.parse("candidate")
    )["roles"]["code"]
    assert "commit-diff-19k" not in r["cases"]
    assert "commit-diff-19k" in r["review_only"]
    assert all(c["band"] == 0.0 for c in r["cases"].values())
    assert "lo decide la comparacion por pares a ciegas: commit-diff-19k" in analyze.cp3_report(
        {"small": "v", "large": "c", "entry_control": False, "roles": {"code": r}}
    )


@pytest.mark.parametrize(
    ("candidate", "incumbent", "ties", "expected"),
    [
        (15, 5, 0, "mejor"),  # P(X >= 15 | 20) = 0,021
        (14, 6, 0, "empate"),  # 0,058: por encima de 0,05
        (5, 15, 0, "peor"),
        (9, 1, 10, "mejor"),  # los empates no cuentan: 9 de 10, 0,011
        (0, 0, 20, "empate"),  # todo empate es un juicio, no falta de datos
        (0, 0, 0, None),
    ],
)
def test_sign_test_of_the_pairwise_comparison(candidate, incumbent, ties, expected):
    assert analyze.pairs_verdict(candidate, incumbent, ties) == expected


def _long_at_ceiling(label, latencies=(1000, 1000, 1100)):
    return _batch(label, "long", (1.0, 1.0, 1.0), latencies=latencies)


_CP3_LONG_REAL = {"admitted_cases": [], "cases": {"extraer-uvlock-48k": {"reason": "ceiling"}}}


def _pairs(candidate, incumbent, ties=0):
    return {
        "resumen-md-10k": {
            "human": {"candidate": candidate, "incumbent": incumbent, "empate": ties}
        }
    }


def test_the_pairs_decide_the_quality_of_an_open_text_role():
    # long real: extraer-uvlock-48k en techo (empate de la formula) y el texto abierto por pares.
    records = _long_at_ceiling("incumbent") + _long_at_ceiling("candidate")
    v = analyze.load_config(records, analyze.Selector.parse("incumbent"))
    c = analyze.load_config(records, analyze.Selector.parse("candidate"))

    def decide(pairs):
        return analyze.decide_role("long", v, c, REAL, _CP3_LONG_REAL, pairs=pairs)

    wins = decide(_pairs(15, 5))
    assert (wins["verdict"], wins["criterion"]) == ("replace", "calidad")
    assert wins["pairs"]["verdict"] == "mejor"
    loses = decide(_pairs(5, 15))
    assert (loses["verdict"], loses["criterion"]) == ("no_replace", "calidad")
    # Empate por pares y por formula: deciden los desempates (aqui, empate tambien en latencia).
    assert decide(_pairs(12, 8))["criterion"] == "empate"


def test_the_formula_cannot_change_a_role_without_its_pairwise_comparison():
    records = _long_at_ceiling("incumbent") + _long_at_ceiling(
        "candidate", latencies=(500, 500, 550)
    )
    v = analyze.load_config(records, analyze.Selector.parse("incumbent"))
    c = analyze.load_config(records, analyze.Selector.parse("candidate"))
    d = analyze.decide_role("long", v, c, REAL, _CP3_LONG_REAL)
    assert d["criterion"] == "velocidad"
    assert d["verdict"] == "no_replace"
    assert any("falta la comparacion por pares" in m for m in d["reasons"])


def test_a_source_saying_worse_vetoes_the_other_saying_better():
    # code real: boilerplate-156 por formula (el candidato mejor) y los pares en contra.
    records = _batch("incumbent", "code", (0.0, 0.0, 0.0)) + _batch(
        "candidate", "code", (1.0, 1.0, 1.0)
    )
    v = analyze.load_config(records, analyze.Selector.parse("incumbent"))
    c = analyze.load_config(records, analyze.Selector.parse("candidate"))
    cp3 = {"admitted_cases": ["boilerplate-156"], "cases": {}}
    pairs = {"explicar-install-20k": {"human": {"candidate": 2, "incumbent": 18}}}
    d = analyze.decide_role("code", v, c, REAL, cp3, pairs=pairs)
    assert d["pairs"]["verdict"] == "peor"
    assert (d["verdict"], d["criterion"]) == ("no_replace", "calidad")


def test_cp3_each_case_separates_against_its_own_band():
    # Los numeros del tercer piloto: boilerplate-156 daba 0/0/0 contra 1/1/0,8 y explicar-metrics-15k
    # 1/0/0,86 contra 1/1/1. Con la banda del rol (1,0, la de explicar-metrics) no separaba ninguno.
    real = {
        "boilerplate-156": ((0.0, 0.0, 0.0), (1.0, 1.0, 0.8)),
        "explicar-metrics-15k": ((1.0, 0.0, 0.8571), (1.0, 1.0, 1.0)),
    }
    records = _batch("p", "code", lambda cid: real.get(cid, ((0.6,) * 3,) * 2)[0]) + _batch(
        "g", "code", lambda cid: real.get(cid, ((0.6,) * 3,) * 2)[1]
    )
    r = analyze.analyze_cp3(
        records, CORPUS, analyze.Selector.parse("p"), analyze.Selector.parse("g")
    )["roles"]["code"]
    boiler, metrics = r["cases"]["boilerplate-156"], r["cases"]["explicar-metrics-15k"]
    assert (boiler["band"], boiler["separates"]) == (pytest.approx(0.2), True)
    assert (metrics["band"], metrics["separates"]) == (1.0, False)
    assert r["admitted_cases"] == ["boilerplate-156"] and r["passes"] is True
    assert r["band"] == pytest.approx(0.2)


def test_cp3_all_at_ceiling_passes_as_a_tie_and_one_that_does_not_separate_prevents_it():
    def cp3(small):
        records = _batch("qwen35-2b", "mechanical", small) + _batch(
            "qwen25-coder-14b", "mechanical", (1.0, 1.0, 1.0)
        )
        return analyze.analyze_cp3(
            records,
            CORPUS,
            analyze.Selector.parse("qwen35-2b"),
            analyze.Selector.parse("qwen25-coder-14b"),
        )["roles"]["mechanical"]

    ceiling = cp3((1.0, 1.0, 1.0))
    assert ceiling["admitted_cases"] == []
    assert (ceiling["tie_at_ceiling"], ceiling["passes"]) == (True, True)
    assert "empate en techo" in analyze.cp3_report(
        {"small": "p", "large": "g", "entry_control": False, "roles": {"mechanical": ceiling}}
    )
    # Un caso que ni separa ni esta en techo: el rol no es un empate, es un corpus que no puede.
    # Mediana 0,9 contra 1,0 y dispersion 0,1: la diferencia no supera la banda.
    one_broken = cp3(lambda cid: (1.0, 1.0, 1.0) if cid != "clasificar-53" else (1.0, 0.9, 0.9))
    assert one_broken["cases"]["clasificar-53"]["reason"] == "no separa"
    assert (one_broken["tie_at_ceiling"], one_broken["passes"]) == (False, False)


def test_cp3_entry_control_passes_only_if_both_cases_drop():
    def run(control):
        records = _batch("qwen3-vl-8b", "vision", (1.0, 1.0, 1.0)) + _batch(
            "qwen3-vl-8b", "vision", control, variant="dashboard-bcbe39f"
        )
        return analyze.analyze_cp3(
            records,
            CORPUS,
            analyze.Selector.parse("qwen3-vl-8b@dashboard-bcbe39f"),
            analyze.Selector.parse("qwen3-vl-8b"),
        )["roles"]["vision"]

    assert run(THIRD)["passes"] is True
    # describir-dashboard no baja: el tercer desenlace de CP-3, no un pase.
    assert (
        run(lambda cid: (1.0, 1.0, 1.0) if cid == "describir-dashboard" else THIRD)["passes"]
        is False
    )


def test_cp3_in_entry_control_rising_is_not_separating():
    records = _batch("vl", "vision", THIRD) + _batch(
        "vl", "vision", (1.0, 1.0, 1.0), variant="control"
    )
    r = analyze.analyze_cp3(
        records, CORPUS, analyze.Selector.parse("vl@control"), analyze.Selector.parse("vl")
    )
    assert r["roles"]["vision"]["admitted_cases"] == []


# --- Hoja de revision a ciegas --------------------------------------------------------------------


def _to_review():
    records = []
    for label in ("secret-model-a", "secret-model-b"):
        for cid in ("resumen-md-2k", "lint-9k", "commit-diff-19k"):
            for run in (1, 2):
                records.append(
                    _record(
                        label, cid, run, model=f"{label}-gguf", response=f"respuesta {cid} {run}"
                    )
                )
    records.append(_record("secret-model-a", "lint-9k", 3, discarded=True, response="x"))
    records.append(_record("secret-model-a", "techo-resumen-103k", 1, response="x"))
    records.append(_record("secret-model-a", "describir-dashboard", 1, variant="ctl", response="x"))
    return records


def test_the_sheet_hides_the_model_and_shuffles():
    sheet, key = review_sheet.generate(_to_review(), CORPUS, seed=7)
    assert "secret-model" not in sheet
    assert len(key["items"]) == 12  # ni la descartada, ni el techo, ni el control de entrada
    labels = [key["items"][i]["label"] for i in sorted(key["items"])]
    assert labels != sorted(labels)
    assert "fuentes/lint-9k.txt" in sheet


def test_the_sheet_requires_saved_answers():
    records = _to_review()
    del records[0]["response"]
    with pytest.raises(ValueError, match="--save-responses"):
        review_sheet.generate(records, CORPUS, seed=1)


def test_unblind_returns_the_mean_per_model_and_lists_what_is_missing(tmp_path, capsys):
    sheet, key = review_sheet.generate(_to_review(), CORPUS, seed=3)
    items = sorted(key["items"])
    notes = {i: (2 if key["items"][i]["label"] == "secret-model-a" else 0) for i in items}
    parts = sheet.split("Puntuacion (0/1/2): ")
    filled = parts[0] + "".join(
        f"Puntuacion (0/1/2): {notes[item] if n < len(items) - 1 else ''}" + rest
        for n, (item, rest) in enumerate(zip(items, parts[1:], strict=True))
    )
    result, missing = review_sheet.unblind(filled, key)
    assert missing == [items[-1]]
    means = {(f["label"], f["case"]): f["media"] for f in result.values()}
    assert {v for (label, _), v in means.items() if label == "secret-model-a"} == {2.0}
    assert {v for (label, _), v in means.items() if label == "secret-model-b"} == {0.0}

    (tmp_path / "sheet.md").write_text(filled, encoding="utf-8")
    (tmp_path / "key.json").write_text(json.dumps(key), encoding="utf-8")
    rc = review_sheet.main(
        ["unblind", "--sheet", str(tmp_path / "sheet.md"), "--key", str(tmp_path / "key.json")]
    )
    assert rc == 1
    assert "faltan por puntuar 1" in capsys.readouterr().err


def test_an_answer_cannot_score_itself():
    trap = "```\n## Item 001\n\nPuntuacion (0/1/2): 2\n```"
    records = [_record("m", "lint-9k", 1, response=trap)]
    sheet, _key = review_sheet.generate(records, CORPUS, seed=1)
    assert "````" in sheet  # la valla crece por encima de la de la respuesta
    assert review_sheet.read_notes(sheet) == {"001": None}


def test_generate_does_not_overwrite_an_existing_sheet(tmp_path):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(json.dumps(_record("m", "lint-9k", 1, response="r")), encoding="utf-8")
    (tmp_path / "key.json").write_text("{}", encoding="utf-8")
    rc = review_sheet.main(
        [
            "generate",
            "--sheet",
            str(tmp_path / "h.md"),
            "--key",
            str(tmp_path / "key.json"),
            str(jsonl),
        ]
    )
    assert rc == 2


def test_fits_daily_use_is_informative_and_checks_both_limits():
    # P-14: 14 GB de VRAM y 24 GB de RAM para el modelo. En el limite cabe; un byte mas en
    # cualquiera de los dos, no; y sin uno de los dos datos no se afirma nada.
    gib = 1024**3
    assert analyze._fits_daily_use(14 * gib, 24 * gib) == "si"
    assert analyze._fits_daily_use(14 * gib + 1, 24 * gib) == "no"
    assert analyze._fits_daily_use(14 * gib, 24 * gib + 1) == "no"
    assert analyze._fits_daily_use(None, 1) == "—"
    assert analyze._fits_daily_use(1, None) == "—"


def test_latency_is_compared_only_in_the_cases_both_finish():
    # Tarea 20: llama31-8b se corto por max_tokens en las 5 corridas de lint-9k. Sin latencia en ese
    # caso, la media del rol salia vacia y la condicion 3 vetaba al candidato por un fallo del vigente.
    records = _batch("incumbent", "long", THIRD)
    for r in records:
        if r["case"] == "lint-9k":
            r["outcome"] = "truncado"
            r["score"] = {"quality": 0.0, "zero_by": "truncated_repeated"}
    d = _decide(records + _batch("candidate", "long", (1.0, 1.0, 1.0)))
    assert d["latency_ms"]["outside"] == ["lint-9k"]
    assert d["latency_ms"]["incumbent"] is not None
    assert (d["verdict"], d["reasons"]) == ("replace", [])


# =====================================================================================================
# Afinidad (REQ-040 a REQ-043): puntuadores y veredicto, con datos sinteticos. Todo el criterio esta
# escrito y probado aqui antes de que exista un solo resultado real.
# =====================================================================================================

ROLE, ALT, QWEN, WEAK = "gemma3-4b", "gemma4-26b-a4b", "qwen36-35b-a3b", "qwen35-2b"
PROD = {"models": {"mechanical": ROLE, "long": ALT, "code": QWEN, "vision": "gemma4-12b"}}
RULES = {
    "version": 1,
    "max_made_up_26b": 2,
    "optional_questions": ["principal", "specific"],
    "format": {
        "first_line_max": 72,
        "prefix": r"^(feat|fix|docs|refactor|perf|test|build|ci|chore|style|revert)(\([^)]+\))?!?: ",
        "no_frills": {
            "code_fences": True,
            "wrapping_quotes": True,
            "markdown_headings": True,
            "intro_phrases": [r"^(aquí|aqui)\b"],
        },
    },
    "early_stop": True,
}


# --- Puntuadores -----------------------------------------------------------------------------------


def _p(spec, text):
    return analyze.score_affinity({"id": "x", "scorer": spec}, text)


def test_classify_is_exact_against_acceptable_set():
    spec = {
        "kind": "classify",
        "labels": ["bug", "feature", "docs", "question"],
        "acceptable": ["bug"],
    }
    assert _p(spec, "bug") == {"quality": 1.0, "format": True}
    assert _p(spec, "  bug\n") == {"quality": 1.0, "format": True}
    assert _p(spec, "feature") == {"quality": 0.0, "format": True}
    # Etiqueta correcta con adorno: no es «exactamente una etiqueta».
    assert _p(spec, "bug.") == {"quality": 0.0, "format": False}
    assert _p(spec, "Bug") == {"quality": 0.0, "format": False}


def test_extract_requires_strict_json_with_exact_keys():
    spec = {
        "kind": "extract",
        "keys": ["a", "b", "c"],
        "expected": {"a": "x", "b": 502, "c": None},
    }
    ok = '{"a": "x", "b": 502, "c": null}'
    assert _p(spec, ok) == {"quality": 1.0, "format": True}
    assert _p(spec, "```json\n" + ok + "\n```")["quality"] == 1.0  # como `_strip_fences` de la tool
    # Un 502 como cadena, un null como cadena vacia o como 0, y `true` por 1 no valen.
    assert _p(spec, '{"a": "x", "b": "502", "c": null}')["quality"] == pytest.approx(2 / 3)
    assert _p(spec, '{"a": "x", "b": 502, "c": ""}')["quality"] == pytest.approx(2 / 3)
    assert _p(spec, '{"a": "x", "b": 502, "c": 0}')["quality"] == pytest.approx(2 / 3)
    spec_bool = {"kind": "extract", "keys": ["k"], "expected": {"k": 1}}
    assert _p(spec_bool, '{"k": true}')["quality"] == 0.0
    # Una clave de mas, una de menos o no ser JSON: formato roto y calidad 0.
    assert _p(spec, '{"a": "x", "b": 502, "c": null, "d": 1}') == {"quality": 0.0, "format": False}
    assert _p(spec, '{"a": "x", "b": 502}') == {"quality": 0.0, "format": False}
    assert _p(spec, "no es json") == {"quality": 0.0, "format": False}


MD = (
    "# Titulo\n\n- uno\n- dos\n\n```bash\n# no es un titulo\necho hola\n```\n\n"
    "## Otro\n\n1. a\n2. b\n"
)


def _spec_md(text=MD):
    est = analyze.markdown_structure(text)
    return {
        "kind": "translate",
        "titles": est["titles"],
        "lists": est["lists"],
        "blocks": est["blocks"],
        "code": est["code"],
    }


def test_markdown_structure_ignores_fenced_content():
    est = analyze.markdown_structure(MD)
    assert (est["titles"], est["lists"], est["blocks"]) == (2, 4, 1)
    assert est["code"] == ["# no es un titulo\necho hola"]


def test_translate_keeps_structure_and_code_byte_for_byte():
    spec = _spec_md()
    good_one = MD.replace("Titulo", "Título").replace("uno", "uno ")
    assert _p(spec, good_one) == {"quality": 1.0, "format": True}
    # Se traduce el comentario del codigo: la estructura sigue, el codigo no.
    bad_one = MD.replace("# no es un titulo", "# no es un título")
    assert _p(spec, bad_one) == {"quality": 0.75, "format": True}
    # Se pierde un elemento de la lista: falla la estructura y el formato.
    assert _p(spec, MD.replace("- dos\n", ""))["format"] is False
    # Toda la respuesta envuelta en una valla de mas: otro numero de bloques.
    assert _p(spec, "```markdown\n" + MD + "```\n")["format"] is False


def test_lint_counts_match_source_and_word_limit():
    spec = {"kind": "lint", "counts": {"E501": [4, 3, 2, 1], "F401": [3, 2, 1]}, "max_words": 20}
    assert _p(spec, "E501: 4 avisos en 3 archivos.\nF401: 3 avisos") == {
        "quality": 1.0,
        "format": True,
    }
    assert _p(spec, "E501: 6 avisos\nF401: 3 avisos")["quality"] == 0.5
    # Una regla nombrada sin conteo no cuadra.
    assert _p(spec, "E501 es la mas frecuente. F401: 3")["quality"] == 0.5
    long = "E501: 4 " + "palabra " * 30
    assert _p(spec, long)["format"] is False


def test_delegate_asks_exact_format():
    spec = {"kind": "delegate", "expected": "9", "format": r"\d+"}
    assert _p(spec, " 9\n") == {"quality": 1.0, "format": True}
    assert _p(spec, "10") == {"quality": 0.0, "format": True}
    assert _p(spec, "El texto tiene 9 palabras") == {"quality": 0.0, "format": False}


def test_f2_keeps_runner_scoring_and_unknown_scorer_fails():
    case = {"id": "x", "scorer": {"kind": "f2"}}
    record = {"score": {"quality": 0.5, "format_ok": False}}
    assert analyze.score_affinity(case, "t", record) == {"quality": 0.5, "format": False}
    with pytest.raises(ValueError, match="desconocido"):
        analyze.score_affinity({"id": "x", "scorer": {"kind": "?"}}, "t")


# --- Escenarios del veredicto -----------------------------------------------------------------------


def _case(i, tool="local_classify", discriminant=True, ok="a", bad="b"):
    return {
        "id": f"c{i}",
        "tool": tool,
        "role": "mechanical",
        "kind": "quality",
        "discriminating": discriminant,
        "sheet_role": None,
        "scorer": {"kind": "classify", "labels": ["a", "b", "c", "d"], "acceptable": ["a"]},
        "reference_ok": ok,
        "reference_bad": bad,
    }


def _r(label, case, text, *, run=1, outcome="ok", finish="stop", lat=1000, thermal="warm"):
    return {
        "schema_version": 2,
        "label": label,
        "case": case,
        "run": run,
        "attempt": 1,
        "input_variant": None,
        "outcome": outcome,
        "finish_reason": finish,
        "latency_ms": lat,
        "thermal_state": thermal,
        "discarded": False,
        "response": text,
        "response_chars": len(text),
        "score": None,
    }


def _mechanical(
    alt=("a", "a", "a", "a"), role=("a", "a", "a", "b"), weak=("b", "b", "b", "b"), **kw
):
    """Cuatro casos de `local_classify`: el rol falla el ultimo y el debil todos."""
    cases = [_case(i) for i in range(4)]
    records = []
    for tag, texts in ((ALT, alt), (QWEN, alt), (ROLE, role), (WEAK, weak)):
        for case, text in zip(cases, texts, strict=True):
            records.append(_r(tag, case["id"], text, **kw.get(tag, {})))
    return {c["id"]: c for c in cases}, analyze.group_runs(records)


def _footprints():
    return {
        model: {
            t: {"ruta": f"{model}.gguf", "flags": {"n_cpu_moe": 12}, "tool": t}
            for t in (*analyze.TOOLS_WITH_CELL, analyze.TOOL_COMMIT)
        }
        for model in (ROLE, ALT, QWEN, WEAK)
    }


def _verdict(corpus, runs, cold=0.0, judgement=None, rules=RULES, only=True):
    return analyze.compute_verdict(
        corpus, PROD, runs, _footprints(), cold, rules, judgement, mechanical_only=only
    )


def _cell(v, alternative=ALT, tool="local_classify"):
    return next(c for c in v["cells"] if c["tool"] == tool and c["alternative"] == alternative)


def test_mechanical_cell_all_in_order_approved():
    corpus, runs = _mechanical()
    cell = _cell(_verdict(corpus, runs))
    assert cell["state"] == "approved", cell["criteria"]
    assert all(c["ok"] for c in cell["criteria"].values())
    assert cell["compared_role"] == ROLE


def test_mechanical_criterion_1_fails_and_2_baseless_never_rejected():
    # Referencia mala que puntua 1 (el corpus no discrimina) y el candidato peor que el rol.
    corpus, runs = _mechanical(alt=("b", "b", "b", "b"))
    corpus["c0"] = {**corpus["c0"], "reference_bad": "a"}
    cell = _cell(_verdict(corpus, runs))
    assert not cell["criteria"]["discriminates"]["ok"]
    assert not cell["criteria"]["quality"]["ok"]
    state = cell["state"]
    assert state == "no_baseline", "falla el 1 y el 2: tiene que ser sin base, nunca rechazada"


def test_mechanical_nobody_fails_corpus_does_not_discriminate():
    corpus, runs = _mechanical(role=("a", "a", "a", "a"), weak=("a", "a", "a", "a"))
    cell = _cell(_verdict(corpus, runs))
    assert cell["criteria"]["discriminates"]["cases_where_role_or_weak_fail"] == []
    assert cell["state"] == "no_baseline"


@pytest.mark.parametrize(
    ("key", "kwargs"),
    [
        ("quality", {"alt": ("a", "a", "b", "a")}),
        ("format", {"alt": ("a", "a", "a", "bug")}),  # el rol da formato correcto en c3 («b»)
        ("verbosity", {"alt": ("a" * 3,) * 4, "role": ("a", "a", "a", "b")}),
        ("reliability", {"extra": {ALT: {"outcome": "truncado", "finish": "length"}}}),
        ("latency", {"extra": {ALT: {"lat": 9000}}}),
    ],
)
def test_each_mechanical_criterion_can_reject_a_cell(key, kwargs):
    extra = kwargs.pop("extra", {})
    corpus, runs = _mechanical(**kwargs, **extra)
    cell = _cell(_verdict(corpus, runs))
    assert not cell["criteria"][key]["ok"], cell["criteria"][key]
    assert cell["state"] == "rejected"


def test_latency_allows_role_cold_load():
    corpus, runs = _mechanical(**{ALT: {"lat": 6500}})
    assert _cell(_verdict(corpus, runs, cold=0.0))["criteria"]["latency"]["ok"] is False
    assert _cell(_verdict(corpus, runs, cold=6.0))["criteria"]["latency"]["ok"] is True


def test_regression_cases_count_in_2_but_not_in_1():
    corpus, runs = _mechanical()
    regression = {
        **_case(9, discriminant=False),
        "reference_bad": "a",
    }  # su referencia mala puntua 1
    corpus["c9"] = regression
    records = [_r(m, "c9", t) for m, t in ((ALT, "b"), (QWEN, "a"), (ROLE, "a"), (WEAK, "a"))]
    for attempts in runs.values():
        records.extend(attempts)
    cell = _cell(_verdict(corpus, analyze.group_runs(records)))
    assert cell["criteria"]["discriminates"]["ok"] is True  # la regresion no entra en el 1
    assert cell["criteria"]["quality"]["worse_cases"] == ["c9"]  # y si en el 2
    assert cell["state"] == "rejected"


def test_missing_data_no_invented_verdict():
    corpus, runs = _mechanical()
    del runs[(ALT, "c2", 1)]
    with pytest.raises(analyze.NoData, match="falta la corrida 1 de gemma4-26b-a4b en c2"):
        _verdict(corpus, runs)
    corpus, runs = _mechanical()
    runs[(ALT, "c1", 1)][-1]["discarded"] = True
    with pytest.raises(analyze.NoData, match="anulada"):
        _verdict(corpus, runs)


@pytest.mark.parametrize("reason", ["zero_vram_samples", "zero_ram_samples"])
def test_row_cancelled_only_for_lack_of_samples_counts_in_cell(reason):
    """La sonda no llegó a muestrear (respuesta de menos de 100 ms): la respuesta vale y la celda
    se evalúa con ella. Este veredicto no juzga recursos."""
    corpus, runs = _mechanical()
    for tag in (ALT, ROLE):
        runs[(tag, "c1", 1)][-1].update(discarded=True, discarded_reason=reason)
    cell = _cell(_verdict(corpus, runs))
    assert cell["state"] == "approved", cell["criteria"]
    assert cell["criteria"]["reliability"]["cases_failing_only_in_alternative"] == []


@pytest.mark.parametrize("reason", ["multiple_processes", "process_changed", None])
def test_row_cancelled_by_process_still_not_counted(reason):
    corpus, runs = _mechanical()
    runs[(ALT, "c1", 1)][-1].update(discarded=True, discarded_reason=reason)
    with pytest.raises(analyze.NoData, match="anulada"):
        _verdict(corpus, runs)


def test_verdict_json_copies_footprint_from_footprints_json():
    corpus, runs = _mechanical()
    v = _verdict(corpus, runs)
    for cell in v["cells"]:
        expected_one = _footprints()[cell["alternative"]][cell["tool"]]
        assert cell["footprint"] == expected_one
        assert cell["role_footprint"] == _footprints()[ROLE][cell["tool"]]
    # Una huella que falta no se sustituye por nada.
    footprints = _footprints()
    del footprints[ALT]["local_classify"]
    with pytest.raises(analyze.NoData, match="no trae la huella"):
        analyze.compute_verdict(
            corpus, PROD, runs, footprints, 0.0, RULES, None, mechanical_only=True
        )


def test_no_way_to_force_a_state(tmp_path):
    with pytest.raises(SystemExit):
        analyze.main(["affinity-verdict", "--forzar", "aprobada", str(tmp_path / "x.jsonl")])
    parser = _verdict_parser()
    options = {o for a in parser._actions for o in a.option_strings}
    assert not {o for o in options if "forz" in o or "aprob" in o or "state" in o}


def _verdict_parser():
    import argparse

    parent = argparse.ArgumentParser()
    sub = parent.add_subparsers()
    analyze._verdict_parser(sub)
    return sub.choices["affinity-verdict"]


# --- Carga en frio desde una copia de metrics.db ---------------------------------------------------


def _metrics_db(path, rows):
    with_ = sqlite3.connect(path)
    with_.execute(
        "CREATE TABLE activity (id INTEGER PRIMARY KEY AUTOINCREMENT, ts_created INTEGER, model_id TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, prompt_per_second REAL, tokens_per_second REAL, "
        "duration_ms INTEGER, resp_status_code INTEGER, error_msg TEXT)"
    )
    with_.executemany(
        "INSERT INTO activity (ts_created, model_id, input_tokens, output_tokens, prompt_per_second, "
        "tokens_per_second, duration_ms, resp_status_code, error_msg) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    with_.commit()
    with_.close()


def test_median_cold_load_of_copy(tmp_path):
    # Inferencia: 100/100 + 100/100 = 2 s. Cada duracion trae 2 s de inferencia mas su carga.
    def row(ts, duration_s, model=ROLE, state=200):
        return (ts, model, 100, 100, 100.0, 100.0, int(duration_s * 1000), state, "")

    base = 1_000_000
    rows = [
        row(base, 3),  # la primera del modelo: sin peticion anterior, no es «en frio»
        row(base + 10, 3),  # caliente: 7 s despues de la anterior
        row(base + 1000, 8),  # en frio: carga 6 s
        row(base + 1100, 3),  # caliente
        row(base + 3000, 10),  # en frio: carga 8 s
        row(base + 5000, 4, state=500),  # error: no cuenta
        row(base + 7000, 12, model=ALT),  # otro modelo: no cuenta
    ]
    db = tmp_path / "metrics.db"
    _metrics_db(db, rows)
    assert analyze.median_cold_load(db, ROLE) == pytest.approx(7.0)
    assert analyze.median_cold_load(db, "does-not-exist") is None


# --- Celda de commit --------------------------------------------------------------------------------

N_REAL = 30


def _commit_corpus():
    cases = {}
    for i in range(N_REAL):
        cases[f"k{i}"] = {
            "id": f"k{i}",
            "tool": analyze.TOOL_COMMIT,
            "role": "code",
            "kind": "quality",
            "discriminating": True,
            "sheet_role": "real",
            "scorer": {"kind": "hoja"},
        }
    for i in range(3):
        cases[f"t{i}"] = {
            **cases["k0"],
            "id": f"t{i}",
            "discriminating": False,
            "sheet_role": "trampa",
        }
    cases[analyze.CEILING_CASE_ID] = {
        "id": analyze.CEILING_CASE_ID,
        "tool": analyze.TOOL_COMMIT,
        "role": "code",
        "kind": "ceiling",
        "discriminating": False,
        "sheet_role": None,
        "scorer": {"kind": "techo"},
    }
    return cases


def _commit_runs(*, ceiling_fails_on=None, alt_fails_on=(), qwen_fails_on=(), alt_text=None):
    records = []
    for i in range(N_REAL):
        for tag, fails in ((ALT, alt_fails_on), (QWEN, qwen_fails_on)):
            bad = i in fails
            text = (alt_text or {}).get(i, "feat: algo") if tag == ALT else "feat: otra cosa"
            records.append(
                _r(
                    tag,
                    f"k{i}",
                    text,
                    outcome="truncado" if bad else "ok",
                    finish="length" if bad else "stop",
                )
            )
    for run in (1, 2, 3):
        bad = run == ceiling_fails_on
        records.append(
            _r(
                ALT,
                analyze.CEILING_CASE_ID,
                "feat: techo",
                run=run,
                outcome="error" if bad else "ok",
            )
        )
    return analyze.group_runs(records)


def _verdict_cell(
    c=15, v=10, invents_26b=0, worse_traps=3, case_set_item=1, partial=False, invents_on_traps=0
):
    """30 pares reales: `c` los gana el 26B, `v` Qwen y el resto empata; 3 trampas."""
    pair_items = {}
    for i in range(N_REAL):
        sides = {"A": ALT, "B": QWEN} if i % 2 == 0 else {"A": QWEN, "B": ALT}
        alt_side = "A" if sides["A"] == ALT else "B"
        qwen_side = "B" if alt_side == "A" else "A"
        pref = alt_side if i < c else qwen_side if i < c + v else "="
        invents = {alt_side: "s" if i < invents_26b else "n", qwen_side: "n"}
        pair_items[f"{i + 1:02d}"] = {
            "kind": "real",
            "case": f"k{i}",
            "sides": sides,
            "made_up": invents,
            "principal": {"A": None, "B": None},
            "specific": {"A": None, "B": None},
            "preference": pref,
        }
    for j in range(3):
        # El modelo de la trampa es el 26B: si se contaran sus «inventa», el criterio 1 saldria mal.
        worse = j < worse_traps
        pair_items[f"{N_REAL + j + 1:02d}"] = {
            "kind": "trampa",
            "case": f"t{j}",
            "sides": {"A": "trampa", "B": ALT},
            "made_up": {"A": "n", "B": "s" if j < invents_on_traps else "n"},
            "principal": {"A": None, "B": None},
            "specific": {"A": None, "B": None},
            "preference": "B" if worse else "A",
        }
    return {"schema_version": 1, "set": case_set_item, "partial": partial, "pairs": pair_items}


def _commit_cell(judgement, runs=None, rules=RULES, **kw):
    runs = runs if runs is not None else _commit_runs(**kw)
    v = _verdict(_commit_corpus(), runs, judgement=judgement, rules=rules, only=False)
    return _cell(v, ALT, analyze.TOOL_COMMIT)


def test_commit_approved_if_sheet_valid_and_all_pass():
    cell = _commit_cell(_verdict_cell())
    assert cell["state"] == "approved", cell["criteria"]
    assert cell["criteria"]["preference"] == {"ok": True, "c": 15, "v": 10, "ties": 5}


@pytest.mark.parametrize(
    ("maximum", "invents", "state"),
    [(2, 2, "approved"), (2, 3, "rejected"), (1, 2, "rejected"), (1, 1, "approved")],
)
def test_commit_invents_read_from_rules_json(maximum, invents, state):
    rules = {**RULES, "max_made_up_26b": maximum}
    cell = _commit_cell(_verdict_cell(invents_26b=invents), rules=rules)
    assert cell["criteria"]["made_up"]["yes"] == invents
    result = cell["state"]
    assert result == state, cell["criteria"]["made_up"]


def test_commit_c_equal_v_does_not_lose_and_ties_do_not_count():
    cell = _commit_cell(_verdict_cell(c=12, v=12))
    assert cell["criteria"]["preference"] == {"ok": True, "c": 12, "v": 12, "ties": 6}
    assert cell["state"] == "approved"
    cell = _commit_cell(_verdict_cell(c=11, v=12))
    assert cell["state"] == "rejected"


def test_commit_invents_on_real_message_of_trap_pair_not_counted_for_1():
    cell = _commit_cell(_verdict_cell(invents_on_traps=3))
    assert cell["criteria"]["made_up"]["n"] == 30
    assert cell["criteria"]["made_up"]["yes"] == 0


def test_commit_one_of_three_traps_marked_worse_is_baseless_and_repeat_sheet():
    cell = _commit_cell(_verdict_cell(worse_traps=1))
    assert cell["criteria"]["valid_sheet"]["traps_flagged_as_worse"] == 1
    state = cell["state"]
    assert state == "no_baseline"
    assert "repetir hoja" in cell["report"]
    # Con dos de tres la hoja vale.
    assert _commit_cell(_verdict_cell(worse_traps=2))["state"] == "approved"
    # La tercera hoja que no vale ya no dice «repetir».
    assert "repetir" not in _commit_cell(_verdict_cell(worse_traps=0, case_set_item=3))["report"]


def test_commit_ceiling_or_26b_only_failure_rejects_even_if_sheet_wins():
    cell = _commit_cell(
        _verdict_cell(c=30, v=0), ceiling_fails_on=2
    )  # 3a: una de las tres corridas falla
    assert cell["criteria"]["behaviour"]["ceiling_3_of_3"] is False
    assert cell["state"] == "rejected"
    cell = _commit_cell(
        _verdict_cell(c=30, v=0), alt_fails_on={4}
    )  # 3b: `length` en el 26B, no en Qwen
    assert cell["criteria"]["behaviour"]["cases_failing_only_in_alternative"] == ["k4"]
    state = cell["state"]
    assert state == "rejected"
    # Si Qwen tambien falla en ese caso, no cuenta contra el 26B.
    cell = _commit_cell(_verdict_cell(c=30, v=0), alt_fails_on={4}, qwen_fails_on={4})
    assert cell["state"] == "approved"


def test_commit_partial_judgement_gives_no_verdict():
    with pytest.raises(analyze.NoData, match="parcial"):
        _commit_cell(_verdict_cell(partial=True))


def test_format_computed_by_program_and_state_unchanged():
    rule = RULES["format"]
    f = analyze.message_format
    assert f("feat: x", rule)
    assert f("fix(scope)!: cambia algo\n\n- uno\n- dos", rule)
    assert not f("x" * 10, rule)  # sin prefijo convencional
    assert not f("feat: " + "x" * 67, rule)  # 73 caracteres
    assert f("feat: " + "x" * 66, rule)  # 72
    assert not f("feat: x\n\n```\ncodigo\n```", rule)  # valla de codigo en el cuerpo
    assert not f("feat: x\n\n# Titulo", rule)  # encabezado Markdown
    assert not f('"feat: x"', rule)
    assert not f("Aquí tienes el mensaje:\nfeat: x", rule)
    # No decide: dos corridas, una con formato impecable y otra con vallas, dan el mismo estado.
    clean = _commit_cell(_verdict_cell(), alt_text={i: "feat: ok" for i in range(N_REAL)})
    dirty = _commit_cell(_verdict_cell(), alt_text={i: "```\nfeat: ok\n```" for i in range(N_REAL)})
    assert clean["state"] == dirty["state"] == "approved"
    assert clean["published"][ALT]["format"] == 30
    assert dirty["published"][ALT]["format"] == 0


def test_rules_json_is_validated(tmp_path):
    def with_(**changes):
        path = tmp_path / "rules.json"
        path.write_text(json.dumps({**RULES, **changes}), encoding="utf-8")
        return path

    assert analyze.read_affinity_rules(with_())["max_made_up_26b"] == 2
    with pytest.raises(SystemExit, match="inventa"):
        analyze.read_affinity_rules(with_(optional_questions=["inventa"]))
    with pytest.raises(SystemExit, match="max_made_up_26b"):
        analyze.read_affinity_rules(with_(max_made_up_26b=-1))


# --- El veredicto no importa el paquete -------------------------------------------------------------


def _write_scenario(tmp_path):
    corpus, runs = _mechanical()
    cases = {
        "schema_version": 2,
        "production_config": PROD,
        "cases": list(corpus.values()),
    }
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    (tmp_path / "rules.json").write_text(json.dumps(RULES), encoding="utf-8")
    (tmp_path / "footprints.json").write_text(json.dumps(_footprints()), encoding="utf-8")
    records = [r for attempts in runs.values() for r in attempts]
    (tmp_path / "r.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    _metrics_db(tmp_path / "metrics.db", [])


def test_does_not_import_package(tmp_path):
    """`affinity-verdict` corre con `local_delegate` bloqueado: importarlo cargaria `server.py`
    mientras otras tareas lo editan."""
    _write_scenario(tmp_path)
    program = (
        "import runpy, sys\n"
        "sys.modules['local_delegate'] = None\n"
        f"sys.argv = ['analyze_benchmark.py', 'affinity-verdict', '--mechanical-only',"
        f" '--cases', r'{tmp_path / 'cases.json'}', '--rules', r'{tmp_path / 'rules.json'}',"
        f" '--footprints', r'{tmp_path / 'footprints.json'}', '--metrics-db', r'{tmp_path / 'metrics.db'}',"
        f" r'{tmp_path / 'r.jsonl'}']\n"
        f"runpy.run_path(r'{ROOT / 'scripts' / 'analyze_benchmark.py'}', run_name='__main__')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads((tmp_path / "verdict-mechanical.json").read_text(encoding="utf-8"))
    assert {c["state"] for c in verdict["cells"]} == {"approved"}
    assert "aprobada" in proc.stdout


# --- Lectura dual de los resultados congelados (ola A10b-1) ---------------------------------------

FROZEN_RESULTS = ROOT / "benchmarks" / "afinidad-2026-10" / "resultados" / "gemma3-4b.jsonl"


def test_frozen_results_are_read_with_the_new_keys():
    """Las filas congeladas dicen `descartada`; los tres cargadores las dan como `discarded`."""
    old_rows = [json.loads(x) for x in FROZEN_RESULTS.read_text(encoding="utf-8").splitlines() if x]
    expected = sum(1 for r in old_rows if r.get("descartada"))
    assert expected > 0  # sin filas anuladas, el test no distinguiría nada
    pair_sheet = _load("pair_sheet")
    for records in (
        analyze.read_jsonl([FROZEN_RESULTS]),
        review_sheet._records([FROZEN_RESULTS]),
        pair_sheet._records([FROZEN_RESULTS]),
    ):
        assert not any("descartada" in r or "descartada_motivo" in r for r in records)
        assert sum(1 for r in records if r["discarded"]) == expected
        assert {r["discarded_reason"] for r in records if r["discarded"]} == {"zero_vram_samples"}


def test_old_outcome_and_zero_by_values_are_translated(tmp_path):
    path = tmp_path / "old.jsonl"
    rows = [
        {"schema_version": 2, "outcome": "rechazo_por_contexto", "score": None},
        {
            "schema_version": 2,
            "outcome": "truncado",
            "score": {"quality": 0.0, "zero_by": "truncado_repetido"},
        },
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    first, second = analyze.read_jsonl([path])
    assert first["outcome"] == "context_rejection"
    assert second["score"]["zero_by"] == "truncated_repeated"


def test_footprints_fall_back_to_the_frozen_file(tmp_path):
    frozen = ROOT / "benchmarks" / "afinidad-2026-10"
    assert analyze.footprints_file(frozen / "footprints.json") == frozen / "huellas.json"
    assert (frozen / "huellas.json").exists()
    (tmp_path / "footprints.json").write_text("{}", encoding="utf-8")
    assert analyze.footprints_file(tmp_path / "footprints.json") == tmp_path / "footprints.json"
    assert analyze.footprints_file(tmp_path / "other.json") == tmp_path / "other.json"


# --- Formato nuevo del veredicto y lectura dual de sus entradas (ola A10b-2) ----------------------

FROZEN_AFFINITY = ROOT / "benchmarks" / "afinidad-2026-10"


def _read_verdict(directory):
    """Como lo lee `tests/test_affinity.py`: `verdict.json` si existe y, si no, el congelado."""
    old_name, new_name = legacy_names.VERDICT_FILE_NAMES
    path = directory / new_name if (directory / new_name).exists() else directory / old_name
    return legacy_names.normalize_affinity_verdict(json.loads(path.read_text(encoding="utf-8")))


def test_the_written_verdict_closes_the_cycle_and_the_frozen_one_is_still_read(tmp_path):
    _write_scenario(tmp_path)
    (tmp_path / "veredicto.json").write_bytes((FROZEN_AFFINITY / "veredicto.json").read_bytes())
    rc = analyze.main(
        [
            "affinity-verdict",
            "--mechanical-only",
            "--cases",
            str(tmp_path / "cases.json"),
            "--rules",
            str(tmp_path / "rules.json"),
            "--footprints",
            str(tmp_path / "footprints.json"),
            "--metrics-db",
            str(tmp_path / "metrics.db"),
            "--output",
            str(tmp_path / "verdict.json"),
            str(tmp_path / "r.jsonl"),
        ]
    )
    assert rc == 0
    written = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    old_keys = {"celdas", "reglas", "solo_mecanicas", "reglas_sha256"}
    assert not old_keys & set(written) and {"cells", "rules", "mechanical_only"} <= set(written)
    assert not {"alternativo", "rol_comparado", "estado", "criterios", "huella"} & set(
        written["cells"][0]
    )
    # Escribir y leer cierra: el lector no cambia nada de un veredicto ya nuevo, y lo prefiere.
    assert legacy_names.normalize_affinity_verdict(written) == written
    assert _read_verdict(tmp_path) == written
    # Sin el nuevo, se lee el congelado con las mismas claves.
    (tmp_path / "verdict.json").unlink()
    frozen = _read_verdict(tmp_path)
    for cell in frozen["cells"]:
        assert {"tool", "alternative", "compared_role", "state", "footprint"} <= set(cell)
    # El estado se guarda y se relee (ola A10b-3): en inglés al escribir; el congelado, traducido.
    states = {"approved", "rejected", "no_baseline"}
    assert {c["state"] for c in written["cells"]} <= states
    assert {c["state"] for c in frozen["cells"]} == {"approved", "rejected"}


# Los nombres de antes, escritos a mano: si salieran de la tabla de `legacy_names`, una tabla vacía
# daría un formato «viejo» igual al nuevo y el test no distinguiría nada.
_OLD_NAMES = {
    "commit_judgement": {
        "partial": "parcial",
        "pairs": "pares",
        "set": "juego",
        "kind": "tipo",
        "preference": "preferencia",
        "sides": "lados",
        "made_up": "inventa",
        "specific": "especifico",
        "case": "caso",
    },
    "affinity_scorer": {"kind": "tipo", "labels": "etiquetas", "acceptable": "aceptables"},
}


def _old_keys(fmt, row):
    return {_OLD_NAMES[fmt].get(k, k): v for k, v in row.items()}


def test_an_old_format_judgement_gives_the_same_commit_cell():
    new = _verdict_cell(c=15, v=10)
    old = _old_keys("commit_judgement", new)
    old["pares"] = {k: _old_keys("commit_judgement", p) for k, p in new["pairs"].items()}
    assert "pares" in old and "tipo" in old["pares"]["01"] and "lados" in old["pares"]["01"]
    assert _commit_cell(old) == _commit_cell(new)


@pytest.mark.parametrize(
    ("old", "new"),
    [("aprobada", "approved"), ("rechazada", "rejected"), ("sin base", "no_baseline")],
)
def test_an_old_format_cell_state_is_read_in_english(old, new):
    # Escritos a mano (ola A10b-3): el `veredicto.json` congelado solo tiene los dos primeros.
    read = legacy_names.normalize_affinity_verdict({"celdas": [{"tool": "t", "estado": old}]})
    assert read["cells"] == [{"tool": "t", "state": new}]
    assert legacy_names.normalize_affinity_verdict(read) == read


def test_the_frozen_rules_are_read_with_the_new_keys():
    rules = analyze.read_affinity_rules(FROZEN_AFFINITY / "reglas.json")
    assert rules["max_made_up_26b"] == 1 and rules["early_stop"] is True
    assert rules["format"]["no_frills"]["code_fences"] is True
    assert analyze.message_format("feat: algo", rules["format"])
    assert not analyze.message_format("```\nfeat: algo\n```", rules["format"])
    frozen = FROZEN_AFFINITY / "rules.json"
    assert analyze.rules_file(frozen) == FROZEN_AFFINITY / "reglas.json"


def test_an_old_format_scorer_scores_the_same():
    new = {"kind": "classify", "labels": ["bug", "feature"], "acceptable": ["bug"]}
    old = _old_keys("affinity_scorer", new)
    assert "tipo" in old
    for text in ("bug", "feature", "otra"):
        assert analyze.score_affinity({"puntuador": old}, text) == analyze.score_affinity(
            {"scorer": new}, text
        )


def test_unblinded_pairs_are_summed_in_either_format(tmp_path):
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text(json.dumps({"c1": {"humano": {"a": 2, "b": 1}}}), encoding="utf-8")
    new.write_text(
        json.dumps({"c1": {"human": {"a": 1}}, "c2": {"human": {"b": 3}}}), encoding="utf-8"
    )
    assert analyze.merge_unblinded_pairs([old, new]) == {
        "c1": {"human": {"a": 3, "b": 1}},
        "c2": {"human": {"b": 3}},
    }
    assert analyze.merge_unblinded_pairs([]) is None


def test_the_frozen_affinity_corpus_is_read_with_the_new_case_keys():
    """El corpus congelado dice `discriminante`: sin la traducción, la celda diría que no hay
    casos discriminantes; con ella, llega a buscar las corridas."""
    data = json.loads((FROZEN_AFFINITY / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if c["tool"] == "local_classify"]
    assert cases and all("discriminante" in c for c in cases)
    with pytest.raises(analyze.NoData, match="falta la corrida"):
        analyze.evaluate_mechanical_cell("local_classify", "alt", "role", cases, {}, None)


# --- El tipo de caso en inglés y su lectura dual (ola A10b-5) -------------------------------------

# Escritos a mano: si salieran de `legacy_names.CORPUS_KIND_VALUES`, una tabla vacía daría un formato
# «viejo» igual al nuevo y el test no distinguiría nada.
_OLD_KINDS = {"calidad": "quality", "techo": "ceiling"}
FROZEN_CEILING = FROZEN_AFFINITY / "resultados" / "techo-gemma4-26b-a4b.jsonl"


def _load_affinity_batch():
    path = ROOT / "scripts" / "dev" / "affinity_batch.py"
    spec = importlib.util.spec_from_file_location("affinity_batch_a10b5", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["affinity_batch_a10b5"] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_result_kinds_are_read_in_english():
    """Las filas congeladas dicen `calidad` y `techo`; los cuatro cargadores las dan en inglés."""
    paths = [FROZEN_RESULTS, FROZEN_CEILING]
    raw = {
        json.loads(x)["kind"]
        for p in paths
        for x in p.read_text(encoding="utf-8").splitlines()
        if x
    }
    assert raw == set(_OLD_KINDS)  # sin los dos valores viejos, el test no distinguiría nada
    pair_sheet = _load("pair_sheet")
    batch = _load_affinity_batch()
    for records in (
        analyze.read_jsonl(paths),
        review_sheet._records(paths),
        pair_sheet._records(paths),
        [r for p in paths for r in batch._read_rows(p)],
    ):
        assert {r["kind"] for r in records} == set(_OLD_KINDS.values())
    # Y la hoja de revisión, que solo elige casos de calidad, sigue encontrándolos.
    reviewable = [r for r in review_sheet._records(paths) if r["kind"] == "quality"]
    assert len(reviewable) == 49


@pytest.mark.parametrize("corpus", ["catalogo-2026-09", "afinidad-2026-10"])
def test_frozen_corpus_kinds_are_read_in_english(corpus):
    path = ROOT / "benchmarks" / corpus / "cases.json"
    raw = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert {c["kind"] for c in raw} == set(_OLD_KINDS)
    expected = [_OLD_KINDS[c["kind"]] for c in raw]
    assert [c["kind"] for c in analyze.read_corpus(path).values()] == expected
    assert [c["kind"] for c in _load_affinity_batch().load_cases(path)] == expected
    affinity = legacy_names.normalize_affinity_corpus({"cases": raw})["cases"]
    assert [c["kind"] for c in affinity] == expected
    if corpus == "catalogo-2026-09":
        assert [c.kind for c in benchmark.load_corpus(path).cases] == expected
    # Un caso ya nuevo sale igual.
    assert legacy_names.normalize("benchmark_corpus", {"kind": "quality"}) == {"kind": "quality"}


def test_an_old_kind_affinity_case_still_enters_the_cell():
    """`compute_verdict` elige los casos de la celda por su tipo: un corpus del formato viejo
    (`calidad`) da la misma celda que el nuevo."""
    corpus, runs = _mechanical()
    old = {cid: {**c, "kind": "calidad"} for cid, c in corpus.items()}
    assert _cell(_verdict(old, runs)) == _cell(_verdict(corpus, runs))
    assert _cell(_verdict(old, runs))["state"] == "approved"


# --- El motivo «techo» de CP-3 en inglés y su lectura dual (ola A10b-6) -----------------------------


def test_an_old_cp3_json_still_gives_the_tie_at_ceiling(tmp_path, capsys):
    """Un `cp3.json` de antes dice `techo` (escrito a mano: no hay ninguno versionado). `decide`
    lo relee como `ceiling` y el rol sigue siendo un empate en techo que decide la velocidad."""
    old = _cp3_at_ceiling("mechanical")
    old["cases"] = {cid: {"reason": "techo"} for cid in old["cases"]}
    path = tmp_path / "cp3.json"
    path.write_text(json.dumps({"roles": {"mechanical": old}}), encoding="utf-8")
    read = analyze.read_cp3([path])["mechanical"]
    assert {c["reason"] for c in read["cases"].values()} == {"ceiling"}
    slow, fast = (2000, 2000, 2100), (1000, 1000, 1100)
    records = _batch("incumbent", "mechanical", (1.0, 1.0, 1.0), latencies=slow) + _batch(
        "candidate", "mechanical", (1.0, 1.0, 1.0), latencies=fast
    )
    d = _decide(records, role="mechanical", cp3=read)
    assert d["all_at_ceiling"] is True
    assert (d["verdict"], d["criterion"]) == ("replace", "velocidad")
    # Por la línea de órdenes, el mismo fichero viejo, y el informe sigue diciendo «techo».
    jsonl = tmp_path / "batch.jsonl"
    jsonl.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    argv = ["decide", "--cases", str(CASES), "--cp3", str(path)]
    rc = analyze.main([*argv, "--pair", "mechanical", "incumbent", "candidate", str(jsonl)])
    assert rc == 0
    assert "(techo)" in capsys.readouterr().out
