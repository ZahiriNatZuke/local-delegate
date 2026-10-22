"""Static guards of the local-delegate mod (SDD claude-plugin-and-mods, F2-mod-core; REQ-013, 016).

The mod is JavaScript that the engine runs where Python tests cannot reach, so what REQ-016 promises
(one secret read, loopback only, the token never written) is held here by reading its source; what
it does is held by `claude plugin test` (`mod/*.test.ts`, run in the `plugin` CI job). The last test
builds `register.js` with a piece that throws and, when `node` is on PATH, runs it: the other pieces
must still register.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PLUGIN_DIR = ROOT / "src" / "local_delegate" / "resources" / "claude-plugin" / "local-delegate"
MOD_DIR = PLUGIN_DIR / "mod"

if not SCRIPTS.is_dir():
    pytest.skip(
        "scripts/ no está en el árbol (sdist): estas pruebas necesitan el repositorio",
        allow_module_level=True,
    )


def _load_build_mod():
    spec = importlib.util.spec_from_file_location("build_mod", SCRIPTS / "build_mod.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_mod = _load_build_mod()

#: Every variable the mod may read. The token is the only secret; the rest locate the plugin's
#: data folder (T0: `CLAUDE_PLUGIN_DATA` does not reach the mod) or say who started the session.
ALLOWED_VARIABLES = {
    "LOCAL_DELEGATE_WEB_TOKEN",
    "CLAUDE_CONFIG_DIR",
    "USERPROFILE",
    "HOME",
    "CLAUDE_CODE_ENTRYPOINT",
}

ENV_GET = re.compile(r"\$\.env\.get\(\s*([^)]*)\)")
ENV_ANY = re.compile(r"\$\.env\.(\w+)")
HTTP_ANY = re.compile(r"\$\.http\.(\w+)")
URL_LITERAL = re.compile(r"""\b(?:https?|wss?)://[^\s'"`)]+""")
UI_CALL = re.compile(r"\$\.ui\.(?:log|status|toast|notice)\(([^)]*)\)")


def _sources() -> dict[str, str]:
    """The mod's own code: every `mod/*.js` (tests are not shipped code paths)."""
    found = {path.name: path.read_text(encoding="utf-8") for path in sorted(MOD_DIR.glob("*.js"))}
    assert "common.js" in found and "pinned-tools.js" in found, sorted(found)
    return found


