"""Tests del banco y del experimento de adopción (SDD subagente-lector-local, spec v2, tarea 5).

Solo las partes puras: reglas del veredicto, plan de corridas, hecho plantado y lectura del
transcript. Lo que lanza `claude -p` se prueba corriendo (tareas 4 y 5), no aquí.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


banco = _load("_banco_claude")
exp = _load("experimento_adopcion")


# --- Veredicto ------------------------------------------------------------------------------------


def _filas(correctas: dict[tuple[str, str], int], r: int = 3, coste: dict | None = None):
    coste = coste or {}
    filas = []
    for (tarea, oferta), n in correctas.items():
        for i in range(r):
            filas.append(
                {
                    "tarea": tarea,
                    "oferta": oferta,
                    "valida": True,
                    "correcta": i < n,
                    "coste_usd": coste.get(oferta, 0.4),
                }
            )
    return filas


def _tabla(v0: list[int], v1: list[int], v2: list[int]) -> dict:
    return {
        (f"t{i}", oferta): n
        for oferta, valores in (("v0", v0), ("v1", v1), ("v2", v2))
        for i, n in enumerate(valores)
    }


def test_gana_la_que_supera_a_v0_en_mas_tareas():
    tabla = _tabla([0] * 8, [1, 1, 1, 0, 0, 0, 0, 0], [2, 2, 2, 2, 0, 0, 0, 0])
    assert exp.veredicto(_filas(tabla))["elegida"] == "v2"


def test_sin_tres_tareas_no_gana_nadie():
    # Control: con 2 de 8 no llega al mínimo, aunque supere a V0 por mucho.
    tabla = _tabla([0] * 8, [3, 3, 0, 0, 0, 0, 0, 0], [0] * 8)
    assert exp.veredicto(_filas(tabla))["elegida"] is None


def test_empate_en_tareas_lo_decide_el_coste():
    tabla = _tabla([0] * 8, [1, 1, 1, 0, 0, 0, 0, 0], [1, 1, 1, 0, 0, 0, 0, 0])
    filas = _filas(tabla, coste={"v0": 0.4, "v1": 0.5, "v2": 0.3})
    assert exp.veredicto(filas)["elegida"] == "v2"


def test_empate_en_tareas_y_coste_gana_la_mas_simple():
    tabla = _tabla([0] * 8, [1, 1, 1, 0, 0, 0, 0, 0], [1, 1, 1, 0, 0, 0, 0, 0])
    assert exp.veredicto(_filas(tabla))["elegida"] == "v1"


def test_igualar_a_v0_no_es_superarlo():
    tabla = _tabla([2] * 8, [2] * 8, [2] * 8)
    resultado = exp.veredicto(_filas(tabla))
    assert resultado["elegida"] is None
    assert resultado["supera_a_v0_en"] == {"v1": [], "v2": []}


def test_las_corridas_invalidas_no_cuentan():
    tabla = _tabla([0] * 8, [1, 1, 1, 0, 0, 0, 0, 0], [0] * 8)
    filas = _filas(tabla)
    for f in filas:
        if f["oferta"] == "v1":
            f["valida"] = False
    assert exp.veredicto(filas)["elegida"] is None


# --- Plan de corridas y hecho plantado --------------------------------------------------------


def test_el_plan_cubre_todo_una_vez_y_es_reproducible():
    plan = exp.plan_de_corridas(["a", "b"], 3, semilla=7)
    assert len(plan) == len(set(plan)) == 2 * 3 * 3
    assert plan == exp.plan_de_corridas(["a", "b"], 3, semilla=7)
    assert plan != exp.plan_de_corridas(["a", "b"], 3, semilla=8)  # intercalado de verdad


@pytest.mark.parametrize("estilo", ["md", "log"])
def test_el_hecho_plantado_esta_una_vez_y_hacia_la_mitad(estilo):
    base = "".join(f"linea {i}\n" for i in range(400))
    texto, conector, valor = exp.plantar(base, estilo, random.Random(1))
    assert texto.count(valor) == 1 and conector in texto
    posicion = texto.index(valor) / len(texto)
    assert 0.3 < posicion < 0.7


def test_la_pregunta_no_menciona_delegar_ni_el_dato_plantado():
    # Sin el dato ni su conector: si la pregunta los nombra, `Grep` la resuelve sin leer (tarea 4).
    for estilo in ("md", "log"):
        texto = exp.pregunta(Path("C:/x/informe.md"), estilo).lower()
        for palabra in ("deleg", "local_", "tool", "umbral", "reintent", *exp.CONECTORES):
            assert palabra not in texto, (estilo, palabra)


def test_la_pregunta_del_piloto_no_nombra_secciones_ni_delegar():
    # Si nombrase las secciones, `Grep '^## '` sacaría los títulos sin leer ni delegar.
    texto = exp.pregunta_piloto(Path("C:/x/informe.md")).lower()
    for palabra in ("deleg", "local_", "tool", "secci", "título", "titulo", "##", "cifra"):
        assert palabra not in texto, palabra


def test_la_cobertura_cuenta_titulos_normalizados():
    doc = "# T\n## Por qué existe\nx\n## Opciones: `--agents`\ny\n### Sub\n## Arranque\n"
    titulos = exp.titulos_de_seccion(doc)
    assert titulos == ["Por qué existe", "Opciones: `--agents`", "Arranque"]
    respuesta = "- **Por qué existe**: ...\n- Opciones --agents: ...\n"
    assert exp.cobertura_de_titulos(respuesta, titulos) == pytest.approx(2 / 3)
    assert exp.cobertura_de_titulos(respuesta + "Arranque", titulos) == 1.0
    assert exp.cobertura_de_titulos("", titulos) == 0.0
    assert exp.cobertura_de_titulos("algo", []) == 0.0


def test_las_tareas_del_piloto_existen_y_tienen_secciones():
    tareas = {t["id"]: t for t in json.loads(exp.TAREAS.read_text(encoding="utf-8"))["tareas"]}
    for tid in exp.TAREAS_PILOTO:
        texto = (exp.RAIZ / tareas[tid]["fuente"]["repo"]).read_text(encoding="utf-8")
        assert len(exp.titulos_de_seccion(texto)) >= 5, tid


# --- Lectura del transcript -------------------------------------------------------------------


def _uso(uid: str, nombre: str, entrada: dict) -> dict:
    return {
        "message": {"content": [{"type": "tool_use", "id": uid, "name": nombre, "input": entrada}]}
    }


def _res(uid: str, texto: str, error: bool = False) -> dict:
    bloque = {"type": "tool_result", "tool_use_id": uid, "content": texto, "is_error": error}
    return {"message": {"content": [bloque]}}


def _diferidas(con_nuestras: bool = True) -> dict:
    nombres = ["CronCreate"] + ([banco.TOOL_PRINCIPAL] if con_nuestras else [])
    return {"attachment": {"type": "deferred_tools_delta", "addedNames": nombres}}


def test_delegar_con_path_no_mete_el_contenido(tmp_path):
    f = tmp_path / "doc.md"
    eventos = [
        _diferidas(),
        _uso("1", "ToolSearch", {"query": f"select:{banco.TOOL_PRINCIPAL}"}),
        _res("1", "ok"),
        _uso("2", banco.TOOL_PRINCIPAL, {"path": str(f)}),
        _res("2", "resumen"),
    ]
    visto = banco.analizar(eventos, f)
    assert visto["local_con_path"] == [banco.TOOL_PRINCIPAL]
    assert visto["toolsearch"] and not visto["contenido_en_contexto"]


def test_una_lectura_denegada_no_cuenta_como_leida(tmp_path):
    f = tmp_path / "doc.md"
    eventos = [
        _diferidas(),
        _uso("1", "Read", {"file_path": str(f)}),
        _res("1", "40 KB y es prosa", True),
    ]
    visto = banco.analizar(eventos, f)
    assert visto["bloqueado"] and not visto["read_completo"]


@pytest.mark.parametrize(
    ("uso", "resultado", "clave"),
    [
        (("Read", {"file_path": "{f}"}), "texto", "read_completo"),
        (("Read", {"file_path": "{f}", "offset": 10, "limit": 50}), "trozo", "read_franjas"),
        (("Bash", {"command": "cat doc.md"}), "x" * 3000, "volcado_bash"),
    ],
)
def test_las_tres_formas_de_meter_el_contenido(tmp_path, uso, resultado, clave):
    f = tmp_path / "doc.md"
    nombre, entrada = uso
    entrada = {k: (str(f) if v == "{f}" else v) for k, v in entrada.items()}
    visto = banco.analizar([_diferidas(), _uso("1", nombre, entrada), _res("1", resultado)], f)
    assert visto[clave]
    assert visto["contenido_en_contexto"]


def test_un_bash_corto_que_nombra_el_fichero_no_es_volcado(tmp_path):
    f = tmp_path / "doc.md"
    eventos = [
        _diferidas(),
        _uso("1", "Bash", {"command": "wc -c doc.md"}),
        _res("1", "40000 doc.md"),
    ]
    assert not banco.analizar(eventos, f)["contenido_en_contexto"]


def test_lo_del_subagente_no_cuenta_como_hilo_principal(tmp_path):
    f = tmp_path / "doc.md"
    lectura = {**_uso("1", "Read", {"file_path": str(f)}), "isSidechain": True}
    assert not banco.analizar([_diferidas(), lectura, _res("1", "t")], f)["read_completo"]


def test_sin_la_lista_de_diferidas_el_formato_es_desconocido(tmp_path):
    with pytest.raises(banco.FormatoDesconocido):
        banco.analizar([_uso("1", "Read", {"file_path": "x"})], tmp_path / "x")


def test_la_corrida_solo_es_valida_con_su_evento_de_prompt():
    bueno = {"event": "UserPromptSubmit", "session_id": "s1", "bloqueo": "encendido"}
    assert banco.corrida_valida([bueno], "s1")
    assert not banco.corrida_valida([bueno], "s2")  # otra sesión
    assert not banco.corrida_valida([{**bueno, "bloqueo": "apagado_fichero"}], "s1")
    assert not banco.corrida_valida([{**bueno, "event": "PreToolUse"}], "s1")
    assert not banco.corrida_valida([], "s1")


def test_dir_de_proyecto_sigue_la_convencion_de_claude_code():
    ruta = banco.dir_de_proyecto(Path(r"C:\Users\ana\AppData\Local\Temp\banco-lector"))
    assert ruta.name == "C--Users-ana-AppData-Local-Temp-banco-lector"


def test_las_diferidas_se_acumulan_delta_a_delta(tmp_path):
    """Medido en el control instalado: el primer delta traía las nuestras y el último, otras 5."""
    f = tmp_path / "doc.md"
    primero = {"attachment": {"type": "deferred_tools_delta", "addedNames": [banco.TOOL_PRINCIPAL]}}
    ultimo = {"attachment": {"type": "deferred_tools_delta", "addedNames": ["CronList"]}}
    assert banco.analizar([primero, ultimo], f)["tools_diferidas"]
    quita = {"attachment": {"type": "deferred_tools_delta", "removedNames": [banco.TOOL_PRINCIPAL]}}
    assert not banco.analizar([primero, ultimo, quita], f)["tools_diferidas"]


# --- Etapa 2 del SDD resumen-por-secciones --------------------------------------------------------


def _fila(tarea: str, correcta: bool, en_contexto: bool) -> dict:
    return {
        "tarea": tarea,
        "oferta": "v0",
        "valida": True,
        "correcta": correcta,
        "contenido_en_contexto": en_contexto,
    }


@pytest.mark.parametrize(
    ("correctas", "decision"),
    [
        (6, "se queda"),
        (9, "se queda"),
        (5, "no concluyente"),
        (4, "no concluyente"),
        (3, "se retira"),
    ],
)
def test_informe_resumen_decide_solo_por_correctas(correctas, decision):
    filas = [
        _fila(t, i * 3 + r < correctas, i * 3 + r >= correctas)
        for i, t in enumerate(("readme", "wiki-daemon", "wiki-instalacion"))
        for r in range(3)
    ]
    informe = exp.informe_resumen(filas)
    assert informe["correctas"] == correctas
    assert informe["contenido_en_contexto"] == 9 - correctas
    assert informe["decision"] == decision
    assert sum(t["corridas"] for t in informe["por_tarea"].values()) == 9


def test_informe_resumen_no_decide_con_otro_numero_de_corridas():
    filas = [_fila("readme", True, False)] * 8 + [{**_fila("readme", True, False), "valida": False}]
    assert exp.informe_resumen(filas)["decision"].startswith("sin decisión")


def test_plan_con_una_sola_variante():
    plan = exp.plan_de_corridas(["a", "b", "c"], 3, 7, ("v0",))
    assert len(plan) == 9 and {v for _t, v, _r in plan} == {"v0"}


def test_las_fuentes_fijas_sustituyen_al_fichero_vivo(tmp_path):
    fuentes = tmp_path / "fuentes"
    fuentes.mkdir()
    (fuentes / "readme.md").write_text("COPIA FIJA", encoding="utf-8")
    manifiesto = {"ficheros": {"readme.md": {"origen": "README.md"}}}
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifiesto), encoding="utf-8")
    tarea = {"id": "readme", "fuente": {"repo": "README.md"}}
    assert exp.texto_fuente(tarea, tmp_path / "cache", fuentes) == "COPIA FIJA"
    assert exp.texto_fuente(tarea, tmp_path / "cache") != "COPIA FIJA"
