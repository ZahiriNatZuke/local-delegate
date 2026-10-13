"""`cost-aggregates.json` y el registro del statusline con los nombres viejos (REQ-005, 006, 008, 033).

Datos SINTÉTICOS en `tmp_path`. El fichero viejo, `coste-agregados.json`, siembra el nuevo una sola
vez, traducido entero ANTES de juntar (la identidad del punto es `(source, type, start, end)`), y no
se toca nunca. El statusline del usuario puede seguir escribiendo `cuota-statusline.jsonl`: se leen
los dos nombres, y los dos ficheros si están los dos.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from test_transcripts import BASE, escribir, peticion, principal, sintetica

from local_delegate import legacy_names, quota, recompute

AHORA = BASE + timedelta(days=1)

#: Claves del formato nuevo → las viejas, para fabricar un `coste-agregados.json` de antes.
_OLD_TOP = {new: old for old, new in legacy_names.FORMATS["cost_aggregates"]["keys"].items()}
_OLD_POINT = {
    new: old for old, new in legacy_names.FORMATS["cost_aggregates_point"]["keys"].items()
}
_OLD_CHECK = {
    new: old for old, new in legacy_names.FORMATS["cost_aggregates_check"]["keys"].items()
}
_OLD_MARK = {new: old for old, new in legacy_names.COST_MARK_VALUES.items()}
_OLD_DISCARD = {new: old for old, new in legacy_names.COST_DISCARD_REASONS.items()}


def _old_point(p: dict) -> dict:
    out = {_OLD_POINT.get(k, k): v for k, v in p.items()}
    out["fuente"] = {"rejection": "rechazo"}.get(out["fuente"], out["fuente"])
    out["marcas"] = [_OLD_MARK.get(m, m) for m in out["marcas"]]
    return out


def _rejection(s: float, kind: str, hours_to_reset: float) -> dict:
    reset = int((BASE + timedelta(hours=hours_to_reset)).timestamp())
    return sintetica(
        s, f"s-{kind}", quota={"status": "rejected", "rateLimitType": kind, "resetsAt": reset}
    )


def _statusline_point(end_days_ago: float, marks: list[str]) -> dict:
    end = AHORA - timedelta(days=end_days_ago)
    return {
        "source": "statusline",
        "type": "five_hour",
        "start": (end - timedelta(hours=2)).isoformat(),
        "end": end.isoformat(),
        "delta_pct": 20,
        "delta_usd": 10.0,
        "C": 50.0,
        "marks": marks,
        "unpriced_requests": None,
    }


def _seed_case(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    """Un `coste-agregados.json` viejo con: el gemelo del rechazo de `five_hour` que vuelve a salir
    del transcript, un punto del statusline vigente, otro caducado, el cotejo y un mes cerrado.
    El transcript da además un rechazo de `seven_day` que el viejo no tiene."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    transcript = escribir(
        principal(claude),
        [
            peticion(0, "m0", usage={"input_tokens": 1_000_000}),
            _rejection(5, "five_hour", 3),
            _rejection(6, "seven_day", 100),
        ],
    )
    # El gemelo, sacado de una corrida aparte: mismos valores, formato viejo.
    scratch = tmp_path / "scratch-log"
    recompute.run(claude, scratch, now=AHORA)
    fresh = json.loads((scratch / recompute.FILE_NAME).read_text(encoding="utf-8"))["points"]
    (twin,) = [p for p in fresh if p["type"] == "five_hour"]
    alive = _statusline_point(2, ["low_bound_if_other_surfaces", "reset"])
    expired = _statusline_point(70, ["low_bound_if_other_surfaces"])
    old = {
        "version": 1,
        "generado": "2026-09-01T00:00:00+00:00",
        "plazo_dias": 30,
        "cotejo": {
            "fecha": "2026-09-01T00:00:00+00:00",
            "version_tabla": "2026-08-30",
            "juzgadas": 4,
            "fuera": 0,
            "sin_precio": [],
            "veredicto": "pasa",
        },
        "n_por_mes": {"202608": {"claude-opus-5|main": [127]}},
        "puntos": [_old_point(twin), _old_point(alive), _old_point(expired)],
        "descartes": {"five_hour": {"delta_pequeno": 3}, "seven_day": {}},
        "reinicios": {"five_hour": None, "seven_day": None},
        "fuentes": {"transcripts": True, "statusline": True},
    }
    log.mkdir(parents=True)
    old_path = log / recompute.OLD_FILE_NAME
    old_path.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    return claude, log, transcript, {"twin": twin, "alive": alive, "expired": expired}


def _raw(log: Path) -> dict:
    return json.loads((log / recompute.FILE_NAME).read_text(encoding="utf-8"))


