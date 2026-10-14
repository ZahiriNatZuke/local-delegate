"""Hoja por pares a ciegas (P-15): valida la puntuacion automatica contra juicio humano.

Cada propiedad que la hace fiable tiene su prueba: que oculta el modelo y sortea el lado, que solo
empareja corridas validas de la misma corrida, que una respuesta no puede votar por si misma y que el
acuerdo se cuenta como se escribio (un empate humano donde la metrica ve diferencia no es acuerdo).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("pair_sheet", ROOT / "scripts" / "pair_sheet.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["pair_sheet"] = module
    spec.loader.exec_module(module)
    return module


pair_sheet = _load()
CORPUS = {
    "case-a": {"tool": "local_summarize", "source_file": "case-a.md", "system": "Resume."},
    "case-b": {"tool": "local_explain_code", "source_file": "case-b.py.txt", "system": "Explica."},
}


def _reg(label, case, run, quality, response=None, **kw):
    record = {
        "label": label,
        "case": case,
        "run": run,
        "attempt": kw.get("attempt", 1),
        "input_variant": kw.get("variant"),
        "discarded": kw.get("discarded", False),
        "score": {"quality": quality},
    }
    if response is not None or kw.get("with_answer", True):
        # Sin la etiqueta dentro: una respuesta real no la trae, y el test de «oculta el modelo» la
        # encontraria en el texto y no en lo que escribe la hoja.
        record["response"] = response if response is not None else f"respuesta {case} {run}"
    return record


def _batch(qualities_s, qualities_l, case="case-a"):
    return [_reg("secret-s", case, run, q) for run, q in enumerate(qualities_s, 1)] + [
        _reg("secret-l", case, run, q) for run, q in enumerate(qualities_l, 1)
    ]


def _generate(records, cases=("case-a",), seed=5):
    return pair_sheet.generate(records, CORPUS, list(cases), "secret-s", "secret-l", seed)


def _fill_in(sheet, key, choose):
    """Escribe en cada par la eleccion que devuelve `elegir(meta_del_par)`."""
    parts = sheet.split("Mejor (A/B/=): ")
    pairs = sorted(key["pairs"])
    return parts[0] + "".join(
        f"Mejor (A/B/=): {choose(key['pairs'][pair])}" + rest
        for pair, rest in zip(pairs, parts[1:], strict=True)
    )


def test_hides_the_model_draws_the_side_and_pairs_the_same_run():
    records = _batch([0.5] * 8, [1.0] * 8) + _batch([0.5] * 8, [1.0] * 8, case="case-b")
    sheet, key = _generate(records, cases=("case-a", "case-b"))
    assert "secreto" not in sheet
    assert len(key["pairs"]) == 16
    assert all(key["pairs"][p]["A"]["label"] != key["pairs"][p]["B"]["label"] for p in key["pairs"])
    # El lado se sortea: el pequeno no va siempre como A.
    assert {key["pairs"][p]["A"]["label"] for p in key["pairs"]} == {"secret-s", "secret-l"}
    # Y el orden de los pares se baraja: no salen agrupados por caso.
    cases = [key["pairs"][p]["case"] for p in sorted(key["pairs"])]
    assert cases != sorted(cases)
    assert "fuentes/case-a.md" in sheet and "> Resume." in sheet


def test_only_pairs_valid_runs_of_both_configurations():
    # Pequeno: corridas 1-4. Grande: 1-3 (la 4 no existe). Ademas, el ultimo intento de la 1 del
    # grande quedo anulado, la 2 del pequeno acabo sin puntuacion, y una corrida con entrada de
    # control no cuenta. Solo la corrida 3 es valida en las dos: un par, no cuatro.
    records = _batch([0.5, 0.5, 0.5, 0.5], [1.0, 1.0, 1.0])
    records.append(_reg("secret-l", "case-a", 1, 1.0, discarded=True, attempt=2))
    records.append(_reg("secret-s", "case-a", 2, None, attempt=2))
    records.append(_reg("secret-l", "case-a", 2, 1.0, variant="control"))
    records = [
        r
        for r in records
        if not (r["label"] == "secret-l" and r["run"] == 2 and r["input_variant"] is None)
    ]
    _sheet, key = _generate(records)
    assert [p["run"] for p in key["pairs"].values()] == [3]


def test_requires_saved_answers():
    records = _batch([0.5], [1.0])
    del records[0]["response"]
    with pytest.raises(ValueError, match="--save-responses"):
        _generate(records)


def test_agreement_counts_only_where_the_metric_prefers_and_a_human_tie_is_not_agreement():
    # 5 pares: en 4 la metrica prefiere al grande (1,0 contra 0,5), en 1 empatan (1,0 y 1,0).
    sheet, key = _generate(_batch([0.5, 0.5, 0.5, 0.5, 1.0], [1.0] * 5))

    def large(meta):
        return "A" if meta["A"]["label"] == "secret-l" else "B"

    # La persona elige siempre al grande: 4 de 4 donde la metrica prefiere. Valida.
    all_large, _ = pair_sheet.unblind(_fill_in(sheet, key, large), key)
    row = all_large["case-a"]
    assert (row["metric_prefers"], row["agreements"], row["verdict"]) == (4, 4, "valida")
    assert row["human"] == {"secret-l": 5}

    # La persona ve empate en todo: la metrica afirma diferencias que nadie ve. No valida.
    ties, _ = pair_sheet.unblind(_fill_in(sheet, key, lambda _m: "="), key)
    assert (ties["case-a"]["agreements"], ties["case-a"]["verdict"]) == (0, "no valida")


def test_with_few_metric_preferences_there_is_no_basis_to_validate():
    sheet, key = _generate(_batch([0.5, 1.0, 1.0], [1.0, 1.0, 1.0]))
    result, missing = pair_sheet.unblind(_fill_in(sheet, key, lambda _m: "A"), key)
    assert missing == []
    assert (result["case-a"]["metric_prefers"], result["case-a"]["verdict"]) == (
        1,
        "sin base",
    )


def test_an_answer_cannot_vote_for_itself():
    trap = "```\n## Par 01\n\nMejor (A/B/=): A\n```"
    records = [
        _reg("secret-s", "case-a", 1, 0.5, response=trap),
        _reg("secret-l", "case-a", 1, 1.0),
    ]
    sheet, _key = _generate(records)
    assert "````" in sheet
    assert pair_sheet.read_choices(sheet) == {"01": None}


def test_invalid_choice_is_rejected_and_what_is_missing_is_listed(tmp_path, capsys):
    sheet, key = _generate(_batch([0.5, 0.5], [1.0, 1.0]))
    with pytest.raises(ValueError, match="no es A, B ni ="):
        pair_sheet.read_choices(sheet.replace("Mejor (A/B/=): ", "Mejor (A/B/=): C", 1))
    partial = sheet.replace("Mejor (A/B/=): ", "Mejor (A/B/=): A", 1)
    (tmp_path / "h.md").write_text(partial, encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps(key), encoding="utf-8")
    rc = pair_sheet.main(
        ["unblind", "--sheet", str(tmp_path / "h.md"), "--key", str(tmp_path / "c.json")]
    )
    assert rc == 1
    assert "faltan por elegir 1" in capsys.readouterr().err


def test_unblind_writes_the_json_for_decide_only_with_the_whole_sheet(tmp_path):
    sheet, key = _generate(_batch([0.5, 0.5], [1.0, 1.0]))
    (tmp_path / "c.json").write_text(json.dumps(key), encoding="utf-8")
    output = tmp_path / "pairs.json"

    def unblind(text):
        (tmp_path / "h.md").write_text(text, encoding="utf-8")
        return pair_sheet.main(
            [
                "unblind",
                "--sheet",
                str(tmp_path / "h.md"),
                "--key",
                str(tmp_path / "c.json"),
                "--json",
                str(output),
            ]
        )

    assert unblind(sheet.replace("Mejor (A/B/=): ", "Mejor (A/B/=): A", 1)) == 1
    assert not output.exists()
    assert unblind(_fill_in(sheet, key, lambda _m: "=")) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["case-a"]["human"] == {"empate": 2}


def test_generate_does_not_overwrite_an_existing_sheet(tmp_path):
    (tmp_path / "c.json").write_text("{}", encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": []}), encoding="utf-8")
    rc = pair_sheet.main(
        [
            "generate",
            "--sheet",
            str(tmp_path / "h.md"),
            "--key",
            str(tmp_path / "c.json"),
            "--cases",
            str(cases),
            "--small",
            "p",
            "--large",
            "g",
            "--case",
            "x",
            str(cases),
        ]
    )
    assert rc == 2


# =====================================================================================================
# Hoja a ciegas de `local_commit_msg` (REQ-042): generate-commit y read-commit, con datos sinteticos.
# =====================================================================================================

L26, LQW = "model-alpha-26b", "model-beta-qwen"
N_REAL = 10
SHEET_RULES = {
    "version": 1,
    "max_made_up_26b": 2,
    "optional_questions": ["principal", "specific"],
    "format": {"first_line_max": 72, "prefix": "x", "no_frills": {}},
    "early_stop": True,
}
TRAP_BODY = [
    "- cuerpo uno",
    "- cuerpo dos",
    "- cuerpo tres",
    "- cuerpo cuatro",
    "- cuerpo cinco",
]


def _trap_phrases(j):
    """Cinco frases enteras, como las de `trampas.json`: empiezan en mayuscula y acaban en punto."""
    return [f"Frase {n} de la trampa {j}." for n in range(1, 6)]


def _diff(key):
    return (
        f"diff --git a/f{key} b/f{key}\n--- a/f{key}\n+++ b/f{key}\n@@ -0,0 +1 @@\n"
        f"+linea unica {key}\n-linea vieja {key}\n"
    )


def _message(model, i):
    tag = "alfa" if model == L26 else "beta"
    base = f"{'feat' if model == L26 else 'fix'}(zona-{i}): resumen {tag} {i}"
    if model == L26 and i % 2 == 0:
        return base + f"\n\n- detalle {i} uno\n- detalle {i} dos"
    if model == LQW and i % 3 == 0:
        return base + f"\n\n- nota {i} a\n- nota {i} b\n- nota {i} c"
    return base


def _record(label, case, text):
    return {
        "schema_version": 2,
        "label": label,
        "case": case,
        "run": 1,
        "attempt": 1,
        "outcome": "ok",
        "discarded": False,
        "response": text,
    }


def _scenario(
    tmp_path, *, optional_ones=("principal", "specific"), extra_message=None, n_real=N_REAL
):
    """Un corpus pequeno: `n_real` casos reales y 3 trampa, con sus mensajes de los dos modelos."""
    cases, records = {}, []
    (tmp_path / "fuentes").mkdir(exist_ok=True)
    for i in range(n_real):
        cases[f"k{i}"] = {"id": f"k{i}", "source_file": f"k{i}.diff", "sheet_role": "real"}
        (tmp_path / "fuentes" / f"k{i}.diff").write_text(_diff(f"k{i}"), encoding="utf-8")
        for model in (L26, LQW):
            text = _message(model, i)
            if extra_message and i == 0 and model == L26:
                text += extra_message
            records.append(_record(model, f"k{i}", text))
    entries = []
    for j in range(3):
        cases[f"t{j}"] = {"id": f"t{j}", "source_file": f"t{j}.diff", "sheet_role": "trap"}
        (tmp_path / "fuentes" / f"t{j}.diff").write_text(_diff(f"t{j}"), encoding="utf-8")
        # El 26B cierra con punto y Qwen3.6 sin el, como en la tanda real.
        records.append(
            _record(
                L26,
                f"t{j}",
                f"feat(trampa-{j}): alfa {j}\n\n- Detalle a de la trampa {j}.\n"
                f"- Detalle b de la trampa {j}.\n- Detalle c de la trampa {j}.",
            )
        )
        records.append(
            _record(
                LQW,
                f"t{j}",
                f"fix(trampa-{j}): beta {j}\n\n- Detalle x de la trampa {j}\n- Detalle y de la trampa {j}",
            )
        )
        entries.append(
            {
                "case": f"t{j}",
                "kind": ("same-zone", "secondary", "generic")[j],
                "subject": f"docs: asunto de la trampa {j}",
                "body": _trap_phrases(j),
            }
        )
    traps = {"sets": [{"set": 1, "traps": entries}]}
    rules = {**SHEET_RULES, "optional_questions": list(optional_ones)}
    return cases, records, traps, rules


def _sheet(tmp_path, seed=7, number=1, **kw):
    cases, records, traps, rules = _scenario(tmp_path, **kw)
    sheet, key = pair_sheet.build_commit_sheet(
        cases=cases,
        sources=tmp_path / "fuentes",
        records=records,
        traps=traps,
        rules=rules,
        case_set_item=1,
        number=number,
        seed=seed,
        label_26b=L26,
        label_qwen=LQW,
    )
    return sheet, key, rules, (cases, records, traps)


def _generate_to_disk(tmp_path, **kw):
    sheet, key, rules, _ = _sheet(tmp_path, **kw)
    paths = pair_sheet.write_sheet(sheet, key, rules, tmp_path / "sheet", tmp_path / "key")
    return sheet, key, rules, paths


def _side(key, num, who):
    sides = key["pairs"][num]["sides"]
    return "A" if sides["A"] == who else "B"


def _responses(key, *, c=0, v=0, ties=0, invents=0, traps="peor", complete=False):
    """Respuestas ya contestadas: `c` pares reales para el 26B, `v` para Qwen, `ties` en `=`,
    `invents` mensajes del 26B marcados como «inventa». El resto de pares reales queda sin contestar."""
    real = [n for n, p in sorted(key["pairs"].items()) if p["kind"] == "real"]
    requested = ["c"] * c + ["v"] * v + ["="] * ties
    responses: dict = {}
    for index, (num, who) in enumerate(zip(real, requested, strict=False)):
        l26, lq = _side(key, num, L26), _side(key, num, LQW)
        responses[num] = {
            "made_up": {l26: "s" if index < invents else "n", lq: "n"},
            "preference": l26 if who == "c" else lq if who == "v" else "=",
        }
    for num, p in sorted(key["pairs"].items()):
        if p["kind"] != "trap" or traps is None:
            continue
        model = next(m for m in p["sides"].values() if m != "trap")
        model_side = _side(key, num, model)
        trap_side = "A" if model_side == "B" else "B"
        responses[num] = {
            "made_up": {"A": "n", "B": "n"},
            "preference": model_side if traps == "peor" else trap_side,
        }
    if complete:
        assert len(responses) == len(key["pairs"])
    return {"sheet": key["sheet"], "sha256": key["sha256"], "answers": responses}


def test_sheet_gives_nobody_away(tmp_path):
    # Si el generador para antes de escribir (su propia guarda contra repetidos), el test lo dice con
    # un assert y no con una excepcion suelta.
    generated, stopped = None, None
    try:
        generated = _generate_to_disk(tmp_path)
    except SystemExit as exc:
        stopped = exc
    assert generated is not None, f"el generador no llego a escribir la hoja: {stopped}"
    sheet, key, _rules, paths = generated
    html_ = paths["html"].read_text(encoding="utf-8")
    md = paths["md"].read_text(encoding="utf-8")
    key_txt = paths["key"].read_text(encoding="utf-8")
    # Control positivo de la busqueda: la clave SI lleva los nombres; si no, el test no buscaria nada.
    assert L26 in key_txt and LQW in key_txt
    tells = [
        x
        for x in (L26, LQW, "label_26b", "label_qwen", "sides", "trap_kind")
        if x in html_ or x in md
    ]
    assert not tells, tells
    # Ningun diff ni mensaje sale dos veces.
    texts = [t for pair_ in sheet["pairs"] for t in (pair_["diff"], pair_["A"], pair_["B"])]
    repeated = [t for t in texts if md.count(t.strip("\n")) != 1]
    assert not repeated, repeated[:1]
    assert len(set(texts)) == len(texts)
    # Las trampas copian la forma del mensaje con el que se emparejan.
    traps = [(n, p) for n, p in key["pairs"].items() if p["kind"] == "trap"]
    assert len(traps) == 3
    by_num = {pair_["num"]: pair_ for pair_ in sheet["pairs"]}
    for num, p in traps:
        trap_side = "A" if p["sides"]["A"] == "trap" else "B"
        other_side = "B" if trap_side == "A" else "A"
        trap, pair = by_num[num][trap_side], by_num[num][other_side]
        assert pair_sheet.shape(trap) == pair_sheet.shape(pair)
        # Y la trampa no se reconoce por mal escrita: ni viñetas que empiezan en minuscula tras
        # partir una frase, ni una viñeta cortada.
        assert pair_sheet.body_defects(trap, pair) == [], (num, trap)
        assert pair_sheet.uses_final_scoring(trap) == pair_sheet.uses_final_scoring(pair)
    # Y entre los 3 pares hay mensajes con cuerpo: el control no es de una linea contra una linea.
    assert any(pair_sheet.shape(by_num[n][_side(key, n, L26)])[0] for n, _ in traps)


def test_key_not_next_to_sheet(tmp_path):
    _sheet_, _key, _rules, paths = _generate_to_disk(tmp_path)
    sheet_dir_path = tmp_path / "sheet"
    assert not (sheet_dir_path / "key-1.json").exists()
    assert not list(sheet_dir_path.glob("clave*"))
    assert paths["key"].is_file() and paths["key"].parent == tmp_path / "key"
    with pytest.raises(SystemExit, match="otra carpeta|carpeta de la hoja"):
        pair_sheet.write_sheet(_sheet_, _key, _rules, tmp_path / "x", tmp_path / "x")


def test_generated_sheet_not_overwritten(tmp_path):
    sheet, key, rules, _ = _sheet(tmp_path)
    pair_sheet.write_sheet(sheet, key, rules, tmp_path / "sheet", tmp_path / "key")
    with pytest.raises(SystemExit, match="ya existen"):
        pair_sheet.write_sheet(sheet, key, rules, tmp_path / "sheet", tmp_path / "key")


def test_same_seed_same_sheet_and_traps_not_always_same_positions(tmp_path):
    h1, c1, _, _ = _sheet(tmp_path, seed=11)
    h2, c2, _, _ = _sheet(tmp_path, seed=11)
    assert h1 == h2 and c1 == c2
    total = len(h1["pairs"])
    assert total == N_REAL + 3
    all_ones = set()
    for seed in range(1, 9):
        _, key, _, _ = _sheet(tmp_path, seed=seed)
        positions = sorted(int(n) for n, p in key["pairs"].items() if p["kind"] == "trap")
        assert positions != list(range(total - 2, total + 1)), f"semilla {seed}: trampas al final"
        all_ones.add(tuple(positions))
    assert len(all_ones) > 1
    # Otra semilla da otra hoja (y otro sha256).
    assert _sheet(tmp_path, seed=12)[0]["id"] != h1["id"]


def test_trap_copies_shape_of_paired_message():
    trap = {"subject": "docs: algo", "body": TRAP_BODY}
    no_body = pair_sheet.shaped_trap(trap, "feat: x")
    assert no_body == "docs: algo"
    with_two = pair_sheet.shaped_trap(trap, "feat: x\n\n- uno\n- dos")
    assert with_two == "docs: algo\n\n- cuerpo uno\n- cuerpo dos"
    # Sin linea en blanco y sin viñetas en el modelo: tampoco la lleva la trampa.
    prose = pair_sheet.shaped_trap(trap, "feat: x\nuna linea\notra linea")
    assert prose == "docs: algo\n- cuerpo uno\n- cuerpo dos"
    # Como mucho 5 lineas, aunque el modelo escriba 8.
    long = "feat: x\n\n" + "\n".join(f"- l{i}" for i in range(8))
    assert pair_sheet.shape(pair_sheet.shaped_trap(trap, long)) == (True, 5)
    assert pair_sheet.shape(long) == (True, 5)


def test_repeated_message_in_sheet_stops_generator(tmp_path):
    cases, records, traps, rules = _scenario(tmp_path)
    for r in records:  # el mismo mensaje para dos casos distintos
        if r["case"] in ("k1", "k2") and r["label"] == L26:
            r["response"] = "feat: identico"
    with pytest.raises(SystemExit, match="dos veces"):
        pair_sheet.build_commit_sheet(
            cases=cases,
            sources=tmp_path / "fuentes",
            records=records,
            traps=traps,
            rules=rules,
            case_set_item=1,
            number=1,
            seed=1,
            label_26b=L26,
            label_qwen=LQW,
        )


# --- El reparto de lados y la forma de las trampas --------------------------------------------------

# 1781 es una semilla que, con un sorteo independiente por par, deja al 26B en A 23 veces de 30.
SEEDS = (1781, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1115541376)
# Las trampas congeladas, normalizadas como las lee `pair_sheet` (el fichero sigue en el formato viejo).
REAL_SETS = pair_sheet.LEGACY_NAMES.normalize_affinity_traps(
    json.loads(
        (ROOT / "benchmarks" / "afinidad-2026-10" / "trampas.json").read_text(encoding="utf-8")
    )
)["sets"]


def test_side_split_with_balanced_permutation(tmp_path):
    # Con 30 pares reales, cada modelo queda en A exactamente 15 veces, sea cual sea la semilla. Con un
    # sorteo independiente por par, el 26B quedo en A 23 veces de 30 (p = 0,005) y la hoja salia
    # «A largo, B corto» casi siempre.
    for seed in SEEDS:
        _, key, _rules, _ = _sheet(tmp_path, seed=seed, n_real=30)
        real = [p for p in key["pairs"].values() if p["kind"] == "real"]
        assert len(real) == 30
        from_26b_in_a = sum(p["sides"]["A"] == L26 for p in real)
        assert from_26b_in_a == 15, f"semilla {seed}: el 26B esta en A {from_26b_in_a} veces de 30"
        assert sum(p["sides"]["A"] == LQW for p in real) == 15
    # Con un numero impar de pares, la diferencia es como mucho 1.
    for seed in SEEDS:
        _, key, _rules, _ = _sheet(tmp_path, seed=seed, n_real=11)
        real = [p for p in key["pairs"].values() if p["kind"] == "real"]
        from_26b_in_a = sum(p["sides"]["A"] == L26 for p in real)
        assert abs(from_26b_in_a - (len(real) - from_26b_in_a)) <= 1, seed


def test_trap_and_pair_also_split_without_bias(tmp_path):
    # Tres trampas no se pueden partir por la mitad: el lado de la trampa y el modelo con el que se
    # empareja salen 1-2 o 2-1, nunca 0-3 ni 3-0.
    seen_set = set()
    for seed in SEEDS:
        _, key, _rules, _ = _sheet(tmp_path, seed=seed)
        traps = [p for p in key["pairs"].values() if p["kind"] == "trap"]
        assert len(traps) == 3
        in_a = sum(p["sides"]["A"] == "trap" for p in traps)
        assert in_a in (1, 2), f"semilla {seed}: la trampa esta en A {in_a} veces de 3"
        pairs = [next(m for m in p["sides"].values() if m != "trap") for p in traps]
        assert pairs.count(L26) in (1, 2), f"semilla {seed}: parejas {pairs}"
        seen_set.add(in_a)
    assert seen_set == {
        1,
        2,
    }  # el lado de la trampa no esta fijo: ninguna de las dos opciones falta


# Lo que escribia la regla de forma antes: cada LINEA FISICA del cuerpo pasaba a ser una viñeta. El
# cuerpo es el de la trampa del par 21 de la primera hoja: un parrafo real partido a 80 columnas.
SPLIT_PARAGRAPH_BODY = [
    "Era el ultimo fleco manual del release: release.py no la mencionaba y ningun",
    "workflow la tocaba (pages.yml publica site/, no docs/). Medido clonandola:",
    "los ONCE ficheros divergidos -Repo-hardening 291 lineas, Daemon 154,",
    "Integration-install 142- y congelada desde el 28 de julio, con 0.18.0, 0.18.1",
    "y 0.19.0 publicadas encima.",
]
PAIR_WITH_BULLETS = (
    "chore(sdd): cerrar cambios pendientes\n\n- Cambia el estado de varios cambios a `closed`.\n"
    "- Aprueba el gate de `memory` en todos los estados.\n- Registra la evidencia de vaciado.\n"
    "- Anade las transiciones finales al historial."
)


def _old_shape_trap(trap, pair_message):
    """La regla de forma de antes de esta correccion, tal cual: corta por lineas fisicas."""
    _subject, model_body, separate = pair_sheet.split_message(pair_message)
    n = min(len(model_body), pair_sheet.MAX_BODY_LINES)
    lines = [str(x) for x in trap["body"]][:n]
    if sum(x.lstrip().startswith(("- ", "* ")) for x in model_body) * 2 >= len(model_body):
        lines = [x if x.lstrip().startswith(("- ", "* ")) else f"- {x}" for x in lines]
    return "\n".join([str(trap["subject"]), *([""] if separate else []), *lines])


def test_old_rule_splits_bullets_and_guard_sees_it():
    trap = {"subject": "feat(wiki): algo", "body": SPLIT_PARAGRAPH_BODY}
    old_one = _old_shape_trap(trap, PAIR_WITH_BULLETS)
    defects = pair_sheet.body_defects(old_one)
    # Mutante: la regla vieja. Dispara los dos defectos, uno por cada viñeta partida.
    assert any("empieza en minuscula" in d and "workflow la tocaba" in d for d in defects), defects
    assert any("termina cortada" in d and "0.18.1" in d for d in defects), defects
    assert len(defects) >= 6, defects
    # La regla nueva, con el mismo cuerpo: viñetas que son frases enteras y ningun defecto.
    new_one = pair_sheet.shaped_trap(trap, PAIR_WITH_BULLETS)
    assert pair_sheet.body_defects(new_one) == [], new_one
    body = pair_sheet.split_message(new_one)[1]
    assert len(body) == 2 and all(x.startswith("- ") for x in body)
    assert body[0] == (
        "- Era el ultimo fleco manual del release: release.py no la mencionaba y ningun workflow "
        "la tocaba (pages.yml publica site/, no docs/)."
    )


def test_body_guard_tells_well_written_from_cut():
    good = (
        "docs: x\n\n- Una frase entera.\n- `ruta/al/fichero.py` queda como estaba.\n- Dice «algo»."
    )
    assert pair_sheet.body_defects(good) == []
    assert pair_sheet.body_defects("docs: x\n\n- empieza abajo.") == [
        "empieza en minuscula: '- empieza abajo.'"
    ]
    assert pair_sheet.body_defects("docs: x\n\n- Termina en la") == [
        "termina cortada: '- Termina en la'"
    ]
    # Sin viñetas tambien: cada linea de cuerpo es una unidad.
    assert len(pair_sheet.body_defects("docs: x\nuna\nDos.")) == 2
    # Sin cuerpo no hay nada que revisar.
    assert pair_sheet.body_defects("docs: solo asunto") == []


def test_body_units_are_whole_sentences_or_bullets_never_physical_lines():
    units_list = pair_sheet.body_units(
        [
            "Primera frase que se parte en",
            "dos lineas. Segunda frase. Tercera: con (pages.yml), release.py y 0.18.0.",
            "- Una viñeta que sigue en",
            "  otra linea.",
            "- Otra viñeta.",
            "",
            "Cola de texto.",
        ]
    )
    assert units_list == [
        "Primera frase que se parte en dos lineas.",
        "Segunda frase.",
        "Tercera: con (pages.yml), release.py y 0.18.0.",
        "- Una viñeta que sigue en otra linea.",
        "- Otra viñeta.",
        "Cola de texto.",
    ]
    # Al recortar se quitan unidades enteras: con 2 lineas de pareja salen las dos primeras.
    trap = {"subject": "docs: algo", "body": SPLIT_PARAGRAPH_BODY}
    two = pair_sheet.shaped_trap(trap, "feat: x\n\n- Uno.\n- Dos.")
    assert pair_sheet.split_message(two)[1] == [
        (
            "- Era el ultimo fleco manual del release: release.py no la mencionaba y ningun workflow "
            "la tocaba (pages.yml publica site/, no docs/)."
        ),
        (
            "- Medido clonandola: los ONCE ficheros divergidos -Repo-hardening 291 lineas, Daemon "
            "154, Integration-install 142- y congelada desde el 28 de julio, con 0.18.0, 0.18.1 y "
            "0.19.0 publicadas encima."
        ),
    ]


def test_generator_stops_if_trap_recognizable_by_bad_writing(tmp_path):
    cases, records, traps, rules = _scenario(tmp_path)
    traps["sets"][0]["traps"][1]["body"] = ["corta y sin final", "Otra frase."]
    with pytest.raises(SystemExit, match="mal escrita"):
        pair_sheet.build_commit_sheet(
            cases=cases,
            sources=tmp_path / "fuentes",
            records=records,
            traps=traps,
            rules=rules,
            case_set_item=1,
            number=1,
            seed=3,
            label_26b=L26,
            label_qwen=LQW,
        )


PAIR_WITHOUT_PERIODS = (
    "chore(sdd): cerrar cambios pendientes\n\n- Actualizar estado de cambios a 'closed'\n"
    "- Aprobar puertas de memoria y conformidad\n- Registrar evidencia de cierre"
)
TRAP_WITH_PERIODS = {
    "subject": "docs: algo",
    "body": ["Primera frase entera.", "Segunda frase entera.", "Tercera frase entera."],
}


def test_trap_copies_final_punctuation_of_its_pair():
    # Pareja sin puntos: la trampa tampoco los lleva.
    without = pair_sheet.shaped_trap(TRAP_WITH_PERIODS, PAIR_WITHOUT_PERIODS)
    assert pair_sheet.split_message(without)[1] == [
        "- Primera frase entera",
        "- Segunda frase entera",
        "- Tercera frase entera",
    ]
    assert not pair_sheet.uses_final_scoring(without)
    assert pair_sheet.body_defects(without, PAIR_WITHOUT_PERIODS) == []
    # Pareja con puntos: los conserva.
    with_ = pair_sheet.shaped_trap(TRAP_WITH_PERIODS, PAIR_WITH_BULLETS)
    assert all(x.endswith(".") for x in pair_sheet.split_message(with_)[1])
    assert pair_sheet.uses_final_scoring(with_)
    # Mutante: la trampa que NO copia la puntuacion (lleva los puntos con una pareja sin ellos).
    not_copied = (
        "docs: algo\n\n- Primera frase entera.\n- Segunda frase entera.\n- Tercera frase entera."
    )
    assert pair_sheet.uses_final_scoring(not_copied) != pair_sheet.uses_final_scoring(
        PAIR_WITHOUT_PERIODS
    )
    defects = pair_sheet.body_defects(not_copied, PAIR_WITHOUT_PERIODS)
    assert any("puntuacion final no es la de la pareja" in d for d in defects), defects


def test_no_final_mark_only_if_pair_lacks_it_and_whole_word():
    ok = "docs: x\n\n- Cierra el estado de la tarea\n- Aprueba la puerta"
    assert pair_sheet.body_defects(ok, PAIR_WITHOUT_PERIODS) == []
    # Con una pareja que si cierra con punto, la misma trampa sin punto esta cortada.
    defects = pair_sheet.body_defects(ok, PAIR_WITH_BULLETS)
    assert [d.split(":")[0] for d in defects[:2]] == ["termina cortada"] * 2, defects
    # Aunque la pareja no use punto, la ultima palabra no puede ser de corte ni la linea acabar en coma.
    for cutoff in ("con", "de", "y", "a", "el", "la", "en", "que", "por", "para", "o", "del", "al"):
        bad = f"docs: x\n\n- Cierra el estado {cutoff}\n- Aprueba la puerta"
        assert pair_sheet.body_defects(bad, PAIR_WITHOUT_PERIODS) == [
            f"termina cortada: '- Cierra el estado {cutoff}'"
        ], cutoff
    comma = "docs: x\n\n- Cierra el estado,\n- Aprueba la puerta"
    assert pair_sheet.body_defects(comma, PAIR_WITHOUT_PERIODS) == [
        "termina cortada: '- Cierra el estado,'"
    ]


def test_trap_mean_bullet_at_most_1_5_times_its_pair():
    long_one = {
        "subject": "docs: algo",
        "body": [
            "Una frase corta pero entera.",
            "Otra frase corta igual de entera.",
            "Esta es una frase bastante mas larga que las otras dos de este cuerpo de prueba.",
            "Y esta tambien es una frase muy larga, escrita para pasarse del limite de largo.",
            "La ultima es corta.",
        ],
    }
    pair = (
        "feat: x\n\n- Cierra el estado de la tarea\n- Aprueba la puerta de memoria\n"
        "- Registra la evidencia"
    )
    limit = pair_sheet.MAX_LENGTH_FACTOR * pair_sheet.mean_bullet_length(pair)
    message = pair_sheet.shaped_trap(long_one, pair)
    # Las tres primeras pasan del limite; se eligen las tres MAS CORTAS, enteras y en su orden.
    assert pair_sheet.split_message(message)[1] == [
        "- Una frase corta pero entera",
        "- Otra frase corta igual de entera",
        "- La ultima es corta",
    ]
    assert pair_sheet.mean_bullet_length(message) <= limit
    assert pair_sheet.body_defects(message, pair) == []
    # Mutante: la trampa con frases largas (sin elegir las cortas) se pasa del limite.
    long_ones = "docs: algo\n\n" + "\n".join(f"- {x[:-1]}" for x in long_one["body"][1:4])
    defects = pair_sheet.body_defects(long_ones, pair)
    assert any("viñeta media" in d for d in defects), defects
    # Si con frases enteras no se puede (solo hay frases largas), la guarda lo dice y no se fuerza.
    long_only = {"subject": "docs: algo", "body": long_one["body"][2:4]}
    forced = pair_sheet.shaped_trap(long_only, pair)
    assert any("viñeta media" in d for d in pair_sheet.body_defects(forced, pair))


REALISTIC_PAIRS = {
    "sin cuerpo": "feat: x",
    "26B, viñetas con punto": (
        "feat: x\n\n- Actualiza la versión en pyproject.toml, server.json y uv.lock.\n"
        "- Registra los cambios de la versión en el CHANGELOG.\n"
        "- Cierra el estado de la tarea en el state.json."
    ),
    "Qwen3.6, viñetas sin punto": (
        "feat: x\n\n- Actualizar estado de cambios a 'closed'\n"
        "- Aprobar puertas de memoria y conformidad\n- Registrar evidencia de cierre"
    ),
    "Qwen3.6, ocho viñetas sin punto": (
        "feat: x\n\n"
        + "\n".join(
            f"- Registrar el cambio numero {i} del diff en el repositorio" for i in range(8)
        )
    ),
    "dos viñetas sin punto": "feat: x\n\n- Cierra el estado de la tarea en el state.json\n- Aprueba la puerta de memoria y conformidad",
    "prosa sin punto": "feat: x\nActualizar el estado de la tarea en el state.json\nRegistrar la evidencia de cierre del cambio",
}


@pytest.mark.parametrize("case_set_item", REAL_SETS, ids=lambda j: f"juego-{j['set']}")
def test_nine_versioned_traps_are_whole_sentences_with_any_pair(case_set_item):
    assert len(case_set_item["traps"]) == 3
    for entry in case_set_item["traps"]:
        # Cada elemento del cuerpo es una unidad entera: ni trozos ni dos frases juntas.
        assert pair_sheet.body_units(entry["body"]) == entry["body"], entry["case"]
        assert 1 <= len(entry["body"]) <= 5
        for name, pair in REALISTIC_PAIRS.items():
            message = pair_sheet.shaped_trap(entry, pair)
            defects = pair_sheet.body_defects(message, pair)
            assert defects == [], (entry["case"], name, message, defects)
            assert pair_sheet.shape(message) == pair_sheet.shape(pair), entry["case"]
            assert pair_sheet.uses_final_scoring(message) == pair_sheet.uses_final_scoring(pair), (
                entry["case"],
                name,
            )
    same_zone = next(t for t in case_set_item["traps"] if t["kind"] == "same-zone")
    assert same_zone["source_body"] == "real-reescrito"


# --- Leer las respuestas ---------------------------------------------------------------------------


def test_read_commit_accepts_full_sheet_and_unmasks_with_key(tmp_path):
    sheet, key, rules, _ = _sheet(tmp_path)
    r = _responses(key, c=6, v=2, ties=2, invents=1)
    judgement, missing = pair_sheet.read_commit(r, key, rules)
    assert missing == []
    assert judgement["partial"] is False and judgement["sheet"] == sheet["id"]
    real = [p for p in judgement["pairs"].values() if p["kind"] == "real"]
    assert sum(p["sides"][p["preference"]] == L26 for p in real if p["preference"] != "=") == 6
    assert sum(p["preference"] == "=" for p in real) == 2


def test_optional_questions_come_from_rules_json(tmp_path):
    _, key, rules, _ = _sheet(tmp_path)
    r = _responses(key, c=10)
    # Opcionales (la propuesta del usuario): sin «lo principal» ni «especifico» se acepta.
    accepted_one = pair_sheet.read_commit(r, key, rules)[1] == []
    assert accepted_one, "con principal y especifico opcionales, la hoja sin ellas se acepta"
    # Obligatorias: la misma hoja ya no se acepta, y dice que falta.
    required = {**rules, "optional_questions": []}
    _, missing = pair_sheet.read_commit(r, key, required)
    assert missing and all("principal" in f or "specific" in f for f in missing)
    assert len(missing) == 4 * len(key["pairs"])
    # «Inventa» no puede ser opcional: el fichero de reglas se rechaza.
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({**rules, "optional_questions": ["inventa"]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="inventa"):
        pair_sheet.read_rules(path)
    path.write_text(json.dumps({**rules, "optional_questions": ["preference"]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="optional_questions"):
        pair_sheet.read_rules(path)


def test_missing_required_says_which_and_produces_nothing(tmp_path, capsys):
    _, key, rules, _ = _sheet(tmp_path)
    r = _responses(key, c=10)
    num = min(r["answers"])
    side = min(r["answers"][num]["made_up"])
    del r["answers"][num]["made_up"][side]
    _, missing = pair_sheet.read_commit(r, key, rules)
    assert missing == [f"par {num}: inventa {side}"]
    # Por la linea de ordenes: error, sin fichero de salida.
    (tmp_path / "r.json").write_text(json.dumps(r), encoding="utf-8")
    (tmp_path / "key.json").write_text(json.dumps(key), encoding="utf-8")
    (tmp_path / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    arguments = [
        "read-commit",
        "--key",
        str(tmp_path / "key.json"),
        "--rules",
        str(tmp_path / "rules.json"),
        "--answers",
        str(tmp_path / "r.json"),
        "--output",
        str(tmp_path / "judgement.json"),
    ]
    assert pair_sheet.main(arguments) == 1
    assert not (tmp_path / "judgement.json").exists()
    assert f"par {num}: inventa {side}" in capsys.readouterr().err


def test_answers_from_other_sheet(tmp_path):
    # Los mismos pares con otra semilla: las respuestas estan COMPLETAS y todos los numeros de par
    # existen, asi que solo el sha256 puede distinguirlas.
    _, key_a, rules, _ = _sheet(tmp_path, seed=1)
    _, key_b, _, _ = _sheet(tmp_path, seed=2)
    answers_to = _responses(key_a, c=10, complete=True)
    assert pair_sheet.read_commit(answers_to, key_a, rules)[1] == []  # control positivo
    with pytest.raises(SystemExit, match="sha256"):
        pair_sheet.read_commit(answers_to, key_b, rules)


def test_invalid_values_and_unknown_pairs(tmp_path):
    _, key, rules, _ = _sheet(tmp_path)
    r = _responses(key, c=10)
    num = min(r["answers"])
    r["answers"][num]["preference"] = "C"
    with pytest.raises(SystemExit, match="no es valido para preferencia"):
        pair_sheet.read_commit(r, key, rules)
    r = _responses(key, c=10)
    r["answers"]["99"] = {"preference": "A"}
    with pytest.raises(SystemExit, match="99"):
        pair_sheet.read_commit(r, key, rules)


# --- Parada anticipada -----------------------------------------------------------------------------


def _stopped(tmp_path, **kw):
    _, key, rules, _ = _sheet(tmp_path)
    judgement, _ = pair_sheet.read_commit(_responses(key, **kw), key, rules, partial=True)
    output = pair_sheet.can_stop(judgement, rules)
    assert not any(x in output for x in ("26B", "Qwen", "qwen", "aprob", L26, LQW)), output
    return output


def test_early_stop(tmp_path):
    # Decidido: las trampas valen y el 26B ya paso del maximo (2) de «inventa».
    assert _stopped(tmp_path, c=5, invents=3) == "puedes parar"
    # Sin decidir: `v - c` (3) es igual a los pares que faltan (3): aun podria empatar y no perder.
    output = _stopped(tmp_path, v=3, ties=4)
    assert output == "sigue"
    # Con `v - c` mayor que los que faltan, ya no puede alcanzar a Qwen.
    assert _stopped(tmp_path, v=6) == "puedes parar"
    # Las trampas sin contestar: «sigue» aunque el 26B ya se haya pasado.
    output = _stopped(tmp_path, c=5, invents=3, traps=None)
    assert output == "sigue"
    # Una hoja que no vale (la trampa preferida en las 3): tampoco se puede parar.
    assert _stopped(tmp_path, c=5, invents=3, traps="mejor") == "sigue"


def test_read_commit_partial_answers_one_word(tmp_path, capsys):
    _, key, rules, _ = _sheet(tmp_path)
    (tmp_path / "key.json").write_text(json.dumps(key), encoding="utf-8")
    (tmp_path / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    for name, kw, expected in (
        ("a", {"c": 5, "invents": 3}, "puedes parar"),
        ("b", {"c": 5}, "sigue"),
    ):
        (tmp_path / f"{name}.json").write_text(json.dumps(_responses(key, **kw)), encoding="utf-8")
        capsys.readouterr()
        rc = pair_sheet.main(
            [
                "read-commit",
                "--partial",
                "--key",
                str(tmp_path / "key.json"),
                "--rules",
                str(tmp_path / "rules.json"),
                "--answers",
                str(tmp_path / f"{name}.json"),
            ]
        )
        assert rc == 0
        assert capsys.readouterr().out.strip() == expected


# --- La hoja .md y la pagina -----------------------------------------------------------------------


def _fill_md(md, responses):
    """Contesta la hoja `.md` a mano: escribe el valor detras de cada pregunta, fuera de las vallas."""
    output, pair, fence = [], None, None
    names = {"Inventa": "made_up", "Lo principal": "principal", "Específico": "specific"}
    for line in md.split("\n"):
        if fence is not None:
            output.append(line)
            fence = None if line == fence else fence
            continue
        if line.startswith("```"):
            fence = line[: len(line) - len(line.lstrip("`"))]
            output.append(line)
            continue
        if line.startswith("## Par "):
            pair = line.split()[-1]
        elif pair is not None and pair in responses:
            given = responses[pair]
            if line.startswith("Mejor (A/B/=):") and given.get("preference"):
                line = f"Mejor (A/B/=): {given['preference']}"
            for label_text, key_ in names.items():
                for side in "AB":
                    if line.startswith(f"{label_text} {side} ") and given.get(key_, {}).get(side):
                        line = line.split(":")[0] + f": {given[key_][side]}"
        output.append(line)
    return "\n".join(output)


def test_md_sheet_answered_by_hand_is_parsed(tmp_path):
    # Un mensaje con una linea que parece una respuesta: dentro de la valla no puede votar.
    _, key, rules, paths = _generate_to_disk(tmp_path, extra_message="\nMejor (A/B/=): A")
    md = paths["md"].read_text(encoding="utf-8")
    empty = pair_sheet.md_answers(md)
    assert empty["sha256"] == key["sha256"]
    assert all(not p.get("preference") for p in empty["answers"].values())
    r = _responses(key, c=7, v=3, invents=2)
    read_ones = pair_sheet.md_answers(_fill_md(md, r["answers"]))
    judgement, missing = pair_sheet.read_commit(read_ones, key, rules)
    assert missing == []
    num = next(iter(r["answers"]))
    assert judgement["pairs"][num]["preference"] == r["answers"][num]["preference"]


def test_page_exports_what_read_commit_accepts(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no esta en el PATH")
    _, key, rules, paths = _generate_to_disk(tmp_path)
    html_ = paths["html"].read_text(encoding="utf-8")
    logic = html_.split('<script id="logica">', 1)[1].split("</script>", 1)[0]
    data = json.loads(
        html_.split('<script type="application/json" id="datos">', 1)[1].split("</script>", 1)[0]
    )
    assert data["id"] == key["sha256"]
    state = {}
    for pair in data["pairs"]:
        state[pair["num"]] = {"made_up.A": "n", "made_up.B": "s", "preference": "A"}
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    program = tmp_path / "probe.js"
    program.write_text(
        logic
        + "\nconst fs = require('fs');\n"
        + f"const data = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'data.json'))}, 'utf8'));\n"
        + f"const state = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'state.json'))}, 'utf8'));\n"
        + "console.log(JSON.stringify({exported: exportar(state, data, false), missing: missing(state, data)}));\n",
        encoding="utf-8",
    )
    output = json.loads(
        subprocess.run([node, str(program)], capture_output=True, text=True, check=True).stdout
    )
    assert output["missing"] == []
    _, missing = pair_sheet.read_commit(output["exported"], key, rules)
    assert missing == [], missing
    # Con una obligatoria menos, el lector dice cual falta, y el contador de la pagina tambien.
    del state["03"]["made_up.B"]
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    output = json.loads(
        subprocess.run([node, str(program)], capture_output=True, text=True, check=True).stdout
    )
    assert output["missing"] == [["03", "made_up.B"]]
    _, missing = pair_sheet.read_commit(output["exported"], key, rules)
    assert missing == ["par 03: inventa B"]


def test_page_is_self_contained_and_has_no_names(tmp_path):
    _, _, _, paths = _generate_to_disk(tmp_path)
    html_ = paths["html"].read_text(encoding="utf-8")
    for external in ("http://", "https://", "<link", " src=", "@import", "url("):
        assert external not in html_, external
    assert "Descargar respuestas" in html_ and "¿Puedo parar ya?" in html_
    assert "localStorage" in html_ and "Faltan" in html_


# --- Sin el paquete ----------------------------------------------------------------------------------


def test_does_not_import_package(tmp_path):
    """`generate-commit` y `read-commit` corren con `local_delegate` bloqueado: importarlo cargaria
    `server.py` mientras otras tareas lo editan."""
    cases, records, traps, rules = _scenario(tmp_path)
    (tmp_path / "cases.json").write_text(
        json.dumps({"schema_version": 2, "cases": list(cases.values())}), encoding="utf-8"
    )
    (tmp_path / "traps.json").write_text(json.dumps(traps), encoding="utf-8")
    (tmp_path / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    (tmp_path / "r.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    def run(arguments):
        program = (
            "import runpy, sys\n"
            "sys.modules['local_delegate'] = None\n"
            f"sys.argv = ['pair_sheet.py'] + {arguments!r}\n"
            f"runpy.run_path(r'{ROOT / 'scripts' / 'pair_sheet.py'}', run_name='__main__')\n"
        )
        return subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, timeout=60
        )

    proc = run(
        [
            "generate-commit",
            "--cases",
            str(tmp_path / "cases.json"),
            "--traps",
            str(tmp_path / "traps.json"),
            "--rules",
            str(tmp_path / "rules.json"),
            "--seed",
            "3",
            "--label-26b",
            L26,
            "--label-qwen",
            LQW,
            "--sheet-dir",
            str(tmp_path / "sheet"),
            "--key-dir",
            str(tmp_path / "key"),
            str(tmp_path / "r.jsonl"),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    key = json.loads((tmp_path / "key" / "key-1.json").read_text(encoding="utf-8"))
    (tmp_path / "partial.json").write_text(
        json.dumps(_responses(key, c=5, invents=3)), encoding="utf-8"
    )
    proc = run(
        [
            "read-commit",
            "--partial",
            "--key",
            str(tmp_path / "key" / "key-1.json"),
            "--rules",
            str(tmp_path / "rules.json"),
            "--answers",
            str(tmp_path / "partial.json"),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "puedes parar"


# --- Lectura dual de lo congelado de la hoja 1 (ola A10b-4) -----------------------------------------

FROZEN_AFFINITY = ROOT / "benchmarks" / "afinidad-2026-10"


def test_the_frozen_key_answers_and_rules_give_a_complete_judgement_in_the_new_format():
    key = json.loads((FROZEN_AFFINITY / "clave" / "clave-1.json").read_text(encoding="utf-8"))
    answers = json.loads(
        (FROZEN_AFFINITY / "hoja" / "respuestas-1.json").read_text(encoding="utf-8")
    )
    # Control: lo congelado sigue con los nombres de antes; si no, el test no probaria nada.
    assert "pares" in key and "respuestas" in answers
    rules = pair_sheet.read_rules(FROZEN_AFFINITY / "reglas.json")
    assert rules["optional_questions"] == ["principal", "specific"]
    judgement, missing = pair_sheet.read_commit(answers, key, rules)
    assert missing == []
    assert len(judgement["pairs"]) == len(key["pares"]) == 33
    # El par trampa y su lado (lote 3): lo congelado dice `trampa` en `tipo` y en `lados`.
    assert {p["tipo"] for p in key["pares"].values()} == {"real", "trampa"}
    assert {p["kind"] for p in judgement["pairs"].values()} == {"real", "trap"}
    traps = [p for p in judgement["pairs"].values() if p["kind"] == "trap"]
    assert len(traps) == 3 and all("trap" in p["sides"].values() for p in traps), traps
    assert not any("trampa" in p["sides"].values() for p in judgement["pairs"].values())
    for pair in judgement["pairs"].values():
        assert {"case", "sides", "made_up", "principal", "specific", "preference"} <= set(pair)
        assert pair["preference"] in {"A", "B", "="}


def test_the_frozen_traps_are_read_in_the_new_format():
    raw = json.loads((FROZEN_AFFINITY / "trampas.json").read_text(encoding="utf-8"))
    assert "juegos" in raw
    traps = pair_sheet.LEGACY_NAMES.normalize_affinity_traps(raw)
    assert {"shape_rule", "same-zone", "secondary", "generic", "sets"} <= set(traps)
    entries = [t for item in traps["sets"] for t in item["traps"]]
    assert [item["set"] for item in traps["sets"]] == [1, 2, 3]
    assert {t["kind"] for t in entries} == {"same-zone", "secondary", "generic"}
    assert all(t["subject"] and t["body"] and t["source_body"] for t in entries)
    same_zone = [t for t in entries if t["kind"] == "same-zone"]
    assert same_zone and all(set(t["subject_of"]) == {"hash", "file"} for t in same_zone)
    assert pair_sheet.LEGACY_NAMES.normalize_affinity_traps(traps) == traps
