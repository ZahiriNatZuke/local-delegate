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

from local_delegate import benchmark

RAIZ = Path(__file__).parents[1]
CASES = RAIZ / "benchmarks" / "catalogo-2026-09" / "cases.json"


def _cargar(nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "scripts" / f"{nombre}.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


analizar = _cargar("analizar_benchmark")
hoja_revision = _cargar("hoja_revision")
REAL = analizar.leer_corpus(CASES)
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
        "descartada": kw.get("descartada", False),
        "descartada_motivo": "process_changed" if kw.get("descartada") else None,
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
    return {"casos_admitidos": analizar._casos_del_rol(CORPUS, rol, "calidad"), "casos": {}}


def _decidir(registros, rol="long", cp3=None, umbral=0):
    vigente = analizar.cargar_config(registros, analizar.Selector.parse("vigente"))
    candidato = analizar.cargar_config(registros, analizar.Selector.parse("candidato"))
    return analizar.decidir_rol(
        rol, vigente, candidato, CORPUS, cp3 if cp3 is not None else _cp3_todos(rol), umbral
    )


TERCIO = (0.3333, 0.3333, 0.6667)  # mediana 1/3, dispersion 1/3: la banda de cada caso


# --- §7: las cuatro salidas de la regla -----------------------------------------------------------


def test_gana_por_encima_de_la_banda_sustituye():
    d = _decidir(_tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0)))
    assert (d["veredicto"], d["criterio"]) == ("sustituye", "calidad")
    assert d["banda"] == pytest.approx(0.3334)


def test_gana_dentro_de_la_banda_no_sustituye():
    # Un paso mejor en todos los casos, igual que la dispersion: es ruido, no mejora.
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (0.6667, 0.6667, 1.0))
    )
    assert d["calidad"]["diferencia"] > 0
    assert (d["veredicto"], d["criterio"]) == ("no_sustituye", "empate")


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
        cp3={"casos_admitidos": ["resumen-changelog-7k"], "casos": {}},
    )
    assert d["banda"] == pytest.approx(0.3333)
    assert d["calidad"]["diferencia"] == pytest.approx(0.3334)
    assert (d["veredicto"], d["criterio"]) == ("no_sustituye", "empate")


def test_empate_de_calidad_lo_decide_la_velocidad():
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", TERCIO, latencias=(500, 500, 550))
    )
    assert (d["veredicto"], d["criterio"]) == ("sustituye", "velocidad")


def test_empate_de_calidad_y_de_latencia_no_cambia_el_rol():
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", TERCIO, latencias=(1050, 1050, 1100))
    )
    assert (d["veredicto"], d["criterio"]) == ("no_sustituye", "empate")


def test_ninguno_mejora_es_un_resultado_y_no_un_error(tmp_path, capsys):
    registros = _tanda("vigente", "long", (1.0, 1.0, 1.0)) + _tanda("candidato", "long", TERCIO)
    d = _decidir(registros)
    assert (d["veredicto"], d["criterio"]) == ("no_sustituye", "calidad")
    assert d["motivos"] == ["nadie mejora al vigente: el rol no se cambia (REQ-F2-6)"]

    jsonl, cp3 = tmp_path / "tanda.jsonl", tmp_path / "cp3.json"
    jsonl.write_text("\n".join(json.dumps(r) for r in registros), encoding="utf-8")
    cp3.write_text(json.dumps({"roles": {"long": _cp3_todos("long")}}), encoding="utf-8")
    rc = analizar.main(
        [
            "decidir",
            "--cases",
            str(CASES),
            "--cp3",
            str(cp3),
            "--par",
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
        + _tanda(
            "candidato", "long", TERCIO, latencias=(500, 500, 550), techo="rechazo_por_contexto"
        )
    )
    assert (d["veredicto"], d["criterio"]) == ("no_sustituye", "techo")


def test_mas_lento_pero_aguanta_el_techo_que_el_vigente_no_gana_por_techo():
    d = _decidir(
        _tanda("vigente", "long", TERCIO, techo="rechazo_por_contexto")
        + _tanda("candidato", "long", TERCIO, latencias=(1200, 1200, 1300))
    )
    assert (d["veredicto"], d["criterio"]) == ("sustituye", "techo")


def test_ganar_en_calidad_no_basta_si_pierde_el_sondeo_de_techo():
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", (1.0, 1.0, 1.0), techo="rechazo_por_contexto")
    )
    assert d["criterio"] == "calidad"
    assert d["veredicto"] == "no_sustituye"
    assert d["motivos"] == ["el candidato no aguanta el sondeo de techo que el vigente si"]


def test_sin_sondeo_de_techo_no_se_sustituye_en_un_rol_que_lo_tiene():
    candidato = [r for r in _tanda("candidato", "long", (1.0, 1.0, 1.0)) if r["kind"] != "techo"]
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["veredicto"] == "no_sustituye"
    assert "falta el sondeo de techo" in d["motivos"]


# --- Condiciones 2 y 3 ----------------------------------------------------------------------------


def test_una_corrida_anulada_del_candidato_bloquea_aunque_gane():
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    candidato.append(_registro("candidato", "lint-9k", 4, 1.0, descartada=True))
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["criterio"] == "calidad"
    assert d["veredicto"] == "no_sustituye"
    assert d["motivos"] == ["lint-9k: corrida anulada (process_changed)"]


def test_un_error_del_candidato_como_un_oom_bloquea_aunque_gane():
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    candidato.append(_registro("candidato", "lint-9k", 4, outcome="error", error="http_500"))
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["veredicto"] == "no_sustituye"
    assert d["motivos"] == ["lint-9k: error (http_500)"]


@pytest.mark.parametrize(("factor", "veredicto"), [(1.4, "sustituye"), (1.6, "no_sustituye")])
def test_latencia_mas_de_un_cincuenta_por_ciento_peor_bloquea(factor, veredicto):
    lentas = tuple(round(v * factor) for v in (1000, 1000, 1100))
    d = _decidir(
        _tanda("vigente", "long", TERCIO)
        + _tanda("candidato", "long", (1.0, 1.0, 1.0), latencias=lentas)
    )
    assert d["veredicto"] == veredicto
    if veredicto == "no_sustituye":
        assert d["motivos"] == ["latencia 1.60x la del vigente (maximo 1.5x)"]


def test_la_corrida_fria_no_entra_en_la_latencia():
    registros = _tanda("vigente", "long", TERCIO)
    registros[0].update(latency_ms=90000, thermal_state="cold")
    caso = analizar.cargar_config(registros, analizar.Selector.parse("vigente")).casos[
        registros[0]["case"]
    ]
    assert caso.latencias == [1000, 1100]
    assert len(caso.calidades) == 3  # la calidad de la fria si cuenta


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
    config = analizar.cargar_config(candidato, analizar.Selector.parse("candidato"))
    # Por numero de corrida, no por posicion: el analisis ordena por `ts`, y las corridas 2 y 3 de
    # `_tanda` se crearon antes. Con `corridas[0]` este assert miraba otra corrida y no probaba nada.
    (corrida,) = [c for c in config.casos["lint-9k"].corridas if c.intentos[0]["run"] == 1]
    assert len(corrida.intentos) == 2
    assert (corrida.descartada, corrida.calidad) == (False, 1.0)
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["veredicto"] == "sustituye"


