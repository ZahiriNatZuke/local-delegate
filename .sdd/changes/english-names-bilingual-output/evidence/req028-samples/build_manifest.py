"""Freezes the manifest of the REQ-028 closing samples (explain_code/describe_image and fr).

Writes `manifest.json` next to this file with the sha256 of every document, before any call.
Run once from the repo root: `python .sdd/changes/.../req028-samples/build_manifest.py`.
"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
EV = ".sdd/changes/english-names-bilingual-output/evidence"

# Code documented in English (target es) and in Spanish (target en); < 200 lines, one chunk.
CODE_EN = [
    "src/local_delegate/lint_patterns.py",
    f"{EV}/B2d-3/check_controls.py",
    f"{EV}/B2f/compare.py",
    f"{EV}/B2-affinity/scorer_v2_check.py",
    f"{EV}/B2e/validate_counter.py",
]
CODE_ES = [
    "src/local_delegate/pricing.py",
    "src/local_delegate/entrypoint.py",
    "scripts/build_site.py",
    "scripts/clean_watcher_fixtures.py",
    "scripts/sync_wiki.py",
]
# Panel captures with the interface in English (target es) and in Spanish (target en).
IMG_EN = [
    f"{EV}/B4/screenshots/dialog-cost-en-light.png",
    f"{EV}/B4/screenshots/dialog-cost-en-dark.png",
    f"{EV}/B4/screenshots/header-en-dark.png",
    f"{EV}/B4/screenshots/panel-en-light.png",
    f"{EV}/live-036/panel-en-US-dark.png",
]
IMG_ES = [
    f"{EV}/B4/screenshots/dialog-cost-es-light.png",
    f"{EV}/B4/screenshots/dialog-cost-es-dark.png",
    f"{EV}/B4/screenshots/header-es-dark.png",
    f"{EV}/B4/screenshots/panel-es-light.png",
    f"{EV}/live-035/panel-claro.png",
]
# fr: documents in Spanish and English (none in French), already used by B2d-2.
DOCS = f"{EV}/B2d-fix"
FR_SUMMARIZE = [
    f"{DOCS}/docs-3/es-doc-docs_recipes_claude-code-hooks.md",
    f"{DOCS}/docs-3/es-doc-docs_recipes_remote-backend.md",
    f"{DOCS}/docs-3/es-doc-docs_recipes_llama-swap-groups.md",
    f"{DOCS}/docs-3/en-doc-identify-2.6.19.METADATA.md",
    f"{DOCS}/docs-3/en-doc-pycparser-3.0.METADATA.md",
]
FR_LINT = [
    f"{DOCS}/docs-2/en-log-ruff-concise.txt",
    f"{DOCS}/docs-2/en-log-pytest.txt",
    f"{DOCS}/docs-3/en-log-tsc-angular.txt",
    f"{DOCS}/docs-2/es-log-B1b_doctor_es_complete.txt",
    f"{DOCS}/docs-3/es-log-check-llamaswap-pre-b10909.txt",
]
FR_CODE = [CODE_EN[0], CODE_EN[1], CODE_ES[0], CODE_ES[1], CODE_ES[2]]
FR_IMG = [IMG_EN[0], IMG_EN[3], IMG_ES[0], IMG_ES[3], IMG_ES[4]]

WINDOWS = {
    "ES": {
        "product": "es",
        "requested": "es",
        "env": {},
        "label": "REQ-028 muestras es (explain_code, describe_image)",
        "runnable_without_restart": True,
    },
    "EN": {
        "product": "en",
        "requested": "en",
        "env": {"LOCAL_DELEGATE_LANG": "en"},
        "label": "REQ-028 muestras en (explain_code, describe_image)",
        "runnable_without_restart": False,
    },
    "FR": {
        "product": "es",
        "requested": "fr",
        "env": {"LOCAL_DELEGATE_OUTPUT_LANGUAGE": "fr"},
        "label": "REQ-028 muestras fr (4 tools)",
        "runnable_without_restart": False,
    },
}


def _calls() -> list[dict]:
    plan = [
        ("ES", "local_explain_code", "E", CODE_EN),
        ("ES", "local_describe_image", "I", IMG_EN),
        ("EN", "local_explain_code", "E", CODE_ES),
        ("EN", "local_describe_image", "I", IMG_ES),
        ("FR", "local_summarize", "S", FR_SUMMARIZE),
        ("FR", "local_lint_summary", "L", FR_LINT),
        ("FR", "local_explain_code", "E", FR_CODE),
        ("FR", "local_describe_image", "I", FR_IMG),
    ]
    calls = []
    for window, tool, prefix, docs in plan:
        for n, doc in enumerate(docs, start=1):
            digest = hashlib.sha256((ROOT / doc).read_bytes()).hexdigest()
            calls.append(
                {
                    "id": f"{window}-{prefix}{n:02d}",
                    "window": window,
                    "tool": tool,
                    "document": doc,
                    "document_sha256": digest,
                }
            )
    return calls


def main() -> None:
    manifest = {
        "frozen_before_any_measurement_call": True,
        "repeat": 3,
        "criterion": (
            "Per window and tool, over the 15 answers (5 documents x 3 repetitions): at least "
            "90 % with verdict `requested` (errors and not_judgeable count as misses) and 0 "
            "`opposite`. es/en: scripts/judge_response_language.py; fr: fr_judge.py."
        ),
        "windows": WINDOWS,
        "calls": _calls(),
    }
    out = HERE / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(manifest['calls'])} calls -> {out}")


if __name__ == "__main__":
    main()
