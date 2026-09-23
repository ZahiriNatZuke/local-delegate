"""Tests de `scripts/sesiones_de_prueba.py` (SDD subagente-lector-local, tarea 0)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RAIZ = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location(
    "sesiones_de_prueba", RAIZ / "scripts" / "sesiones_de_prueba.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _transcript(dir_: Path, nombre: str, eventos: list[dict]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{nombre}.jsonl").write_text(
        "\n".join(json.dumps(e) for e in eventos) + "\n", encoding="utf-8"
    )


def test_solo_cuenta_sesiones_sdk_del_dia_pedido(tmp_path):
    p = tmp_path / "projects" / "D--x"
    _transcript(
        p,
        "a",
        [
            {"entrypoint": "sdk-cli", "sessionId": "a", "timestamp": "2026-09-22T10:00:00Z"},
            {"entrypoint": "sdk-cli", "sessionId": "a", "timestamp": "2026-09-22T10:05:00Z"},
        ],
    )
    # Control: interactiva el mismo día y sdk de otro día. Si el filtro no discriminara, entrarían.
    _transcript(p, "b", [{"entrypoint": "cli", "sessionId": "b", "timestamp": "2026-09-22T11:00Z"}])
    _transcript(
        p, "c", [{"entrypoint": "sdk-cli", "sessionId": "c", "timestamp": "2026-09-21T09:00Z"}]
    )

    sesiones = mod.sesiones_sdk(tmp_path / "projects", "2026-09-22")

    assert [s["session_id"] for s in sesiones] == ["a"]
    assert sesiones[0]["inicio"] == "2026-09-22T10:00:00Z"
    assert sesiones[0]["fin"] == "2026-09-22T10:05:00Z"


def test_fusionar_no_duplica_y_conserva_lo_que_habia(tmp_path):
    salida = tmp_path / "v.json"
    salida.write_text(
        json.dumps({"sesiones": [{"session_id": "a"}], "ventanas": [{"inicio": "x", "fin": "y"}]}),
        encoding="utf-8",
    )
    datos = mod.fusionar(salida, [{"session_id": "a"}, {"session_id": "z"}], "prueba")
    assert [s["session_id"] for s in datos["sesiones"]] == ["a", "z"]
    assert datos["ventanas"] == [{"inicio": "x", "fin": "y"}]


def test_la_salida_no_guarda_rutas(tmp_path):
    p = tmp_path / "projects" / "D--x"
    _transcript(
        p,
        "a",
        [
            {
                "entrypoint": "sdk-cli",
                "sessionId": "a",
                "timestamp": "2026-09-22T10:00:00Z",
                "cwd": "C:\\secreto\\ruta",
            }
        ],
    )
    salida = tmp_path / "v.json"
    mod.main(
        ["--dia", "2026-09-22", "--proyectos", str(tmp_path / "projects"), "--salida", str(salida)]
    )
    assert "secreto" not in salida.read_text(encoding="utf-8")
