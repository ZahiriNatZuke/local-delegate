"""T1 de `coste-api-y-cuota`: tablas del paquete y cotejo puro (REQ-010 a REQ-013, REQ-030).

Las filas del cotejo son **literales**: números de líneas `cost-state` reales de esta PC, reducidos
a sus seis campos y al id de modelo, congelados aquí. No se calculan con la tabla: si se
calcularan, el cotejo se daría la razón a sí mismo. Se eligieron con un script de solo lectura del
scratchpad, y se comprobó con la regla de `insumos/scripts/cotejo.py` que cada una cae `fuera` con
la mutación que le toca antes de congelarla (ver `evidencias/T1.md`).
"""

from __future__ import annotations

import contextlib
import copy
import socket

from local_delegate import pricing
from local_delegate.pricing import check_rows, entry, load_prices, normalize_id, verdict

SPEC_IDS = [
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
ROW_OPUS_5 = {
    "model": "claude-opus-5",
    "inputTokens": 2,
    "cacheCreationInputTokens": 40445,
    "cacheReadInputTokens": 0,
    "outputTokens": 4,
    "webSearchRequests": 0,
    "costUSD": 0.40456000000000003,
}
# Opus 5.5 con mucha lectura de caché (y con `[1m]`, que tiene que normalizarse).
ROW_OPUS_55_READ = {
    "model": "claude-opus-5-5[1m]",
    "inputTokens": 8,
    "cacheCreationInputTokens": 28669,
    "cacheReadInputTokens": 144347,
    "outputTokens": 199,
    "webSearchRequests": 0,
    "costUSD": 0.2622334,
}
# Opus 5.5 con mucha salida.
ROW_OPUS_55_OUTPUT = {
    "model": "claude-opus-5-5",
    "inputTokens": 248,
    "cacheCreationInputTokens": 95543,
    "cacheReadInputTokens": 2302120,
    "outputTokens": 22289,
    "webSearchRequests": 0,
    "costUSD": 1.6715400000000002,
}
# Haiku con búsquedas web: solo cae dentro si se suman ($0,051 sin ellas, $0,091 con ellas).
ROW_HAIKU_WEB = {
    "model": "claude-haiku-4-5-20251001",
    "inputTokens": 42371,
    "cacheCreationInputTokens": 0,
    "cacheReadInputTokens": 0,
    "outputTokens": 1800,
    "webSearchRequests": 4,
    "costUSD": 0.09137100000000001,
}
# Menos de $0,05: no se juzga.
ROW_SMALL = {
    "model": "claude-haiku-4-5-20251001",
    "inputTokens": 36,
    "cacheCreationInputTokens": 8443,
    "cacheReadInputTokens": 21430,
    "outputTokens": 1536,
    "webSearchRequests": 0,
    "costUSD": 0.02041275,
}
ROWS = [ROW_OPUS_5, ROW_OPUS_55_READ, ROW_OPUS_55_OUTPUT, ROW_HAIKU_WEB, ROW_SMALL]


def _without_price(rows, results):
    return {normalize_id(f["model"]) for f, r in zip(rows, results) if r == "unpriced"}


def test_normalizes_date_and_1m():
    assert entry("claude-haiku-4-5-20251001") is not None
    assert entry("claude-opus-5-5[1m]") is not None
    assert normalize_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5"
    assert normalize_id("claude-opus-5-5[1m]") == "claude-opus-5-5"


def test_exact_lookup_in_the_pairs():
    assert entry("claude-opus-5")["cache_read"] == 0.50
    assert entry("claude-opus-5-5")["cache_read"] == 0.20
    assert entry("claude-fable-5")["cache_read"] == 1.0
    assert entry("claude-fable-5-1")["cache_read"] == 0.25


def test_an_id_without_entry_has_no_price():
    assert entry("claude-opus-9") is None
    assert pricing.family("claude-opus-9") is None


def test_the_table_covers_the_13_ids():
    table = load_prices()
    assert sorted(table["models"]) == sorted(SPEC_IDS)
    for field in ("source", "consulted", "web_search_per_1000"):
        assert field in table
    for mid, e in table["models"].items():
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


def test_the_density_table_says_which_models_it_was_measured_with():
    density = pricing.load_density()
    families = density["families"]
    assert density.get("measured_on")
    assert families["new"].get("measured_with") == [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5",
        "claude-fable-5-1",
    ]
    assert families["previous"].get("measured_with") == ["claude-haiku-4-5"]
    assert families["new"]["unnumbered"]["prose"] == 223
    assert families["previous"]["unnumbered"]["prose"] == 301
    # Cada modelo de `measured_with` es de esa familia en la tabla de precios.
    for name, f in families.items():
        for mid in f.get("measured_with", []):
            assert pricing.family(mid) == name, mid


def test_crosscheck_with_literal_rows():
    table = load_prices()

    # Guarda: con la tabla sin mutar todas caen dentro salvo la de menos de $0,05.
    r = check_rows(ROWS, table)
    assert r == ["inside", "inside", "inside", "inside", None]
    assert verdict(r) == "pass"

    # Mutante de datos 1: falta `claude-opus-5`.
    without_opus5 = copy.deepcopy(table)
    del without_opus5["models"]["claude-opus-5"]
    r = check_rows(ROWS, without_opus5)
    assert verdict(r) == "fail"
    assert "claude-opus-5" in _without_price(ROWS, r)

    # Mutante de datos 2: lectura de Opus 5.5 ×0,8.
    read = copy.deepcopy(table)
    read["models"]["claude-opus-5-5"]["cache_read"] *= 0.8
    r = check_rows(ROWS, read)
    assert verdict(r) == "fail"

    # Mutante de datos 3: salida de Opus 5.5 ×0,8.
    output = copy.deepcopy(table)
    output["models"]["claude-opus-5-5"]["output"] *= 0.8
    r = check_rows(ROWS, output)
    assert verdict(r) == "fail"


def test_the_crosscheck_counts_web_search():
    r = check_rows([ROW_HAIKU_WEB], load_prices())
    assert verdict(r) == "pass"
    assert r == ["inside"]


def test_loading_the_tables_opens_no_sockets(monkeypatch):
    attempts: list[str] = []

    def record(name):
        def fake(*args, **kwargs):
            attempts.append(name)
            raise OSError(f"red prohibida en el test: {name}")

        return fake

    monkeypatch.setattr(socket, "getaddrinfo", record("getaddrinfo"))
    monkeypatch.setattr(socket, "create_connection", record("create_connection"))
    monkeypatch.setattr(socket.socket, "connect", record("connect"))
    # Sin caché, para que la carga se ejecute de verdad dentro del test.
    pricing.load_prices.cache_clear()
    pricing.load_density.cache_clear()
    try:
        # Se ignora a propósito: este test solo comprueba que la carga no intente salir a
        # la red; si la lectura falla por otra causa, lo que importa es el assert de abajo.
        with contextlib.suppress(OSError):
            pricing.load_prices()
            pricing.load_density()
        assert attempts == []
    finally:
        pricing.load_prices.cache_clear()
        pricing.load_density.cache_clear()


def test_a_trial_mark_in_the_table_changes_nothing(monkeypatch):
    """La tabla de un PR de ensayo del vigilante trae `_dry_run` (y siempre `_note`): no son datos.

    Se carga por el camino real (`load_prices`) una copia con marcas `_` añadidas y todo lo que
    lee la tabla tiene que dar lo mismo que con la limpia.
    """
    clean = copy.deepcopy(load_prices())
    read = pricing._read_table

    def with_marks(name):
        table = read(name)
        if name != "prices.json":
            return table
        return {"_dry_run": "PR de prueba del vigilante (run 1): no mezclar", **table, "_otra": 0}

    monkeypatch.setattr(pricing, "_read_table", with_marks)
    pricing.load_prices.cache_clear()
    try:
        marked = load_prices()
        assert "_dry_run" in marked, "guarda: la carga pasó por la tabla con marcas"
        assert {k: x for k, x in marked.items() if not k.startswith("_")} == {
            k: x for k, x in clean.items() if not k.startswith("_")
        }
        for mid in SPEC_IDS:
            assert entry(mid) == clean["models"][mid], mid
            assert pricing.family(mid) == clean["models"][mid]["family"], mid
        assert check_rows(ROWS, marked) == check_rows(ROWS, clean)
    finally:
        pricing.load_prices.cache_clear()
