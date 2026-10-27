"""Los textos de los hooks, en el idioma vigente y en ASCII (REQ-024, REQ-030, REQ-034; ola B3).

Los hooks no importan el paquete: llevan su catálogo dentro (`hook_common.HOOK_TEXTS`) y resuelven
el idioma con la misma regla que el paquete (`resolve_language` sobre su `LOG_DIR`). Por eso el
test que importa es el del hook **instalado**, lanzado como subproceso con un `language.json`: la
suite prueba el script, pero el idioma lo decide el entorno que hereda.
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from local_delegate import install as inst
from local_delegate.resources.hooks import hook_common

HOOKS = Path(hook_common.__file__).parent
HOOK_FILES = sorted(HOOKS.glob("*.py"))


# --- Guardián: ningún hook importa el paquete -----------------------------------------------------


def imports_of_the_package(source: str) -> list[str]:
    """Los `import local_delegate…` y `from local_delegate… import` de un fichero."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "local_delegate"]
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and (node.module or "").split(".")[0] == "local_delegate"
        ):
            found.append(node.module)
    return found


def test_the_guardian_sees_every_hook():
    """Guarda de no vacío: sin ficheros, el guardián de abajo pasaría sobre nada."""
    names = {path.name for path in HOOK_FILES}
    assert {"hook_common.py", "suggest_delegate_read.py", "suggest_delegate_shell.py"} <= names


@pytest.mark.parametrize("path", HOOK_FILES, ids=lambda p: p.name)
def test_no_hook_imports_the_package(path):
    """Un hook instalado corre con el Python del usuario, sin el paquete: el import lo rompería."""
    assert imports_of_the_package(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "source",
    [
        "import local_delegate",
        "from local_delegate import config",
        "from local_delegate.resources.hooks import hook_common",
        "def f():\n    import local_delegate.i18n",
    ],
)
def test_the_guardian_catches_an_import_of_the_package(source):
    """Control positivo: el mutante «añadir el import» tiene que caer."""
    assert imports_of_the_package(source) != []


# --- El catálogo de los hooks ---------------------------------------------------------------------


def test_the_hook_catalog_is_not_empty():
    """Guarda de no vacío para la paridad y el ASCII de `test_i18n_parity.py`."""
    assert len(hook_common.HOOK_TEXTS["es"]) >= 8
    assert set(hook_common.HOOK_TEXTS["es"]) == set(hook_common.HOOK_TEXTS["en"])


def test_every_key_the_hooks_use_exists():
    """Cada `hook_text("…")` literal de los hooks tiene su texto (los dos idiomas, por paridad)."""
    used = set()
    for path in HOOK_FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "hook_text"
                and node.args
            ):
                continue
            key = node.args[0]
            # Una clave literal, o las dos ramas de un `a if cond else b`.
            options = [key.body, key.orelse] if isinstance(key, ast.IfExp) else [key]
            used |= {o.value for o in options if isinstance(o, ast.Constant)}
    assert used, "ningún hook llama a hook_text: el test no comprobaría nada"
    # Las dos fuerzas de la sugerencia se piden con f-string (`read.strength.{band}`).
    used |= {"read.strength.strong", "read.strength.suggest"}
    assert used == set(hook_common.HOOK_TEXTS["es"])


def test_hook_text_interpolates_and_keeps_braces_in_values():
    text = hook_common.hook_text("shell.block", lang="en", size_kb="40", path="C:/a/{b}.md")
    assert 'path="C:/a/{b}.md"' in text
    assert text.startswith("This command dumps 40 KB of prose into the context.")


def test_hook_text_follows_the_variable(monkeypatch):
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    assert hook_common.hook_text("read.strength.suggest") == "Suggestion"
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "es")
    assert hook_common.hook_text("read.strength.suggest") == "Sugerencia"


def test_the_ascii_check_catches_an_accent():
    """Control positivo del ASCII de `test_i18n_parity.py`: el mutante «poner una tilde» cae."""
    from test_i18n_parity import check_pair

    es = {**hook_common.HOOK_TEXTS["es"], "read.strength.suggest": "Sugerencía"}
    problems = check_pair(es, hook_common.HOOK_TEXTS["en"], ascii_only=True)
    assert problems == ["read.strength.suggest: no es ASCII en es"]


