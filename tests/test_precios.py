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

from local_delegate import precios
from local_delegate.precios import cargar_precios, cotejar, entrada, normalizar_id, veredicto

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
    "modelo": "claude-opus-5",
    "inputTokens": 2,
    "cacheCreationInputTokens": 40445,
    "cacheReadInputTokens": 0,
    "outputTokens": 4,
    "webSearchRequests": 0,
    "costUSD": 0.40456000000000003,
}
# Opus 5.5 con mucha lectura de caché (y con `[1m]`, que tiene que normalizarse).
FILA_OPUS_55_LECTURA = {
    "modelo": "claude-opus-5-5[1m]",
    "inputTokens": 8,
    "cacheCreationInputTokens": 28669,
    "cacheReadInputTokens": 144347,
    "outputTokens": 199,
    "webSearchRequests": 0,
    "costUSD": 0.2622334,
}
# Opus 5.5 con mucha salida.
FILA_OPUS_55_SALIDA = {
    "modelo": "claude-opus-5-5",
    "inputTokens": 248,
    "cacheCreationInputTokens": 95543,
    "cacheReadInputTokens": 2302120,
    "outputTokens": 22289,
    "webSearchRequests": 0,
    "costUSD": 1.6715400000000002,
}
# Haiku con búsquedas web: solo cae dentro si se suman ($0,051 sin ellas, $0,091 con ellas).
FILA_HAIKU_WEB = {
    "modelo": "claude-haiku-4-5-20251001",
    "inputTokens": 42371,
    "cacheCreationInputTokens": 0,
    "cacheReadInputTokens": 0,
    "outputTokens": 1800,
    "webSearchRequests": 4,
    "costUSD": 0.09137100000000001,
}
# Menos de $0,05: no se juzga.
FILA_PEQUENA = {
    "modelo": "claude-haiku-4-5-20251001",
    "inputTokens": 36,
    "cacheCreationInputTokens": 8443,
    "cacheReadInputTokens": 21430,
    "outputTokens": 1536,
    "webSearchRequests": 0,
    "costUSD": 0.02041275,
}
FILAS = [FILA_OPUS_5, FILA_OPUS_55_LECTURA, FILA_OPUS_55_SALIDA, FILA_HAIKU_WEB, FILA_PEQUENA]


def _sin_precio(filas, resultados):
    return {normalizar_id(f["modelo"]) for f, r in zip(filas, resultados) if r == "sin_precio"}


def test_normaliza_fecha_y_1m():
    assert entrada("claude-haiku-4-5-20251001") is not None
    assert entrada("claude-opus-5-5[1m]") is not None
    assert normalizar_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5"
    assert normalizar_id("claude-opus-5-5[1m]") == "claude-opus-5-5"


def test_busqueda_exacta_en_los_pares():
    assert entrada("claude-opus-5")["lectura"] == 0.50
    assert entrada("claude-opus-5-5")["lectura"] == 0.20
    assert entrada("claude-fable-5")["lectura"] == 1.0
    assert entrada("claude-fable-5-1")["lectura"] == 0.25


def test_un_id_sin_entrada_no_tiene_precio():
    assert entrada("claude-opus-9") is None
    assert precios.familia("claude-opus-9") is None


def test_la_tabla_cubre_los_13_ids():
    tabla = cargar_precios()
    assert sorted(tabla["modelos"]) == sorted(IDS_DE_LA_SPEC)
    for campo in ("fuente", "consultado", "busqueda_web_por_1000"):
        assert campo in tabla
    for mid, e in tabla["modelos"].items():
        assert set(e) == {
            "entrada",
            "w5m",
            "w1h",
            "lectura",
            "salida",
            "familia",
            "admite_esfuerzo",
        }, mid
        assert e["familia"] in ("nueva", "anterior"), mid


def test_la_tabla_de_densidad_dice_con_que_modelos_se_midio():
    densidad = precios.cargar_densidad()
    familias = densidad["familias"]
    assert densidad.get("medido")
    assert familias["nueva"].get("medido_con") == [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5",
        "claude-fable-5-1",
    ]
    assert familias["anterior"].get("medido_con") == ["claude-haiku-4-5"]
    assert familias["nueva"]["sin_numerar"]["prosa"] == 223
    assert familias["anterior"]["sin_numerar"]["prosa"] == 301
    # Cada modelo de `medido_con` es de esa familia en la tabla de precios.
    for nombre, f in familias.items():
        for mid in f.get("medido_con", []):
            assert precios.familia(mid) == nombre, mid


def test_cotejo_con_filas_literales():
    tabla = cargar_precios()

    # Guarda: con la tabla sin mutar todas caen dentro salvo la de menos de $0,05.
    r = cotejar(FILAS, tabla)
    assert r == ["dentro", "dentro", "dentro", "dentro", None]
    assert veredicto(r) == "pasa"

    # Mutante de datos 1: falta `claude-opus-5`.
    sin_opus5 = copy.deepcopy(tabla)
    del sin_opus5["modelos"]["claude-opus-5"]
    r = cotejar(FILAS, sin_opus5)
    assert veredicto(r) == "falla"
    assert "claude-opus-5" in _sin_precio(FILAS, r)

    # Mutante de datos 2: lectura de Opus 5.5 ×0,8.
    lectura = copy.deepcopy(tabla)
    lectura["modelos"]["claude-opus-5-5"]["lectura"] *= 0.8
    r = cotejar(FILAS, lectura)
    assert veredicto(r) == "falla"

    # Mutante de datos 3: salida de Opus 5.5 ×0,8.
    salida = copy.deepcopy(tabla)
    salida["modelos"]["claude-opus-5-5"]["salida"] *= 0.8
    r = cotejar(FILAS, salida)
    assert veredicto(r) == "falla"


def test_el_cotejo_cuenta_la_busqueda_web():
    r = cotejar([FILA_HAIKU_WEB], cargar_precios())
    assert veredicto(r) == "pasa"
    assert r == ["dentro"]


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
    precios.cargar_precios.cache_clear()
    precios.cargar_densidad.cache_clear()
    try:
        try:
            precios.cargar_precios()
            precios.cargar_densidad()
        except OSError:
            # Se ignora a propósito: este test solo comprueba que la carga no intente salir a
            # la red; si la lectura falla por otra causa, lo que importa es el assert de abajo.
            pass
        assert intentos == []
    finally:
        precios.cargar_precios.cache_clear()
        precios.cargar_densidad.cache_clear()
