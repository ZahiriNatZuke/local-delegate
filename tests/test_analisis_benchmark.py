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

RAIZ = Path(__file__).parents[1]
CASES = RAIZ / "benchmarks" / "catalogo-2026-09" / "cases.json"


def _cargar(nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "scripts" / f"{nombre}.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


analizar = _cargar("analyze_benchmark")
hoja_revision = _cargar("review_sheet")
REAL = analizar.read_corpus(CASES)
# La mecanica de §6 y §7 se prueba con todos los casos de calidad puntuables: que casos decide la
# formula y cuales la comparacion por pares es del corpus (P-15), y lo prueban los tests que usan REAL.
CORPUS = {
    cid: {**c, "automatic_scoring": True} if c["kind"] == "calidad" else c
    for cid, c in REAL.items()
}
_RELOJ = itertools.count()


def _registro(label, case, run, calidad=1.0, **kw):
    meta = CORPUS[case]
    outcome = kw.get("outcome", "ok")
    shared = kw.get("shared", (0, 0))
    registro = {
        "schema_version": 2,
        "ts": f"2026-09-20T00:00:00.{next(_RELOJ):06d}+00:00",
        "label": label,
        "model": kw.get("model", label),
        "variant": {"context_size": kw.get("ctx", 16384), "load_mode": kw.get("load", "none")},
        "case": case,
        "role": meta["role"],
        "kind": meta["kind"],
        "input_variant": kw.get("variante"),
        "run": run,
        "attempt": kw.get("attempt", 1),
        "thermal_state": kw.get("termico", "hot"),
        "input_bytes": meta["source_bytes"],
        "latency_ms": kw.get("latencia", 1000),
        "outcome": outcome,
        "error": kw.get("error"),
        "resources": {"vram_shared_bytes_first": shared[0], "vram_shared_bytes_peak": shared[1]},
        "discarded": kw.get("descartada", False),
        "discarded_reason": "process_changed" if kw.get("descartada") else None,
        "score": {"quality": calidad if outcome == "ok" else None}
        if meta["kind"] == "calidad" and outcome in ("ok", "truncado")
        else None,
    }
    if "respuesta" in kw:
        registro["response"] = kw["respuesta"]
    return registro


def _tanda(label, rol, calidades, latencias=(1000, 1000, 1100), techo="ok", **kw):
    """Tres corridas por caso de calidad del rol y, si el rol lo tiene, su sondeo de techo."""
    registros = []
    for cid, meta in CORPUS.items():
        if meta["role"] != rol:
            continue
        if meta["kind"] == "techo":
            registros += [_registro(label, cid, run, outcome=techo, **kw) for run in (1, 2, 3)]
            continue
        valores = calidades(cid) if callable(calidades) else calidades
        for run, (calidad, latencia) in enumerate(zip(valores, latencias, strict=True), 1):
            registros.append(_registro(label, cid, run, calidad, latencia=latencia, **kw))
    return registros


def _cp3_todos(rol):
    return {"admitted_cases": analizar._role_cases(CORPUS, rol, "calidad"), "cases": {}}


def _decidir(registros, rol="long", cp3=None, umbral=0):
    vigente = analizar.load_config(registros, analizar.Selector.parse("vigente"))
    candidato = analizar.load_config(registros, analizar.Selector.parse("candidato"))
    return analizar.decide_role(
        rol, vigente, candidato, CORPUS, cp3 if cp3 is not None else _cp3_todos(rol), umbral
    )


TERCIO = (0.3333, 0.3333, 0.6667)  # mediana 1/3, dispersion 1/3: la banda de cada caso


# --- §7: las cuatro salidas de la regla -----------------------------------------------------------


def test_gana_por_encima_de_la_banda_sustituye():
    d = _decidir(_tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0)))
    assert (d["verdict"], d["criterion"]) == ("replace", "calidad")
    assert d["band"] == pytest.approx(0.3334)


def test_gana_dentro_de_la_banda_no_sustituye():
    # Un paso mejor en todos los casos, igual que la dispersion: es ruido, no mejora.
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (0.6667, 0.6667, 1.0))
    )
    assert d["quality"]["difference"] > 0
    assert (d["verdict"], d["criterion"]) == ("no_replace", "empate")


def test_el_redondeo_a_cuatro_decimales_no_da_una_victoria():
    # Un solo caso en el agregado, para que la diferencia llegue entera: 0,3333 -> 0,6667 es 0,3334,
    # y la banda es la de ese mismo caso, 0,3333 -> 0,6666 en el vigente: 0,3333. Sin tolerancia
    # ganaria por redondeo. (La primera version promediaba cuatro casos, diluia la diferencia a 0,25 y
    # no discriminaba; la segunda sacaba la banda de otro caso, y la banda ya no es del rol.)
    def vigente(cid):
        return (0.3333, 0.3333, 0.6666) if cid == "resumen-changelog-7k" else (0.3333,) * 3

    def candidato(cid):
        return (0.6667, 0.6667, 0.6667) if cid == "resumen-changelog-7k" else vigente(cid)

    d = _decidir(
        _tanda("vigente", "long", vigente) + _tanda("candidato", "long", candidato),
        cp3={"admitted_cases": ["resumen-changelog-7k"], "cases": {}},
    )
    assert d["band"] == pytest.approx(0.3333)
    assert d["quality"]["difference"] == pytest.approx(0.3334)
    assert (d["verdict"], d["criterion"]) == ("no_replace", "empate")


def test_empate_de_calidad_lo_decide_la_velocidad():
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", TERCIO, latencias=(500, 500, 550))
    )
    assert (d["verdict"], d["criterion"]) == ("replace", "velocidad")


def test_empate_de_calidad_y_de_latencia_no_cambia_el_rol():
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", TERCIO, latencias=(1050, 1050, 1100))
    )
    assert (d["verdict"], d["criterion"]) == ("no_replace", "empate")


def test_ninguno_mejora_es_un_resultado_y_no_un_error(tmp_path, capsys):
    registros = _tanda("vigente", "long", (1.0, 1.0, 1.0)) + _tanda("candidato", "long", TERCIO)
    d = _decidir(registros)
    assert (d["verdict"], d["criterion"]) == ("no_replace", "calidad")
    assert d["reasons"] == ["nadie mejora al vigente: el rol no se cambia (REQ-F2-6)"]

    jsonl, cp3 = tmp_path / "tanda.jsonl", tmp_path / "cp3.json"
    jsonl.write_text("\n".join(json.dumps(r) for r in registros), encoding="utf-8")
    cp3.write_text(json.dumps({"roles": {"long": _cp3_todos("long")}}), encoding="utf-8")
    rc = analizar.main(
        [
            "decide",
            "--cases",
            str(CASES),
            "--cp3",
            str(cp3),
            "--pair",
            "long",
            "vigente",
            "candidato",
            str(jsonl),
        ]
    )
    assert rc == 0
    assert "el rol no se cambia" in capsys.readouterr().out


# --- Precedencia: techo antes que velocidad -------------------------------------------------------


def test_mas_rapido_pero_pierde_el_techo_manda_el_techo():
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", TERCIO, latencias=(500, 500, 550), techo="context_rejection")
    )
    assert (d["verdict"], d["criterion"]) == ("no_replace", "techo")


