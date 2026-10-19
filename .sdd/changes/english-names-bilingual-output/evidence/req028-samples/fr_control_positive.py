"""Positive control of `fr_judge.py`: French texts that are known to be French must come out `fr`.

Translates to French, with `local_translate` through the daemon's /mcp, five answers of the ES
window (explain_code and describe_image) and five B2d-2 answers (summarize/lint, es and en), and
writes them to `fr-control/<name>.txt`. The translations never go through a Claude context; then
`fr_judge.py` judges them (`fr-control-positive.jsonl`).

    python fr_control_positive.py
"""

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[4]
sys.path[:0] = [str(HERE), str(ROOT / "scripts"), str(ROOT / "src")]

import fr_judge
from measure_structured_summary import URL, _token

EV = HERE.parent
SOURCES = [
    ("ES-E01-r1", HERE / "answers/ES/ES-E01-r1.txt", ""),
    ("ES-E03-r1", HERE / "answers/ES/ES-E03-r1.txt", ""),
    ("ES-I01-r1", HERE / "answers/ES/ES-I01-r1.txt", ""),
    ("ES-I04-r1", HERE / "answers/ES/ES-I04-r1.txt", ""),
]


def _b2d2_sources() -> list[tuple[str, Path, str]]:
    manifest = json.loads((EV / "B2d-2/manifest.json").read_text(encoding="utf-8"))
    picked = []
    for wanted in ("A19", "A01", "B33", "B35"):
        for c in manifest["calls"]:
            if c["id"] == wanted:
                picked.append((wanted, ROOT / c["answer"], c["document"]))
    return picked


async def main() -> int:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    out_dir = HERE / "fr-control"
    out_dir.mkdir(exist_ok=True)
    sources = SOURCES + _b2d2_sources()
    headers = {"Authorization": f"Bearer {_token()}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=900) as client,
        streamable_http_client(URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        for name, path, _doc in sources:
            res = await session.call_tool(
                "local_translate", {"path": str(path.resolve()), "target_lang": "French"}
            )
            text = "".join(getattr(c, "text", "") for c in res.content)
            (out_dir / f"{name}.txt").write_text(text, encoding="utf-8", newline="")
            print(f"{name} chars={len(text)} error={res.is_error}", flush=True)
    words = fr_judge.load_words()
    rows = []
    for name, _path, doc in sources:
        document = (ROOT / doc).read_text(encoding="utf-8", errors="replace") if doc else ""
        text = (out_dir / f"{name}.txt").read_text(encoding="utf-8")
        rows.append({"id": name, **fr_judge.judge(text, document, words)})
    with (HERE / "fr-control-positive.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in rows:
        print(
            r["id"],
            r["verdict"],
            r["lang"],
            r["tokens"],
            r["fr_ratio"],
            r["es_ratio"],
            r["en_ratio"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
