"""El script que aplica el criterio de P-4.

Se prueba por la misma razon que `measure_adoption.py`: es quien va a dar el resultado, y un script
que cuenta mal parece una medida. Cada regla tiene su caso y su control en el borde, porque un
umbral mal escrito (`>` por `>=`) cambia el resultado sin que nada falle.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from local_delegate import config

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "measure_cooldown", ROOT / "scripts" / "measure_cooldown.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_cooldown"] = module
    spec.loader.exec_module(module)
    return module


measure_cooldown = _load()


def _ts(day: int, hour: int = 10) -> str:
    return f"2026-09-{day:02d}T{hour:02d}:00:00+00:00"


class Logs:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.usages: list[dict] = []
        #: Filas para `enfriamiento-eventos.jsonl` (el registro viejo, hasta la 0.34.0) y para
        #: `cooldown-events.jsonl` (el nuevo). El script lee los dos, siempre (REQ-007).
        self.record: list[dict] = []
        self.new_log: list[dict] = []

    def failures(self, count: int, day: int = 20, error_class: str = "modelo") -> None:
        self.usages += [
            {
                "ts": _ts(day),
                "tool": "local_summarize",
                "error": "http_500",
                "error_class": error_class,
            }
            for _ in range(count)
        ]

    def diverted(self, how_many: int, day: int = 20) -> None:
        self.usages += [
            {"ts": _ts(day), "tool": "local_summarize", "fallback_class": "enfriamiento"}
            for _ in range(how_many)
        ]

    def episode(
        self,
        day: int,
        model: str = "m",
        error_class: str = "modelo",
        reentry_waits: tuple[float, ...] = (),
        final: str | None = "recovered",
    ) -> None:
        hour = 10
        self.record.append(
            {
                "ts": _ts(day, hour),
                "modelo": model,
                "evento": "entra",
                "clase": error_class,
                "reentradas": 1,
                "espera_s": 120.0,
            }
        )
        for number, wait in enumerate(reentry_waits, start=2):
            hour += 1
            self.record.append(
                {
                    "ts": _ts(day, hour),
                    "modelo": model,
                    "evento": "reentra",
                    "clase": error_class,
                    "reentradas": number,
                    "espera_s": wait,
                }
            )
        if final is not None:
            self.record.append(
                {
                    "ts": _ts(day, hour + 1),
                    "modelo": model,
                    "evento": "limpia",
                    "reentradas": 1 + len(reentry_waits),
                    "espera_s": 120.0,
                    "tras_vencer": final == "recovered",
                }
            )

    def measure(self, **options) -> dict:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "usage-202609.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in self.usages), encoding="utf-8"
        )
        (self.directory / "enfriamiento-eventos.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in self.record), encoding="utf-8"
        )
        (self.directory / "cooldown-events.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in self.new_log), encoding="utf-8"
        )
        return measure_cooldown.measure(options.pop("since", "2026-09-16"), **options)


@pytest.fixture
def logs(tmp_path, monkeypatch) -> Logs:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    return Logs(tmp_path / "logs")


def _five_episodes(logs: Logs, reentran: int = 2, **options) -> None:
    for day in range(20, 25):
        waits = (240.0,) if day - 20 < reentran else ()
        logs.episode(day, model=f"m{day}", reentry_waits=waits, **options)


# --- Los tres resultados ------------------------------------------------------------------------


def test_without_episodes_it_is_not_a_success_but_inconclusive(logs):
    """Una ventana sin enfriamientos no mide nada, y el script no puede leerla como «se quedan»."""
    measurement = logs.measure()
    assert measurement["episodes"] == 0
    assert measurement["result"] == "inconclusive"


def test_four_episodes_are_inconclusive_and_five_are_not(logs):
    logs.failures(10)
    for day in range(20, 24):
        logs.episode(day, model=f"m{day}")
    assert logs.measure()["result"] == "inconclusive"
    logs.episode(24, model="m24")
    assert logs.measure()["result"] == "keep", "con el minimo exacto ya se concluye"


def test_nine_failures_are_inconclusive_even_with_episodes(logs):
    _five_episodes(logs)
    logs.failures(9)
    assert logs.measure()["result"] == "inconclusive"
    logs.failures(1)
    assert logs.measure()["result"] == "keep"


def test_the_failures_that_count_are_the_table_ones_and_nothing_else(logs):
    logs.failures(2, error_class="modelo")
    logs.failures(3, error_class="timeout_lectura")
    logs.failures(4, error_class="capacidad_o_carga")
    logs.failures(5, error_class="peticion")
    logs.usages.append({"ts": _ts(20), "tool": "local_summarize", "fallback_class": "modelo"})
    logs.usages.append({"ts": _ts(20), "tool": "local_summarize", "error": "cooldown"})
    measurement = logs.measure()
    assert measurement["counting_failures"] == 2 + 3 + 1
    assert measurement["immediate_failures"] == 1
    assert measurement["diverted_operations"] == 1


# --- Las reglas, cada una con su borde -----------------------------------------------------------


def test_rule_1_the_model_was_still_broken(logs):
    logs.failures(10)
    _five_episodes(logs, reentran=4)
    measurement = logs.measure()
    assert measurement["R"] == pytest.approx(0.8)
    assert (measurement["result"], measurement["rule"]) == ("change", 1)


def test_rule_1_does_not_fire_with_r_at_60(logs):
    logs.failures(10)
    _five_episodes(logs, reentran=3)
    measurement = logs.measure()
    assert measurement["R"] == pytest.approx(0.6)
    assert measurement["result"] == "keep"


def test_rule_2_is_opened_by_timeouts(logs):
    logs.failures(10)
    for day in range(20, 25):
        error_class = "timeout_lectura" if day < 23 else "modelo"
        waits = (240.0,) if day < 22 else ()
        logs.episode(day, model=f"m{day}", error_class=error_class, reentry_waits=waits)
    measurement = logs.measure()
    assert measurement["episodes_by_timeout"] == 3
    assert (measurement["result"], measurement["rule"]) == ("change", 2)


def test_rule_2_fires_with_exactly_half(logs):
    """El borde de «la mitad o mas» solo existe con un numero par de episodios: con cinco, `>=` y
    `>` dan lo mismo y el mutante que los cambia sobrevivio."""
    logs.failures(10)
    for day in range(20, 26):
        error_class = "timeout_lectura" if day < 23 else "modelo"
        waits = (240.0,) if day < 22 else ()
        logs.episode(day, model=f"m{day}", error_class=error_class, reentry_waits=waits)
    measurement = logs.measure()
    assert (measurement["episodes"], measurement["episodes_by_timeout"]) == (6, 3)
    assert measurement["R"] == pytest.approx(2 / 6, abs=1e-3), "R fuera de las reglas 1 y 3"
    assert (measurement["result"], measurement["rule"]) == ("change", 2)


def test_rule_2_does_not_fire_with_two_of_five(logs):
    logs.failures(10)
    for day in range(20, 25):
        error_class = "timeout_lectura" if day < 22 else "modelo"
        waits = (240.0,) if day < 22 else ()
        logs.episode(day, model=f"m{day}", error_class=error_class, reentry_waits=waits)
    assert logs.measure()["result"] == "keep"


def test_rule_3_cools_down_too_much(logs):
    logs.failures(10)
    _five_episodes(logs, reentran=0)
    logs.diverted(15)
    measurement = logs.measure()
    assert measurement["R"] == 0
    assert (measurement["result"], measurement["rule"]) == ("change", 3)


def test_rule_3_does_not_fire_with_fewer_than_three_diverted_on_average(logs):
    logs.failures(10)
    _five_episodes(logs, reentran=0)
    logs.diverted(14)
    assert logs.measure()["result"] == "keep"


def test_rule_4_reaches_tmax_and_reenters_again(logs):
    logs.failures(10)
    logs.episode(20, model="roto", reentry_waits=(240.0, 480.0, 900.0, 900.0))
    for day in range(21, 25):
        logs.episode(day, model=f"m{day}")
    measurement = logs.measure()
    assert measurement["episodes_reentering_at_tmax"] == 1
    assert (measurement["result"], measurement["rule"]) == ("change", 4)


def test_rule_4_does_not_fire_if_it_reaches_tmax_and_recovers(logs):
    logs.failures(10)
    logs.episode(20, model="roto", reentry_waits=(240.0, 480.0, 900.0))
    for day in range(21, 25):
        logs.episode(day, model=f"m{day}")
    assert logs.measure()["result"] == "keep"


def test_only_the_first_rule_applies_and_the_rest_are_noted(logs):
    logs.failures(10)
    logs.episode(
        20, model="roto", error_class="timeout_lectura", reentry_waits=(240.0, 900.0, 900.0)
    )
    for day in range(21, 25):
        logs.episode(day, model=f"m{day}", error_class="timeout_lectura", reentry_waits=(240.0,))
    measurement = logs.measure()
    assert measurement["rule"] == 1
    assert measurement["noted"] == [2, 4]


# --- Que entra en la ventana y en R ------------------------------------------------------------


def test_r_ignores_episodes_without_known_outcome(logs):
    """Abiertos, o limpiados por un exito con `model` explicito antes de vencer: no se sabe si el
    modelo se habria recuperado, asi que no pueden contar ni a favor ni en contra."""
    logs.episode(20, model="a", reentry_waits=(240.0,))
    logs.episode(21, model="b")
    logs.episode(22, model="c", final=None)
    logs.episode(23, model="d", final="explicit_success")
    measurement = logs.measure()
    assert measurement["episodes"] == 4
    assert measurement["episodes_with_outcome"] == 2
    assert measurement["R"] == pytest.approx(0.5)


def test_the_excluded_span_removes_its_episodes_and_failures(logs):
    logs.failures(10, day=21)
    logs.failures(10, day=25)
    _five_episodes(logs)
    complete = logs.measure()
    assert complete["result"] == "keep"
    span = ("2026-09-21T00:00", "2026-09-22T00:00")
    trimmed = logs.measure(excluded=[span])
    assert trimmed["episodes"] == 4
    assert trimmed["counting_failures"] == 10
    assert trimmed["result"] == "inconclusive"


def test_what_precedes_the_window_does_not_count(logs):
    logs.failures(10, day=10)
    for day in (10, 11, 12, 13, 14):
        logs.episode(day, model=f"m{day}")
    measurement = logs.measure()
    assert (measurement["episodes"], measurement["counting_failures"]) == (0, 0)


def test_a_reentry_without_its_entry_is_ignored(logs):
    logs.record.append(
        {
            "ts": _ts(20),
            "modelo": "m",
            "evento": "reentra",
            "clase": "modelo",
            "reentradas": 2,
            "espera_s": 240.0,
        }
    )
    assert logs.measure()["episodes"] == 0


def test_the_warning_outside_p4_fires_above_5_pct(logs):
    logs.usages += [{"ts": _ts(20), "tool": "local_summarize"} for _ in range(18)]
    logs.usages += [
        {"ts": _ts(20), "tool": "local_summarize", "error": "cooldown"} for _ in range(2)
    ]
    assert logs.measure()["outside_p4_immediate_failures_over_5_pct"] is True
    logs.usages += [{"ts": _ts(20), "tool": "local_summarize"} for _ in range(20)]
    assert logs.measure()["outside_p4_immediate_failures_over_5_pct"] is False


def test_reads_the_log_the_module_writes(logs):
    """Ida y vuelta: los eventos que escribe `CooldownState` son los que este script agrupa. Sin esto, los
    tests de arriba prueban el script contra un formato que yo mismo escribi a mano."""
    from local_delegate import cooldown

    now = [1_789_900_000.0]  # 2026-09-20
    state = cooldown.CooldownState(
        logs.directory / "cooldown.json",
        failures=3,
        wait_s=120.0,
        max_wait_s=900.0,
        clock=lambda: now[0],
    )
    for _ in range(3):
        state.record_failure("m", "timeout_lectura")
    now[0] += 121
    state.record_failure("m", "modelo")
    now[0] += 241
    state.record_success("m")
    record = (logs.directory / cooldown.EVENTS_FILE).read_text(encoding="utf-8")
    logs.new_log = [json.loads(line) for line in record.splitlines()]
    assert {e["event"] for e in logs.new_log} == {"enter", "reenter", "clear"}
    measurement = logs.measure()
    assert measurement["episodes"] == 1
    assert measurement["episodes_that_reentered"] == 1
    assert measurement["episodes_by_timeout"] == 1


# --- Arranque y ventanas de prueba (test-windows-out-of-metrics, REQ-020) ------------------------


def _without_metadata(measurement: dict) -> dict:
    """Lo que decide P-4, sin lo que solo describe como se filtro."""
    outside = {"excluded", "include_tests", "excluded_manual", "excluded_tests", "test_windows"}
    return {k: v for k, v in measurement.items() if k not in outside}


def test_real_main_exits_with_zero(tmp_path, monkeypatch, capsys):
    """El `main()` reventaba siempre con `AttributeError: ... 'exclude'` (evidencias/T0.md).
    Control: volver a poner `args.excluir` → este test falla."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["measure_cooldown.py", "--since", "2030-01-01"])
    assert measure_cooldown.main() == 0
    assert "RESULTADO: no concluyente" in capsys.readouterr().out
    monkeypatch.setattr(
        sys,
        "argv",
        ["measure_cooldown.py", "--json", "--exclude", "2026-09-15T19:31:14,2026-09-15T19:35:14"],
    )
    assert measure_cooldown.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["excluded_tests"]) == {"usage_rows", "episodes"}
    assert data["test_windows"] == []


