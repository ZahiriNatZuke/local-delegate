#!/usr/bin/env python3
"""Lo que el CI comprueba de lo generado, antes del commit (SDD ci-root-cause, REQ-008).

Entre el 2026-11-03 y el 2026-11-23, 17 corridas salieron rojas por cosas que se ven sin CI: las
huellas de los hooks sin regenerar (`bump_version.py --boundaries`), la captura del README con la
versión anterior, un nombre nuevo sin clasificar en el léxico del detector de nombres en español
o un texto para personas fuera del catálogo. Este script las mira en local; lo engancha
`.pre-commit-config.yaml`, así que fallan al hacer el commit y no diez minutos después del push.

Uso:

    uv run python scripts/check_local.py          # comprueba; sale 1 si algo está viejo
    uv run python scripts/check_local.py --fix    # además regenera lo que se puede sin navegador

`--fix` solo une las huellas de los hooks (nunca quita ninguna). La captura necesita Playwright y la
regenera `bump_version.py <versión>`; el léxico y el catálogo los decide una persona.

Las comprobaciones de nombres y catálogo **son los mismos tests** que corre el CI: aquí se lanzan con
pytest para que no haya dos versiones de la regla.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Los manifiestos de las dos capturas del README (los escribe `scripts/dev/capture_dashboard.py`).
CAPTURE_MANIFESTS = (
    Path("docs") / "assets" / "dashboard.json",
    Path("docs") / "assets" / "dashboard-light.json",
)
#: Los tests del CI que deciden nombres y catálogo, tal cual.
NAME_AND_CATALOG_TESTS = (
    "tests/test_detect_spanish_names.py::test_repo_has_no_spanish_name_outside_the_exception_list",
    "tests/test_no_uncatalogued_text.py::test_no_uncatalogued_text_outside_pending",
    "tests/test_no_uncatalogued_text.py::test_text_exceptions_are_live_and_machine_text",
)
CAPTURE_REMEDY = (
    "la captura la regenera `uv run python scripts/bump_version.py <versión>` (necesita "
    "Playwright), o a mano con los pasos de `tests/test_capture.py`"
)
BOUNDARIES_REMEDY = "uv run python scripts/bump_version.py --boundaries (o este script con --fix)"


def _bump_version(root: Path):
    spec = importlib.util.spec_from_file_location(
        "_check_local_bump_version", root / "scripts" / "bump_version.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def declared_version(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]


def stale_boundaries(root: Path = ROOT) -> dict[str, str]:
    """Los hooks cuya huella de hoy no está en el conjunto «después»: {hook: huella}."""
    bump = _bump_version(root)
    path = root / bump.HOOK_HASHES_FILE
    after = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {
        name: digest
        for name, digest in bump.current_hook_hashes(root).items()
        if digest not in set(after.get(name, []))
    }


def stale_captures(root: Path = ROOT, version: str | None = None) -> dict[str, str]:
    """Los manifiestos de captura que no dicen la versión del proyecto: {fichero: su versión}."""
    version = version or declared_version(root)
    stale = {}
    for rel in CAPTURE_MANIFESTS:
        path = root / rel
        found = (
            json.loads(path.read_text(encoding="utf-8")).get("version") if path.is_file() else None
        )
        if found != version:
            stale[rel.as_posix()] = found or "falta"
    return stale


def names_and_catalog(root: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *NAME_AND_CATALOG_TESTS],
        cwd=root,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def run_checks(root: Path = ROOT, *, fix: bool = False, names=names_and_catalog) -> list[str]:
    """Los problemas encontrados, cada uno con su remedio; vacía si todo está al día."""
    problems: list[str] = []

    stale = stale_boundaries(root)
    if stale and fix:
        _bump_version(root).update_boundaries(root)
        problems.append(
            "huellas de los hooks regeneradas para "
            + ", ".join(sorted(stale))
            + ": añade scripts/data/hook_hashes_after.json al commit"
        )
    elif stale:
        problems.append(
            f"huellas de los hooks sin regenerar ({', '.join(sorted(stale))}): {BOUNDARIES_REMEDY}"
        )

    version = declared_version(root)
    captures = stale_captures(root, version)
    if captures:
        detail = ", ".join(f"{name} dice {found}" for name, found in sorted(captures.items()))
        problems.append(f"la captura no es de la {version} ({detail}): {CAPTURE_REMEDY}")

    result = names(root)
    if result.returncode != 0:
        tail = "\n".join(result.stdout.strip().splitlines()[-25:])
        problems.append(
            "nombres en español o textos fuera del catálogo (los mismos tests del CI):\n" + tail
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fix", action="store_true", help="une las huellas de los hooks")
    args = parser.parse_args(argv)

    problems = run_checks(ROOT, fix=args.fix)
    if not problems:
        print("OK: huellas, captura, nombres y catálogo al día")
        return 0
    for problem in problems:
        print(f"- {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
