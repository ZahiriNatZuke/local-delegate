"""Cuenta, caso a caso y campo a campo, que difiere entre el corpus de afinidad reconstruido y el versionado."""

import collections
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "scripts")
import build_corpus as b

from local_delegate import legacy_names

target = b.AFFINITY_TARGET
v = legacy_names.normalize_affinity_corpus(
    json.loads((target / "cases.json").read_text(encoding="utf-8"))
)
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    (t / "fuentes").mkdir()
    b.build_affinity(b.ROOT, t, privacy=v["selection"]["privacy"])
    n = legacy_names.normalize_affinity_corpus(
        json.loads((t / "cases.json").read_text(encoding="utf-8"))
    )
vb = {c["id"]: c for c in v["cases"]}
cnt = collections.Counter()
for c in n["cases"]:
    o = vb.get(c["id"])
    if o is None:
        cnt[("nuevo", c["tool"])] += 1
        continue
    for k in set(c) | set(o):
        if c.get(k) != o.get(k):
            cnt[(k, c["tool"])] += 1
for k in set(n) - {"cases"}:
    if n.get(k) != v.get(k):
        cnt[("top:" + k, "-")] += 1
print("diferencias por (campo, tool):", dict(cnt), "total:", sum(cnt.values()))
