"""Hoja por pares a ciegas (P-15): valida la puntuacion automatica contra juicio humano.

Cada propiedad que la hace fiable tiene su prueba: que oculta el modelo y sortea el lado, que solo
empareja corridas validas de la misma corrida, que una respuesta no puede votar por si misma y que el
acuerdo se cuenta como se escribio (un empate humano donde la metrica ve diferencia no es acuerdo).
"""

from __future__ import annotations

import importlib.util
import json
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