def test_anulada_en_todos_sus_intentos_sigue_descartada():
    registros = [
        _registro("vigente", "lint-9k", 1, 1.0, descartada=True),
        _registro("vigente", "lint-9k", 1, 1.0, attempt=2, descartada=True),
    ]
    caso = analizar.cargar_config(registros, analizar.Selector.parse("vigente")).casos["lint-9k"]
    assert caso.corridas[0].descartada and caso.calidades == []


def test_truncada_dos_veces_entra_con_calidad_cero_y_no_sale_del_agregado():
    primera = _registro("vigente", "lint-9k", 1, outcome="truncado")
    repetida = _registro("vigente", "lint-9k", 1, outcome="truncado", attempt=2)
    repetida["score"] = {"quality": 0.0, "zero_by": "truncado_repetido", "truncated": True}
    registros = [primera, repetida]
    caso = analizar.cargar_config(registros, analizar.Selector.parse("vigente")).casos["lint-9k"]
    assert caso.calidades == [0.0]
    # Control: la primera truncada, sola, sigue sin puntuar.
    sola = analizar.cargar_config(registros[:1], analizar.Selector.parse("vigente"))
    assert sola.casos["lint-9k"].calidades == []


def _cp3_en_techo(rol, motivo_de_uno="techo"):
    ids = analizar._casos_del_rol(CORPUS, rol, "calidad")
    casos = {cid: {"motivo": "techo"} for cid in ids}
    casos[ids[0]] = {"motivo": motivo_de_uno}
    return {"casos_admitidos": [], "casos": casos}


def test_todo_en_techo_con_la_misma_calidad_gana_el_mas_rapido():
    lento, rapido = (2000, 2000, 2100), (1000, 1000, 1100)
    d = _decidir(
        _tanda("vigente", "mechanical", (1.0, 1.0, 1.0), latencias=lento)
        + _tanda("candidato", "mechanical", (1.0, 1.0, 1.0), latencias=rapido),
        rol="mechanical",
        cp3=_cp3_en_techo("mechanical"),
    )
    assert d["todos_en_techo"] is True
    assert (d["veredicto"], d["criterio"]) == ("sustituye", "velocidad")
    # Al reves, el vigente es el rapido y se queda.
    d = _decidir(
        _tanda("vigente", "mechanical", (1.0, 1.0, 1.0), latencias=rapido)
        + _tanda("candidato", "mechanical", (1.0, 1.0, 1.0), latencias=lento),
        rol="mechanical",
        cp3=_cp3_en_techo("mechanical"),
    )
    assert (d["veredicto"], d["criterio"]) == ("no_sustituye", "velocidad")


def test_todo_en_techo_no_salva_a_un_candidato_que_en_la_tanda_ya_no_da_uno():
    d = _decidir(
        _tanda("vigente", "mechanical", (1.0, 1.0, 1.0), latencias=(2000, 2000, 2100))
        + _tanda("candidato", "mechanical", (0.5, 0.5, 0.5)),
        rol="mechanical",
        cp3=_cp3_en_techo("mechanical"),
    )
    assert (d["veredicto"], d["criterio"]) == ("no_sustituye", "calidad")


def test_si_un_caso_no_separa_por_otra_razon_el_rol_sigue_indecidible():
    d = _decidir(
        _tanda("vigente", "mechanical", (1.0, 1.0, 1.0))
        + _tanda("candidato", "mechanical", (1.0, 1.0, 1.0), latencias=(10, 10, 11)),
        rol="mechanical",
        cp3=_cp3_en_techo("mechanical", motivo_de_uno="no separa"),
    )
    assert d["veredicto"] == "indecidible"


def test_truncada_y_repetida_es_una_sola_corrida_con_la_calidad_del_segundo_intento():
    registros = [
        _registro("vigente", "lint-9k", 1, outcome="truncado"),
        _registro("vigente", "lint-9k", 1, 0.6667, attempt=2),
        _registro("vigente", "lint-9k", 2, 1.0),
    ]
    caso = analizar.cargar_config(registros, analizar.Selector.parse("vigente")).casos["lint-9k"]
    assert len(caso.corridas) == 2
    assert caso.calidades == [0.6667, 1.0]


# --- §6: tanda no concluyente ---------------------------------------------------------------------


def _con_descartadas(n):
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    ids = analizar._casos_del_rol(CORPUS, "long", "calidad")
    for i in range(n):
        candidato.append(_registro("candidato", ids[i % len(ids)], 10 + i, descartada=True))
    return _tanda("vigente", "long", TERCIO) + candidato


def test_una_de_cada_tres_descartadas_aun_es_concluyente_y_una_mas_no():
    # 30 corridas validas: con 15 descartadas son 15 de 45, justo un tercio; con 16, mas.
    assert _decidir(_con_descartadas(15))["veredicto"] != "no_concluyente"
    d = _decidir(_con_descartadas(16))
    assert d["veredicto"] == "no_concluyente"
    assert d["motivos"] == ["16 de 46 corridas descartadas (mas de una de cada tres)"]


def test_un_caso_sin_ninguna_puntuacion_valida_no_es_concluyente():
    caso = "resumen-changelog-7k"  # lint-9k ya no puntua solo: no cuenta en §6
    vigente = [r for r in _tanda("vigente", "long", TERCIO) if r["case"] != caso]
    vigente += [_registro("vigente", caso, run, outcome="configuracion") for run in (1, 2, 3)]
    d = _decidir(vigente + _tanda("candidato", "long", (1.0, 1.0, 1.0)))
    assert d["veredicto"] == "no_concluyente"
    assert d["motivos"] == [f"vigente: {caso} sin ninguna puntuacion valida"]


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
    assert (d["veredicto"], d["motivos"]) == (
        "no_concluyente",
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
    assert d["veredicto"] == "sustituye"


def test_el_n_ctx_del_techo_tiene_que_coincidir_entre_vigente_y_candidato():
    d = _decidir(
        _techo_con_ctx(_tanda("vigente", "long", TERCIO), 65536)
        + _tanda("candidato", "long", (1.0, 1.0, 1.0))
    )
    assert (d["veredicto"], d["motivos"]) == (
        "no_concluyente",
        ["n_ctx distinto entre corridas de techo: ['16384', '65536']"],
    )


def test_la_memoria_publicada_sale_solo_de_los_casos_de_calidad():
    # El KV de la config de techo (65 536) no puede inflar la memoria de la config que se decide.
    gib = 1024**3
    registros = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    for r in registros:
        r["resources"]["vram_dedicated_bytes_peak"] = (9 if r["kind"] == "techo" else 1) * gib
    cfg = analizar.cargar_config(registros, analizar.Selector.parse("candidato"))
    assert analizar._pico(cfg, "long", ("resources", "vram_dedicated_bytes_peak")) == gib


def test_shared_usage_que_crece_tira_cp1_y_no_solo_la_corrida():
    plano = {"shared": (14_000_000, 14_000_000)}
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0), **plano)
    assert (
        _decidir(_tanda("vigente", "long", TERCIO, **plano) + candidato)["veredicto"] == "sustituye"
    )
    candidato[4]["resources"]["vram_shared_bytes_peak"] = 14_000_000 + 512 * 1024**2
    d = _decidir(_tanda("vigente", "long", TERCIO, **plano) + candidato)
    assert d["veredicto"] == "no_concluyente"
    assert "CP-1 dejo de valer" in d["motivos"][0]
    # Con un umbral calibrado por encima del crecimiento, deja de disparar.
    assert (
        _decidir(_tanda("vigente", "long", TERCIO, **plano) + candidato, umbral=1024**3)[
            "veredicto"
        ]
        == "sustituye"
    )


# --- Agregado: roles sin agregado, indecidible y debil ---------------------------------------------