def test_the_old_file_seeds_the_new_one_once(tmp_path):
    """Los cuatro controles de la siembra, más el fichero viejo intacto byte a byte.

    Controles: mutante «`_point_key` no junta el gemelo» → los descartes de la primera corrida
    traen un `overlapping` que la segunda ya no tiene; mutante «se siembra en cada corrida» (lee
    el viejo aunque exista el nuevo) → el rechazo de `seven_day`, que solo estaba en el nuevo, se
    pierde al borrar el transcript."""
    claude, log, transcript, p = _seed_case(tmp_path)
    old_path = log / recompute.OLD_FILE_NAME
    old_bytes = old_path.read_bytes()

    recompute.run(claude, log, now=AHORA)
    first = _raw(log)
    # Formato nuevo entero: ni una clave ni un valor viejo.
    text = (log / recompute.FILE_NAME).read_text(encoding="utf-8")
    for old_word in ('"puntos"', '"fuente"', '"rechazo"', '"cotejo"', "cota baja", '"pasa"'):
        assert old_word not in text, old_word
    # El gemelo es UN punto; el caducado no entra; el vigente llega con sus marcas traducidas.
    by_type = [(q["source"], q["type"]) for q in first["points"]]
    assert by_type.count(("rejection", "five_hour")) == 1
    assert p["expired"]["end"] not in [q["end"] for q in first["points"]]
    (alive,) = [q for q in first["points"] if q["source"] == "statusline"]
    assert alive["marks"] == ["low_bound_if_other_surfaces", "reset"]
    assert "overlapping" not in first["discards"]["five_hour"]
    assert "corrupt_line" not in first["discards"]["five_hour"]
    # El cotejo y el mes cerrado se arrastran, con el veredicto ya en inglés.
    assert first["check"]["verdict"] == "pass"
    assert first["n_by_month"]["202608"] == {"claude-opus-5|main": [127]}

    recompute.run(claude, log, now=AHORA)
    second = _raw(log)
    assert second["discards"] == first["discards"]
    assert len(second["points"]) == len(first["points"])
    assert p["expired"]["end"] not in [q["end"] for q in second["points"]]

    # Desde la siembra manda el nuevo: un punto que solo está en él sobrevive al transcript borrado.
    assert ("rejection", "seven_day") in by_type  # guarda: el caso podía distinguir
    transcript.unlink()
    recompute.run(claude, log, now=AHORA + timedelta(hours=1))
    third = [(q["source"], q["type"]) for q in _raw(log)["points"]]
    assert ("rejection", "seven_day") in third

    assert old_path.read_bytes() == old_bytes


def test_a_damaged_new_file_does_not_seed_again(tmp_path):
    """Un `cost-aggregates.json` roto cuenta como vacío: no se vuelve a leer el viejo."""
    log = tmp_path / "log"
    log.mkdir()
    (log / recompute.OLD_FILE_NAME).write_text(
        json.dumps({"version": 1, "puntos": [], "plazo_dias": 30}), encoding="utf-8"
    )
    assert recompute.read_aggregates(log)["cleanup_days"] == 30  # guarda: el viejo se lee
    (log / recompute.FILE_NAME).write_text("{ esto no es JSON", encoding="utf-8")
    assert recompute.read_aggregates(log) is None


def test_old_and_new_aggregates_give_the_same_quota(tmp_path):
    """Un dato viejo da el mismo estado de cuota que su equivalente nuevo (REQ-006).

    Controles: mutante «`read_aggregates` no traduce» → no entrega el formato nuevo; mutante
    «`quota.status` no traduce» → el viejo sin traducir sale sin puntos."""
    points = [_statusline_point(d, ["low_bound_if_other_surfaces"]) for d in (1, 3, 5)]
    new = {
        "version": 1,
        "points": points,
        "discards": {"five_hour": {"small_delta": 1}, "seven_day": {}},
        "resets": {"five_hour": None, "seven_day": None},
        "sources": {"transcripts": True, "statusline": True},
    }
    old = {_OLD_TOP.get(k, k): v for k, v in new.items()}
    old["puntos"] = [_old_point(q) for q in points]
    old["descartes"] = {
        k: {_OLD_DISCARD.get(r, r): n for r, n in v.items()} for k, v in new["discards"].items()
    }
    log = tmp_path / "log"
    log.mkdir()
    (log / recompute.OLD_FILE_NAME).write_text(json.dumps(old), encoding="utf-8")
    # `read_aggregates` entrega el formato nuevo…
    assert recompute.read_aggregates(log) == new
    from_old = quota.status(recompute.read_aggregates(log), AHORA)
    assert from_old == quota.status(new, AHORA)
    assert from_old["five_hour"]["status"] == "calibrated"  # guarda: hay algo que comparar
    assert from_old["five_hour"]["discards"] == {"small_delta": 1}
    # …y `quota.status`, que también es lector, entiende el viejo aunque le llegue sin traducir.
    assert quota.status(old, AHORA) == from_old


