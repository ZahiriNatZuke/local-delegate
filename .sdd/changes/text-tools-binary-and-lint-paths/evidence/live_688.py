"""Prueba en vivo de #688 en proceso: `local_lint_summary` de la rama contra el backend real.

Uso: python -I live_688.py <src_dir> <etiqueta> <salida.json>. La key llega por entorno.
"""

import json
import sys
from pathlib import Path

src, label, out = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, src)

from local_delegate import lint_patterns, server

clean = [f"tests/test_mod_{n:02d}.py" for n in range(14)]
rel = ".venv/Lib/site-packages/starlette/testclient.py"
log = (
    "============================= test session starts ==============================\n"
    "platform win32 -- Python 3.12.7, pytest-8.3.3, pluggy-1.5.0\n"
    "collected 283 items\n\n"
    + "".join(
        f"{f} {'.' * (10 + i)}{' ' * (40 - i)}[{round(100 * (i + 1) / 14):3d}%]\n"
        for i, f in enumerate(clean)
    )
    + "\n=============================== warnings summary ===============================\n"
    f"{rel}:53\n"
    "  C:\\work\\proj\\.venv\\Lib\\site-packages\\starlette\\testclient.py:53: DeprecationWarning: "
    "The 'app' shortcut is now deprecated. Use the explicit style 'transport=WSGITransport(app=...)' instead.\n"
    "    warnings.warn(\n\n"
    "-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html\n"
    "======================= 283 passed, 1 warning in 4.21s ========================\n"
)
path = Path(out).with_suffix(".log")
path.write_text(log, encoding="utf-8")
answers = []
for run in range(3):
    answer = server.local_lint_summary(path=str(path), max_words=80)
    body = answer.split("[local-delegate warning", 1)[0]
    entries = [c for c in clean if c in body]
    answers.append(
        {
            "run": run,
            "clean_named_in_body": len(entries),
            "warning": "[local-delegate warning" in answer,
            "clean_entries_by_program": lint_patterns.clean_file_entries(body, log)
            if hasattr(lint_patterns, "clean_file_entries")
            else None,
            "answer": answer,
        }
    )
Path(out).write_text(
    json.dumps({"label": label, "runs": answers}, ensure_ascii=False, indent=1), "utf-8"
)
print(label, [(a["clean_named_in_body"], a["warning"]) for a in answers])
