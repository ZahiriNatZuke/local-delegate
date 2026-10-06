# ruff: noqa: SIM115  (script de evidencia desechable del SDD, no es producto)
"""Recalcula la tabla de densidad (caracteres por token de Claude) de `insumos/densidad-por-modelo.md`.

Entrada: `insumos/datos/densidad-resultados.jsonl` (45 llamadas `claude -p` del 2026-10-06, con
`usage`; sin texto, solo «ok» o resúmenes de una línea de un commit público del repo).
Regla: cuerpo = entrada total de la celda − control estable (el último control del modelo, porque
los dos primeros de Opus 5.5 se midieron sin aislar los MCP); densidad = caracteres / cuerpo.
Para las celdas `*_read` se cuentan los caracteres del fichero ORIGINAL (sin numerar), que es lo
que conoce el daemon: prosa 9 543, python 9 958.

Uso: python -I densidad.py
"""

import json
import os

aqui = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(aqui, "..", "datos", "densidad-resultados.jsonl")
CHARS_ORIGINAL = {"prosa_read": 9543, "python_read": 9958}
filas = [json.loads(l) for l in open(F, encoding="utf-8")]
control = {}
for r in filas:
    if r["contenido"] == "control":
        control[r["modelo"]] = r["entrada_total"]  # el último gana
tabla = {}
for r in filas:
    c = r["contenido"]
    if c == "control" or r["tarea"] != "ok" or r["effort"]:
        continue
    cuerpo = r["entrada_total"] - control[r["modelo"]]
    chars = CHARS_ORIGINAL.get(c, r["chars"])
    tabla.setdefault(r["modelo"], {})[c] = [round(chars / cuerpo, 2), cuerpo, chars / cuerpo]
for fila in tabla.values():
    sin = [v[2] for k, v in fila.items() if not k.endswith("_read")]
    fila["_dispersion_contenidos_%"] = (
        round((max(sin) - min(sin)) / min(sin) * 100, 1) if len(sin) > 1 else None
    )
    for k, v in list(fila.items()):
        if isinstance(v, list):
            fila[k] = v[:2]
print(json.dumps(tabla, ensure_ascii=False, indent=1))
salida = {}
for r in filas:
    if r["tarea"] == "resumen":
        salida.setdefault(r["effort"], []).append(r["usage"]["output_tokens"])
print("salida por esfuerzo (tarea resumen):", salida)
ent = {}
for r in filas:
    if r["contenido"] == "diff" and r["modelo"] == "claude-opus-5-5":
        clave = f"tarea={r['tarea']} esfuerzo={r['effort'] or 'sin flag'}"
        ent.setdefault(clave, []).append(r["entrada_total"])
print("entrada con el diff en Opus 5.5, por tarea y esfuerzo:", ent)
