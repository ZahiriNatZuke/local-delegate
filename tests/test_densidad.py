"""Densidad de Claude por evento, fusión del relleno y tramos (coste-api-y-cuota, T4).

Los campos nuevos se leen con `.get(...)` donde el código de antes no los tenía: contra ese código
el test tiene que fallar por su assert, no por un `KeyError`.
"""

from __future__ import annotations

import inspect
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import backend_mock
import httpx2
import pytest

from local_delegate import atribucion, config, coste, server
from local_delegate.web import metrics


@pytest.fixture(autouse=True)
def _respaldo_declarado(monkeypatch):
    """Sin variable de respaldo: el declarado (Opus 5.5 en subagente) en todos los tests."""
    monkeypatch.setattr(config, "COSTE_RESPALDO", "")


def _fila(**kw) -> dict:
    base = {
        "ts": "2026-10-06T10:00:00+00:00",
        "tool": "local_summarize",
        "model": "m",
        "source": "path",
        "chars_in": 4000,
        "chars_out": 400,
        "ok": True,
    }
    base.update(kw)
    return base


def _extraer_funcion_js(fuente: str, cabecera: str) -> str:
    i = fuente.index(cabecera)
    depth, j = 0, i
    while True:
        if fuente[j] == "{":
            depth += 1
        elif fuente[j] == "}":
            depth -= 1
            if depth == 0:
                return fuente[i : j + 1]
        j += 1


