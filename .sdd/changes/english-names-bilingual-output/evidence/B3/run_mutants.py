"""Mutantes de la ola B3: aplica cada uno, corre SOLO su test, mira QUE assert salta y revierte.

Uso (desde la raiz del arbol, con el cerrojo de pesados):
    bash ~/.claude/scripts/pesado.sh .venv/Scripts/python.exe \
        .sdd/changes/english-names-bilingual-output/evidence/B3/run_mutants.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
HOOKS = "src/local_delegate/resources/hooks/"

# (nombre, fichero, viejo, nuevo, test, texto que tiene que aparecer en la salida del fallo)
MUTANTS = [
    (
        "M1 import del paquete en un hook",
        HOOKS + "suggest_delegate_prompt.py",
        "import json\n",
        "import json\nimport local_delegate  # mutante\n",
        "tests/test_hook_texts.py::test_no_hook_imports_the_package",
        "assert ['local_delegate'] == []",
    ),
    (
        "M2 tilde en HOOK_TEXTS",
        HOOKS + "hook_common.py",
        '"read.strength.suggest": "Sugerencia",',
        '"read.strength.suggest": "Sugerencía",',
        "tests/test_i18n_parity.py::test_the_hook_texts_have_parity_and_are_ascii",
        "read.strength.suggest: no es ASCII en es",
    ),
    (
        "M3 hook tocado sin regenerar el conjunto",
        HOOKS + "suggest_delegate_shell.py",
        'if __name__ == "__main__":\n',
        '# mutante\nif __name__ == "__main__":\n',
        "tests/test_hook_boundaries.py::test_the_current_hash_of_each_hook_is_in_the_set",
        "corre `uv run python scripts/bump_version.py --boundaries`",
    ),
    (
        "M4 regenerar sustituye en vez de unir",
        "scripts/bump_version.py",
        "data[name] = sorted(set(data.get(name, [])) | {digest})",
        "data[name] = [digest]",
        "tests/test_hook_boundaries.py::test_regenerating_after_a_change_keeps_the_old_hash",
        "la regeneración sustituyó en vez de unir",
    ),
    (
        "M5 tramo por fecha en vez de por huella",
        "scripts/measure_adoption.py",
        "    return measurement_boundaries.AFTER if in_set else measurement_boundaries.BEFORE\n",
        (
            '    late = str(event.get("ts", "")) >= "2026-10-01"\n'
            "    return measurement_boundaries.AFTER if late else measurement_boundaries.BEFORE\n"
        ),
        "tests/test_hook_boundaries.py::test_two_machines_an_old_hash_with_a_later_date_stays_before",
        "assert 'after' == 'before'",
    ),
    (
        "M6 los hooks ignoran el idioma (siempre es)",
        HOOKS + "hook_common.py",
        '    texts = HOOK_TEXTS.get(lang or hook_language()) or HOOK_TEXTS["en"]\n',
        '    texts = HOOK_TEXTS["es"]\n',
        "tests/test_hook_texts.py::test_the_installed_hook_answers_in_the_preferred_language",
        "Sugerencia: este archivo pesa 39 KB.",
    ),
    (
        "M7 el guardian deja de saltarse solo HOOK_TEXTS de su fichero",
        "tests/test_no_uncatalogued_text.py",
        "    names = {name for file, name in INLINE_CATALOGS if file == rel}\n",
        "    names = {name for _file, name in INLINE_CATALOGS}\n",
        "tests/test_no_uncatalogued_text.py::test_the_hook_catalog_is_skipped_only_in_its_file",
        "assert 'Hola, mundo' in",
    ),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failures = 0
    for name, rel, old, new, test, expected in MUTANTS:
        path = ROOT / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(old) != 1:
            print(f"{name}: NO MUTA (el texto viejo aparece {text.count(old)} veces)")
            failures += 1
            continue
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            run = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test],
                cwd=ROOT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        finally:
            path.write_bytes(original)
        out = run.stdout + run.stderr
        caught = run.returncode != 0 and expected in out
        failures += not caught
        verdict = "CAZADO por el assert esperado" if caught else "NO CAZADO o por otro assert"
        print(f"{name}: rc={run.returncode} -> {verdict}")
        if not caught:
            print(out[-1500:])
    print("RESULT:", "OK" if failures == 0 else f"{failures} mutantes sin cazar")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