def test_mas_lento_pero_aguanta_el_techo_que_el_vigente_no_gana_por_techo():
    d = _decidir(
        _tanda("vigente", "long", TERCIO, techo="context_rejection")
        + _tanda("candidato", "long", TERCIO, latencias=(1200, 1200, 1300))
    )
    assert (d["verdict"], d["criterion"]) == ("replace", "techo")


def test_ganar_en_calidad_no_basta_si_pierde_el_sondeo_de_techo():
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", (1.0, 1.0, 1.0), techo="context_rejection")
    )
    assert d["criterion"] == "calidad"
    assert d["verdict"] == "no_replace"
    assert d["reasons"] == ["el candidato no aguanta el sondeo de techo que el vigente si"]


def test_sin_sondeo_de_techo_no_se_sustituye_en_un_rol_que_lo_tiene():
    candidato = [r for r in _tanda("candidato", "long", (1.0, 1.0, 1.0)) if r["kind"] != "techo"]
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["verdict"] == "no_replace"
    assert "falta el sondeo de techo" in d["reasons"]


# --- Condiciones 2 y 3 ----------------------------------------------------------------------------


def test_una_corrida_anulada_del_candidato_bloquea_aunque_gane():
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    candidato.append(_registro("candidato", "lint-9k", 4, 1.0, descartada=True))
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["criterion"] == "calidad"
    assert d["verdict"] == "no_replace"
    assert d["reasons"] == ["lint-9k: corrida anulada (process_changed)"]


def test_un_error_del_candidato_como_un_oom_bloquea_aunque_gane():
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    candidato.append(_registro("candidato", "lint-9k", 4, outcome="error", error="http_500"))
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["verdict"] == "no_replace"
    assert d["reasons"] == ["lint-9k: error (http_500)"]


@pytest.mark.parametrize(("factor", "veredicto"), [(1.4, "replace"), (1.6, "no_replace")])
def test_latencia_mas_de_un_cincuenta_por_ciento_peor_bloquea(factor, veredicto):
    lentas = tuple(round(v * factor) for v in (1000, 1000, 1100))
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", (1.0, 1.0, 1.0), latencias=lentas)
    )
    assert d["verdict"] == veredicto
    if veredicto == "no_replace":
        assert d["reasons"] == ["latencia 1.60x la del vigente (maximo 1.5x)"]


def test_la_corrida_fria_no_entra_en_la_latencia():
    registros = _tanda("vigente", "long", TERCIO)
    registros[0].update(latency_ms=90000, thermal_state="cold")
    caso = analizar.load_config(registros, analizar.Selector.parse("vigente")).cases[
        registros[0]["case"]
    ]
    assert caso.latencies == [1000, 1100]
    assert len(caso.qualities) == 3  # la calidad de la fria si cuenta


def test_anulada_y_repetida_bien_cuenta_su_calidad_y_no_bloquea_al_candidato():
    candidato = [
        r
        for r in _tanda("candidato", "long", (1.0, 1.0, 1.0))
        if not (r["case"] == "lint-9k" and r["run"] == 1)
    ]
    candidato += [
        _registro("candidato", "lint-9k", 1, 1.0, descartada=True),
        _registro("candidato", "lint-9k", 1, 1.0, attempt=2),
    ]
    config = analizar.load_config(candidato, analizar.Selector.parse("candidato"))
    # Por numero de corrida, no por posicion: el analisis ordena por `ts`, y las corridas 2 y 3 de
    # `_tanda` se crearon antes. Con `corridas[0]` este assert miraba otra corrida y no probaba nada.
    (corrida,) = [c for c in config.cases["lint-9k"].runs if c.attempts[0]["run"] == 1]
    assert len(corrida.attempts) == 2
    assert (corrida.discarded, corrida.quality) == (False, 1.0)
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["verdict"] == "replace"


def test_anulada_en_todos_sus_intentos_sigue_descartada():
    registros = [
        _registro("vigente", "lint-9k", 1, 1.0, descartada=True),
        _registro("vigente", "lint-9k", 1, 1.0, attempt=2, descartada=True),
    ]
    caso = analizar.load_config(registros, analizar.Selector.parse("vigente")).cases["lint-9k"]
    assert caso.runs[0].discarded and caso.qualities == []


def test_truncada_dos_veces_entra_con_calidad_cero_y_no_sale_del_agregado():
    primera = _registro("vigente", "lint-9k", 1, outcome="truncado")
    repetida = _registro("vigente", "lint-9k", 1, outcome="truncado", attempt=2)
    repetida["score"] = {"quality": 0.0, "zero_by": "truncated_repeated", "truncated": True}
    registros = [primera, repetida]
    caso = analizar.load_config(registros, analizar.Selector.parse("vigente")).cases["lint-9k"]
    assert caso.qualities == [0.0]
    # Control: la primera truncada, sola, sigue sin puntuar.
    sola = analizar.load_config(registros[:1], analizar.Selector.parse("vigente"))
    assert sola.cases["lint-9k"].qualities == []


def _cp3_en_techo(rol, motivo_de_uno="techo"):
    ids = analizar._role_cases(CORPUS, rol, "calidad")
    casos = {cid: {"reason": "techo"} for cid in ids}
    casos[ids[0]] = {"reason": motivo_de_uno}
    return {"admitted_cases": [], "cases": casos}


def test_todo_en_techo_con_la_misma_calidad_gana_el_mas_rapido():
    lento, rapido = (2000, 2000, 2100), (1000, 1000, 1100)
    d = _decidir(
        _tanda("vigente", "mechanical", (1.0, 1.0, 1.0), latencias=lento)
        + _tanda("candidato", "mechanical", (1.0, 1.0, 1.0), latencias=rapido),
        rol="mechanical",
        cp3=_cp3_en_techo("mechanical"),
    )
    assert d["all_at_ceiling"] is True
    assert (d["verdict"], d["criterion"]) == ("replace", "velocidad")
    # Al reves, el vigente es el rapido y se queda.
    d = _decidir(
        _tanda("vigente", "mechanical", (1.0, 1.0, 1.0), latencias=rapido)
        + _tanda("candidato", "mechanical", (1.0, 1.0, 1.0), latencias=lento),
        rol="mechanical",
        cp3=_cp3_en_techo("mechanical"),
    )
    assert (d["verdict"], d["criterion"]) == ("no_replace", "velocidad")


def test_todo_en_techo_no_salva_a_un_candidato_que_en_la_tanda_ya_no_da_uno():
    d = _decidir(
        _tanda("vigente", "mechanical", (1.0, 1.0, 1.0), latencias=(2000, 2000, 2100))
        + _tanda("candidato", "mechanical", (0.5, 0.5, 0.5)),
        rol="mechanical",
        cp3=_cp3_en_techo("mechanical"),
    )
    assert (d["verdict"], d["criterion"]) == ("no_replace", "calidad")


def test_si_un_caso_no_separa_por_otra_razon_el_rol_sigue_indecidible():
    d = _decidir(
        _tanda("vigente", "mechanical", (1.0, 1.0, 1.0))
        + _tanda("candidato", "mechanical", (1.0, 1.0, 1.0), latencias=(10, 10, 11)),
        rol="mechanical",
        cp3=_cp3_en_techo("mechanical", motivo_de_uno="no separa"),
    )
    assert d["verdict"] == "undecidable"


