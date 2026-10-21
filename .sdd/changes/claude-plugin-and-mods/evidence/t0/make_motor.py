"""T0 (claude-plugin-and-mods): engine checks for plugins and mods.

Usage: python make_motor.py <t0_dir> [version]

Writes, under <t0_dir>:
- `mkt/` : a local marketplace `t0-mkt` with plugin `t0-motor` (version given, default 0.0.1):
  userConfig `ld_bin`, hooks.json with `hooks` (SessionStart + UserPromptSubmit, exec form with
  `${user_config.ld_bin}` in `command`) AND `modules` (register.js with a static relative import).
  The mod registers `/t0report`, which prints what session.start saw (no model turn needed).
- `plugins/t0-motor-dyn/` : same mod but loading its piece with a dynamic `import()`.
- `plugins/t0-motor-throw/` : register.js throws at load; hooks.json also has a UserPromptSubmit hook.
- `t0_dump` module in env039's site-packages: a hook that dumps its stdin JSON and the
  CLAUDE_PLUGIN_* / entrypoint env vars to `<t0>/markers/dump-<tag>.json`, then exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

T0 = Path(sys.argv[1]).resolve()
VERSION = sys.argv[2] if len(sys.argv) > 2 else "0.0.1"
ENV = T0 / "env039"
MARKERS = T0 / "markers"
PY039 = str(ENV / "Scripts" / "python.exe").replace("\\", "/")


def fwd(p: Path) -> str:
    return str(p).replace("\\", "/")


(ENV / "Lib" / "site-packages" / "t0_dump.py").write_text(
    "import json, os, sys, pathlib\n"
    f"M = pathlib.Path({fwd(MARKERS)!r})\n"
    "M.mkdir(parents=True, exist_ok=True)\n"
    "tag = sys.argv[1] if len(sys.argv) > 1 else 'x'\n"
    "try:\n"
    "    payload = json.loads(sys.stdin.read() or '{}')\n"
    "except Exception as exc:\n"
    "    payload = {'_error': repr(exc)}\n"
    "env = {k: v for k, v in os.environ.items()\n"
    "       if k.startswith('CLAUDE_PLUGIN_') or k in ('CLAUDE_CODE_ENTRYPOINT', 'CLAUDECODE')}\n"
    "(M / f'dump-{tag}.json').write_text(json.dumps({'stdin': payload, 'env': env}, indent=2))\n"
    "sys.exit(0)\n",
    encoding="utf-8",
)

PLUGIN_JSON = {
    "description": "T0 engine probe",
    "userConfig": {
        "ld_bin": {
            "type": "string",
            "title": "Interpreter",
            "description": "Absolute path of the hook interpreter",
            "required": True,
        }
    },
}


def dump_hook(tag: str, command: str = "${user_config.ld_bin}") -> dict:
    return {
        "type": "command",
        "command": command,
        "args": ["-I", "-m", "t0_dump", tag],
        "timeout": 30,
    }


REPORT_JS = """
let report = { loadedAt: new Date().toISOString() }

