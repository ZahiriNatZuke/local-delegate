"""B2f: the criterion of the plan (section B2f), applied to `main` and one tag of the branch.

Reads `score-<tag>.json` (written by `score_b2f.py --out`) and `same-prompt-check.json`, and prints
each condition with its numbers. The calls with the same prompt in both versions give the noise.

    uv run --frozen python compare.py main c1
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
LONG = {"long_es": "G", "long_en": "GE", "forced_long_es": "H", "forced_long_en": "HE"}
WATCHED = ("A14", "A15", "B31", "B32")


def _rows(tag: str) -> list[dict]:
    return json.loads((HERE / f"score-{tag}.json").read_text(encoding="utf-8"))["rows"]


def _avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(mean(values), 4) if values else None


def main(base: str, tag: str) -> None:
    same = {
        k
        for k, v in json.loads((HERE / "same-prompt-check.json").read_text()).items()
        if v["identical"]
    }
    rows = {"main": _rows(base), "branch": _rows(tag)}

    def group(version: str, window: str) -> list[dict]:
        return [r for r in rows[version] if r["window"] == window]

    noise_rows = {v: [r for r in rows[v] if r["id"] in same] for v in rows}
    noise_fid = abs(
        _avg(r["fidelity_total"] for r in noise_rows["branch"])
        - _avg(r["fidelity_total"] for r in noise_rows["main"])
    )
    noise_cut = abs(
        sum(r["finish_reason"] == "length" for r in noise_rows["branch"])
        - sum(r["finish_reason"] == "length" for r in noise_rows["main"])
    )
    out: dict = {
        "noise": {
            "calls": len(noise_rows["branch"]),
            "fidelity_mean_diff": noise_fid,
            "cut_diff": noise_cut,
        }
    }
    table = {}
    for name, window in LONG.items():
        table[name] = {
            v: {
                "codes": _avg(r["codes"] for r in group(v, window)),
                "files": _avg(r["files"] for r in group(v, window)),
                "model_codes": _avg(r["model_codes"] for r in group(v, window)),
                "model_files": _avg(r["model_files"] for r in group(v, window)),
                "fidelity_mean": _avg(r["fidelity_total"] for r in group(v, window)),
                "cut": sum(r["finish_reason"] == "length" for r in group(v, window)),
                "calls": len(group(v, window)),
            }
            for v in rows
        }
    for name in ("mechanical_es", "mechanical_en"):
        window = "M" if name.endswith("es") else "ME"
        table[name] = {
            v: {
                "codes": _avg(r["codes"] for r in group(v, window)),
                "model_codes": _avg(r["model_codes"] for r in group(v, window)),
                "files": _avg(r["files"] for r in group(v, window)),
                "fidelity_mean": _avg(r["fidelity_total"] for r in group(v, window)),
                "cut": sum(r["finish_reason"] == "length" for r in group(v, window)),
            }
            for v in rows
        }
    out["table"] = table
    long_rows = {v: [r for r in rows[v] if r["window"] in LONG.values()] for v in rows}
    es = {v: [r for r in long_rows[v] if r["window"] in ("G", "H")] for v in rows}
    fid = {v: _avg(r["fidelity_total"] for r in long_rows[v]) for v in rows}
    cut = {v: sum(r["finish_reason"] == "length" for r in long_rows[v]) for v in rows}
    es_model = {v: _avg(r["model_codes"] for r in es[v]) for v in rows}
    watched = {
        cid: {
            v: {
                "fidelity": sum(r["fidelity_total"] for r in rows[v] if r["id"] == cid),
                "cut": sum(r["finish_reason"] == "length" for r in rows[v] if r["id"] == cid),
                "codes": _avg(r.get("codes") for r in rows[v] if r["id"] == cid),
            }
            for v in rows
        }
        for cid in WATCHED
    }
    out["watched"] = watched
    c = {
        "1_reader_codes_files_ge_0.9": all(
            table[n]["branch"]["codes"] >= 0.9 and table[n]["branch"]["files"] >= 0.9 for n in LONG
        ),
        "2a_model_codes_not_worse": all(
            table[n]["branch"]["model_codes"] >= table[n]["main"]["model_codes"] for n in LONG
        ),
        "2b_es_model_codes_plus_0.2": es_model["branch"] >= es_model["main"] + 0.2,
        "3_fidelity": fid["branch"] <= fid["main"] + noise_fid,
        "4_cut": cut["branch"] <= cut["main"] + noise_cut,
        "5_watched": all(
            w["branch"]["fidelity"] <= w["main"]["fidelity"] + 3 * noise_fid + 1e-9
            and w["branch"]["cut"] <= w["main"]["cut"]
            for w in watched.values()
        ),
    }
    out["long_totals"] = {"fidelity_mean": fid, "cut": cut, "es_model_codes": es_model}
    out["criterion"] = c
    out["met"] = all(c.values())
    text = json.dumps(out, indent=1)
    (HERE / f"compare-{base}-{tag}.json").write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
