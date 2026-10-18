"""Replaces the home folder with `~` in the text evidence of this folder (no private paths)."""

import sys
from pathlib import Path

HOME = str(Path.home())
for path in Path(__file__).parent.rglob("*"):
    if path.suffix not in {".txt", ".json", ".jsonl", ".md"} or not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    new = text
    for form in (HOME, HOME.replace("\\", "/"), HOME.replace("\\", "\\\\")):
        new = new.replace(form, "~")
    if new != text:
        path.write_text(new, encoding="utf-8", newline="")
        print("sanitized", path.name, file=sys.stderr)
