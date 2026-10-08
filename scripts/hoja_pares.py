#!/usr/bin/env python3
"""Hoja por pares, a ciegas, para validar la puntuacion automatica contra juicio humano (P-15).

La cobertura de terminos puede medir vocabulario y no correccion: el cuarto piloto de CP-3 vio al
mismo modelo pasar de 1,0 a 0 segun nombrara o describiera, y al 2B puntuar tras contradecir la
fuente. Antes de fiarse de ella en la tanda, se contrasta con la pregunta que §7 decide de verdad:
¿cual de estas dos respuestas es mejor?

- `generar` empareja, por caso, la corrida i de dos configuraciones (solo si las dos son validas y
  puntuadas), sortea que respuesta va como A y cual como B, baraja los pares y numera DESPUES. La
  clave, con los modelos y las puntuaciones automaticas, va a un fichero aparte.
- `generate-commit` y `read-commit`: la hoja a ciegas de `local_commit_msg` del SDD
  `daemon-reparte-el-backend` (REQ-042), al final de este modulo.
- `destapar` lee las elecciones (A, B o =) y dice, por caso, en cuantos pares la metrica prefiere a
  uno y en cuantos de esos coincide la persona. Un empate humano donde la metrica ve diferencia NO es
  acuerdo: la metrica afirmo algo que la persona no ve. Un caso es valido con al menos
  `MIN_PREFERENCIAS` preferencias de la metrica y `UMBRAL_ACUERDO` de acuerdo; con menos, «sin base».

Uso:
    python scripts/hoja_pares.py generar --hoja pares.md --clave pares-clave.json \\
        --cases benchmarks/catalogo-2026-09/cases.json --pequeno cp3-qwen35-2b \\
        --grande cp3-qwen25-coder-14b --caso resumen-changelog-7k ... resultados/cp3d-*.jsonl
    python scripts/hoja_pares.py destapar --hoja pares.md --clave pares-clave.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import secrets
import sys
from pathlib import Path
from typing import Any

UMBRAL_ACUERDO = 0.8
MIN_PREFERENCIAS = 3

_PAR_RE = re.compile(r"^## Par (\d+)\s*$")
_ELECCION_RE = re.compile(r"^Mejor \(A/B/=\):[ \t]*(\S*)[ \t]*$")


def _registros(rutas: list[Path]) -> list[dict[str, Any]]:
    registros = []
    for ruta in rutas:
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                registros.append(json.loads(linea))
    return registros


def _valla(texto: str) -> str:
    """Una valla mas larga que cualquier racha de acentos graves de la respuesta."""
    rachas = [len(m) for m in re.findall(r"`+", texto)]
    return "`" * max(3, max(rachas, default=0) + 1)


def _corridas_validas(
    registros: list[dict[str, Any]], label: str, caso: str
) -> dict[int, dict[str, Any]]:
    """El ultimo intento de cada corrida, si es valido y tiene puntuacion automatica."""
    ultimos: dict[int, dict[str, Any]] = {}
    for r in registros:
        if r.get("label") == label and r.get("case") == caso and r.get("input_variant") is None:
            ultimos[int(r["run"])] = r  # el fichero va en orden: el ultimo intento pisa a los otros
    validas = {}
    for run, r in ultimos.items():
        calidad = (r.get("score") or {}).get("quality")
        if r.get("descartada") or calidad is None:
            continue
        if "response" not in r:
            raise ValueError(
                f"{label}:{caso} run {run} sin respuesta guardada (el runner necesita --save-responses)"
            )
        validas[run] = r
    return validas


def generar(
    registros: list[dict[str, Any]],
    corpus: dict[str, dict[str, Any]],
    casos: list[str],
    pequeno: str,
    grande: str,
    semilla: int,
) -> tuple[str, dict[str, Any]]:
    azar = random.Random(semilla)
    pares = []
    for caso in casos:
        a, b = (
            _corridas_validas(registros, pequeno, caso),
            _corridas_validas(registros, grande, caso),
        )
        for run in sorted(set(a) & set(b)):
            pares.append((caso, run, a[run], b[run]))
    if not pares:
        raise ValueError("ningun par valido: ¿etiquetas o casos equivocados?")
    azar.shuffle(pares)
    lineas = [
        "# Comparacion por pares, a ciegas",
        "",
        "En cada par, lee la tarea y las dos respuestas (abre la fuente si hace falta) y escribe detras",
        "de «Mejor (A/B/=):» cual responde MEJOR a la tarea: A, B, o = si no ves diferencia real.",
        "Juzga si es correcta y util para quien la pidio, no si nombra mas cosas. No abras la clave.",
        "",
    ]
    clave: dict[str, Any] = {"semilla": semilla, "pequeno": pequeno, "grande": grande, "pares": {}}
    for numero, (caso, run, reg_p, reg_g) in enumerate(pares, 1):
        par = f"{numero:02d}"
        meta = corpus.get(caso) or {}
        lados = [(pequeno, reg_p), (grande, reg_g)]
        azar.shuffle(lados)
        lineas += [
            f"## Par {par}",
            "",
            f"Tarea: `{meta.get('tool', '?')}` sobre `fuentes/{meta.get('source_file', '?')}`",
            "",
            f"> {meta.get('system') or ''}",
            "",
        ]
        for letra, (_label, reg) in zip("AB", lados, strict=True):
            respuesta = str(reg["response"])
            valla = _valla(respuesta)
            lineas += [f"### Respuesta {letra}", "", valla, respuesta, valla, ""]
        lineas += ["Mejor (A/B/=): ", ""]
        clave["pares"][par] = {
            "case": caso,
            "run": run,
            "A": {"label": lados[0][0], "quality": lados[0][1]["score"]["quality"]},
            "B": {"label": lados[1][0], "quality": lados[1][1]["score"]["quality"]},
        }
    return "\n".join(lineas), clave


def leer_elecciones(hoja: str) -> dict[str, str | None]:
    """Lee las elecciones saltandose lo que va dentro de la valla: la respuesta la escribio un
    modelo, y una linea «Mejor (A/B/=): A» dentro de ella no puede votar por el."""
    elecciones: dict[str, str | None] = {}
    actual: str | None = None
    valla: str | None = None
    for linea in hoja.splitlines():
        if valla is not None:
            if linea == valla:
                valla = None
            continue
        if re.fullmatch(r"`{3,}", linea):
            valla = linea
            continue
        if m := _PAR_RE.match(linea):
            actual = m.group(1)
            elecciones[actual] = None
        elif actual is not None and (m := _ELECCION_RE.match(linea)):
            valor = m.group(1).upper()
            if valor == "":
                elecciones[actual] = None
            elif valor in {"A", "B", "="}:
                elecciones[actual] = valor
            else:
                raise ValueError(f"par {actual}: eleccion {m.group(1)!r} no es A, B ni =")
            actual = None
    return elecciones


def destapar(hoja: str, clave: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    elecciones = leer_elecciones(hoja)
    pares = clave["pares"]
    if set(elecciones) != set(pares):
        raise ValueError(
            "la hoja y la clave no tienen los mismos pares: ¿son de la misma generacion?"
        )
    faltan = sorted(par for par, eleccion in elecciones.items() if eleccion is None)
    por_caso: dict[str, dict[str, Any]] = {}
    for par, eleccion in sorted(elecciones.items()):
        if eleccion is None:
            continue
        meta = pares[par]
        fila = por_caso.setdefault(
            meta["case"],
            {"pares": 0, "metrica_prefiere": 0, "acuerdos": 0, "humano": {}},
        )
        fila["pares"] += 1
        ganador_humano = "empate" if eleccion == "=" else meta[eleccion]["label"]
        fila["humano"][ganador_humano] = fila["humano"].get(ganador_humano, 0) + 1
        qa, qb = meta["A"]["quality"], meta["B"]["quality"]
        if qa == qb:
            continue  # la metrica no prefiere: nada que validar en este par
        fila["metrica_prefiere"] += 1
        preferida = "A" if qa > qb else "B"
        if eleccion == preferida:
            fila["acuerdos"] += 1
    for fila in por_caso.values():
        n = fila["metrica_prefiere"]
        fila["acuerdo"] = fila["acuerdos"] / n if n else None
        if n < MIN_PREFERENCIAS:
            fila["veredicto"] = "sin base"
        elif fila["acuerdo"] >= UMBRAL_ACUERDO:
            fila["veredicto"] = "valida"
        else:
            fila["veredicto"] = "no valida"
    return por_caso, faltan


# --- Hoja a ciegas de `local_commit_msg` (REQ-042) --------------------------------------------------
#
# Para el usuario, que juzga 33 pares de mensajes de commit sin saber de que modelo es cada uno. Este
# modulo NO importa `local_delegate`: la hoja se recoge mientras otras tareas editan `server.py`.
# Todo lo que decide algo vive en `reglas.json`; la clave (que mensaje es de quien) va en otra
# carpeta y solo la leen estos programas.

AFFINITY_BASE = Path(__file__).resolve().parents[1] / "benchmarks" / "afinidad-2026-10"
MODEL_26B = "gemma4-26b-a4b"
QWEN_MODEL = "qwen36-35b-a3b"
TRAP = "trampa"
MAX_BODY_LINES = 5
POSSIBLE_OPTIONAL_QUESTIONS = ("principal", "especifico")
_VALUES = {
    "inventa": ("s", "n"),
    "principal": ("s", "p", "n"),
    "especifico": ("s", "n"),
    "preferencia": ("A", "B", "="),
}
_SYNONYMS_RESPONSE = {"si": "s", "sí": "s", "no": "n", "parcial": "p", "empate": "=", "": ""}


def read_rules(path: Path) -> dict[str, Any]:
    """`reglas.json`, validado. «Inventa» y la preferencia no pueden ser opcionales: son lo que
    decide la celda, y una hoja que no los pidiera no decidiria nada."""
    rules = json.loads(path.read_text(encoding="utf-8"))
    maximum = rules.get("max_inventa_26b")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
        raise SystemExit("reglas.json: max_inventa_26b tiene que ser un entero >= 0")
    optional_ones = rules.get("preguntas_opcionales")
    if not isinstance(optional_ones, list) or not set(optional_ones) <= set(
        POSSIBLE_OPTIONAL_QUESTIONS
    ):
        raise SystemExit(
            "reglas.json: preguntas_opcionales solo admite 'principal' y 'especifico'; "
            "'inventa' y la preferencia no pueden ser opcionales"
        )
    if not isinstance(rules.get("parada_anticipada"), bool):
        raise SystemExit("reglas.json: parada_anticipada tiene que ser true o false")
    return rules


# --- La forma del mensaje ---------------------------------------------------------------------------


def split_message(message: str) -> tuple[str, list[str], bool]:
    """`(asunto, lineas de cuerpo no vacias, hay linea en blanco entre los dos)`."""
    lines = message.strip("\n").split("\n")
    subject, rest = lines[0], lines[1:]
    separate = bool(rest) and not rest[0].strip()
    return subject, [x for x in rest if x.strip()], separate


def forma(message: str) -> tuple[bool, int]:
    """Lo que tiene que copiar la trampa: si lleva cuerpo y cuantas lineas (como mucho 5)."""
    _subject, body, _sep = split_message(message)
    return bool(body), min(len(body), MAX_BODY_LINES)


_BULLETS = ("- ", "* ")
# Un punto (o ! o ?) seguido de espacio y de una mayuscula es el limite entre dos frases; un
# «release.py» o un «0.18.0» no lo son porque no llevan espacio detras del punto.
_SENTENCE_LIMIT = re.compile(r"(?<=[.!?])\s+(?=[¿¡A-ZÁÉÍÓÚÑ])")
_SENTENCE_END = re.compile(r"[.!?…][\"')\]»`*]*$")


def body_units(lines: list[str]) -> list[str]:
    """Las unidades COMPLETAS de un cuerpo: cada viñeta entera y cada frase entera de un parrafo.

    Una linea fisica no es una unidad: un cuerpo escrito a 80 columnas parte las frases por la mitad,
    y convertir cada trozo en una viñeta deja una trampa que se reconoce sin leer el diff. Las viñetas
    conservan su marca; las lineas indentadas que siguen a una viñeta son su continuacion; el resto
    se junta en texto corrido y se parte por frases.
    """
    units_list: list[str] = []
    paragraph: list[str] = []
    in_bullet = False

    def close_paragraph() -> None:
        if paragraph:
            text = " ".join(x.strip() for x in paragraph)
            units_list.extend(f.strip() for f in _SENTENCE_LIMIT.split(text) if f.strip())
            paragraph.clear()

    for line in lines:
        if not line.strip():
            continue
        if line.lstrip().startswith(_BULLETS):
            close_paragraph()
            units_list.append(line.strip())
            in_bullet = True
        elif in_bullet and line[:1].isspace():
            units_list[-1] += " " + line.strip()
        else:
            in_bullet = False
            paragraph.append(line)
    close_paragraph()
    return units_list


# Palabras que no pueden cerrar una frase: si la ultima palabra es una de ellas, la linea esta cortada.
_CUTOFF_WORDS = frozenset(
    [
        "con",
        "de",
        "y",
        "a",
        "el",
        "la",
        "en",
        "que",
        "por",
        "para",
        "o",
        "del",
        "al",
        "los",
        "las",
        "un",
        "una",
        "e",
        "u",
        "se",
        "sin",
        "sobre",
        "como",
    ]
)
MAX_LENGTH_FACTOR = 1.5  # la viñeta media de la trampa no pasa de 1,5 veces la de su pareja


def _line_text(line: str) -> str:
    text = line.strip()
    return text[2:].strip() if text.startswith(_BULLETS) else text


def uses_final_scoring(message: str) -> bool:
    """Si la mayoria de las lineas de cuerpo (la mitad o mas) acaban en signo final. Sin cuerpo, no."""
    _subject, body, _sep = split_message(message)
    signed = sum(bool(_SENTENCE_END.search(_line_text(x))) for x in body)
    return bool(body) and signed * 2 >= len(body)


def mean_bullet_length(message: str) -> float:
    """Caracteres medios por linea de cuerpo, sin la marca de viñeta. 0 si no hay cuerpo."""
    _subject, body, _sep = split_message(message)
    return sum(len(_line_text(x)) for x in body) / len(body) if body else 0.0


def body_defects(message: str, pair: str | None = None) -> list[str]:
    """Lo que delata a una trampa por mal escrita, no por falsa: cada linea del cuerpo (viñeta o
    frase) tiene que ser una unidad entera, y con la pareja a la vista, escrita como ella.

    - No empieza en minuscula: una viñeta que arranca a mitad de frase es un trozo de parrafo partido.
      Un acento grave, una cifra o una comilla delante no cuentan como minuscula.
    - No termina cortada. Sin `pareja` (o si la pareja cierra con signo final) exige signo final
      (`.`, `!`, `?` o `…`, con un cierre opcional de comillas, parentesis o acento grave detras).
      Si la pareja NO cierra con signo final, acepta una linea sin el, pero exige palabra completa:
      la ultima no puede ser una de corte (`con`, `de`, `y`, `a`, `el`...) ni la linea acabar en coma,
      punto y coma, dos puntos o guion. Lo incumple el trozo que termina en «ningun» o en «0.18.1,».
    - Con `pareja`: la puntuacion final es la de la pareja (si ella cierra con punto, la trampa
      tambien; si no, tampoco) y la viñeta media de la trampa no pasa de `MAX_LENGTH_FACTOR` veces la
      de la pareja.

    Solo se aplica a las trampas; los mensajes de los modelos no se tocan.
    """
    _subject, body, _sep = split_message(message)
    signed = True if pair is None else uses_final_scoring(pair)
    defects = []
    for line in body:
        text = _line_text(line)
        if text[:1].islower():
            defects.append(f"empieza en minuscula: {line.strip()!r}")
        if _SENTENCE_END.search(text):
            continue
        words = re.findall(r"\w+", text)
        if (
            signed
            or text.endswith((",", ";", ":", "-"))
            or (words and words[-1].lower() in _CUTOFF_WORDS)
        ):
            defects.append(f"termina cortada: {line.strip()!r}")
    if pair is not None and body:
        if uses_final_scoring(message) != signed:
            defects.append(
                "la puntuacion final no es la de la pareja "
                f"(la pareja {'cierra' if signed else 'no cierra'} con signo final)"
            )
        long, pair_length = mean_bullet_length(message), mean_bullet_length(pair)
        if pair_length and long > MAX_LENGTH_FACTOR * pair_length:
            defects.append(
                f"viñeta media de {long:.0f} caracteres, mas de {MAX_LENGTH_FACTOR} veces "
                f"los {pair_length:.0f} de la pareja"
            )
    return defects


def shaped_trap(trap: dict[str, Any], pair_message: str) -> str:
    """El mensaje de la trampa con la forma del mensaje con el que se empareja.

    Regla de forma, escrita antes de la tanda: si el mensaje del modelo tiene cuerpo, la trampa lleva
    el asunto mas tantas unidades de su cuerpo como lineas de cuerpo tenga ese mensaje (como mucho 5);
    si no lo tiene, solo el asunto. Una unidad es una viñeta entera o una frase entera (nunca una linea
    fisica del cuerpo) y, al recortar, se quitan unidades enteras. Si la trampa no tiene tantas
    unidades, lleva las que tiene.

    Ademas copia la puntuacion final de la pareja (si la mayoria de sus lineas no cierran con punto,
    la trampa tampoco) y, si sus n primeras unidades pasan de `MAX_LENGTH_FACTOR` veces la viñeta
    media de la pareja, lleva las n unidades MAS CORTAS, en su orden. Nunca acorta una frase.
    """
    _subject, model_body, separate = split_message(pair_message)
    n = min(len(model_body), MAX_BODY_LINES)
    if n == 0:
        return str(trap["asunto"])
    units_list = body_units([str(x) for x in trap["cuerpo"]])
    lines = units_list[:n]
    pair_length = mean_bullet_length(pair_message)

    def long(units: list[str]) -> float:
        return sum(len(_line_text(x)) for x in units) / len(units)

    if len(units_list) > n and long(lines) > MAX_LENGTH_FACTOR * pair_length:
        chosen_ones = sorted(
            sorted(range(len(units_list)), key=lambda i: (len(units_list[i]), i))[:n]
        )
        lines = [units_list[i] for i in chosen_ones]
    if not uses_final_scoring(pair_message):
        lines = [x[:-1].rstrip() if x.endswith(".") and not x.endswith("..") else x for x in lines]
    with_bullets = sum(x.lstrip().startswith(_BULLETS) for x in model_body) * 2 >= len(model_body)
    if with_bullets:
        lines = [x if x.startswith(_BULLETS) else f"- {x}" for x in lines]
    return "\n".join([str(trap["asunto"]), *([""] if separate else []), *lines])


def diff_summary(diff: str) -> tuple[int, int, int]:
    """`(ficheros, lineas anadidas, lineas quitadas)` de un diff unificado."""
    files_list = more = less = 0
    for line in diff.replace("\r\n", "\n").split("\n"):
        if line.startswith("diff --git "):
            files_list += 1
        elif line.startswith("+") and not line.startswith("+++"):
            more += 1
        elif line.startswith("-") and not line.startswith("---"):
            less += 1
    return files_list, more, less


# --- Construir la hoja ------------------------------------------------------------------------------


def _message_of(records: list[dict[str, Any]], label: str, case: str) -> str | None:
    """La respuesta del ULTIMO intento de la corrida 1, si termino bien."""
    last = None
    for r in records:
        if r.get("label") == label and r.get("case") == case and int(r.get("run", 1)) == 1:
            last = r
    if last is None or last.get("descartada") or last.get("outcome") != "ok":
        return None
    text = last.get("response")
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def _balanced_split(rng: random.Random, n: int, a: str, b: str) -> list[str]:
    """`n` etiquetas barajadas, la mitad `a` y la mitad `b`; si `n` es impar, quien se lleva la
    sobrante lo sortea `azar`. Asi la diferencia entre las dos es 0 o 1, nunca la del azar."""
    of_a = n // 2 + (rng.randint(0, 1) if n % 2 else 0)
    tags = [a] * of_a + [b] * (n - of_a)
    rng.shuffle(tags)
    return tags


def sheet_id(number: int, pair_items: list[dict[str, Any]]) -> str:
    content = json.dumps({"n": number, "pares": pair_items}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_commit_sheet(
    *,
    cases: dict[str, dict[str, Any]],
    sources: Path,
    records: list[dict[str, Any]],
    traps: dict[str, Any],
    rules: dict[str, Any],
    case_set_item: int,
    number: int,
    seed: int,
    label_26b: str = MODEL_26B,
    label_qwen: str = QWEN_MODEL,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """`(hoja, clave)`: 30 pares reales y 3 trampa, barajados, numerados DESPUES de barajar.

    La hoja lleva los diffs y los mensajes tal como los devolvio la tool y nada mas: ni ids de
    modelo, ni etiquetas, ni latencias. La clave dice quien es cada lado y cual es la trampa.
    """
    rng = random.Random(seed)
    sets = traps["juegos"]
    if not 1 <= case_set_item <= len(sets):
        raise SystemExit(f"trampas.json no tiene el juego {case_set_item}")

    def diff_of(case_id: str) -> str:
        name = cases[case_id]["source_file"]
        return (sources / name).read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")

    real: list[tuple[str, str, str]] = []
    skipped: list[str] = []
    for case_id, case in cases.items():
        if case.get("rol_en_hoja") != "real":
            continue
        a = _message_of(records, label_26b, case_id)
        b = _message_of(records, label_qwen, case_id)
        if a is None or b is None:
            skipped.append(case_id)
            continue
        real.append((case_id, a, b))
    # El lado NO se sortea par a par: con 30 pares, un sorteo independiente deja a un modelo en A en 23
    # (p = 0,005) y, como uno escribe cuerpo largo y el otro corto, la hoja queda casi siempre como
    # «A largo, B corto». Una permutacion equilibrada: la mitad exacta (o con diferencia 1) por lado.
    in_a = _balanced_split(rng, len(real), label_26b, label_qwen)
    pending_items: list[dict[str, Any]] = []
    for (case_id, a, b), first in zip(real, in_a, strict=True):
        sides = [(label_26b, a), (label_qwen, b)]
        if first != label_26b:
            sides.reverse()
        pending_items.append(
            {"tipo": "real", "caso": case_id, "lados": sides, "diff": diff_of(case_id)}
        )
    entries = sets[case_set_item - 1]["trampas"]
    # De las trampas tambien se equilibra el lado de la trampa y el modelo con el que se empareja.
    trap_in_a = _balanced_split(rng, len(entries), "A", "B")
    pairs = _balanced_split(rng, len(entries), label_26b, label_qwen)
    for entry, trap_side, model in zip(entries, trap_in_a, pairs, strict=True):
        case_id = entry["caso"]
        message = _message_of(records, model, case_id)
        if message is None:
            raise SystemExit(f"la trampa de {case_id} no tiene mensaje del modelo elegido")
        trap_text = shaped_trap(entry, message)
        defects = body_defects(trap_text, message)
        if defects:
            raise SystemExit(
                f"la trampa de {case_id} se reconoce por mal escrita: {'; '.join(defects)}"
            )
        sides = [(TRAP, trap_text), (model, message)]
        if trap_side == "B":
            sides.reverse()
        pending_items.append(
            {
                "tipo": TRAP,
                "caso": case_id,
                "trampa_tipo": entry["tipo"],
                "lados": sides,
                "diff": diff_of(case_id),
            }
        )
    rng.shuffle(pending_items)

    pair_items: list[dict[str, Any]] = []
    pairs_key: dict[str, Any] = {}
    for position, p in enumerate(pending_items, 1):
        num = f"{position:02d}"
        files_list, more, less = diff_summary(p["diff"])
        pair_items.append(
            {
                "num": num,
                "ficheros": files_list,
                "mas": more,
                "menos": less,
                "diff": p["diff"],
                "A": p["lados"][0][1],
                "B": p["lados"][1][1],
            }
        )
        pairs_key[num] = {
            "tipo": p["tipo"],
            "caso": p["caso"],
            "lados": {"A": p["lados"][0][0], "B": p["lados"][1][0]},
            **({"trampa_tipo": p["trampa_tipo"]} if p["tipo"] == TRAP else {}),
        }
    seen_set: set[str] = set()
    for pair in pair_items:
        for text in (pair["diff"], pair["A"], pair["B"]):
            if text in seen_set:
                raise SystemExit(
                    f"par {pair['num']}: un diff o un mensaje aparece dos veces en la hoja"
                )
            seen_set.add(text)
    sheet = {
        "id": sheet_id(number, pair_items),
        "n": number,
        "opcionales": list(rules["preguntas_opcionales"]),
        "pares": pair_items,
    }
    key = {
        "schema_version": 1,
        "hoja": number,
        "juego": case_set_item,
        "sha256": sheet["id"],
        "semilla": seed,
        "label_26b": label_26b,
        "label_qwen": label_qwen,
        "pares": pairs_key,
        "omitidos": skipped,
    }
    return sheet, key


# --- Renderizado ------------------------------------------------------------------------------------

_INSTRUCTIONS = [
    (
        "Inventa (si/no)",
        "¿El mensaje dice algo que el diff no hace? Lo que el mensaje se deja fuera no se marca aquí, sino en «lo principal».",
    ),
    ("Lo principal (si/parcial/no)", "¿Nombra el cambio más importante del diff?"),
    ("Específico (si/no)", "¿Se entiende sin abrir el diff?"),
    ("Preferencia", "A, B o empate, después de marcar los dos mensajes."),
]


def estimated_time(rules: dict[str, Any]) -> str:
    optional_ones = set(rules["preguntas_opcionales"])
    if {"principal", "especifico"} <= optional_ones:
        return "unos 45–60 minutos (solo «inventa» y la preferencia son obligatorias)"
    return "entre 60 y 90 minutos"


def _fence_for(text: str) -> str:
    streaks = [len(m) for m in re.findall(r"`+", text)]
    return "`" * max(3, max(streaks, default=0) + 1)


def render_md(sheet: dict[str, Any], rules: dict[str, Any]) -> str:
    optional_ones = set(rules["preguntas_opcionales"])
    lines = [
        f"# Hoja {sheet['n']}: mensajes de commit, a ciegas",
        "",
        f"Hoja: {sheet['id']}",
        "",
        f"En cada par hay dos mensajes de commit para el mismo cambio. Tiempo estimado: {estimated_time(rules)}.",
        "Puedes hacerlo en varias sentadas. Escribe la respuesta detrás de los dos puntos de cada línea.",
        "",
    ]
    for name, text in _INSTRUCTIONS:
        lines.append(f"- **{name}**: {text}")
    lines.append("")
    for pair in sheet["pares"]:
        lines += [f"## Par {pair['num']}", ""]
        lines.append(f"Diff: {pair['ficheros']} ficheros, +{pair['mas']} −{pair['menos']}")
        lines.append("")
        fence = _fence_for(pair["diff"])
        lines += [fence + "diff", pair["diff"].rstrip("\n"), fence, ""]
        for side in "AB":
            text = pair[side]
            fence = _fence_for(text)
            lines += [f"### Mensaje {side}", "", fence, text.strip("\n"), fence, ""]
        for side in "AB":
            lines.append(f"Inventa {side} (s/n): ")
        for side in "AB":
            mark = " [opcional]" if "principal" in optional_ones else ""
            lines.append(f"Lo principal {side} (s/p/n):{mark} ")
        for side in "AB":
            mark = " [opcional]" if "especifico" in optional_ones else ""
            lines.append(f"Específico {side} (s/n):{mark} ")
        lines += ["Mejor (A/B/=): ", ""]
    return "\n".join(lines)


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hoja __N__: mensajes de commit, a ciegas</title>
<style>
body{font-family:system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:1rem 1.5rem 6rem;color:#1b1b1b;line-height:1.45}
header.barra{position:sticky;top:0;background:#fff;border-bottom:2px solid #ccc;padding:.5rem 0;z-index:5;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
#faltan{font-weight:700}
button{font:inherit;padding:.4rem .8rem;cursor:pointer}
section.par{border:1px solid #bbb;border-radius:6px;margin:1.5rem 0;padding:.5rem 1rem 1rem}
section.par.completo{border-color:#2e7d32}
pre{font-family:ui-monospace,Consolas,monospace;font-size:.88rem;white-space:pre-wrap;word-break:break-word;background:#f6f6f6;border:1px solid #ddd;padding:.6rem;margin:.3rem 0}
pre.diff{max-height:28rem;overflow:auto;white-space:pre}
.mensajes{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media (max-width:800px){.mensajes{grid-template-columns:1fr}}
fieldset{border:1px solid #ccc;margin:.4rem 0;padding:.3rem .6rem}
legend{font-size:.9rem;color:#444}
label{margin-right:1rem;white-space:nowrap}
fieldset.pref{margin-top:.8rem;border-color:#555}
fieldset.pref:disabled{opacity:.5}
details.opcional>summary{cursor:pointer;color:#555}
textarea{width:100%;height:7rem;font-family:ui-monospace,Consolas,monospace;font-size:.8rem}
dl dt{font-weight:700}
</style>
</head>
<body>
<h1>Hoja __N__: mensajes de commit, a ciegas</h1>
<p>En cada par hay dos mensajes de commit para el mismo cambio. Léelos tal como están, abre el diff si lo necesitas y contesta. Tiempo estimado: __TIEMPO__. Puedes hacerlo en varias sentadas: tu progreso se guarda en este navegador.</p>
<dl>__INSTRUCCIONES__</dl>
<header class="barra">
<span id="faltan">Faltan … respuestas</span>
<button type="button" id="descargar">Descargar respuestas</button>
<button type="button" id="parar">¿Puedo parar ya?</button>
<span id="aviso" role="status"></span>
</header>
<div id="pares"></div>
<h2>Respuestas en texto</h2>
<p>Si el navegador no deja descargar, copia este cuadro y pégalo en un mensaje.</p>
<textarea id="copia" readonly aria-label="Respuestas en JSON"></textarea>
<script type="application/json" id="datos">__DATOS__</script>
<script id="logica">
const CAMPOS_DE_PREGUNTA = {
  inventa: ["s", "n"],
  principal: ["s", "p", "n"],
  especifico: ["s", "n"],
};
function camposObligatorios(datos) {
  const campos = ["inventa.A", "inventa.B"];
  for (const q of ["principal", "especifico"]) {
    if (!datos.opcionales.includes(q)) campos.push(q + ".A", q + ".B");
  }
  campos.push("preferencia");
  return campos;
}
function faltan(estado, datos) {
  const falta = [];
  for (const par of datos.pares) {
    const e = estado[par.num] || {};
    for (const campo of camposObligatorios(datos)) {
      if (!e[campo]) falta.push([par.num, campo]);
    }
  }
  return falta;
}
function exportar(estado, datos, parcial) {
  const respuestas = {};
  for (const par of datos.pares) {
    const e = estado[par.num] || {};
    const r = {};
    for (const q of Object.keys(CAMPOS_DE_PREGUNTA)) {
      for (const lado of ["A", "B"]) {
        const v = e[q + "." + lado];
        if (v) {
          r[q] = r[q] || {};
          r[q][lado] = v;
        }
      }
    }
    if (e.preferencia) r.preferencia = e.preferencia;
    if (Object.keys(r).length) respuestas[par.num] = r;
  }
  return { hoja: datos.n, sha256: datos.id, parcial: !!parcial, respuestas };
}
</script>
<script id="interfaz">
(function () {
  const datos = JSON.parse(document.getElementById("datos").textContent);
  const clave = "hoja-commit-" + datos.id.slice(0, 16);
  let estado = {};
  try { estado = JSON.parse(localStorage.getItem(clave) || "{}"); } catch (e) { estado = {}; }
  const NOMBRES = { s: "sí", n: "no", p: "parcial" };
  const raiz = document.getElementById("pares");
  function radios(par, campo, valores, etiquetas) {
    const out = [];
    for (const v of valores) {
      const id = "r-" + par.num + "-" + campo + "-" + v;
      out.push('<label for="' + id + '"><input type="radio" id="' + id + '" name="' + par.num + "-" + campo + '" value="' + v + '" data-par="' + par.num + '" data-campo="' + campo + '"> ' + etiquetas[v] + "</label>");
    }
    return out.join("");
  }
  function pregunta(par, q, lado, texto) {
    return '<fieldset><legend>' + texto + "</legend>" + radios(par, q + "." + lado, CAMPOS_DE_PREGUNTA[q], NOMBRES) + "</fieldset>";
  }
  function mensaje(par, lado) {
    const opc = (q) => datos.opcionales.includes(q);
    const principal = pregunta(par, "principal", lado, "¿Nombra el cambio más importante?");
    const especifico = pregunta(par, "especifico", lado, "¿Se entiende sin abrir el diff?");
    const extras = (opc("principal") || opc("especifico"))
      ? '<details class="opcional"><summary>Si te apetece</summary>' + (opc("principal") ? principal : "") + (opc("especifico") ? especifico : "") + "</details>"
      : "";
    return '<div class="msg"><h3>Mensaje ' + lado + "</h3><pre>" + esc(par[lado]) + "</pre>" +
      pregunta(par, "inventa", lado, "¿Dice algo que el diff no hace?") +
      (opc("principal") ? "" : principal) + (opc("especifico") ? "" : especifico) + extras + "</div>";
  }
  function esc(t) { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  for (const par of datos.pares) {
    const sec = document.createElement("section");
    sec.className = "par";
    sec.id = "par-" + par.num;
    sec.innerHTML = "<h2>Par " + par.num + "</h2>" +
      "<details><summary>Diff (" + par.ficheros + " ficheros, +" + par.mas + " −" + par.menos + ")</summary><pre class=\"diff\">" + esc(par.diff) + "</pre></details>" +
      '<div class="mensajes">' + mensaje(par, "A") + mensaje(par, "B") + "</div>" +
      '<fieldset class="pref" id="pref-' + par.num + '"><legend>¿Cuál prefieres?</legend>' +
      radios(par, "preferencia", ["A", "B", "="], { A: "Mensaje A", B: "Mensaje B", "=": "Empate" }) + "</fieldset>";
    raiz.appendChild(sec);
  }
  function refrescar() {
    for (const input of document.querySelectorAll("input[type=radio]")) {
      const e = estado[input.dataset.par] || {};
      input.checked = e[input.dataset.campo] === input.value;
    }
    for (const par of datos.pares) {
      const e = estado[par.num] || {};
      const listo = !!(e["inventa.A"] && e["inventa.B"]);
      document.getElementById("pref-" + par.num).disabled = !listo;
      const falta = faltan({ [par.num]: e }, { ...datos, pares: [par] });
      document.getElementById("par-" + par.num).classList.toggle("completo", falta.length === 0);
    }
    const n = faltan(estado, datos).length;
    document.getElementById("faltan").textContent = n === 0 ? "No falta ninguna respuesta" : "Faltan " + n + " respuestas";
    document.getElementById("copia").value = JSON.stringify(exportar(estado, datos, n > 0), null, 1);
  }
  document.addEventListener("change", (ev) => {
    const t = ev.target;
    if (!t.dataset || !t.dataset.par) return;
    estado[t.dataset.par] = estado[t.dataset.par] || {};
    estado[t.dataset.par][t.dataset.campo] = t.value;
    try { localStorage.setItem(clave, JSON.stringify(estado)); } catch (e) { /* sin almacenamiento: queda el cuadro de texto */ }
    refrescar();
  });
  function descargar(nombre, contenido) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(contenido, null, 1)], { type: "application/json" }));
    a.download = nombre;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  document.getElementById("descargar").addEventListener("click", () => {
    const n = faltan(estado, datos).length;
    descargar("respuestas-" + datos.n + ".json", exportar(estado, datos, n > 0));
    document.getElementById("aviso").textContent = n > 0 ? "Descargadas con " + n + " respuestas sin contestar." : "Descargadas.";
  });
  document.getElementById("parar").addEventListener("click", () => {
    descargar("respuestas-parcial-" + datos.n + ".json", exportar(estado, datos, true));
    document.getElementById("aviso").textContent = "Descargado: pásalo para saber si puedes parar.";
  });
  refrescar();
})();
</script>
</body>
</html>
"""


