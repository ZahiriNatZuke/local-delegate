#!/usr/bin/env python3
"""Etapa 1 del SDD `resumen-por-secciones`: ¿sigue `local_summarize` la estructura? Sin cuota.

Llama la tool por el `/mcp` del daemon (backend real) con las copias fijas de
`benchmarks/resumen-estructurado/fuentes/` y mide **en la salida de la tool**, no en la respuesta
de Claude:

- **cobertura**: títulos esperados emparejados por línea de título y en orden, **sin contar** los
  que completó el servidor (llevan «(sin resumir)»);
- **con contenido**: emparejados con al menos 5 palabras debajo;
- **fuera de orden**: títulos presentes pero fuera de su sitio;
- **palabras** del texto sin títulos ni avisos, contra `max_words`;
- `finish_reason`, `truncated_out` y latencia, del evento de uso de la llamada.

El emparejamiento es el de producción (`local_delegate.secciones`): una sola fuente. Por eso los
controles de `tests/test_medir_resumen_estructurado.py` llevan el resultado esperado escrito a
mano. El banco de T5 (`experimento_adopcion.cobertura_de_titulos`) no se toca: su línea base se
midió con su normalización.

Criterio (spec REQ-208, escrito antes de medir): pasa si en README, `Integration-install.md` y
`Daemon.md` la cobertura es ≥ 0,9, todos los emparejados tienen contenido y no hay fuera de orden;
el CHANGELOG, igual y sin `length`; el documento corto (4B), cobertura ≥ 0,9. Más el juicio del
usuario sobre los tres primeros, que este script no puede dar: deja las salidas en `--salidas`.

Solo guarda en el repo las métricas; las salidas (contenido) van fuera, a `%TEMP%`. El token del
daemon se lee de la variable de usuario `LOCAL_DELEGATE_WEB_TOKEN` y nunca se imprime.

Uso:
    uv run python scripts/medir_resumen_estructurado.py --etiqueta main
    uv run python scripts/medir_resumen_estructurado.py --etiqueta rama
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from local_delegate import secciones

RAIZ = Path(__file__).parents[1]
BANCO = RAIZ / "benchmarks" / "resumen-estructurado"
FUENTES = BANCO / "fuentes"
URL = "http://127.0.0.1:9393/mcp"
MINIMO_CONTENIDO = 5
UMBRAL = 0.9

LLAMADAS = [
    {"id": "readme", "fichero": "readme.md", "max_words": 500, "juicio": True},
    {"id": "instalacion", "fichero": "integration-install.md", "max_words": 500, "juicio": True},
    {"id": "daemon", "fichero": "daemon.md", "max_words": 500, "juicio": True},
    {"id": "changelog", "fichero": "changelog.md", "max_words": 500, "sin_length": True},
    {"id": "corto-4b", "fichero": "llama-swap-blackwell.md", "max_words": 500},
    {
        "id": "daemon-focus",
        "fichero": "daemon.md",
        "max_words": 500,
        "focus": "puertos, variables y rutas",
        "informativa": True,
    },
]

_AVISO = re.compile(r"^\s*(\[local-delegate [^\]]*\]|\((leído server-side|resumido de) .*\))\s*$")


# --- Métrica (pura) -------------------------------------------------------------------------------


def medir(salida: str, esperados: list[str], max_words: int) -> dict:
    """Las métricas de una salida frente a los títulos esperados del documento."""
    emp = secciones.emparejar(salida, esperados, minimo_contenido=MINIMO_CONTENIDO)
    lineas = salida.split("\n")
    orden = sorted(emp.pares.items(), key=lambda par: par[1])
    completadas = 0
    con_contenido = 0
    for pos, (_k, linea) in enumerate(orden):
        fin = orden[pos + 1][1] if pos + 1 < len(orden) else len(lineas)
        cuerpo = "\n".join(x for x in lineas[linea + 1 : fin] if not _AVISO.match(x)).strip()
        if cuerpo == secciones.SIN_RESUMIR:
            completadas += 1
        elif len(re.findall(r"\w+", cuerpo)) >= MINIMO_CONTENIDO:
            con_contenido += 1
    emparejados = len(emp.pares) - completadas
    titulos = {linea for linea, _ in secciones.lineas_de_titulo(salida)}
    palabras = sum(
        len(re.findall(r"\w+", x))
        for i, x in enumerate(lineas)
        if i not in titulos and not _AVISO.match(x) and x.strip() != secciones.SIN_RESUMIR
    )
    cobertura = emparejados / len(esperados) if esperados else 0.0
    return {
        "esperados": len(esperados),
        "emparejados": emparejados,
        "completadas_por_el_servidor": completadas,
        "con_contenido": con_contenido,
        "fuera_de_orden": len(emp.fuera_de_orden),
        "cobertura": round(cobertura, 3),
        "palabras": palabras,
        "max_words": max_words,
        "pasa_estructura": (
            cobertura >= UMBRAL and con_contenido == emparejados and not emp.fuera_de_orden
        ),
    }


def cobertura_subsecciones(salida: str, subtitulos: list[str]) -> dict:
    """Informativa (v3): cuántas subsecciones se nombran en algún sitio de la salida.

    No decide nada: el prompt pide nombrarlas en negrita dentro de su sección, pero la métrica que
    decide sigue siendo la del nivel estructural.
    """
    cuerpo = " " + secciones.normal_titulo(salida) + " "
    nombradas = sum(f" {secciones.normal_titulo(t)} " in cuerpo for t in subtitulos)
    return {"total": len(subtitulos), "nombradas": nombradas}


def veredicto(resultados: dict[str, dict]) -> dict:
    """Aplica el criterio de la spec a las métricas (sin el juicio humano, que va aparte)."""
    principales = [resultados.get(k, {}) for k in ("readme", "instalacion", "daemon")]
    changelog = resultados.get("changelog", {})
    corto = resultados.get("corto-4b", {})
    return {
        "tres_documentos": all(r.get("pasa_estructura") for r in principales),
        "changelog": bool(changelog.get("pasa_estructura"))
        and changelog.get("finish_reason") != "length",
        # Desde la v3 el modelo mecánico resume en prosa (criterio del 4B): lo que se comprueba es
        # que el documento corto NO fue por el modo estructurado.
        "corto_4b_en_prosa": bool(corto) and corto.get("secciones_log") is None,
        "pendiente": "juicio del usuario sobre readme, instalacion y daemon",
    }


# --- Llamadas al daemon ---------------------------------------------------------------------------


def _token() -> str:
    token = os.environ.get("LOCAL_DELEGATE_WEB_TOKEN", "")
    if token or sys.platform != "win32":
        return token
    salida = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "[Environment]::GetEnvironmentVariable('LOCAL_DELEGATE_WEB_TOKEN','User')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return salida.stdout.strip()


async def _llamar(argumentos: dict) -> tuple[str, bool]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    cabeceras = {"Authorization": f"Bearer {_token()}"}
    async with (
        httpx2.AsyncClient(headers=cabeceras, timeout=900) as cliente,
        streamable_http_client(URL, http_client=cliente) as flujos,
        ClientSession(flujos[0], flujos[1]) as sesion,
    ):
        await sesion.initialize()
        res = await sesion.call_tool("local_summarize", argumentos)
        texto = "".join(getattr(c, "text", "") for c in res.content)
        return texto, bool(res.is_error)


def _evento_de_uso(ruta: Path, desde: str) -> dict:
    """El último evento de `local_summarize` para esa ruta escrito después de `desde`."""
    carpeta = Path(os.environ.get("LOCALAPPDATA", "")) / "local-delegate"
    eventos = []
    for log in sorted(carpeta.glob("usage-*.jsonl")):
        for linea in log.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(linea)
            except ValueError:
                continue
            if (
                e.get("tool") == "local_summarize"
                and e.get("ts", "") >= desde
                and Path(e.get("path") or "") == ruta
            ):
                eventos.append(e)
    return eventos[-1] if eventos else {}


def ejecutar(etiqueta: str, salidas: Path) -> int:
    salidas.mkdir(parents=True, exist_ok=True)
    resultados: dict[str, dict] = {}
    for llamada in LLAMADAS:
        ruta = (FUENTES / llamada["fichero"]).resolve()
        documento = ruta.read_text(encoding="utf-8")
        plan = secciones.secciones_para_resumen(documento, secciones.detectar(documento))
        esperados = [s.titulo for s in plan]
        subtitulos = [t for s in plan for t in s.subtitulos]
        argumentos = {"path": str(ruta), "max_words": llamada["max_words"]}
        if "focus" in llamada:
            argumentos["focus"] = llamada["focus"]
        desde = datetime.now(UTC).isoformat(timespec="seconds")
        inicio = time.monotonic()
        try:
            texto, error = asyncio.run(_llamar(argumentos))
        except Exception as exc:
            texto, error = f"[excepción] {type(exc).__name__}: {exc}", True
        segundos = round(time.monotonic() - inicio, 1)
        (salidas / f"{llamada['id']}.md").write_text(texto, encoding="utf-8")
        fila = medir(texto, esperados, llamada["max_words"])
        fila["subsecciones"] = cobertura_subsecciones(texto, subtitulos)
        fila["introduccion"] = secciones.INTRODUCCION in esperados
        evento = _evento_de_uso(ruta, desde)
        fila.update(
            {
                "error": error,
                "segundos": segundos,
                "finish_reason": evento.get("finish_reason"),
                "truncated_out": bool(evento.get("truncated_out")),
                "chunks": evento.get("chunks", 1),
                "modelo": evento.get("model"),
                "secciones_log": evento.get("secciones"),
                "focus_log": bool(evento.get("focus")),
            }
        )
        resultados[llamada["id"]] = fila
        print(
            f"{llamada['id']:13} cob={fila['cobertura']:.2f} "
            f"({fila['emparejados']}/{fila['esperados']}, completadas "
            f"{fila['completadas_por_el_servidor']}) contenido={fila['con_contenido']} "
            f"orden={fila['fuera_de_orden']} palabras={fila['palabras']}/{fila['max_words']} "
            f"fin={fila['finish_reason']} {segundos}s {fila['modelo']} error={error}"
        )
    informe = {
        "etiqueta": etiqueta,
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "resultados": resultados,
        "veredicto": veredicto(resultados),
    }
    destino = BANCO / f"resultados-{etiqueta}.json"
    destino.write_bytes((json.dumps(informe, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(informe["veredicto"], ensure_ascii=False, indent=2))
    print(f"Métricas en {destino.relative_to(RAIZ)}; salidas para el juicio humano en {salidas}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--etiqueta", required=True, help="p. ej. main o rama")
    parser.add_argument("--salidas", type=Path, help="dónde dejar las salidas (fuera del repo)")
    args = parser.parse_args(argv)
    salidas = args.salidas or Path(tempfile.gettempdir()) / "medir-resumen" / args.etiqueta
    if RAIZ in salidas.resolve().parents:
        parser.error("--salidas tiene que estar fuera del repo: son contenido")
    return ejecutar(args.etiqueta, salidas)


if __name__ == "__main__":
    sys.exit(main())
