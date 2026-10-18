"""Coste equivalente a precio de API y bloque de imágenes (coste-api-y-cuota, REQ-038 y REQ-040 a
REQ-048).

Una pregunta: cuánto habría costado, a precio de lista de la API, que Claude leyera lo que leyó el
MCP server-side. **No es dinero ahorrado** (la suscripción es de tarifa plana) y el panel lo dice.

- `price(m, hilo)`: escritura de caché del hilo (5 min en un subagente, 1 h en el principal) y
  lectura de caché, o `None` si el modelo no está en la tabla (REQ-016: nunca 0).
- `n_of(fila, agregados)`: `N` y caducidades en el orden único de REQ-042 (relleno, mediana del
  grupo con al menos 10 casos, declarado del hilo).
- `event_cost(fila, agregados)`: `T`, cota baja y estimación de un evento (REQ-041).
- `cost_block(filas, agregados)`: la cifra del periodo con todo lo que la acompaña (REQ-007,
  REQ-008, REQ-016, REQ-044, REQ-046, REQ-047); `images_block(filas)`: REQ-038.

Las filas llegan **fundidas** (`cost.merge`, REQ-006). Solo stdlib; no abre sockets ni lee
`~/.claude`: los agregados los trae quien llama (`recompute.read_aggregates`), ya en el formato
nuevo. Las claves de salida son las de `/api/stats` `cost` e `images` (REQ-009).
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime

from . import attribution, cost, i18n, legacy_names, pricing, server

#: `N` declarado por hilo (REQ-042 (3)), medido con `atribucion_n.py`: principal 127 (14 casos),
#: subagente 40 (135 casos).
DECLARED_N = {"main": 127, "subagent": 40}
#: Casos mínimos de un grupo para usar su mediana (REQ-042 (2)).
MIN_GROUP_CASES = 10
#: Plazo de borrado de los transcripts sin `cost-aggregates.json` (Definiciones, `H`).
DEFAULT_CLEANUP_DAYS = attribution.DEFAULT_CLEANUP_DAYS

N_ORIGINS = ("backfill", "aggregate", "declared")
DENSITY_ORIGINS = ("measured", "unnumbered", "conservative")

#: Por qué no hay cifra: claves del catálogo (`panel.json`), redactadas en el idioma que se pida.
NO_DELEGATIONS = "panel.cost.reason.no_delegations"
NO_TABLE = "panel.cost.reason.no_table"
ALL_UNPRICED = "panel.cost.reason.all_unpriced"
COMMAND = "local-delegate recompute-cost"
FALLBACK_VARIABLE = "LOCAL_DELEGATE_COST_FALLBACK"


def model_name(mid: str) -> str:
    """`claude-opus-5-5` → `Opus 5.5`; `claude-haiku-4-5` → `Haiku 4.5`. Solo para rótulos."""
    parts = pricing.normalize_id(str(mid)).removeprefix("claude-").split("-")
    if not parts or not parts[0]:
        return str(mid)
    return " ".join([parts[0].capitalize(), ".".join(parts[1:])]).strip()


def _thread(row: dict) -> str:
    thread = row.get("caller_kind")
    return thread if thread in cost.THREADS else cost.fallback()["thread"]


def price(m: str, thread: str, table: dict | None = None) -> dict | None:
    """`{"w": P_w(m, hilo), "r": P_r(m)}` en USD/MTok, o `None` si `m` no tiene precio."""
    entry = pricing.entry(str(m or ""), table)
    if entry is None:
        return None
    return {"w": entry["w5m"] if thread == "subagent" else entry["w1h"], "r": entry["cache_read"]}


def _int_or_none(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _group_n(aggregates: dict | None, group: str) -> list[int]:
    n_by_month = (
        legacy_names.read_key(aggregates, "n_by_month", "n_por_mes")
        if isinstance(aggregates, dict)
        else None
    )
    if not isinstance(n_by_month, dict):
        return []
    values: list[int] = []
    for groups in n_by_month.values():
        if isinstance(groups, dict) and isinstance(groups.get(group), list):
            values.extend(v for v in groups[group] if _int_or_none(v) is not None)
    return values


def n_of(row: dict, aggregates: dict | None) -> tuple[float, int, str]:
    """`(N, caducidades, origen)` de un evento, en el orden único de REQ-042:

    (1) `n` y `expiries` del relleno; (2) la mediana de `N` del grupo (`modelo|hilo`) en los
    agregados guardados, si tiene al menos 10 casos, con 0 caducidades; (3) el declarado del hilo.
    """
    n = _int_or_none(row.get("n"))
    if n is not None:
        return n, _int_or_none(row.get("expiries")) or 0, "backfill"
    values = _group_n(aggregates, f"{row.get('caller_model')}|{_thread(row)}")
    if len(values) >= MIN_GROUP_CASES:
        return statistics.median(values), 0, "aggregate"
    return DECLARED_N[_thread(row)], 0, "declared"


def net_tokens(row: dict) -> int:
    """`T`: tokens de Claude del texto leído server-side menos los devueltos (Definiciones). 0 en
    una imagen (REQ-038). Pasa SOLO por `server.claude_tokens`."""
    if cost.is_image(row):
        return 0
    acc = server._accounting(row)
    return server.claude_tokens(
        acc["chars_saved_text"], kind="text", event=row
    ) - server.claude_tokens(acc["chars_returned"], kind="returned", event=row)


def event_cost(row: dict, aggregates: dict | None = None, table: dict | None = None) -> dict:
    """`T`, cota baja y estimación de UN evento (REQ-041), con `N` y su origen.

    cota baja = T × P_w(m, hilo); estimación = T × (P_w × (1 + cad) + (N − cad) × P_r). Un `T`
    negativo resta. Sin precio: `low_bound` y `estimate` son `None` (nunca 0).
    """
    thread = _thread(row)
    model = str(row.get("caller_model") or "")
    t = net_tokens(row)
    n, expiries, origin = n_of(row, aggregates)
    p = price(model, thread, table)
    out = {
        "model": model,
        "thread": thread,
        "effort": row.get("caller_effort") or "no_data",
        "T": t,
        "N": n,
        "expiries": expiries,
        "n_origin": origin,
        "low_bound": None,
        "estimate": None,
    }
    if p is not None:
        out["low_bound"] = t * p["w"] / 1e6
        out["estimate"] = t * (p["w"] * (1 + expiries) + (n - expiries) * p["r"]) / 1e6
    return out


def _in_base(row: dict, acc: dict) -> bool:
    """REQ-040: atribuible (sin fallo), de texto, con algo leído o devuelto."""
    if acc["failed"] or cost.is_image(row):
        return False
    return acc["chars_saved_text"] > 0 or acc["chars_returned"] > 0


def _money(x: float) -> float:
    """A céntimos. Sumar 0.0 convierte el `-0.0` de un negativo diminuto en `0.0`: la API no
    devuelve un cero con signo (la fórmula no cambia; un negativo de verdad sigue negativo)."""
    return round(x, 2) + 0.0


def cost_block(
    rows: Iterable[dict],
    aggregates: dict | None,
    *,
    now: datetime | None = None,
    language: str | None = None,
) -> dict:
    """La cifra del periodo con sus supuestos a la vista. Sin cifra, el motivo (REQ-046), redactado
    en `language` (el del visitante del panel, D6) o, sin él, en el idioma del proceso."""
    now = now or datetime.now(UTC)
    cleanup_days = DEFAULT_CLEANUP_DAYS
    if isinstance(aggregates, dict):
        cleanup_days = (
            _int_or_none(legacy_names.read_key(aggregates, "cleanup_days", "plazo_dias"))
            or DEFAULT_CLEANUP_DAYS
        )
    try:
        table = pricing.load_prices()
        r = cost.fallback()
    except Exception:
        # Sin tabla no hay cifra (REQ-046), pero la barra y el motivo se enseñan igual.
        table, r = None, dict(cost.DECLARED_FALLBACK, fallback_invalid=False)

    bar: Counter = Counter({t: 0 for t in cost.SEGMENTS})
    excluded_by_reason: Counter = Counter()
    n_origin: Counter = Counter({o: 0 for o in N_ORIGINS})
    density_origin: Counter = Counter({o: 0 for o in DENSITY_ORIGINS})
    families: Counter = Counter()
    marks: Counter = Counter()
    outside = {"images": 0, "output_to_file": 0}
    unpriced: Counter = Counter()
    breakdown: dict[tuple, dict] = {}
    fallback_invalid = bool(r.get("fallback_invalid"))
    low_bound = estimate = 0.0
    t_total = valued = in_base = 0

    for row in rows:
        acc = server._accounting(row)
        if acc["failed"]:
            continue
        if cost.is_image(row):
            outside["images"] += 1
            continue
        if acc["chars_saved_output"] > 0:
            outside["output_to_file"] += 1
        if not _in_base(row, acc):
            continue
        segment = cost.segment(row, now=now, cleanup_days=cleanup_days)
        bar[segment] += 1
        if segment == "excluded":
            excluded_by_reason[attribution.exclusion_reason(row, {"bench": row.get("bench")})] += 1
            continue
        in_base += 1
        if row.get("fallback_invalid"):
            fallback_invalid = True
        text = (row.get("density") or {}).get("text")
        if text:
            density_origin[text[1]] += 1
        families[str(row.get("family"))] += 1
        marks.update(row.get("marks") or [])
        if table is None:
            continue
        c = event_cost(row, aggregates, table)
        n_origin[c["n_origin"]] += 1
        if c["low_bound"] is None:
            unpriced[pricing.normalize_id(c["model"])] += 1
            continue
        valued += 1
        t_total += c["T"]
        low_bound += c["low_bound"]
        estimate += c["estimate"]
        key = (c["model"], c["thread"], c["effort"])
        g = breakdown.setdefault(
            key,
            {
                "model": c["model"],
                "name": model_name(c["model"]),
                "thread": c["thread"],
                "effort": c["effort"],
                "cases": 0,
                "T": 0,
                "low_bound": 0.0,
                "estimate": 0.0,
            },
        )
        g["cases"] += 1
        g["T"] += c["T"]
        g["low_bound"] += c["low_bound"]
        g["estimate"] += c["estimate"]

    if table is None:
        reason = NO_TABLE
    elif in_base == 0:
        reason = NO_DELEGATIONS
    elif valued == 0:
        reason = ALL_UNPRICED
    else:
        reason = None

    with_assumed_model = bar["pending"] + bar["assumed"]
    return {
        "figure": None
        if reason
        else {"low_bound": _money(low_bound), "estimate": _money(estimate)},
        "reason": i18n.t_lang(language or i18n.lang(), reason) if reason else None,
        "events": valued,
        "T": t_total,
        "bar": {
            **{t: bar[t] for t in cost.SEGMENTS},
            "valued": in_base,
            "with_assumed_model": with_assumed_model,
            "excluded_by_reason": dict(sorted(excluded_by_reason.items())),
            "cleanup_days": cleanup_days,
        },
        "fallback": {
            "model": r["model"],
            "name": model_name(r["model"]),
            "thread": r["thread"],
            "invalid": fallback_invalid,
            "variable": FALLBACK_VARIABLE,
        },
        "n_origin": {o: n_origin[o] for o in N_ORIGINS},
        "n_declared": dict(DECLARED_N),
        "density": {
            "origin": {o: density_origin[o] for o in DENSITY_ORIGINS},
            "families": dict(sorted(families.items())),
            "assumed_family": marks[cost.MARK_ASSUMED_FAMILY],
            "family_density": marks[cost.MARK_FAMILY_DENSITY],
        },
        "unpriced": {"n": sum(unpriced.values()), "ids": sorted(unpriced)},
        "outside_base": outside,
        "breakdown": [
            {**g, "low_bound": _money(g["low_bound"]), "estimate": _money(g["estimate"])}
            for g in sorted(breakdown.values(), key=lambda g: -g["estimate"])
        ],
        "table": {
            "consulted": (table or {}).get("consulted"),
            "source": (table or {}).get("source"),
        },
        "command": COMMAND,
    }


def images_block(rows: Iterable[dict]) -> dict:
    """REQ-038: número de imágenes, bytes leídos server-side y caracteres devueltos a Claude, sin
    ninguna cifra de tokens de Claude. Los fallos no cuentan."""
    n = bytes_ = returned = 0
    for row in rows:
        if not cost.is_image(row):
            continue
        acc = server._accounting(row)
        if acc["failed"]:
            continue
        n += 1
        bytes_ += acc["bytes_saved_image"]
        returned += acc["chars_returned"]
    return {"n": n, "bytes": bytes_, "chars_returned": returned}
