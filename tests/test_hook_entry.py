"""Los hooks por subcomando de la entrega por plugin (REQ-003; plan, lote F1-hook-entry).

El plugin llama `<python del entorno de uv tool> -I -m local_delegate.hook <nombre>` (vía B de T0).
Lo que se prueba aquí es el camino **instalado**: el intérprete del entorno con `-I`, como lo lanza
Claude Code, y no la función suelta. Cuatro promesas:

- nunca bloquea: un nombre desconocido, una excepción o un `sys.exit(2)` acaban en código 0;
- no carga el servidor: ni `local_delegate.server` ni `mcp` en el camino de un hook;
- hace lo mismo que el script de la entrega por settings, con la misma huella de telemetría;
- su salida es UTF-8 aunque `-I` ignore `PYTHONUTF8` y la tubería de Windows sea cp1252.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from local_delegate import config, hook_entry

ROOT = Path(__file__).parents[1]
HOOKS = ROOT / "src" / "local_delegate" / "resources" / "hooks"
TIMEOUT_S = 60


def _load_hook_common():
    spec = importlib.util.spec_from_file_location("_he_hook_common", HOOKS / "hook_common.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = _load_hook_common()


# --- Montaje ---------------------------------------------------------------------------------------


def _sandbox(base: Path) -> dict[str, str]:
    """Entorno de un hook con temporal, datos y telemetría propios, sin variables del paquete.

    Se quitan también `PYTHONUTF8` y `PYTHONIOENCODING`: con `-I` Python las ignora igual, y así el
    script de referencia no las hereda de quien corre la suite.
    """
    tmp = base / "tmp"
    data = base / "data"
    tmp.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in config.ENVIRONMENT_VARIABLES
        and name not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH"}
    }
    env.update(
        {
            "TMP": str(tmp),
            "TEMP": str(tmp),
            "TMPDIR": str(tmp),
            "LOCAL_DELEGATE_LOG_DIR": str(data),
            "LOCAL_DELEGATE_LANG": "es",
            "LD_HOOK_TELEMETRY_LOG": str(base / "telemetry.jsonl"),
            "LD_HOOK_READ_SWITCH_FILE": str(base / "block-off"),
        }
    )
    return env


def _entry(name: str | None, stdin: bytes, env: dict[str, str], *extra: str):
    """Como lo lanza el plugin: el intérprete del entorno, aislado, por módulo."""
    args = [sys.executable, "-I", *extra, "-m", "local_delegate.hook"]
    if name is not None:
        args.append(name)
    return subprocess.run(
        args, input=stdin, capture_output=True, env=env, timeout=TIMEOUT_S, cwd=env["TMP"]
    )


def _script(script: str, stdin: bytes, env: dict[str, str], *args: str):
    """Como lo lanza la entrega por settings de la 0.39: `python <script>` (en UTF-8)."""
    return subprocess.run(
        [sys.executable, str(HOOKS / script), *args],
        input=stdin,
        capture_output=True,
        env={**env, "PYTHONUTF8": "1"},
        timeout=TIMEOUT_S,
        cwd=env["TMP"],
    )


def _payload(**fields: object) -> bytes:
    return json.dumps({"session_id": "s-test", **fields}, ensure_ascii=False).encode("utf-8")


def _telemetry(base: Path) -> list[dict]:
    path = base / "telemetry.jsonl"
    if not path.exists():
        return []
    events = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]
    return [{k: v for k, v in e.items() if k not in {"ts", "id"}} for e in events]


def _notes(base: Path) -> dict[str, dict]:
    """Las notas de llamada que deja `record_call` en el temporal, sin la hora."""
    directory = base / "tmp" / common.FILE_NAMES["call_notes_dir"][1]
    if not directory.is_dir():
        return {}
    return {
        p.name: {k: v for k, v in json.loads(p.read_text("utf-8")).items() if k != "ts"}
        for p in directory.glob("*.json")
    }


def _block_notes(base: Path) -> list[dict]:
    path = base / "tmp" / common.FILE_NAMES["block_notes"][1]
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _prose(directory: Path, name: str = "report.md", kb: int = 20) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text("Texto de prosa para resumir.\n" * (kb * 1024 // 29 + 1), encoding="utf-8")
    return target


def _seed_backend_alive(base: Path) -> None:
    """La marca de salud fresca: `backend_available` responde sin sondear la red."""
    marker = base / "tmp" / common._health_path().name
    marker.write_text(json.dumps({"ts": time.time(), "ok": True}), encoding="utf-8")


def _imported_modules(stderr: bytes) -> set[str]:
    """Los módulos que lista `-X importtime` (una línea por import, el nombre en la última columna)."""
    names = set()
    for line in stderr.decode("utf-8", "replace").splitlines():
        if line.startswith("import time:") and "|" in line:
            name = line.rsplit("|", 1)[1].strip()
            if name and name != "imported package":
                names.add(name)
    return names


# --- Nunca bloquea ---------------------------------------------------------------------------------


def test_unknown_hook_exits_zero_silently(tmp_path):
    env = _sandbox(tmp_path)
    for name in ("nope", "PROMPT", "", None):
        result = _entry(name, b"{}", env)
        assert (result.returncode, result.stdout, result.stderr) == (0, b"", b""), name
    # Un nombre desconocido no es un fallo: no deja línea en el log de fallos.
    assert not (Path(env["LOCAL_DELEGATE_LOG_DIR"]) / hook_entry.FAILURE_LOG).exists()


def test_unknown_hook_through_the_installed_console_script(tmp_path):
    """`local-delegate hook <nombre>` del ejecutable instalado: también sale con 0 y sin texto."""
    scripts = Path(sys.executable).parent
    exe = next(
        (scripts / n for n in ("local-delegate.exe", "local-delegate") if (scripts / n).exists()),
        None,
    )
    if exe is None:
        pytest.skip("el entorno no tiene el ejecutable de consola instalado")
    env = _sandbox(tmp_path)
    result = subprocess.run(
        [str(exe), "hook", "nope"], input=b"{}", capture_output=True, env=env, timeout=TIMEOUT_S
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def _tmp_hook(monkeypatch, tmp_path: Path, body: str) -> Path:
    scripts = tmp_path / "hooks"
    scripts.mkdir()
    (scripts / "boom.py").write_text(body, encoding="utf-8")
    monkeypatch.setattr(hook_entry, "hooks_dir", lambda: scripts)
    monkeypatch.setitem(hook_entry.HOOKS, "prompt", ("boom.py", False))
    return scripts


def test_hook_crash_lets_the_call_through(monkeypatch, tmp_path, capsys):
    """Una excepción del hook sale con 0, sin texto, y deja una línea en el log de fallos."""
    _tmp_hook(monkeypatch, tmp_path, "raise RuntimeError('boom')\n")
    monkeypatch.setattr(sys, "stdin", _Stdin(b"{}"))

    assert hook_entry.main(["prompt"]) == 0

    assert capsys.readouterr().out == ""
    log = Path(os.environ["LOCAL_DELEGATE_LOG_DIR"]) / hook_entry.FAILURE_LOG
    lines = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
    assert [(e["hook"], e["error"]) for e in lines] == [("prompt", "RuntimeError")]
    assert set(lines[0]) == {"ts", "hook", "error"}, "ni rutas ni mensajes: solo el tipo"


def test_hook_exit_2_inside_the_script_lets_the_call_through(monkeypatch, tmp_path):
    _tmp_hook(monkeypatch, tmp_path, "import sys\nsys.exit(2)\n")
    monkeypatch.setattr(sys, "stdin", _Stdin(b"{}"))
    assert hook_entry.main(["prompt"]) == 0
    log = Path(os.environ["LOCAL_DELEGATE_LOG_DIR"]) / hook_entry.FAILURE_LOG
    assert json.loads(log.read_text("utf-8").splitlines()[-1])["error"] == "SystemExit"


class _Stdin:
    """Un stdin de texto con `buffer`, como el de un proceso real."""

    def __init__(self, data: bytes):
        import io

        self.buffer = io.BytesIO(data)
        self._text = io.TextIOWrapper(self.buffer, encoding="utf-8")

    def read(self, *args):
        return self._text.read(*args)


def _wrapper(code: str):
    return subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, timeout=TIMEOUT_S
    )


def test_wrapper_exits_zero_on_sys_exit_2():
    control = _wrapper("import sys; sys.exit(2)")
    assert control.returncode == 2, "control positivo: sin envoltorio el 2 llega a Claude Code"
    result = _wrapper("import sys\nfrom local_delegate.hook import run\nrun(lambda: sys.exit(2))")
    assert result.returncode == 0, result.stderr


def test_wrapper_exits_zero_on_exception():
    control = _wrapper("raise RuntimeError('boom')")
    assert control.returncode == 1, "control positivo: una excepción suelta sale con 1"
    result = _wrapper(
        "from local_delegate.hook import run\n"
        "def boom():\n    raise RuntimeError('boom')\n"
        "run(boom)"
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == b"", "ni traceback: Claude Code lo mostraría"


# --- Coste: el camino del hook no carga el servidor ------------------------------------------------


def test_hook_path_does_not_import_server(tmp_path):
    env = _sandbox(tmp_path)
    stdin = _payload(prompt="resume este texto")
    by_module = _entry("prompt", stdin, env, "-X", "importtime")
    by_console = subprocess.run(
        [
            sys.executable,
            "-I",
            "-X",
            "importtime",
            "-c",
            (
                "import sys; sys.argv = ['local-delegate', 'hook', 'prompt']; "
                "import local_delegate; local_delegate.main()"
            ),
        ],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=TIMEOUT_S,
    )
    for result in (by_module, by_console):
        assert result.returncode == 0
        modules = _imported_modules(result.stderr)
        # Guarda: el hook corrió de verdad y `-X importtime` está informando.
        assert {"local_delegate.hook_entry", "hook_common"} <= modules, sorted(modules)[:20]
        assert result.stdout, "el hook de prompt tenía que avisar"
        loaded = {m for m in modules if m == "mcp" or m.startswith("mcp.")}
        loaded |= {m for m in modules if m in {"local_delegate.server", "local_delegate.config"}}
        assert loaded == set(), sorted(loaded)


def test_inactive_read_hook_imports_only_switch(tmp_path):
    env = _sandbox(tmp_path)
    stdin = _payload(tool_name="Read", tool_input={"file_path": str(_prose(tmp_path / "docs"))})
    for name in ("read", "mcp-read", "shell"):
        result = _entry(name, stdin, env, "-X", "importtime")
        assert (result.returncode, result.stdout) == (0, b""), name
        modules = _imported_modules(result.stderr)
        ours = {m for m in modules if m.startswith("local_delegate")}
        # `local_delegate.hook` corre como `__main__`, así que no aparece con su nombre.
        assert ours == {
            "local_delegate",
            "local_delegate.hook_entry",
            "local_delegate.read_switch",
        }, (name, sorted(ours))
        assert "hook_common" not in modules, name

    # Control positivo: con la capa «activo» encendida el mismo hook sí carga el script.
    state = Path(env["LOCAL_DELEGATE_LOG_DIR"]) / "read-hook.json"
    state.write_text(json.dumps({"active": True, "since": "2026-10-21T00:00:00+00:00"}), "utf-8")
    result = _entry("read", stdin, env, "-X", "importtime")
    assert "hook_common" in _imported_modules(result.stderr)
    assert result.stdout, "activo y un .md de 20 KB: tenía que sugerir"


# --- Misma conducta y misma huella que la entrega por settings -------------------------------------


def _cases(tmp_path: Path) -> list[tuple[str, str, bytes, tuple[str, ...], bool]]:
    """(hook, script, stdin, argumentos de settings, ¿capa activo?). Cada uno con salida propia."""
    prose = _prose(tmp_path / "docs")
    return [
        ("prompt", "suggest_delegate_prompt.py", _payload(prompt="resume este texto"), (), False),
        (
            "record-call",
            "record_call.py",
            _payload(tool_use_id="toolu_abc123", agent_id="ag-1", agent_type="Explore"),
            (),
            False,
        ),
        (
            "read",
            "suggest_delegate_read.py",
            _payload(tool_name="Read", tool_input={"file_path": str(prose)}),
            ("--enabled",),
            True,
        ),
        (
            "mcp-read",
            "suggest_delegate_read.py",
            _payload(tool_name="mcp__fs__read_text_file", tool_input={"path": str(prose)}),
            ("--enabled",),
            True,
        ),
        (
            "shell",
            "suggest_delegate_shell.py",
            _payload(tool_input={"command": f'cat "{prose}"'}, cwd=str(tmp_path)),
            ("--enabled",),
            True,
        ),
    ]


def _observe(base: Path) -> dict:
    return {"telemetry": _telemetry(base), "notes": _notes(base)}


def _run_both(tmp_path: Path, name: str, script: str, stdin: bytes, args, gated: bool):
    entry_base, script_base = tmp_path / f"entry-{name}", tmp_path / f"script-{name}"
    entry_env, script_env = _sandbox(entry_base), _sandbox(script_base)
    if gated:
        # En la entrega por plugin, el fichero de estado sustituye a `--enabled`.
        state = Path(entry_env["LOCAL_DELEGATE_LOG_DIR"]) / "read-hook.json"
        state.write_text(json.dumps({"active": True, "since": "2026-10-21T00:00:00Z"}), "utf-8")
    by_entry = _entry(name, stdin, entry_env)
    by_script = _script(script, stdin, script_env, *args)
    assert by_entry.returncode == by_script.returncode == 0, (by_entry.stderr, by_script.stderr)
    return (
        {"stdout": by_entry.stdout.decode("utf-8"), **_observe(entry_base)},
        {"stdout": by_script.stdout.decode("utf-8"), **_observe(script_base)},
    )


def test_each_hook_name_matches_script_behaviour(tmp_path):
    outputs = []
    for name, script, stdin, args, gated in _cases(tmp_path):
        by_entry, by_script = _run_both(tmp_path, name, script, stdin, args, gated)
        # Guarda: un caso sin salida compararía vacío con vacío y no probaría nada.
        assert by_script["stdout"] or by_script["telemetry"] or by_script["notes"], name
        assert by_entry == by_script, name
        outputs.append(json.dumps(by_script, sort_keys=True))
    assert len(set(outputs)) == len(outputs), "cada caso tiene que dar una salida propia"
    assert set(hook_entry.HOOKS) == {name for name, *_ in _cases(tmp_path)}


def test_plugin_and_settings_fingerprints_match(tmp_path):
    """La huella (`version`) de cada evento es la del script empaquetado, como en settings."""
    for name, script, stdin, args, gated in _cases(tmp_path):
        by_entry, by_script = _run_both(tmp_path, name, script, stdin, args, gated)
        versions = {e.get("version") for e in by_entry["telemetry"]}
        if name == "record-call":
            assert versions == set(), "record_call no escribe telemetría"
            continue
        assert versions == {common.version_de(str(HOOKS / script))}, name
        assert versions == {e.get("version") for e in by_script["telemetry"]}, name
        assert "" not in versions, name


def test_blocks_jsonl_unchanged_format(tmp_path):
    """El bloqueo por la vía del plugin deja la misma nota y el mismo evento que por settings."""
    prose = _prose(tmp_path / "docs")
    stdin = _payload(tool_name="Read", tool_input={"file_path": str(prose)})
    results = []
    for kind in ("entry", "script"):
        base = tmp_path / kind
        env = {**_sandbox(base), "LD_HOOK_READ_BLOCK": "1", "LD_HOOK_READ_ENABLED": "1"}
        _seed_backend_alive(base)
        run = (
            _entry("read", stdin, env)
            if kind == "entry"
            else _script("suggest_delegate_read.py", stdin, env)
        )
        assert run.returncode == 0
        decision = json.loads(run.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        notes = _block_notes(base)
        assert [set(n) for n in notes] == [{"id", "sha", "ts"}]
        events = _telemetry(base)
        assert [(e["block"], e["blocked"], e["reason"]) for e in events] == [
            ("on", True, "large_prose")
        ]
        results.append((decision, [n["sha"] for n in notes], events))
    assert results[0] == results[1]


def test_hook_output_is_utf8(tmp_path):
    """Con `-I` y en tubería, Windows da cp1252: un carácter fuera de esa tabla perdía el aviso."""
    prose = _prose(tmp_path / "docs", name="report-→-✓.md")
    stdin = _payload(tool_name="Read", tool_input={"file_path": str(prose)})
    env = {**_sandbox(tmp_path / "run"), "LD_HOOK_READ_BLOCK": "1", "LD_HOOK_READ_ENABLED": "1"}
    _seed_backend_alive(tmp_path / "run")

    result = _entry("read", stdin, env)

    assert result.returncode == 0
    assert result.stdout != b"", "el aviso se perdió por la codificación de la consola"
    reason = json.loads(result.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert "report-→-✓.md" in reason["permissionDecisionReason"]
    assert "→".encode() in result.stdout, "tenía que salir en UTF-8, no escapado"


def test_hook_input_is_read_as_utf8(tmp_path):
    """Claude Code manda el JSON en UTF-8; con `-I` en Windows stdin sería cp1252."""
    env = _sandbox(tmp_path)
    result = _entry("prompt", _payload(prompt="resume la sección «Diseño» → ya"), env)
    assert result.returncode == 0
    (event,) = _telemetry(tmp_path)
    assert event["prompt_chars"] == len("resume la sección «Diseño» → ya")


def test_failure_log_is_not_written_on_success(tmp_path):
    env = _sandbox(tmp_path)
    assert _entry("prompt", _payload(prompt="resume esto"), env).returncode == 0
    assert not (Path(env["LOCAL_DELEGATE_LOG_DIR"]) / hook_entry.FAILURE_LOG).exists()


def test_hook_names_are_the_plugin_contract():
    """Los cinco nombres de la decisión 2 del plan; `classify` llega en F4."""
    assert set(hook_entry.HOOKS) == {"prompt", "record-call", "read", "shell", "mcp-read"}
    for script, _gated in hook_entry.HOOKS.values():
        assert (HOOKS / script).is_file(), script
    # La huella del hook de lectura incluye el clasificador (F4-classifier, REQ-019).
    rules = (HOOKS / "suggest_delegate_read.py").read_bytes() + (
        HOOKS / "read_classifier.py"
    ).read_bytes()
    digest = hashlib.sha256(rules).hexdigest()[:8]
    assert digest == common.version_de(str(hook_entry.hooks_dir() / "suggest_delegate_read.py"))