export function register(on, options) {
  on('session.start', async ($, e, next) => {
    report.event = e
    report.options = options
    report.piece = PIECE_EXPR
    try { report.sessionId = await $.session.id() } catch (err) { report.sessionId = 'ERR ' + err }
    try { report.surfaces = await $.session.surfaces() } catch (err) { report.surfaces = 'ERR ' + err }
    report.pluginRoot = String($.plugin.root)
    // CLAUDE_PLUGIN_DATA is exported to settings hooks, not to the mod's process: probe and derive.
    let data = await $.env.get('CLAUDE_PLUGIN_DATA')
    report.envPluginData = String(data)
    const cfgDir = await $.env.get('CLAUDE_CONFIG_DIR')
    const home = await $.env.get('USERPROFILE')
    report.envConfigDirSet = cfgDir !== undefined
    const base = cfgDir !== undefined ? cfgDir : home + '/.claude'
    const derived = base + '/plugins/data/' + $.plugin.name + '-t0-mkt'
    try {
      const r = await $.process.run([options.ld_bin, '-I', '-c', 'print(42)'])
      report.processRun = { exitCode: r.exitCode, stdout: String(r.stdout).trim() }
    } catch (err) { report.processRun = 'ERR ' + err }
    const hb = derived + '/heartbeats/' + report.sessionId + '.json'
    try {
      await $.fs.write(hb, JSON.stringify({ ok: true, at: report.loadedAt }))
      report.writeDerivedData = (await $.fs.exists(hb)) ? 'ok' : 'written-but-missing'
    } catch (err) { report.writeDerivedData = 'ERR ' + err }
    report.derivedDataSuffix = '/plugins/data/' + $.plugin.name + '-t0-mkt'
    try { await $.command.register({ name: 't0report', description: 'T0 report' }) } catch (err) { report.cmd = 'ERR ' + err }
    return next(e)
  })
  on('command.run', { command: 't0report' }, async () => {
    return { text: 'T0REPORT ' + JSON.stringify(report) }
  })
}
"""


def write_plugin(
    root: Path,
    name: str,
    version: str,
    register_js: str,
    extra_files: dict,
    hooks: dict,
    ld_default: str | None = None,
) -> None:
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / "hooks").mkdir(parents=True, exist_ok=True)
    manifest = json.loads(json.dumps({"name": name, "version": version, **PLUGIN_JSON}))
    if ld_default:  # --plugin-dir variants: no install, so no --config; use a default instead
        manifest["userConfig"]["ld_bin"].update({"required": False, "default": ld_default})
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (root / "hooks" / "register.js").write_text(register_js, encoding="utf-8")
    for rel, body in extra_files.items():
        p = root / "hooks" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (root / "hooks" / "hooks.json").write_text(
        json.dumps({"modules": ["./register.js"], "hooks": hooks}, indent=2), encoding="utf-8"
    )


PIECE = {"mod/piece.js": "export function pieceName() { return 'piece-static-ok' }\n"}

# 1) Installed via marketplace: static import + hooks + modules + ${user_config} in command.
mkt = T0 / "mkt"
(mkt / ".claude-plugin").mkdir(parents=True, exist_ok=True)
(mkt / ".claude-plugin" / "marketplace.json").write_text(
    json.dumps(
        {
            "name": "t0-mkt",
            "owner": {"name": "t0"},
            "plugins": [
                {
                    "name": "t0-motor",
                    "source": "./plugins/t0-motor",
                    "version": VERSION,
                    "description": "T0 engine probe",
                }
            ],
        },
        indent=2,
    ),
    encoding="utf-8",
)
write_plugin(
    mkt / "plugins" / "t0-motor",
    "t0-motor",
    VERSION,
    "import { pieceName } from './mod/piece.js'\n" + REPORT_JS.replace("PIECE_EXPR", "pieceName()"),
    PIECE,
    {
        "SessionStart": [{"hooks": [dump_hook("motor-sessionstart")]}],
        "UserPromptSubmit": [{"hooks": [dump_hook("motor-ups")]}],
    },
)

# 2) Dynamic import() inside the hook.
dyn_js = REPORT_JS.replace(
    "report.piece = PIECE_EXPR",
    "try { const m = await import('./mod/piece.js'); report.piece = m.pieceName() } "
    "catch (err) { report.piece = 'ERR ' + err }",
)
write_plugin(
    T0 / "plugins" / "t0-motor-dyn",
    "t0-motor-dyn",
    "0.0.1",
    dyn_js,
    PIECE,
    {"UserPromptSubmit": [{"hooks": [dump_hook("dyn-ups")]}]},
    PY039,
)

# 3) register.js that throws at load, next to a settings-style hook in the same hooks.json.
write_plugin(
    T0 / "plugins" / "t0-motor-throw",
    "t0-motor-throw",
    "0.0.1",
    "throw new Error('t0 boom at load')\nexport function register(on) {}\n",
    {},
    {"UserPromptSubmit": [{"hooks": [dump_hook("throw-ups", PY039)]}]},
    PY039,
)

print("ok", VERSION)
