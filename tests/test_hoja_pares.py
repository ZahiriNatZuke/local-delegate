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
# Hoja a ciegas de `local_commit_msg` (REQ-042): generar-commit y leer-commit, con datos sinteticos.
# =====================================================================================================

L26, LQW = "modelo-alfa-26b", "modelo-beta-qwen"
N_REALES = 10
REGLAS_HOJA = {
    "version": 1,
    "max_inventa_26b": 2,
    "preguntas_opcionales": ["principal", "especifico"],
    "formato": {"primera_linea_max": 72, "prefijo": "x", "sin_adornos": {}},
    "parada_anticipada": True,
}
CUERPO_TRAMPA = [
    "- cuerpo uno",
    "- cuerpo dos",
    "- cuerpo tres",
    "- cuerpo cuatro",
    "- cuerpo cinco",
]


def _diff(clave):
    return (
        f"diff --git a/f{clave} b/f{clave}\n--- a/f{clave}\n+++ b/f{clave}\n@@ -0,0 +1 @@\n"
        f"+linea unica {clave}\n-linea vieja {clave}\n"
    )


def _mensaje(modelo, i):
    etiqueta = "alfa" if modelo == L26 else "beta"
    base = f"{'feat' if modelo == L26 else 'fix'}(zona-{i}): resumen {etiqueta} {i}"
    if modelo == L26 and i % 2 == 0:
        return base + f"\n\n- detalle {i} uno\n- detalle {i} dos"
    if modelo == LQW and i % 3 == 0:
        return base + f"\n\n- nota {i} a\n- nota {i} b\n- nota {i} c"
    return base


def _registro(label, caso, texto):
    return {
        "schema_version": 2,
        "label": label,
        "case": caso,
        "run": 1,
        "attempt": 1,
        "outcome": "ok",
        "descartada": False,
        "response": texto,
    }


def _escenario(tmp_path, *, opcionales=("principal", "especifico"), mensaje_extra=None):
    """Un corpus pequeno: N_REALES casos reales y 3 trampa, con sus mensajes de los dos modelos."""
    casos, registros = {}, []
    (tmp_path / "fuentes").mkdir(exist_ok=True)
    for i in range(N_REALES):
        casos[f"k{i}"] = {"id": f"k{i}", "source_file": f"k{i}.diff", "rol_en_hoja": "real"}
        (tmp_path / "fuentes" / f"k{i}.diff").write_text(_diff(f"k{i}"), encoding="utf-8")
        for modelo in (L26, LQW):
            texto = _mensaje(modelo, i)
            if mensaje_extra and i == 0 and modelo == L26:
                texto += mensaje_extra
            registros.append(_registro(modelo, f"k{i}", texto))
    entradas = []
    for j in range(3):
        casos[f"t{j}"] = {"id": f"t{j}", "source_file": f"t{j}.diff", "rol_en_hoja": "trampa"}
        (tmp_path / "fuentes" / f"t{j}.diff").write_text(_diff(f"t{j}"), encoding="utf-8")
        registros.append(
            _registro(L26, f"t{j}", f"feat(trampa-{j}): alfa {j}\n\n- a {j}\n- b {j}\n- c {j}")
        )
        registros.append(_registro(LQW, f"t{j}", f"fix(trampa-{j}): beta {j}\n\n- x {j}\n- y {j}"))
        entradas.append(
            {
                "caso": f"t{j}",
                "tipo": ("misma-zona", "secundario", "generico")[j],
                "asunto": f"docs: asunto de la trampa {j}",
                "cuerpo": [f"{linea} {j}" for linea in CUERPO_TRAMPA],
            }
        )
    trampas = {"juegos": [{"juego": 1, "trampas": entradas}]}
    reglas = {**REGLAS_HOJA, "preguntas_opcionales": list(opcionales)}
    return casos, registros, trampas, reglas


def _hoja(tmp_path, semilla=7, numero=1, **kw):
    casos, registros, trampas, reglas = _escenario(tmp_path, **kw)
    hoja, clave = hoja_pares.construir_hoja_commit(
        casos=casos,
        fuentes=tmp_path / "fuentes",
        registros=registros,
        trampas=trampas,
        reglas=reglas,
        juego=1,
        numero=numero,
        semilla=semilla,
        label_26b=L26,
        label_qwen=LQW,
    )
    return hoja, clave, reglas, (casos, registros, trampas)


