"""Tests de `tools/make_mapping.py` (D13): una fila por definición y el reemplazo acotado.

Se corren aparte de la suite del paquete (viven en la carpeta del cambio):

    uv run pytest .sdd/changes/english-names-bilingual-output/tools/tests -q -p no:cacheprovider
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[3]

_spec = importlib.util.spec_from_file_location("make_mapping", TOOLS / "make_mapping.py")
assert _spec is not None and _spec.loader is not None
mm = importlib.util.module_from_spec(_spec)
sys.modules["make_mapping"] = mm
_spec.loader.exec_module(mm)


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """Repo mínimo: el detector y su léxico reales más los ficheros de prueba."""
    (tmp_path / "scripts" / "data").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "detect_spanish_names.py", tmp_path / "scripts")
    for name in ("spanish_lexicon.json", "reserved_words.json"):
        shutil.copy(REPO / "scripts" / "data" / name, tmp_path / "scripts" / "data")
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
    return tmp_path


# --- build: una fila por definición -------------------------------------------
def test_two_same_name_locals_in_two_files_are_two_function_local_rows(tmp_path):
    root = _tree(
        tmp_path,
        {
            "src/local_delegate/uno.py": "def a():\n    estado = 1\n    return estado\n",
            "src/local_delegate/dos.py": "def b():\n    estado = 2\n    return estado + 1\n",
        },
    )
    rows = [r for r in mm.build_rows(root, []) if r["old"] == "estado"]
    assert len(rows) == 2, rows
    assert {r["scope"] for r in rows} == {"function_local"}
    assert {r["definition"] for r in rows} == {
        "src/local_delegate/uno.py:2@a",
        "src/local_delegate/dos.py:2@b",
    }
    assert {r["method"] for r in rows} == {"search_edit"}
    assert all(r["reason"] for r in rows)


def test_scopes_cross_module_module_local_unreferenced_test_and_unresolved(tmp_path):
    root = _tree(
        tmp_path,
        {
            "src/local_delegate/__init__.py": "",
            "src/local_delegate/cuota.py": (
                "LIMITE_DIARIO = 3\n"
                "def calcular_resto(x):\n    return x - LIMITE_DIARIO\n"
                "def ayuda_privada():\n    return calcular_resto(1)\n"
                "def leida_por_nombre():\n    return 0\n"
            ),
            "src/local_delegate/otro.py": (
                "from local_delegate.cuota import calcular_resto\n"
                "def usa():\n    return calcular_resto(2)\n"
            ),
            "tests/test_cuota.py": (
                "import local_delegate.cuota as cuota\n"
                "def test_el_resto_cuadra(monkeypatch):\n"
                "    monkeypatch.setattr(cuota, 'leida_por_nombre', lambda: 1)\n"
                "    assert cuota.LIMITE_DIARIO == 3\n"
            ),
        },
    )
    rows = mm.build_rows(root, [])
    by_name = {r["old"]: r for r in rows if r["kind"] != "module"}
    by_name["cuota"] = next(r for r in rows if r["kind"] == "module")
    # El alias `as cuota` del test es otra definición, en otra fila.
    assert any(r["kind"] == "import_alias" and r["old"] == "cuota" for r in rows)
    assert by_name["calcular_resto"]["scope"] == "cross_module"
    assert by_name["LIMITE_DIARIO"]["scope"] == "cross_module"  # `cuota.LIMITE_DIARIO` en el test
    assert by_name["ayuda_privada"]["scope"] == "module_local"
    assert by_name["leida_por_nombre"]["scope"] == "unresolved"
    assert by_name["test_el_resto_cuadra"]["scope"] == "unreferenced_test"
    assert by_name["cuota"]["kind"] == "module" and by_name["cuota"]["scope"] == "cross_module"
    assert by_name["calcular_resto"]["method"] == "pycharm"


def test_a_flat_import_between_sibling_scripts_counts_as_cross_module(tmp_path):
    """Los hooks se importan entre ellos por `sys.path[0]` (`from hook_common import x`), no por
    el paquete. En la ola A2 eso dejó como `module_local` nueve símbolos que sí se usaban fuera."""
    root = _tree(
        tmp_path,
        {
            "src/local_delegate/resources/hooks/comun.py": (
                "def estado_del_bloqueo():\n    return 1\n"
                "def solo_aqui():\n    return estado_del_bloqueo()\n"
                "def importado_entero():\n    return 2\n"
            ),
            "src/local_delegate/resources/hooks/lector.py": (
                "from comun import estado_del_bloqueo\n"
                "import comun\n"
                "def principal():\n    return estado_del_bloqueo() + comun.importado_entero()\n"
            ),
        },
    )
    by_name = {r["old"]: r for r in mm.build_rows(root, []) if r["kind"] == "function"}
    assert by_name["estado_del_bloqueo"]["scope"] == "cross_module"
    assert by_name["importado_entero"]["scope"] == "cross_module"
    # Control: lo que nadie importa sigue siendo local.
    assert by_name["solo_aqui"]["scope"] == "module_local"


def test_paths_filters_by_definition_file(tmp_path):
    root = _tree(
        tmp_path,
        {
            "src/local_delegate/uno.py": "def a():\n    estado = 1\n    return estado\n",
            "src/local_delegate/dos.py": "def b():\n    estado = 2\n    return estado\n",
        },
    )
    rows = mm.build_rows(root, ["src/local_delegate/uno.py"])
    assert {r["definition"].split(":")[0] for r in rows} == {"src/local_delegate/uno.py"}


# --- apply: reemplazo acotado a la función ------------------------------------
SOURCE_FILE = (
    "def first():\r\n"
    "    estado = 1\r\n"
    "    texto = f'{estado}'\r\n"
    "    return estado, texto\r\n"
    "\r\n"
    "\r\n"
    "def second(estado):\r\n"
    "    resultado = {'estado': estado}\r\n"
    "    return resultado['estado'] + estado\r\n"
    "\r\n"
    "\r\n"
    "def test_algo_viejo():\r\n"
    "    assert second(1) == 2\r\n"
)


def _mapping(tmp_path: Path, rows: list[dict[str, str]], approved: bool = True) -> Path:
    path = tmp_path / "waves" / "X-mapping.csv"
    mm.write_mapping(rows, path, "X")
    if approved:
        text = path.read_text(encoding="utf-8")
        path.write_text("# approved-by-main: 2026-10-12\n" + text, encoding="utf-8", newline="")
    return path


def _row(old, new, definition, scope="function_local", kind="variable"):
    return dict(  # noqa: C408
        old=old, new=new, kind=kind, definition=definition, scope=scope,
        method="search_edit", reason="prueba", verified="",
    )  # fmt: skip


def test_same_name_locals_in_two_functions_each_get_their_own_name(tmp_path):
    root = _tree(tmp_path, {"tests/test_x.py": SOURCE_FILE})
    mapping = _mapping(
        tmp_path,
        [
            _row("estado", "state", "tests/test_x.py:2@first"),
            _row("estado", "status_value", "tests/test_x.py:7@second", kind="param"),
            _row("test_algo_viejo", "test_something_old", "tests/test_x.py:12@<module>",
                 scope="unreferenced_test", kind="function"),
        ],
    )  # fmt: skip
    mm.apply_mapping(mapping, root)
    text = (root / "tests" / "test_x.py").read_bytes().decode("utf-8")
    head, tail = text.split("def second")
    assert "estado" not in head.replace("'estado'", "")
    assert "    state = 1\r\n" in head and "f'{state}'" in head
    # La segunda función tiene SU nombre, no el de la primera.
    assert "def second(status_value):" not in head
    tail = "def second" + tail
    assert "def second(status_value):" in tail
    assert "return resultado['estado'] + status_value" in tail
    assert "state" not in tail.replace("status_value", "")
    # Las claves de cadena no se tocan; el test se renombra en su def.
    assert "{'estado': status_value}" in tail
    assert "def test_something_old():" in tail
    # Los finales de línea siguen siendo CRLF, todos.
    assert text.count("\r\n") == SOURCE_FILE.count("\r\n") and "\n" not in text.replace("\r\n", "")


def test_unapproved_mapping_is_not_applied(tmp_path):
    root = _tree(tmp_path, {"tests/test_x.py": SOURCE_FILE})
    mapping = _mapping(tmp_path, [_row("estado", "state", "tests/test_x.py:2@first")], False)
    try:
        mm.apply_mapping(mapping, root)
    except SystemExit as exc:
        assert "no está aprobado" in str(exc)
    else:
        raise AssertionError("se aplicó un mapping sin «# approved-by-main»")
    assert (root / "tests" / "test_x.py").read_bytes().decode("utf-8") == SOURCE_FILE