def _old_name_wrapper():
    """`scripts/medir_enfriamiento.py`, el envoltorio de REQ-046 con el nombre y las opciones viejas."""
    spec = importlib.util.spec_from_file_location(
        "medir_enfriamiento", ROOT / "scripts" / "medir_enfriamiento.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_old_options_translate_to_the_new_ones():
    wrapper = _old_name_wrapper()
    assert wrapper.translate(
        [
            "--desde",
            "2026-09-16",
            "--hasta=2026-09-20",
            "--excluir",
            "a,b",
            "--json",
            "--tmax",
            "60",
        ]
    ) == [
        "--since",
        "2026-09-16",
        "--until=2026-09-20",
        "--exclude",
        "a,b",
        "--json",
        "--tmax",
        "60",
    ]


def test_the_documented_p4_command_still_works(logs, monkeypatch, capsys):
    """REQ-046: el comando de P-4 tal como está escrito (`--desde`) da el mismo informe que el nuevo.
    Control: quitar `--desde` de `OLD_OPTIONS` → argparse sale con 2 y este test falla."""
    _five_episodes(logs)
    logs.measure()  # escribe los ficheros del escenario en LOG_DIR
    argv = ["--since", "2026-09-16", "--exclude", "2026-09-21T00:00,2026-09-21T23:59:59", "--json"]
    monkeypatch.setattr(sys, "argv", ["measure_cooldown.py", *argv])
    assert measure_cooldown.main() == 0
    new = json.loads(capsys.readouterr().out)
    assert new["episodes"] > 0, "guarda: el escenario cuenta algo"
    old_argv = [
        "--desde",
        "2026-09-16",
        "--excluir",
        "2026-09-21T00:00,2026-09-21T23:59:59",
        "--json",
    ]
    monkeypatch.setattr(sys, "argv", ["medir_enfriamiento.py", *old_argv])
    assert _old_name_wrapper().main() == 0
    assert json.loads(capsys.readouterr().out) == new


def test_the_old_wrapper_prints_the_same_report_with_the_spanish_result(logs, monkeypatch, capsys):
    """REQ-046: sin `--json`, el envoltorio viejo imprime el mismo informe que el nuevo, y el
    resultado sale con su rótulo en español aunque el valor interno sea inglés (lote 5).
    Control: imprimir `m['result']` tal cual → sale «RESULTADO: keep» y este test falla."""
    logs.failures(10)
    _five_episodes(logs)
    logs.measure()  # escribe los ficheros del escenario en LOG_DIR
    monkeypatch.setattr(sys, "argv", ["measure_cooldown.py", "--since", "2026-09-16", "--json"])
    assert measure_cooldown.main() == 0
    measured = json.loads(capsys.readouterr().out)
    assert measured["episodes"] > 0, "guarda: el escenario cuenta algo"
    measured = measured["result"]
    assert measured != "inconclusive", "guarda: con los fallos minimos ya se concluye"
    monkeypatch.setattr(sys, "argv", ["measure_cooldown.py", "--since", "2026-09-16"])
    assert measure_cooldown.main() == 0
    new = capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["medir_enfriamiento.py", "--desde", "2026-09-16"])
    assert _old_name_wrapper().main() == 0
    assert capsys.readouterr().out == new
    expected = {"inconclusive": "no concluyente", "keep": "se quedan", "change": "cambiar"}
    assert f"RESULTADO: {expected[measured]}\n" in new


