"""Unicidad de la clave del relleno (REQ-005) sobre los logs de uso de esta máquina.

Solo lectura; devuelve solo conteos. Compara tres claves candidatas para las líneas SIN
`tool_use_id` (el histórico):
- (ts, tool): la de la versión 2 de la spec;
- (ts, tool, chars_in, chars_out);
- (ts, tool, ordinal): ordinal = posición de la línea entre las de su misma (ts, tool), en el
  orden del fichero. Es la que adopta la spec.
Y comprueba que los `tool_use_id` presentes no se repiten.

Uso: python -I clave_relleno.py
"""

import collections
import glob
import json
import os

L = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~/.local/share")), "local-delegate"
)
lineas, con_id = [], collections.Counter()
for f in sorted(glob.glob(os.path.join(L, "usage-*.jsonl"))):
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("tool_use_id"):
                con_id[r["tool_use_id"]] += 1
                continue
            lineas.append(r)


def repetidas(claves):
    c = collections.Counter(claves)
    return {
        "claves_repetidas": sum(1 for v in c.values() if v > 1),
        "lineas_afectadas": sum(v for v in c.values() if v > 1),
    }


ordinal = collections.Counter()
k3 = []
for r in lineas:
    base = (r.get("ts"), r.get("tool"))
    k3.append(base + (ordinal[base],))
    ordinal[base] += 1
print(
    json.dumps(
        {
            "ficheros": len(glob.glob(os.path.join(L, "usage-*.jsonl"))),
            "lineas_sin_tool_use_id": len(lineas),
            "lineas_con_tool_use_id": sum(con_id.values()),
            "tool_use_id_repetidos": sum(1 for v in con_id.values() if v > 1),
            "(ts, tool)": repetidas((r.get("ts"), r.get("tool")) for r in lineas),
            "(ts, tool, chars_in, chars_out)": repetidas(
                (r.get("ts"), r.get("tool"), r.get("chars_in"), r.get("chars_out")) for r in lineas
            ),
            "(ts, tool, ordinal)": repetidas(k3),
        },
        ensure_ascii=False,
        indent=1,
    )
)
