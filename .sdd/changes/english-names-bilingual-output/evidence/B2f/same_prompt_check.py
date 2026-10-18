"""B2f: which prompts are the SAME in `main` and in the branch (copy of the B2e check).

For each call of `manifest.json` it runs the tool in each checkout with a fake backend (every step
answers "- nota") and hashes the `system` + `user` of EVERY step it sends: the single
call of every window of `manifest.json` (G, GE, H, HE, M, ME, A, B). A call with the same hashes
in both versions is a control: any difference there between `main` and the branch measured live is
noise of the model, not effect of the change. `LOCAL_DELEGATE_LONG_INPUT_CHARS` of a window (H, HE)
is set on `config`, which reads it at import.

    uv run --frozen python .sdd/changes/english-names-bilingual-output/evidence/B2f/same_prompt_check.py D:/Projects/ld-wt-b2f-main
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]

PROBE = r"""
import hashlib, json, os, pathlib, sys, tempfile
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text("utf-8"))
root = pathlib.Path(sys.argv[2])
from local_delegate import config, i18n, server
config.FEEDBACK_ENABLED = False
tmp = pathlib.Path(tempfile.mkdtemp())
config.LOG_DIR = tmp
config.USAGE_LOG = tmp / "usage.jsonl"
seen = []
def run_chat(model, system, user, max_tokens, temperature, **_):
    seen.append(hashlib.sha256((system + "\0" + user).encode()).hexdigest())
    result = server.ChatResult(text="- nota", ok=True, finish_reason="stop")
    return result, 0, None, [server.Attempt(model, True, None, None, 0)]
server._run_chat = run_chat
long_default = config.MAX_CHARS_BY_ROLE["long"]
threshold_default = config.LONG_INPUT_CHARS
out = {}
for call in manifest["calls"]:
    for name in ("LOCAL_DELEGATE_LANG", "LOCAL_DELEGATE_OUTPUT_LANGUAGE"):
        os.environ.pop(name, None)
    env = dict(manifest["windows"][call["window"]]["env"])
    config.MAX_CHARS_BY_ROLE["long"] = int(env.pop("LOCAL_DELEGATE_MAX_CHARS_LONG", long_default))
    config.LONG_INPUT_CHARS = int(env.pop("LOCAL_DELEGATE_LONG_INPUT_CHARS", threshold_default))
    os.environ.update(env)
    i18n.reset()
    seen.clear()
    getattr(server, call["tool"])(path=str((root / call["document"]).resolve()))
    out[call["id"]] = list(seen)
print(json.dumps(out))
"""


def _hashes(checkout: Path) -> dict[str, list[str]]:
    command = [
        "uv",
        "run",
        "--frozen",
        "python",
        "-c",
        PROBE,
        str(HERE / "manifest.json"),
        str(ROOT),
    ]
    done = subprocess.run(command, cwd=checkout, capture_output=True, text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def main(main_checkout: str) -> None:
    before = _hashes(Path(main_checkout))
    after = _hashes(ROOT)
    report = {}
    for cid, steps in after.items():
        old = before[cid]
        report[cid] = {
            "steps_main": len(old),
            "steps_branch": len(steps),
            "identical": old == steps,
            "same_steps": sum(a == b for a, b in zip(old, steps, strict=False)),
        }
    out = HERE / "same-prompt-check.json"
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({cid: r["identical"] for cid, r in report.items()}))


if __name__ == "__main__":
    main(sys.argv[1])