def _generar_a_disco(tmp_path, **kw):
    hoja, clave, reglas, _ = _hoja(tmp_path, **kw)
    rutas = hoja_pares.escribir_hoja(hoja, clave, reglas, tmp_path / "hoja", tmp_path / "clave")
    return hoja, clave, reglas, rutas


def _lado(clave, num, quien):
    lados = clave["pares"][num]["lados"]
    return "A" if lados["A"] == quien else "B"


def _respuestas(clave, *, c=0, v=0, empates=0, inventa=0, trampas="peor", completo=False):
    """Respuestas ya contestadas: `c` pares reales para el 26B, `v` para Qwen, `empates` en `=`,
    `inventa` mensajes del 26B marcados como «inventa». El resto de pares reales queda sin contestar."""
    reales = [n for n, p in sorted(clave["pares"].items()) if p["tipo"] == "real"]
    pedidos = ["c"] * c + ["v"] * v + ["="] * empates
    respuestas: dict = {}
    for indice, (num, quien) in enumerate(zip(reales, pedidos, strict=False)):
        l26, lq = _lado(clave, num, L26), _lado(clave, num, LQW)
        respuestas[num] = {
            "inventa": {l26: "s" if indice < inventa else "n", lq: "n"},
            "preferencia": l26 if quien == "c" else lq if quien == "v" else "=",
        }
    for num, p in sorted(clave["pares"].items()):
        if p["tipo"] != "trampa" or trampas is None:
            continue
        modelo = next(m for m in p["lados"].values() if m != "trampa")
        lado_modelo = _lado(clave, num, modelo)
        lado_trampa = "A" if lado_modelo == "B" else "B"
        respuestas[num] = {
            "inventa": {"A": "n", "B": "n"},
            "preferencia": lado_modelo if trampas == "peor" else lado_trampa,
        }
    if completo:
        assert len(respuestas) == len(clave["pares"])
    return {"hoja": clave["hoja"], "sha256": clave["sha256"], "respuestas": respuestas}


def test_la_hoja_no_delata_a_nadie(tmp_path):
    # Si el generador para antes de escribir (su propia guarda contra repetidos), el test lo dice con
    # un assert y no con una excepcion suelta.
    generada, parada = None, None
    try:
        generada = _generar_a_disco(tmp_path)
    except SystemExit as exc:
        parada = exc
    assert generada is not None, f"el generador no llego a escribir la hoja: {parada}"
    hoja, clave, _reglas, rutas = generada
    html_ = rutas["html"].read_text(encoding="utf-8")
    md = rutas["md"].read_text(encoding="utf-8")
    clave_txt = rutas["clave"].read_text(encoding="utf-8")
    # Control positivo de la busqueda: la clave SI lleva los nombres; si no, el test no buscaria nada.
    assert L26 in clave_txt and LQW in clave_txt
    delatores = [
        x
        for x in (L26, LQW, "label_26b", "label_qwen", "lados", "trampa_tipo")
        if x in html_ or x in md
    ]
    assert not delatores, delatores
    # Ningun diff ni mensaje sale dos veces.
    textos = [t for par in hoja["pares"] for t in (par["diff"], par["A"], par["B"])]
    repetidos = [t for t in textos if md.count(t.strip("\n")) != 1]
    assert not repetidos, repetidos[:1]
    assert len(set(textos)) == len(textos)
    # Las trampas copian la forma del mensaje con el que se emparejan.
    trampas = [(n, p) for n, p in clave["pares"].items() if p["tipo"] == "trampa"]
    assert len(trampas) == 3
    por_num = {par["num"]: par for par in hoja["pares"]}
    for num, p in trampas:
        lado_trampa = "A" if p["lados"]["A"] == "trampa" else "B"
        lado_otro = "B" if lado_trampa == "A" else "A"
        trampa, pareja = por_num[num][lado_trampa], por_num[num][lado_otro]
        assert hoja_pares.forma(trampa) == hoja_pares.forma(pareja)
    # Y entre los 3 pares hay mensajes con cuerpo: el control no es de una linea contra una linea.
    assert any(hoja_pares.forma(por_num[n][_lado(clave, n, L26)])[0] for n, _ in trampas)


def test_la_clave_no_esta_junto_a_la_hoja(tmp_path):
    _hoja_, _clave, _reglas, rutas = _generar_a_disco(tmp_path)
    hoja_dir = tmp_path / "hoja"
    assert not (hoja_dir / "clave-1.json").exists()
    assert not list(hoja_dir.glob("clave*"))
    assert rutas["clave"].is_file() and rutas["clave"].parent == tmp_path / "clave"
    with pytest.raises(SystemExit, match="otra carpeta|carpeta de la hoja"):
        hoja_pares.escribir_hoja(_hoja_, _clave, _reglas, tmp_path / "x", tmp_path / "x")