# --- El hook INSTALADO, lanzado como subproceso ---------------------------------------------------


def _installed(home: Path) -> dict[str, list[str]]:
    """Instala en un HOME de prueba y devuelve el argv registrado de cada hook, por matcher."""
    options = inst.Options(
        home=home,
        components={"hooks"},
        targets={"claude"},
        python_exe="python3",
        use_cli=False,
        enable_read_hook=True,
    )
    assert inst.apply(inst.plan_install(options), dry_run=False, out=lambda *_a: None) == 0
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = {}
    for event, groups in settings["hooks"].items():
        for group in groups:
            command = group["hooks"][0]["command"]
            argv = shlex.split(command)
            # El intérprete registrado se resuelve por PATH y puede no ser el de la suite.
            argv[0] = sys.executable
            commands[group.get("matcher") or event] = argv
    return commands


def _run(argv: list[str], hook_input: dict, log_dir: Path) -> dict:
    env = {**os.environ, "LOCAL_DELEGATE_LOG_DIR": str(log_dir)}
    # Sin la variable, el idioma sale del `language.json` que escribe el test (REQ-018, paso 2).
    env.pop("LOCAL_DELEGATE_LANG", None)
    env.pop("LD_HOOK_READ_BLOCK", None)
    env.pop("LD_HOOK_TELEMETRY_LOG", None)
    out = subprocess.run(
        argv, input=json.dumps(hook_input).encode(), capture_output=True, env=env, timeout=60
    ).stdout
    assert out.isascii(), f"la salida del hook no es ASCII: {out!r}"
    return json.loads(out.decode("ascii"))["hookSpecificOutput"]


@pytest.mark.parametrize(
    ("lang", "read_start", "prompt_start"),
    [
        ("en", "Suggestion: this file is 39 KB.", "Mechanical task detected (summarize)."),
        # Control: con `es`, el mismo hook instalado responde en español. Sin él, un hook que
        # respondiera siempre en inglés pasaría el caso de arriba.
        (
            "es",
            "Sugerencia: este archivo pesa 39 KB.",
            "Oportunidad mecanica detectada (summarize).",
        ),
    ],
)
def test_the_installed_hook_answers_in_the_preferred_language(
    tmp_path, lang, read_start, prompt_start
):
    commands = _installed(tmp_path / "home")
    log_dir = tmp_path / "data"
    log_dir.mkdir()
    (log_dir / hook_common.LANGUAGE_PREFERENCE_FILE).write_text(
        json.dumps({"lang": lang, "source": "system"}), encoding="utf-8"
    )
    document = tmp_path / "notes.md"
    document.write_text("x" * 40_000, encoding="utf-8")

    read = _run(commands["Read"], {"tool_input": {"file_path": str(document)}}, log_dir)
    assert read["additionalContext"].startswith(read_start), read

    prompt = _run(commands["UserPromptSubmit"], {"prompt": "resume este log"}, log_dir)
    assert prompt["additionalContext"].startswith(prompt_start), prompt


# --- Issue #443: dentro de un subagente, localizar con local_* y leer el rango ----------------------


def _run_raw(argv: list[str], hook_input: dict, log_dir: Path) -> bytes:
    env = {**os.environ, "LOCAL_DELEGATE_LOG_DIR": str(log_dir)}
    for name in ("LOCAL_DELEGATE_LANG", "LD_HOOK_READ_BLOCK", "LD_HOOK_TELEMETRY_LOG"):
        env.pop(name, None)
    return subprocess.run(
        argv, input=json.dumps(hook_input).encode(), capture_output=True, env=env, timeout=60
    ).stdout


def _english_hooks(tmp_path) -> tuple[dict[str, list[str]], Path]:
    commands = _installed(tmp_path / "home")
    log_dir = tmp_path / "data"
    log_dir.mkdir()
    (log_dir / hook_common.LANGUAGE_PREFERENCE_FILE).write_text(
        json.dumps({"lang": "en", "source": "system"}), encoding="utf-8"
    )
    return commands, log_dir