def test_truncada_y_repetida_es_una_sola_corrida_con_la_calidad_del_segundo_intento():
    registros = [
        _registro("vigente", "lint-9k", 1, outcome="truncado"),
        _registro("vigente", "lint-9k", 1, 0.6667, attempt=2),
        _registro("vigente", "lint-9k", 2, 1.0),
    ]
    caso = analizar.load_config(registros, analizar.Selector.parse("vigente")).cases["lint-9k"]
    assert len(caso.runs) == 2
    assert caso.qualities == [0.6667, 1.0]


# --- §6: tanda no concluyente ---------------------------------------------------------------------


def _con_descartadas(n):
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    ids = analizar._role_cases(CORPUS, "long", "calidad")
    for i in range(n):
        candidato.append(_registro("candidato", ids[i % len(ids)], 10 + i, descartada=True))
    return _tanda("vigente", "long", TERCIO) + candidato


def test_una_de_cada_tres_descartadas_aun_es_concluyente_y_una_mas_no():
    # 30 corridas validas: con 15 descartadas son 15 de 45, justo un tercio; con 16, mas.
    assert _decidir(_con_descartadas(15))["verdict"] != "inconclusive"
    d = _decidir(_con_descartadas(16))
    assert d["verdict"] == "inconclusive"
    assert d["reasons"] == ["16 de 46 corridas descartadas (mas de una de cada tres)"]


def test_un_caso_sin_ninguna_puntuacion_valida_no_es_concluyente():
    caso = "resumen-changelog-7k"  # lint-9k ya no puntua solo: no cuenta en §6
    vigente = [r for r in _tanda("vigente", "long", TERCIO) if r["case"] != caso]
    vigente += [_registro("vigente", caso, run, outcome="configuracion") for run in (1, 2, 3)]
    d = _decidir(vigente + _tanda("candidato", "long", (1.0, 1.0, 1.0)))
    assert d["verdict"] == "inconclusive"
    assert d["reasons"] == [f"vigente: {caso} sin ninguna puntuacion valida"]


@pytest.mark.parametrize(
    ("kw", "motivo"),
    [
        ({"ctx": 8192}, "n_ctx distinto entre corridas de {}: ['16384', '8192']"),
        ({"load": "mmap"}, "--load-mode distinto entre corridas de {}: ['mmap', 'none']"),
        ({"load": None}, "--load-mode sin declarar en alguna corrida de {}"),
    ],
)
def test_contexto_o_load_mode_distintos_o_sin_declarar_no_son_concluyentes(kw, motivo):
    # `_tanda` aplica el cambio a los casos de calidad y al sondeo: sale un motivo por tipo.
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0), **kw)
    )
    assert (d["verdict"], d["reasons"]) == (
        "inconclusive",
        [motivo.format("calidad"), motivo.format("techo")],
    )


def _techo_con_ctx(registros, ctx):
    for r in registros:
        if r["kind"] == "techo":
            r["variant"]["context_size"] = ctx
    return registros


def test_el_sondeo_de_techo_corre_con_su_propio_n_ctx_sin_tumbar_la_tanda():
    # §3.5, dos configs por modelo: calidad a 16 384 y techo a 65 536 en los dos es concluyente.
    d = _decidir(
        _techo_con_ctx(_tanda("vigente", "long", TERCIO), 65536)
        + _techo_con_ctx(_tanda("candidato", "long", (1.0, 1.0, 1.0)), 65536)
    )
    assert d["verdict"] == "replace"


def test_el_n_ctx_del_techo_tiene_que_coincidir_entre_vigente_y_candidato():
    d = _decidir(
        _techo_con_ctx(_tanda("vigente", "long", TERCIO), 65536)
        + _tanda("candidato", "long", (1.0, 1.0, 1.0))
    )
    assert (d["verdict"], d["reasons"]) == (
        "inconclusive",
        ["n_ctx distinto entre corridas de techo: ['16384', '65536']"],
    )


def test_la_memoria_publicada_sale_solo_de_los_casos_de_calidad():
    # El KV de la config de techo (65 536) no puede inflar la memoria de la config que se decide.
    gib = 1024**3
    registros = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    for r in registros:
        r["resources"]["vram_dedicated_bytes_peak"] = (9 if r["kind"] == "techo" else 1) * gib
    cfg = analizar.load_config(registros, analizar.Selector.parse("candidato"))
    assert analizar._peak(cfg, "long", ("resources", "vram_dedicated_bytes_peak")) == gib


def test_shared_usage_que_crece_tira_cp1_y_no_solo_la_corrida():
    plano = {"shared": (14_000_000, 14_000_000)}
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0), **plano)
    assert _decidir(_tanda("vigente", "long", TERCIO, **plano) + candidato)["verdict"] == "replace"
    candidato[4]["resources"]["vram_shared_bytes_peak"] = 14_000_000 + 512 * 1024**2
    d = _decidir(_tanda("vigente", "long", TERCIO, **plano) + candidato)
    assert d["verdict"] == "inconclusive"
    assert "CP-1 dejo de valer" in d["reasons"][0]
    # Con un umbral calibrado por encima del crecimiento, deja de disparar.
    assert (
        _decidir(_tanda("vigente", "long", TERCIO, **plano) + candidato, umbral=1024**3)["verdict"]
        == "replace"
    )


# --- Agregado: roles sin agregado, indecidible y debil ---------------------------------------------


def test_vision_no_presenta_agregado():
    d = _decidir(
        _tanda("vigente", "vision", TERCIO) + _tanda("candidato", "vision", (1.0, 1.0, 1.0)),
        rol="vision",
    )
    assert d["verdict"] == "no_aggregate"


def test_sin_casos_admitidos_el_rol_es_indecidible():
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0)),
        cp3={"admitted_cases": [], "cases": {"resumen-changelog-7k": {"reason": "techo"}}},
    )
    assert d["verdict"] == "undecidable"
    assert d["discarded_cases"]["resumen-changelog-7k"] == "techo"


def test_con_un_solo_caso_admitido_es_debilmente_decidible():
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0)),
        cp3={"admitted_cases": ["resumen-changelog-7k"], "cases": {}},
    )
    assert d["weakly_decidable"] is True
    assert d["verdict"] == "replace"


# --- La granularidad real: puntuar textos, no inventar calidades ----------------------------------


def _texto_con(meta, aciertos):
    terminos = " ".join(meta["expected_terms"][:aciertos])
    campos = meta.get("expected_json_fields") or []
    if campos:
        return json.dumps({campo: terminos for campo in campos}, ensure_ascii=False)
    return terminos


def _calidad_real(cid, aciertos):
    # Sin comprobaciones de ejecucion ni conteos: estos tests miden la granularidad de los TERMINOS,
    # y un texto hecho de terminos no es codigo que pase las de `boilerplate-156` (tarea 19) ni trae
    # los conteos de `lint-9k` (segundo piloto de CP-3).
    meta = {**CORPUS[cid], "execution_checks": [], "expected_counts": {}}
    calidad = benchmark.score_output(meta, _texto_con(meta, aciertos), "stop")["quality"]
    esperado = round(aciertos / len(meta["expected_terms"]), 4)
    assert calidad == esperado, f"{cid}: el texto no acierta {aciertos} terminos"
    return calidad