def test_no_se_pisa_una_hoja_ya_generada(tmp_path):
    hoja, clave, reglas, _ = _hoja(tmp_path)
    hoja_pares.escribir_hoja(hoja, clave, reglas, tmp_path / "hoja", tmp_path / "clave")
    with pytest.raises(SystemExit, match="ya existen"):
        hoja_pares.escribir_hoja(hoja, clave, reglas, tmp_path / "hoja", tmp_path / "clave")


def test_misma_semilla_misma_hoja_y_las_trampas_no_siempre_en_las_mismas_posiciones(tmp_path):
    h1, c1, _, _ = _hoja(tmp_path, semilla=11)
    h2, c2, _, _ = _hoja(tmp_path, semilla=11)
    assert h1 == h2 and c1 == c2
    total = len(h1["pares"])
    assert total == N_REALES + 3
    todas = set()
    for semilla in range(1, 9):
        _, clave, _, _ = _hoja(tmp_path, semilla=semilla)
        posiciones = sorted(int(n) for n, p in clave["pares"].items() if p["tipo"] == "trampa")
        assert posiciones != list(range(total - 2, total + 1)), (
            f"semilla {semilla}: trampas al final"
        )
        todas.add(tuple(posiciones))
    assert len(todas) > 1
    # Otra semilla da otra hoja (y otro sha256).
    assert _hoja(tmp_path, semilla=12)[0]["id"] != h1["id"]


def test_la_trampa_copia_la_forma_del_mensaje_con_el_que_se_empareja():
    trampa = {"asunto": "docs: algo", "cuerpo": CUERPO_TRAMPA}
    sin_cuerpo = hoja_pares.trampa_con_forma(trampa, "feat: x")
    assert sin_cuerpo == "docs: algo"
    con_dos = hoja_pares.trampa_con_forma(trampa, "feat: x\n\n- uno\n- dos")
    assert con_dos == "docs: algo\n\n- cuerpo uno\n- cuerpo dos"
    # Sin linea en blanco y sin viñetas en el modelo: tampoco la lleva la trampa.
    prosa = hoja_pares.trampa_con_forma(trampa, "feat: x\nuna linea\notra linea")
    assert prosa == "docs: algo\n- cuerpo uno\n- cuerpo dos"
    # Como mucho 5 lineas, aunque el modelo escriba 8.
    largo = "feat: x\n\n" + "\n".join(f"- l{i}" for i in range(8))
    assert hoja_pares.forma(hoja_pares.trampa_con_forma(trampa, largo)) == (True, 5)
    assert hoja_pares.forma(largo) == (True, 5)


def test_un_mensaje_repetido_en_la_hoja_para_el_generador(tmp_path):
    casos, registros, trampas, reglas = _escenario(tmp_path)
    for r in registros:  # el mismo mensaje para dos casos distintos
        if r["case"] in ("k1", "k2") and r["label"] == L26:
            r["response"] = "feat: identico"
    with pytest.raises(SystemExit, match="dos veces"):
        hoja_pares.construir_hoja_commit(
            casos=casos,
            fuentes=tmp_path / "fuentes",
            registros=registros,
            trampas=trampas,
            reglas=reglas,
            juego=1,
            numero=1,
            semilla=1,
            label_26b=L26,
            label_qwen=LQW,
        )


# --- Leer las respuestas ---------------------------------------------------------------------------


def test_leer_commit_acepta_una_hoja_completa_y_destapa_con_la_clave(tmp_path):
    hoja, clave, reglas, _ = _hoja(tmp_path)
    r = _respuestas(clave, c=6, v=2, empates=2, inventa=1)
    juicio, faltan = hoja_pares.leer_commit(r, clave, reglas)
    assert faltan == []
    assert juicio["parcial"] is False and juicio["hoja"] == hoja["id"]
    reales = [p for p in juicio["pares"].values() if p["tipo"] == "real"]
    assert sum(p["lados"][p["preferencia"]] == L26 for p in reales if p["preferencia"] != "=") == 6
    assert sum(p["preferencia"] == "=" for p in reales) == 2


