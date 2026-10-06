"""Lectura de transcripts para `recalcular-coste`: cruce, `N`, caducidades y `cost-state` (T5).

Todo es SINTÉTICO y vive en `tmp_path`: ningún id de sesión, ruta ni texto real. Los
constructores de este fichero (`peticion`, `resultado`, `escribir`…) los reutilizan
`test_cuota.py` y `test_recalcular.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_delegate import atribucion, recalcular, transcripts

BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SESION = "sesion-sintetica-0001"
OPUS = "claude-opus-5-5"
PREFIJO = transcripts.PREFIJO


# --- Constructores ------------------------------------------------------------------------------


def ts(s: float) -> str:
    """Hora de un transcript (con milisegundos y `Z`, como Claude Code)."""
    return (BASE + timedelta(seconds=s)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ts_log(s: float) -> str:
    """Hora de una línea del log (en segundos, como `server._log_event`)."""
    return (BASE + timedelta(seconds=s)).isoformat(timespec="seconds")


def peticion(
    s: float,
    mid: str,
    *,
    modelo: str = OPUS,
    sesion: str = SESION,
    tool_use: tuple[str, str, str | None] | None = None,
    effort: str | None = "high",
    usage: dict | None = None,
) -> dict:
    """Una línea `assistant`; con `tool_use=(id, tool, path)` lleva la llamada a local-delegate."""
    if tool_use:
        tid, tool, path = tool_use
        contenido = [
            {
                "type": "tool_use",
                "id": tid,
                "name": PREFIJO + tool,
                "input": {"path": path} if path else {},
            }
        ]
    else:
        contenido = [{"type": "text", "text": "respuesta sintética"}]
    linea = {
        "type": "assistant",
        "timestamp": ts(s),
        "sessionId": sesion,
        "requestId": f"req_{mid}",
        "message": {"id": mid, "model": modelo, "content": contenido, "usage": usage or {}},
    }
    if effort is not None:
        linea["effort"] = effort
    return linea


def resultado(s: float, tid: str, texto: str = "hecho", *, sesion: str = SESION) -> dict:
    return {
        "type": "user",
        "timestamp": ts(s),
        "sessionId": sesion,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tid, "content": texto}],
        },
    }


def sintetica(s: float, mid: str, *, quota: object = None, sesion: str = SESION) -> dict:
    linea = {
        "type": "assistant",
        "timestamp": ts(s),
        "sessionId": sesion,
        "message": {"id": mid, "model": "<synthetic>", "content": []},
    }
    if quota is not None:
        linea["quotaLimits"] = quota
    return linea


def compactacion(s: float) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "timestamp": ts(s)}


def escribir(path: Path, lineas: list) -> Path:
    """Un JSONL; una cadena se escribe tal cual (para las líneas rotas)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    texto = "".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lineas)
    path.write_text(texto, encoding="utf-8")
    return path


def principal(claude: Path, *, sesion: str = SESION, proyecto: str = "D--Proyecto") -> Path:
    return claude / "projects" / proyecto / f"{sesion}.jsonl"


def subagente(
    claude: Path, agente: str, *, sesion: str = SESION, proyecto: str = "D--Proyecto"
) -> Path:
    return claude / "projects" / proyecto / sesion / "subagents" / f"agent-{agente}.jsonl"


def linea_log(s: float, tool: str = "local_summarize", **extra) -> dict:
    fila = {
        "ts": ts_log(s),
        "tool": tool,
        "client": "claude-code",
        "ok": True,
        "source": "path",
        "chars_in": 4000,
        "chars_out": 400,
    }
    fila.update(extra)
    return fila


def escribir_log(log_dir: Path, filas: list[dict], mes: str = "202610") -> Path:
    return escribir(log_dir / f"usage-{mes}.jsonl", filas)


def casar_todo(claude: Path, filas: list[dict]) -> list[dict | None]:
    """Las entradas de `casar` en el orden de las filas (`None` si una fila no tiene)."""
    indice = transcripts.leer(claude / "projects")
    claves = atribucion.claves_del_fichero(filas)
    entradas = transcripts.casar(zip(claves, filas), indice, desde=BASE - timedelta(days=1))
    return [entradas.get(c) for c in claves]


# --- N y caducidades (REQ-043) --------------------------------------------------------------


def test_n_y_caducidades_conocidos(tmp_path):
    """Subagente (TTL 300 s). Escrito a mano: después de `t0` = 1 s cuentan m1 (una vez, aunque
    aparece en dos líneas), m2 y m3; la `<synthetic>` no cuenta y m4 cae tras el
    `compact_boundary`. Huecos: 1→10 (9 s), 10→311 (301 s, caducidad), 311→610 (299 s, no).
    N = 3, caducidades = 1."""
    claude = tmp_path / "claude"
    escribir(
        subagente(claude, "a1"),
        [
            peticion(0, "m0", tool_use=("toolu_n", "local_summarize", "docs/a.md")),
            resultado(1, "toolu_n"),
            peticion(10, "m1"),
            peticion(11, "m1"),  # el mismo message.id en otra línea (otro bloque de contenido)
            sintetica(20, "s1"),
            peticion(311, "m2"),
            peticion(610, "m3"),
            compactacion(700),
            peticion(800, "m4"),
        ],
    )
    indice = transcripts.leer(claude / "projects")
    d = indice.delegaciones["toolu_n"]
    assert d.kind == "subagent"
    n, caducidades = transcripts.n_y_caducidades(indice, d)
    N_CONOCIDO = 3
    assert n == N_CONOCIDO
    assert caducidades == 1