def _tanda_real(label, rol, aciertos_por_corrida):
    def calidades(cid):
        n = len(CORPUS[cid]["expected_terms"])
        return tuple(_calidad_real(cid, max(0, n + delta)) for delta in aciertos_por_corrida)

    return _tanda(label, rol, calidades)


def test_con_pasos_de_1_n_un_termino_mas_no_gana_y_dos_si():
    # Vigente: un paso de dispersion en cada caso. Un candidato un termino mejor queda dentro.
    uno = _decidir(
        _tanda_real("vigente", "long", (-1, -1, 0)) + _tanda_real("candidato", "long", (0, 0, 0))
    )
    assert uno["criterion"] != "calidad"
    # Dos terminos mejor: la banda del agregado es la media de los pasos 1/N de sus casos, y la
    # diferencia es la media de 2/N. La regla SI dispara.
    dos = _decidir(
        _tanda_real("vigente", "long", (-2, -2, -1)) + _tanda_real("candidato", "long", (0, 0, 0))
    )
    ids = analizar._role_cases(CORPUS, "long", "calidad")
    pasos = [1 / len(CORPUS[cid]["expected_terms"]) for cid in ids]
    assert dos["band"] == pytest.approx(sum(pasos) / len(pasos), abs=1e-3)
    assert dos["can_fire"] is True
    assert (dos["verdict"], dos["criterion"]) == ("replace", "calidad")


def test_un_caso_inestable_ya_no_veta_a_los_demas_del_rol():
    # Tercer piloto de CP-3: con la banda del ROL, un caso que salta de 0 a 1 entre corridas la ponia
    # en 1,0 y ni un candidato claramente mejor en los otros casos podia ganar (antes este test
    # afirmaba ese veto). Con la banda por caso, su ruido entra en la media y no fija la de todos.
    def vigente(cid):
        return (0.0, 1.0, 1.0) if cid == "explicar-install-20k" else (0.25, 0.25, 0.25)

    d = _decidir(
        _tanda("vigente", "code", vigente) + _tanda("candidato", "code", (1.0, 1.0, 1.0)),
        rol="code",
    )
    # Solo explicar-install-20k varia (dispersion 1): la banda del agregado es 1/N, no 1.
    n_casos = len(analizar._role_cases(CORPUS, "code", "calidad"))
    assert d["band"] == pytest.approx(1 / n_casos, abs=1e-3)
    assert d["can_fire"] is True
    assert (d["verdict"], d["criterion"]) == ("replace", "calidad")


def test_con_los_terminos_de_la_tarea_19_el_mismo_tropiezo_deja_disparar_la_regla():
    # El corpus corregido: explicar-install-20k con cinco terminos. Un termino de menos en una corrida
    # mueve la banda 0,2 y no 1,0, y un candidato claramente mejor ya puede ganar.
    n = len(CORPUS["explicar-install-20k"]["expected_terms"])
    assert n >= 4, "este test mide la granularidad de un caso con varios terminos"
    vigente = _tanda_real("vigente", "code", (-2, -2, -2))
    commit = [r for r in vigente if r["case"] == "explicar-install-20k"]
    commit[0]["score"]["quality"] = _calidad_real("explicar-install-20k", n - 3)
    d = _decidir(vigente + _tanda_real("candidato", "code", (0, 0, 0)), rol="code")
    # Solo explicar-install-20k varia (un paso de 1/N); la banda del agregado es la media por caso.
    casos_code = analizar._role_cases(CORPUS, "code", "calidad")
    assert d["band"] == pytest.approx((1 / n) / len(casos_code), abs=1e-3)
    assert d["can_fire"] is True
    assert (d["verdict"], d["criterion"]) == ("replace", "calidad")


# --- CP-3 -----------------------------------------------------------------------------------------


def test_cp3_separa_marca_techo_y_agrega_solo_lo_admitido():
    def pequeno(cid):
        return (1.0, 1.0, 1.0) if cid == "resumen-md-10k" else TERCIO

    registros = _tanda("qwen35-2b", "long", pequeno) + _tanda(
        "qwen25-coder-14b", "long", (1.0, 1.0, 1.0)
    )
    r = analizar.analyze_cp3(
        registros,
        CORPUS,
        analizar.Selector.parse("qwen35-2b"),
        analizar.Selector.parse("qwen25-coder-14b"),
    )["roles"]["long"]
    assert r["cases"]["resumen-md-10k"]["reason"] == "techo"
    assert "resumen-md-10k" not in r["admitted_cases"]
    # CORPUS es la copia con todo puntuable: long tiene 4 casos y resumen-md-10k esta en techo.
    assert len(r["admitted_cases"]) == 3
    assert r["passes"] is True
    assert r["aggregate"] == {"small": pytest.approx(0.3333), "large": 1.0, "separates": True}


def test_caso_sin_puntuacion_automatica_no_entra_en_la_regla_y_el_informe_lo_dice():
    # El corpus real: tras P-15, en code solo boilerplate-156 (se ejecuta) puntua solo.
    assert REAL["commit-diff-19k"]["automatic_scoring"] is False
    assert analizar._role_cases(REAL, "code", "calidad") == ["boilerplate-156"]
    assert set(analizar._review_only(REAL, "code")) == {
        "commit-diff-19k",
        "explicar-metrics-15k",
        "explicar-install-20k",
    }
    assert analizar._role_cases(REAL, "long", "calidad") == ["extraer-uvlock-48k"]
    # Un 0 en todas sus corridas no hunde la banda ni el agregado del candidato.
    registros = [
        r
        for label in ("vigente", "candidato")
        for r in _tanda(
            label,
            "code",
            lambda cid: (0.0, 1.0, 0.0) if cid == "commit-diff-19k" else (1.0, 1.0, 1.0),
        )
    ]
    r = analizar.analyze_cp3(
        registros, REAL, analizar.Selector.parse("vigente"), analizar.Selector.parse("candidato")
    )["roles"]["code"]
    assert "commit-diff-19k" not in r["cases"]
    assert "commit-diff-19k" in r["review_only"]
    assert all(c["band"] == 0.0 for c in r["cases"].values())
    assert "lo decide la comparacion por pares a ciegas: commit-diff-19k" in analizar.cp3_report(
        {"small": "v", "large": "c", "entry_control": False, "roles": {"code": r}}
    )


@pytest.mark.parametrize(
    ("candidato", "vigente", "empates", "esperado"),
    [
        (15, 5, 0, "mejor"),  # P(X >= 15 | 20) = 0,021
        (14, 6, 0, "empate"),  # 0,058: por encima de 0,05
        (5, 15, 0, "peor"),
        (9, 1, 10, "mejor"),  # los empates no cuentan: 9 de 10, 0,011
        (0, 0, 20, "empate"),  # todo empate es un juicio, no falta de datos
        (0, 0, 0, None),
    ],
)
def test_prueba_de_signos_de_la_comparacion_por_pares(candidato, vigente, empates, esperado):
    assert analizar.pairs_verdict(candidato, vigente, empates) == esperado