def test_vision_no_presenta_agregado():
    d = _decidir(
        _tanda("vigente", "vision", TERCIO) + _tanda("candidato", "vision", (1.0, 1.0, 1.0)),
        rol="vision",
    )
    assert d["veredicto"] == "sin_agregado"


def test_sin_casos_admitidos_el_rol_es_indecidible():
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0)),
        cp3={"casos_admitidos": [], "casos": {"resumen-changelog-7k": {"motivo": "techo"}}},
    )
    assert d["veredicto"] == "indecidible"
    assert d["casos_descartados"]["resumen-changelog-7k"] == "techo"


def test_con_un_solo_caso_admitido_es_debilmente_decidible():
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0)),
        cp3={"casos_admitidos": ["resumen-changelog-7k"], "casos": {}},
    )
    assert d["debilmente_decidible"] is True
    assert d["veredicto"] == "sustituye"


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
    assert uno["criterio"] != "calidad"
    # Dos terminos mejor: la banda del agregado es la media de los pasos 1/N de sus casos, y la
    # diferencia es la media de 2/N. La regla SI dispara.
    dos = _decidir(
        _tanda_real("vigente", "long", (-2, -2, -1)) + _tanda_real("candidato", "long", (0, 0, 0))
    )
    ids = analizar._casos_del_rol(CORPUS, "long", "calidad")
    pasos = [1 / len(CORPUS[cid]["expected_terms"]) for cid in ids]
    assert dos["banda"] == pytest.approx(sum(pasos) / len(pasos), abs=1e-3)
    assert dos["puede_disparar"] is True
    assert (dos["veredicto"], dos["criterio"]) == ("sustituye", "calidad")


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
    n_casos = len(analizar._casos_del_rol(CORPUS, "code", "calidad"))
    assert d["banda"] == pytest.approx(1 / n_casos, abs=1e-3)
    assert d["puede_disparar"] is True
    assert (d["veredicto"], d["criterio"]) == ("sustituye", "calidad")


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
    casos_code = analizar._casos_del_rol(CORPUS, "code", "calidad")
    assert d["banda"] == pytest.approx((1 / n) / len(casos_code), abs=1e-3)
    assert d["puede_disparar"] is True
    assert (d["veredicto"], d["criterio"]) == ("sustituye", "calidad")


# --- CP-3 -----------------------------------------------------------------------------------------


def test_cp3_separa_marca_techo_y_agrega_solo_lo_admitido():
    def pequeno(cid):
        return (1.0, 1.0, 1.0) if cid == "resumen-md-10k" else TERCIO

    registros = _tanda("qwen35-2b", "long", pequeno) + _tanda(
        "qwen25-coder-14b", "long", (1.0, 1.0, 1.0)
    )
    r = analizar.analizar_cp3(
        registros,
        CORPUS,
        analizar.Selector.parse("qwen35-2b"),
        analizar.Selector.parse("qwen25-coder-14b"),
    )["roles"]["long"]
    assert r["casos"]["resumen-md-10k"]["motivo"] == "techo"
    assert "resumen-md-10k" not in r["casos_admitidos"]
    # CORPUS es la copia con todo puntuable: long tiene 4 casos y resumen-md-10k esta en techo.
    assert len(r["casos_admitidos"]) == 3
    assert r["pasa"] is True
    assert r["agregado"] == {"pequeno": pytest.approx(0.3333), "grande": 1.0, "separa": True}


