"""Envoltorio de `scripts/measure_cooldown.py` con el nombre y las opciones de antes (REQ-046).

La medición P-4 está abierta hasta ~2026-12-14 y su comando está escrito así en los procedimientos de
los SDD cerrados (`delegacion-precisa-y-fiable` y `daemon-reparte-el-backend`):

    uv run python scripts/medir_enfriamiento.py --desde 2026-09-15T19:26:41

Este fichero lo mantiene funcionando sin cambios: traduce `--desde`, `--hasta` y `--excluir` a
`--since`, `--until` y `--exclude`, deja pasar el resto (`--tmax`, `--json`, `--include-tests` y las
opciones nuevas) y llama a `measure_cooldown.main()`. Se retira tras la medición de P-4 de los
90 días (entrada en el backlog del proyecto).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

#: Opción vieja → opción nueva de `measure_cooldown.py`.
OLD_OPTIONS = {"--desde": "--since", "--hasta": "--until", "--excluir": "--exclude"}


def translate(argv: list[str]) -> list[str]:
    """Las opciones viejas, también en la forma `--desde=VALOR`, pasan a su nombre nuevo."""
    out = []
    for arg in argv:
        name, sep, value = arg.partition("=")
        out.append(OLD_OPTIONS[name] + sep + value if name in OLD_OPTIONS else arg)
    return out


def _measure_cooldown():
    path = Path(__file__).with_name("measure_cooldown.py")
    spec = importlib.util.spec_from_file_location("measure_cooldown", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_cooldown"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    sys.argv = [sys.argv[0], *translate(sys.argv[1:])]
    return _measure_cooldown().main()


if __name__ == "__main__":
    sys.exit(main())
