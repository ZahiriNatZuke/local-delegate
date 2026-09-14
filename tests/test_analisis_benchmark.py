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
CORPUS = analizar.leer_corpus(CASES)
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


TERCIO = (0.3333, 0.3333, 0.6667)  # mediana 1/3, dispersion 1/3: la banda del rol


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
    # y la banda sale de otro caso, 0,6667 -> 1,0, que es 0,3333. Sin tolerancia ganaria por redondeo.
    # (La primera version promediaba cuatro casos, diluia la diferencia a 0,25 y no discriminaba.)
    def vigente(cid):
        return (0.6667, 1.0, 1.0) if cid == "resumen-md-10k" else (0.3333, 0.3333, 0.3333)

    def candidato(cid):
        return (0.6667, 0.6667, 0.6667) if cid == "lint-33k" else vigente(cid)

    d = _decidir(
        _tanda("vigente", "long", vigente) + _tanda("candidato", "long", candidato),
        cp3={"casos_admitidos": ["lint-33k"], "casos": {}},
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
    candidato.append(_registro("candidato", "lint-33k", 4, 1.0, descartada=True))
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["criterio"] == "calidad"
    assert d["veredicto"] == "no_sustituye"
    assert d["motivos"] == ["lint-33k: corrida anulada (process_changed)"]


def test_un_error_del_candidato_como_un_oom_bloquea_aunque_gane():
    candidato = _tanda("candidato", "long", (1.0, 1.0, 1.0))
    candidato.append(_registro("candidato", "lint-33k", 4, outcome="error", error="http_500"))
    d = _decidir(_tanda("vigente", "long", TERCIO) + candidato)
    assert d["veredicto"] == "no_sustituye"
    assert d["motivos"] == ["lint-33k: error (http_500)"]


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


def test_truncada_y_repetida_es_una_sola_corrida_con_la_calidad_del_segundo_intento():
    registros = [
        _registro("vigente", "lint-33k", 1, outcome="truncado"),
        _registro("vigente", "lint-33k", 1, 0.6667, attempt=2),
        _registro("vigente", "lint-33k", 2, 1.0),
    ]
    caso = analizar.cargar_config(registros, analizar.Selector.parse("vigente")).casos["lint-33k"]
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
    vigente = [r for r in _tanda("vigente", "long", TERCIO) if r["case"] != "lint-33k"]
    vigente += [_registro("vigente", "lint-33k", run, outcome="configuracion") for run in (1, 2, 3)]
    d = _decidir(vigente + _tanda("candidato", "long", (1.0, 1.0, 1.0)))
    assert d["veredicto"] == "no_concluyente"
    assert d["motivos"] == ["vigente: lint-33k sin ninguna puntuacion valida"]


@pytest.mark.parametrize(
    ("kw", "motivo"),
    [
        ({"ctx": 8192}, "n_ctx distinto entre corridas: ['16384', '8192']"),
        ({"load": "mmap"}, "--load-mode distinto entre corridas: ['mmap', 'none']"),
        ({"load": None}, "--load-mode sin declarar en alguna corrida"),
    ],
)
def test_contexto_o_load_mode_distintos_o_sin_declarar_no_son_concluyentes(kw, motivo):
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0), **kw)
    )
    assert (d["veredicto"], d["motivos"]) == ("no_concluyente", [motivo])


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
        cp3={"casos_admitidos": [], "casos": {"lint-33k": {"motivo": "techo"}}},
    )
    assert d["veredicto"] == "indecidible"
    assert d["casos_descartados"]["lint-33k"] == "techo"


def test_con_un_solo_caso_admitido_es_debilmente_decidible():
    d = _decidir(
        _tanda("vigente", "long", TERCIO) + _tanda("candidato", "long", (1.0, 1.0, 1.0)),
        cp3={"casos_admitidos": ["lint-33k"], "casos": {}},
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
    meta = CORPUS[cid]
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
    # Dos terminos mejor, con la banda que da el caso de dos terminos (0,5): la regla SI dispara.
    dos = _decidir(
        _tanda_real("vigente", "long", (-2, -2, -1)) + _tanda_real("candidato", "long", (0, 0, 0))
    )
    assert dos["banda"] == pytest.approx(0.5)
    assert dos["puede_disparar"] is True
    assert (dos["veredicto"], dos["criterio"]) == ("sustituye", "calidad")


def test_un_caso_de_un_solo_termino_que_cambia_una_vez_impide_cualquier_ganador():
    # commit-diff-19k tiene UN termino: 0 o 1. Si cambia en una de tres corridas, la banda de code
    # vale 1,0 y ni un candidato perfecto la supera. Es lo que la regla tiene que DECIR.
    assert len(CORPUS["commit-diff-19k"]["expected_terms"]) == 1
    vigente = _tanda_real("vigente", "code", (0, 0, 0))
    commit = [r for r in vigente if r["case"] == "commit-diff-19k"]
    commit[0]["score"]["quality"] = _calidad_real("commit-diff-19k", 0)
    d = _decidir(vigente + _tanda_real("candidato", "code", (0, 0, 0)), rol="code")
    assert d["banda"] == 1.0
    assert d["puede_disparar"] is False
    assert d["veredicto"] == "no_sustituye"


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
    assert len(r["casos_admitidos"]) == 3
    assert r["pasa"] is True
    assert r["agregado"] == {"pequeno": pytest.approx(0.3333), "grande": 1.0, "separa": True}


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
        for cid in ("resumen-md-2k", "lint-33k", "commit-diff-19k"):
            for run in (1, 2):
                registros.append(
                    _registro(
                        label, cid, run, model=f"{label}-gguf", respuesta=f"respuesta {cid} {run}"
                    )
                )
    registros.append(_registro("modelo-secreto-a", "lint-33k", 3, descartada=True, respuesta="x"))
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
    assert "fuentes/lint-33k.txt" in hoja


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
    registros = [_registro("m", "lint-33k", 1, respuesta=trampa)]
    hoja, _clave = hoja_revision.generar(registros, CORPUS, semilla=1)
    assert "````" in hoja  # la valla crece por encima de la de la respuesta
    assert hoja_revision.leer_notas(hoja) == {"001": None}


def test_generar_no_pisa_una_hoja_existente(tmp_path):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(json.dumps(_registro("m", "lint-33k", 1, respuesta="r")), encoding="utf-8")
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