def _long_en_techo(label, latencias=(1000, 1000, 1100)):
    return _tanda(label, "long", (1.0, 1.0, 1.0), latencias=latencias)


_CP3_LONG_REAL = {"admitted_cases": [], "cases": {"extraer-uvlock-48k": {"reason": "techo"}}}


def _pares(candidato, vigente, empates=0):
    return {
        "resumen-md-10k": {"human": {"candidato": candidato, "vigente": vigente, "empate": empates}}
    }


def test_los_pares_deciden_la_calidad_de_un_rol_de_texto_abierto():
    # long real: extraer-uvlock-48k en techo (empate de la formula) y el texto abierto por pares.
    registros = _long_en_techo("vigente") + _long_en_techo("candidato")
    v = analizar.load_config(registros, analizar.Selector.parse("vigente"))
    c = analizar.load_config(registros, analizar.Selector.parse("candidato"))

    def decidir(pares):
        return analizar.decide_role("long", v, c, REAL, _CP3_LONG_REAL, pairs=pares)

    gana = decidir(_pares(15, 5))
    assert (gana["verdict"], gana["criterion"]) == ("replace", "calidad")
    assert gana["pairs"]["verdict"] == "mejor"
    pierde = decidir(_pares(5, 15))
    assert (pierde["verdict"], pierde["criterion"]) == ("no_replace", "calidad")
    # Empate por pares y por formula: deciden los desempates (aqui, empate tambien en latencia).
    assert decidir(_pares(12, 8))["criterion"] == "empate"


def test_la_formula_no_puede_cambiar_un_rol_sin_su_comparacion_por_pares():
    registros = _long_en_techo("vigente") + _long_en_techo("candidato", latencias=(500, 500, 550))
    v = analizar.load_config(registros, analizar.Selector.parse("vigente"))
    c = analizar.load_config(registros, analizar.Selector.parse("candidato"))
    d = analizar.decide_role("long", v, c, REAL, _CP3_LONG_REAL)
    assert d["criterion"] == "velocidad"
    assert d["verdict"] == "no_replace"
    assert any("falta la comparacion por pares" in m for m in d["reasons"])


def test_una_fuente_que_dice_peor_veta_a_la_otra_que_dice_mejor():
    # code real: boilerplate-156 por formula (el candidato mejor) y los pares en contra.
    registros = _tanda("vigente", "code", (0.0, 0.0, 0.0)) + _tanda(
        "candidato", "code", (1.0, 1.0, 1.0)
    )
    v = analizar.load_config(registros, analizar.Selector.parse("vigente"))
    c = analizar.load_config(registros, analizar.Selector.parse("candidato"))
    cp3 = {"admitted_cases": ["boilerplate-156"], "cases": {}}
    pares = {"explicar-install-20k": {"human": {"candidato": 2, "vigente": 18}}}
    d = analizar.decide_role("code", v, c, REAL, cp3, pairs=pares)
    assert d["pairs"]["verdict"] == "peor"
    assert (d["verdict"], d["criterion"]) == ("no_replace", "calidad")


def test_cp3_cada_caso_separa_contra_su_propia_banda():
    # Los numeros del tercer piloto: boilerplate-156 daba 0/0/0 contra 1/1/0,8 y explicar-metrics-15k
    # 1/0/0,86 contra 1/1/1. Con la banda del rol (1,0, la de explicar-metrics) no separaba ninguno.
    reales = {
        "boilerplate-156": ((0.0, 0.0, 0.0), (1.0, 1.0, 0.8)),
        "explicar-metrics-15k": ((1.0, 0.0, 0.8571), (1.0, 1.0, 1.0)),
    }
    registros = _tanda("p", "code", lambda cid: reales.get(cid, ((0.6,) * 3,) * 2)[0]) + _tanda(
        "g", "code", lambda cid: reales.get(cid, ((0.6,) * 3,) * 2)[1]
    )
    r = analizar.analyze_cp3(
        registros, CORPUS, analizar.Selector.parse("p"), analizar.Selector.parse("g")
    )["roles"]["code"]
    boiler, metrics = r["cases"]["boilerplate-156"], r["cases"]["explicar-metrics-15k"]
    assert (boiler["band"], boiler["separates"]) == (pytest.approx(0.2), True)
    assert (metrics["band"], metrics["separates"]) == (1.0, False)
    assert r["admitted_cases"] == ["boilerplate-156"] and r["passes"] is True
    assert r["band"] == pytest.approx(0.2)


def test_cp3_todo_en_techo_pasa_como_empate_y_uno_que_no_separa_lo_impide():
    def cp3(pequeno):
        registros = _tanda("qwen35-2b", "mechanical", pequeno) + _tanda(
            "qwen25-coder-14b", "mechanical", (1.0, 1.0, 1.0)
        )
        return analizar.analyze_cp3(
            registros,
            CORPUS,
            analizar.Selector.parse("qwen35-2b"),
            analizar.Selector.parse("qwen25-coder-14b"),
        )["roles"]["mechanical"]

    techo = cp3((1.0, 1.0, 1.0))
    assert techo["admitted_cases"] == []
    assert (techo["tie_at_ceiling"], techo["passes"]) == (True, True)
    assert "empate en techo" in analizar.cp3_report(
        {"small": "p", "large": "g", "entry_control": False, "roles": {"mechanical": techo}}
    )
    # Un caso que ni separa ni esta en techo: el rol no es un empate, es un corpus que no puede.
    # Mediana 0,9 contra 1,0 y dispersion 0,1: la diferencia no supera la banda.
    uno_roto = cp3(lambda cid: (1.0, 1.0, 1.0) if cid != "clasificar-53" else (1.0, 0.9, 0.9))
    assert uno_roto["cases"]["clasificar-53"]["reason"] == "no separa"
    assert (uno_roto["tie_at_ceiling"], uno_roto["passes"]) == (False, False)


def test_cp3_control_de_entrada_pasa_solo_si_bajan_los_dos_casos():
    def correr(control):
        registros = _tanda("qwen3-vl-8b", "vision", (1.0, 1.0, 1.0)) + _tanda(
            "qwen3-vl-8b", "vision", control, variante="dashboard-bcbe39f"
        )
        return analizar.analyze_cp3(
            registros,
            CORPUS,
            analizar.Selector.parse("qwen3-vl-8b@dashboard-bcbe39f"),
            analizar.Selector.parse("qwen3-vl-8b"),
        )["roles"]["vision"]

    assert correr(TERCIO)["passes"] is True
    # describir-dashboard no baja: el tercer desenlace de CP-3, no un pase.
    assert (
        correr(lambda cid: (1.0, 1.0, 1.0) if cid == "describir-dashboard" else TERCIO)["passes"]
        is False
    )


def test_cp3_en_control_de_entrada_subir_no_es_separar():
    registros = _tanda("vl", "vision", TERCIO) + _tanda(
        "vl", "vision", (1.0, 1.0, 1.0), variante="control"
    )
    r = analizar.analyze_cp3(
        registros, CORPUS, analizar.Selector.parse("vl@control"), analizar.Selector.parse("vl")
    )
    assert r["roles"]["vision"]["admitted_cases"] == []