def render_html(sheet: dict[str, Any], rules: dict[str, Any]) -> str:
    data = json.dumps(sheet, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    instructions = "".join(
        f"<dt>{html.escape(name)}</dt><dd>{html.escape(text)}</dd>" for name, text in _INSTRUCTIONS
    )
    return (
        _HTML_TEMPLATE.replace("__N__", str(sheet["n"]))
        .replace("__TIEMPO__", html.escape(estimated_time(rules)))
        .replace("__INSTRUCCIONES__", instructions)
        .replace("__DATOS__", data)
    )


def write_sheet(
    sheet: dict[str, Any],
    key: dict[str, Any],
    rules: dict[str, Any],
    sheet_dir: Path,
    key_dir: Path,
) -> dict[str, Path]:
    """Escribe `hoja-<n>.html`, `hoja-<n>.md` y `clave-<n>.json`; la clave en OTRA carpeta."""
    if sheet_dir.resolve() == key_dir.resolve():
        raise SystemExit("la clave no puede ir en la carpeta de la hoja")
    n = sheet["n"]
    paths = {
        "html": sheet_dir / f"hoja-{n}.html",
        "md": sheet_dir / f"hoja-{n}.md",
        "clave": key_dir / f"clave-{n}.json",
    }
    existing = [str(r) for r in paths.values() if r.exists()]
    if existing:
        # Regenerar sortea otra vez: una hoja ya contestada quedaria emparejada con otra clave.
        raise SystemExit(f"ya existen {', '.join(existing)}; elige otro numero de hoja")
    sheet_dir.mkdir(parents=True, exist_ok=True)
    key_dir.mkdir(parents=True, exist_ok=True)
    paths["html"].write_text(render_html(sheet, rules), encoding="utf-8", newline="\n")
    paths["md"].write_text(render_md(sheet, rules), encoding="utf-8", newline="\n")
    paths["clave"].write_text(
        json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return paths


# --- Lectura de las respuestas ----------------------------------------------------------------------

_MD_SHEET = re.compile(r"^Hoja:\s*([0-9a-f]{64})\s*$")
_MD_INVENTS = re.compile(r"^Inventa ([AB]) \(s/n\):(?: \[opcional\])?[ \t]*(\S*)[ \t]*$")
_MD_PRINCIPAL = re.compile(r"^Lo principal ([AB]) \(s/p/n\):(?: \[opcional\])?[ \t]*(\S*)[ \t]*$")
_MD_SPECIFIC = re.compile(r"^Espec[ií]fico ([AB]) \(s/n\):(?: \[opcional\])?[ \t]*(\S*)[ \t]*$")
_MD_BETTER = re.compile(r"^Mejor \(A/B/=\):[ \t]*(\S*)[ \t]*$")


def md_answers(sheet_md: str) -> dict[str, Any]:
    """Las respuestas escritas a mano en la hoja `.md`, como el JSON de la pagina.

    Se salta lo que va dentro de una valla: el mensaje lo escribio un modelo, y una linea
    «Mejor (A/B/=): A» dentro de el no puede votar por nadie.
    """
    sha: str | None = None
    responses: dict[str, Any] = {}
    pair: str | None = None
    fence: str | None = None
    for line in sheet_md.splitlines():
        if fence is not None:
            if line == fence:
                fence = None
            continue
        if re.fullmatch(r"`{3,}(?:diff)?", line) or line.startswith("```"):
            fence = re.match(r"`+", line).group(0)  # type: ignore[union-attr]
            continue
        if m := _MD_SHEET.match(line):
            sha = m.group(1)
        elif m := re.match(r"^## Par (\d+)\s*$", line):
            pair = m.group(1)
        elif pair is not None:
            actual = responses.setdefault(pair, {})
            if m := _MD_INVENTS.match(line):
                actual.setdefault("inventa", {})[m.group(1)] = m.group(2)
            elif m := _MD_PRINCIPAL.match(line):
                actual.setdefault("principal", {})[m.group(1)] = m.group(2)
            elif m := _MD_SPECIFIC.match(line):
                actual.setdefault("especifico", {})[m.group(1)] = m.group(2)
            elif m := _MD_BETTER.match(line):
                actual["preferencia"] = m.group(1)
    return {"sha256": sha, "respuestas": responses}


def _normal(value: Any, question: str, pair: str) -> str | None:
    """El valor ya validado, o `None` si esta vacio."""
    if value is None:
        return None
    text = str(value).strip()
    if question == "preferencia":
        text = text.upper() if text.lower() not in ("empate", "=") else "="
        text = {"EMPATE": "="}.get(text, text)
    else:
        text = _SYNONYMS_RESPONSE.get(text.lower(), text.lower())
    if text == "":
        return None
    if text not in _VALUES[question]:
        raise SystemExit(
            f"par {pair}: el valor {value!r} no es valido para {question} "
            f"(admite {', '.join(_VALUES[question])})"
        )
    return text


def read_commit(
    responses: dict[str, Any],
    key: dict[str, Any],
    rules: dict[str, Any],
    *,
    partial: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """`(juicio, faltan)`: las respuestas ya validadas y destapadas con la clave.

    Valida que son de ESA hoja (`sha256`) y que los valores son validos. Con la hoja entera, `faltan`
    lista lo obligatorio segun `reglas.json` que no esta contestado; con `parcial`, solo se valida lo
    que hay y `faltan` va vacio (la parada solo necesita lo contestado).
    """
    if responses.get("sha256") != key["sha256"]:
        raise SystemExit(
            "las respuestas no son de esta hoja: el sha256 no coincide con el de la clave"
        )
    key_pairs = key["pares"]
    unknown_ones = sorted(set(responses.get("respuestas", {})) - set(key_pairs))
    if unknown_ones:
        raise SystemExit(
            f"las respuestas traen pares que la hoja no tiene: {', '.join(unknown_ones)}"
        )
    optional_ones = set(rules["preguntas_opcionales"])
    pairs_judgement: dict[str, Any] = {}
    missing: list[str] = []
    for num, meta in sorted(key_pairs.items()):
        given = responses.get("respuestas", {}).get(num, {})
        pair: dict[str, Any] = {"tipo": meta["tipo"], "caso": meta["caso"], "lados": meta["lados"]}
        for question in ("inventa", "principal", "especifico"):
            by_side = {
                side: _normal((given.get(question) or {}).get(side), question, num) for side in "AB"
            }
            pair[question] = by_side
            if question not in optional_ones and not partial:
                missing += [
                    f"par {num}: {question} {side}" for side in "AB" if by_side[side] is None
                ]
        pair["preferencia"] = _normal(given.get("preferencia"), "preferencia", num)
        if pair["preferencia"] is None and not partial:
            missing.append(f"par {num}: preferencia")
        pairs_judgement[num] = pair
    judgement = {
        "schema_version": 1,
        "hoja": key["sha256"],
        "juego": key.get("juego"),
        "parcial": partial,
        "label_26b": key["label_26b"],
        "label_qwen": key["label_qwen"],
        "pares": pairs_judgement,
    }
    return judgement, missing


def _winner(pair: dict[str, Any]) -> str:
    choice = pair["preferencia"]
    return "empate" if choice == "=" else str(pair["lados"][choice])


def can_stop(judgement: dict[str, Any], rules: dict[str, Any]) -> str:
    """«puedes parar» o «sigue», y nada mas: ni hacia donde va el resultado ni quien va ganando.

    Solo contesta «puedes parar» si las 3 trampas estan contestadas y la hoja vale (criterio 0) Y el
    desenlace ya no puede cambiar con los pares que faltan: el 26B ya pasa de `max_inventa_26b`, o
    `v - c` es mayor que los pares reales sin contestar.
    """
    if not rules["parada_anticipada"]:
        return "sigue"
    pair_items = judgement["pares"].values()
    traps = [p for p in pair_items if p["tipo"] == TRAP]
    if len(traps) < 3 or any(p["preferencia"] is None for p in traps):
        return "sigue"
    if sum(_winner(p) not in ("empate", TRAP) for p in traps) < 2:
        return "sigue"
    real = [p for p in pair_items if p["tipo"] == "real"]
    model = judgement["label_26b"]
    invents = 0
    for p in real:
        side = "A" if p["lados"]["A"] == model else "B"
        invents += p["inventa"][side] == "s"
    if invents > int(rules["max_inventa_26b"]):
        return "puedes parar"
    answered = [p for p in real if p["preferencia"] is not None]
    c = sum(_winner(p) == model for p in answered)
    v = sum(_winner(p) == judgement["label_qwen"] for p in answered)
    unanswered = len(real) - len(answered)
    return "puedes parar" if v - c > unanswered else "sigue"


def _load_responses(args: argparse.Namespace) -> dict[str, Any]:
    if args.md is not None:
        return md_answers(args.md.read_text(encoding="utf-8"))
    return json.loads(args.answers.read_text(encoding="utf-8"))


def run_generate_commit(args: argparse.Namespace) -> int:
    data = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in data["cases"]}
    rules = read_rules(args.rules)
    traps = json.loads(args.traps.read_text(encoding="utf-8"))
    seed = args.semilla if args.semilla is not None else secrets.randbits(32)
    sheet, key = build_commit_sheet(
        cases=cases,
        sources=args.cases.parent / "fuentes",
        records=_registros(args.jsonl),
        traps=traps,
        rules=rules,
        case_set_item=args.trap_set,
        number=args.number,
        seed=seed,
        label_26b=args.label_26b,
        label_qwen=args.label_qwen,
    )
    paths = write_sheet(sheet, key, rules, args.sheet_dir, args.key_dir)
    print(
        f"{len(sheet['pares'])} pares en {paths['html']}; la clave ({paths['clave'].parent}) no se abre"
    )
    if key["omitidos"]:
        print(f"omitidos por falta de mensaje: {', '.join(key['omitidos'])}", file=sys.stderr)
    return 0


def run_read_commit(args: argparse.Namespace) -> int:
    rules = read_rules(args.rules)
    key = json.loads(args.clave.read_text(encoding="utf-8"))
    judgement, missing = read_commit(_load_responses(args), key, rules, partial=args.partial)
    if args.partial:
        print(can_stop(judgement, rules))
        return 0
    if missing:
        print("Falta por contestar, y no se produce nada hasta completarlo:", file=sys.stderr)
        for line in missing:
            print(f"  - {line}", file=sys.stderr)
        return 1
    if args.salida:
        args.salida.write_text(
            json.dumps(judgement, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print("ok: hoja completa")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    sub = parser.add_subparsers(dest="modo", required=True)
    gen = sub.add_parser("generar")
    gen.add_argument("--hoja", type=Path, required=True)
    gen.add_argument("--clave", type=Path, required=True)
    gen.add_argument("--cases", type=Path, required=True)
    gen.add_argument("--pequeno", required=True)
    gen.add_argument("--grande", required=True)
    gen.add_argument("--caso", action="append", required=True)
    gen.add_argument("--semilla", type=int, default=None, help="solo para pruebas")
    gen.add_argument("jsonl", nargs="+", type=Path)
    gc = sub.add_parser("generate-commit", help="hoja a ciegas de local_commit_msg (REQ-042)")
    gc.add_argument("--cases", type=Path, default=AFFINITY_BASE / "cases.json")
    gc.add_argument("--traps", type=Path, default=AFFINITY_BASE / "trampas.json")
    gc.add_argument("--rules", type=Path, default=AFFINITY_BASE / "reglas.json")
    gc.add_argument("--trap-set", type=int, default=1, help="juego de trampas (1 a 3)")
    gc.add_argument("--number", type=int, default=1, help="numero de hoja")
    gc.add_argument("--semilla", type=int, default=None, help="solo para pruebas")
    gc.add_argument("--label-26b", default=MODEL_26B)
    gc.add_argument("--label-qwen", default=QWEN_MODEL)
    gc.add_argument("--sheet-dir", type=Path, default=AFFINITY_BASE / "hoja")
    gc.add_argument("--key-dir", type=Path, default=AFFINITY_BASE / "clave")
    gc.add_argument(
        "jsonl", nargs="+", type=Path, help="resultados de la tanda con --save-responses"
    )
    lc = sub.add_parser("read-commit", help="valida las respuestas de la hoja de commit")
    lc.add_argument("--clave", type=Path, required=True)
    lc.add_argument("--rules", type=Path, default=AFFINITY_BASE / "reglas.json")
    origen = lc.add_mutually_exclusive_group(required=True)
    origen.add_argument("--answers", type=Path, help="respuestas-<n>.json de la pagina")
    origen.add_argument("--md", type=Path, help="la hoja .md contestada a mano")
    lc.add_argument("--partial", action="store_true", help="solo contesta «puedes parar» o «sigue»")
    lc.add_argument(
        "--salida", type=Path, default=None, help="juicio ya destapado, para el veredicto"
    )
    des = sub.add_parser("destapar")
    des.add_argument("--hoja", type=Path, required=True)
    des.add_argument("--clave", type=Path, required=True)
    des.add_argument(
        "--json",
        type=Path,
        default=None,
        help="escribe el resultado por caso; es el --pares de `analizar_benchmark.py decidir`",
    )
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if args.modo == "generate-commit":
        return run_generate_commit(args)
    if args.modo == "read-commit":
        return run_read_commit(args)
    try:
        if args.modo == "generar":
            if args.clave.exists() or args.hoja.exists():
                # Regenerar sortea otra vez: una hoja ya elegida quedaria emparejada con otra clave.
                raise ValueError("la hoja o la clave ya existen; elige otras rutas")
            data = json.loads(args.cases.read_text(encoding="utf-8"))
            corpus = {c["id"]: c for c in data["cases"]}
            semilla = args.semilla if args.semilla is not None else secrets.randbits(32)
            hoja, clave = generar(
                _registros(args.jsonl), corpus, args.caso, args.pequeno, args.grande, semilla
            )
            args.hoja.write_text(hoja, encoding="utf-8")
            args.clave.write_text(
                json.dumps(clave, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"{len(clave['pares'])} pares en {args.hoja}; la clave no se abre hasta elegir")
            return 0
        resultado, faltan = destapar(
            args.hoja.read_text(encoding="utf-8"),
            json.loads(args.clave.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json and not faltan:
        # Solo con la hoja entera: una decision sobre elecciones a medias parece una medida.
        args.json.write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        "| Caso | Pares | Metrica prefiere | Acuerdos | Acuerdo | Veredicto | Elegido por la persona |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for caso, fila in resultado.items():
        acuerdo = "—" if fila["acuerdo"] is None else f"{fila['acuerdo']:.0%}"
        humano = ", ".join(f"{k}: {v}" for k, v in sorted(fila["humano"].items()))
        print(
            f"| {caso} | {fila['pares']} | {fila['metrica_prefiere']} | {fila['acuerdos']} | "
            f"{acuerdo} | {fila['veredicto']} | {humano} |"
        )
    if faltan:
        print(f"\nfaltan por elegir {len(faltan)} pares: {', '.join(faltan)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