def _acct_en_js(tmp_path, casos: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    entrada = tmp_path / "casos.json"
    entrada.write_text(json.dumps(casos), encoding="utf-8")
    programa = tmp_path / "acct.mjs"
    programa.write_text(
        "import {readFileSync} from 'node:fs';\n"
        "const CPT = 4;\n"
        "const tok = c => Math.floor(c/CPT);\n"
        f"{_extraer_funcion_js(metrics.HTML, 'function tokensClaude(')}\n"
        f"{_extraer_funcion_js(metrics.HTML, 'function acct(e){')}\n"
        f"const casos = JSON.parse(readFileSync({json.dumps(str(entrada))}, 'utf-8'));\n"
        "console.log(JSON.stringify(casos.map(acct)));\n",
        encoding="utf-8",
    )
    salida = subprocess.run(
        [node, str(programa)], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(salida.stdout)


# --- Las dos copias solo dividen -----------------------------------------------------------------


def test_sin_densidad_las_dos_dan_cero(tmp_path):
    """Una fila SIN fundir no trae `densidad`: Python y JS dan 0, no una cifra con un respaldo
    inventado (REQ-033). Una fusión olvidada se ve."""
    fila = _fila(path="C:/docs/guia.md")
    assert "densidad" not in fila  # guarda: de verdad está sin fundir
    assert server.tokens_claude(4000, tipo="text", evento=fila) == 0
    assert server.tokens_claude(400, tipo="returned", evento=fila) == 0
    (js,) = _acct_en_js(tmp_path, [fila])
    assert (js.get("saved"), js.get("returned")) == (0, 0)
    # Control de que la misma fila, fundida, sí da tokens en las dos copias.
    (fundida,) = coste.fundir([fila], log_dir=tmp_path)
    assert server.tokens_claude(4000, tipo="text", evento=fundida) == 2000  # 4000 × 100 // 200


def test_el_mismo_py_con_haiku_da_menos_tokens():
    """Escenario de la spec: un `.py` por `path`. Opus 5.5 usa `c` = 2,03 (familia nueva, formato
    `Read`, `medida`); Haiku, `c` = 3,12 (familia anterior, `formato_read` sin medir → respaldo (2),
    `sin_numerar`). El valor de Haiku coincide con el del respaldo (3) porque `codigo` es la mayor
    `c` de su familia: lo que discrimina es el ORIGEN."""
    base = _fila(path="C:/src/app.py")
    d_opus = coste.resolver_densidad(dict(base, caller_model="claude-opus-5-5"))
    d_haiku = coste.resolver_densidad(dict(base, caller_model="claude-haiku-4-5"))
    assert d_opus["text"] == [203, "medida"]
    assert d_haiku["text"] == [312, "sin_numerar"]
    t_opus = server.tokens_claude(4000, tipo="text", evento={"densidad": d_opus})
    t_haiku = server.tokens_claude(4000, tipo="text", evento={"densidad": d_haiku})
    assert (t_opus, t_haiku) == (1970, 1282)  # 4000 × 100 // 203 y 4000 × 100 // 312
    assert t_haiku < t_opus


def test_la_tool_manda_sobre_la_extension():
    """REQ-032: primero la tool, después la extensión."""
    clase = coste.clase_de_contenido({"tool": "local_lint_summary", "path": "C:/src/app.py"})
    assert clase == "log"
    assert coste.clase_de_contenido({"tool": "local_commit_msg", "path": "x.md"}) == "diff"
    assert (
        coste.clase_de_contenido({"tool": "local_summarize", "path": "C:/src/app.py"}) == "codigo"
    )
    assert (
        coste.clase_de_contenido({"tool": "local_summarize", "path": "/a/b.LOCK"}) == "estructurado"
    )
    assert (
        coste.clase_de_contenido({"tool": "local_summarize", "path": "C:\\a.b\\volcado"}) == "otro"
    )


def test_las_columnas_de_devuelto_y_salida():
    """REQ-031: lo devuelto y lo escrito no van numerados; su clase sale de la tool."""
    d = coste.resolver_densidad(_fila(tool="local_extract", path="C:/a.md"))
    assert d["text"] == [200, "medida"]  # prosa, formato `Read`
    assert d["returned"] == [188, "medida"]  # estructurado, sin numerar
    assert d["output"] == [223, "medida"]  # prosa, sin numerar
    b = coste.resolver_densidad(_fila(tool="local_boilerplate", source="inline"))
    assert b["text"] == [241, "conservadora"]  # inline sin path: clase `otro`, sin numerar → (3)
    assert (b["returned"], b["output"]) == ([241, "medida"], [241, "medida"])  # codigo


def test_respaldo_por_variable(monkeypatch):
    """REQ-008: la variable manda sobre el declarado; con solo `modelo`, el hilo es `subagent`;
    un valor inválido usa el declarado y lo dice."""
    monkeypatch.setattr(config, "COSTE_RESPALDO", "claude-haiku-4-5")
    r = coste.respaldo()
    assert r["familia"] == "anterior"
    assert (r["modelo"], r["hilo"], r.get("respaldo_invalido")) == (
        "claude-haiku-4-5",
        "subagent",
        False,
    )

    monkeypatch.setattr(config, "COSTE_RESPALDO", "claude-opus-5:main")
    r = coste.respaldo()
    assert (r["modelo"], r["hilo"], r["familia"]) == ("claude-opus-5", "main", "nueva")

    monkeypatch.setattr(config, "COSTE_RESPALDO", "xyz")
    r = coste.respaldo()
    assert r.get("respaldo_invalido") is True
    assert (r["modelo"], r["hilo"]) == ("claude-opus-5-5", "subagent")

    # Y la fila fundida lo dice.
    (fila,) = coste.fundir([_fila()], log_dir=config.LOG_DIR)
    assert fila.get("respaldo_invalido") is True
    assert (fila["caller_model"], fila["caller_kind"]) == ("claude-opus-5-5", "subagent")


def test_la_variable_de_respaldo_se_lee_por_la_puerta_registrada():
    assert "LOCAL_DELEGATE_COSTE_RESPALDO" in config.VARIABLES_DE_ENTORNO


def test_marcas_de_familia():
    """REQ-030/031: un modelo de la familia que no está entre los medidos lleva `densidad de la
    familia`; uno fuera de la tabla, `familia supuesta` y la familia nueva."""
    assert coste.familia_y_marcas("claude-opus-5-5") == ("nueva", [])
    assert coste.familia_y_marcas("claude-sonnet-4-6") == ("anterior", ["densidad de la familia"])
    assert coste.familia_y_marcas("claude-opus-4-8") == ("nueva", ["densidad de la familia"])
    assert coste.familia_y_marcas("claude-xyz-1") == ("nueva", ["familia supuesta"])


# --- Imágenes fuera del neto (REQ-038) ----------------------------------------------------------


def test_una_imagen_no_resta_del_neto(tmp_path):
    """Escenario de la spec, con el evento de imagen del hermano: los campos del contrato no
    cambian, pero `saved = returned = net = 0` en las dos copias."""
    evento = {
        "tool": "local_describe_image",
        "source": "path",
        "chars_in": 250000,
        "chars_out": 800,
        "ok": True,
        "tokens_in": 1200,
        "tokens_out": 200,
    }
    (fila,) = coste.fundir([evento], log_dir=tmp_path)
    a = metrics._accounting(fila)
    assert a["saved"] == 0
    assert (a.get("returned"), a.get("net")) == (0, 0)
    assert a.get("bytes_saved_image") == 250000
    assert a.get("chars_returned") == 800
    assert fila["densidad"] == {"text": None, "returned": None, "output": None}
    (js,) = _acct_en_js(tmp_path, [fila])
    assert (js.get("saved"), js.get("returned"), js.get("net")) == (0, 0, 0)
    assert (js.get("bytesSavedImage"), js.get("charsReturned")) == (250000, 800)


# --- Fusión (REQ-006) ----------------------------------------------------------------------------

DE_LA_LINEA = "claude-opus-5"
DEL_RELLENO = "claude-haiku-4-5"


def test_la_fusion_respeta_el_orden(tmp_path):
    """Por campo: la línea, luego el relleno, luego el respaldo."""
    lineas = [
        _fila(tool_use_id="toolu_a", caller_model=DE_LA_LINEA, caller_kind="main"),
        _fila(tool_use_id="toolu_b", caller_kind="main", caller_src="hook"),
        _fila(ts="2026-10-06T10:00:05+00:00"),
    ]
    atribucion.escribir_relleno(
        tmp_path,
        "202610",
        {
            "toolu_a": {"caller_model": DEL_RELLENO, "caller_kind": "subagent", "cruce": "exacto"},
            "toolu_b": {
                "caller_model": DEL_RELLENO,
                "caller_kind": "subagent",
                "caller_effort": "n/a",
                "n": 12,
                "caducidades": 1,
                "cruce": "exacto",
                "banco": False,
            },
        },
    )
    a, b, c = coste.fundir(lineas, log_dir=tmp_path)

    assert a["caller_model"] == DE_LA_LINEA
    assert (a["caller_kind"], a.get("caller_origen")) == ("main", "linea")

    assert (b["caller_model"], b.get("caller_origen")) == (DEL_RELLENO, "relleno")
    assert b["caller_kind"] == "main", "por campo: el hilo de la línea manda sobre el del relleno"
    assert (b.get("n"), b.get("caducidades"), b.get("caller_effort")) == (12, 1, "n/a")
    assert b.get("familia") == "anterior"

    assert (c["caller_model"], c["caller_kind"], c.get("caller_origen")) == (
        "claude-opus-5-5",
        "subagent",
        "respaldo",
    )
    assert "respaldo_invalido" not in c
    # La entrada del relleno se busca con la clave del fichero entero.
    assert atribucion.claves_del_fichero(lineas)[2] == "2026-10-06T10:00:05+00:00|local_summarize|0"


def test_la_fusion_no_toca_la_cache(tmp_path, monkeypatch):
    """`fundir` copia: dos `_load` seguidos no dejan claves nuevas en las filas cacheadas."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    ruta = tmp_path / "usage-202610.jsonl"
    ruta.write_text(json.dumps(_fila()) + "\n", encoding="utf-8")
    metrics._FILE_CACHE.clear()
    desde = datetime(2026, 10, 1, tzinfo=UTC)
    hasta = datetime(2026, 11, 1, tzinfo=UTC)
    filas, _ = metrics._load(desde, hasta)
    assert filas[0].get("densidad") is not None  # guarda: lo que sale de `_load` va fundido
    metrics._load(desde, hasta)
    assert "densidad" not in metrics._read_file_cached(ruta)[0]
    assert "caller_origen" not in metrics._read_file_cached(ruta)[0]


# --- Tramos de la barra (REQ-007) ----------------------------------------------------------------


def test_tramos(tmp_path):
    ahora = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

    def hace(dias: int) -> str:
        return (ahora - timedelta(days=dias)).isoformat(timespec="seconds")

    def fundida(fila: dict, entrada: dict | None = None) -> dict:
        return coste.fundir_fila(fila, entrada)

    t = coste.tramo
    # Excluidos: clientes declarados y bancos, aunque traigan modelo.
    assert t(fundida(_fila(client="codex-mcp-client")), ahora=ahora, plazo_dias=30) == "excluido"
    assert t(fundida(_fila(client="mcp")), ahora=ahora, plazo_dias=30) == "excluido"
    banco = fundida(_fila(client="claude-code"), {"caller_model": DEL_RELLENO, "banco": True})
    assert t(banco, ahora=ahora, plazo_dias=30) == "excluido"
    # Al momento y por relleno.
    linea = fundida(_fila(caller_model=DE_LA_LINEA, ts=hace(100)))
    assert t(linea, ahora=ahora, plazo_dias=30) == "al_momento"
    relleno = fundida(_fila(ts=hace(100)), {"caller_model": DEL_RELLENO, "cruce": "exacto"})
    assert t(relleno, ahora=ahora, plazo_dias=30) == "por_relleno"
    # Sin modelo: pendiente mientras el transcript puede existir; supuesto después.
    f29, f31, f60 = (fundida(_fila(ts=hace(d))) for d in (29, 31, 60))
    assert t(f29, ahora=ahora, plazo_dias=30) == "pendiente"
    assert t(f31, ahora=ahora, plazo_dias=30) == "supuesto"
    assert t(f60, ahora=ahora, plazo_dias=90) == "pendiente"
    assert t(f60, ahora=ahora, plazo_dias=30) == "supuesto"
    # Un cruce `ambiguo` o `sin_cruce` ya no se arregla: supuesto aunque sea reciente.
    f = fundida(_fila(ts=hace(1)), {"cruce": "ambiguo"})
    assert t(f, ahora=ahora, plazo_dias=30) == "supuesto"
    f = fundida(_fila(ts=hace(1)), {"cruce": "sin_cruce"})
    assert t(f, ahora=ahora, plazo_dias=30) == "supuesto"


# --- Ningún `CHARS_PER_TOKEN` para tokens de Claude (REQ-034) ------------------------------------


def _bloque_de_tokens_aprox() -> str:
    fuente = inspect.getsource(server.local_extract)
    i = fuente.index('meta["leido_server_side"]')
    return fuente[i : fuente.index("}", i) + 1]


def test_ningun_chars_per_token_en_la_conversion():
    fuentes = {
        "tokens_claude": inspect.getsource(server.tokens_claude),
        "_savings_feedback": inspect.getsource(server._savings_feedback),
        "_escribir_destino": inspect.getsource(server._escribir_destino),
        "tokens_aprox": _bloque_de_tokens_aprox(),
    }
    assert "tokens_aprox" in fuentes["tokens_aprox"]  # guarda: el recorte encontró el bloque
    for nombre, fuente in fuentes.items():
        assert "CHARS_PER_TOKEN" not in fuente, nombre


# --- Los mensajes a Claude (REQ-035) -------------------------------------------------------------


def _backend(monkeypatch, tmp_path, *, prompt_tokens: int, texto: str = "resumen") -> None:
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    backend_mock.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": texto}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 5},
            },
        )
    )


@backend_mock.mock
def test_la_coletilla_usa_tokens_de_claude(monkeypatch, tmp_path):
    """`local_summarize` con `path` a un `.md` de 4000 caracteres: prosa, formato `Read`, familia
    nueva del respaldo → 4000 × 100 // 200 = 2000 tokens de Claude, no los 9999 del modelo local."""
    _backend(monkeypatch, tmp_path, prompt_tokens=9999)
    doc = tmp_path / "notas.md"
    doc.write_text("palabra " * 500, encoding="utf-8")
    assert len(doc.read_text(encoding="utf-8")) == 4000  # guarda del tamaño
    texto = server.local_summarize(path=str(doc))
    assert "≈ 2,000 tokens de Claude" in texto
    assert "9,999" not in texto
    assert texto.rstrip().endswith("que no entraron a tu contexto)")


@backend_mock.mock
def test_el_recibo_de_salida_usa_tokens_de_claude(monkeypatch, tmp_path):
    """Salida a fichero de `local_boilerplate`: clase `codigo`, sin numerar → c = 2,41."""
    codigo = "x = 1\n" * 100  # 600 caracteres
    _backend(monkeypatch, tmp_path, prompt_tokens=10, texto=codigo.strip())
    destino = tmp_path / "salida.py"
    recibo = server.local_boilerplate(spec="un módulo", language="python", target=str(destino))
    assert len(destino.read_text(encoding="utf-8")) == 600  # guarda del tamaño escrito
    assert (
        "600 chars (≈248 tokens de Claude que no entraron a tu contexto)" in recibo
    )  # 60000 // 241


@backend_mock.mock
def test_tokens_aprox_de_extract_es_de_claude(monkeypatch, tmp_path):
    _backend(monkeypatch, tmp_path, prompt_tokens=9999, texto='{"titulo": "x"}')
    doc = tmp_path / "datos.json"
    doc.write_text('{"a": "' + "b" * 3991 + '"}', encoding="utf-8")
    datos = server.local_extract(fields=["titulo"], path=str(doc))
    leido = datos.get("_local_delegate", {}).get("leido_server_side", {})
    assert leido.get("chars") == 4000
    # estructurado, formato `Read` sin medir → respaldo (2), sin numerar: 4000 × 100 // 188
    assert leido.get("tokens_aprox") == 2127


@backend_mock.mock
def test_la_coletilla_usa_el_modelo_de_la_nota_si_ya_esta(monkeypatch, tmp_path):
    """REQ-035: con la atribución de la llamada en curso (nota del hook y transcript), la coletilla
    usa ese modelo y no el respaldo. Haiku, `.md` por `path`: su `formato_read` está sin medir →
    respaldo (2), prosa sin numerar, c = 3,01 → 4000 × 100 // 301 = 1328 (con Opus 5.5, 2000)."""
    _backend(monkeypatch, tmp_path, prompt_tokens=9999)
    monkeypatch.setattr(
        atribucion,
        "llamada_actual",
        lambda: {"caller_model": "claude-haiku-4-5", "caller_kind": "main", "caller_src": "hook"},
    )
    doc = tmp_path / "notas.md"
    doc.write_text("palabra " * 500, encoding="utf-8")
    texto = server.local_summarize(path=str(doc))
    assert "≈ 1,328 tokens de Claude" in texto
