"""Criterio de calibración (REQ-055 y REQ-056), en funciones puras, y los escenarios de la spec.

Sin datos: solo comprueba la aritmética que cita la spec. `calibracion.py` importa estas mismas
funciones para aplicarlas a los puntos reales.

Uso: python -I criterio.py
"""

import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

UMBRAL = 0.25
MIN_PUNTOS = 3


def dispersion(cs):
    """Mediana, sobre los puntos, de |C_i − mediana(C_j≠i)| / mediana(C_j≠i)."""
    errs = []
    for i, c in enumerate(cs):
        resto = cs[:i] + cs[i + 1 :]
        m = statistics.median(resto)
        errs.append(abs(c - m) / m)
    return statistics.median(errs)


def deriva(cs):
    """Índice del primer punto vigente tras la última deriva, o None si no la hubo.
    `cs` en orden cronológico (fin de ventana). Se recorre en orden: con un tramo vigente que
    empieza en `s`, hay deriva en el par (j−1, j) si el tramo tiene al menos MIN_PUNTOS puntos antes
    de j−1 y los dos se alejan más del 25 % de la mediana de esos puntos, en el mismo sentido.
    Entonces el tramo vigente pasa a empezar en j−1 (los anteriores dejan de contar)."""
    s, hubo = 0, False
    for j in range(len(cs)):
        if j - 1 - s < MIN_PUNTOS:
            continue
        m = statistics.median(cs[s : j - 1])
        d1, d2 = (cs[j - 1] - m) / m, (cs[j] - m) / m
        if abs(d1) > UMBRAL and abs(d2) > UMBRAL and (d1 > 0) == (d2 > 0):
            s, hubo = j - 1, True
    return s if hubo else None


def evalua(cs):
    """Estado de un tipo de ventana a partir de las capacidades C de sus puntos del statusline
    vigentes, en orden cronológico."""
    k = deriva(cs)
    if k is not None:
        cs = cs[k:]
    if len(cs) < MIN_PUNTOS:
        return {
            "estado": "sin calibrar",
            "motivo": f"faltan {MIN_PUNTOS - len(cs)} puntos",
            "deriva": k is not None,
        }
    d = dispersion(cs)
    if d >= UMBRAL:
        return {
            "estado": "sin calibrar",
            "motivo": f"dispersión {d:.1%} ≥ 25 %",
            "deriva": k is not None,
        }
    return {
        "estado": "calibrado",
        "mediana_C": statistics.median(cs),
        "dispersion": round(d, 3),
        "deriva": k is not None,
    }


if __name__ == "__main__":
    for nombre, cs in [
        ("gana", [150, 160, 170, 175]),
        ("un punto raro no lo tumba", [150, 160, 170, 175, 300]),
        ("dispersión alta", [100, 160, 250]),
        ("deriva: dos puntos altos seguidos", [150, 160, 170, 175, 230, 240]),
        ("no es deriva: dos puntos en sentidos opuestos", [150, 160, 170, 175, 230, 100]),
        ("deriva y luego se recalibra", [150, 160, 170, 175, 230, 240, 235]),
    ]:
        print(f"{nombre}: {cs} -> {evalua(cs)}")
    # aritmética del escenario de coste (Opus 5.5 en subagente, 1 000 000 chars de prosa por path)
    t = 1_000_000 * 100 // 200
    print("tokens de 1 000 000 chars de prosa por path (familia nueva, formato Read):", t)
    print(
        "cota baja $",
        round(t * 5 / 1e6, 2),
        "· estimación con N=40, 0 caducidades $",
        round(t * (5 + 40 * 0.20) / 1e6, 2),
    )
