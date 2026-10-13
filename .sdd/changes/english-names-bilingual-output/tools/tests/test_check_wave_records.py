"""Tests de `tools/check_wave_records.py` (plan §2.1).

uv run pytest .sdd/changes/english-names-bilingual-output/tools/tests -q -p no:cacheprovider
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_wave_records", TOOLS / "check_wave_records.py"
)
assert _spec is not None and _spec.loader is not None
cwr = importlib.util.module_from_spec(_spec)
sys.modules["check_wave_records"] = cwr
_spec.loader.exec_module(cwr)

RECORD = """# Ola X — prueba

- Mapping: `waves/X-mapping.csv` aprobado

## Controles positivos
| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| test_a | se quita el filtro | `assert (dest/"ajena").exists()` | sí |

## Llamadas `local_*` (sesión principal y cada agente)
| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente | `local_lint_summary` | resumen de la suite | útil |
| agente | `local_commit_msg` | borrador del commit | corregido |

## Llamadas `mcp__pycharm__*`
| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente | `rename_refactoring` | `a.py:3` VIEJO→NEW | ok |
| agente | `get_file_problems` | a.py | sin errores |
"""

MAPPING = """# approved-by-main: 2026-10-12
old,new,kind,definition,scope,method,reason,verified
VIEJO,NEW,constant,a.py:3@<module>,cross_module,pycharm,,ok
estado,state,variable,a.py:9@f,function_local,search_edit,variable local,
"""


def _waves(tmp_path: Path, record: str = RECORD, mapping: str = MAPPING) -> Path:
    waves = tmp_path / "waves"
    waves.mkdir()
    (waves / "X.md").write_text(record, encoding="utf-8")
    (waves / "X-mapping.csv").write_text(mapping, encoding="utf-8")
    return waves


def _run(tmp_path: Path, waves: Path) -> tuple[int, str]:
    out = tmp_path / "wave-records.txt"
    code = cwr.main(["--waves-dir", str(waves), "--out", str(out)])
    return code, out.read_text(encoding="utf-8")


def test_complete_record_passes(tmp_path):
    code, report = _run(tmp_path, _waves(tmp_path))
    assert code == 0, report
    assert "OK    X.md" in report


def test_fails_without_local_lint_summary_row(tmp_path):
    record = RECORD.replace("| agente | `local_lint_summary` | resumen de la suite | útil |\n", "")
    code, report = _run(tmp_path, _waves(tmp_path, record))
    assert code == 1
    assert "falta la fila de local_lint_summary" in report


def test_fails_when_renames_do_not_match_mapping(tmp_path):
    mapping = MAPPING + "OTRO,OTHER,function,a.py:20@<module>,module_local,pycharm,,\n"
    code, report = _run(tmp_path, _waves(tmp_path, mapping=mapping))
    assert code == 1
    assert "filas rename_refactoring (1) ≠ filas method=pycharm de los mappings (2)" in report


def test_fails_without_approval_verification_or_reason(tmp_path):
    mapping = MAPPING.replace("# approved-by-main: 2026-10-12\n", "").replace(",ok\n", ",\n")
    mapping = mapping.replace("variable local", "")
    code, report = _run(tmp_path, _waves(tmp_path, mapping=mapping))
    assert code == 1
    assert "sin la cabecera «# approved-by-main»" in report
    assert "VIEJO (cross_module) sin verificar" in report
    assert "fila search_edit sin motivo (estado)" in report


def test_fails_when_a_positive_control_lacks_its_assert(tmp_path):
    record = RECORD.replace('`assert (dest/"ajena").exists()`', "")
    code, report = _run(tmp_path, _waves(tmp_path, record))
    assert code == 1
    assert "control positivo sin el assert que disparó: test_a" in report
