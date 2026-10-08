"""`local-delegate recalcular-coste`: privacidad, solo lectura, fusión y agregados (T5).

HOME de Claude Code, registro del statusline y log de uso SINTÉTICOS en `tmp_path`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

from test_transcripts import (
    BASE,
    OPUS,
    escribir,
    escribir_log,
    linea_log,
    peticion,
    principal,
    resultado,
    sintetica,
    subagente,
    ts,
)

from local_delegate import cli, config, recalcular

AHORA = BASE + timedelta(days=1)
MES = "202610"


def _delegacion_con_n(
    ruta: Path, tid: str, n: int, *, sesion: str = "sesion-sintetica-0001", s0: float = 0
) -> list:
    """Un hilo con una delegación y `n` peticiones después de su resultado (sin caducidades)."""
    lineas = [
        peticion(s0, f"{tid}-0", sesion=sesion, tool_use=(tid, "local_summarize", "docs/a.md")),
        resultado(s0 + 1, tid, sesion=sesion),
    ]
    lineas += [peticion(s0 + 2 + i, f"{tid}-{i + 1}", sesion=sesion) for i in range(n)]
    return escribir(ruta, lineas)


def _textos(log: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(log.glob("*.json"))}


# --- REQ-072: privacidad --------------------------------------------------------------------


def test_la_privacidad(tmp_path):
    MARCADORA = "MARCADORA-7f3a"
    SESION = "sesion-marcadora-9c41"
    TOOL_USE_ID = "toolu_privado01"
    claude, log = tmp_path / "claude", tmp_path / "log"
    proyecto = f"D--{MARCADORA}-proyecto"
    ruta = f"{MARCADORA}/doc.md"
    reset = int((BASE + timedelta(hours=3)).timestamp())
    escribir(
        principal(claude, sesion=SESION, proyecto=proyecto),
        [
            {
                "type": "user",
                "timestamp": ts(-5),
                "sessionId": SESION,
                "message": {"role": "user", "content": f"resume {MARCADORA} por favor"},
            },
            peticion(0, "m0", sesion=SESION, tool_use=(TOOL_USE_ID, "local_summarize", ruta)),
            resultado(1, TOOL_USE_ID, f"el resumen de {MARCADORA}", sesion=SESION),
            peticion(2, "m1", sesion=SESION, usage={"input_tokens": 1000}),
            sintetica(
                5,
                "s1",
                sesion=SESION,
                quota={"status": "rejected", "rateLimitType": "five_hour", "resetsAt": reset},
            ),
            {
                "type": "cost-state",
                "sessionId": SESION,
                "startTime": ts(0),
                "modelUsage": {OPUS: {"inputTokens": 1000, "costUSD": 0.004}},
            },
        ],
    )
    escribir(
        claude / "cuota-statusline.jsonl",
        [
            {"ts": ts(0), "session_id": SESION, "five_hour": 10, "five_reset": "r", "cost_usd": 1},
            {"ts": ts(9), "session_id": SESION, "five_hour": 40, "five_reset": "r", "cost_usd": 3},
        ],
    )
    escribir_log(
        log,
        [linea_log(1, path=ruta, tool_use_id=TOOL_USE_ID), linea_log(1, path=ruta)],
    )
    recalcular.ejecutar(claude, log, ahora=AHORA)

    textos = _textos(log)
    assert recalcular.NOMBRE in textos
    assert f"atribucion-{MES}.json" in textos  # guarda: el relleno se escribió
    texto_de_todos_los_json = "\n".join(textos.values())
    assert MARCADORA not in texto_de_todos_los_json
    assert SESION not in texto_de_todos_los_json
    texto_de_coste_agregados = textos[recalcular.NOMBRE]
    assert TOOL_USE_ID not in texto_de_coste_agregados
    agregados = json.loads(texto_de_coste_agregados)
    assert agregados["puntos"]  # guarda: había algo que escribir


# --- REQ-074: idempotente y de solo lectura -------------------------------------------------


def _foto(raiz: Path) -> list[tuple]:
    return sorted(
        (
            str(p.relative_to(raiz)),
            p.stat().st_size,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in raiz.rglob("*")
        if p.is_file()
    )


def _sin_fechas(agregados: dict) -> dict:
    copia = json.loads(json.dumps(agregados))
    copia.pop("generado", None)
    if isinstance(copia.get("cotejo"), dict):
        copia["cotejo"].pop("fecha", None)
    return copia


def test_idempotente_y_solo_lectura(tmp_path):
    claude, log = tmp_path / "claude", tmp_path / "log"
    (claude).mkdir()
    (claude / "settings.json").write_text('{"cleanupPeriodDays": 60}', encoding="utf-8")
    _delegacion_con_n(subagente(claude, "a1"), "toolu_i1", 4)
    escribir(
        claude / "cuota-statusline.jsonl",
        [
            {"ts": ts(0), "session_id": "s", "five_hour": 10, "five_reset": "r", "cost_usd": 1},
            {"ts": ts(90), "session_id": "s", "five_hour": 30, "five_reset": "r", "cost_usd": 2},
        ],
    )
    escribir_log(log, [linea_log(1, tool_use_id="toolu_i1"), linea_log(1)])
    antes = _foto(claude)

    recalcular.ejecutar(claude, log, ahora=AHORA)
    primera = _textos(log)
    recalcular.ejecutar(claude, log, ahora=AHORA + timedelta(minutes=1))
    segunda = _textos(log)

    despues = _foto(claude)
    assert despues == antes
    assert set(primera) == set(segunda) == {recalcular.NOMBRE, f"atribucion-{MES}.json"}
    assert primera[f"atribucion-{MES}.json"] == segunda[f"atribucion-{MES}.json"]
    a1, a2 = json.loads(primera[recalcular.NOMBRE]), json.loads(segunda[recalcular.NOMBRE])
    assert a1["generado"] != a2["generado"]
    assert _sin_fechas(a1) == _sin_fechas(a2)


# --- REQ-042 (2): agregados de N --------------------------------------------------------------


def test_los_agregados_de_n_no_cuentan_excluidas(tmp_path):
    """Una delegación de Claude Code (N = 40), una del cliente `mcp` (N = 60) y una de un banco
    (N = 70): el agregado solo tiene el 40."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    _delegacion_con_n(subagente(claude, "a1"), "toolu_cc", 40)
    _delegacion_con_n(subagente(claude, "a2"), "toolu_mcp", 60)
    _delegacion_con_n(
        subagente(claude, "a3", proyecto="C--Users-x-AppData-Local-Temp-banco"), "toolu_bk", 70
    )
    escribir_log(
        log,
        [
            linea_log(1, tool_use_id="toolu_cc"),
            linea_log(1, tool_use_id="toolu_mcp", client="mcp"),
            linea_log(1, tool_use_id="toolu_bk"),
        ],
    )
    recalcular.ejecutar(claude, log, ahora=AHORA)
    agregados = recalcular.leer_agregados(log)
    assert agregados["n_por_mes"][MES]["claude-opus-5-5|subagent"] == [40]


