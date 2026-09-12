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


def _correr(monkeypatch, capsys, comando, *, backend=True, bloquear=True, log=None):
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOQUEAR", "1" if bloquear else "0")
    if log is not None:
        monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setattr(shell_hook, "backend_disponible", lambda **k: backend)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": comando}})))
    shell_hook.main()
    return capsys.readouterr().out


@pytest.fixture
def documento(tmp_path):
    fichero = tmp_path / "informe.md"
    fichero.write_text("x" * 40 * 1024, encoding="utf-8")
    return fichero


# --- Lo que SÍ se bloquea ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "plantilla",
    [
        "cat {p}",
        "type {p}",
        "more {p}",
        "Get-Content {p}",
        "gc {p}",
        "rtk read {p}",
        "head {p}",
        'cat "{p}"',
        "CAT {p}",
    ],
)
def test_las_formas_simples_de_volcar_un_documento_se_bloquean(
    monkeypatch, capsys, documento, plantilla
):
    salida = _correr(monkeypatch, capsys, plantilla.format(p=documento))
    decision = json.loads(salida)["hookSpecificOutput"]

    assert decision["permissionDecision"] == "deny"
    assert "local_summarize" in decision["permissionDecisionReason"]
    assert "sed -n" in decision["permissionDecisionReason"], "tiene que decir por dónde salir"


# --- Lo que NO se bloquea (que es la mayoría) -------------------------------------------------


@pytest.mark.parametrize(
    "comando",
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
        "rtk git status",
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
def test_lo_que_no_es_un_volcado_limpio_pasa(monkeypatch, capsys, documento, comando):
    """Ante la duda, no se bloquea. Un falso positivo aquí se lleva por delante el experimento."""
    assert _correr(monkeypatch, capsys, comando.format(p=documento)) == ""


def test_un_json_grande_no_se_bloquea(monkeypatch, capsys, tmp_path):
    """Mismo trato que en el hook de lectura: los datos se leen para sacar un valor exacto."""
    datos = tmp_path / "state.json"
    datos.write_text("x" * 40 * 1024, encoding="utf-8")

    assert _correr(monkeypatch, capsys, f"cat {datos}") == ""


def test_un_documento_pequeno_no_se_bloquea(monkeypatch, capsys, tmp_path):
    corto = tmp_path / "notas.md"
    corto.write_text("x" * 2 * 1024, encoding="utf-8")

    assert _correr(monkeypatch, capsys, f"cat {corto}") == ""


def test_sin_backend_no_se_bloquea(monkeypatch, capsys, documento):
    assert _correr(monkeypatch, capsys, f"cat {documento}", backend=False) == ""


def test_con_el_bloqueo_apagado_no_se_bloquea(monkeypatch, capsys, documento):
    assert _correr(monkeypatch, capsys, f"cat {documento}", bloquear=False) == ""


def test_un_fichero_que_no_existe_no_rompe_nada(monkeypatch, capsys, tmp_path):
    assert _correr(monkeypatch, capsys, f"cat {tmp_path / 'fantasma.md'}") == ""


# --- El denominador ---------------------------------------------------------------------------


def test_todo_comando_deja_rastro_para_poder_medir(monkeypatch, capsys, documento, tmp_path):
    """Sin denominador no se sabe cuánta lectura se va por aquí, que es lo que nadie pudo medir."""
    log = tmp_path / "telemetria.jsonl"

    _correr(monkeypatch, capsys, f"cat {documento} | head -5", log=log)
    _correr(monkeypatch, capsys, "rtk git status", log=log)
    _correr(monkeypatch, capsys, f"cat {documento}", log=log)

    eventos = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [e["motivo"] for e in eventos] == ["no_es_volcado", "no_es_volcado", "prosa_grande"]
    assert all(e["camino"] == "shell" for e in eventos)
    assert eventos[-1]["blocked"] is True
    # Ni el comando ni la ruta entran nunca en la telemetría.
    assert str(documento) not in log.read_text(encoding="utf-8")


def _motivos(log) -> list[str]:
    return [json.loads(x)["motivo"] for x in log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    "comando",
    ["cat {p}>copia.md", "cat {p}|head", "cat {p}&&echo ya", "cat {p};ls"],
    ids=["redireccion pegada", "tuberia pegada", "encadenado pegado", "punto y coma pegado"],
)
def test_los_metacaracteres_sin_espacios_tambien_frenan(
    monkeypatch, capsys, documento, comando, tmp_path
):
    """Estos son los que de verdad necesitan la guarda de metacaracteres.

    Con espacios alrededor, `shlex` deja el metacaracter como palabra suelta y el comando ya cae
    por «más de una palabra tras el verbo». Pegado al nombre del fichero **no**: `cat x.md>copia`
    se trocea como dos palabras, y sin esa guarda se bloquearía una redirección, que es un comando
    completamente distinto del que el usuario escribió.
    """
    log = tmp_path / "telemetria.jsonl"

    assert _correr(monkeypatch, capsys, comando.format(p=documento), log=log) == ""

    # Y se registra por lo que es. Sin la guarda de metacaracteres el comando tampoco se
    # bloquearia —el fichero «informe.md>copia.md» no existe— pero quedaria contado como
    # «sin_fichero», y el denominador de F1 se lee por motivo.
    assert _motivos(log) == ["no_es_volcado"]


def test_un_flag_suelto_no_se_confunde_con_una_ruta(monkeypatch, capsys, tmp_path):
    """`cat -v` no lee ningún fichero, y tiene que notarse en el motivo, no en un error de disco.

    Sin la guarda de flags, el hook intentaría medir el tamaño de un fichero llamado «-v» y
    registraría «sin_fichero»: el mismo no-bloqueo, pero por la razón equivocada, y la telemetría
    contaría mal.
    """
    log = tmp_path / "telemetria.jsonl"

    assert _correr(monkeypatch, capsys, "cat -v", log=log) == ""

    assert _motivos(log) == ["no_es_volcado"]