def test_el_ttl_depende_del_hilo(tmp_path):
    """En el principal el TTL es de 3 600 s: un hueco de 3 599 s no es caducidad."""
    claude = tmp_path / "claude"
    escribir(
        principal(claude),
        [
            peticion(0, "m0", tool_use=("toolu_t", "local_summarize", "docs/a.md")),
            resultado(1, "toolu_t"),
            peticion(3600, "m1"),
        ],
    )
    indice = transcripts.leer(claude / "projects")
    d = indice.delegaciones["toolu_t"]
    assert d.kind == "main"
    n, caducidades = transcripts.n_y_caducidades(indice, d)
    assert n == 1
    assert caducidades == 0


def test_percentil_par():
    assert transcripts.mediana([1, 2, 3, 4]) == 2.5
    assert transcripts.mediana([3, 1, 2]) == 2
    assert transcripts.percentil([10, 20, 30, 40, 50], 0.25) == 20
    assert transcripts.mediana([]) is None


# --- Cruce (REQ-004) ------------------------------------------------------------------------


def _dos_subagentes(claude: Path, path_a: str, path_b: str) -> None:
    """Dos subagentes llaman a la vez a `local_summarize`: A deja 2 peticiones después de su
    resultado y B, 5; así la `n` de la entrada dice con cuál casó cada línea."""
    escribir(
        subagente(claude, "A"),
        [
            peticion(0, "a0", tool_use=("toolu_a", "local_summarize", path_a)),
            resultado(5, "toolu_a"),
            peticion(6, "a1"),
            peticion(7, "a2"),
        ],
    )
    escribir(
        subagente(claude, "B"),
        [
            peticion(1, "b0", tool_use=("toolu_b", "local_summarize", path_b)),
            resultado(6, "toolu_b"),
        ]
        + [peticion(7 + i, f"b{i + 1}") for i in range(5)],
    )


def test_cruce_exacto_ventana_y_path(tmp_path):
    claude = tmp_path / "claude"
    _dos_subagentes(claude, "docs/a.md", "docs/b.md")
    escribir(
        principal(claude),
        [
            peticion(100, "c0", tool_use=("toolu_c", "local_extract", None)),
            resultado(103, "toolu_c"),
        ],
    )
    filas = [
        linea_log(4, path="docs/a.md"),
        linea_log(4, path="docs/b.md"),
        linea_log(4, tool_use_id="toolu_a"),
        linea_log(102, tool="local_extract"),
    ]
    e = casar_todo(claude, filas)
    assert [x["cruce"] for x in e] == ["ventana+path", "ventana+path", "exacto", "ventana"]
    assert [e[0]["n"], e[1]["n"], e[2]["n"]] == [2, 5, 2]
    assert e[0]["caller_model"] == OPUS
    assert e[0]["caller_kind"] == "subagent"
    assert e[0]["caller_effort"] == "high"
    assert e[3]["caller_kind"] == "main"

    # Con los dos `path` iguales no hay desempate posible: las dos, ambiguas.
    otro = tmp_path / "otro"
    _dos_subagentes(otro, "docs/a.md", "docs/a.md")
    cruces = [x["cruce"] for x in casar_todo(otro, filas[:2])]
    assert cruces == ["ambiguo", "ambiguo"]


def test_el_relleno_usa_el_plazo_leido(tmp_path):
    """Con `cleanupPeriodDays: 90`, una línea de hace 45 días con su transcript se rellena."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 90}), encoding="utf-8")
    escribir(
        principal(claude),
        [
            peticion(0, "m0", tool_use=("toolu_p", "local_summarize", "docs/a.md")),
            resultado(2, "toolu_p"),
        ],
    )
    escribir_log(log, [linea_log(1, tool_use_id="toolu_p")])
    recalcular.ejecutar(claude, log, ahora=BASE + timedelta(days=45))
    entradas = atribucion.leer_relleno(log, "202610")
    clave = "toolu_p"
    assert clave in entradas
    assert entradas[clave]["cruce"] == "exacto"


def test_sin_cruce_y_banco(tmp_path):
    claude = tmp_path / "claude"
    escribir(
        principal(claude, proyecto="C--Users-x-AppData-Local-Temp-banco"),
        [
            peticion(0, "m0", tool_use=("toolu_banco", "local_summarize", "x.md")),
            resultado(1, "toolu_banco"),
        ],
    )
    filas = [
        linea_log(1, tool_use_id="toolu_banco"),
        linea_log(1, tool_use_id="toolu_no_esta"),
        linea_log(5000, tool="local_translate"),
    ]
    e_banco, e_id, e = casar_todo(claude, filas)
    assert e_banco["banco"] is True
    assert e_banco["cruce"] == "exacto"
    assert e_id["cruce"] == "sin_cruce"
    assert e["cruce"] == "sin_cruce"


# --- cost-state (REQ-014) -------------------------------------------------------------------


def _cost_state(coste: float) -> dict:
    uso = {
        "inputTokens": 10,
        "cacheCreationInputTokens": 0,
        "cacheReadInputTokens": 0,
        "outputTokens": 0,
        "webSearchRequests": 0,
        "costUSD": coste,
    }
    return {
        "type": "cost-state",
        "sessionId": SESION,
        "startTime": ts(0),
        "modelUsage": {OPUS: uso},
    }


def test_cost_state_toma_la_ultima_por_posicion(tmp_path):
    claude = tmp_path / "claude"
    PRIMERO, ULTIMO = 1.0, 2.5
    escribir(principal(claude), [_cost_state(PRIMERO), _cost_state(ULTIMO)])
    filas = transcripts.cost_state(transcripts.leer(claude / "projects"))
    assert len(filas) == 1
    fila = filas[0]
    assert fila["modelo"] == OPUS
    assert fila["costUSD"] == ULTIMO
    assert SESION not in json.dumps(filas)
