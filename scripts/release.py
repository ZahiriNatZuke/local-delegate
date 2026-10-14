"""Publica una versión: crea la GitHub Release y, con ella, el tag que dispara `publish.yml`.

Uso:

    uv run python scripts/release.py 0.12.3
    uv run python scripts/release.py 0.12.3 --dry-run

Por qué existe: el tag es el disparador de todo el release, pero crearlo a mano deja fuera dos
cosas que siempre había que recordar — adjuntar el wheel y el sdist, y crear la GitHub Release, que
`publish.yml` **no** crea—. Aquí va todo en un comando.

`gh release create` crea el tag con TU credencial, y por eso sí dispara `publish.yml`. Un tag
empujado por un workflow con el `GITHUB_TOKEN` no dispararía nada: GitHub lo bloquea para evitar
bucles entre workflows. De ahí que esto sea un script local y no una acción.

Las comprobaciones previas no son adorno: **PyPI es inmutable**. Publicar con la versión mal puesta
en `server.json` no se puede deshacer, solo se tapa con otra versión. Todas se hacen antes de tocar
nada remoto.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kw)


def _failure(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _declared_versions() -> dict[str, str]:
    """Los tres sitios que `check-version` de publish.yml compara contra el tag."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    return {
        "pyproject.toml": pyproject["project"]["version"],
        "server.json": server["version"],
        "server.json/packages[0]": server["packages"][0]["version"],
    }


def _changelog_notes(version: str) -> str:
    """Extrae la sección `## [X.Y.Z]` hasta la siguiente cabecera de versión."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    pattern = rf"^## \[{re.escape(version)}\].*?$(.*?)(?=^## \[)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not match:
        _failure(
            f"CHANGELOG.md no tiene una sección `## [{version}]`. "
            "El release se documenta antes de publicarse, no después."
        )
    return match.group(1).strip()


def _checks(version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        _failure(f"la versión '{version}' no tiene forma X.Y.Z")

    declared = _declared_versions()
    desalineadas = {k: v for k, v in declared.items() if v != version}
    if desalineadas:
        detail = ", ".join(f"{k}={v}" for k, v in desalineadas.items())
        _failure(
            f"hay archivos que no declaran {version}: {detail}\n"
            f"       Ejecuta antes:  uv run python scripts/bump_version.py {version}"
        )

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != "main":
        _failure(f"estás en la rama '{branch}'. El release sale de `main`.")

    # `main` está protegida: si local y remoto difieren, lo publicado no sería lo revisado.
    _run(["git", "fetch", "origin", "main"])
    local = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote = _run(["git", "rev-parse", "origin/main"]).stdout.strip()
    if local != remote:
        _failure("`main` local y `origin/main` no coinciden. Haz pull (o push) antes de publicar.")

    if _run(["git", "tag", "-l", f"v{version}"]).stdout.strip():
        _failure(f"el tag v{version} ya existe en local.")

    already_published = _run(["gh", "release", "view", f"v{version}", "--json", "tagName"])
    if already_published.returncode == 0:
        _failure(f"la release v{version} ya existe en GitHub.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea la GitHub Release y dispara la publicación.")
    parser.add_argument("version", help="versión a publicar, en formato X.Y.Z")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="comprueba todo y enseña el plan, sin crear nada",
    )
    args = parser.parse_args()
    version = args.version.lstrip("v")

    _checks(version)
    notes = _changelog_notes(version)

    print(f"Versión {version} coherente en los tres archivos, `main` al día, tag libre.")
    print(f"Notas tomadas del CHANGELOG ({len(notes.splitlines())} líneas).")

    if args.dry_run:
        print("\n--dry-run: no se crea nada. Se haría:")
        print("  1. uv build")
        print(f"  2. gh release create v{version} --target main (crea el tag)")
        print("  3. el tag dispara publish.yml -> PyPI -> registro MCP")
        return 0

    print("\nConstruyendo wheel y sdist...")
    build = _run(["uv", "build"], cwd=ROOT)
    if build.returncode != 0:
        _failure(f"`uv build` falló:\n{build.stderr}")

    artifacts = sorted(str(p) for p in (ROOT / "dist").glob(f"*{version}*"))
    if not artifacts:
        _failure(f"`uv build` no dejó artefactos de {version} en dist/")
    print(f"Artefactos: {', '.join(Path(a).name for a in artifacts)}")

    # Fichero temporal porque `gh` no lee las notas de stdin.
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(notes)
        notes_path = f.name

    try:
        create = _run(
            [
                "gh",
                "release",
                "create",
                f"v{version}",
                "--target",
                "main",
                "--title",
                f"v{version}",
                "--notes-file",
                notes_path,
                *artifacts,
            ],
            cwd=ROOT,
        )
    finally:
        Path(notes_path).unlink(missing_ok=True)

    if create.returncode != 0:
        _failure(f"`gh release create` falló:\n{create.stderr}")

    print(f"\nRelease creada: {create.stdout.strip()}")
    print("El tag ya disparó publish.yml (check-version -> pypi -> mcp-registry).")
    print(
        "Seguimiento:  gh run watch $(gh run list --workflow publish.yml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status"
    )
    print("\nOjo al verificar: PyPI sirve el índice con caché y puede anunciar la versión")
    print("anterior durante unos minutos. Si compruebas demasiado pronto, verás la vieja.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