@pytest.mark.parametrize("name", ["big.py", "notes.md"])
def test_the_installed_read_hook_tells_a_subagent_to_read_only_the_range(tmp_path, name):
    commands, log_dir = _english_hooks(tmp_path)
    document = tmp_path / name
    document.write_text("x" * 40_000, encoding="utf-8")
    hook_input = {"tool_input": {"file_path": str(document)}, "agent_id": "agent-1"}

    context = _run(commands["Read"], hook_input, log_dir)["additionalContext"]

    assert context.startswith("Subagent: this file is 39 KB."), context
    assert f'`local_extract` or `local_explain_code` with `path="{document}"`' in context
    assert "read only that range with `offset` and `limit`" in context
    assert "Read it directly" not in context, "la excepcion que daba permiso para leerlo entero"


def test_the_main_thread_keeps_its_read_texts(tmp_path):
    """Control: sin `agent_id`, el código grande sigue en silencio y la prosa con la sugerencia."""
    commands, log_dir = _english_hooks(tmp_path)
    code = tmp_path / "big.py"
    code.write_text("x" * 40_000, encoding="utf-8")
    assert _run_raw(commands["Read"], {"tool_input": {"file_path": str(code)}}, log_dir) == b""
    prose = tmp_path / "notes.md"
    prose.write_text("x" * 40_000, encoding="utf-8")
    read = _run(commands["Read"], {"tool_input": {"file_path": str(prose)}}, log_dir)
    assert read["additionalContext"].startswith("Suggestion: this file is 39 KB."), read


def _open_breaker(log_dir: Path, until: float) -> None:
    """El corte por backend inalcanzable tal como lo deja el servidor (issue #436)."""
    from local_delegate import cooldown

    (log_dir / cooldown.BREAKER_STATE_FILE).write_text(
        json.dumps(
            {"test-backend": {"failures": 0, "wait_s": 60.0, "until": until, "reentries": 1}}
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("down", [True, False], ids=["backend-down", "control"])
@pytest.mark.parametrize("name", ["big.py", "notes.md"])
def test_a_subagent_gets_no_suggestion_while_the_backend_is_down(tmp_path, name, down):
    """Issue #443 + #436: la nota del subagente manda a una local_*; con el corte abierto, calla."""
    import time

    commands, log_dir = _english_hooks(tmp_path)
    _open_breaker(log_dir, time.time() + (300 if down else -1))
    document = tmp_path / name
    document.write_text("x" * 40_000, encoding="utf-8")
    hook_input = {"tool_input": {"file_path": str(document)}, "agent_id": "agent-1"}

    out = _run_raw(commands["Read"], hook_input, log_dir)

    if down:
        assert out == b"", out
    else:
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert context.startswith("Subagent: this file is 39 KB."), context


@pytest.mark.parametrize("down", [True, False], ids=["backend-down", "control"])
def test_the_subagent_start_hook_is_quiet_while_the_backend_is_down(tmp_path, down):
    import time

    commands, log_dir = _english_hooks(tmp_path)
    _open_breaker(log_dir, time.time() + (300 if down else -1))
    hook_input = {"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": "Explore"}

    out = _run_raw(commands["SubagentStart"], hook_input, log_dir)

    if down:
        assert out == b"", out
    else:
        assert "ToolSearch" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_the_installed_subagent_start_hook_says_how_to_load_the_tools(tmp_path):
    commands, log_dir = _english_hooks(tmp_path)
    hook_input = {"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": "Explore"}

    out = _run(commands["SubagentStart"], hook_input, log_dir)

    assert out["hookEventName"] == "SubagentStart"
    assert 'ToolSearch("select:mcp__local-delegate__local_extract,' in out["additionalContext"]
    assert "read only that range" in out["additionalContext"]
    # Una entrada rota no rompe nada: sale sin texto.
    broken = subprocess.run(
        commands["SubagentStart"], input=b"not json", capture_output=True, timeout=60
    )
    assert broken.returncode == 0 and broken.stdout == b""