# --- REQ-071: fundir, no sobrescribir ---------------------------------------------------------


def test_un_punto_sobrevive_al_transcript_borrado(tmp_path):
    claude, log = tmp_path / "claude", tmp_path / "log"
    reset = int((BASE + timedelta(hours=3)).timestamp())
    transcript = escribir(
        principal(claude),
        [
            peticion(0, "m0", usage={"input_tokens": 1_000_000}),
            sintetica(
                5,
                "s1",
                quota={"status": "rejected", "rateLimitType": "five_hour", "resetsAt": reset},
            ),
        ],
    )
    recalcular.ejecutar(claude, log, ahora=AHORA)
    (punto,) = recalcular.leer_agregados(log)["puntos"]
    assert punto["fuente"] == "rechazo"

    transcript.unlink()  # Claude Code lo borra a los `H` días
    recalcular.ejecutar(claude, log, ahora=AHORA + timedelta(days=1))
    agregados = recalcular.leer_agregados(log)
    assert punto in agregados["puntos"]

    # …hasta que caduca (60 días).
    recalcular.ejecutar(claude, log, ahora=AHORA + timedelta(days=62))
    assert recalcular.leer_agregados(log)["puntos"] == []


def test_un_mes_viejo_no_se_recalcula(tmp_path):
    """Agosto terminó hace más de 30 días: se conserva lo guardado aunque hoy saliera otra cosa."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    claude.mkdir()
    (claude / "settings.json").write_text('{"cleanupPeriodDays": 90}', encoding="utf-8")
    _delegacion_con_n(subagente(claude, "a1"), "toolu_ago", 7, s0=-41 * 86400)
    escribir_log(log, [linea_log(-41 * 86400 + 1, tool_use_id="toolu_ago")], mes="202608")
    PREVIO = {"claude-opus-5|main": [127]}
    log.mkdir(exist_ok=True)
    recalcular.escribir_agregados(log, {"version": 1, "n_por_mes": {"202608": PREVIO}})

    recalcular.ejecutar(claude, log, ahora=AHORA + timedelta(days=5))  # 2026-10-07
    agregados = recalcular.leer_agregados(log)
    assert agregados["n_por_mes"]["202608"] == PREVIO

    # Guarda: sin lo previo, ese mes sí sale del relleno (el caso podía dar otra cosa).
    (log / recalcular.NOMBRE).unlink()
    recalcular.ejecutar(claude, log, ahora=AHORA + timedelta(days=5))
    assert recalcular.leer_agregados(log)["n_por_mes"]["202608"] == {f"{OPUS}|subagent": [7]}


def test_guarda_el_plazo(tmp_path):
    claude, log = tmp_path / "claude", tmp_path / "log"
    claude.mkdir()
    (claude / "settings.json").write_text('{"cleanupPeriodDays": 90}', encoding="utf-8")
    recalcular.ejecutar(claude, log, ahora=AHORA)
    agregados = recalcular.leer_agregados(log)
    assert agregados.get("plazo_dias") == 90


def test_sin_transcripts_no_rellena(tmp_path):
    """Otra máquina (la Mac, un CI): sin `projects` no se escribe ningún relleno, y las fuentes
    dicen que no hay datos."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    escribir_log(log, [linea_log(1)])
    resumen = recalcular.ejecutar(claude, log, ahora=AHORA)
    assert list(log.glob("atribucion-*.json")) == []
    agregados = recalcular.leer_agregados(log)
    assert agregados["fuentes"] == {"transcripts": False, "statusline": False}
    assert agregados["cotejo"] is None
    assert resumen["cuota"] == {"five_hour": "sin calibrar", "seven_day": "sin calibrar"}


