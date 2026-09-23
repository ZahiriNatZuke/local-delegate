#!/usr/bin/env python3
"""Experimento de adopción: ¿qué oferta de los hooks hace que el modelo delegue? (REQ-102)

**Cerrado el 2026-09-23 con el piloto (`--piloto`):** las variantes no se distinguieron (las 9
corridas delegaron, V0 incluida, y 7 releyeron porque el resumen local no sigue la estructura), así
que V1 y V2 se retiraron de los hooks. Hoy las tres «variantes» corren los mismos hooks: el script
queda como registro y como base para medir un resumen que respete la estructura. Resultado en
`.sdd/changes/subagente-lector-local/verification.md`.

SDD `subagente-lector-local`, spec v2 y plan v4.1, tarea 5. Corre con `claude -p`, en sesiones
nuevas, 8 tareas que exigen leer un fichero grande, bajo V0 (el texto de siempre), V1 (receta
lista) y V2 (receta + permiso en el prompt), R veces cada una, en orden intercalado con semilla.
El prompt NUNCA menciona delegar: lo que se mide es si la oferta de los hooks basta.

Reglas escritas antes de correr (plan v4.1, T5):

- **Válida**: la telemetría de la corrida trae el evento del hook de prompt con su `session_id`
  y el bloqueo encendido (hasta la retirada de V1/V2 exigía además la oferta esperada). Si no, se
  repite (2 veces como mucho; a la tercera la tanda aborta).
- **Correcta**: el hecho plantado está en la respuesta y el contenido del fichero no entró al
  contexto principal (ni `Read` completo, ni por franjas, ni volcado por Bash).
- **Supera a V0 en una tarea**: más corridas correctas que V0 en esa tarea.
- **Se elige** la variante que supera a V0 en más tareas, mínimo 3 de 8. Desempate: menor coste
  medio sobre sus corridas válidas; después la más simple (V1 < V2). Si ninguna llega, ninguna.

Guarda cada corrida al terminarla (`--reanudar` sigue donde se quedó) y nunca guarda rutas ni
contenido: solo ids, variante, métricas y el veredicto.

Uso:
    uv run python scripts/experimento_adopcion.py --banco %TEMP%\\banco-adopcion
    uv run python scripts/experimento_adopcion.py --banco ... --reanudar
    uv run python scripts/experimento_adopcion.py --solo-informe resultados.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).parent))
import _banco_claude as banco

RAIZ = Path(__file__).parents[1]
TAREAS = RAIZ / "benchmarks" / "adopcion-directa" / "tareas.json"
VENTANAS = RAIZ / "benchmarks" / "ventanas-excluidas.json"
VARIANTES = ("v0", "v1", "v2")
SIMPLICIDAD = {"v1": 1, "v2": 2}
MINIMO_DE_TAREAS = 3
REINTENTOS = 2
CONECTORES = ("aurora", "boreal", "cierzo", "delta", "estela", "fenix", "granito", "halcon")


# --- Ficheros con hecho plantado ------------------------------------------------------------------


def texto_fuente(tarea: dict, cache: Path, fuentes: Path | None = None) -> str:
    """El texto base de la tarea: un fichero del repo o la salida de un comando (cacheada).

    Con `fuentes` (una carpeta de copias fijas con su `MANIFEST.json` al lado), los ficheros del
    repo se leen de esas copias: así una tanda mide el mismo documento aunque el repo cambie
    después (SDD resumen-por-secciones, N3).
    """
    fuente = tarea["fuente"]
    if "repo" in fuente:
        if fuentes is not None:
            manifiesto = json.loads((fuentes.parent / "MANIFEST.json").read_text(encoding="utf-8"))
            por_origen = {d["origen"]: n for n, d in manifiesto["ficheros"].items()}
            return (fuentes / por_origen[fuente["repo"]]).read_text(encoding="utf-8")
        return (RAIZ / fuente["repo"]).read_text(encoding="utf-8")
    destino = cache / f"{tarea['id']}.txt"
    if not destino.is_file():
        salida = subprocess.run(
            fuente["comando"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        cache.mkdir(parents=True, exist_ok=True)
        destino.write_text(salida.stdout, encoding="utf-8")
    texto = destino.read_text(encoding="utf-8")
    tope = tarea.get("max_bytes")
    return texto[:tope] if tope else texto


def plantar(texto: str, estilo: str, rng: random.Random) -> tuple[str, str, str]:
    """(texto con el hecho, conector, valor). El hecho va hacia la mitad, en una frontera de línea."""
    conector = rng.choice(CONECTORES)
    valor = str(rng.randint(100, 999))
    if estilo == "md":
        hecho = (
            f"\n## Nota de mantenimiento\n\nEl umbral de reintentos del conector {conector} quedó "
            f"fijado en {valor}.\n\n"
        )
    else:
        hecho = f"2026-09-22T10:00:00Z WARN conector {conector}: umbral de reintentos fijado en {valor}\n"
    lineas = texto.splitlines(keepends=True)
    corte = len(lineas) // 2 + rng.randint(-len(lineas) // 8, len(lineas) // 8)
    return "".join(lineas[:corte]) + hecho + "".join(lineas[corte:]), conector, valor


def pregunta(ruta: Path, estilo: str) -> str:
    """Una pregunta de COMPRENSIÓN: exige leer el fichero entero, o delegar su lectura.

    La primera versión preguntaba por el dato plantado («¿en cuánto quedó el umbral del conector
    X?») y en el control instalado (tarea 4) el modelo lo resolvió con `Grep` en las tres
    variantes, sin leer ni delegar: la tarea no exigía leer, que es lo que pide REQ-102, y el
    experimento no habría podido distinguir nada. Un resumen no se saca con `Grep`. El hecho
    plantado sigue sirviendo de comprobación: la pregunta pide las cifras, sin decir cuál.
    """
    que = "este log" if estilo == "log" else "este documento"
    return (
        f"Tengo {que}: {ruta}\nResúmelo en 5 puntos e incluye todas las cifras de configuración "
        "que aparezcan."
    )


# --- Piloto: resumen sin datos concretos, corregido por los títulos de sección -------------------
#
# En la tarea 4 la pregunta de «todas las cifras» hizo que las tres variantes delegaran y luego
# releyeran, porque el resumen local pierde cifras: el experimento no podía distinguir la oferta.
# El piloto pide un resumen que siga la estructura, sin nombrar las secciones (si las nombrase,
# un `Grep '^## '` la resolvería sin leer), y lo da por bueno si nombra casi todos los títulos.

TAREAS_PILOTO = ("readme", "wiki-instalacion", "wiki-daemon")
COBERTURA_MINIMA = 0.8


def pregunta_piloto(ruta: Path) -> str:
    return (
        f"Tengo este documento: {ruta}\nHazme un resumen organizado siguiendo su estructura, "
        "para decidir qué partes leer con calma."
    )


def _normal(texto: str) -> str:
    return " ".join(re.sub(r"[`*_\[\]()¿?¡!:]", " ", texto).lower().split())


def titulos_de_seccion(texto: str) -> list[str]:
    return [linea[3:].strip() for linea in texto.splitlines() if linea.startswith("## ")]


def cobertura_de_titulos(respuesta: str, titulos: list[str]) -> float:
    """Fracción de los títulos `##` que aparecen, normalizados, en la respuesta."""
    if not titulos:
        return 0.0
    cuerpo = _normal(respuesta)
    return sum(_normal(t) in cuerpo for t in titulos) / len(titulos)


# --- Plan de corridas y veredicto (puro: se prueba sin lanzar nada) --------------------------------


def plan_de_corridas(
    ids: list[str], repeticiones: int, semilla: int, variantes: tuple[str, ...] = VARIANTES
) -> list[tuple[str, str, int]]:
    corridas = [(t, v, r) for t in ids for v in variantes for r in range(repeticiones)]
    random.Random(semilla).shuffle(corridas)
    return corridas


def informe_resumen(filas: list[dict]) -> dict:
    """Informe de la etapa 2 del SDD resumen-por-secciones: se decide solo por correctas.

    «Correcta» ya exige que el contenido no entrara al contexto; las corridas con el contenido en
    el contexto (`contenido_en_contexto`, la misma definición que en T5) se informan aparte, con
    el desglose por tarea para no leer un total como uniforme.
    """
    validas = [f for f in filas if f.get("valida")]
    por_tarea: dict[str, dict[str, int]] = defaultdict(
        lambda: {"corridas": 0, "correctas": 0, "contenido_en_contexto": 0}
    )
    for f in validas:
        fila = por_tarea[f["tarea"]]
        fila["corridas"] += 1
        fila["correctas"] += bool(f.get("correcta"))
        fila["contenido_en_contexto"] += bool(f.get("contenido_en_contexto"))
    correctas = sum(t["correctas"] for t in por_tarea.values())
    corridas = len(validas)
    if corridas == 9:
        decision = (
            "se queda" if correctas >= 6 else "se retira" if correctas <= 3 else "no concluyente"
        )
    else:
        decision = f"sin decisión: el criterio es para 9 corridas válidas, hay {corridas}"
    return {
        "corridas_validas": corridas,
        "correctas": correctas,
        "contenido_en_contexto": sum(t["contenido_en_contexto"] for t in por_tarea.values()),
        "por_tarea": dict(sorted(por_tarea.items())),
        "decision": decision,
    }


def veredicto(filas: list[dict]) -> dict:
    """Aplica las reglas de REQ-102 a las corridas válidas. Devuelve la variante elegida o None."""
    validas = [f for f in filas if f.get("valida")]
    correctas: dict[tuple[str, str], int] = defaultdict(int)
    tareas = sorted({f["tarea"] for f in validas})
    for f in validas:
        correctas[(f["tarea"], f["oferta"])] += bool(f.get("correcta"))
    supera = {
        v: [t for t in tareas if correctas[(t, v)] > correctas[(t, "v0")]] for v in ("v1", "v2")
    }
    coste = {
        v: mean([f["coste_usd"] for f in validas if f["oferta"] == v] or [float("inf")])
        for v in VARIANTES
    }
    candidatas = [v for v in ("v1", "v2") if len(supera[v]) >= MINIMO_DE_TAREAS]
    candidatas.sort(key=lambda v: (-len(supera[v]), coste[v], SIMPLICIDAD[v]))
    return {
        "elegida": candidatas[0] if candidatas else None,
        "supera_a_v0_en": {v: supera[v] for v in ("v1", "v2")},
        "correctas": {f"{t}/{v}": correctas[(t, v)] for t in tareas for v in VARIANTES},
        "coste_medio_usd": coste,
        "corridas_validas": len(validas),
        "corridas_invalidas": len(filas) - len(validas),
    }


# --- Ejecución ------------------------------------------------------------------------------------


def ejecutar(args: argparse.Namespace) -> int:
    tareas = json.loads(TAREAS.read_text(encoding="utf-8"))["tareas"]
    if args.piloto:
        tareas = [t for t in tareas if t["id"] in TAREAS_PILOTO]
    ids = [t["id"] for t in tareas]
    por_id = {t["id"]: t for t in tareas}
    corridas = plan_de_corridas(ids, args.repeticiones, args.semilla, args.variantes)
    salida = args.banco / "resultados.jsonl"
    hechas = set()
    if args.reanudar and salida.is_file():
        for linea in salida.read_text(encoding="utf-8").splitlines():
            fila = json.loads(linea)
            hechas.add((fila["tarea"], fila["oferta"], fila["rep"]))
    pendientes = [c for c in corridas if c not in hechas]
    if not banco.confirmar(len(pendientes), args.coste_por_corrida, si=args.si):
        print("Cancelado.")
        return 1

    args.banco.mkdir(parents=True, exist_ok=True)
    interruptor = args.banco / "interruptor-que-no-existe"
    interruptor.unlink(missing_ok=True)
    muestra = args.banco / "precedencia.md"
    muestra.write_text((RAIZ / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    if not banco.control_de_precedencia(args.banco, muestra, interruptor):
        print("ABORTA: con LD_HOOK_ENABLED=0 por --settings el Read siguió bloqueado o no se leyó.")
        return 2

    rng = random.Random(args.semilla)
    lanzadas: list[banco.Corrida] = []
    for tarea_id, oferta, rep in pendientes:
        tarea = por_id[tarea_id]
        fila = None
        for intento in range(REINTENTOS + 1):
            dir_corrida = args.banco / f"{tarea_id}-{oferta}-{rep}-{intento}"
            shutil.rmtree(dir_corrida, ignore_errors=True)
            dir_corrida.mkdir(parents=True)
            fuente = texto_fuente(tarea, args.banco / "fuentes", args.fuentes)
            if args.piloto:
                texto, valor = fuente, ""
            else:
                texto, _conector, valor = plantar(fuente, tarea["estilo"], rng)
            fichero = dir_corrida / tarea["nombre"]
            fichero.write_text(texto, encoding="utf-8")
            telemetria = dir_corrida / "telemetria.jsonl"
            settings = banco.escribir_settings(
                dir_corrida / "settings.json", banco.env_de_tanda(telemetria, interruptor)
            )
            prompt = pregunta_piloto(fichero) if args.piloto else pregunta(fichero, tarea["estilo"])
            corrida = banco.correr(prompt, args.banco, settings)
            lanzadas.append(corrida)
            if corrida.error or not corrida.session_id:
                continue
            visto = banco.analizar(banco.leer_transcript(args.banco, corrida.session_id), fichero)
            valida = visto["tools_diferidas"] and banco.corrida_valida(
                banco.eventos_de_telemetria(telemetria), corrida.session_id
            )
            if not valida:
                continue
            if args.piloto:
                cobertura = cobertura_de_titulos(corrida.resultado, titulos_de_seccion(texto))
                acierto = cobertura >= COBERTURA_MINIMA
                medida = {"cobertura_titulos": round(cobertura, 2)}
            else:
                acierto = valor in corrida.resultado
                medida = {"hecho_en_respuesta": acierto}
            fila = {
                "tarea": tarea_id,
                "oferta": oferta,
                "rep": rep,
                "session_id": corrida.session_id,
                "valida": True,
                "correcta": acierto and not visto["contenido_en_contexto"],
                **medida,
                "coste_usd": corrida.coste_usd,
                **{k: v for k, v in visto.items() if k != "local_con_path"},
                "tools_locales": visto["local_con_path"],
                "intentos": intento + 1,
            }
            break
        if fila is None:
            banco.anotar_ventana(VENTANAS, "experimento-adopcion (abortado)", lanzadas)
            print(f"ABORTA: {tarea_id}/{oferta}/{rep} no dio una corrida válida en 3 intentos.")
            return 3
        with salida.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
        print(
            f"{tarea_id:18} {oferta} #{rep}: correcta={fila['correcta']} coste={fila['coste_usd']:.2f}"
        )

    banco.anotar_ventana(VENTANAS, "experimento-adopcion", lanzadas)
    return informe(salida)


def informe(resultados: Path) -> int:
    filas = [json.loads(x) for x in resultados.read_text(encoding="utf-8").splitlines() if x]
    if len({f["oferta"] for f in filas}) > 1:
        print(json.dumps(veredicto(filas), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(informe_resumen(filas), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--banco", type=Path, help="directorio de trabajo neutro (fuera del repo)")
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--semilla", type=int, default=20260922)
    parser.add_argument("--coste-por-corrida", type=float, default=0.45)
    parser.add_argument("--reanudar", action="store_true")
    parser.add_argument(
        "--piloto",
        action="store_true",
        help="3 tareas de docs, resumen sin datos concretos, corrección por títulos de sección",
    )
    parser.add_argument(
        "--variantes",
        type=lambda s: tuple(v.strip() for v in s.split(",") if v.strip()),
        default=VARIANTES,
        help="etiquetas a correr, separadas por comas (por defecto v0,v1,v2); hoy son iguales",
    )
    parser.add_argument(
        "--fuentes",
        type=Path,
        help="carpeta de copias fijas (con MANIFEST.json al lado) en vez de los ficheros vivos",
    )
    parser.add_argument("--si", action="store_true", help="no preguntar antes de gastar cuota")
    parser.add_argument(
        "--solo-informe", type=Path, help="recalcula el veredicto de un resultados.jsonl"
    )
    args = parser.parse_args(argv)
    if set(args.variantes) - set(VARIANTES):
        parser.error(f"--variantes solo admite {', '.join(VARIANTES)}")
    if args.solo_informe:
        return informe(args.solo_informe)
    if not args.banco:
        parser.error("--banco es obligatorio para correr")
    if RAIZ in args.banco.resolve().parents or args.banco.resolve() == RAIZ:
        parser.error("--banco tiene que estar fuera del repo (sin memoria de proyecto)")
    return ejecutar(args)


if __name__ == "__main__":
    sys.exit(main())
