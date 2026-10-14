#!/usr/bin/env python3
"""Aplica el criterio de P-4: si los numeros del enfriamiento se cambian, se quedan o no se sabe.

El criterio esta escrito en `verification.md` («Criterio de P-4») antes de encender el mecanismo, y
este script es quien lo aplica. Si el recuento se hiciera a mano, el criterio volveria a ser una
opinion. Lee dos ficheros de `LOG_DIR`:

- el log de uso (`usage-*.jsonl`): saltos por clase, fallos que cuentan y fallos al momento;
- `cooldown-events.jsonl` y el viejo `enfriamiento-eventos.jsonl` (los dos, siempre): los
  episodios. El log de uso no los puede reconstruir, porque guarda un evento por operacion y no ve
  el fallo del segundo salto ni el de los trozos siguientes. Las filas del formato viejo (claves
  `modelo`, `evento`, `clase`…, valores `entra`, `reentra`, `limpia`) se traducen al nuevo antes de
  contar (REQ-007): el informe es el mismo con los dos formatos.

Las ventanas de prueba de `LOG_DIR/test-windows.json` se aplican solas a las filas del log y a los
episodios, ademas de los tramos de `--exclude`; `--include-tests` desactiva las del fichero (no las
de `--exclude`). Los tramos se comparan como instantes con la regla de las ventanas (intervalo
cerrado, al segundo), no como cadenas.

Uso:
    uv run python scripts/measure_cooldown.py --since 2026-09-16
    uv run python scripts/measure_cooldown.py --since 2026-09-16 \\
        --exclude 2026-09-16T10:00,2026-09-16T11:30     # el fallo provocado de la tarea 30
    uv run python scripts/measure_cooldown.py --since 2026-09-16 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from measure_adoption import logs_dir, read, usage_logs
from script_i18n import argparse_in_language

from local_delegate import i18n, legacy_names, test_windows
from local_delegate.cooldown import COUNTING_CLASSES, EVENTS_FILE, LEGACY_EVENTS_FILE

#: Por debajo de cualquiera de los dos, el resultado es «no concluyente» (criterio de P-4).
MIN_EPISODES = 5
MIN_FAILURES = 10

#: Cómo se dice cada resultado en «RESULTADO:», en el idioma vigente (el envoltorio
#: `medir_enfriamiento.py` de REQ-046 da la misma salida: llama a este `main`).
_RESULT_KEYS = {
    "inconclusive": "cli.script.measure_cooldown.result.inconclusive",
    "keep": "cli.script.measure_cooldown.result.keep",
    "change": "cli.script.measure_cooldown.result.change",
}

CLASSES = {error_class.value for error_class in COUNTING_CLASSES}

#: Las reglas en su orden de precedencia: se aplica solo la primera que se cumpla. Cada una es
#: (motivo, cambio), como claves del catálogo (`rule_text`).
RULES = {
    1: ("cli.script.measure_cooldown.rule.1.reason", "cli.script.measure_cooldown.rule.1.change"),
    2: ("cli.script.measure_cooldown.rule.2.reason", "cli.script.measure_cooldown.rule.2.change"),
    3: ("cli.script.measure_cooldown.rule.3.reason", "cli.script.measure_cooldown.rule.3.change"),
    4: ("cli.script.measure_cooldown.rule.4.reason", "cli.script.measure_cooldown.rule.4.change"),
}


def rule_text(number: int) -> tuple[str, str]:
    """(motivo, cambio) de una regla, en el idioma vigente."""
    reason, change = RULES[number]
    return i18n.t(reason), i18n.t(change)


def _ts(event: dict) -> str:
    return str(event.get("ts", ""))


def _in_range(ts: str, since: str | None, until: str | None) -> bool:
    if since and ts < since:
        return False
    return not (until and ts >= until)


def _by_hand(excluded: Iterable[tuple[str, str]]) -> test_windows.Windows:
    """Los tramos de `--exclude` como ventanas: la misma regla que las del fichero (REQ-002)."""
    windows = []
    for number, (start, end) in enumerate(excluded, start=1):
        windows.append(
            test_windows.Window(
                id=f"exclude-{number}",
                start=test_windows.parse_instant(start),
                end=test_windows.parse_instant(end),
            )
        )
    return test_windows.Windows(windows=windows)


class _Filter:
    """Quita lo de `--exclude` y, salvo `--include-tests`, lo de las ventanas del fichero, y cuenta
    cuanto quita cada fuente. Una fila que cae en las dos cuenta para `--exclude`."""

    def __init__(self, excluded: list, include_tests: bool) -> None:
        self.by_hand = _by_hand(excluded)
        self.file = test_windows.Windows() if include_tests else test_windows.load(logs_dir())
        self.removed = {"manual": Counter(), "test_windows": Counter()}
        self.per_window: Counter = Counter()

    def lets_through(self, ts: str, kind: str) -> bool:
        if self.by_hand.find(ts) is not None:
            self.removed["manual"][kind] += 1
            return False
        window = self.file.find(ts)
        if window is not None:
            self.removed["test_windows"][kind] += 1
            self.per_window[window] += 1
            return False
        return True


def episodes(events: list[dict], tmax_s: float) -> list[dict]:
    """Agrupa las transiciones en episodios: de un `enter` al `clear` del mismo modelo.

    Un `reenter` o un `clear` sin su `enter` es de un episodio empezado antes del registro: se
    ignora, porque no se sabe con que clase empezo. Las filas del formato viejo se traducen antes.
    """
    opened: dict[str, dict] = {}
    all_episodes: list[dict] = []
    new_ones = (legacy_names.normalize("cooldown_events", event) for event in events)
    for event in sorted(new_ones, key=_ts):
        model = str(event.get("model"))
        kind = event.get("event")
        at_tmax = float(event.get("wait_s") or 0) >= tmax_s
        if kind == "enter":
            episode = {
                "model": model,
                "since": _ts(event),
                "class": event.get("class"),
                "reentries": 0,
                "at_tmax": int(at_tmax),
                "final": None,
            }
            opened[model] = episode
            all_episodes.append(episode)
        elif kind == "reenter" and model in opened:
            opened[model]["reentries"] += 1
            opened[model]["at_tmax"] += int(at_tmax)
        elif kind == "clear" and model in opened:
            final = "recovered" if event.get("after_expiry") else "explicit_success"
            opened.pop(model)["final"] = final
    return all_episodes


def verdict(measurement: dict) -> dict:
    n = measurement["episodes"]
    if n < MIN_EPISODES or measurement["counting_failures"] < MIN_FAILURES:
        return {"result": "inconclusive", "rule": None, "noted": []}
    r = measurement["R"]
    meets = {
        1: r is not None and r > 0.6,
        2: measurement["episodes_by_timeout"] * 2 >= n,
        3: r is not None and r < 0.2 and measurement["diverted_operations"] >= 3 * n,
        4: measurement["episodes_reentering_at_tmax"] > 0,
    }
    met = [number for number in sorted(meets) if meets[number]]
    if not met:
        return {"result": "keep", "rule": None, "noted": []}
    return {"result": "change", "rule": met[0], "noted": met[1:]}


def measure(
    since: str | None,
    until: str | None = None,
    excluded: Iterable[tuple[str, str]] = (),
    tmax_s: float = 900.0,
    include_tests: bool = False,
) -> dict:
    excluded = list(excluded)
    window_filter = _Filter(excluded, include_tests)
    usages = [
        legacy_names.normalize("usage", event)
        for path in usage_logs()
        for event in read(path, None)
        if _in_range(_ts(event), since, until)
        and window_filter.lets_through(_ts(event), "usage_rows")
    ]
    # Un minimo, no el total: con salto, el log solo ve el fallo del pedido y el ultimo.
    failures = sum(1 for e in usages if e.get("error_class") in CLASSES) + sum(
        1 for e in usages if e.get("fallback_class") == "model"
    )
    jumps = Counter(e["fallback_class"] for e in usages if e.get("fallback_class"))
    at_moment = sum(1 for e in usages if e.get("error") == "cooldown")
    delegations = sum(1 for e in usages if str(e.get("tool", "")).startswith("local_"))

    # Los dos registros, siempre: el viejo dejo de crecer al actualizar, pero su historia cuenta.
    record = [
        event
        for name in (LEGACY_EVENTS_FILE, EVENTS_FILE)
        for event in read(logs_dir() / name, None)
    ]
    eps = [
        ep
        for ep in episodes(record, tmax_s)
        if _in_range(ep["since"], since, until)
        and window_filter.lets_through(ep["since"], "episodes")
    ]
    # R solo sobre los episodios con desenlace conocido: reentraron, o se recuperaron tras vencer.
    with_outcome = [ep for ep in eps if ep["reentries"] or ep["final"] == "recovered"]
    reentraron = [ep for ep in with_outcome if ep["reentries"]]

    measurement = {
        "window_since": since or "(todo)",
        "window_until": until or "(ahora)",
        "excluded": [list(span) for span in excluded],
        "include_tests": include_tests,
        "excluded_manual": {
            "usage_rows": window_filter.removed["manual"]["usage_rows"],
            "episodes": window_filter.removed["manual"]["episodes"],
        },
        "excluded_tests": {
            "usage_rows": window_filter.removed["test_windows"]["usage_rows"],
            "episodes": window_filter.removed["test_windows"]["episodes"],
        },
        "test_windows": [
            {**w.to_json(), "removed": window_filter.per_window.get(w.id, 0)}
            for w in window_filter.file.windows
        ],
        "delegations": delegations,
        "counting_failures": failures,
        "jumps_per_class": dict(jumps),
        "immediate_failures": at_moment,
        "diverted_operations": jumps.get("cooldown", 0) + at_moment,
        "episodes": len(eps),
        "episodes_with_outcome": len(with_outcome),
        "episodes_that_reentered": len(reentraron),
        "R": round(len(reentraron) / len(with_outcome), 3) if with_outcome else None,
        "episodes_by_timeout": sum(1 for ep in eps if ep["class"] == "read_timeout"),
        "episodes_reentering_at_tmax": sum(1 for ep in eps if ep["at_tmax"] >= 2),
        "outside_p4_immediate_failures_over_5_pct": delegations > 0
        and at_moment > 0.05 * delegations,
    }
    measurement.update(verdict(measurement))
    return measurement


def _span(text: str) -> tuple[str, str]:
    start, _, end = text.partition(",")
    if not start or not end:
        raise argparse.ArgumentTypeError(i18n.t("cli.script.measure_cooldown.exclude_format"))
    try:
        is_reversed = test_windows.parse_instant(start) > test_windows.parse_instant(end)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            i18n.t("cli.script.measure_cooldown.exclude_unreadable", error=exc)
        ) from exc
    if is_reversed:
        raise argparse.ArgumentTypeError(i18n.t("cli.script.measure_cooldown.exclude_reversed"))
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser(
        description=_t("help._description"), formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--since", help=_t("help.since"))
    parser.add_argument("--until", help=_t("help.until"))
    parser.add_argument(
        "--exclude", type=_span, action="append", default=[], help=_t("help.exclude")
    )
    parser.add_argument("--tmax", type=float, default=900.0, help=_t("help.tmax"))
    parser.add_argument("--json", action="store_true", help=_t("help.json"))
    parser.add_argument("--include-tests", action="store_true", help=_t("help.include_tests"))
    with argparse_in_language(i18n.argparse_gettext, i18n.argparse_ngettext):
        args = parser.parse_args()

    m = measure(args.since, args.until, args.exclude, args.tmax, include_tests=args.include_tests)
    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
        return 0

    print(report(m))
    return 0


def _t(key: str, /, **values: object) -> str:
    return i18n.t(f"cli.script.measure_cooldown.{key}", **values)


def _n(value: object) -> str:
    """Un entero para la persona, con el separador de miles del idioma (REQ-026)."""
    return i18n.format_number(value) if isinstance(value, int) else str(value)


def report(m: dict) -> str:
    """El informe para la persona, en el idioma vigente. Las fechas siguen en ISO 8601 UTC."""
    # `(todo)` y `(ahora)` son los marcadores de «sin límite» del JSON (contrato): aquí se dicen.
    since = _t("all") if m["window_since"] == "(todo)" else m["window_since"]
    until = _t("now") if m["window_until"] == "(ahora)" else m["window_until"]
    lines = [
        _t("window", since=since, until=until, now=f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}"),
        *(_t("excluded", start=start, end=end) for start, end in m["excluded"]),
    ]
    by_hand, windows = m["excluded_manual"], m["excluded_tests"]
    lines.append(
        _t("removed_by_exclude", rows=_n(by_hand["usage_rows"]), episodes=_n(by_hand["episodes"]))
    )
    if m["include_tests"]:
        lines.append(_t("test_windows_not_applied"))
    else:
        lines.append(
            _t(
                "removed_by_test_windows",
                rows=_n(windows["usage_rows"]),
                episodes=_n(windows["episodes"]),
            )
        )
        for w in m["test_windows"]:
            if w["removed"]:
                end = w["end"] or _t("open")
                lines.append(
                    f"    {w['id']}  {_t('span', start=w['start'], end=end)}  "
                    f"{_n(w['removed'])}  {w['label']}"
                )
    r = "None" if m["R"] is None else i18n.format_number(m["R"], None)
    lines += [
        "",
        _t("delegations", n=_n(m["delegations"])),
        _t("counting_failures", n=_n(m["counting_failures"]), minimum=MIN_FAILURES),
        _t("jumps_per_class", jumps=m["jumps_per_class"]),
        _t("immediate_failures", n=_n(m["immediate_failures"])),
        _t("diverted_operations", n=_n(m["diverted_operations"])),
        "",
        _t("episodes", n=_n(m["episodes"]), minimum=MIN_EPISODES),
        _t("with_outcome", n=_n(m["episodes_with_outcome"])),
        _t("reentered", n=_n(m["episodes_that_reentered"]), r=r),
        _t("by_timeout", n=_n(m["episodes_by_timeout"])),
        _t("reentering_at_tmax", n=_n(m["episodes_reentering_at_tmax"])),
        "",
        _t("result", result=i18n.t(_RESULT_KEYS[m["result"]])),
    ]
    if m["rule"] is not None:
        reason, change = rule_text(m["rule"])
        lines.append(_t("rule_applied", rule=m["rule"], reason=reason, change=change))
    for number in m["noted"]:
        lines.append(_t("rule_noted", rule=number, reason=rule_text(number)[0]))
    if m["outside_p4_immediate_failures_over_5_pct"]:
        lines += ["", _t("outside_p4_warning"), _t("outside_p4_note")]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