# --- Hoja de revision a ciegas --------------------------------------------------------------------


def _para_revisar():
    registros = []
    for label in ("modelo-secreto-a", "modelo-secreto-b"):
        for cid in ("resumen-md-2k", "lint-9k", "commit-diff-19k"):
            for run in (1, 2):
                registros.append(
                    _registro(
                        label, cid, run, model=f"{label}-gguf", respuesta=f"respuesta {cid} {run}"
                    )
                )
    registros.append(_registro("modelo-secreto-a", "lint-9k", 3, descartada=True, respuesta="x"))
    registros.append(_registro("modelo-secreto-a", "techo-resumen-103k", 1, respuesta="x"))
    registros.append(
        _registro("modelo-secreto-a", "describir-dashboard", 1, variante="ctl", respuesta="x")
    )
    return registros


def test_la_hoja_oculta_el_modelo_y_baraja():
    hoja, clave = hoja_revision.generate(_para_revisar(), CORPUS, seed=7)
    assert "modelo-secreto" not in hoja
    assert len(clave["items"]) == 12  # ni la descartada, ni el techo, ni el control de entrada
    etiquetas = [clave["items"][i]["label"] for i in sorted(clave["items"])]
    assert etiquetas != sorted(etiquetas)
    assert "fuentes/lint-9k.txt" in hoja


def test_la_hoja_exige_respuestas_guardadas():
    registros = _para_revisar()
    del registros[0]["response"]
    with pytest.raises(ValueError, match="--save-responses"):
        hoja_revision.generate(registros, CORPUS, seed=1)


def test_destapar_devuelve_la_media_por_modelo_y_lista_lo_que_falta(tmp_path, capsys):
    hoja, clave = hoja_revision.generate(_para_revisar(), CORPUS, seed=3)
    items = sorted(clave["items"])
    notas = {i: (2 if clave["items"][i]["label"] == "modelo-secreto-a" else 0) for i in items}
    partes = hoja.split("Puntuacion (0/1/2): ")
    rellena = partes[0] + "".join(
        f"Puntuacion (0/1/2): {notas[item] if n < len(items) - 1 else ''}" + resto
        for n, (item, resto) in enumerate(zip(items, partes[1:], strict=True))
    )
    resultado, faltan = hoja_revision.unblind(rellena, clave)
    assert faltan == [items[-1]]
    medias = {(f["label"], f["case"]): f["media"] for f in resultado.values()}
    assert {v for (label, _), v in medias.items() if label == "modelo-secreto-a"} == {2.0}
    assert {v for (label, _), v in medias.items() if label == "modelo-secreto-b"} == {0.0}

    (tmp_path / "hoja.md").write_text(rellena, encoding="utf-8")
    (tmp_path / "clave.json").write_text(json.dumps(clave), encoding="utf-8")
    rc = hoja_revision.main(
        ["unblind", "--sheet", str(tmp_path / "hoja.md"), "--key", str(tmp_path / "clave.json")]
    )
    assert rc == 1
    assert "faltan por puntuar 1" in capsys.readouterr().err


def test_una_respuesta_no_puede_puntuarse_a_si_misma():
    trampa = "```\n## Item 001\n\nPuntuacion (0/1/2): 2\n```"
    registros = [_registro("m", "lint-9k", 1, respuesta=trampa)]
    hoja, _clave = hoja_revision.generate(registros, CORPUS, seed=1)
    assert "````" in hoja  # la valla crece por encima de la de la respuesta
    assert hoja_revision.read_notes(hoja) == {"001": None}


def test_generar_no_pisa_una_hoja_existente(tmp_path):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(json.dumps(_registro("m", "lint-9k", 1, respuesta="r")), encoding="utf-8")
    (tmp_path / "clave.json").write_text("{}", encoding="utf-8")
    rc = hoja_revision.main(
        [
            "generate",
            "--sheet",
            str(tmp_path / "h.md"),
            "--key",
            str(tmp_path / "clave.json"),
            str(jsonl),
        ]
    )
    assert rc == 2


def test_cabe_uso_diario_es_informativo_y_mira_los_dos_limites():
    # P-14: 14 GB de VRAM y 24 GB de RAM para el modelo. En el limite cabe; un byte mas en
    # cualquiera de los dos, no; y sin uno de los dos datos no se afirma nada.
    gib = 1024**3
    assert analizar._fits_daily_use(14 * gib, 24 * gib) == "si"
    assert analizar._fits_daily_use(14 * gib + 1, 24 * gib) == "no"
    assert analizar._fits_daily_use(14 * gib, 24 * gib + 1) == "no"
    assert analizar._fits_daily_use(None, 1) == "—"
    assert analizar._fits_daily_use(1, None) == "—"


def test_la_latencia_se_compara_solo_en_los_casos_que_los_dos_terminan():
    # Tarea 20: llama31-8b se corto por max_tokens en las 5 corridas de lint-9k. Sin latencia en ese
    # caso, la media del rol salia vacia y la condicion 3 vetaba al candidato por un fallo del vigente.
    registros = _tanda("vigente", "long", TERCIO)
    for r in registros:
        if r["case"] == "lint-9k":
            r["outcome"] = "truncado"
            r["score"] = {"quality": 0.0, "zero_by": "truncated_repeated"}
    d = _decidir(registros + _tanda("candidato", "long", (1.0, 1.0, 1.0)))
    assert d["latency_ms"]["outside"] == ["lint-9k"]
    assert d["latency_ms"]["incumbent"] is not None
    assert (d["verdict"], d["reasons"]) == ("replace", [])


# =====================================================================================================
# Afinidad (REQ-040 a REQ-043): puntuadores y veredicto, con datos sinteticos. Todo el criterio esta
# escrito y probado aqui antes de que exista un solo resultado real.
# =====================================================================================================

