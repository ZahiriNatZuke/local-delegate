"""B2d-4, second round: which calls of set 3 send the SAME prompt in `main` and in the branch.

For each call it hashes `system` + the content that reaches the model (after
`compact_repeated_lines` when the version has it), with the languages of its batch, in each
checkout. A call whose hash is equal in both is a call the change does not touch: any difference
between the two versions there is noise of the model, not effect of the change.

    uv run python .sdd/changes/english-names-bilingual-output/evidence/B2d-4/same_prompt_check.py MAIN_CHECKOUT
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]

PROBE = r"""
import hashlib, json, os, pathlib, sys
from local_delegate import i18n, server
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text("utf-8"))
out = {}
for call in manifest["calls"]:
    for name in ("LOCAL_DELEGATE_LANG", "LOCAL_DELEGATE_OUTPUT_LANGUAGE"):
        os.environ.pop(name, None)
    os.environ.update(manifest["windows"][call["window"]]["env"])
    i18n.reset()
    content, _truncated, _raw = server._read_input(None, call["document"], server._NO_TRUNCATE)
    if hasattr(server, "compact_repeated_lines"):
        content, _groups = server.compact_repeated_lines(content)
    data = (server._lint_system(200) + "\0" + content).encode()
    out[call["id"]] = hashlib.sha256(data).hexdigest()
print(json.dumps(out))
"""


def _hashes(checkout: Path) -> dict[str, str]:
    manifest = str(HERE / "manifest.json")
    command = ["uv", "run", "--frozen", "python", "-c", PROBE, manifest]
    done = subprocess.run(command, cwd=checkout, capture_output=True, text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def main(main_checkout: str) -> None:
    before = _hashes(Path(main_checkout))
    after = _hashes(ROOT)
    print(json.dumps({cid: before[cid] == after[cid] for cid in after}))


if __name__ == "__main__":
    main(sys.argv[1])