def test_las_preguntas_opcionales_salen_de_reglas_json(tmp_path):
    _, clave, reglas, _ = _hoja(tmp_path)
    r = _respuestas(clave, c=10)
    # Opcionales (la propuesta del usuario): sin «lo principal» ni «especifico» se acepta.
    aceptada = hoja_pares.leer_commit(r, clave, reglas)[1] == []
    assert aceptada, "con principal y especifico opcionales, la hoja sin ellas se acepta"
    # Obligatorias: la misma hoja ya no se acepta, y dice que falta.
    obligatorias = {**reglas, "preguntas_opcionales": []}
    _, faltan = hoja_pares.leer_commit(r, clave, obligatorias)
    assert faltan and all("principal" in f or "especifico" in f for f in faltan)
    assert len(faltan) == 4 * len(clave["pares"])
    # «Inventa» no puede ser opcional: el fichero de reglas se rechaza.
    ruta = tmp_path / "reglas.json"
    ruta.write_text(json.dumps({**reglas, "preguntas_opcionales": ["inventa"]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="inventa"):
        hoja_pares.leer_reglas(ruta)
    ruta.write_text(
        json.dumps({**reglas, "preguntas_opcionales": ["preferencia"]}), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="preguntas_opcionales"):
        hoja_pares.leer_reglas(ruta)


def test_si_falta_una_obligatoria_dice_cual_y_no_produce_nada(tmp_path, capsys):
    _, clave, reglas, _ = _hoja(tmp_path)
    r = _respuestas(clave, c=10)
    num = min(r["respuestas"])
    lado = min(r["respuestas"][num]["inventa"])
    del r["respuestas"][num]["inventa"][lado]
    _, faltan = hoja_pares.leer_commit(r, clave, reglas)
    assert faltan == [f"par {num}: inventa {lado}"]
    # Por la linea de ordenes: error, sin fichero de salida.
    (tmp_path / "r.json").write_text(json.dumps(r), encoding="utf-8")
    (tmp_path / "clave.json").write_text(json.dumps(clave), encoding="utf-8")
    (tmp_path / "reglas.json").write_text(json.dumps(reglas), encoding="utf-8")
    argumentos = [
        "leer-commit",
        "--clave",
        str(tmp_path / "clave.json"),
        "--reglas",
        str(tmp_path / "reglas.json"),
        "--respuestas",
        str(tmp_path / "r.json"),
        "--salida",
        str(tmp_path / "juicio.json"),
    ]
    assert hoja_pares.main(argumentos) == 1
    assert not (tmp_path / "juicio.json").exists()
    assert f"par {num}: inventa {lado}" in capsys.readouterr().err


def test_respuestas_de_otra_hoja(tmp_path):
    # Los mismos pares con otra semilla: las respuestas estan COMPLETAS y todos los numeros de par
    # existen, asi que solo el sha256 puede distinguirlas.
    _, clave_a, reglas, _ = _hoja(tmp_path, semilla=1)
    _, clave_b, _, _ = _hoja(tmp_path, semilla=2)
    respuestas_a = _respuestas(clave_a, c=10, completo=True)
    assert hoja_pares.leer_commit(respuestas_a, clave_a, reglas)[1] == []  # control positivo
    with pytest.raises(SystemExit, match="sha256"):
        hoja_pares.leer_commit(respuestas_a, clave_b, reglas)


def test_valores_invalidos_y_pares_desconocidos(tmp_path):
    _, clave, reglas, _ = _hoja(tmp_path)
    r = _respuestas(clave, c=10)
    num = min(r["respuestas"])
    r["respuestas"][num]["preferencia"] = "C"
    with pytest.raises(SystemExit, match="no es valido para preferencia"):
        hoja_pares.leer_commit(r, clave, reglas)
    r = _respuestas(clave, c=10)
    r["respuestas"]["99"] = {"preferencia": "A"}
    with pytest.raises(SystemExit, match="99"):
        hoja_pares.leer_commit(r, clave, reglas)


# --- Parada anticipada -----------------------------------------------------------------------------


def _parada(tmp_path, **kw):
    _, clave, reglas, _ = _hoja(tmp_path)
    juicio, _ = hoja_pares.leer_commit(_respuestas(clave, **kw), clave, reglas, parcial=True)
    salida = hoja_pares.puedes_parar(juicio, reglas)
    assert not any(x in salida for x in ("26B", "Qwen", "qwen", "aprob", L26, LQW)), salida
    return salida


def test_parada_anticipada(tmp_path):
    # Decidido: las trampas valen y el 26B ya paso del maximo (2) de «inventa».
    assert _parada(tmp_path, c=5, inventa=3) == "puedes parar"
    # Sin decidir: `v - c` (3) es igual a los pares que faltan (3): aun podria empatar y no perder.
    salida = _parada(tmp_path, v=3, empates=4)
    assert salida == "sigue"
    # Con `v - c` mayor que los que faltan, ya no puede alcanzar a Qwen.
    assert _parada(tmp_path, v=6) == "puedes parar"
    # Las trampas sin contestar: «sigue» aunque el 26B ya se haya pasado.
    salida = _parada(tmp_path, c=5, inventa=3, trampas=None)
    assert salida == "sigue"
    # Una hoja que no vale (la trampa preferida en las 3): tampoco se puede parar.
    assert _parada(tmp_path, c=5, inventa=3, trampas="mejor") == "sigue"


def test_leer_commit_parcial_solo_contesta_una_palabra(tmp_path, capsys):
    _, clave, reglas, _ = _hoja(tmp_path)
    (tmp_path / "clave.json").write_text(json.dumps(clave), encoding="utf-8")
    (tmp_path / "reglas.json").write_text(json.dumps(reglas), encoding="utf-8")
    for nombre, kw, esperado in (
        ("a", {"c": 5, "inventa": 3}, "puedes parar"),
        ("b", {"c": 5}, "sigue"),
    ):
        (tmp_path / f"{nombre}.json").write_text(
            json.dumps(_respuestas(clave, **kw)), encoding="utf-8"
        )
        capsys.readouterr()
        rc = hoja_pares.main(
            [
                "leer-commit",
                "--parcial",
                "--clave",
                str(tmp_path / "clave.json"),
                "--reglas",
                str(tmp_path / "reglas.json"),
                "--respuestas",
                str(tmp_path / f"{nombre}.json"),
            ]
        )
        assert rc == 0
        assert capsys.readouterr().out.strip() == esperado


# --- La hoja .md y la pagina -----------------------------------------------------------------------


def _rellenar_md(md, respuestas):
    """Contesta la hoja `.md` a mano: escribe el valor detras de cada pregunta, fuera de las vallas."""
    salida, par, valla = [], None, None
    nombres = {"Inventa": "inventa", "Lo principal": "principal", "Específico": "especifico"}
    for linea in md.split("\n"):
        if valla is not None:
            salida.append(linea)
            valla = None if linea == valla else valla
            continue
        if linea.startswith("```"):
            valla = linea[: len(linea) - len(linea.lstrip("`"))]
            salida.append(linea)
            continue
        if linea.startswith("## Par "):
            par = linea.split()[-1]
        elif par is not None and par in respuestas:
            dadas = respuestas[par]
            if linea.startswith("Mejor (A/B/=):") and dadas.get("preferencia"):
                linea = f"Mejor (A/B/=): {dadas['preferencia']}"
            for rotulo, clave_ in nombres.items():
                for lado in "AB":
                    if linea.startswith(f"{rotulo} {lado} ") and dadas.get(clave_, {}).get(lado):
                        linea = linea.split(":")[0] + f": {dadas[clave_][lado]}"
        salida.append(linea)
    return "\n".join(salida)


def test_la_hoja_md_se_contesta_a_mano_y_el_lector_la_entiende(tmp_path):
    # Un mensaje con una linea que parece una respuesta: dentro de la valla no puede votar.
    _, clave, reglas, rutas = _generar_a_disco(tmp_path, mensaje_extra="\nMejor (A/B/=): A")
    md = rutas["md"].read_text(encoding="utf-8")
    vacio = hoja_pares.respuestas_de_md(md)
    assert vacio["sha256"] == clave["sha256"]
    assert all(not p.get("preferencia") for p in vacio["respuestas"].values())
    r = _respuestas(clave, c=7, v=3, inventa=2)
    leidas = hoja_pares.respuestas_de_md(_rellenar_md(md, r["respuestas"]))
    juicio, faltan = hoja_pares.leer_commit(leidas, clave, reglas)
    assert faltan == []
    num = next(iter(r["respuestas"]))
    assert juicio["pares"][num]["preferencia"] == r["respuestas"][num]["preferencia"]


def test_la_pagina_exporta_lo_que_leer_commit_acepta(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no esta en el PATH")
    _, clave, reglas, rutas = _generar_a_disco(tmp_path)
    html_ = rutas["html"].read_text(encoding="utf-8")
    logica = html_.split('<script id="logica">', 1)[1].split("</script>", 1)[0]
    datos = json.loads(
        html_.split('<script type="application/json" id="datos">', 1)[1].split("</script>", 1)[0]
    )
    assert datos["id"] == clave["sha256"]
    estado = {}
    for par in datos["pares"]:
        estado[par["num"]] = {"inventa.A": "n", "inventa.B": "s", "preferencia": "A"}
    (tmp_path / "datos.json").write_text(json.dumps(datos), encoding="utf-8")
    (tmp_path / "estado.json").write_text(json.dumps(estado), encoding="utf-8")
    programa = tmp_path / "prueba.js"
    programa.write_text(
        logica
        + "\nconst fs = require('fs');\n"
        + f"const datos = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'datos.json'))}, 'utf8'));\n"
        + f"const estado = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'estado.json'))}, 'utf8'));\n"
        + "console.log(JSON.stringify({exportado: exportar(estado, datos, false), faltan: faltan(estado, datos)}));\n",
        encoding="utf-8",
    )
    salida = json.loads(
        subprocess.run([node, str(programa)], capture_output=True, text=True, check=True).stdout
    )
    assert salida["faltan"] == []
    _, faltan = hoja_pares.leer_commit(salida["exportado"], clave, reglas)
    assert faltan == [], faltan
    # Con una obligatoria menos, el lector dice cual falta, y el contador de la pagina tambien.
    del estado["03"]["inventa.B"]
    (tmp_path / "estado.json").write_text(json.dumps(estado), encoding="utf-8")
    salida = json.loads(
        subprocess.run([node, str(programa)], capture_output=True, text=True, check=True).stdout
    )
    assert salida["faltan"] == [["03", "inventa.B"]]
    _, faltan = hoja_pares.leer_commit(salida["exportado"], clave, reglas)
    assert faltan == ["par 03: inventa B"]


def test_la_pagina_es_autonoma_y_no_lleva_nombres(tmp_path):
    _, _, _, rutas = _generar_a_disco(tmp_path)
    html_ = rutas["html"].read_text(encoding="utf-8")
    for externo in ("http://", "https://", "<link", " src=", "@import", "url("):
        assert externo not in html_, externo
    assert "Descargar respuestas" in html_ and "¿Puedo parar ya?" in html_
    assert "localStorage" in html_ and "Faltan" in html_


# --- Sin el paquete ----------------------------------------------------------------------------------


def test_no_importa_el_paquete(tmp_path):
    """`generar-commit` y `leer-commit` corren con `local_delegate` bloqueado: importarlo cargaria
    `server.py` mientras otras tareas lo editan."""
    casos, registros, trampas, reglas = _escenario(tmp_path)
    (tmp_path / "cases.json").write_text(
        json.dumps({"schema_version": 2, "cases": list(casos.values())}), encoding="utf-8"
    )
    (tmp_path / "trampas.json").write_text(json.dumps(trampas), encoding="utf-8")
    (tmp_path / "reglas.json").write_text(json.dumps(reglas), encoding="utf-8")
    (tmp_path / "r.jsonl").write_text("\n".join(json.dumps(r) for r in registros), encoding="utf-8")

    def correr(argumentos):
        programa = (
            "import runpy, sys\n"
            "sys.modules['local_delegate'] = None\n"
            f"sys.argv = ['hoja_pares.py'] + {argumentos!r}\n"
            f"runpy.run_path(r'{RAIZ / 'scripts' / 'hoja_pares.py'}', run_name='__main__')\n"
        )
        return subprocess.run(
            [sys.executable, "-c", programa], capture_output=True, text=True, timeout=60
        )

    proc = correr(
        [
            "generar-commit",
            "--cases",
            str(tmp_path / "cases.json"),
            "--trampas",
            str(tmp_path / "trampas.json"),
            "--reglas",
            str(tmp_path / "reglas.json"),
            "--semilla",
            "3",
            "--label-26b",
            L26,
            "--label-qwen",
            LQW,
            "--hoja-dir",
            str(tmp_path / "hoja"),
            "--clave-dir",
            str(tmp_path / "clave"),
            str(tmp_path / "r.jsonl"),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    clave = json.loads((tmp_path / "clave" / "clave-1.json").read_text(encoding="utf-8"))
    (tmp_path / "parcial.json").write_text(
        json.dumps(_respuestas(clave, c=5, inventa=3)), encoding="utf-8"
    )
    proc = correr(
        [
            "leer-commit",
            "--parcial",
            "--clave",
            str(tmp_path / "clave" / "clave-1.json"),
            "--reglas",
            str(tmp_path / "reglas.json"),
            "--respuestas",
            str(tmp_path / "parcial.json"),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "puedes parar"
