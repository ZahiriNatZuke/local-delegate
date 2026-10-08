#!/usr/bin/env python3
"""Responde, sin cruzar nada a mano, si la regla de delegacion esta funcionando.

Las cuatro mediciones anteriores se hicieron leyendo dos logs por separado y atandolos a ojo, y
por eso la pregunta central —«de los avisos que se dieron, cuantos acabaron en delegacion»— no
tenia respuesta: los dos lados son procesos distintos que escriben en ficheros distintos. Desde
F1 cada aviso y cada bloqueo llevan un identificador que el evento de la tool recoge, asi que el
cruce lo hace el programa.

Cuando la pregunta es «cuantos sitios hay», que la conteste el programa: contar a ojo ya salio
mal una vez en este repo, catorce contra treinta y cuatro.

Las pruebas no cuentan: los eventos de hooks dentro de una ventana de prueba
(`LOG_DIR/test-windows.json`) y las filas del log de uso que la regla comun
(`atribucion.test_reason`, con la ventana estampada) marca como prueba se quitan, y la salida dice
cuantas. `--include-tests` las deja.

Uso:
    uv run python scripts/medir_adopcion.py                      # desde que arranco el experimento
    uv run python scripts/medir_adopcion.py --desde 2026-09-12   # una ventana concreta
    uv run python scripts/medir_adopcion.py --json               # para pegarlo en una nota
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from local_delegate import atribucion, config, coste, test_windows


def telemetria_de_hooks() -> Path:
    destino = os.environ.get("LD_HOOK_TELEMETRY_LOG", "").strip()
    return Path(destino) if destino else Path.home() / ".claude" / "hooks" / "telemetry.jsonl"


def directorio_de_logs() -> Path:
    """`config.LOG_DIR`: el mismo directorio que leen el panel y el daemon, y por tanto el mismo
    `test-windows.json` (test-windows-out-of-metrics, REQ-022). Lo usa tambien
    `medir_enfriamiento.py`."""
    return config.LOG_DIR


def logs_de_uso() -> list[Path]:
    return sorted(directorio_de_logs().glob("usage-*.jsonl"))


def leer(ruta: Path, desde: str | None) -> list[dict]:
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    eventos = []
    for linea in lineas:
        try:
            evento = json.loads(linea)
        except ValueError:
            continue
        if desde and str(evento.get("ts", "")) < desde:
            continue
        eventos.append(evento)
    return eventos


def usos_fundidos(desde: str | None) -> list[dict]:
    """Las filas del log de uso FUNDIDAS como las ve el panel (`coste.fundir`): con el `banco` del
    relleno y el `test_window` estampado. Se funde el fichero entero y se filtra despues, porque la
    clave de una fila sin `tool_use_id` depende de su posicion en el fichero."""
    usos = []
    for ruta in logs_de_uso():
        for e in coste.fundir(leer(ruta, None), log_dir=directorio_de_logs()):
            if desde and str(e.get("ts", "")) < desde:
                continue
            usos.append(e)
    return usos


def medir(desde: str | None, include_tests: bool = False) -> dict:
    hooks = leer(telemetria_de_hooks(), desde)
    usos = usos_fundidos(desde)
    fuera = {"hooks": 0, "usage": 0}
    aplicadas: list[dict] = []
    if not include_tests:
        ventanas = test_windows.load(directorio_de_logs())
        aplicadas = [w.to_json() for w in ventanas.windows]
        antes = len(hooks)
        hooks = [e for e in hooks if ventanas.find(e.get("ts")) is None]
        fuera["hooks"] = antes - len(hooks)
        antes = len(usos)
        usos = [e for e in usos if not atribucion.test_reason(e)]
        fuera["usage"] = antes - len(usos)

    lecturas = [e for e in hooks if e.get("category") in {"read", "shell"}]
    ofrecidos = [e for e in lecturas if e.get("suggested")]
    bloqueos = [e for e in ofrecidos if e.get("blocked")]

    # «Aceptado» = el identificador del bloqueo aparece en un evento de tool. Sin esto, lo unico
    # medible era «hubo delegaciones», que no dice si las provoco el aviso.
    ids_delegados = {e["bloqueo_id"] for e in usos if e.get("bloqueo_id")}
    aceptados = [b for b in bloqueos if b.get("id") in ids_delegados]

    # De las lecturas acotadas, cuantas eran de un fichero que en la misma sesion acabo leyendose
    # entero: el criterio escrito ANTES de mirar el dato (REQ-F1-8).
    enteras_por_sesion: dict[tuple, set] = defaultdict(set)
    franjas_por_sesion: dict[tuple, int] = Counter()
    for evento in lecturas:
        clave = (evento.get("session_id", ""), evento.get("path_sha", ""))
        if not clave[1]:
            continue  # eventos viejos, sin huella: no se pueden agrupar
        if evento.get("motivo") == "acotada":
            franjas_por_sesion[clave] += 1
        else:
            enteras_por_sesion[clave].add(evento.get("motivo") or "aviso")

    acotadas = [c for c, n in franjas_por_sesion.items() if n]
    convenia = [c for c in acotadas if c in enteras_por_sesion or franjas_por_sesion[c] >= 3]

    return {
        "ventana_desde": desde or "(todo)",
        "sesiones": len({e.get("session_id") for e in lecturas if e.get("session_id")}),
        "versiones_de_script": sorted({e.get("version", "?") for e in lecturas}),
        "lecturas": len(lecturas),
        "por_motivo": dict(
            Counter(
                e.get("motivo") or ("(ofrecido)" if e.get("suggested") else "(sin motivo)")
                for e in lecturas
            )
        ),
        "por_camino": dict(Counter(e.get("camino", "read") for e in lecturas)),
        "ofrecidos": len(ofrecidos),
        "bloqueos": len(bloqueos),
        "aceptados": len(aceptados),
        "tasa_de_aceptacion": round(len(aceptados) / len(bloqueos), 3) if bloqueos else None,
        "delegaciones_totales": len([e for e in usos if e.get("tool", "").startswith("local_")]),
        "delegaciones_espontaneas": len(
            [e for e in usos if e.get("tool", "").startswith("local_") and not e.get("bloqueo_id")]
        ),
        "acotadas_con_huella": len(acotadas),
        "acotadas_que_convenia_delegar": len(convenia),
        "excluded_tests": fuera,
        "test_windows": aplicadas,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desde", help="fecha ISO; se compara contra el `ts` del evento")
    parser.add_argument("--json", action="store_true", help="salida cruda")
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="no quitar las pruebas (ventanas y regla comun)",
    )
    args = parser.parse_args()

    resultado = medir(args.desde, include_tests=args.include_tests)
    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0

    print(f"Ventana: {resultado['ventana_desde']}  ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)")
    print(
        f"Sesiones: {resultado['sesiones']} | versiones de script: {resultado['versiones_de_script']}"
    )
    fuera = resultado["excluded_tests"]
    if args.include_tests:
        print("Pruebas: incluidas (--include-tests)")
    else:
        print(
            f"Pruebas fuera: {fuera['hooks']} eventos de hooks y {fuera['usage']} filas del log de "
            f"uso ({len(resultado['test_windows'])} ventanas de prueba en el fichero)"
        )
    print()
    print(f"Lecturas vistas:        {resultado['lecturas']}")
    for motivo, cuantas in sorted(resultado["por_motivo"].items(), key=lambda x: -x[1]):
        print(f"    {motivo:20} {cuantas}")
    print(f"Por camino:             {resultado['por_camino']}")
    print()
    print(f"Ofrecidos:              {resultado['ofrecidos']}")
    print(f"  de ellos, bloqueos:   {resultado['bloqueos']}")
    print(
        f"  aceptados:            {resultado['aceptados']}  (tasa: {resultado['tasa_de_aceptacion']})"
    )
    print()
    print(f"Delegaciones totales:   {resultado['delegaciones_totales']}")
    print(f"  espontaneas:          {resultado['delegaciones_espontaneas']}")
    print()
    print("Guarda de lectura acotada (REQ-F1-8):")
    print(f"  agrupables por fichero: {resultado['acotadas_con_huella']}")
    print(f"  convenia delegarlas:    {resultado['acotadas_que_convenia_delegar']}")

    versiones = resultado["versiones_de_script"]
    if "?" in versiones:
        print()
        print("AVISO: hay eventos SIN version de script, o sea anteriores a que se registrara.")
        print("Esos no se pueden atribuir a una politica concreta; acota la ventana con --desde.")
    if len([v for v in versiones if v != "?"]) > 1:
        print()
        print("AVISO: hay mas de una version de script en la ventana. Una sesion abierta hereda")
        print("el entorno del lanzador, asi que la muestra puede mezclar dos politicas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
