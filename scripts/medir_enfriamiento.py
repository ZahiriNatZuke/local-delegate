#!/usr/bin/env python3
"""Aplica el criterio de P-4: si los numeros del enfriamiento se cambian, se quedan o no se sabe.

El criterio esta escrito en `verification.md` («Criterio de P-4») antes de encender el mecanismo, y
este script es quien lo aplica. Si el recuento se hiciera a mano, el criterio volveria a ser una
opinion. Lee dos ficheros de `LOG_DIR`:

- el log de uso (`usage-*.jsonl`): saltos por clase, fallos que cuentan y fallos al momento;
- `enfriamiento-eventos.jsonl`: los episodios. El log de uso no los puede reconstruir, porque
  guarda un evento por operacion y no ve el fallo del segundo salto ni el de los trozos siguientes.

Las ventanas de prueba de `LOG_DIR/test-windows.json` se aplican solas a las filas del log y a los
episodios, ademas de los tramos de `--excluir`; `--include-tests` desactiva las del fichero (no las
de `--excluir`). Los tramos se comparan como instantes con la regla de las ventanas (intervalo
cerrado, al segundo), no como cadenas.

Uso:
    uv run python scripts/medir_enfriamiento.py --desde 2026-09-16
    uv run python scripts/medir_enfriamiento.py --desde 2026-09-16 \\
        --excluir 2026-09-16T10:00,2026-09-16T11:30     # el fallo provocado de la tarea 30
    uv run python scripts/medir_enfriamiento.py --desde 2026-09-16 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from medir_adopcion import directorio_de_logs, leer, logs_de_uso

from local_delegate import test_windows
from local_delegate.enfriamiento import CLASES_QUE_CUENTAN, FICHERO_EVENTOS

#: Por debajo de cualquiera de los dos, el resultado es «no concluyente» (criterio de P-4).
MINIMO_EPISODIOS = 5
MINIMO_FALLOS = 10

CLASES = {clase.value for clase in CLASES_QUE_CUENTAN}

#: Las reglas en su orden de precedencia: se aplica solo la primera que se cumpla.
REGLAS = {
    1: ("R > 60 %: el modelo seguia roto al vencer", "T pasa a 240 s"),
    2: ("la mitad o mas de los episodios los abre un timeout de lectura", "N pasa a 2"),
    3: ("R < 20 % y 3 o mas operaciones desviadas por episodio", "T pasa a 60 s"),
    4: ("algun episodio llega a Tmax y vuelve a reentrar", "Tmax pasa a 1800 s"),
}


def _ts(evento: dict) -> str:
    return str(evento.get("ts", ""))


def _en_rango(ts: str, desde: str | None, hasta: str | None) -> bool:
    if desde and ts < desde:
        return False
    return not (hasta and ts >= hasta)


def _a_mano(excluidos: Iterable[tuple[str, str]]) -> test_windows.Windows:
    """Los tramos de `--excluir` como ventanas: la misma regla que las del fichero (REQ-002)."""
    ventanas = []
    for numero, (inicio, fin) in enumerate(excluidos, start=1):
        ventanas.append(
            test_windows.Window(
                id=f"excluir-{numero}",
                start=test_windows.parse_instant(inicio),
                end=test_windows.parse_instant(fin),
            )
        )
    return test_windows.Windows(windows=ventanas)


class _Filtro:
    """Quita lo de `--excluir` y, salvo `--include-tests`, lo de las ventanas del fichero, y cuenta
    cuanto quita cada fuente. Una fila que cae en las dos cuenta para `--excluir`."""

    def __init__(self, excluidos: list, include_tests: bool) -> None:
        self.a_mano = _a_mano(excluidos)
        self.fichero = (
            test_windows.Windows() if include_tests else test_windows.load(directorio_de_logs())
        )
        self.quitadas = {"manual": Counter(), "test_windows": Counter()}
        self.por_ventana: Counter = Counter()

    def deja(self, ts: str, que: str) -> bool:
        if self.a_mano.find(ts) is not None:
            self.quitadas["manual"][que] += 1
            return False
        ventana = self.fichero.find(ts)
        if ventana is not None:
            self.quitadas["test_windows"][que] += 1
            self.por_ventana[ventana] += 1
            return False
        return True


def episodios(eventos: list[dict], tmax_s: float) -> list[dict]:
    """Agrupa las transiciones en episodios: de un `entra` al `limpia` del mismo modelo.

    Un `reentra` o un `limpia` sin su `entra` es de un episodio empezado antes del registro: se
    ignora, porque no se sabe con que clase empezo.
    """
    abiertos: dict[str, dict] = {}
    todos: list[dict] = []
    for evento in sorted(eventos, key=_ts):
        modelo = str(evento.get("modelo"))
        tipo = evento.get("evento")
        en_tmax = float(evento.get("espera_s") or 0) >= tmax_s
        if tipo == "entra":
            episodio = {
                "modelo": modelo,
                "desde": _ts(evento),
                "clase": evento.get("clase"),
                "reentradas": 0,
                "en_tmax": int(en_tmax),
                "final": None,
            }
            abiertos[modelo] = episodio
            todos.append(episodio)
        elif tipo == "reentra" and modelo in abiertos:
            abiertos[modelo]["reentradas"] += 1
            abiertos[modelo]["en_tmax"] += int(en_tmax)
        elif tipo == "limpia" and modelo in abiertos:
            final = "recuperado" if evento.get("tras_vencer") else "exito_explicito"
            abiertos.pop(modelo)["final"] = final
    return todos


def veredicto(medida: dict) -> dict:
    n = medida["episodios"]
    if n < MINIMO_EPISODIOS or medida["fallos_que_cuentan"] < MINIMO_FALLOS:
        return {"resultado": "no concluyente", "regla": None, "anotadas": []}
    r = medida["R"]
    cumple = {
        1: r is not None and r > 0.6,
        2: medida["episodios_por_timeout"] * 2 >= n,
        3: r is not None and r < 0.2 and medida["operaciones_desviadas"] >= 3 * n,
        4: medida["episodios_que_reentran_en_tmax"] > 0,
    }
    cumplidas = [numero for numero in sorted(cumple) if cumple[numero]]
    if not cumplidas:
        return {"resultado": "se quedan", "regla": None, "anotadas": []}
    return {"resultado": "cambiar", "regla": cumplidas[0], "anotadas": cumplidas[1:]}


def medir(
    desde: str | None,
    hasta: str | None = None,
    excluidos: Iterable[tuple[str, str]] = (),
    tmax_s: float = 900.0,
    include_tests: bool = False,
) -> dict:
    excluidos = list(excluidos)
    filtro = _Filtro(excluidos, include_tests)
    usos = [
        evento
        for ruta in logs_de_uso()
        for evento in leer(ruta, None)
        if _en_rango(_ts(evento), desde, hasta) and filtro.deja(_ts(evento), "usage_rows")
    ]
    # Un minimo, no el total: con salto, el log solo ve el fallo del pedido y el ultimo.
    fallos = sum(1 for e in usos if e.get("error_class") in CLASES) + sum(
        1 for e in usos if e.get("fallback_class") == "modelo"
    )
    saltos = Counter(e["fallback_class"] for e in usos if e.get("fallback_class"))
    al_momento = sum(1 for e in usos if e.get("error") == "cooldown")
    delegaciones = sum(1 for e in usos if str(e.get("tool", "")).startswith("local_"))

    registro = leer(directorio_de_logs() / FICHERO_EVENTOS, None)
    eps = [
        ep
        for ep in episodios(registro, tmax_s)
        if _en_rango(ep["desde"], desde, hasta) and filtro.deja(ep["desde"], "episodes")
    ]
    # R solo sobre los episodios con desenlace conocido: reentraron, o se recuperaron tras vencer.
    con_desenlace = [ep for ep in eps if ep["reentradas"] or ep["final"] == "recuperado"]
    reentraron = [ep for ep in con_desenlace if ep["reentradas"]]

    medida = {
        "ventana_desde": desde or "(todo)",
        "ventana_hasta": hasta or "(ahora)",
        "excluidos": [list(tramo) for tramo in excluidos],
        "include_tests": include_tests,
        "excluded_manual": {
            "usage_rows": filtro.quitadas["manual"]["usage_rows"],
            "episodes": filtro.quitadas["manual"]["episodes"],
        },
        "excluded_tests": {
            "usage_rows": filtro.quitadas["test_windows"]["usage_rows"],
            "episodes": filtro.quitadas["test_windows"]["episodes"],
        },
        "test_windows": [
            {**w.to_json(), "removed": filtro.por_ventana.get(w.id, 0)}
            for w in filtro.fichero.windows
        ],
        "delegaciones": delegaciones,
        "fallos_que_cuentan": fallos,
        "saltos_por_clase": dict(saltos),
        "fallos_al_momento": al_momento,
        "operaciones_desviadas": saltos.get("enfriamiento", 0) + al_momento,
        "episodios": len(eps),
        "episodios_con_desenlace": len(con_desenlace),
        "episodios_que_reentraron": len(reentraron),
        "R": round(len(reentraron) / len(con_desenlace), 3) if con_desenlace else None,
        "episodios_por_timeout": sum(1 for ep in eps if ep["clase"] == "timeout_lectura"),
        "episodios_que_reentran_en_tmax": sum(1 for ep in eps if ep["en_tmax"] >= 2),
        "fuera_de_p4_fallos_al_momento_sobre_5_pct": delegaciones > 0
        and al_momento > 0.05 * delegaciones,
    }
    medida.update(veredicto(medida))
    return medida


def _tramo(texto: str) -> tuple[str, str]:
    inicio, _, fin = texto.partition(",")
    if not inicio or not fin:
        raise argparse.ArgumentTypeError("--excluir espera INICIO,FIN")
    try:
        al_reves = test_windows.parse_instant(inicio) > test_windows.parse_instant(fin)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--excluir: fecha ilegible ({exc})") from exc
    if al_reves:
        raise argparse.ArgumentTypeError("--excluir: el inicio va antes que el fin")
    return inicio, fin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desde", help="fecha ISO; se compara contra el `ts` del evento")
    parser.add_argument("--hasta", help="fecha ISO, exclusiva")
    parser.add_argument(
        "--excluir", type=_tramo, action="append", default=[], help="tramo INICIO,FIN a excluir"
    )
    parser.add_argument("--tmax", type=float, default=900.0, help="Tmax vigente en la ventana")
    parser.add_argument("--json", action="store_true", help="salida cruda")
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="no aplicar las ventanas de test-windows.json (las de --excluir siguen)",
    )
    args = parser.parse_args()

    m = medir(args.desde, args.hasta, args.excluir, args.tmax, include_tests=args.include_tests)
    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
        return 0

    print(
        f"Ventana: {m['ventana_desde']} a {m['ventana_hasta']}  ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)"
    )
    for inicio, fin in m["excluidos"]:
        print(f"  excluido: {inicio} a {fin}")
    a_mano, ventanas = m["excluded_manual"], m["excluded_tests"]
    print(f"  quitado por --excluir: {a_mano['usage_rows']} filas, {a_mano['episodes']} episodios")
    if m["include_tests"]:
        print("  ventanas de prueba: no aplicadas (--include-tests)")
    else:
        print(
            f"  quitado por ventanas de prueba: {ventanas['usage_rows']} filas, "
            f"{ventanas['episodes']} episodios"
        )
        for w in m["test_windows"]:
            if w["removed"]:
                fin = w["end"] or "abierta"
                print(f"    {w['id']}  {w['start']} a {fin}  {w['removed']}  {w['label']}")
    print()
    print(f"Delegaciones:              {m['delegaciones']}")
    print(f"Fallos que cuentan (min.): {m['fallos_que_cuentan']}  (minimo {MINIMO_FALLOS})")
    print(f"Saltos por clase:          {m['saltos_por_clase']}")
    print(f"Fallos al momento:         {m['fallos_al_momento']}")
    print(f"Operaciones desviadas:     {m['operaciones_desviadas']}")
    print()
    print(f"Episodios:                 {m['episodios']}  (minimo {MINIMO_EPISODIOS})")
    print(f"  con desenlace conocido:  {m['episodios_con_desenlace']}")
    print(f"  reentraron:              {m['episodios_que_reentraron']}  (R: {m['R']})")
    print(f"  abiertos por timeout:    {m['episodios_por_timeout']}")
    print(f"  reentran en Tmax:        {m['episodios_que_reentran_en_tmax']}")
    print()
    print(f"RESULTADO: {m['resultado']}")
    if m["regla"] is not None:
        motivo, cambio = REGLAS[m["regla"]]
        print(f"  regla {m['regla']}: {motivo} -> {cambio}")
    for numero in m["anotadas"]:
        print(f"  anotada para la ventana siguiente: regla {numero}: {REGLAS[numero][0]}")
    if m["fuera_de_p4_fallos_al_momento_sobre_5_pct"]:
        print()
        print("AVISO fuera de P-4: los fallos al momento pasan del 5 % de las delegaciones.")
        print("No cambia N, T ni Tmax: falta candidato, y eso es una pregunta sobre las cadenas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