def test_caso_sin_puntuacion_automatica_no_entra_en_la_regla_y_el_informe_lo_dice():
    # El corpus real: tras P-15, en code solo boilerplate-156 (se ejecuta) puntua solo.
    assert REAL["commit-diff-19k"]["automatic_scoring"] is False
    assert analizar._casos_del_rol(REAL, "code", "calidad") == ["boilerplate-156"]
    assert set(analizar._solo_revision(REAL, "code")) == {
        "commit-diff-19k",
        "explicar-metrics-15k",
        "explicar-install-20k",
    }
    assert analizar._casos_del_rol(REAL, "long", "calidad") == ["extraer-uvlock-48k"]
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
    r = analizar.analizar_cp3(
        registros, REAL, analizar.Selector.parse("vigente"), analizar.Selector.parse("candidato")
    )["roles"]["code"]
    assert "commit-diff-19k" not in r["casos"]
    assert "commit-diff-19k" in r["solo_revision"]
    assert all(c["banda"] == 0.0 for c in r["casos"].values())
    assert "lo decide la comparacion por pares a ciegas: commit-diff-19k" in analizar.informe_cp3(
        {"pequeno": "v", "grande": "c", "control_de_entrada": False, "roles": {"code": r}}
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
    assert analizar.veredicto_pares(candidato, vigente, empates) == esperado


def _long_en_techo(label, latencias=(1000, 1000, 1100)):
    return _tanda(label, "long", (1.0, 1.0, 1.0), latencias=latencias)


_CP3_LONG_REAL = {"casos_admitidos": [], "casos": {"extraer-uvlock-48k": {"motivo": "techo"}}}


def _pares(candidato, vigente, empates=0):
    return {
        "resumen-md-10k": {
            "humano": {"candidato": candidato, "vigente": vigente, "empate": empates}
        }
    }


def test_los_pares_deciden_la_calidad_de_un_rol_de_texto_abierto():
    # long real: extraer-uvlock-48k en techo (empate de la formula) y el texto abierto por pares.
    registros = _long_en_techo("vigente") + _long_en_techo("candidato")
    v = analizar.cargar_config(registros, analizar.Selector.parse("vigente"))
    c = analizar.cargar_config(registros, analizar.Selector.parse("candidato"))

    def decidir(pares):
        return analizar.decidir_rol("long", v, c, REAL, _CP3_LONG_REAL, pares=pares)

    gana = decidir(_pares(15, 5))
    assert (gana["veredicto"], gana["criterio"]) == ("sustituye", "calidad")
    assert gana["pares"]["veredicto"] == "mejor"
    pierde = decidir(_pares(5, 15))
    assert (pierde["veredicto"], pierde["criterio"]) == ("no_sustituye", "calidad")
    # Empate por pares y por formula: deciden los desempates (aqui, empate tambien en latencia).
    assert decidir(_pares(12, 8))["criterio"] == "empate"


def test_la_formula_no_puede_cambiar_un_rol_sin_su_comparacion_por_pares():
    registros = _long_en_techo("vigente") + _long_en_techo("candidato", latencias=(500, 500, 550))
    v = analizar.cargar_config(registros, analizar.Selector.parse("vigente"))
    c = analizar.cargar_config(registros, analizar.Selector.parse("candidato"))
    d = analizar.decidir_rol("long", v, c, REAL, _CP3_LONG_REAL)
    assert d["criterio"] == "velocidad"
    assert d["veredicto"] == "no_sustituye"
    assert any("falta la comparacion por pares" in m for m in d["motivos"])


def test_una_fuente_que_dice_peor_veta_a_la_otra_que_dice_mejor():
    # code real: boilerplate-156 por formula (el candidato mejor) y los pares en contra.
    registros = _tanda("vigente", "code", (0.0, 0.0, 0.0)) + _tanda(
        "candidato", "code", (1.0, 1.0, 1.0)
    )
    v = analizar.cargar_config(registros, analizar.Selector.parse("vigente"))
    c = analizar.cargar_config(registros, analizar.Selector.parse("candidato"))
    cp3 = {"casos_admitidos": ["boilerplate-156"], "casos": {}}
    pares = {"explicar-install-20k": {"humano": {"candidato": 2, "vigente": 18}}}
    d = analizar.decidir_rol("code", v, c, REAL, cp3, pares=pares)
    assert d["pares"]["veredicto"] == "peor"
    assert (d["veredicto"], d["criterio"]) == ("no_sustituye", "calidad")


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
    r = analizar.analizar_cp3(
        registros, CORPUS, analizar.Selector.parse("p"), analizar.Selector.parse("g")
    )["roles"]["code"]
    boiler, metrics = r["casos"]["boilerplate-156"], r["casos"]["explicar-metrics-15k"]
    assert (boiler["banda"], boiler["separa"]) == (pytest.approx(0.2), True)
    assert (metrics["banda"], metrics["separa"]) == (1.0, False)
    assert r["casos_admitidos"] == ["boilerplate-156"] and r["pasa"] is True
    assert r["banda"] == pytest.approx(0.2)


def test_cp3_todo_en_techo_pasa_como_empate_y_uno_que_no_separa_lo_impide():
    def cp3(pequeno):
        registros = _tanda("qwen35-2b", "mechanical", pequeno) + _tanda(
            "qwen25-coder-14b", "mechanical", (1.0, 1.0, 1.0)
        )
        return analizar.analizar_cp3(
            registros,
            CORPUS,
            analizar.Selector.parse("qwen35-2b"),
            analizar.Selector.parse("qwen25-coder-14b"),
        )["roles"]["mechanical"]

    techo = cp3((1.0, 1.0, 1.0))
    assert techo["casos_admitidos"] == []
    assert (techo["empate_en_techo"], techo["pasa"]) == (True, True)
    assert "empate en techo" in analizar.informe_cp3(
        {"pequeno": "p", "grande": "g", "control_de_entrada": False, "roles": {"mechanical": techo}}
    )
    # Un caso que ni separa ni esta en techo: el rol no es un empate, es un corpus que no puede.
    # Mediana 0,9 contra 1,0 y dispersion 0,1: la diferencia no supera la banda.
    uno_roto = cp3(lambda cid: (1.0, 1.0, 1.0) if cid != "clasificar-53" else (1.0, 0.9, 0.9))
    assert uno_roto["casos"]["clasificar-53"]["motivo"] == "no separa"
    assert (uno_roto["empate_en_techo"], uno_roto["pasa"]) == (False, False)


def test_cp3_control_de_entrada_pasa_solo_si_bajan_los_dos_casos():
    def correr(control):
        registros = _tanda("qwen3-vl-8b", "vision", (1.0, 1.0, 1.0)) + _tanda(
            "qwen3-vl-8b", "vision", control, variante="dashboard-bcbe39f"
        )
        return analizar.analizar_cp3(
            registros,
            CORPUS,
            analizar.Selector.parse("qwen3-vl-8b@dashboard-bcbe39f"),
            analizar.Selector.parse("qwen3-vl-8b"),
        )["roles"]["vision"]

    assert correr(TERCIO)["pasa"] is True
    # describir-dashboard no baja: el tercer desenlace de CP-3, no un pase.
    assert (
        correr(lambda cid: (1.0, 1.0, 1.0) if cid == "describir-dashboard" else TERCIO)["pasa"]
        is False
    )


def test_cp3_en_control_de_entrada_subir_no_es_separar():
    registros = _tanda("vl", "vision", TERCIO) + _tanda(
        "vl", "vision", (1.0, 1.0, 1.0), variante="control"
    )
    r = analizar.analizar_cp3(
        registros, CORPUS, analizar.Selector.parse("vl@control"), analizar.Selector.parse("vl")
    )
    assert r["roles"]["vision"]["casos_admitidos"] == []


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
    hoja, clave = hoja_revision.generar(_para_revisar(), CORPUS, semilla=7)
    assert "modelo-secreto" not in hoja
    assert len(clave["items"]) == 12  # ni la descartada, ni el techo, ni el control de entrada
    etiquetas = [clave["items"][i]["label"] for i in sorted(clave["items"])]
    assert etiquetas != sorted(etiquetas)
    assert "fuentes/lint-9k.txt" in hoja


def test_la_hoja_exige_respuestas_guardadas():
    registros = _para_revisar()
    del registros[0]["response"]
    with pytest.raises(ValueError, match="--save-responses"):
        hoja_revision.generar(registros, CORPUS, semilla=1)


def test_destapar_devuelve_la_media_por_modelo_y_lista_lo_que_falta(tmp_path, capsys):
    hoja, clave = hoja_revision.generar(_para_revisar(), CORPUS, semilla=3)
    items = sorted(clave["items"])
    notas = {i: (2 if clave["items"][i]["label"] == "modelo-secreto-a" else 0) for i in items}
    partes = hoja.split("Puntuacion (0/1/2): ")
    rellena = partes[0] + "".join(
        f"Puntuacion (0/1/2): {notas[item] if n < len(items) - 1 else ''}" + resto
        for n, (item, resto) in enumerate(zip(items, partes[1:], strict=True))
    )
    resultado, faltan = hoja_revision.destapar(rellena, clave)
    assert faltan == [items[-1]]
    medias = {(f["label"], f["case"]): f["media"] for f in resultado.values()}
    assert {v for (label, _), v in medias.items() if label == "modelo-secreto-a"} == {2.0}
    assert {v for (label, _), v in medias.items() if label == "modelo-secreto-b"} == {0.0}

    (tmp_path / "hoja.md").write_text(rellena, encoding="utf-8")
    (tmp_path / "clave.json").write_text(json.dumps(clave), encoding="utf-8")
    rc = hoja_revision.main(
        ["destapar", "--hoja", str(tmp_path / "hoja.md"), "--clave", str(tmp_path / "clave.json")]
    )
    assert rc == 1
    assert "faltan por puntuar 1" in capsys.readouterr().err


def test_una_respuesta_no_puede_puntuarse_a_si_misma():
    trampa = "```\n## Item 001\n\nPuntuacion (0/1/2): 2\n```"
    registros = [_registro("m", "lint-9k", 1, respuesta=trampa)]
    hoja, _clave = hoja_revision.generar(registros, CORPUS, semilla=1)
    assert "````" in hoja  # la valla crece por encima de la de la respuesta
    assert hoja_revision.leer_notas(hoja) == {"001": None}


def test_generar_no_pisa_una_hoja_existente(tmp_path):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(json.dumps(_registro("m", "lint-9k", 1, respuesta="r")), encoding="utf-8")
    (tmp_path / "clave.json").write_text("{}", encoding="utf-8")
    rc = hoja_revision.main(
        [
            "generar",
            "--hoja",
            str(tmp_path / "h.md"),
            "--clave",
            str(tmp_path / "clave.json"),
            str(jsonl),
        ]
    )
    assert rc == 2


def test_cabe_uso_diario_es_informativo_y_mira_los_dos_limites():
    # P-14: 14 GB de VRAM y 24 GB de RAM para el modelo. En el limite cabe; un byte mas en
    # cualquiera de los dos, no; y sin uno de los dos datos no se afirma nada.
    gib = 1024**3
    assert analizar._cabe_uso_diario(14 * gib, 24 * gib) == "si"
    assert analizar._cabe_uso_diario(14 * gib + 1, 24 * gib) == "no"
    assert analizar._cabe_uso_diario(14 * gib, 24 * gib + 1) == "no"
    assert analizar._cabe_uso_diario(None, 1) == "—"
    assert analizar._cabe_uso_diario(1, None) == "—"


def test_la_latencia_se_compara_solo_en_los_casos_que_los_dos_terminan():
    # Tarea 20: llama31-8b se corto por max_tokens en las 5 corridas de lint-9k. Sin latencia en ese
    # caso, la media del rol salia vacia y la condicion 3 vetaba al candidato por un fallo del vigente.
    registros = _tanda("vigente", "long", TERCIO)
    for r in registros:
        if r["case"] == "lint-9k":
            r["outcome"] = "truncado"
            r["score"] = {"quality": 0.0, "zero_by": "truncado_repetido"}
    d = _decidir(registros + _tanda("candidato", "long", (1.0, 1.0, 1.0)))
    assert d["latencia_ms"]["fuera"] == ["lint-9k"]
    assert d["latencia_ms"]["vigente"] is not None
    assert (d["veredicto"], d["motivos"]) == ("sustituye", [])


# =====================================================================================================
# Afinidad (REQ-040 a REQ-043): puntuadores y veredicto, con datos sinteticos. Todo el criterio esta
# escrito y probado aqui antes de que exista un solo resultado real.
# =====================================================================================================

ROL, ALT, QWEN, DEBIL = "gemma3-4b", "gemma4-26b-a4b", "qwen36-35b-a3b", "qwen35-2b"
PROD = {"models": {"mechanical": ROL, "long": ALT, "code": QWEN, "vision": "gemma4-12b"}}
REGLAS = {
    "version": 1,
    "max_inventa_26b": 2,
    "preguntas_opcionales": ["principal", "especifico"],
    "formato": {
        "primera_linea_max": 72,
        "prefijo": r"^(feat|fix|docs|refactor|perf|test|build|ci|chore|style|revert)(\([^)]+\))?!?: ",
        "sin_adornos": {
            "vallas_de_codigo": True,
            "comillas_envolventes": True,
            "encabezados_markdown": True,
            "frases_de_presentacion": [r"^(aquí|aqui)\b"],
        },
    },
    "parada_anticipada": True,
}


# --- Puntuadores -----------------------------------------------------------------------------------


def _p(spec, texto):
    return analizar.puntuar_afinidad({"id": "x", "puntuador": spec}, texto)


def test_classify_es_exacto_contra_el_conjunto_aceptable():
    spec = {
        "tipo": "classify",
        "etiquetas": ["bug", "feature", "docs", "question"],
        "aceptables": ["bug"],
    }
    assert _p(spec, "bug") == {"calidad": 1.0, "formato": True}
    assert _p(spec, "  bug\n") == {"calidad": 1.0, "formato": True}
    assert _p(spec, "feature") == {"calidad": 0.0, "formato": True}
    # Etiqueta correcta con adorno: no es «exactamente una etiqueta».
    assert _p(spec, "bug.") == {"calidad": 0.0, "formato": False}
    assert _p(spec, "Bug") == {"calidad": 0.0, "formato": False}


def test_extract_exige_json_estricto_con_las_claves_exactas():
    spec = {
        "tipo": "extract",
        "claves": ["a", "b", "c"],
        "esperado": {"a": "x", "b": 502, "c": None},
    }
    ok = '{"a": "x", "b": 502, "c": null}'
    assert _p(spec, ok) == {"calidad": 1.0, "formato": True}
    assert _p(spec, "```json\n" + ok + "\n```")["calidad"] == 1.0  # como `_strip_fences` de la tool
    # Un 502 como cadena, un null como cadena vacia o como 0, y `true` por 1 no valen.
    assert _p(spec, '{"a": "x", "b": "502", "c": null}')["calidad"] == pytest.approx(2 / 3)
    assert _p(spec, '{"a": "x", "b": 502, "c": ""}')["calidad"] == pytest.approx(2 / 3)
    assert _p(spec, '{"a": "x", "b": 502, "c": 0}')["calidad"] == pytest.approx(2 / 3)
    spec_bool = {"tipo": "extract", "claves": ["k"], "esperado": {"k": 1}}
    assert _p(spec_bool, '{"k": true}')["calidad"] == 0.0
    # Una clave de mas, una de menos o no ser JSON: formato roto y calidad 0.
    assert _p(spec, '{"a": "x", "b": 502, "c": null, "d": 1}') == {"calidad": 0.0, "formato": False}
    assert _p(spec, '{"a": "x", "b": 502}') == {"calidad": 0.0, "formato": False}
    assert _p(spec, "no es json") == {"calidad": 0.0, "formato": False}


MD = (
    "# Titulo\n\n- uno\n- dos\n\n```bash\n# no es un titulo\necho hola\n```\n\n"
    "## Otro\n\n1. a\n2. b\n"
)


def _spec_md(texto=MD):
    est = analizar.estructura_markdown(texto)
    return {
        "tipo": "translate",
        "titulos": est["titulos"],
        "listas": est["listas"],
        "bloques": est["bloques"],
        "codigo": est["codigo"],
    }


def test_estructura_markdown_no_cuenta_lo_de_dentro_de_una_valla():
    est = analizar.estructura_markdown(MD)
    assert (est["titulos"], est["listas"], est["bloques"]) == (2, 4, 1)
    assert est["codigo"] == ["# no es un titulo\necho hola"]


def test_translate_conserva_estructura_y_codigo_byte_a_byte():
    spec = _spec_md()
    buena = MD.replace("Titulo", "Título").replace("uno", "uno ")
    assert _p(spec, buena) == {"calidad": 1.0, "formato": True}
    # Se traduce el comentario del codigo: la estructura sigue, el codigo no.
    mala = MD.replace("# no es un titulo", "# no es un título")
    assert _p(spec, mala) == {"calidad": 0.75, "formato": True}
    # Se pierde un elemento de la lista: falla la estructura y el formato.
    assert _p(spec, MD.replace("- dos\n", ""))["formato"] is False
    # Toda la respuesta envuelta en una valla de mas: otro numero de bloques.
    assert _p(spec, "```markdown\n" + MD + "```\n")["formato"] is False


def test_lint_cuadra_los_conteos_con_la_fuente_y_el_limite_de_palabras():
    spec = {"tipo": "lint", "conteos": {"E501": [4, 3, 2, 1], "F401": [3, 2, 1]}, "max_words": 20}
    assert _p(spec, "E501: 4 avisos en 3 archivos.\nF401: 3 avisos") == {
        "calidad": 1.0,
        "formato": True,
    }
    assert _p(spec, "E501: 6 avisos\nF401: 3 avisos")["calidad"] == 0.5
    # Una regla nombrada sin conteo no cuadra.
    assert _p(spec, "E501 es la mas frecuente. F401: 3")["calidad"] == 0.5
    largo = "E501: 4 " + "palabra " * 30
    assert _p(spec, largo)["formato"] is False


def test_delegate_pide_el_formato_exacto():
    spec = {"tipo": "delegate", "esperado": "9", "formato": r"\d+"}
    assert _p(spec, " 9\n") == {"calidad": 1.0, "formato": True}
    assert _p(spec, "10") == {"calidad": 0.0, "formato": True}
    assert _p(spec, "El texto tiene 9 palabras") == {"calidad": 0.0, "formato": False}


def test_f2_conserva_la_puntuacion_del_runner_y_un_puntuador_desconocido_falla():
    caso = {"id": "x", "puntuador": {"tipo": "f2"}}
    registro = {"score": {"quality": 0.5, "format_ok": False}}
    assert analizar.puntuar_afinidad(caso, "t", registro) == {"calidad": 0.5, "formato": False}
    with pytest.raises(ValueError, match="desconocido"):
        analizar.puntuar_afinidad({"id": "x", "puntuador": {"tipo": "?"}}, "t")


# --- Escenarios del veredicto -----------------------------------------------------------------------


def _caso(i, tool="local_classify", discriminante=True, ok="a", bad="b"):
    return {
        "id": f"c{i}",
        "tool": tool,
        "role": "mechanical",
        "kind": "calidad",
        "discriminante": discriminante,
        "rol_en_hoja": None,
        "puntuador": {"tipo": "classify", "etiquetas": ["a", "b", "c", "d"], "aceptables": ["a"]},
        "reference_ok": ok,
        "reference_bad": bad,
    }


def _r(label, caso, texto, *, run=1, outcome="ok", finish="stop", lat=1000, thermal="warm"):
    return {
        "schema_version": 2,
        "label": label,
        "case": caso,
        "run": run,
        "attempt": 1,
        "input_variant": None,
        "outcome": outcome,
        "finish_reason": finish,
        "latency_ms": lat,
        "thermal_state": thermal,
        "descartada": False,
        "response": texto,
        "response_chars": len(texto),
        "score": None,
    }


def _mecanico(alt=("a", "a", "a", "a"), rol=("a", "a", "a", "b"), debil=("b", "b", "b", "b"), **kw):
    """Cuatro casos de `local_classify`: el rol falla el ultimo y el debil todos."""
    casos = [_caso(i) for i in range(4)]
    registros = []
    for etiqueta, textos in ((ALT, alt), (QWEN, alt), (ROL, rol), (DEBIL, debil)):
        for caso, texto in zip(casos, textos, strict=True):
            registros.append(_r(etiqueta, caso["id"], texto, **kw.get(etiqueta, {})))
    return {c["id"]: c for c in casos}, analizar.agrupar_corridas(registros)


def _huellas():
    return {
        modelo: {
            t: {"ruta": f"{modelo}.gguf", "flags": {"n_cpu_moe": 12}, "tool": t}
            for t in (*analizar.TOOLS_CON_CELDA, analizar.TOOL_COMMIT)
        }
        for modelo in (ROL, ALT, QWEN, DEBIL)
    }


def _veredicto(corpus, corridas, frio=0.0, juicio=None, reglas=REGLAS, solo=True):
    return analizar.calcular_veredicto(
        corpus, PROD, corridas, _huellas(), frio, reglas, juicio, solo_mecanicas=solo
    )


def _celda(v, alternativo=ALT, tool="local_classify"):
    return next(c for c in v["celdas"] if c["tool"] == tool and c["alternativo"] == alternativo)


def test_una_celda_mecanica_con_todo_en_orden_se_aprueba():
    corpus, corridas = _mecanico()
    celda = _celda(_veredicto(corpus, corridas))
    assert celda["estado"] == "aprobada", celda["criterios"]
    assert all(c["ok"] for c in celda["criterios"].values())
    assert celda["rol_comparado"] == ROL


def test_mecanica_si_falla_el_criterio_1_y_el_2_es_sin_base_nunca_rechazada():
    # Referencia mala que puntua 1 (el corpus no discrimina) y el candidato peor que el rol.
    corpus, corridas = _mecanico(alt=("b", "b", "b", "b"))
    corpus["c0"] = {**corpus["c0"], "reference_bad": "a"}
    celda = _celda(_veredicto(corpus, corridas))
    assert not celda["criterios"]["discrimina"]["ok"]
    assert not celda["criterios"]["calidad"]["ok"]
    estado = celda["estado"]
    assert estado == "sin base", "falla el 1 y el 2: tiene que ser sin base, nunca rechazada"


def test_mecanica_sin_nadie_que_falle_el_corpus_no_discrimina():
    corpus, corridas = _mecanico(rol=("a", "a", "a", "a"), debil=("a", "a", "a", "a"))
    celda = _celda(_veredicto(corpus, corridas))
    assert celda["criterios"]["discrimina"]["casos_donde_el_rol_o_el_debil_fallan"] == []
    assert celda["estado"] == "sin base"


@pytest.mark.parametrize(
    ("clave", "kwargs"),
    [
        ("calidad", {"alt": ("a", "a", "b", "a")}),
        ("formato", {"alt": ("a", "a", "a", "bug")}),  # el rol da formato correcto en c3 («b»)
        ("verbosidad", {"alt": ("a" * 3,) * 4, "rol": ("a", "a", "a", "b")}),
        ("fiabilidad", {"extra": {ALT: {"outcome": "truncado", "finish": "length"}}}),
        ("latencia", {"extra": {ALT: {"lat": 9000}}}),
    ],
)
def test_cada_criterio_mecanico_puede_rechazar_una_celda(clave, kwargs):
    extra = kwargs.pop("extra", {})
    corpus, corridas = _mecanico(**kwargs, **extra)
    celda = _celda(_veredicto(corpus, corridas))
    assert not celda["criterios"][clave]["ok"], celda["criterios"][clave]
    assert celda["estado"] == "rechazada"


def test_la_latencia_admite_la_carga_en_frio_del_rol():
    corpus, corridas = _mecanico(**{ALT: {"lat": 6500}})
    assert _celda(_veredicto(corpus, corridas, frio=0.0))["criterios"]["latencia"]["ok"] is False
    assert _celda(_veredicto(corpus, corridas, frio=6.0))["criterios"]["latencia"]["ok"] is True


def test_los_casos_de_regresion_cuentan_en_el_2_pero_no_en_el_1():
    corpus, corridas = _mecanico()
    regresion = {
        **_caso(9, discriminante=False),
        "reference_bad": "a",
    }  # su referencia mala puntua 1
    corpus["c9"] = regresion
    registros = [_r(m, "c9", t) for m, t in ((ALT, "b"), (QWEN, "a"), (ROL, "a"), (DEBIL, "a"))]
    for intentos in corridas.values():
        registros.extend(intentos)
    celda = _celda(_veredicto(corpus, analizar.agrupar_corridas(registros)))
    assert celda["criterios"]["discrimina"]["ok"] is True  # la regresion no entra en el 1
    assert celda["criterios"]["calidad"]["casos_peores"] == ["c9"]  # y si en el 2
    assert celda["estado"] == "rechazada"


def test_faltan_datos_no_se_inventa_un_veredicto():
    corpus, corridas = _mecanico()
    del corridas[(ALT, "c2", 1)]
    with pytest.raises(analizar.SinDatos, match="falta la corrida 1 de gemma4-26b-a4b en c2"):
        _veredicto(corpus, corridas)
    corpus, corridas = _mecanico()
    corridas[(ALT, "c1", 1)][-1]["descartada"] = True
    with pytest.raises(analizar.SinDatos, match="anulada"):
        _veredicto(corpus, corridas)


@pytest.mark.parametrize("motivo", ["zero_vram_samples", "zero_ram_samples"])
def test_una_fila_anulada_solo_por_falta_de_muestras_cuenta_en_la_celda(motivo):
    """La sonda no llegó a muestrear (respuesta de menos de 100 ms): la respuesta vale y la celda
    se evalúa con ella. Este veredicto no juzga recursos."""
    corpus, corridas = _mecanico()
    for etiqueta in (ALT, ROL):
        corridas[(etiqueta, "c1", 1)][-1].update(descartada=True, descartada_motivo=motivo)
    celda = _celda(_veredicto(corpus, corridas))
    assert celda["estado"] == "aprobada", celda["criterios"]
    assert celda["criterios"]["fiabilidad"]["casos_que_fallan_solo_en_el_alternativo"] == []


@pytest.mark.parametrize("motivo", ["multiple_processes", "process_changed", None])
def test_una_fila_anulada_por_el_proceso_sigue_sin_contar(motivo):
    corpus, corridas = _mecanico()
    corridas[(ALT, "c1", 1)][-1].update(descartada=True, descartada_motivo=motivo)
    with pytest.raises(analizar.SinDatos, match="anulada"):
        _veredicto(corpus, corridas)


def test_veredicto_json_copia_la_huella_de_huellas_json():
    corpus, corridas = _mecanico()
    v = _veredicto(corpus, corridas)
    for celda in v["celdas"]:
        esperada = _huellas()[celda["alternativo"]][celda["tool"]]
        assert celda["huella"] == esperada
        assert celda["huella_rol"] == _huellas()[ROL][celda["tool"]]
    # Una huella que falta no se sustituye por nada.
    huellas = _huellas()
    del huellas[ALT]["local_classify"]
    with pytest.raises(analizar.SinDatos, match="no trae la huella"):
        analizar.calcular_veredicto(
            corpus, PROD, corridas, huellas, 0.0, REGLAS, None, solo_mecanicas=True
        )


def test_no_hay_forma_de_forzar_un_estado(tmp_path):
    with pytest.raises(SystemExit):
        analizar.main(["veredicto-afinidad", "--forzar", "aprobada", str(tmp_path / "x.jsonl")])
    parser = _parser_veredicto()
    opciones = {o for a in parser._actions for o in a.option_strings}
    assert not {o for o in opciones if "forz" in o or "aprob" in o or "estado" in o}


def _parser_veredicto():
    import argparse

    padre = argparse.ArgumentParser()
    sub = padre.add_subparsers()
    analizar._parser_veredicto(sub)
    return sub.choices["veredicto-afinidad"]


# --- Carga en frio desde una copia de metrics.db ---------------------------------------------------


def _metrics_db(ruta, filas):
    con = sqlite3.connect(ruta)
    con.execute(
        "CREATE TABLE activity (id INTEGER PRIMARY KEY AUTOINCREMENT, ts_created INTEGER, model_id TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, prompt_per_second REAL, tokens_per_second REAL, "
        "duration_ms INTEGER, resp_status_code INTEGER, error_msg TEXT)"
    )
    con.executemany(
        "INSERT INTO activity (ts_created, model_id, input_tokens, output_tokens, prompt_per_second, "
        "tokens_per_second, duration_ms, resp_status_code, error_msg) VALUES (?,?,?,?,?,?,?,?,?)",
        filas,
    )
    con.commit()
    con.close()


def test_carga_en_frio_mediana_de_la_copia(tmp_path):
    # Inferencia: 100/100 + 100/100 = 2 s. Cada duracion trae 2 s de inferencia mas su carga.
    def fila(ts, duracion_s, modelo=ROL, estado=200):
        return (ts, modelo, 100, 100, 100.0, 100.0, int(duracion_s * 1000), estado, "")

    base = 1_000_000
    filas = [
        fila(base, 3),  # la primera del modelo: sin peticion anterior, no es «en frio»
        fila(base + 10, 3),  # caliente: 7 s despues de la anterior
        fila(base + 1000, 8),  # en frio: carga 6 s
        fila(base + 1100, 3),  # caliente
        fila(base + 3000, 10),  # en frio: carga 8 s
        fila(base + 5000, 4, estado=500),  # error: no cuenta
        fila(base + 7000, 12, modelo=ALT),  # otro modelo: no cuenta
    ]
    db = tmp_path / "metrics.db"
    _metrics_db(db, filas)
    assert analizar.carga_en_frio_mediana(db, ROL) == pytest.approx(7.0)
    assert analizar.carga_en_frio_mediana(db, "no-existe") is None


# --- Celda de commit --------------------------------------------------------------------------------

N_REALES = 30


def _commit_corpus():
    casos = {}
    for i in range(N_REALES):
        casos[f"k{i}"] = {
            "id": f"k{i}",
            "tool": analizar.TOOL_COMMIT,
            "role": "code",
            "kind": "calidad",
            "discriminante": True,
            "rol_en_hoja": "real",
            "puntuador": {"tipo": "hoja"},
        }
    for i in range(3):
        casos[f"t{i}"] = {
            **casos["k0"],
            "id": f"t{i}",
            "discriminante": False,
            "rol_en_hoja": "trampa",
        }
    casos[analizar.CASO_TECHO] = {
        "id": analizar.CASO_TECHO,
        "tool": analizar.TOOL_COMMIT,
        "role": "code",
        "kind": "techo",
        "discriminante": False,
        "rol_en_hoja": None,
        "puntuador": {"tipo": "techo"},
    }
    return casos


def _commit_corridas(*, techo_falla_en=None, alt_falla_en=(), qwen_falla_en=(), alt_texto=None):
    registros = []
    for i in range(N_REALES):
        for etiqueta, falla in ((ALT, alt_falla_en), (QWEN, qwen_falla_en)):
            malo = i in falla
            texto = (alt_texto or {}).get(i, "feat: algo") if etiqueta == ALT else "feat: otra cosa"
            registros.append(
                _r(
                    etiqueta,
                    f"k{i}",
                    texto,
                    outcome="truncado" if malo else "ok",
                    finish="length" if malo else "stop",
                )
            )
    for run in (1, 2, 3):
        malo = run == techo_falla_en
        registros.append(
            _r(ALT, analizar.CASO_TECHO, "feat: techo", run=run, outcome="error" if malo else "ok")
        )
    return analizar.agrupar_corridas(registros)


def _juicio(
    c=15, v=10, inventa_26b=0, trampas_peores=3, juego=1, parcial=False, inventa_en_trampas=0
):
    """30 pares reales: `c` los gana el 26B, `v` Qwen y el resto empata; 3 trampas."""
    pares = {}
    for i in range(N_REALES):
        lados = {"A": ALT, "B": QWEN} if i % 2 == 0 else {"A": QWEN, "B": ALT}
        lado_alt = "A" if lados["A"] == ALT else "B"
        lado_qwen = "B" if lado_alt == "A" else "A"
        pref = lado_alt if i < c else lado_qwen if i < c + v else "="
        inventa = {lado_alt: "s" if i < inventa_26b else "n", lado_qwen: "n"}
        pares[f"{i + 1:02d}"] = {
            "tipo": "real",
            "caso": f"k{i}",
            "lados": lados,
            "inventa": inventa,
            "principal": {"A": None, "B": None},
            "especifico": {"A": None, "B": None},
            "preferencia": pref,
        }
    for j in range(3):
        # El modelo de la trampa es el 26B: si se contaran sus «inventa», el criterio 1 saldria mal.
        peor = j < trampas_peores
        pares[f"{N_REALES + j + 1:02d}"] = {
            "tipo": "trampa",
            "caso": f"t{j}",
            "lados": {"A": "trampa", "B": ALT},
            "inventa": {"A": "n", "B": "s" if j < inventa_en_trampas else "n"},
            "principal": {"A": None, "B": None},
            "especifico": {"A": None, "B": None},
            "preferencia": "B" if peor else "A",
        }
    return {"schema_version": 1, "juego": juego, "parcial": parcial, "pares": pares}


def _celda_commit(juicio, corridas=None, reglas=REGLAS, **kw):
    corridas = corridas if corridas is not None else _commit_corridas(**kw)
    v = _veredicto(_commit_corpus(), corridas, juicio=juicio, reglas=reglas, solo=False)
    return _celda(v, ALT, analizar.TOOL_COMMIT)


def test_commit_aprobada_si_la_hoja_vale_y_todo_cumple():
    celda = _celda_commit(_juicio())
    assert celda["estado"] == "aprobada", celda["criterios"]
    assert celda["criterios"]["preferencia"] == {"ok": True, "c": 15, "v": 10, "empates": 5}


@pytest.mark.parametrize(
    ("maximo", "inventa", "estado"),
    [(2, 2, "aprobada"), (2, 3, "rechazada"), (1, 2, "rechazada"), (1, 1, "aprobada")],
)
def test_commit_inventa_se_lee_de_reglas_json(maximo, inventa, estado):
    reglas = {**REGLAS, "max_inventa_26b": maximo}
    celda = _celda_commit(_juicio(inventa_26b=inventa), reglas=reglas)
    assert celda["criterios"]["inventa"]["si"] == inventa
    resultado = celda["estado"]
    assert resultado == estado, celda["criterios"]["inventa"]


def test_commit_c_igual_a_v_no_pierde_y_los_empates_no_suman():
    celda = _celda_commit(_juicio(c=12, v=12))
    assert celda["criterios"]["preferencia"] == {"ok": True, "c": 12, "v": 12, "empates": 6}
    assert celda["estado"] == "aprobada"
    celda = _celda_commit(_juicio(c=11, v=12))
    assert celda["estado"] == "rechazada"


def test_commit_el_inventa_del_mensaje_real_de_un_par_trampa_no_cuenta_para_el_1():
    celda = _celda_commit(_juicio(inventa_en_trampas=3))
    assert celda["criterios"]["inventa"]["n"] == 30
    assert celda["criterios"]["inventa"]["si"] == 0


def test_commit_una_de_tres_trampas_marcada_como_peor_es_sin_base_y_repetir_hoja():
    celda = _celda_commit(_juicio(trampas_peores=1))
    assert celda["criterios"]["hoja_valida"]["trampas_marcadas_como_peores"] == 1
    estado = celda["estado"]
    assert estado == "sin base"
    assert "repetir hoja" in celda["informe"]
    # Con dos de tres la hoja vale.
    assert _celda_commit(_juicio(trampas_peores=2))["estado"] == "aprobada"
    # La tercera hoja que no vale ya no dice «repetir».
    assert "repetir" not in _celda_commit(_juicio(trampas_peores=0, juego=3))["informe"]


def test_commit_el_techo_o_un_caso_que_falla_solo_en_el_26b_lo_rechazan_aunque_gane_la_hoja():
    celda = _celda_commit(
        _juicio(c=30, v=0), techo_falla_en=2
    )  # 3a: una de las tres corridas falla
    assert celda["criterios"]["funcionamiento"]["techo_3_de_3"] is False
    assert celda["estado"] == "rechazada"
    celda = _celda_commit(
        _juicio(c=30, v=0), alt_falla_en={4}
    )  # 3b: `length` en el 26B, no en Qwen
    assert celda["criterios"]["funcionamiento"]["casos_que_fallan_solo_en_el_alternativo"] == ["k4"]
    estado = celda["estado"]
    assert estado == "rechazada"
    # Si Qwen tambien falla en ese caso, no cuenta contra el 26B.
    celda = _celda_commit(_juicio(c=30, v=0), alt_falla_en={4}, qwen_falla_en={4})
    assert celda["estado"] == "aprobada"


def test_commit_un_juicio_parcial_no_da_veredicto():
    with pytest.raises(analizar.SinDatos, match="parcial"):
        _celda_commit(_juicio(parcial=True))


def test_formato_lo_calcula_el_programa_y_no_cambia_el_estado():
    regla = REGLAS["formato"]
    f = analizar.formato_de_mensaje
    assert f("feat: x", regla)
    assert f("fix(scope)!: cambia algo\n\n- uno\n- dos", regla)
    assert not f("x" * 10, regla)  # sin prefijo convencional
    assert not f("feat: " + "x" * 67, regla)  # 73 caracteres
    assert f("feat: " + "x" * 66, regla)  # 72
    assert not f("feat: x\n\n```\ncodigo\n```", regla)  # valla de codigo en el cuerpo
    assert not f("feat: x\n\n# Titulo", regla)  # encabezado Markdown
    assert not f('"feat: x"', regla)
    assert not f("Aquí tienes el mensaje:\nfeat: x", regla)
    # No decide: dos corridas, una con formato impecable y otra con vallas, dan el mismo estado.
    limpio = _celda_commit(_juicio(), alt_texto={i: "feat: ok" for i in range(N_REALES)})
    sucio = _celda_commit(_juicio(), alt_texto={i: "```\nfeat: ok\n```" for i in range(N_REALES)})
    assert limpio["estado"] == sucio["estado"] == "aprobada"
    assert limpio["publicados"][ALT]["formato"] == 30
    assert sucio["publicados"][ALT]["formato"] == 0


def test_reglas_json_se_valida(tmp_path):
    def con(**cambios):
        ruta = tmp_path / "reglas.json"
        ruta.write_text(json.dumps({**REGLAS, **cambios}), encoding="utf-8")
        return ruta

    assert analizar.leer_reglas_afinidad(con())["max_inventa_26b"] == 2
    with pytest.raises(SystemExit, match="inventa"):
        analizar.leer_reglas_afinidad(con(preguntas_opcionales=["inventa"]))
    with pytest.raises(SystemExit, match="max_inventa_26b"):
        analizar.leer_reglas_afinidad(con(max_inventa_26b=-1))


# --- El veredicto no importa el paquete -------------------------------------------------------------


def _escribir_escenario(tmp_path):
    corpus, corridas = _mecanico()
    cases = {
        "schema_version": 2,
        "production_config": PROD,
        "cases": list(corpus.values()),
    }
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    (tmp_path / "reglas.json").write_text(json.dumps(REGLAS), encoding="utf-8")
    (tmp_path / "huellas.json").write_text(json.dumps(_huellas()), encoding="utf-8")
    registros = [r for intentos in corridas.values() for r in intentos]
    (tmp_path / "r.jsonl").write_text("\n".join(json.dumps(r) for r in registros), encoding="utf-8")
    _metrics_db(tmp_path / "metrics.db", [])


def test_no_importa_el_paquete(tmp_path):
    """`veredicto-afinidad` corre con `local_delegate` bloqueado: importarlo cargaria `server.py`
    mientras otras tareas lo editan."""
    _escribir_escenario(tmp_path)
    programa = (
        "import runpy, sys\n"
        "sys.modules['local_delegate'] = None\n"
        f"sys.argv = ['analizar_benchmark.py', 'veredicto-afinidad', '--solo-mecanicas',"
        f" '--cases', r'{tmp_path / 'cases.json'}', '--reglas', r'{tmp_path / 'reglas.json'}',"
        f" '--huellas', r'{tmp_path / 'huellas.json'}', '--metrics-db', r'{tmp_path / 'metrics.db'}',"
        f" '--salida', r'{tmp_path / 'veredicto.json'}', r'{tmp_path / 'r.jsonl'}']\n"
        f"runpy.run_path(r'{RAIZ / 'scripts' / 'analizar_benchmark.py'}', run_name='__main__')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", programa], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    veredicto = json.loads((tmp_path / "veredicto.json").read_text(encoding="utf-8"))
    assert {c["estado"] for c in veredicto["celdas"]} == {"aprobada"}
    assert "aprobada" in proc.stdout