def test_p4_can_be_measured_again_with_the_file_window(logs):
    """El escenario del spec. Control: mutante «se ignora el fichero» → las dos medidas difieren."""
    from local_delegate import test_windows

    logs.failures(10, day=21)
    logs.failures(10, day=25)
    _five_episodes(logs)
    span = ("2026-09-21T00:00:00Z", "2026-09-21T23:59:59Z")
    complete = logs.measure()
    by_hand = logs.measure(excluded=[span], include_tests=True)
    assert _without_metadata(complete) != _without_metadata(by_hand), "guarda: el tramo quita algo"
    test_windows.add(logs.directory, *span, "P-4 fallo provocado")
    with_file = logs.measure()
    assert _without_metadata(with_file) == _without_metadata(by_hand)
    assert with_file["excluded_tests"] == {"usage_rows": 10, "episodes": 1}
    assert [w["removed"] for w in with_file["test_windows"]] == [11]


def test_include_tests_does_not_remove_the_exclude_spans(logs):
    from local_delegate import test_windows

    logs.failures(3, day=21)
    logs.failures(4, day=22)
    test_windows.add(logs.directory, "2026-09-22T00:00:00Z", "2026-09-22T23:59:59Z")
    m = logs.measure(
        excluded=[("2026-09-21T00:00:00Z", "2026-09-21T23:59:59Z")], include_tests=True
    )
    assert m["excluded_manual"]["usage_rows"] == 3
    assert m["excluded_tests"]["usage_rows"] == 0
    assert m["counting_failures"] == 4


