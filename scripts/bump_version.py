#!/usr/bin/env python3
"""Sube la versión del paquete en todos los sitios donde vive, de una sola vez.

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
    python scripts/bump_version.py --check           # ¿coinciden todos? (sale 1 si no)
    python scripts/bump_version.py --boundaries      # une las huellas de hoy de los hooks
    python scripts/bump_version.py 0.12.0 --boundaries  # las dos cosas, en el PR de release

`--check` es lo mismo que comprueba el CI, disponible en local antes del push.

Desde la 0.40 el plugin de Claude Code (SDD claude-plugin-and-mods, REQ-001) declara la misma versión
en tres sitios más: su `plugin.json` y la entrada de los dos `marketplace.json` (el del paquete y el
de la raíz del repo). Un plugin con la `version` vieja deja a los usuarios clavados en esa versión de
la caché, así que van en el mismo bump y en el mismo `--check`.

Al subir de versión también pone la versión en las entradas de `src/local_delegate/deprecations.py`
que aún dicen `UNRELEASED`: es la primera versión publicada con ese renombrado, y de ella sale el
horizonte de cada alias (REQ-004).
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
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

# El registro de nombres obsoletos: sus entradas nuevas llevan `introduced="UNRELEASED"` hasta que
# se publica la versión que las contiene, y es este script quien pone esa versión.
DEPRECATIONS_FILE = Path("src") / "local_delegate" / "deprecations.py"


#: Fronteras de la telemetría de hooks (REQ-041, plan D9): el conjunto «después» de huellas por
#: script. Lo referencia `scripts/data/measurement_boundaries.json`.
HOOK_HASHES_FILE = Path("scripts") / "data" / "hook_hashes_after.json"
HOOKS_DIR = Path("src") / "local_delegate" / "resources" / "hooks"
#: Los hooks que estampan su huella (`hook_common.context_of`) en cada evento de telemetría.
#: `tests/test_hook_boundaries.py` exige que sean exactamente los que llaman a `context_of`.
HASHED_HOOKS = (
    "suggest_delegate_prompt.py",
    "suggest_delegate_read.py",
    "suggest_delegate_shell.py",
)


#: El plugin de Claude Code (REQ-001): su manifiesto y los dos marketplaces que lo publican.
PLUGIN_ROOT = Path("src") / "local_delegate" / "resources" / "claude-plugin"
PLUGIN_MANIFEST = PLUGIN_ROOT / "local-delegate" / ".claude-plugin" / "plugin.json"
LOCAL_MARKETPLACE = PLUGIN_ROOT / ".claude-plugin" / "marketplace.json"
REPO_MARKETPLACE = Path(".claude-plugin") / "marketplace.json"
PLUGIN_VERSION_FILES = (PLUGIN_MANIFEST, LOCAL_MARKETPLACE, REPO_MARKETPLACE)


class BumpError(RuntimeError):
    """Algo no cuadra; el mensaje ya está redactado para el usuario."""


def _hook_common(root: Path):
    """`hook_common` cargado por ruta: su `version_de` es la huella que escribe cada evento."""
    spec = importlib.util.spec_from_file_location(
        "_bump_hook_common", root / HOOKS_DIR / "hook_common.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_hook_hashes(root: Path = ROOT) -> dict[str, str]:
    """La huella de hoy de cada hook de `HASHED_HOOKS`, calculada como la calcula el hook."""
    version_de = _hook_common(root).version_de
    return {name: version_de(str(root / HOOKS_DIR / name)) for name in HASHED_HOOKS}


def update_boundaries(root: Path = ROOT) -> dict[str, list[str]]:
    """**Une** las huellas de hoy al conjunto «después»; nunca quita ninguna (plan D9).

    Si una máquina se queda en la versión anterior, sus eventos llevan la huella vieja: sustituir
    el conjunto los devolvería al tramo «antes».
    """
    path = root / HOOK_HASHES_FILE
    data: dict[str, list[str]] = (
        json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    )
    for name, digest in current_hook_hashes(root).items():
        if not digest:
            raise BumpError(f"no se pudo leer {HOOKS_DIR.as_posix()}/{name}")
        data[name] = sorted(set(data.get(name, [])) | {digest})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(dict(sorted(data.items())), indent=2) + "\n").encode("utf-8"))
    return data


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

    for relative in plugin_version_files(root):
        for where, version in _plugin_versions(json.loads((root / relative).read_text("utf-8"))):
            versions[f"{relative.as_posix()} ({where})"] = version

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


def plugin_version_files(root: Path = ROOT) -> tuple[Path, ...]:
    """Los ficheros del plugin que declaran versión, o ninguno si el repo aún no tiene plugin.

    Todo o nada: si existe uno y falta otro, el bump se saltaría el que falta sin decir nada, y ese
    es justo el estado a medias que este script existe para evitar.
    """
    present = [relative for relative in PLUGIN_VERSION_FILES if (root / relative).exists()]
    if not present:
        return ()
    missing = [relative.as_posix() for relative in PLUGIN_VERSION_FILES if relative not in present]
    if missing:
        raise BumpError(f"faltan ficheros del plugin que declaran versión: {', '.join(missing)}")
    return PLUGIN_VERSION_FILES


def _plugin_versions(data: dict) -> list[tuple[str, str]]:
    """(dónde, versión) de un `plugin.json` (`version`) o un `marketplace.json` (`plugins[i]`)."""
    if "plugins" in data:
        return [(f"plugins[{i}].version", p["version"]) for i, p in enumerate(data["plugins"])]
    return [("version", data["version"])]


def _set_plugin_versions(data: dict, new_version: str) -> None:
    if "plugins" in data:
        for plugin in data["plugins"]:
            plugin["version"] = new_version
    else:
        data["version"] = new_version


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

    for relative in plugin_version_files(root):
        path = root / relative
        text, newline = _read(path)
        expected = len(_plugin_versions(json.loads(text)))
        new_text, count = SERVER_VERSION_RE.subn(rf"\g<1>{new_version}\g<3>", text)
        if count != expected:
            raise BumpError(
                f"{relative.as_posix()} tiene {count} claves 'version' y se esperaban {expected}"
            )
        _verify_plugin_json(relative, text, new_text, new_version)
        changes[path] = (new_text, newline)

    deprecations_path = root / DEPRECATIONS_FILE
    if deprecations_path.exists():
        text, newline = _read(deprecations_path)
        new_text = stamp_unreleased(text, new_version)
        if new_text != text:
            changes[deprecations_path] = (new_text, newline)

    return changes


def stamp_unreleased(text: str, new_version: str) -> str:
    """Cambia cada `"UNRELEASED"` de las entradas de `DEPRECATED_NAMES` por la versión publicada.

    Solo dentro de la tupla del registro: la constante `UNRELEASED` y los comentarios que la citan
    se quedan como están. La versión que se publica es la primera que contiene el renombrado, que
    es lo que el horizonte de los alias necesita saber (REQ-004).

    Localiza la tupla con `ast`, no buscando su cierre en el texto: así da igual cómo esté escrita
    (`= ()` en una línea, `= (\\n)`, una entrada por línea o repartida en varias) y solo se tocan
    las cadenas `"UNRELEASED"` que son valores dentro de ella (REQ-020 de retire-legacy-aliases).
    Sin nada que sellar devuelve el texto tal cual.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise BumpError(f"{DEPRECATIONS_FILE} no se puede analizar: {exc}") from exc
    registry = next(
        (
            node.value
            for node in tree.body
            if isinstance(node, ast.AnnAssign | ast.Assign)
            and node.value is not None
            and any(
                isinstance(target, ast.Name) and target.id == "DEPRECATED_NAMES"
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            )
        ),
        None,
    )
    if registry is None:
        raise BumpError(f"{DEPRECATIONS_FILE} no declara DEPRECATED_NAMES")
    stamps = [
        node
        for node in ast.walk(registry)
        if isinstance(node, ast.Constant) and node.value == "UNRELEASED"
    ]
    lines = text.splitlines(keepends=True)
    # `ast` da las columnas en bytes UTF-8; se pasan a caracteres para cortar el texto.
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def position(line_number: int, col: int) -> int:
        return starts[line_number - 1] + len(
            lines[line_number - 1].encode("utf-8")[:col].decode("utf-8")
        )

    for node in sorted(stamps, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        begin = position(node.lineno, node.col_offset)
        end = position(node.end_lineno, node.end_col_offset)
        text = text[:begin] + f'"{new_version}"' + text[end:]
    return text


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


def _verify_plugin_json(relative: Path, before: str, after: str, new_version: str) -> None:
    """Como `_verify_server_json`: solo cambian las versiones del plugin."""
    old = json.loads(before)
    new = json.loads(after)
    if any(version != new_version for _, version in _plugin_versions(new)):
        raise BumpError(f"{relative.as_posix()} no quedó con la versión pedida")
    _set_plugin_versions(old, new_version)
    if old != new:
        raise BumpError(f"la edición de {relative.as_posix()} cambió algo más que la versión")


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
        help="solo verifica que todos los sitios coincidan (no escribe)",
    )
    parser.add_argument("--dry-run", action="store_true", help="enseña el plan sin escribir")
    parser.add_argument("--no-lock", action="store_true", help="no regenerar uv.lock")
    parser.add_argument(
        "--boundaries",
        action="store_true",
        help=f"une la huella de hoy de cada hook a {HOOK_HASHES_FILE.as_posix()} (nunca quita)",
    )
    args = parser.parse_args(argv)

    # Este script se ejecuta en Windows justo antes de publicar, y ahí la consola suele ser
    # cp1252: el `→` de más abajo la revienta con UnicodeEncodeError y aborta el bump. Falla
    # imprimiendo, no escribiendo —los archivos se tocan después—, pero un release que se cae
    # con un traceback de codificación invita a hacer el bump a mano, que es exactamente lo que
    # este script existe para evitar.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        if args.check:
            if args.version:
                parser.error("--check no lleva versión: comprueba la que ya está declarada")
            print(f"OK: todos los archivos declaran {check()}")
            return 0

        if args.boundaries and not args.dry_run:
            data = update_boundaries(ROOT)
            total = sum(len(v) for v in data.values())
            print(f"OK: {HOOK_HASHES_FILE.as_posix()} con {total} huellas de {len(data)} hooks")
            if not args.version:
                return 0

        if not args.version:
            parser.error("falta la versión nueva (o usa --check o --boundaries)")

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
