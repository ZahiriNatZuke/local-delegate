"""El hook que cierra la lectura completa por shell.

Cerrar la tool `Read` y dejar `cat` abierto no cambia nada: la conducta se mueve al comando de al
lado, la adopcion medida sube y no se ahorra un token. Pero un comando mal parseado que se bloquea
no es un consejo malo, es impedir algo que el usuario pidio. De ahi que la mayoria de estos tests
comprueben lo que **no** se bloquea.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"
sys.path.insert(0, str(HOOKS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


shell_hook = _load("suggest_delegate_shell")


def _run(monkeypatch, capsys, command, *, backend=True, block=True, log=None):
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1" if block else "0")
    if log is not None:
        monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setattr(shell_hook, "backend_available", lambda **k: backend)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": command}})))
    shell_hook.main()
    return capsys.readouterr().out


@pytest.fixture
def document(tmp_path):
    file = tmp_path / "report.md"
    file.write_text("x" * 40 * 1024, encoding="utf-8")
    return file


# --- Lo que SÍ se bloquea ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    [
        "cat {p}",
        "type {p}",
        "more {p}",
        "Get-Content {p}",
        "gc {p}",
        "head {p}",
        'cat "{p}"',
        "CAT {p}",
    ],
)
def test_the_simple_ways_to_dump_a_document_are_blocked(monkeypatch, capsys, document, template):
    output = _run(monkeypatch, capsys, template.format(p=document))
    decision = json.loads(output)["hookSpecificOutput"]

    assert decision["permissionDecision"] == "deny"
    assert "local_summarize" in decision["permissionDecisionReason"]
    assert "sed -n" in decision["permissionDecisionReason"], "tiene que decir por dónde salir"


# --- Lo que NO se bloquea (que es la mayoría) -------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "cat {p} | head -20",
        "cat {p} > copia.md",
        "cat {p} && echo listo",
        "cat {p}; echo listo",
        "echo $(cat {p})",
        "cat {p} otro.md",
        "sed -n '1,50p' {p}",
        "head -n 20 {p}",
        "Get-Content {p} -TotalCount 20",
        "Get-Content -Tail 5 {p}",
        "grep hola {p}",
        "cat",
        "git status",
        "catalogo {p}",
    ],
    ids=[
        "tuberia",
        "redireccion",
        "encadenado",
        "punto y coma",
        "sustitucion",
        "dos ficheros",
        "sed acotado",
        "head acotado",
        "TotalCount",
        "Tail",
        "grep",
        "sin fichero",
        "otro verbo",
        "verbo que empieza igual",
    ],
)
def test_what_is_not_a_clean_dump_passes(monkeypatch, capsys, document, command):
    """Ante la duda, no se bloquea. Un falso positivo aquí se lleva por delante el experimento."""
    assert _run(monkeypatch, capsys, command.format(p=document)) == ""


def test_a_large_json_is_not_blocked(monkeypatch, capsys, tmp_path):
    """Mismo trato que en el hook de lectura: los datos se leen para sacar un valor exacto."""
    data = tmp_path / "state.json"
    data.write_text("x" * 40 * 1024, encoding="utf-8")

    assert _run(monkeypatch, capsys, f"cat {data}") == ""


def test_a_small_document_is_not_blocked(monkeypatch, capsys, tmp_path):
    short = tmp_path / "notes.md"
    short.write_text("x" * 2 * 1024, encoding="utf-8")

    assert _run(monkeypatch, capsys, f"cat {short}") == ""


def test_without_backend_it_is_not_blocked(monkeypatch, capsys, document):
    assert _run(monkeypatch, capsys, f"cat {document}", backend=False) == ""


def test_with_the_block_off_it_is_not_blocked(monkeypatch, capsys, document):
    assert _run(monkeypatch, capsys, f"cat {document}", block=False) == ""


def test_a_missing_file_breaks_nothing(monkeypatch, capsys, tmp_path):
    assert _run(monkeypatch, capsys, f"cat {tmp_path / 'fantasma.md'}") == ""


# --- El denominador ---------------------------------------------------------------------------


def test_every_command_leaves_a_trace_to_measure(monkeypatch, capsys, document, tmp_path):
    """Sin denominador no se sabe cuánta lectura se va por aquí, que es lo que nadie pudo medir."""
    log = tmp_path / "telemetry.jsonl"

    _run(monkeypatch, capsys, f"cat {document} | head -5", log=log)
    _run(monkeypatch, capsys, "git status", log=log)
    _run(monkeypatch, capsys, f"cat {document}", log=log)

    events = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [e["reason"] for e in events] == ["not_a_dump", "not_a_dump", "large_prose"]
    assert all(e["route"] == "shell" for e in events)
    assert events[-1]["blocked"] is True
    # Ni el comando ni la ruta entran nunca en la telemetría.
    assert str(document) not in log.read_text(encoding="utf-8")


def _reasons(log) -> list[str]:
    return [json.loads(x)["reason"] for x in log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    "command",
    ["cat {p}>copia.md", "cat {p}|head", "cat {p}&&echo ya", "cat {p};ls"],
    ids=["redireccion pegada", "tuberia pegada", "encadenado pegado", "punto y coma pegado"],
)
def test_metacharacters_without_spaces_also_stop_it(
    monkeypatch, capsys, document, command, tmp_path
):
    """Estos son los que de verdad necesitan la guarda de metacaracteres.

    Con espacios alrededor, `shlex` deja el metacaracter como palabra suelta y el comando ya cae
    por «más de una palabra tras el verbo». Pegado al nombre del fichero **no**: `cat x.md>copia`
    se trocea como dos palabras, y sin esa guarda se bloquearía una redirección, que es un comando
    completamente distinto del que el usuario escribió.
    """
    log = tmp_path / "telemetry.jsonl"

    assert _run(monkeypatch, capsys, command.format(p=document), log=log) == ""

    # Y se registra por lo que es. Sin la guarda de metacaracteres el comando tampoco se
    # bloquearia —el fichero «informe.md>copia.md» no existe— pero quedaria contado como
    # «no_file», y el denominador de F1 se lee por motivo.
    assert _reasons(log) == ["not_a_dump"]


def test_a_loose_flag_is_not_mistaken_for_a_path(monkeypatch, capsys, tmp_path):
    """`cat -v` no lee ningún fichero, y tiene que notarse en el motivo, no en un error de disco.

    Sin la guarda de flags, el hook intentaría medir el tamaño de un fichero llamado «-v» y
    registraría «no_file»: el mismo no-bloqueo, pero por la razón equivocada, y la telemetría
    contaría mal.
    """
    log = tmp_path / "telemetry.jsonl"

    assert _run(monkeypatch, capsys, "cat -v", log=log) == ""

    assert _reasons(log) == ["not_a_dump"]