def test_exclude_compares_instants_not_strings(logs):
    """Con cadenas, `...01:20:05+00:00` < `...01:20:05.255Z` (el `+` ordena antes que el `.`) y la
    fila se colaba. Control: mutante que compara cadenas → este test falla."""
    logs.usages.append(
        {"ts": "2026-09-20T01:20:05+00:00", "tool": "local_summarize", "error_class": "modelo"}
    )
    m = logs.measure(excluded=[("2026-09-20T01:20:05.255Z", "2026-09-20T01:22:31.544Z")])
    assert m["excluded_manual"]["usage_rows"] == 1
    assert m["counting_failures"] == 0


# --- Formato viejo, nuevo y mezclado (REQ-007, ola A3) --------------------------------------------

_OLD_TO_NEW = {
    "modelo": "model",
    "timeout_lectura": "read_timeout",
    "capacidad_o_carga": "capacity_or_load",
    "peticion": "request",
    "enfriamiento": "cooldown",
}


def _scenario(logs: Logs, fmt: str) -> dict:
    """El mismo tramo de P-4 escrito con las clases viejas, las nuevas o mitad y mitad."""

    def error_class(old: str, i: int) -> str:
        if fmt == "old" or (fmt == "mixed" and i % 2 == 0):
            return old
        return _OLD_TO_NEW[old]

    for i, old in enumerate(["modelo"] * 4 + ["timeout_lectura"] * 4 + ["capacidad_o_carga"] * 3):
        logs.failures(1, error_class=error_class(old, i))
    for i in range(4):
        logs.usages.append(
            {
                "ts": _ts(20),
                "tool": "local_summarize",
                "fallback_class": error_class("enfriamiento", i),
            }
        )
        logs.usages.append(
            {"ts": _ts(21), "tool": "local_summarize", "fallback_class": error_class("modelo", i)}
        )
    for day in range(20, 26):
        old = "timeout_lectura" if day < 23 else "modelo"
        waits = (240.0,) if day < 22 else ()
        logs.episode(day, model=f"m{day}", error_class=error_class(old, day), reentry_waits=waits)
    return logs.measure()


