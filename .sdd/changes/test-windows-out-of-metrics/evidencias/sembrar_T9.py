"""Siembra las ventanas de prueba conocidas en el `LOG_DIR` de ESTA PC (REQ-023, D5).

No va en el paquete: esas fechas solo valen en la PC (en la Mac taparían trabajo real). Usa el
mismo camino que el usuario, `local-delegate test-window add`, así que repetirla no duplica nada.

    uv run python .sdd/changes/test-windows-out-of-metrics/evidencias/sembrar_T9.py

Antes, copia de seguridad de `LOG_DIR/test-windows.json` si existe.
"""

from __future__ import annotations

import json
from pathlib import Path

from local_delegate import cli, config

RAIZ = Path(__file__).resolve().parents[4]

CONOCIDAS = [
    (
        "2026-10-08T01:20:05.255Z",
        "2026-10-08T01:22:31.544Z",
        "daemon-reparte-el-backend ola 11 paso 5",
    ),
    (
        "2026-10-08T01:24:10.521Z",
        "2026-10-08T01:24:39.452Z",
        "daemon-reparte-el-backend ola 11 paso 7",
    ),
    ("2026-09-15T19:31:14Z", "2026-09-15T19:35:14Z", "P-4 fallo provocado"),
]


def ventanas() -> list[tuple[str, str, str]]:
    datos = json.loads((RAIZ / "benchmarks" / "ventanas-excluidas.json").read_text("utf-8"))
    todas = list(CONOCIDAS)
    todas += [(t["inicio"], t["fin"], f"tanda {t['tanda']}") for t in datos["ventanas"]]
    # La etiqueta es el motivo, sin el `session_id`: el fichero no guarda ids de sesión.
    todas += [(s["inicio"], s["fin"], f"sesión: {s['motivo']}") for s in datos["sesiones"]]
    return todas


def main() -> int:
    print(f"LOG_DIR: {config.LOG_DIR}")
    fallos = 0
    for inicio, fin, etiqueta in ventanas():
        fallos += cli.run(["test-window", "add", inicio, fin, "--label", etiqueta]) != 0
    print(f"{len(ventanas())} ventanas pedidas, {fallos} con error")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
