"""T1 de `coste-api-y-cuota`: tablas del paquete y cotejo puro (REQ-010 a REQ-013, REQ-030).

Las filas del cotejo son **literales**: números de líneas `cost-state` reales de esta PC, reducidos
a sus seis campos y al id de modelo, congelados aquí. No se calculan con la tabla: si se
calcularan, el cotejo se daría la razón a sí mismo. Se eligieron con un script de solo lectura del
scratchpad, y se comprobó con la regla de `insumos/scripts/cotejo.py` que cada una cae `fuera` con
la mutación que le toca antes de congelarla (ver `evidencias/T1.md`).
"""

from __future__ import annotations

import copy
import socket

from local_delegate import pricing
from local_delegate.pricing import check_rows, entry, load_prices, normalize_id, verdict

IDS_DE_LA_SPEC = [
    "claude-fable-5-1",
    "claude-fable-5",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-5-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]

# Filas literales de `cost-state` (solo números e id de modelo).
FILA_OPUS_5 = {
    "model": "claude-opus-5",
    "inputTokens": 2,
    "cacheCreationInputTokens": 40445,
    "cacheReadInputTokens": 0,
    "outputTokens": 4,
    "webSearchRequests": 0,
    "costUSD": 0.40456000000000003,
}
# Opus 5.5 con mucha lectura de caché (y con `[1m]`, que tiene que normalizarse).
FILA_OPUS_55_LECTURA = {
    "model": "claude-opus-5-5[1m]",
    "inputTokens": 8,
    "cacheCreationInputTokens": 28669,
    "cacheReadInputTokens": 144347,
    "outputTokens": 199,
    "webSearchRequests": 0,
    "costUSD": 0.2622334,
}
# Opus 5.5 con mucha salida.
FILA_OPUS_55_SALIDA = {
    "model": "claude-opus-5-5",
    "inputTokens": 248,
    "cacheCreationInputTokens": 95543,
    "cacheReadInputTokens": 2302120,
    "outputTokens": 22289,
    "webSearchRequests": 0,
    "costUSD": 1.6715400000000002,
}
# Haiku con búsquedas web: solo cae dentro si se suman ($0,051 sin ellas, $0,091 con ellas).
FILA_HAIKU_WEB = {
    "model": "claude-haiku-4-5-20251001",
    "inputTokens": 42371,
    "cacheCreationInputTokens": 0,
    "cacheReadInputTokens": 0,
    "outputTokens": 1800,
    "webSearchRequests": 4,
    "costUSD": 0.09137100000000001,
}
# Menos de $0,05: no se juzga.
FILA_PEQUENA = {
    "model": "claude-haiku-4-5-20251001",
    "inputTokens": 36,
    "cacheCreationInputTokens": 8443,
    "cacheReadInputTokens": 21430,
    "outputTokens": 1536,
    "webSearchRequests": 0,
    "costUSD": 0.02041275,
}
FILAS = [FILA_OPUS_5, FILA_OPUS_55_LECTURA, FILA_OPUS_55_SALIDA, FILA_HAIKU_WEB, FILA_PEQUENA]


def _sin_precio(filas, resultados):
    return {normalize_id(f["model"]) for f, r in zip(filas, resultados) if r == "unpriced"}


def test_normaliza_fecha_y_1m():
    assert entry("claude-haiku-4-5-20251001") is not None
    assert entry("claude-opus-5-5[1m]") is not None
    assert normalize_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5"
    assert normalize_id("claude-opus-5-5[1m]") == "claude-opus-5-5"


def test_busqueda_exacta_en_los_pares():
    assert entry("claude-opus-5")["cache_read"] == 0.50
    assert entry("claude-opus-5-5")["cache_read"] == 0.20
    assert entry("claude-fable-5")["cache_read"] == 1.0
    assert entry("claude-fable-5-1")["cache_read"] == 0.25


def test_un_id_sin_entrada_no_tiene_precio():
    assert entry("claude-opus-9") is None
    assert pricing.family("claude-opus-9") is None


def test_la_tabla_cubre_los_13_ids():
    tabla = load_prices()
    assert sorted(tabla["models"]) == sorted(IDS_DE_LA_SPEC)
    for campo in ("source", "consulted", "web_search_per_1000"):
        assert campo in tabla
    for mid, e in tabla["models"].items():
        assert set(e) == {
            "input",
            "w5m",
            "w1h",
            "cache_read",
            "output",
            "family",
            "supports_effort",
        }, mid
        assert e["family"] in ("new", "previous"), mid


