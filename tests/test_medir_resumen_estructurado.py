"""Controles de la métrica de la etapa 1 (SDD `resumen-por-secciones`, T6).

La métrica usa el emparejamiento de producción, así que no puede señalar un fallo de esa función:
por eso cada control lleva el resultado esperado **escrito a mano**, contado sobre la salida de
ejemplo, y los hay en los dos sentidos —salidas que tienen que pasar y salidas que no—.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).parents[1]


def _cargar():
    spec = importlib.util.spec_from_file_location(
        "medir_resumen_estructurado", RAIZ / "scripts" / "medir_resumen_estructurado.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["medir_resumen_estructurado"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


medir = _cargar().medir
veredicto = sys.modules["medir_resumen_estructurado"].veredicto

ESPERADOS = ["Por qué existe", "Arranque", "Clientes", "Autenticación del puerto"]
FRASE = "El daemon arranca una vez y sirve a todos los clientes por HTTP."  # 13 palabras


def _bueno() -> str:
    return "\n\n".join(f"## {t}\n{FRASE}" for t in ESPERADOS)


def test_un_buen_resumen_pasa():
    r = medir(_bueno(), ESPERADOS, 500)
    assert (r["emparejados"], r["con_contenido"], r["fuera_de_orden"]) == (4, 4, 0)
    assert r["cobertura"] == 1.0
    assert r["palabras"] == 4 * 13
    assert r["pasa_estructura"] is True


def test_solo_titulos_falla_el_contenido():
    r = medir("\n\n".join(f"## {t}" for t in ESPERADOS), ESPERADOS, 500)
    assert (r["emparejados"], r["con_contenido"]) == (4, 0)
    assert r["pasa_estructura"] is False


def test_prosa_que_menciona_los_titulos_da_cobertura_baja():
    prosa = (
        "El documento explica por qué existe el daemon, su arranque, los clientes y la "
        "autenticación del puerto, todo en prosa y sin títulos."
    )
    r = medir(prosa, ESPERADOS, 500)
    assert r["emparejados"] == 0
    assert r["cobertura"] == 0.0
    assert r["pasa_estructura"] is False


def test_titulos_desordenados_fallan_el_orden():
    orden = [ESPERADOS[1], ESPERADOS[0], ESPERADOS[2], ESPERADOS[3]]
    r = medir("\n\n".join(f"## {t}\n{FRASE}" for t in orden), ESPERADOS, 500)
    assert r["fuera_de_orden"] == 1
    assert r["emparejados"] == 3
    assert r["pasa_estructura"] is False


def test_las_completadas_por_el_servidor_no_cuentan():
    salida = (
        f"## Por qué existe\n{FRASE}\n\n## Arranque\n(sin resumir)\n\n"
        f"## Clientes\n{FRASE}\n\n## Autenticación del puerto\n(sin resumir)\n\n"
        "[local-delegate aviso: 2 secciones sin resumir por el límite de palabras o del modelo]"
    )
    r = medir(salida, ESPERADOS, 500)
    assert (r["emparejados"], r["completadas_por_el_servidor"]) == (2, 2)
    assert r["cobertura"] == 0.5
    assert r["palabras"] == 2 * 13  # ni los «(sin resumir)» ni el aviso cuentan
    assert r["pasa_estructura"] is False


def test_changelog_con_la_mitad_completada_falla():
    versiones = [f"[0.{i}.0] - 2026-09-{i:02d}" for i in range(1, 21)]
    partes = [
        f"## {v}\n" + (FRASE if i % 2 == 0 else "(sin resumir)") for i, v in enumerate(versiones)
    ]
    r = medir("\n\n".join(partes), versiones, 500)
    assert (r["emparejados"], r["completadas_por_el_servidor"]) == (10, 10)
    assert r["pasa_estructura"] is False
    assert veredicto({"changelog": {**r, "finish_reason": "stop"}})["changelog"] is False


def test_negrita_dentro_de_una_seccion_es_contenido():
    salida = _bueno().replace(f"## Arranque\n{FRASE}", "## Arranque\n**Puntos clave:**\n- " + FRASE)
    r = medir(salida, ESPERADOS, 500)
    assert r["con_contenido"] == 4
    assert r["pasa_estructura"] is True


def test_titulo_con_sufijo_casa_y_duplicado_con_una_aparicion_cuenta_una():
    salida = _bueno().replace("## Clientes", "## Clientes: Codex, Claude y opencode")
    assert medir(salida, ESPERADOS, 500)["emparejados"] == 4
    dobles = ["Notas", "Notas"]
    r = medir(f"## Notas\n{FRASE}", dobles, 500)
    assert r["emparejados"] == 1
    assert r["cobertura"] == 0.5


def test_el_veredicto_exige_los_tres_documentos_y_no_mira_el_juicio():
    bueno = medir(_bueno(), ESPERADOS, 500)
    malo = medir("prosa", ESPERADOS, 500)
    base = {"readme": bueno, "instalacion": bueno, "daemon": bueno}
    assert veredicto(base)["tres_documentos"] is True
    assert veredicto({**base, "daemon": malo})["tres_documentos"] is False
    assert veredicto({"changelog": {**bueno, "finish_reason": "length"}})["changelog"] is False


def test_la_cobertura_de_subsecciones_es_informativa_y_por_palabras():
    cobertura = sys.modules["medir_resumen_estructurado"].cobertura_subsecciones
    salida = "## Arranque\n**La sesión del navegador**: se entra con el token.\n"
    subs = ["La sesión del navegador", "Linux", "sesión"]
    assert cobertura(salida, subs) == {"total": 3, "nombradas": 2}
    assert cobertura("Linuxero", ["Linux"])["nombradas"] == 0
