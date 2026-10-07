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

RAIZ = Path(__file__).parents[1]


def _cargar():
    spec = importlib.util.spec_from_file_location("hoja_pares", RAIZ / "scripts" / "hoja_pares.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["hoja_pares"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


hoja_pares = _cargar()
CORPUS = {
    "caso-a": {"tool": "local_summarize", "source_file": "caso-a.md", "system": "Resume."},
    "caso-b": {"tool": "local_explain_code", "source_file": "caso-b.py.txt", "system": "Explica."},
}


def _reg(label, caso, run, calidad, respuesta=None, **kw):
    registro = {
        "label": label,
        "case": caso,
        "run": run,
        "attempt": kw.get("attempt", 1),
        "input_variant": kw.get("variante"),
        "descartada": kw.get("descartada", False),
        "score": {"quality": calidad},
    }
    if respuesta is not None or kw.get("con_respuesta", True):
        # Sin la etiqueta dentro: una respuesta real no la trae, y el test de «oculta el modelo» la
        # encontraria en el texto y no en lo que escribe la hoja.
        registro["response"] = respuesta if respuesta is not None else f"respuesta {caso} {run}"
    return registro


def _tanda(calidades_p, calidades_g, caso="caso-a"):
    return [_reg("secreto-p", caso, run, q) for run, q in enumerate(calidades_p, 1)] + [
        _reg("secreto-g", caso, run, q) for run, q in enumerate(calidades_g, 1)
    ]


def _generar(registros, casos=("caso-a",), semilla=5):
    return hoja_pares.generar(registros, CORPUS, list(casos), "secreto-p", "secreto-g", semilla)


def _rellenar(hoja, clave, elegir):
    """Escribe en cada par la eleccion que devuelve `elegir(meta_del_par)`."""
    partes = hoja.split("Mejor (A/B/=): ")
    pares = sorted(clave["pares"])
    return partes[0] + "".join(
        f"Mejor (A/B/=): {elegir(clave['pares'][par])}" + resto
        for par, resto in zip(pares, partes[1:], strict=True)
    )


def test_oculta_el_modelo_sortea_el_lado_y_empareja_la_misma_corrida():
    registros = _tanda([0.5] * 8, [1.0] * 8) + _tanda([0.5] * 8, [1.0] * 8, caso="caso-b")
    hoja, clave = _generar(registros, casos=("caso-a", "caso-b"))
    assert "secreto" not in hoja
    assert len(clave["pares"]) == 16
    assert all(
        clave["pares"][p]["A"]["label"] != clave["pares"][p]["B"]["label"] for p in clave["pares"]
    )
    # El lado se sortea: el pequeno no va siempre como A.
    assert {clave["pares"][p]["A"]["label"] for p in clave["pares"]} == {"secreto-p", "secreto-g"}
    # Y el orden de los pares se baraja: no salen agrupados por caso.
    casos = [clave["pares"][p]["case"] for p in sorted(clave["pares"])]
    assert casos != sorted(casos)
    assert "fuentes/caso-a.md" in hoja and "> Resume." in hoja


def test_solo_empareja_corridas_validas_de_las_dos_configuraciones():
    # Pequeno: corridas 1-4. Grande: 1-3 (la 4 no existe). Ademas, el ultimo intento de la 1 del
    # grande quedo anulado, la 2 del pequeno acabo sin puntuacion, y una corrida con entrada de
    # control no cuenta. Solo la corrida 3 es valida en las dos: un par, no cuatro.
    registros = _tanda([0.5, 0.5, 0.5, 0.5], [1.0, 1.0, 1.0])
    registros.append(_reg("secreto-g", "caso-a", 1, 1.0, descartada=True, attempt=2))
    registros.append(_reg("secreto-p", "caso-a", 2, None, attempt=2))
    registros.append(_reg("secreto-g", "caso-a", 2, 1.0, variante="control"))
    registros = [
        r
        for r in registros
        if not (r["label"] == "secreto-g" and r["run"] == 2 and r["input_variant"] is None)
    ]
    _hoja, clave = _generar(registros)
    assert [p["run"] for p in clave["pares"].values()] == [3]


def test_exige_respuestas_guardadas():
    registros = _tanda([0.5], [1.0])
    del registros[0]["response"]
    with pytest.raises(ValueError, match="--save-responses"):
        _generar(registros)


def test_acuerdo_cuenta_solo_donde_la_metrica_prefiere_y_el_empate_humano_no_es_acuerdo():
    # 5 pares: en 4 la metrica prefiere al grande (1,0 contra 0,5), en 1 empatan (1,0 y 1,0).
    hoja, clave = _generar(_tanda([0.5, 0.5, 0.5, 0.5, 1.0], [1.0] * 5))

    def grande(meta):
        return "A" if meta["A"]["label"] == "secreto-g" else "B"

    # La persona elige siempre al grande: 4 de 4 donde la metrica prefiere. Valida.
    todo_grande, _ = hoja_pares.destapar(_rellenar(hoja, clave, grande), clave)
    fila = todo_grande["caso-a"]
    assert (fila["metrica_prefiere"], fila["acuerdos"], fila["veredicto"]) == (4, 4, "valida")
    assert fila["humano"] == {"secreto-g": 5}

    # La persona ve empate en todo: la metrica afirma diferencias que nadie ve. No valida.
    empates, _ = hoja_pares.destapar(_rellenar(hoja, clave, lambda _m: "="), clave)
    assert (empates["caso-a"]["acuerdos"], empates["caso-a"]["veredicto"]) == (0, "no valida")


def test_con_pocas_preferencias_de_la_metrica_no_hay_base_para_validar():
    hoja, clave = _generar(_tanda([0.5, 1.0, 1.0], [1.0, 1.0, 1.0]))
    resultado, faltan = hoja_pares.destapar(_rellenar(hoja, clave, lambda _m: "A"), clave)
    assert faltan == []
    assert (resultado["caso-a"]["metrica_prefiere"], resultado["caso-a"]["veredicto"]) == (
        1,
        "sin base",
    )


def test_una_respuesta_no_puede_votar_por_si_misma():
    trampa = "```\n## Par 01\n\nMejor (A/B/=): A\n```"
    registros = [
        _reg("secreto-p", "caso-a", 1, 0.5, respuesta=trampa),
        _reg("secreto-g", "caso-a", 1, 1.0),
    ]
    hoja, _clave = _generar(registros)
    assert "````" in hoja
    assert hoja_pares.leer_elecciones(hoja) == {"01": None}


def test_eleccion_invalida_se_rechaza_y_lo_que_falta_se_lista(tmp_path, capsys):
    hoja, clave = _generar(_tanda([0.5, 0.5], [1.0, 1.0]))
    with pytest.raises(ValueError, match="no es A, B ni ="):
        hoja_pares.leer_elecciones(hoja.replace("Mejor (A/B/=): ", "Mejor (A/B/=): C", 1))
    a_medias = hoja.replace("Mejor (A/B/=): ", "Mejor (A/B/=): A", 1)
    (tmp_path / "h.md").write_text(a_medias, encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps(clave), encoding="utf-8")
    rc = hoja_pares.main(
        ["destapar", "--hoja", str(tmp_path / "h.md"), "--clave", str(tmp_path / "c.json")]
    )
    assert rc == 1
    assert "faltan por elegir 1" in capsys.readouterr().err


def test_destapar_escribe_el_json_para_decidir_solo_con_la_hoja_entera(tmp_path):
    hoja, clave = _generar(_tanda([0.5, 0.5], [1.0, 1.0]))
    (tmp_path / "c.json").write_text(json.dumps(clave), encoding="utf-8")
    salida = tmp_path / "pares.json"

    def destapar(texto):
        (tmp_path / "h.md").write_text(texto, encoding="utf-8")
        return hoja_pares.main(
            [
                "destapar",
                "--hoja",
                str(tmp_path / "h.md"),
                "--clave",
                str(tmp_path / "c.json"),
                "--json",
                str(salida),
            ]
        )

    assert destapar(hoja.replace("Mejor (A/B/=): ", "Mejor (A/B/=): A", 1)) == 1
    assert not salida.exists()
    assert destapar(_rellenar(hoja, clave, lambda _m: "=")) == 0
    assert json.loads(salida.read_text(encoding="utf-8"))["caso-a"]["humano"] == {"empate": 2}


def test_generar_no_pisa_una_hoja_existente(tmp_path):
    (tmp_path / "c.json").write_text("{}", encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": []}), encoding="utf-8")
    rc = hoja_pares.main(
        [
            "generar",
            "--hoja",
            str(tmp_path / "h.md"),
            "--clave",
            str(tmp_path / "c.json"),
            "--cases",
            str(cases),
            "--pequeno",
            "p",
            "--grande",
            "g",
            "--caso",
            "x",
            str(cases),
        ]
    )
    assert rc == 2


# =====================================================================================================
# Hoja a ciegas de `local_commit_msg` (REQ-042): generate-commit y read-commit, con datos sinteticos.
# =====================================================================================================

L26, LQW = "modelo-alfa-26b", "modelo-beta-qwen"
N_REAL = 10
SHEET_RULES = {
    "version": 1,
    "max_inventa_26b": 2,
    "preguntas_opcionales": ["principal", "especifico"],
    "formato": {"primera_linea_max": 72, "prefijo": "x", "sin_adornos": {}},
    "parada_anticipada": True,
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


def _registro(label, case, text):
    return {
        "schema_version": 2,
        "label": label,
        "case": case,
        "run": 1,
        "attempt": 1,
        "outcome": "ok",
        "descartada": False,
        "response": text,
    }


def _scenario(
    tmp_path, *, optional_ones=("principal", "especifico"), extra_message=None, n_real=N_REAL
):
    """Un corpus pequeno: `n_real` casos reales y 3 trampa, con sus mensajes de los dos modelos."""
    cases, records = {}, []
    (tmp_path / "fuentes").mkdir(exist_ok=True)
    for i in range(n_real):
        cases[f"k{i}"] = {"id": f"k{i}", "source_file": f"k{i}.diff", "rol_en_hoja": "real"}
        (tmp_path / "fuentes" / f"k{i}.diff").write_text(_diff(f"k{i}"), encoding="utf-8")
        for model in (L26, LQW):
            text = _message(model, i)
            if extra_message and i == 0 and model == L26:
                text += extra_message
            records.append(_registro(model, f"k{i}", text))
    entries = []
    for j in range(3):
        cases[f"t{j}"] = {"id": f"t{j}", "source_file": f"t{j}.diff", "rol_en_hoja": "trampa"}
        (tmp_path / "fuentes" / f"t{j}.diff").write_text(_diff(f"t{j}"), encoding="utf-8")
        # El 26B cierra con punto y Qwen3.6 sin el, como en la tanda real.
        records.append(
            _registro(
                L26,
                f"t{j}",
                f"feat(trampa-{j}): alfa {j}\n\n- Detalle a de la trampa {j}.\n"
                f"- Detalle b de la trampa {j}.\n- Detalle c de la trampa {j}.",
            )
        )
        records.append(
            _registro(
                LQW,
                f"t{j}",
                f"fix(trampa-{j}): beta {j}\n\n- Detalle x de la trampa {j}\n- Detalle y de la trampa {j}",
            )
        )
        entries.append(
            {
                "caso": f"t{j}",
                "tipo": ("misma-zona", "secundario", "generico")[j],
                "asunto": f"docs: asunto de la trampa {j}",
                "cuerpo": _trap_phrases(j),
            }
        )
    traps = {"juegos": [{"juego": 1, "trampas": entries}]}
    rules = {**SHEET_RULES, "preguntas_opcionales": list(optional_ones)}
    return cases, records, traps, rules


def _hoja(tmp_path, seed=7, number=1, **kw):
    cases, records, traps, rules = _scenario(tmp_path, **kw)
    sheet, key = hoja_pares.build_commit_sheet(
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
    sheet, key, rules, _ = _hoja(tmp_path, **kw)
    paths = hoja_pares.write_sheet(sheet, key, rules, tmp_path / "hoja", tmp_path / "clave")
    return sheet, key, rules, paths


def _side(key, num, who):
    sides = key["pares"][num]["lados"]
    return "A" if sides["A"] == who else "B"


def _responses(key, *, c=0, v=0, ties=0, invents=0, traps="peor", complete=False):
    """Respuestas ya contestadas: `c` pares reales para el 26B, `v` para Qwen, `ties` en `=`,
    `invents` mensajes del 26B marcados como «inventa». El resto de pares reales queda sin contestar."""
    real = [n for n, p in sorted(key["pares"].items()) if p["tipo"] == "real"]
    requested = ["c"] * c + ["v"] * v + ["="] * ties
    responses: dict = {}
    for index, (num, who) in enumerate(zip(real, requested, strict=False)):
        l26, lq = _side(key, num, L26), _side(key, num, LQW)
        responses[num] = {
            "inventa": {l26: "s" if index < invents else "n", lq: "n"},
            "preferencia": l26 if who == "c" else lq if who == "v" else "=",
        }
    for num, p in sorted(key["pares"].items()):
        if p["tipo"] != "trampa" or traps is None:
            continue
        model = next(m for m in p["lados"].values() if m != "trampa")
        model_side = _side(key, num, model)
        trap_side = "A" if model_side == "B" else "B"
        responses[num] = {
            "inventa": {"A": "n", "B": "n"},
            "preferencia": model_side if traps == "peor" else trap_side,
        }
    if complete:
        assert len(responses) == len(key["pares"])
    return {"hoja": key["hoja"], "sha256": key["sha256"], "respuestas": responses}


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
    key_txt = paths["clave"].read_text(encoding="utf-8")
    # Control positivo de la busqueda: la clave SI lleva los nombres; si no, el test no buscaria nada.
    assert L26 in key_txt and LQW in key_txt
    tells = [
        x
        for x in (L26, LQW, "label_26b", "label_qwen", "lados", "trampa_tipo")
        if x in html_ or x in md
    ]
    assert not tells, tells
    # Ningun diff ni mensaje sale dos veces.
    texts = [t for pair_ in sheet["pares"] for t in (pair_["diff"], pair_["A"], pair_["B"])]
    repeated = [t for t in texts if md.count(t.strip("\n")) != 1]
    assert not repeated, repeated[:1]
    assert len(set(texts)) == len(texts)
    # Las trampas copian la forma del mensaje con el que se emparejan.
    traps = [(n, p) for n, p in key["pares"].items() if p["tipo"] == "trampa"]
    assert len(traps) == 3
    by_num = {pair_["num"]: pair_ for pair_ in sheet["pares"]}
    for num, p in traps:
        trap_side = "A" if p["lados"]["A"] == "trampa" else "B"
        other_side = "B" if trap_side == "A" else "A"
        trap, pair = by_num[num][trap_side], by_num[num][other_side]
        assert hoja_pares.forma(trap) == hoja_pares.forma(pair)
        # Y la trampa no se reconoce por mal escrita: ni viñetas que empiezan en minuscula tras
        # partir una frase, ni una viñeta cortada.
        assert hoja_pares.body_defects(trap, pair) == [], (num, trap)
        assert hoja_pares.uses_final_scoring(trap) == hoja_pares.uses_final_scoring(pair)
    # Y entre los 3 pares hay mensajes con cuerpo: el control no es de una linea contra una linea.
    assert any(hoja_pares.forma(by_num[n][_side(key, n, L26)])[0] for n, _ in traps)


def test_key_not_next_to_sheet(tmp_path):
    _sheet_, _key, _rules, paths = _generate_to_disk(tmp_path)
    sheet_dir_path = tmp_path / "hoja"
    assert not (sheet_dir_path / "clave-1.json").exists()
    assert not list(sheet_dir_path.glob("clave*"))
    assert paths["clave"].is_file() and paths["clave"].parent == tmp_path / "clave"
    with pytest.raises(SystemExit, match="otra carpeta|carpeta de la hoja"):
        hoja_pares.write_sheet(_sheet_, _key, _rules, tmp_path / "x", tmp_path / "x")


def test_generated_sheet_not_overwritten(tmp_path):
    sheet, key, rules, _ = _hoja(tmp_path)
    hoja_pares.write_sheet(sheet, key, rules, tmp_path / "hoja", tmp_path / "clave")
    with pytest.raises(SystemExit, match="ya existen"):
        hoja_pares.write_sheet(sheet, key, rules, tmp_path / "hoja", tmp_path / "clave")


def test_same_seed_same_sheet_and_traps_not_always_same_positions(tmp_path):
    h1, c1, _, _ = _hoja(tmp_path, seed=11)
    h2, c2, _, _ = _hoja(tmp_path, seed=11)
    assert h1 == h2 and c1 == c2
    total = len(h1["pares"])
    assert total == N_REAL + 3
    all_ones = set()
    for seed in range(1, 9):
        _, key, _, _ = _hoja(tmp_path, seed=seed)
        positions = sorted(int(n) for n, p in key["pares"].items() if p["tipo"] == "trampa")
        assert positions != list(range(total - 2, total + 1)), f"semilla {seed}: trampas al final"
        all_ones.add(tuple(positions))
    assert len(all_ones) > 1
    # Otra semilla da otra hoja (y otro sha256).
    assert _hoja(tmp_path, seed=12)[0]["id"] != h1["id"]


def test_trap_copies_shape_of_paired_message():
    trap = {"asunto": "docs: algo", "cuerpo": TRAP_BODY}
    no_body = hoja_pares.shaped_trap(trap, "feat: x")
    assert no_body == "docs: algo"
    with_two = hoja_pares.shaped_trap(trap, "feat: x\n\n- uno\n- dos")
    assert with_two == "docs: algo\n\n- cuerpo uno\n- cuerpo dos"
    # Sin linea en blanco y sin viñetas en el modelo: tampoco la lleva la trampa.
    prose = hoja_pares.shaped_trap(trap, "feat: x\nuna linea\notra linea")
    assert prose == "docs: algo\n- cuerpo uno\n- cuerpo dos"
    # Como mucho 5 lineas, aunque el modelo escriba 8.
    long = "feat: x\n\n" + "\n".join(f"- l{i}" for i in range(8))
    assert hoja_pares.forma(hoja_pares.shaped_trap(trap, long)) == (True, 5)
    assert hoja_pares.forma(long) == (True, 5)


def test_repeated_message_in_sheet_stops_generator(tmp_path):
    cases, records, traps, rules = _scenario(tmp_path)
    for r in records:  # el mismo mensaje para dos casos distintos
        if r["case"] in ("k1", "k2") and r["label"] == L26:
            r["response"] = "feat: identico"
    with pytest.raises(SystemExit, match="dos veces"):
        hoja_pares.build_commit_sheet(
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
REAL_SETS = json.loads(
    (RAIZ / "benchmarks" / "afinidad-2026-10" / "trampas.json").read_text(encoding="utf-8")
)["juegos"]


def test_side_split_with_balanced_permutation(tmp_path):
    # Con 30 pares reales, cada modelo queda en A exactamente 15 veces, sea cual sea la semilla. Con un
    # sorteo independiente por par, el 26B quedo en A 23 veces de 30 (p = 0,005) y la hoja salia
    # «A largo, B corto» casi siempre.
    for seed in SEEDS:
        _, key, _rules, _ = _hoja(tmp_path, seed=seed, n_real=30)
        real = [p for p in key["pares"].values() if p["tipo"] == "real"]
        assert len(real) == 30
        from_26b_in_a = sum(p["lados"]["A"] == L26 for p in real)
        assert from_26b_in_a == 15, f"semilla {seed}: el 26B esta en A {from_26b_in_a} veces de 30"
        assert sum(p["lados"]["A"] == LQW for p in real) == 15
    # Con un numero impar de pares, la diferencia es como mucho 1.
    for seed in SEEDS:
        _, key, _rules, _ = _hoja(tmp_path, seed=seed, n_real=11)
        real = [p for p in key["pares"].values() if p["tipo"] == "real"]
        from_26b_in_a = sum(p["lados"]["A"] == L26 for p in real)
        assert abs(from_26b_in_a - (len(real) - from_26b_in_a)) <= 1, seed


def test_trap_and_pair_also_split_without_bias(tmp_path):
    # Tres trampas no se pueden partir por la mitad: el lado de la trampa y el modelo con el que se
    # empareja salen 1-2 o 2-1, nunca 0-3 ni 3-0.
    seen_set = set()
    for seed in SEEDS:
        _, key, _rules, _ = _hoja(tmp_path, seed=seed)
        traps = [p for p in key["pares"].values() if p["tipo"] == "trampa"]
        assert len(traps) == 3
        in_a = sum(p["lados"]["A"] == "trampa" for p in traps)
        assert in_a in (1, 2), f"semilla {seed}: la trampa esta en A {in_a} veces de 3"
        pairs = [next(m for m in p["lados"].values() if m != "trampa") for p in traps]
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
    _subject, model_body, separate = hoja_pares.split_message(pair_message)
    n = min(len(model_body), hoja_pares.MAX_BODY_LINES)
    lines = [str(x) for x in trap["cuerpo"]][:n]
    if sum(x.lstrip().startswith(("- ", "* ")) for x in model_body) * 2 >= len(model_body):
        lines = [x if x.lstrip().startswith(("- ", "* ")) else f"- {x}" for x in lines]
    return "\n".join([str(trap["asunto"]), *([""] if separate else []), *lines])


def test_old_rule_splits_bullets_and_guard_sees_it():
    trap = {"asunto": "feat(wiki): algo", "cuerpo": SPLIT_PARAGRAPH_BODY}
    old_one = _old_shape_trap(trap, PAIR_WITH_BULLETS)
    defects = hoja_pares.body_defects(old_one)
    # Mutante: la regla vieja. Dispara los dos defectos, uno por cada viñeta partida.
    assert any("empieza en minuscula" in d and "workflow la tocaba" in d for d in defects), defects
    assert any("termina cortada" in d and "0.18.1" in d for d in defects), defects
    assert len(defects) >= 6, defects
    # La regla nueva, con el mismo cuerpo: viñetas que son frases enteras y ningun defecto.
    new_one = hoja_pares.shaped_trap(trap, PAIR_WITH_BULLETS)
    assert hoja_pares.body_defects(new_one) == [], new_one
    body = hoja_pares.split_message(new_one)[1]
    assert len(body) == 2 and all(x.startswith("- ") for x in body)
    assert body[0] == (
        "- Era el ultimo fleco manual del release: release.py no la mencionaba y ningun workflow "
        "la tocaba (pages.yml publica site/, no docs/)."
    )


def test_body_guard_tells_well_written_from_cut():
    good = (
        "docs: x\n\n- Una frase entera.\n- `ruta/al/fichero.py` queda como estaba.\n- Dice «algo»."
    )
    assert hoja_pares.body_defects(good) == []
    assert hoja_pares.body_defects("docs: x\n\n- empieza abajo.") == [
        "empieza en minuscula: '- empieza abajo.'"
    ]
    assert hoja_pares.body_defects("docs: x\n\n- Termina en la") == [
        "termina cortada: '- Termina en la'"
    ]
    # Sin viñetas tambien: cada linea de cuerpo es una unidad.
    assert len(hoja_pares.body_defects("docs: x\nuna\nDos.")) == 2
    # Sin cuerpo no hay nada que revisar.
    assert hoja_pares.body_defects("docs: solo asunto") == []


def test_body_units_are_whole_sentences_or_bullets_never_physical_lines():
    units_list = hoja_pares.body_units(
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
    trap = {"asunto": "docs: algo", "cuerpo": SPLIT_PARAGRAPH_BODY}
    two = hoja_pares.shaped_trap(trap, "feat: x\n\n- Uno.\n- Dos.")
    assert hoja_pares.split_message(two)[1] == [
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
    traps["juegos"][0]["trampas"][1]["cuerpo"] = ["corta y sin final", "Otra frase."]
    with pytest.raises(SystemExit, match="mal escrita"):
        hoja_pares.build_commit_sheet(
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
    "asunto": "docs: algo",
    "cuerpo": ["Primera frase entera.", "Segunda frase entera.", "Tercera frase entera."],
}


def test_trap_copies_final_punctuation_of_its_pair():
    # Pareja sin puntos: la trampa tampoco los lleva.
    without = hoja_pares.shaped_trap(TRAP_WITH_PERIODS, PAIR_WITHOUT_PERIODS)
    assert hoja_pares.split_message(without)[1] == [
        "- Primera frase entera",
        "- Segunda frase entera",
        "- Tercera frase entera",
    ]
    assert not hoja_pares.uses_final_scoring(without)
    assert hoja_pares.body_defects(without, PAIR_WITHOUT_PERIODS) == []
    # Pareja con puntos: los conserva.
    with_ = hoja_pares.shaped_trap(TRAP_WITH_PERIODS, PAIR_WITH_BULLETS)
    assert all(x.endswith(".") for x in hoja_pares.split_message(with_)[1])
    assert hoja_pares.uses_final_scoring(with_)
    # Mutante: la trampa que NO copia la puntuacion (lleva los puntos con una pareja sin ellos).
    not_copied = (
        "docs: algo\n\n- Primera frase entera.\n- Segunda frase entera.\n- Tercera frase entera."
    )
    assert hoja_pares.uses_final_scoring(not_copied) != hoja_pares.uses_final_scoring(
        PAIR_WITHOUT_PERIODS
    )
    defects = hoja_pares.body_defects(not_copied, PAIR_WITHOUT_PERIODS)
    assert any("puntuacion final no es la de la pareja" in d for d in defects), defects


def test_no_final_mark_only_if_pair_lacks_it_and_whole_word():
    ok = "docs: x\n\n- Cierra el estado de la tarea\n- Aprueba la puerta"
    assert hoja_pares.body_defects(ok, PAIR_WITHOUT_PERIODS) == []
    # Con una pareja que si cierra con punto, la misma trampa sin punto esta cortada.
    defects = hoja_pares.body_defects(ok, PAIR_WITH_BULLETS)
    assert [d.split(":")[0] for d in defects[:2]] == ["termina cortada"] * 2, defects
    # Aunque la pareja no use punto, la ultima palabra no puede ser de corte ni la linea acabar en coma.
    for cutoff in ("con", "de", "y", "a", "el", "la", "en", "que", "por", "para", "o", "del", "al"):
        bad = f"docs: x\n\n- Cierra el estado {cutoff}\n- Aprueba la puerta"
        assert hoja_pares.body_defects(bad, PAIR_WITHOUT_PERIODS) == [
            f"termina cortada: '- Cierra el estado {cutoff}'"
        ], cutoff
    coma = "docs: x\n\n- Cierra el estado,\n- Aprueba la puerta"
    assert hoja_pares.body_defects(coma, PAIR_WITHOUT_PERIODS) == [
        "termina cortada: '- Cierra el estado,'"
    ]


def test_trap_mean_bullet_at_most_1_5_times_its_pair():
    long_one = {
        "asunto": "docs: algo",
        "cuerpo": [
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
    limit = hoja_pares.MAX_LENGTH_FACTOR * hoja_pares.mean_bullet_length(pair)
    message = hoja_pares.shaped_trap(long_one, pair)
    # Las tres primeras pasan del limite; se eligen las tres MAS CORTAS, enteras y en su orden.
    assert hoja_pares.split_message(message)[1] == [
        "- Una frase corta pero entera",
        "- Otra frase corta igual de entera",
        "- La ultima es corta",
    ]
    assert hoja_pares.mean_bullet_length(message) <= limit
    assert hoja_pares.body_defects(message, pair) == []
    # Mutante: la trampa con frases largas (sin elegir las cortas) se pasa del limite.
    long_ones = "docs: algo\n\n" + "\n".join(f"- {x[:-1]}" for x in long_one["cuerpo"][1:4])
    defects = hoja_pares.body_defects(long_ones, pair)
    assert any("viñeta media" in d for d in defects), defects
    # Si con frases enteras no se puede (solo hay frases largas), la guarda lo dice y no se fuerza.
    long_only = {"asunto": "docs: algo", "cuerpo": long_one["cuerpo"][2:4]}
    forced = hoja_pares.shaped_trap(long_only, pair)
    assert any("viñeta media" in d for d in hoja_pares.body_defects(forced, pair))


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


@pytest.mark.parametrize("case_set_item", REAL_SETS, ids=lambda j: f"juego-{j['juego']}")
def test_nine_versioned_traps_are_whole_sentences_with_any_pair(case_set_item):
    assert len(case_set_item["trampas"]) == 3
    for entry in case_set_item["trampas"]:
        # Cada elemento del cuerpo es una unidad entera: ni trozos ni dos frases juntas.
        assert hoja_pares.body_units(entry["cuerpo"]) == entry["cuerpo"], entry["caso"]
        assert 1 <= len(entry["cuerpo"]) <= 5
        for name, pair in REALISTIC_PAIRS.items():
            message = hoja_pares.shaped_trap(entry, pair)
            defects = hoja_pares.body_defects(message, pair)
            assert defects == [], (entry["caso"], name, message, defects)
            assert hoja_pares.forma(message) == hoja_pares.forma(pair), entry["caso"]
            assert hoja_pares.uses_final_scoring(message) == hoja_pares.uses_final_scoring(pair), (
                entry["caso"],
                name,
            )
    same_zone = next(t for t in case_set_item["trampas"] if t["tipo"] == "misma-zona")
    assert same_zone["cuerpo_origen"] == "real-reescrito"


# --- Leer las respuestas ---------------------------------------------------------------------------


def test_read_commit_accepts_full_sheet_and_unmasks_with_key(tmp_path):
    sheet, key, rules, _ = _hoja(tmp_path)
    r = _responses(key, c=6, v=2, ties=2, invents=1)
    judgement, missing = hoja_pares.read_commit(r, key, rules)
    assert missing == []
    assert judgement["parcial"] is False and judgement["hoja"] == sheet["id"]
    real = [p for p in judgement["pares"].values() if p["tipo"] == "real"]
    assert sum(p["lados"][p["preferencia"]] == L26 for p in real if p["preferencia"] != "=") == 6
    assert sum(p["preferencia"] == "=" for p in real) == 2


def test_optional_questions_come_from_rules_json(tmp_path):
    _, key, rules, _ = _hoja(tmp_path)
    r = _responses(key, c=10)
    # Opcionales (la propuesta del usuario): sin «lo principal» ni «especifico» se acepta.
    accepted_one = hoja_pares.read_commit(r, key, rules)[1] == []
    assert accepted_one, "con principal y especifico opcionales, la hoja sin ellas se acepta"
    # Obligatorias: la misma hoja ya no se acepta, y dice que falta.
    required = {**rules, "preguntas_opcionales": []}
    _, missing = hoja_pares.read_commit(r, key, required)
    assert missing and all("principal" in f or "especifico" in f for f in missing)
    assert len(missing) == 4 * len(key["pares"])
    # «Inventa» no puede ser opcional: el fichero de reglas se rechaza.
    path = tmp_path / "reglas.json"
    path.write_text(json.dumps({**rules, "preguntas_opcionales": ["inventa"]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="inventa"):
        hoja_pares.read_rules(path)
    path.write_text(
        json.dumps({**rules, "preguntas_opcionales": ["preferencia"]}), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="preguntas_opcionales"):
        hoja_pares.read_rules(path)


def test_missing_required_says_which_and_produces_nothing(tmp_path, capsys):
    _, key, rules, _ = _hoja(tmp_path)
    r = _responses(key, c=10)
    num = min(r["respuestas"])
    side = min(r["respuestas"][num]["inventa"])
    del r["respuestas"][num]["inventa"][side]
    _, missing = hoja_pares.read_commit(r, key, rules)
    assert missing == [f"par {num}: inventa {side}"]
    # Por la linea de ordenes: error, sin fichero de salida.
    (tmp_path / "r.json").write_text(json.dumps(r), encoding="utf-8")
    (tmp_path / "clave.json").write_text(json.dumps(key), encoding="utf-8")
    (tmp_path / "reglas.json").write_text(json.dumps(rules), encoding="utf-8")
    arguments = [
        "read-commit",
        "--clave",
        str(tmp_path / "clave.json"),
        "--rules",
        str(tmp_path / "reglas.json"),
        "--answers",
        str(tmp_path / "r.json"),
        "--salida",
        str(tmp_path / "juicio.json"),
    ]
    assert hoja_pares.main(arguments) == 1
    assert not (tmp_path / "juicio.json").exists()
    assert f"par {num}: inventa {side}" in capsys.readouterr().err


def test_answers_from_other_sheet(tmp_path):
    # Los mismos pares con otra semilla: las respuestas estan COMPLETAS y todos los numeros de par
    # existen, asi que solo el sha256 puede distinguirlas.
    _, key_a, rules, _ = _hoja(tmp_path, seed=1)
    _, key_b, _, _ = _hoja(tmp_path, seed=2)
    answers_to = _responses(key_a, c=10, complete=True)
    assert hoja_pares.read_commit(answers_to, key_a, rules)[1] == []  # control positivo
    with pytest.raises(SystemExit, match="sha256"):
        hoja_pares.read_commit(answers_to, key_b, rules)


def test_invalid_values_and_unknown_pairs(tmp_path):
    _, key, rules, _ = _hoja(tmp_path)
    r = _responses(key, c=10)
    num = min(r["respuestas"])
    r["respuestas"][num]["preferencia"] = "C"
    with pytest.raises(SystemExit, match="no es valido para preferencia"):
        hoja_pares.read_commit(r, key, rules)
    r = _responses(key, c=10)
    r["respuestas"]["99"] = {"preferencia": "A"}
    with pytest.raises(SystemExit, match="99"):
        hoja_pares.read_commit(r, key, rules)


# --- Parada anticipada -----------------------------------------------------------------------------


def _stopped(tmp_path, **kw):
    _, key, rules, _ = _hoja(tmp_path)
    judgement, _ = hoja_pares.read_commit(_responses(key, **kw), key, rules, partial=True)
    output = hoja_pares.can_stop(judgement, rules)
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
    _, key, rules, _ = _hoja(tmp_path)
    (tmp_path / "clave.json").write_text(json.dumps(key), encoding="utf-8")
    (tmp_path / "reglas.json").write_text(json.dumps(rules), encoding="utf-8")
    for name, kw, expected in (
        ("a", {"c": 5, "invents": 3}, "puedes parar"),
        ("b", {"c": 5}, "sigue"),
    ):
        (tmp_path / f"{name}.json").write_text(json.dumps(_responses(key, **kw)), encoding="utf-8")
        capsys.readouterr()
        rc = hoja_pares.main(
            [
                "read-commit",
                "--partial",
                "--clave",
                str(tmp_path / "clave.json"),
                "--rules",
                str(tmp_path / "reglas.json"),
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
    names = {"Inventa": "inventa", "Lo principal": "principal", "Específico": "especifico"}
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
            if line.startswith("Mejor (A/B/=):") and given.get("preferencia"):
                line = f"Mejor (A/B/=): {given['preferencia']}"
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
    empty = hoja_pares.md_answers(md)
    assert empty["sha256"] == key["sha256"]
    assert all(not p.get("preferencia") for p in empty["respuestas"].values())
    r = _responses(key, c=7, v=3, invents=2)
    read_ones = hoja_pares.md_answers(_fill_md(md, r["respuestas"]))
    judgement, missing = hoja_pares.read_commit(read_ones, key, rules)
    assert missing == []
    num = next(iter(r["respuestas"]))
    assert judgement["pares"][num]["preferencia"] == r["respuestas"][num]["preferencia"]


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
    for pair in data["pares"]:
        state[pair["num"]] = {"inventa.A": "n", "inventa.B": "s", "preferencia": "A"}
    (tmp_path / "datos.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "estado.json").write_text(json.dumps(state), encoding="utf-8")
    program = tmp_path / "prueba.js"
    program.write_text(
        logic
        + "\nconst fs = require('fs');\n"
        + f"const datos = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'datos.json'))}, 'utf8'));\n"
        + f"const estado = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'estado.json'))}, 'utf8'));\n"
        + "console.log(JSON.stringify({exportado: exportar(estado, datos, false), faltan: faltan(estado, datos)}));\n",
        encoding="utf-8",
    )
    output = json.loads(
        subprocess.run([node, str(program)], capture_output=True, text=True, check=True).stdout
    )
    assert output["faltan"] == []
    _, missing = hoja_pares.read_commit(output["exportado"], key, rules)
    assert missing == [], missing
    # Con una obligatoria menos, el lector dice cual falta, y el contador de la pagina tambien.
    del state["03"]["inventa.B"]
    (tmp_path / "estado.json").write_text(json.dumps(state), encoding="utf-8")
    output = json.loads(
        subprocess.run([node, str(program)], capture_output=True, text=True, check=True).stdout
    )
    assert output["faltan"] == [["03", "inventa.B"]]
    _, missing = hoja_pares.read_commit(output["exportado"], key, rules)
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
    (tmp_path / "trampas.json").write_text(json.dumps(traps), encoding="utf-8")
    (tmp_path / "reglas.json").write_text(json.dumps(rules), encoding="utf-8")
    (tmp_path / "r.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    def run(arguments):
        program = (
            "import runpy, sys\n"
            "sys.modules['local_delegate'] = None\n"
            f"sys.argv = ['hoja_pares.py'] + {arguments!r}\n"
            f"runpy.run_path(r'{RAIZ / 'scripts' / 'hoja_pares.py'}', run_name='__main__')\n"
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
            str(tmp_path / "trampas.json"),
            "--rules",
            str(tmp_path / "reglas.json"),
            "--semilla",
            "3",
            "--label-26b",
            L26,
            "--label-qwen",
            LQW,
            "--sheet-dir",
            str(tmp_path / "hoja"),
            "--key-dir",
            str(tmp_path / "clave"),
            str(tmp_path / "r.jsonl"),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    key = json.loads((tmp_path / "clave" / "clave-1.json").read_text(encoding="utf-8"))
    (tmp_path / "parcial.json").write_text(
        json.dumps(_responses(key, c=5, invents=3)), encoding="utf-8"
    )
    proc = run(
        [
            "read-commit",
            "--partial",
            "--clave",
            str(tmp_path / "clave" / "clave-1.json"),
            "--rules",
            str(tmp_path / "reglas.json"),
            "--answers",
            str(tmp_path / "parcial.json"),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "puedes parar"