def test_the_report_is_the_same_with_old_new_and_mixed_classes(tmp_path, monkeypatch):
    measurements = {}
    for fmt in ("old", "new", "mixed"):
        directory = tmp_path / fmt
        monkeypatch.setattr(config, "LOG_DIR", directory)
        measurements[fmt] = _scenario(Logs(directory), fmt)
        measurements[fmt].pop("excluded", None)
    # Guarda: el escenario llega a contar algo en cada medida que depende de la clase.
    assert measurements["old"]["counting_failures"] == 12
    assert measurements["old"]["episodes_by_timeout"] == 3
    assert measurements["old"]["diverted_operations"] == 4
    assert measurements["new"] == measurements["old"]
    assert measurements["mixed"] == measurements["old"]


# --- Registro de episodios viejo, nuevo y mezclado (REQ-007, ola A4) ------------------------------
#
# Desde la A4 el daemon escribe `cooldown-events.jsonl` con claves y valores en inglés; lo escrito
# antes sigue en `enfriamiento-eventos.jsonl`. La traducción de la fila se escribe aquí a mano, no
# con `legacy_names`: si no, el test compararía la tabla consigo misma.

_NEW_KEY = {
    "modelo": "model",
    "evento": "event",
    "clase": "class",
    "reentradas": "reentries",
    "espera_s": "wait_s",
    "tras_vencer": "after_expiry",
}
_NEW_EVENT = {"entra": "enter", "reentra": "reenter", "limpia": "clear"}


