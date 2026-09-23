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
TEXTO_READ = (
    "Este archivo pesa 40 KB y es prosa. Pasalo por una tool local con "
    '`path="{p}"`: `local_summarize` para el contenido, `local_extract` '
    "para campos concretos, `local_translate` o `local_explain_code`. Asi no entra al "
    "contexto.\n\n"
    "Si de verdad necesitas el texto literal —lineas exactas para citar o editar—, "
    "leelo por franjas con `offset` y `limit`, que no se bloquean."
)
TEXTO_SHELL = (
    "Este comando vuelca 40 KB de prosa al contexto. Pasalo por una tool local "
    'con `path="{p}"`: `local_summarize` para el contenido, `local_extract` para campos '
    "concretos.\n\n"
    "Si necesitas el texto literal, pide solo el trozo que te hace falta —`sed -n`, "
    "`head -n`, `Get-Content -TotalCount`— que no se bloquean."
)


@pytest.fixture(autouse=True)
def _entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOQUEAR", "1")
    monkeypatch.setenv("LD_HOOK_READ_INTERRUPTOR", str(tmp_path / "no-existe"))
    # Hook y servidor importan `hook_common` por caminos distintos (módulo suelto y paquete): son
    # dos objetos. Los dos calculan la ruta de las notas con `tempfile.gettempdir()` en cada
    # llamada, así que redirigir eso los apunta al mismo fichero.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for hook in (shell_hook, read_hook):
        monkeypatch.setattr(hook, "backend_disponible", lambda **k: True)
        monkeypatch.setattr(hook, "modelo_enfriado", lambda modelo: False)


def _razon(salida: str) -> str:
    return json.loads(salida)["hookSpecificOutput"]["permissionDecisionReason"]


def _shell(monkeypatch, capsys, comando: str, cwd: Path) -> str:
    entrada = {"tool_input": {"command": comando}, "cwd": str(cwd), "session_id": "s"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(entrada)))
    shell_hook.main()
    return capsys.readouterr().out


def _read(monkeypatch, capsys, fichero: Path) -> str:
    entrada = {"tool_input": {"file_path": str(fichero)}, "session_id": "s"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(entrada)))
    read_hook.main()
    return capsys.readouterr().out


@pytest.fixture
def documento(tmp_path) -> Path:
    fichero = tmp_path / "docs" / "informe.md"
    fichero.parent.mkdir()
    fichero.write_text("x" * 40 * 1024, encoding="utf-8")
    return fichero


def test_el_texto_del_bloqueo_de_lectura_no_cambia_ni_un_byte(monkeypatch, capsys, documento):
    assert _razon(_read(monkeypatch, capsys, documento)) == TEXTO_READ.format(p=documento)


def test_un_cat_relativo_ofrece_la_ruta_absoluta(monkeypatch, capsys, documento, tmp_path):
    razon = _razon(_shell(monkeypatch, capsys, "cat docs/informe.md", tmp_path))
    assert razon == TEXTO_SHELL.format(p=documento)


def test_un_cat_relativo_se_cruza_con_la_delegacion(monkeypatch, capsys, documento, tmp_path):
    from local_delegate import server

    razon = _razon(_shell(monkeypatch, capsys, "cat docs/informe.md", tmp_path))
    ofrecida = re.search(r'path="([^"]+)"', razon).group(1)
    # El modelo delega con la ruta que se le ofreció, y la nota tiene que estar a ese nombre.
    assert Path(ofrecida) == documento
    assert server._bloqueo_reciente(ofrecida) is not None