ROLE, ALT, QWEN, WEAK = "gemma3-4b", "gemma4-26b-a4b", "qwen36-35b-a3b", "qwen35-2b"
PROD = {"models": {"mechanical": ROLE, "long": ALT, "code": QWEN, "vision": "gemma4-12b"}}
REGLAS = {
    "version": 1,
    "max_made_up_26b": 2,
    "optional_questions": ["principal", "especifico"],
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
    return analizar.score_affinity({"id": "x", "puntuador": spec}, text)


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
    est = analizar.markdown_structure(text)
    return {
        "kind": "translate",
        "titles": est["titles"],
        "lists": est["lists"],
        "blocks": est["blocks"],
        "code": est["code"],
    }


def test_markdown_structure_ignores_fenced_content():
    est = analizar.markdown_structure(MD)
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
    case = {"id": "x", "puntuador": {"kind": "f2"}}
    record = {"score": {"quality": 0.5, "format_ok": False}}
    assert analizar.score_affinity(case, "t", record) == {"quality": 0.5, "format": False}
    with pytest.raises(ValueError, match="desconocido"):
        analizar.score_affinity({"id": "x", "puntuador": {"kind": "?"}}, "t")


# --- Escenarios del veredicto -----------------------------------------------------------------------


def _caso(i, tool="local_classify", discriminant=True, ok="a", bad="b"):
    return {
        "id": f"c{i}",
        "tool": tool,
        "role": "mechanical",
        "kind": "calidad",
        "discriminating": discriminant,
        "sheet_role": None,
        "puntuador": {"kind": "classify", "labels": ["a", "b", "c", "d"], "acceptable": ["a"]},
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
    cases = [_caso(i) for i in range(4)]
    records = []
    for tag, texts in ((ALT, alt), (QWEN, alt), (ROLE, role), (WEAK, weak)):
        for case, text in zip(cases, texts, strict=True):
            records.append(_r(tag, case["id"], text, **kw.get(tag, {})))
    return {c["id"]: c for c in cases}, analizar.group_runs(records)


def _footprints():
    return {
        model: {
            t: {"ruta": f"{model}.gguf", "flags": {"n_cpu_moe": 12}, "tool": t}
            for t in (*analizar.TOOLS_WITH_CELL, analizar.TOOL_COMMIT)
        }
        for model in (ROLE, ALT, QWEN, WEAK)
    }


def _verdict(corpus, runs, cold=0.0, judgement=None, rules=REGLAS, only=True):
    return analizar.compute_verdict(
        corpus, PROD, runs, _footprints(), cold, rules, judgement, mechanical_only=only
    )


def _celda(v, alternative=ALT, tool="local_classify"):
    return next(c for c in v["cells"] if c["tool"] == tool and c["alternative"] == alternative)


def test_mechanical_cell_all_in_order_approved():
    corpus, runs = _mechanical()
    cell = _celda(_verdict(corpus, runs))
    assert cell["state"] == "approved", cell["criteria"]
    assert all(c["ok"] for c in cell["criteria"].values())
    assert cell["compared_role"] == ROLE


def test_mechanical_criterion_1_fails_and_2_baseless_never_rejected():
    # Referencia mala que puntua 1 (el corpus no discrimina) y el candidato peor que el rol.
    corpus, runs = _mechanical(alt=("b", "b", "b", "b"))
    corpus["c0"] = {**corpus["c0"], "reference_bad": "a"}
    cell = _celda(_verdict(corpus, runs))
    assert not cell["criteria"]["discriminates"]["ok"]
    assert not cell["criteria"]["quality"]["ok"]
    state = cell["state"]
    assert state == "no_baseline", "falla el 1 y el 2: tiene que ser sin base, nunca rechazada"


def test_mechanical_nobody_fails_corpus_does_not_discriminate():
    corpus, runs = _mechanical(role=("a", "a", "a", "a"), weak=("a", "a", "a", "a"))
    cell = _celda(_verdict(corpus, runs))
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
    cell = _celda(_verdict(corpus, runs))
    assert not cell["criteria"][key]["ok"], cell["criteria"][key]
    assert cell["state"] == "rejected"


def test_latency_allows_role_cold_load():
    corpus, runs = _mechanical(**{ALT: {"lat": 6500}})
    assert _celda(_verdict(corpus, runs, cold=0.0))["criteria"]["latency"]["ok"] is False
    assert _celda(_verdict(corpus, runs, cold=6.0))["criteria"]["latency"]["ok"] is True


def test_regression_cases_count_in_2_but_not_in_1():
    corpus, runs = _mechanical()
    regression = {
        **_caso(9, discriminant=False),
        "reference_bad": "a",
    }  # su referencia mala puntua 1
    corpus["c9"] = regression
    records = [_r(m, "c9", t) for m, t in ((ALT, "b"), (QWEN, "a"), (ROLE, "a"), (WEAK, "a"))]
    for attempts in runs.values():
        records.extend(attempts)
    cell = _celda(_verdict(corpus, analizar.group_runs(records)))
    assert cell["criteria"]["discriminates"]["ok"] is True  # la regresion no entra en el 1
    assert cell["criteria"]["quality"]["worse_cases"] == ["c9"]  # y si en el 2
    assert cell["state"] == "rejected"


def test_missing_data_no_invented_verdict():
    corpus, runs = _mechanical()
    del runs[(ALT, "c2", 1)]
    with pytest.raises(analizar.NoData, match="falta la corrida 1 de gemma4-26b-a4b en c2"):
        _verdict(corpus, runs)
    corpus, runs = _mechanical()
    runs[(ALT, "c1", 1)][-1]["discarded"] = True
    with pytest.raises(analizar.NoData, match="anulada"):
        _verdict(corpus, runs)


@pytest.mark.parametrize("reason", ["zero_vram_samples", "zero_ram_samples"])
def test_row_cancelled_only_for_lack_of_samples_counts_in_cell(reason):
    """La sonda no llegó a muestrear (respuesta de menos de 100 ms): la respuesta vale y la celda
    se evalúa con ella. Este veredicto no juzga recursos."""
    corpus, runs = _mechanical()
    for tag in (ALT, ROLE):
        runs[(tag, "c1", 1)][-1].update(discarded=True, discarded_reason=reason)
    cell = _celda(_verdict(corpus, runs))
    assert cell["state"] == "approved", cell["criteria"]
    assert cell["criteria"]["reliability"]["cases_failing_only_in_alternative"] == []


@pytest.mark.parametrize("reason", ["multiple_processes", "process_changed", None])
def test_row_cancelled_by_process_still_not_counted(reason):
    corpus, runs = _mechanical()
    runs[(ALT, "c1", 1)][-1].update(discarded=True, discarded_reason=reason)
    with pytest.raises(analizar.NoData, match="anulada"):
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
    with pytest.raises(analizar.NoData, match="no trae la huella"):
        analizar.compute_verdict(
            corpus, PROD, runs, footprints, 0.0, REGLAS, None, mechanical_only=True
        )


def test_no_way_to_force_a_state(tmp_path):
    with pytest.raises(SystemExit):
        analizar.main(["affinity-verdict", "--forzar", "aprobada", str(tmp_path / "x.jsonl")])
    parser = _verdict_parser()
    options = {o for a in parser._actions for o in a.option_strings}
    assert not {o for o in options if "forz" in o or "aprob" in o or "state" in o}


def _verdict_parser():
    import argparse

    parent = argparse.ArgumentParser()
    sub = parent.add_subparsers()
    analizar._verdict_parser(sub)
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
    assert analizar.median_cold_load(db, ROLE) == pytest.approx(7.0)
    assert analizar.median_cold_load(db, "no-existe") is None


# --- Celda de commit --------------------------------------------------------------------------------

N_REAL = 30


def _commit_corpus():
    cases = {}
    for i in range(N_REAL):
        cases[f"k{i}"] = {
            "id": f"k{i}",
            "tool": analizar.TOOL_COMMIT,
            "role": "code",
            "kind": "calidad",
            "discriminating": True,
            "sheet_role": "real",
            "puntuador": {"kind": "hoja"},
        }
    for i in range(3):
        cases[f"t{i}"] = {
            **cases["k0"],
            "id": f"t{i}",
            "discriminating": False,
            "sheet_role": "trampa",
        }
    cases[analizar.CEILING_CASE_ID] = {
        "id": analizar.CEILING_CASE_ID,
        "tool": analizar.TOOL_COMMIT,
        "role": "code",
        "kind": "techo",
        "discriminating": False,
        "sheet_role": None,
        "puntuador": {"kind": "techo"},
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
                analizar.CEILING_CASE_ID,
                "feat: techo",
                run=run,
                outcome="error" if bad else "ok",
            )
        )
    return analizar.group_runs(records)


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


def _commit_cell(judgement, runs=None, rules=REGLAS, **kw):
    runs = runs if runs is not None else _commit_runs(**kw)
    v = _verdict(_commit_corpus(), runs, judgement=judgement, rules=rules, only=False)
    return _celda(v, ALT, analizar.TOOL_COMMIT)


def test_commit_approved_if_sheet_valid_and_all_pass():
    cell = _commit_cell(_verdict_cell())
    assert cell["state"] == "approved", cell["criteria"]
    assert cell["criteria"]["preference"] == {"ok": True, "c": 15, "v": 10, "ties": 5}


@pytest.mark.parametrize(
    ("maximum", "invents", "state"),
    [(2, 2, "approved"), (2, 3, "rejected"), (1, 2, "rejected"), (1, 1, "approved")],
)
def test_commit_invents_read_from_rules_json(maximum, invents, state):
    rules = {**REGLAS, "max_made_up_26b": maximum}
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
    with pytest.raises(analizar.NoData, match="parcial"):
        _commit_cell(_verdict_cell(partial=True))


def test_format_computed_by_program_and_state_unchanged():
    rule = REGLAS["format"]
    f = analizar.message_format
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
        path.write_text(json.dumps({**REGLAS, **changes}), encoding="utf-8")
        return path

    assert analizar.read_affinity_rules(with_())["max_made_up_26b"] == 2
    with pytest.raises(SystemExit, match="inventa"):
        analizar.read_affinity_rules(with_(optional_questions=["inventa"]))
    with pytest.raises(SystemExit, match="max_made_up_26b"):
        analizar.read_affinity_rules(with_(max_made_up_26b=-1))


# --- El veredicto no importa el paquete -------------------------------------------------------------


def _write_scenario(tmp_path):
    corpus, runs = _mechanical()
    cases = {
        "schema_version": 2,
        "production_config": PROD,
        "cases": list(corpus.values()),
    }
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    (tmp_path / "rules.json").write_text(json.dumps(REGLAS), encoding="utf-8")
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
        f"runpy.run_path(r'{RAIZ / 'scripts' / 'analyze_benchmark.py'}', run_name='__main__')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads((tmp_path / "verdict-mechanical.json").read_text(encoding="utf-8"))
    assert {c["state"] for c in verdict["cells"]} == {"approved"}
    assert "aprobada" in proc.stdout


# --- Lectura dual de los resultados congelados (ola A10b-1) ---------------------------------------

FROZEN_RESULTS = RAIZ / "benchmarks" / "afinidad-2026-10" / "resultados" / "gemma3-4b.jsonl"


def test_frozen_results_are_read_with_the_new_keys():
    """Las filas congeladas dicen `descartada`; los tres cargadores las dan como `discarded`."""
    old_rows = [json.loads(x) for x in FROZEN_RESULTS.read_text(encoding="utf-8").splitlines() if x]
    expected = sum(1 for r in old_rows if r.get("descartada"))
    assert expected > 0  # sin filas anuladas, el test no distinguiría nada
    hoja_pares = _cargar("hoja_pares")
    for records in (
        analizar.read_jsonl([FROZEN_RESULTS]),
        hoja_revision._records([FROZEN_RESULTS]),
        hoja_pares._registros([FROZEN_RESULTS]),
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
    first, second = analizar.read_jsonl([path])
    assert first["outcome"] == "context_rejection"
    assert second["score"]["zero_by"] == "truncated_repeated"


def test_footprints_fall_back_to_the_frozen_file(tmp_path):
    frozen = RAIZ / "benchmarks" / "afinidad-2026-10"
    assert analizar.footprints_file(frozen / "footprints.json") == frozen / "huellas.json"
    assert (frozen / "huellas.json").exists()
    (tmp_path / "footprints.json").write_text("{}", encoding="utf-8")
    assert analizar.footprints_file(tmp_path / "footprints.json") == tmp_path / "footprints.json"
    assert analizar.footprints_file(tmp_path / "other.json") == tmp_path / "other.json"


# --- Formato nuevo del veredicto y lectura dual de sus entradas (ola A10b-2) ----------------------

FROZEN_AFFINITY = RAIZ / "benchmarks" / "afinidad-2026-10"


def _read_verdict(directory):
    """Como lo lee `tests/test_affinity.py`: `verdict.json` si existe y, si no, el congelado."""
    old_name, new_name = legacy_names.VERDICT_FILE_NAMES
    path = directory / new_name if (directory / new_name).exists() else directory / old_name
    return legacy_names.normalize_affinity_verdict(json.loads(path.read_text(encoding="utf-8")))


def test_the_written_verdict_closes_the_cycle_and_the_frozen_one_is_still_read(tmp_path):
    _write_scenario(tmp_path)
    (tmp_path / "veredicto.json").write_bytes((FROZEN_AFFINITY / "veredicto.json").read_bytes())
    rc = analizar.main(
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
    rules = analizar.read_affinity_rules(FROZEN_AFFINITY / "reglas.json")
    assert rules["max_made_up_26b"] == 1 and rules["early_stop"] is True
    assert rules["format"]["no_frills"]["code_fences"] is True
    assert analizar.message_format("feat: algo", rules["format"])
    assert not analizar.message_format("```\nfeat: algo\n```", rules["format"])
    frozen = FROZEN_AFFINITY / "rules.json"
    assert analizar.rules_file(frozen) == FROZEN_AFFINITY / "reglas.json"


def test_an_old_format_scorer_scores_the_same():
    new = {"kind": "classify", "labels": ["bug", "feature"], "acceptable": ["bug"]}
    old = _old_keys("affinity_scorer", new)
    assert "tipo" in old
    for text in ("bug", "feature", "otra"):
        assert analizar.score_affinity({"puntuador": old}, text) == analizar.score_affinity(
            {"puntuador": new}, text
        )


def test_unblinded_pairs_are_summed_in_either_format(tmp_path):
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text(json.dumps({"c1": {"humano": {"a": 2, "b": 1}}}), encoding="utf-8")
    new.write_text(
        json.dumps({"c1": {"human": {"a": 1}}, "c2": {"human": {"b": 3}}}), encoding="utf-8"
    )
    assert analizar.merge_unblinded_pairs([old, new]) == {
        "c1": {"human": {"a": 3, "b": 1}},
        "c2": {"human": {"b": 3}},
    }
    assert analizar.merge_unblinded_pairs([]) is None


def test_the_frozen_affinity_corpus_is_read_with_the_new_case_keys():
    """El corpus congelado dice `discriminante`: sin la traducción, la celda diría que no hay
    casos discriminantes; con ella, llega a buscar las corridas."""
    data = json.loads((FROZEN_AFFINITY / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if c["tool"] == "local_classify"]
    assert cases and all("discriminante" in c for c in cases)
    with pytest.raises(analizar.NoData, match="falta la corrida"):
        analizar.evaluate_mechanical_cell("local_classify", "alt", "rol", cases, {}, None)