def _new_row(row: dict) -> dict:
    new = {_NEW_KEY.get(k, k): v for k, v in row.items()}
    new["event"] = _NEW_EVENT[new["event"]]
    if "class" in new:
        new["class"] = _OLD_TO_NEW[new["class"]]
    return new


def _p4_episodes(logs: Logs) -> list[dict]:
    """Seis episodios en formato viejo: tres por timeout, dos que reentran, uno sin desenlace."""
    logs.failures(10)
    for day in range(20, 26):
        error_class = "timeout_lectura" if day < 23 else "modelo"
        waits = (240.0, 900.0, 900.0) if day < 22 else ()
        final = None if day == 25 else ("recovered" if day % 2 else "explicit_success")
        logs.episode(
            day, model=f"m{day}", error_class=error_class, reentry_waits=waits, final=final
        )
    rows, logs.record = logs.record, []
    return rows


@pytest.mark.parametrize("fmt", ["new", "mixed_in_two_files", "mixed_in_new_file"])
def test_the_report_is_the_same_with_the_old_new_and_mixed_log(tmp_path, monkeypatch, fmt):
    def measurement(name: str, split) -> dict:
        directory = tmp_path / name
        monkeypatch.setattr(config, "LOG_DIR", directory)
        logs = Logs(directory)
        for i, row in enumerate(_p4_episodes(logs)):
            dest, row = split(i, row)
            (logs.record if dest == "old" else logs.new_log).append(row)
        return logs.measure()

    old = measurement("old", lambda i, row: ("old", row))
    # Guarda: el escenario cuenta algo en cada medida que depende del registro de episodios.
    assert old["episodes"] == 6
    assert old["episodes_by_timeout"] == 3
    assert old["episodes_that_reentered"] == 2
    assert old["episodes_reentering_at_tmax"] == 2
    assert old["episodes_with_outcome"] == 3
    splits = {
        "new": lambda i, row: ("new", _new_row(row)),
        "mixed_in_two_files": lambda i, row: ("old", row) if i % 2 else ("new", _new_row(row)),
        "mixed_in_new_file": lambda i, row: (
            "new",
            row if i % 2 else _new_row(row),
        ),
    }
    assert measurement(fmt, splits[fmt]) == old
