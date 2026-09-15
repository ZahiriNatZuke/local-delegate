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