def test_la_tabla_de_densidad_dice_con_que_modelos_se_midio():
    densidad = pricing.load_density()
    familias = densidad["families"]
    assert densidad.get("measured_on")
    assert familias["new"].get("measured_with") == [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5",
        "claude-fable-5-1",
    ]
    assert familias["previous"].get("measured_with") == ["claude-haiku-4-5"]
    assert familias["new"]["unnumbered"]["prose"] == 223
    assert familias["previous"]["unnumbered"]["prose"] == 301
    # Cada modelo de `measured_with` es de esa familia en la tabla de precios.
    for nombre, f in familias.items():
        for mid in f.get("measured_with", []):
            assert pricing.family(mid) == nombre, mid


def test_cotejo_con_filas_literales():
    tabla = load_prices()

    # Guarda: con la tabla sin mutar todas caen dentro salvo la de menos de $0,05.
    r = check_rows(FILAS, tabla)
    assert r == ["inside", "inside", "inside", "inside", None]
    assert verdict(r) == "pass"

    # Mutante de datos 1: falta `claude-opus-5`.
    sin_opus5 = copy.deepcopy(tabla)
    del sin_opus5["models"]["claude-opus-5"]
    r = check_rows(FILAS, sin_opus5)
    assert verdict(r) == "fail"
    assert "claude-opus-5" in _sin_precio(FILAS, r)

    # Mutante de datos 2: lectura de Opus 5.5 ×0,8.
    lectura = copy.deepcopy(tabla)
    lectura["models"]["claude-opus-5-5"]["cache_read"] *= 0.8
    r = check_rows(FILAS, lectura)
    assert verdict(r) == "fail"

    # Mutante de datos 3: salida de Opus 5.5 ×0,8.
    salida = copy.deepcopy(tabla)
    salida["models"]["claude-opus-5-5"]["output"] *= 0.8
    r = check_rows(FILAS, salida)
    assert verdict(r) == "fail"


def test_el_cotejo_cuenta_la_busqueda_web():
    r = check_rows([FILA_HAIKU_WEB], load_prices())
    assert verdict(r) == "pass"
    assert r == ["inside"]


def test_cargar_las_tablas_no_abre_sockets(monkeypatch):
    intentos: list[str] = []

    def registrar(nombre):
        def falso(*args, **kwargs):
            intentos.append(nombre)
            raise OSError(f"red prohibida en el test: {nombre}")

        return falso

    monkeypatch.setattr(socket, "getaddrinfo", registrar("getaddrinfo"))
    monkeypatch.setattr(socket, "create_connection", registrar("create_connection"))
    monkeypatch.setattr(socket.socket, "connect", registrar("connect"))
    # Sin caché, para que la carga se ejecute de verdad dentro del test.
    pricing.load_prices.cache_clear()
    pricing.load_density.cache_clear()
    try:
        try:
            pricing.load_prices()
            pricing.load_density()
        except OSError:
            # Se ignora a propósito: este test solo comprueba que la carga no intente salir a
            # la red; si la lectura falla por otra causa, lo que importa es el assert de abajo.
            pass
        assert intentos == []
    finally:
        pricing.load_prices.cache_clear()
        pricing.load_density.cache_clear()


def test_una_marca_de_ensayo_en_la_tabla_no_cambia_nada(monkeypatch):
    """La tabla de un PR de ensayo del vigilante trae `_ensayo` (y siempre `_note`): no son datos.

    Se carga por el camino real (`load_prices`) una copia con marcas `_` añadidas y todo lo que
    lee la tabla tiene que dar lo mismo que con la limpia.
    """
    limpia = copy.deepcopy(load_prices())
    leer = pricing._read_table

    def con_marcas(nombre):
        tabla = leer(nombre)
        if nombre != "prices.json":
            return tabla
        return {"_ensayo": "PR de prueba del vigilante (run 1): no mezclar", **tabla, "_otra": 0}

    monkeypatch.setattr(pricing, "_read_table", con_marcas)
    pricing.load_prices.cache_clear()
    try:
        marcada = load_prices()
        assert "_ensayo" in marcada, "guarda: la carga pasó por la tabla con marcas"
        assert {k: x for k, x in marcada.items() if not k.startswith("_")} == {
            k: x for k, x in limpia.items() if not k.startswith("_")
        }
        for mid in IDS_DE_LA_SPEC:
            assert entry(mid) == limpia["models"][mid], mid
            assert pricing.family(mid) == limpia["models"][mid]["family"], mid
        assert check_rows(FILAS, marcada) == check_rows(FILAS, limpia)
    finally:
        pricing.load_prices.cache_clear()
