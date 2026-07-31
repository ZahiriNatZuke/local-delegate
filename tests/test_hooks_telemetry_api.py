"""`/api/hooks`: lo que los hooks consultivos han sugerido, expuesto en el dashboard.

El dato ya se escribía —1800 eventos en tres días en la máquina de referencia— y `metrics.py` no
lo mencionaba ni una vez. Lo que estos tests vigilan sobre todo es que el panel **no diga más de
lo que el dato sostiene**: el hook sugiere, el usuario decide, y desde aquí no hay forma de saber
si la sugerencia se siguió.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from local_delegate import config
from local_delegate.web import metrics


@pytest.fixture(autouse=True)
def _sin_cache():
    """El lector cachea por (mtime, size), y en tests dos ficheros pueden coincidir en ambos."""
    metrics._FILE_CACHE.clear()
    yield
    metrics._FILE_CACHE.clear()


def _evento(cuando: datetime, *, evento="PreToolUse", categoria="bash", sugerida=False) -> dict:
    return {
        "ts": cuando.isoformat(),
        "event": evento,
        "suggested": sugerida,
        "category": categoria,
        "command_chars": 100,
    }


def _escribir(path, eventos: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in eventos) + "\n", encoding="utf-8")


# --- El agregado, que es donde vive todo el criterio ---------------------------


def test_cuenta_sugeridas_sobre_el_total():
    ahora = datetime.now(UTC)
    filas = [
        _evento(ahora, sugerida=True),
        _evento(ahora, sugerida=False),
        _evento(ahora, sugerida=False),
        _evento(ahora, sugerida=True),
    ]
    agregado = metrics._aggregate_hooks(filas)

    assert agregado["total"] == 4
    assert agregado["suggested"] == 2
    assert agregado["rate"] == 0.5


def test_un_evento_viejo_sin_el_campo_suggested_cuenta_como_no_sugirio():
    """El campo se añadió después; su ausencia significaba exactamente «no sugirió».

    Tratarla como `True` inflaría la tasa con eventos que nunca sugirieron nada, y el número
    saldría más bonito — que es justo por lo que hay que fijarlo con un test.
    """
    fila = {"ts": datetime.now(UTC).isoformat(), "event": "PreToolUse"}
    agregado = metrics._aggregate_hooks([fila])

    assert agregado["total"] == 1
    assert agregado["suggested"] == 0


def test_sin_eventos_la_tasa_es_cero_y_no_revienta():
    """Dividir entre cero aquí tumbaría el endpoint entero por no tener datos."""
    agregado = metrics._aggregate_hooks([])
    assert agregado == {
        "total": 0,
        "suggested": 0,
        "rate": 0.0,
        "by_event": [],
        "by_category": [],
        "by_day": [],
    }


def test_agrupa_por_evento_categoria_y_dia():
    hoy = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    ayer = hoy - timedelta(days=1)
    filas = [
        _evento(hoy, evento="PreToolUse", categoria="bash", sugerida=True),
        _evento(hoy, evento="PreToolUse", categoria="bash", sugerida=False),
        _evento(hoy, evento="UserPromptSubmit", categoria="read", sugerida=True),
        _evento(ayer, evento="PreToolUse", categoria="bash", sugerida=False),
    ]
    agregado = metrics._aggregate_hooks(filas)

    por_evento = {d["event"]: d for d in agregado["by_event"]}
    assert por_evento["PreToolUse"] == {"event": "PreToolUse", "total": 3, "suggested": 1}
    assert por_evento["UserPromptSubmit"]["suggested"] == 1

    por_categoria = {d["category"]: d for d in agregado["by_category"]}
    assert por_categoria["bash"]["total"] == 3

    assert [d["day"] for d in agregado["by_day"]] == [
        ayer.date().isoformat(),
        hoy.date().isoformat(),
    ], "los días tienen que salir en orden cronológico, no por volumen"


def test_una_categoria_ausente_no_se_pierde_en_el_recuento():
    """Sin la casilla «sin categoría», los totales por categoría no sumarían el total."""
    fila = {"ts": datetime.now(UTC).isoformat(), "event": "PreToolUse", "suggested": True}
    agregado = metrics._aggregate_hooks([fila])

    assert sum(d["total"] for d in agregado["by_category"]) == agregado["total"]
    assert agregado["by_category"][0]["category"] == "sin categoría"


def test_las_listas_salen_ordenadas_por_volumen():
    ahora = datetime.now(UTC)
    filas = [_evento(ahora, categoria="bash")] * 3 + [_evento(ahora, categoria="read")]
    agregado = metrics._aggregate_hooks(filas)
    assert [d["category"] for d in agregado["by_category"]] == ["bash", "read"]


# --- El endpoint --------------------------------------------------------------


def test_sin_la_variable_el_endpoint_lo_dice_en_vez_de_fingir_que_no_hay_nada(monkeypatch):
    """«No activaste la telemetría» y «está activada y no hay eventos» son cosas distintas.

    Sin `enabled`, un panel a cero se lee como «los hooks no sugieren nada» — una conclusión falsa
    sacada de un fichero que ni siquiera existe.
    """
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    datos = TestClient(metrics.app).get("/api/hooks").json()

    assert datos["enabled"] is False
    assert "LD_HOOK_TELEMETRY_LOG" in datos["reason"]
    assert datos["total"] == 0


def test_con_la_variable_pero_sin_fichero_dice_que_esta_activada(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", tmp_path / "no-existe.jsonl")
    datos = TestClient(metrics.app).get("/api/hooks").json()

    assert datos["enabled"] is True
    assert datos["exists"] is False
    assert datos["total"] == 0


def test_lee_el_log_de_verdad(monkeypatch, tmp_path):
    log = tmp_path / "telemetry.jsonl"
    ahora = datetime.now(UTC)
    _escribir(log, [_evento(ahora, sugerida=True), _evento(ahora, sugerida=False)])
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)

    datos = TestClient(metrics.app).get("/api/hooks").json()

    assert datos["enabled"] is True
    assert datos["exists"] is True
    assert (datos["total"], datos["suggested"]) == (2, 1)


def test_el_rango_filtra_igual_que_en_el_resto_del_panel(monkeypatch, tmp_path):
    """Si no filtrara, la tarjeta contradiría al resto de la página con el mismo rango puesto."""
    log = tmp_path / "telemetry.jsonl"
    ahora = datetime.now(UTC)
    _escribir(
        log,
        [
            _evento(ahora - timedelta(days=40), sugerida=True),
            _evento(ahora, sugerida=True),
        ],
    )
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)

    desde = (ahora - timedelta(days=2)).date().isoformat()
    datos = TestClient(metrics.app).get(f"/api/hooks?from={desde}").json()

    assert datos["total"] == 1, "el evento de hace 40 días no debería entrar en el rango"


def test_una_linea_corrupta_no_tumba_el_endpoint(monkeypatch, tmp_path):
    """El log lo escriben procesos que pueden morir a media línea."""
    log = tmp_path / "telemetry.jsonl"
    bueno = json.dumps(_evento(datetime.now(UTC), sugerida=True))
    log.write_text(f"{bueno}\n{{esto no es json\n{bueno}\n", encoding="utf-8")
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)

    datos = TestClient(metrics.app).get("/api/hooks").json()
    assert datos["total"] == 2


def test_el_endpoint_no_devuelve_ni_comandos_ni_prompts(monkeypatch, tmp_path):
    """La telemetría promete no registrar contenido, y el dashboard no puede romper esa promesa.

    Aunque el hook solo escribe tamaños, exponer el evento crudo dejaría la puerta abierta a que
    un campo nuevo del hook acabe publicado sin que nadie lo decida.
    """
    log = tmp_path / "telemetry.jsonl"
    fila = _evento(datetime.now(UTC), sugerida=True)
    fila["command"] = "rm -rf /algo/secreto"
    _escribir(log, [fila])
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)

    crudo = TestClient(metrics.app).get("/api/hooks").text
    assert "secreto" not in crudo
    assert "rm -rf" not in crudo


# --- El JS de la tarjeta, ejecutado de verdad ---------------------------------


def _extraer_funcion_js(fuente: str, cabecera: str) -> str:
    """Recorta una función del `<script>` balanceando llaves. Igual que en `test_metrics.py`."""
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


def test_la_categoria_del_log_se_escapa_antes_de_pintarla(tmp_path):
    """Se **ejecuta** con node, no se busca por grep: lo que importa es qué produce, no qué dice.

    La categoría es el único texto de esta página que no controla el daemon — sale de un fichero
    que escriben los hooks. El resto del panel interpola directo porque sus datos son propios;
    aquí no lo son.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    esc_js = _extraer_funcion_js(metrics.HTML, "function escHooks(s){")
    casos = ["bash", "<img src=x onerror=alert(1)>", None, "a&b", '"comillas"', "it's"]
    entrada = tmp_path / "casos.json"
    entrada.write_text(json.dumps(casos), encoding="utf-8")

    programa = tmp_path / "esc.mjs"
    programa.write_text(
        "import {readFileSync} from 'node:fs';\n"
        f"{esc_js}\n"
        f"const casos = JSON.parse(readFileSync({json.dumps(str(entrada))}, 'utf-8'));\n"
        "console.log(JSON.stringify(casos.map(escHooks)));\n",
        encoding="utf-8",
    )
    salida = subprocess.run(
        [node, str(programa)], capture_output=True, text=True, timeout=30, check=True
    )
    resultado = json.loads(salida.stdout)

    assert resultado[0] == "bash", "el caso normal no se toca"
    assert resultado[1] == "&lt;img src=x onerror=alert(1)&gt;"
    assert resultado[2] == "", "null se pinta vacío, no como la cadena 'null'"
    assert resultado[3] == "a&amp;b"
    assert resultado[4] == "&quot;comillas&quot;"
    assert resultado[5] == "it&#39;s"

    for pintado in resultado:
        assert "<" not in pintado and ">" not in pintado


