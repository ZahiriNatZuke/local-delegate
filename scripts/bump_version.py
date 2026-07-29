#!/usr/bin/env python3
"""Sube la versión del paquete en los CUATRO sitios donde vive, de una sola vez.

La versión está duplicada por razones ajenas a este repo: `pyproject.toml` es la fuente para
el build, `server.json` la declara **dos veces** (el descriptor del registro MCP y el paquete
PyPI al que apunta) y `uv.lock` la fija como paquete editable. Bumpear a mano significa acertar
cuatro veces seguidas, y el histórico dice que no se acierta: en la 0.8.1 el lock se quedó en
0.7.0 y hubo que arreglarlo después de publicar.

Los guardarraíles existentes solo *detectan* el olvido: `tests/test_release_metadata.py` en cada
PR y el job `check-version` antes de publicar. Este script lo *evita*, que es más barato — y sale
gratis en superficie de seguridad, a diferencia de automatizar el tag desde el CI.

Uso:
    python scripts/bump_version.py 0.12.0            # aplica y regenera uv.lock
    python scripts/bump_version.py 0.12.0 --dry-run  # enseña el plan sin tocar nada
    python scripts/bump_version.py --check           # ¿coinciden los cuatro? (sale 1 si no)

`--check` es lo mismo que comprueba el CI, disponible en local antes del push.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]

# SemVer, más los pre-releases que PyPI y el registro MCP normalizan igual. Se restringe a
# propósito: `1.0` o `1.0.0-rc1` los aceptaría PyPI pero llegan al registro con otra forma, y
# entonces el descriptor publicado no coincide con el paquete.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")

# La versión de `[project]`, acotada a esa sección: `(?:(?!^\[).)*?` impide que el patrón se
# cuele en una tabla posterior si algún día `[project]` dejara de declarar `version`.
# El grupo 1 arrastra todo el prefijo (desde `[project]` hasta el `version = "`) porque `re` no
# admite lookbehind de longitud variable: sin capturarlo, la sustitución se lo comería.
PYPROJECT_VERSION_RE = re.compile(
    r'(?ms)^(\[project\]$(?:(?!^\[).)*?^version\s*=\s*")([^"]+)(")',
)

# Las dos versiones de server.json. Se edita el texto en vez de reserializar el JSON para no
# reformatear el resto del archivo (`json.dump` expandiría las tablas inline y ensuciaría el
# diff); la coherencia del resultado se comprueba después parseándolo.
SERVER_VERSION_RE = re.compile(r'("version"\s*:\s*")([^"]+)(")')


class BumpError(RuntimeError):
    """Algo no cuadra; el mensaje ya está redactado para el usuario."""


def _read(path: Path) -> tuple[str, str]:
    """Devuelve (texto con LF, terminador original) para poder reescribir sin cambiar el EOL.

    Escribir con `write_text` en Windows convertiría todo el archivo a CRLF y el diff saldría
    entero en rojo, tapando el único cambio real.
    """
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), ("\r\n" if "\r\n" in raw else "\n")


def _write(path: Path, text: str, newline: str) -> None:
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def read_versions(root: Path = ROOT) -> dict[str, str]:
    """Lee la versión declarada en cada sitio. Las claves son etiquetas para los mensajes."""
    with (root / "pyproject.toml").open("rb") as f:
        pyproject = tomllib.load(f)
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))

    versions = {
        "pyproject.toml": pyproject["project"]["version"],
        "server.json (version)": server["version"],
    }
    for i, package in enumerate(server["packages"]):
        versions[f"server.json (packages[{i}].version)"] = package["version"]

    lock = root / "uv.lock"
    if lock.exists():
        name = pyproject["project"]["name"]
        # El lock declara cada paquete como `name = "..."` seguido de `version = "..."`; solo
        # interesa el bloque del propio proyecto, no el de las dependencias.
        match = re.search(
            rf'(?m)^name = "{re.escape(name)}"\nversion = "([^"]+)"',
            lock.read_text(encoding="utf-8"),
        )
        if match:
            versions["uv.lock"] = match.group(1)

    return versions


def check(root: Path = ROOT) -> str:
    """Verifica que todos los sitios digan lo mismo. Devuelve la versión común o levanta."""
    versions = read_versions(root)
    distinct = set(versions.values())
    if len(distinct) != 1:
        detail = "\n".join(f"  {where}: {version}" for where, version in versions.items())
        raise BumpError(f"las versiones no coinciden:\n{detail}")
    return distinct.pop()


def plan(new_version: str, root: Path = ROOT) -> dict[Path, tuple[str, str]]:
    """Calcula el contenido nuevo de cada archivo sin escribir nada.

    Se valida todo antes de tocar disco para que un fallo a mitad no deje el repo con dos
    archivos bumpeados y dos sin bumpear — que es exactamente el estado que este script existe
    para evitar.
    """
    if not VERSION_RE.match(new_version):
        raise BumpError(
            f"'{new_version}' no es una versión válida; se espera X.Y.Z con un sufijo "
            "opcional aN/bN/rcN (ej.: 0.12.0, 1.0.0rc1)"
        )

    changes: dict[Path, tuple[str, str]] = {}

    pyproject_path = root / "pyproject.toml"
    text, newline = _read(pyproject_path)
    new_text, count = PYPROJECT_VERSION_RE.subn(rf"\g<1>{new_version}\g<3>", text, count=1)
    if count != 1:
        raise BumpError("no se encontró 'version' dentro de [project] en pyproject.toml")
    _verify_pyproject(text, new_text, new_version)
    changes[pyproject_path] = (new_text, newline)

    server_path = root / "server.json"
    text, newline = _read(server_path)
    new_text, count = SERVER_VERSION_RE.subn(rf"\g<1>{new_version}\g<3>", text)
    if count < 2:
        raise BumpError(
            f"server.json declaraba {count} versión(es) y se esperaban al menos 2 "
            "(la del descriptor y la del paquete PyPI)"
        )
    _verify_server_json(text, new_text, new_version)
    changes[server_path] = (new_text, newline)

    return changes


def _verify_pyproject(before: str, after: str, new_version: str) -> None:
    """Parsea el resultado y comprueba que solo cambió la versión."""
    old = tomllib.loads(before)
    new = tomllib.loads(after)
    if new["project"]["version"] != new_version:
        raise BumpError("pyproject.toml no quedó con la versión pedida")
    old["project"]["version"] = new_version
    if old != new:
        raise BumpError("la edición de pyproject.toml cambió algo más que la versión")


def _verify_server_json(before: str, after: str, new_version: str) -> None:
    """Igual que el anterior: el JSON resultante debe ser idéntico salvo en las versiones."""
    old = json.loads(before)
    new = json.loads(after)
    if new["version"] != new_version or any(p["version"] != new_version for p in new["packages"]):
        raise BumpError("server.json no quedó con la versión pedida en los dos sitios")
    old["version"] = new_version
    for package in old["packages"]:
        package["version"] = new_version
    if old != new:
        raise BumpError("la edición de server.json cambió algo más que las versiones")


def relock(root: Path = ROOT) -> None:
    """Regenera uv.lock. El CI corre `uv lock --check`, así que saltarlo rompe el push."""
    uv = shutil.which("uv")
    if uv is None:
        raise BumpError(
            "no se encontró 'uv' en el PATH; los archivos ya están bumpeados, "
            "queda correr `uv lock` a mano"
        )
    result = subprocess.run([uv, "lock"], cwd=root)
    if result.returncode != 0:
        raise BumpError("`uv lock` falló; revisa su salida")


def warn_if_changelog_missing(new_version: str, root: Path = ROOT) -> None:
    """Aviso, no error: es válido bumpear antes de redactar la entrada del CHANGELOG."""
    changelog = root / "CHANGELOG.md"
    if changelog.exists() and f"## [{new_version}]" not in changelog.read_text(encoding="utf-8"):
        print(
            f"aviso: CHANGELOG.md no tiene una sección '## [{new_version}]' todavía",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("version", nargs="?", help="versión nueva, ej. 0.12.0")
    parser.add_argument(
        "--check",
        action="store_true",
        help="solo verifica que los cuatro sitios coincidan (no escribe)",
    )
    parser.add_argument("--dry-run", action="store_true", help="enseña el plan sin escribir")
    parser.add_argument("--no-lock", action="store_true", help="no regenerar uv.lock")
    args = parser.parse_args(argv)

    # Este script se ejecuta en Windows justo antes de publicar, y ahí la consola suele ser
    # cp1252: el `→` de más abajo la revienta con UnicodeEncodeError y aborta el bump. Falla
    # imprimiendo, no escribiendo —los archivos se tocan después—, pero un release que se cae
    # con un traceback de codificación invita a hacer el bump a mano, que es exactamente lo que
    # este script existe para evitar.
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")

    try:
        if args.check:
            if args.version:
                parser.error("--check no lleva versión: comprueba la que ya está declarada")
            print(f"OK: todos los archivos declaran {check()}")
            return 0

        if not args.version:
            parser.error("falta la versión nueva (o usa --check)")

        current = read_versions()
        changes = plan(args.version)

        for path, (new_text, _) in changes.items():
            old_text, _ = _read(path)
            marker = "=" if old_text == new_text else "→"
            print(f"{path.relative_to(ROOT).as_posix()} {marker} {args.version}")

        if args.dry_run:
            print(f"(dry-run) versiones actuales: {sorted(set(current.values()))}")
            print("(dry-run) uv.lock se regeneraría con `uv lock`")
            return 0

        for path, (new_text, newline) in changes.items():
            _write(path, new_text, newline)

        if not args.no_lock:
            relock()

        warn_if_changelog_missing(args.version)
        print(f"OK: versión {check()} en todos los archivos")
    except BumpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
