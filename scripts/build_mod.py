"""Builds ``register.js``, the hooks module of the local-delegate mod, from its pieces in ``mod/``.

SDD claude-plugin-and-mods, decision 7 (batch F2-mod-core). T0 measured that the engine refuses a
module holding a dynamic import, and that with static ``import`` declarations a piece that is
missing or throws while loading takes the whole mod down. So this script writes a ``register.js``
that imports, with static ``import`` declarations, ``mod/common.js`` and only the pieces present at
build time, and registers each piece inside its own ``try``:

- a piece that is **absent** when the module is built (a later batch has not landed yet) is
  recorded as ``absent`` and the rest load;
- a piece that **throws while registering** is ``failed`` and the rest load;
- a piece whose **switch** in ``userConfig`` is off (``false``, or an empty list) is ``off``.

Each piece (``mod/<name>.js``) is a plain ES module that exports ``register(on, options)``, which
returns nothing, and imports by name only from ``./common.js``. The engine's validator (measured in
this batch) hands ``on`` and ``$`` only to functions declared or imported by name at the top of a
file, never to a method or a closure, and refuses using the value of a call that received ``on``:
that rules out pasting the pieces into closures and a ``common`` object. A piece only declares at
its top level (``check_piece``), so importing it cannot throw. A piece that acts when the session
starts exports ``async function onSessionStart($, e)``: the engine refuses two ``session.start``
hooks without a matcher in one module, so ``register.js`` holds the only one and calls it there. The texts of ``mod/i18n/<lang>.json`` and the
plugin's version are embedded, so ``common.t`` needs no file read.

``register.js`` is generated and not committed: the CI and the packaging run this script before
validating, testing or building the wheel.

Usage::

    uv run python scripts/build_mod.py            # writes <plugin>/register.js
    uv run python scripts/build_mod.py --check    # exit 1 if it is missing or stale
    uv run python scripts/build_mod.py --plugin-dir <folder> [--output <file>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "src" / "local_delegate" / "resources" / "claude-plugin" / "local-delegate"
OUTPUT_NAME = "register.js"

#: Every piece of the mod, in load order, with its ``userConfig`` switch (REQ-016: each piece can
#: be turned off). ``pinned_tools`` is a list: empty turns it off. The others are booleans.
PIECES: tuple[tuple[str, str], ...] = (
    ("pinned-tools", "pinned_tools"),
    ("commands", "commands_enabled"),
    ("status", "status_enabled"),
    ("read", "read_mod_enabled"),
)

COMMON = "common"
LANGUAGES = ("es", "en")

_IMPORT_DECLARATION = re.compile(r"^\s*import\b.*$", re.MULTILINE)
#: The one import a piece may hold: names from ``./common.js``.
_COMMON_IMPORT = re.compile(r"^import \{[\w\s,$]+\} from '\./common\.js'$")
_DYNAMIC_IMPORT = re.compile(r"\bimport\s*\(")
_REGISTER_EXPORT = re.compile(r"^export\s+function\s+register\s*\(", re.MULTILINE)
_START_EXPORT = re.compile(r"^export\s+async\s+function\s+onSessionStart\s*\(", re.MULTILINE)
#: The engine refuses two ``session.start`` hooks without a matcher in one module (measured):
#: ``register.js`` holds the only one and calls each piece's ``onSessionStart($, e)``.
_SESSION_START_HOOK = re.compile(r"\bon\(\s*['\"]session\.start['\"]")
#: What a piece may start a top-level line with: declarations only, so loading it cannot throw.
_TOP_LEVEL = re.compile(
    r"^(?:export\s+)?(?:async\s+function\b|function\b|const\s+[A-Za-z_$][\w$]*\s*=)"
)


class BuildError(Exception):
    """A piece that cannot be loaded safely: the build stops instead of shipping a broken module."""


def check_piece(name: str, source: str, *, needs_register: bool = True) -> None:
    """Refuses a piece that imports, has no ``register`` or runs code while loading.

    A static ``import`` of a piece is safe only if loading it cannot throw (T0: a throw at load
    takes the whole mod down). So a piece's top level holds only ``function`` declarations and
    ``const`` bindings, and its code runs when ``register`` is called, inside its ``try``.
    """
    if _DYNAMIC_IMPORT.search(source):
        raise BuildError(f"mod/{name}.js holds a dynamic import: the engine refuses it (T0)")
    for found in _IMPORT_DECLARATION.finditer(source):
        statement = found.group(0).strip()
        if name == COMMON or not _COMMON_IMPORT.match(statement):
            raise BuildError(
                f"mod/{name}.js: `{statement}`; a piece imports only from './common.js'"
            )
    if needs_register and not _REGISTER_EXPORT.search(source):
        raise BuildError(f"mod/{name}.js does not export `function register(on, options)`")
    if _SESSION_START_HOOK.search(source):
        raise BuildError(
            f"mod/{name}.js hooks `session.start`: export `async function onSessionStart($, e)` "
            "instead (one such hook per module)"
        )
    for number, line in enumerate(source.splitlines(), 1):
        if not line or line[0] in " \t}/*)]" or line.startswith("//") or _COMMON_IMPORT.match(line):
            continue
        if not _TOP_LEVEL.match(line):
            raise BuildError(
                f"mod/{name}.js:{number}: only `function` and `const` at the top level "
                "(loading a piece must not run code)"
            )


def _catalogs(mod_dir: Path) -> dict[str, dict[str, str]]:
    catalogs: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        path = mod_dir / "i18n" / f"{lang}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise BuildError(f"{path}: a catalog is a JSON object")
            catalogs[lang] = data
    return catalogs


def _version(plugin_dir: Path) -> str | None:
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return None
    return json.loads(manifest.read_text(encoding="utf-8")).get("version")


def _binding(name: str, prefix: str = "register_") -> str:
    return prefix + re.sub(r"[^A-Za-z0-9]", "_", name)


def build(plugin_dir: Path = PLUGIN_DIR, pieces: tuple[tuple[str, str], ...] = PIECES) -> str:
    """The text of ``register.js`` for the pieces found in ``<plugin_dir>/mod``."""
    mod_dir = plugin_dir / "mod"
    common_path = mod_dir / f"{COMMON}.js"
    if not common_path.is_file():
        raise BuildError(f"{common_path} is missing: every piece needs it")
    check_piece(COMMON, common_path.read_text(encoding="utf-8"), needs_register=False)

    present: list[tuple[str, str]] = []
    absent: list[tuple[str, str]] = []
    starts: set[str] = set()
    for name, switch in pieces:
        path = mod_dir / f"{name}.js"
        if path.is_file():
            source = path.read_text(encoding="utf-8")
            check_piece(name, source)
            present.append((name, switch))
            if _START_EXPORT.search(source):
                starts.add(name)
        else:
            absent.append((name, switch))

    out: list[str] = [
        "// GENERATED by scripts/build_mod.py from mod/*.js: do not edit, and do not commit.",
        "// Decision 7: only the pieces present at build time are imported, and each one registers",
        "// inside its own `try`, so one that is absent, throws or is switched off leaves the others",
        "// working (REQ-016). A piece only declares at load (`check_piece`): importing cannot throw.",
        "",
        "import { hasDialog, heartbeat, setup } from './mod/common.js'",
    ]
    for n, _ in present:
        names = f"register as {_binding(n)}"
        if n in starts:
            names += f", onSessionStart as {_binding(n, 'start_')}"
        out.append(f"import {{ {names} }} from './mod/{n}.js'")
    out += [
        "",
        f"const VERSION = {json.dumps(_version(plugin_dir))}",
        f"const CATALOGS = {json.dumps(_catalogs(mod_dir), ensure_ascii=False, sort_keys=True)}",
        f"const ABSENT = {json.dumps(dict(absent))}",
        "",
        "function isOff(value) {",
        "  return value === false || (Array.isArray(value) && value.length === 0)",
        "}",
        "",
        "/** @type {import('claude-code').Register} */",
        "export const register = (on, options) => {",
        "  try {",
        "    setup(options, { catalogs: CATALOGS, version: VERSION })",
        "  } catch {",
        "    return",
        "  }",
        "  const pieces = {}",
        "  for (const name of Object.keys(ABSENT)) {",
        "    pieces[name] = 'absent'",
        "  }",
    ]
    for name, switch in present:
        key = json.dumps(name)
        out += [
            "",
            f"  // {name}: mod/{name}.js, switch `{switch}`.",
            f"  if (isOff(options[{json.dumps(switch)}])) {{",
            f"    pieces[{key}] = 'off'",
            "  } else {",
            "    try {",
            f"      {_binding(name)}(on, options)",
            f"      pieces[{key}] = 'on'",
            "    } catch {",
            f"      pieces[{key}] = 'failed'",
            "    }",
            "  }",
        ]
    out += [
        "",
        "  // Decision 9: the heartbeat says, per session, that the mod loaded and which pieces run.",
        "  on('session.start', async ($, e, next) => {",
        "    const started = await next(e)",
        "    hasDialog(e)",
    ]
    for name, _ in present:
        if name in starts:
            key = json.dumps(name)
            out += [
                f"    if (pieces[{key}] === 'on') {{",
                "      try {",
                f"        await {_binding(name, 'start_')}($, e)",
                "      } catch {",
                f"        pieces[{key}] = 'failed'",
                "      }",
                "    }",
            ]
    out += [
        "    await heartbeat($, { pieces })",
        "    return started",
        "  })",
        "}",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Builds register.js from mod/*.js.")
    parser.add_argument("--plugin-dir", type=Path, default=PLUGIN_DIR)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="exit 1 if register.js is stale")
    args = parser.parse_args(argv)
    output = args.output or args.plugin_dir / OUTPUT_NAME
    try:
        text = build(args.plugin_dir)
    except (BuildError, OSError, ValueError) as exc:
        print(f"build_mod: {exc}", file=sys.stderr)
        return 2
    if args.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else None
        if current != text:
            print(f"build_mod: {output} is missing or stale", file=sys.stderr)
            return 1
        return 0
    output.write_text(text, encoding="utf-8", newline="\n")
    print(f"build_mod: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