def test_la_tarjeta_se_esconde_cuando_no_hay_telemetria(tmp_path):
    """Enseñar ceros diría «los hooks no sugieren nada» leyendo un fichero que no existe.

    Se ejercita la función real con node y tres entradas: sin telemetría, activada pero vacía, y
    con datos. Comprobarlo por grep sobre el HTML no distinguiría los tres casos.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    render_js = _extraer_funcion_js(metrics.HTML, "function renderHooks(h){")
    esc_js = _extraer_funcion_js(metrics.HTML, "function escHooks(s){")

    programa = tmp_path / "render.mjs"
    programa.write_text(
        # DOM mínimo: cada `getElementById` devuelve un objeto que apunta lo que le escriben.
        "const nodos = {};\n"
        "const elem = () => ({style:{display:'?'}, textContent:'', innerHTML:''});\n"
        "globalThis.document = {getElementById: id => (nodos[id] ??= elem())};\n"
        "globalThis.F = new Intl.NumberFormat('es');\n"
        f"{esc_js}\n"
        f"{render_js}\n"
        "const salida = [];\n"
        "for (const caso of [null, {enabled:false}, {enabled:true, total:0},\n"
        "  {enabled:true, total:10, suggested:3, rate:0.3,\n"
        "   by_category:[{category:'bash', total:8, suggested:2},\n"
        "                {category:'<img src=x onerror=alert(1)>', total:2, suggested:1}]}]) {\n"
        "  for (const k in nodos) delete nodos[k];\n"
        "  renderHooks(caso);\n"
        "  salida.push({display: nodos.hooksCard.style.display,\n"
        "               head: nodos.hooksHead ? nodos.hooksHead.textContent : '',\n"
        "               body: nodos.hooksBody ? nodos.hooksBody.innerHTML : ''});\n"
        "}\n"
        "console.log(JSON.stringify(salida));\n",
        encoding="utf-8",
    )
    salida = subprocess.run(
        [node, str(programa)], capture_output=True, text=True, timeout=30, check=True
    )
    sin_datos, apagada, vacia, con_datos = json.loads(salida.stdout)

    assert sin_datos["display"] == "none", "sin respuesta del endpoint, la tarjeta no se enseña"
    assert apagada["display"] == "none", "telemetría desactivada: no se enseñan ceros"
    assert vacia["display"] == "none", "activada pero sin eventos: tampoco se enseñan ceros"

    assert con_datos["display"] == "", "con datos, la tarjeta se enseña"
    assert "3 de 10" in con_datos["head"]
    assert "30,0 %" in con_datos["head"], "el porcentaje va con coma decimal, como el resto"
    assert "bash" in con_datos["body"]
    assert "25,0 %" in con_datos["body"], "la tasa por categoría es 2 de 8"
    # Lo que la tarjeta NO puede dejar de decir: que esto cuenta sugerencias, no delegaciones.
    assert "sugieren" in con_datos["body"]

    # Y que el escapado se USE, no solo que exista. Probar `escHooks` por su cuenta deja pasar
    # el mutante que quita la llamada — ya ocurrió, y por eso el caso malicioso entra aquí, en
    # el HTML que produce la función de verdad.
    assert "<img src=x" not in con_datos["body"], "la categoría se pintó sin escapar"
    assert "&lt;img src=x onerror=alert(1)&gt;" in con_datos["body"]
