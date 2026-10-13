"""El hook de Shell anota y ofrece la ruta ABSOLUTA (SDD subagente-lector-local, revisión B2).

`cat docs/x.md` trae una ruta relativa. Antes se anotaba y se ofrecía tal cual, y el daemon —otro
proceso, otro directorio— la resolvía contra el suyo: no encontraba el fichero y la huella de la
nota no casaba con la de la delegación, así que el bloqueo nunca contaba como aceptado.

El texto del bloqueo de lectura, en cambio, no cambió: se vigila byte a byte contra `main`.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import tempfile
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
read_hook = _load("suggest_delegate_read")

# Copiado LITERAL de `main` (e46fe70). Si el texto del bloqueo de lectura se toca, esto falla.
READ_TEXT = (
    "Este archivo pesa 40 KB y es prosa. Pasalo por una tool local con "
    '`path="{p}"`: `local_summarize` para el contenido, `local_extract` '
    "para campos concretos, `local_translate` o `local_explain_code`. Asi no entra al "
    "contexto.\n\n"
    "Si de verdad necesitas el texto literal —lineas exactas para citar o editar—, "
    "leelo por franjas con `offset` y `limit`, que no se bloquean."
)
SHELL_TEXT = (
    "Este comando vuelca 40 KB de prosa al contexto. Pasalo por una tool local "
    'con `path="{p}"`: `local_summarize` para el contenido, `local_extract` para campos '
    "concretos.\n\n"
    "Si necesitas el texto literal, pide solo el trozo que te hace falta —`sed -n`, "
    "`head -n`, `Get-Content -TotalCount`— que no se bloquean."
)


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    monkeypatch.setenv("LD_HOOK_READ_SWITCH_FILE", str(tmp_path / "no-existe"))
    # Hook y servidor importan `hook_common` por caminos distintos (módulo suelto y paquete): son
    # dos objetos. Los dos calculan la ruta de las notas con `tempfile.gettempdir()` en cada
    # llamada, así que redirigir eso los apunta al mismo fichero.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for hook in (shell_hook, read_hook):
        monkeypatch.setattr(hook, "backend_available", lambda **k: True)
        monkeypatch.setattr(hook, "cooled_model", lambda model: False)


def _reason(output: str) -> str:
    return json.loads(output)["hookSpecificOutput"]["permissionDecisionReason"]


def _shell(monkeypatch, capsys, command: str, cwd: Path) -> str:
    hook_input = {"tool_input": {"command": command}, "cwd": str(cwd), "session_id": "s"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_input)))
    shell_hook.main()
    return capsys.readouterr().out


def _read(monkeypatch, capsys, file: Path) -> str:
    hook_input = {"tool_input": {"file_path": str(file)}, "session_id": "s"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_input)))
    read_hook.main()
    return capsys.readouterr().out


@pytest.fixture
def document(tmp_path) -> Path:
    file = tmp_path / "docs" / "informe.md"
    file.parent.mkdir()
    file.write_text("x" * 40 * 1024, encoding="utf-8")
    return file


def test_the_read_block_text_does_not_change_a_single_byte(monkeypatch, capsys, document):
    assert _reason(_read(monkeypatch, capsys, document)) == READ_TEXT.format(p=document)


def test_a_relative_cat_offers_the_absolute_path(monkeypatch, capsys, document, tmp_path):
    reason = _reason(_shell(monkeypatch, capsys, "cat docs/informe.md", tmp_path))
    assert reason == SHELL_TEXT.format(p=document)


def test_a_relative_cat_is_matched_with_the_delegation(monkeypatch, capsys, document, tmp_path):
    from local_delegate import server

    reason = _reason(_shell(monkeypatch, capsys, "cat docs/informe.md", tmp_path))
    offered = re.search(r'path="([^"]+)"', reason).group(1)
    # El modelo delega con la ruta que se le ofreció, y la nota tiene que estar a ese nombre.
    assert Path(offered) == document
    assert server._recent_block_id(offered) is not None