def test_the_old_check_is_read_with_its_verdict_translated(tmp_path):
    """El cotejo de un fichero viejo llega con las claves y el veredicto nuevos (lo lee `doctor`)."""
    log = tmp_path / "log"
    log.mkdir()
    old_check = {_OLD_CHECK[k]: v for k, v in {"date": "x", "verdict": "falla"}.items()}
    (log / recompute.OLD_FILE_NAME).write_text(
        json.dumps({"version": 1, "cotejo": old_check}), encoding="utf-8"
    )
    assert recompute.read_aggregates(log)["check"] == {"date": "x", "verdict": "fail"}


def test_marks_are_machine_values_and_unknown_ones_are_copied():
    """REQ-033: las cuatro marcas viejas pasan a su valor de máquina; una desconocida, tal cual."""
    old = {
        "fuente": "rechazo",
        "marcas": [
            "cota baja",
            "solo comprobación",
            "cota baja si hubo uso en otras superficies",
            "reinicio",
            "otra cosa",
        ],
    }
    new = legacy_names.normalize_cost_point(old)
    assert new == {
        "source": "rejection",
        "marks": ["low_bound", "check_only", "low_bound_if_other_surfaces", "reset", "otra cosa"],
    }
    assert legacy_names.normalize_cost_point(new) == new  # un punto nuevo sale igual


def test_the_writer_marks_are_the_quota_constants():
    assert {
        quota.MARK_LOW_BOUND,
        quota.MARK_CHECK_ONLY,
        quota.MARK_OTHER_SURFACES,
        quota.MARK_RESET,
    } == set(legacy_names.COST_MARK_VALUES.values())


# --- REQ-008: el registro del statusline con los dos nombres --------------------------------


def _statusline_rows(path: Path, session: str, n: int) -> None:
    rows = [
        {"ts": (BASE + timedelta(minutes=i)).isoformat(), "session_id": session, "five_hour": i}
        for i in range(n)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _rows_read(claude: Path) -> int:
    by_type, _sessions, _d = quota.sanitize(recompute._lines_of(recompute._statusline_logs(claude)))
    return len(by_type["five_hour"])


def test_the_statusline_log_is_read_under_both_names(tmp_path):
    """Control: mutante «solo el nuevo si existe» → con los dos se leen 3 filas y no 5."""
    old, new = legacy_names.QUOTA_STATUSLINE_FILE_NAMES
    only_old, only_new, both = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    _statusline_rows(only_old / old, "s-vieja", 2)
    _statusline_rows(only_new / new, "s-nueva", 3)
    _statusline_rows(both / old, "s-vieja", 2)
    _statusline_rows(both / new, "s-nueva", 3)
    assert _rows_read(only_old) == 2
    assert _rows_read(only_new) == 3
    assert _rows_read(both) == 5
    assert _rows_read(tmp_path / "ninguno") == 0


def test_the_new_statusline_name_counts_as_a_source(tmp_path):
    claude, log = tmp_path / "claude", tmp_path / "log"
    _statusline_rows(claude / legacy_names.QUOTA_STATUSLINE_FILE_NAMES[1], "s", 2)
    recompute.run(claude, log, now=AHORA)
    assert _raw(log)["sources"]["statusline"] is True


# --- El resumen de la terminal dice los valores de máquina en palabras -----------------------


def test_the_summary_says_verdict_and_discards_in_words():
    """Control: mutante «el resumen pinta la clave» → sale `small_delta` en la prosa."""
    summary = {
        "cleanup_days": 30,
        "transcripts": 1,
        "corrupt_lines": 0,
        "backfilled_lines": 0,
        "matches": {},
        "n_cases": 0,
        "check": {
            "table_version": "2026-08-30",
            "verdict": "pass",
            "judged": 4,
            "outside": 0,
            "unpriced": [],
        },
        "points": {"rejection:five_hour": 1},
        "discards": {"five_hour": {"small_delta": 2, "expired": 1}, "seven_day": {}},
        "quota": {"five_hour": "uncalibrated", "seven_day": "uncalibrated"},
    }
    text = recompute.summary_text(summary)
    assert "Cotejo de precios (2026-08-30): pasa;" in text
    assert "variación pequeña 2, caducado 1" in text
    assert "1 de rechazo" in text
    for machine in ("small_delta", "expired", '"pass"', " pass;"):
        assert machine not in text, machine
