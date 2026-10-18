import re
from pathlib import Path

from local_delegate import config, server

p = "src/local_delegate/cli.py"
content = Path(p).read_text(encoding="utf-8", errors="replace")
max_chars = config.max_chars_for_role("code")
budget = server._map_budget(max_chars)
names = server._format_names(server._TOP_LEVEL_NAME.findall(content), int(budget * 0.25))
pieces = server._code_pieces(content, budget)
print(
    "len",
    len(content),
    "max_chars",
    max_chars,
    "budget",
    budget,
    "pieces",
    len(pieces) if pieces else None,
)
print(
    "inventory has doctor:",
    "doctor" in names,
    "benchmark:",
    "benchmark" in names,
    "inventory chars",
    len(names),
)
subs = re.findall(r'add_parser\(\s*"([\w-]+)"', content)
print("literal subcommands", len(subs), subs[:60])
for i, pc in enumerate(pieces or [], 1):
    print(
        i,
        len(pc),
        "doctor" if 'add_parser("doctor"' in pc else "",
        "benchmark" if "benchmark.add_parser" in pc else "",
        "build_parser" if "def build_parser" in pc else "",
    )
print("partial tokens", (350 * 2) + 64, "reduce tokens", (250 * 2) + 64)