def _code(source: str) -> str:
    """The source without comments, so a comment that names a variable is not a read."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in source.splitlines())


def test_mod_reads_only_the_token_variable():
    names: list[str] = []
    for name, source in _sources().items():
        code = _code(source)
        for method in ENV_ANY.findall(code):
            assert method == "get", f"{name}: $.env.{method} (the mod only reads)"
        for argument in ENV_GET.findall(code):
            literal = re.fullmatch(r"\s*'([A-Z_]+)'\s*", argument)
            assert literal, f"{name}: $.env.get({argument}) is not a string literal"
            names.append(literal.group(1))
    assert set(names) <= ALLOWED_VARIABLES, sorted(set(names) - ALLOWED_VARIABLES)
    secrets = {n for n in names if re.search(r"TOKEN|SECRET|KEY|PASSWORD|AUTH", n)}
    assert secrets == {"LOCAL_DELEGATE_WEB_TOKEN"}, secrets
    # Guard: the scan reached the reads it is about.
    assert names.count("LOCAL_DELEGATE_WEB_TOKEN") == 1, names


def test_mod_talks_only_to_loopback():
    fetches = 0
    for name, source in _sources().items():
        code = _code(source)
        for method in HTTP_ANY.findall(code):
            assert method == "fetch", f"{name}: $.http.{method}"
            assert name == "common.js", f"{name} calls $.http directly; use daemonFetch"
            fetches += 1
        for url in URL_LITERAL.findall(code):
            assert url.startswith(("http://${DAEMON_HOST}", "http://127.0.0.1")), f"{name}: {url}"
        assert "socketPath" not in code, name
    common = _code(_sources()["common.js"])
    assert "export const DAEMON_HOST = '127.0.0.1'" in common
    # The only fetch builds its URL from the loopback origin and checks it before the request.
    assert fetches == 1
    assert "url.hostname !== DAEMON_HOST" in common
    assert common.index("url.hostname !== DAEMON_HOST") < common.index("$.http.fetch(")


def test_mod_never_logs_token():
    for name, source in _sources().items():
        code = _code(source)
        assert "console." not in code, name
        for argument in UI_CALL.findall(code):
            assert not re.search(r"token|secret|Authorization", argument, re.IGNORECASE), (
                name,
                argument,
            )
    common = _code(_sources()["common.js"])
    # The token's value lives in `secret`, inside `daemonFetch`, and reaches only the header.
    uses = [line.strip() for line in common.splitlines() if re.search(r"\bsecret\b", line)]
    assert uses == [
        "const secret = await token($)",
        "if (secret) {",
        "headers.Authorization = `Bearer ${secret}`",
    ], uses
    calls = [
        line.strip() for line in common.splitlines() if re.search(r"(?<![\w.])token\(\$\)", line)
    ]
    assert calls == [
        "export async function token($) {",
        "const secret = await token($)",
        "token: () => token($),",
    ], calls
    # The heartbeat's fields are listed, and none of them is the token.
    beat = common[common.index("const beat = {") : common.index("await $.fs.write(path")]
    assert "token" not in beat.lower() and "secret" not in beat.lower()


def test_every_piece_has_a_userconfig_switch():
    manifest = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    config = manifest["userConfig"]
    declared = dict(build_mod.PIECES)
    for piece, switch in declared.items():
        assert switch in config, f"{piece}: `{switch}` is not in userConfig"
        assert config[switch].get("required") is not True, switch
    # Every piece in `mod/` is declared, so none can load without a switch.
    shipped = {p.stem for p in MOD_DIR.glob("*.js")} - {build_mod.COMMON}
    assert shipped <= set(declared), sorted(shipped - set(declared))
    # REQ-013: the four tools of the spec by default; REQ-016 / decision 8: the read mod is off.
    assert config["pinned_tools"]["multiple"] is True
    assert config["pinned_tools"]["default"] == [
        "local_summarize",
        "local_extract",
        "local_lint_summary",
        "local_commit_msg",
    ]
    pinned = (MOD_DIR / "pinned-tools.js").read_text(encoding="utf-8")
    assert (
        "export const DEFAULT_PINNED = ['local_summarize', 'local_extract', 'local_lint_summary', "
        "'local_commit_msg']" in pinned
    )
    for switch in ("commands_enabled", "status_enabled", "read_mod_enabled"):
        assert config[switch]["type"] == "boolean", switch
    assert config["commands_enabled"]["default"] is True
    assert config["status_enabled"]["default"] is True
    assert config["read_mod_enabled"]["default"] is False
    hooks = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text("utf-8"))
    assert hooks["modules"] == ["../register.js"]


# --- register.js: each piece in its own try --------------------------------------------------
NODE_DRIVER = """
import { pathToFileURL } from 'node:url'
const { register } = await import(pathToFileURL(process.argv[2]).href)
const hooks = []
const on = (event, matcher, hook) => {
  hooks.push({ event, matcher: typeof matcher === 'function' ? undefined : matcher })
  if (typeof matcher === 'function') hooks[hooks.length - 1].hook = matcher
  else hooks[hooks.length - 1].hook = hook
}
register(on, { ld_bin: 'python', pinned_tools: ['local_summarize'], commands_enabled: true })
const writes = []
const $ = {
  env: { get: async name => (name === 'CLAUDE_CONFIG_DIR' ? '/cfg' : undefined) },
  session: { id: async () => 'sess-9' },
  fs: { write: async (path, text) => { writes.push({ path, text }) } },
  process: { run: async () => { throw new Error('no process here') } },
}
const start = hooks.find(h => h.event === 'session.start')
await start.hook($, { cwd: '/', isInteractive: true }, async () => ({ cwd: '/' }))
console.log(JSON.stringify({ events: hooks.map(h => h.event), beat: JSON.parse(writes[0].text) }))
"""


def _fixture_plugin(tmp_path: Path) -> Path:
    """The real plugin, plus a `status` piece that throws while registering; `read` stays absent."""
    plugin = tmp_path / "plugin"
    shutil.copytree(
        PLUGIN_DIR, plugin, ignore=shutil.ignore_patterns("register.js", "*.test.ts", "types")
    )
    (plugin / "mod" / "status.js").write_text(
        "export function register(on, options) {\n  throw new Error('status broke')\n}\n",
        encoding="utf-8",
    )
    return plugin


def test_register_loads_pieces_dynamically_inside_try(tmp_path):
    plugin = _fixture_plugin(tmp_path)
    text = build_mod.build(plugin)
    # Static: no dynamic import (T0), one import per present piece, each call inside a `try`.
    assert not re.search(r"\bimport\s*\(", _code(text))
    assert "import { register as register_status } from './mod/status.js'" in text
    assert "./mod/read.js" not in text and '"read": "read_mod_enabled"' in text
    for name in ("pinned_tools", "commands", "status"):
        assert f"    try {{\n      register_{name}(on, options)\n" in text, name
    assert text.count("on('session.start'") == 1

    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en PATH: queda la parte estática")
    output = plugin / "register.mjs"
    (plugin / "register.js").write_text(text, encoding="utf-8")
    # node reads `.js` as CommonJS without a package.json: the copy goes as `.mjs`, and so does
    # every piece it imports.
    mjs = text.replace(".js'", ".mjs'")
    output.write_text(mjs, encoding="utf-8")
    for piece in (plugin / "mod").glob("*.js"):
        piece.with_suffix(".mjs").write_text(
            piece.read_text(encoding="utf-8").replace("./common.js'", "./common.mjs'"),
            encoding="utf-8",
        )
    driver = tmp_path / "driver.mjs"
    driver.write_text(NODE_DRIVER, encoding="utf-8")
    done = subprocess.run(
        [node, str(driver), str(output)], capture_output=True, text=True, timeout=60, check=False
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    # The throwing piece is `failed`; the ones beside it registered their hooks and are `on`.
    assert result["beat"]["pieces"] == {
        "pinned-tools": "on",
        "commands": "on",
        "status": "failed",
        "read": "absent",
    }
    assert "tool.describe" in result["events"] and "command.run" in result["events"]
    assert result["beat"]["session_id"] == "sess-9"
    assert result["beat"]["dialog"] is True
    assert result["beat"]["process_run"] is False


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("export function register(on) {}\nconst x = import('./a.js')\n", "dynamic import"),
        ("import { a } from './other.js'\nexport function register(on) {}\n", "imports only"),
        ("export function register(on) {}\nregister(null)\n", "top level"),
        ("export function register(on) {\n  on('session.start', () => {})\n}\n", "onSessionStart"),
        ("export function start(on) {}\n", "does not export"),
    ],
)
def test_build_refuses_a_piece_that_cannot_load_safely(source, message):
    with pytest.raises(build_mod.BuildError, match=message):
        build_mod.check_piece("piece", source)


def test_build_check_flags_a_stale_register(tmp_path):
    plugin = _fixture_plugin(tmp_path)
    assert build_mod.main(["--plugin-dir", str(plugin)]) == 0
    assert build_mod.main(["--plugin-dir", str(plugin), "--check"]) == 0
    (plugin / "mod" / "status.js").unlink()
    assert build_mod.main(["--plugin-dir", str(plugin), "--check"]) == 1