# --- REQ-070: el subcomando -------------------------------------------------------------------


def test_el_cli_lo_lanza(tmp_path, monkeypatch, capsys):
    claude, log = tmp_path / "claude", tmp_path / "log"
    _delegacion_con_n(subagente(claude, "a1"), "toolu_cli", 3)
    monkeypatch.setattr(config, "LOG_DIR", log)
    try:
        codigo = cli.run(["recalcular-coste", "--claude-dir", str(claude)])
    except SystemExit as e:
        codigo = e.code
    salida = capsys.readouterr().out
    assert codigo == 0
    assert (log / recalcular.NOMBRE).is_file()
    assert "Plazo de borrado" in salida
    assert str(tmp_path) not in salida  # el resumen da conteos, no rutas


def test_los_agregados_de_n_no_cuentan_las_filas_en_ventana(tmp_path):
    """test-windows-out-of-metrics, REQ-015. La misma delegación cuenta sin ventana y deja de
    contar con ella: el test comprueba algo en los dos sentidos.
    Control: mutante «`test_reason` ignora `test_window`» → el agregado sigue con el 50."""
    from local_delegate import test_windows

    claude, log = tmp_path / "claude", tmp_path / "log"
    _delegacion_con_n(subagente(claude, "a1"), "toolu_cc", 40)
    _delegacion_con_n(subagente(claude, "a2"), "toolu_win", 50, s0=500)
    escribir_log(
        log,
        [linea_log(1, tool_use_id="toolu_cc"), linea_log(501, tool_use_id="toolu_win")],
    )
    recalcular.ejecutar(claude, log, ahora=AHORA)
    sin_ventana = recalcular.leer_agregados(log)["n_por_mes"][MES]["claude-opus-5-5|subagent"]
    assert sorted(sin_ventana) == [40, 50]
    inicio = BASE + timedelta(seconds=500)
    test_windows.add(log, inicio, inicio + timedelta(seconds=10), "prueba")
    recalcular.ejecutar(claude, log, ahora=AHORA)
    con_ventana = recalcular.leer_agregados(log)["n_por_mes"][MES]["claude-opus-5-5|subagent"]
    assert con_ventana == [40]
