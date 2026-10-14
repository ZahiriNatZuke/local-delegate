#!/usr/bin/env python3
"""Hoja por pares, a ciegas, para validar la puntuacion automatica contra juicio humano (P-15).

La cobertura de terminos puede medir vocabulario y no correccion: el cuarto piloto de CP-3 vio al
mismo modelo pasar de 1,0 a 0 segun nombrara o describiera, y al 2B puntuar tras contradecir la
fuente. Antes de fiarse de ella en la tanda, se contrasta con la pregunta que §7 decide de verdad:
¿cual de estas dos respuestas es mejor?

- `generate` empareja, por caso, la corrida i de dos configuraciones (solo si las dos son validas y
  puntuadas), sortea que respuesta va como A y cual como B, baraja los pares y numera DESPUES. La
  clave, con los modelos y las puntuaciones automaticas, va a un fichero aparte.
- `generate-commit` y `read-commit`: la hoja a ciegas de `local_commit_msg` del SDD
  `daemon-reparte-el-backend` (REQ-042), al final de este modulo.
- `unblind` lee las elecciones (A, B o =) y dice, por caso, en cuantos pares la metrica prefiere a
  uno y en cuantos de esos coincide la persona. Un empate humano donde la metrica ve diferencia NO es
  acuerdo: la metrica afirmo algo que la persona no ve. Un caso es valido con al menos
  `MIN_PREFERENCES` preferencias de la metrica y `AGREEMENT_THRESHOLD` de acuerdo; con menos, «sin base».

Uso:
    python scripts/pair_sheet.py generate --sheet pares.md --key pares-clave.json \\
        --cases benchmarks/catalogo-2026-09/cases.json --small cp3-qwen35-2b \\
        --large cp3-qwen25-coder-14b --case resumen-changelog-7k ... resultados/cp3d-*.jsonl
    python scripts/pair_sheet.py unblind --sheet pares.md --key pares-clave.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import random
import re
import secrets
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from script_i18n import argparse_in_language, format_number, lang, t

AGREEMENT_THRESHOLD = 0.8
MIN_PREFERENCES = 3
#: El veredicto de cada caso en la tabla de `unblind`, en el idioma vigente.
_VERDICT_KEYS = {
    "valid": "cli.script.pair_sheet.verdict.valid",
    "invalid": "cli.script.pair_sheet.verdict.invalid",
    "no_baseline": "cli.script.pair_sheet.verdict.no_baseline",
}
#: Lo que `unblind --json` escribe en `human` cuando la persona elige «=»: valor de máquina. Una
#: hoja destapada antes del frente B escribió `empate`; los lectores aceptan los dos para siempre.
HUMAN_TIE = "tie"
HUMAN_TIE_OLD = "empate"

# La hoja sale en el idioma del proceso y el lector acepta las dos formas, sea cual sea el idioma:
# una hoja contestada en español sigue valiendo con el proceso en inglés y al revés.
_PAIR_RE = re.compile(r"^## (?:Par|Pair) (\d+)\s*$")
_CHOICE_RE = re.compile(r"^(?:Mejor|Better) \(A/B/=\):[ \t]*(\S*)[ \t]*$")


def _load_legacy_names() -> Any:
    """`src/local_delegate/legacy_names.py`, cargado por ruta: solo usa la biblioteca estandar, y
    asi este programa lee las filas viejas con la misma tabla que el paquete sin importarlo."""
    path = Path(__file__).resolve().parents[1] / "src" / "local_delegate" / "legacy_names.py"
    spec = importlib.util.spec_from_file_location("_legacy_names", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY_NAMES = _load_legacy_names()


def _records(paths: list[Path]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(LEGACY_NAMES.normalize_benchmark_result(json.loads(line)))
    return records


def _fence(text: str) -> str:
    """Una valla mas larga que cualquier racha de acentos graves de la respuesta."""
    streaks = [len(m) for m in re.findall(r"`+", text)]
    return "`" * max(3, max(streaks, default=0) + 1)


def _valid_runs(records: list[dict[str, Any]], label: str, case: str) -> dict[int, dict[str, Any]]:
    """El ultimo intento de cada corrida, si es valido y tiene puntuacion automatica."""
    latest: dict[int, dict[str, Any]] = {}
    for r in records:
        if r.get("label") == label and r.get("case") == case and r.get("input_variant") is None:
            latest[int(r["run"])] = r  # el fichero va en orden: el ultimo intento pisa a los otros
    valid_ones = {}
    for run, r in latest.items():
        quality = (r.get("score") or {}).get("quality")
        if r.get("discarded") or quality is None:
            continue
        if "response" not in r:
            raise ValueError(
                t("cli.script.pair_sheet.no_saved_response", label=label, case=case, run=run)
            )
        valid_ones[run] = r
    return valid_ones


def generate(
    records: list[dict[str, Any]],
    corpus: dict[str, dict[str, Any]],
    cases: list[str],
    small: str,
    large: str,
    seed: int,
) -> tuple[str, dict[str, Any]]:
    rng = random.Random(seed)
    pairs = []
    for case in cases:
        a, b = (
            _valid_runs(records, small, case),
            _valid_runs(records, large, case),
        )
        for run in sorted(set(a) & set(b)):
            pairs.append((case, run, a[run], b[run]))
    if not pairs:
        raise ValueError(t("cli.script.pair_sheet.no_valid_pair"))
    rng.shuffle(pairs)
    lines = [
        t("cli.script.pair_sheet.p15.title"),
        "",
        *t("cli.script.pair_sheet.p15.intro").split("\n"),
        "",
    ]
    key: dict[str, Any] = {"seed": seed, "small": small, "large": large, "pairs": {}}
    for number, (case, run, reg_p, reg_g) in enumerate(pairs, 1):
        pair = f"{number:02d}"
        meta = corpus.get(case) or {}
        sides = [(small, reg_p), (large, reg_g)]
        rng.shuffle(sides)
        lines += [
            t("cli.script.pair_sheet.pair_heading", num=pair),
            "",
            t(
                "cli.script.pair_sheet.p15.task",
                tool=meta.get("tool", "?"),
                source=meta.get("source_file", "?"),
            ),
            "",
            f"> {meta.get('system') or ''}",
            "",
        ]
        for letter, (_label, reg) in zip("AB", sides, strict=True):
            response = str(reg["response"])
            fence = _fence(response)
            lines += [
                t("cli.script.pair_sheet.p15.response", side=letter),
                "",
                fence,
                response,
                fence,
                "",
            ]
        lines += [t("cli.script.pair_sheet.better") + " ", ""]
        key["pairs"][pair] = {
            "case": case,
            "run": run,
            "A": {"label": sides[0][0], "quality": sides[0][1]["score"]["quality"]},
            "B": {"label": sides[1][0], "quality": sides[1][1]["score"]["quality"]},
        }
    return "\n".join(lines), key


def read_choices(sheet: str) -> dict[str, str | None]:
    """Lee las elecciones saltandose lo que va dentro de la valla: la respuesta la escribio un
    modelo, y una linea «Mejor (A/B/=): A» dentro de ella no puede votar por el."""
    choices: dict[str, str | None] = {}
    current: str | None = None
    fence: str | None = None
    for line in sheet.splitlines():
        if fence is not None:
            if line == fence:
                fence = None
            continue
        if re.fullmatch(r"`{3,}", line):
            fence = line
            continue
        if m := _PAIR_RE.match(line):
            current = m.group(1)
            choices[current] = None
        elif current is not None and (m := _CHOICE_RE.match(line)):
            value = m.group(1).upper()
            if value == "":
                choices[current] = None
            elif value in {"A", "B", "="}:
                choices[current] = value
            else:
                raise ValueError(
                    t("cli.script.pair_sheet.bad_choice", pair=current, value=repr(m.group(1)))
                )
            current = None
    return choices


def unblind(sheet: str, key: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    choices = read_choices(sheet)
    pairs = key["pairs"]
    if set(choices) != set(pairs):
        raise ValueError(t("cli.script.pair_sheet.sheet_key_mismatch"))
    missing = sorted(pair for pair, choice in choices.items() if choice is None)
    per_case: dict[str, dict[str, Any]] = {}
    for pair, choice in sorted(choices.items()):
        if choice is None:
            continue
        meta = pairs[pair]
        row = per_case.setdefault(
            meta["case"],
            {"pairs": 0, "metric_prefers": 0, "agreements": 0, "human": {}},
        )
        row["pairs"] += 1
        human_winner = HUMAN_TIE if choice == "=" else meta[choice]["label"]
        row["human"][human_winner] = row["human"].get(human_winner, 0) + 1
        qa, qb = meta["A"]["quality"], meta["B"]["quality"]
        if qa == qb:
            continue  # la metrica no prefiere: nada que validar en este par
        row["metric_prefers"] += 1
        preferred = "A" if qa > qb else "B"
        if choice == preferred:
            row["agreements"] += 1
    for row in per_case.values():
        n = row["metric_prefers"]
        row["agreement"] = row["agreements"] / n if n else None
        if n < MIN_PREFERENCES:
            row["verdict"] = "no_baseline"
        elif row["agreement"] >= AGREEMENT_THRESHOLD:
            row["verdict"] = "valid"
        else:
            row["verdict"] = "invalid"
    return per_case, missing


# --- Hoja a ciegas de `local_commit_msg` (REQ-042) --------------------------------------------------
#
# Para el usuario, que juzga 33 pares de mensajes de commit sin saber de que modelo es cada uno. Este
# modulo NO importa `local_delegate`: la hoja se recoge mientras otras tareas editan `server.py`.
# Todo lo que decide algo vive en `reglas.json`; la clave (que mensaje es de quien) va en otra
# carpeta y solo la leen estos programas.

AFFINITY_BASE = Path(__file__).resolve().parents[1] / "benchmarks" / "afinidad-2026-10"
MODEL_26B = "gemma4-26b-a4b"
QWEN_MODEL = "qwen36-35b-a3b"
TRAP = "trap"


def _affinity_file(names: tuple[str, str]) -> Path:
    """El fichero nuevo de la evaluacion de afinidad si existe y, si no, el congelado."""
    old_name, new_name = names
    new = AFFINITY_BASE / new_name
    return new if new.exists() else AFFINITY_BASE / old_name


MAX_BODY_LINES = 5
POSSIBLE_OPTIONAL_QUESTIONS = ("principal", "specific")
_VALUES = {
    "made_up": ("s", "n"),
    "principal": ("s", "p", "n"),
    "specific": ("s", "n"),
    "preference": ("A", "B", "="),
}
#: Como se nombra cada pregunta en lo que se imprime, en el idioma vigente; el valor de maquina va
#: en ingles.
_QUESTION_KEYS = {
    "made_up": "cli.script.pair_sheet.question.made_up",
    "principal": "cli.script.pair_sheet.question.principal",
    "specific": "cli.script.pair_sheet.question.specific",
    "preference": "cli.script.pair_sheet.question.preference",
}
#: Lo que la persona puede escribir en la hoja `.md`, en los dos idiomas, y su valor de maquina
#: (`s`, `n`, `p`; los del JSON de la pagina, que no cambian).
_SYNONYMS_RESPONSE = {
    "si": "s",
    "sí": "s",
    "yes": "s",
    "y": "s",
    "no": "n",
    "parcial": "p",
    "partial": "p",
    "": "",
}
#: Las formas de «empate» de la preferencia: `=` y la palabra en los dos idiomas.
_TIE_WORDS = frozenset({"=", "empate", "tie"})


def _question(question: str) -> str:
    return t(_QUESTION_KEYS[question])


def _shown_value(value: str) -> str:
    """Un valor de maquina como lo escribe la persona en su idioma (`s` es `y` en ingles)."""
    return t("cli.script.pair_sheet.value.yes_letter") if value == "s" else value


def read_rules(path: Path) -> dict[str, Any]:
    """`rules.json` (o el `reglas.json` congelado), validado. «Inventa» y la preferencia no pueden ser opcionales: son lo que
    decide la celda, y una hoja que no los pidiera no decidiria nada."""
    rules = LEGACY_NAMES.normalize_affinity_rules(json.loads(path.read_text(encoding="utf-8")))
    maximum = rules.get("max_made_up_26b")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
        raise SystemExit(t("cli.script.pair_sheet.bad_max_made_up", file=path.name))
    optional_ones = rules.get("optional_questions")
    if not isinstance(optional_ones, list) or not set(optional_ones) <= set(
        POSSIBLE_OPTIONAL_QUESTIONS
    ):
        raise SystemExit(t("cli.script.pair_sheet.bad_optional_questions", file=path.name))
    if not isinstance(rules.get("early_stop"), bool):
        raise SystemExit(t("cli.script.pair_sheet.bad_early_stop", file=path.name))
    return rules


# --- La forma del mensaje ---------------------------------------------------------------------------


def split_message(message: str) -> tuple[str, list[str], bool]:
    """`(asunto, lineas de cuerpo no vacias, hay linea en blanco entre los dos)`."""
    lines = message.strip("\n").split("\n")
    subject, rest = lines[0], lines[1:]
    separate = bool(rest) and not rest[0].strip()
    return subject, [x for x in rest if x.strip()], separate


def shape(message: str) -> tuple[bool, int]:
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
            defects.append(t("cli.script.pair_sheet.defect.lowercase", line=repr(line.strip())))
        if _SENTENCE_END.search(text):
            continue
        words = re.findall(r"\w+", text)
        if (
            signed
            or text.endswith((",", ";", ":", "-"))
            or (words and words[-1].lower() in _CUTOFF_WORDS)
        ):
            defects.append(t("cli.script.pair_sheet.defect.cut", line=repr(line.strip())))
    if pair is not None and body:
        if uses_final_scoring(message) != signed:
            defects.append(
                t(
                    "cli.script.pair_sheet.defect.final_mark_closes"
                    if signed
                    else "cli.script.pair_sheet.defect.final_mark_open"
                )
            )
        long, pair_length = mean_bullet_length(message), mean_bullet_length(pair)
        if pair_length and long > MAX_LENGTH_FACTOR * pair_length:
            defects.append(
                t(
                    "cli.script.pair_sheet.defect.too_long",
                    length=f"{long:.0f}",
                    factor=format_number(MAX_LENGTH_FACTOR, None),
                    pair_length=f"{pair_length:.0f}",
                )
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
    trap = LEGACY_NAMES.normalize_affinity_trap(trap)
    _subject, model_body, separate = split_message(pair_message)
    n = min(len(model_body), MAX_BODY_LINES)
    if n == 0:
        return str(trap["subject"])
    units_list = body_units([str(x) for x in trap["body"]])
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
    return "\n".join([str(trap["subject"]), *([""] if separate else []), *lines])


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
    if last is None or last.get("discarded") or last.get("outcome") != "ok":
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
    content = json.dumps({"n": number, "pairs": pair_items}, sort_keys=True, ensure_ascii=False)
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
    rules = LEGACY_NAMES.normalize_affinity_rules(rules)
    rng = random.Random(seed)
    traps = LEGACY_NAMES.normalize_affinity_traps(traps)
    sets = traps["sets"]
    if not 1 <= case_set_item <= len(sets):
        raise SystemExit(t("cli.script.pair_sheet.no_trap_set", n=case_set_item))

    def diff_of(case_id: str) -> str:
        name = cases[case_id]["source_file"]
        return (sources / name).read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")

    real: list[tuple[str, str, str]] = []
    skipped: list[str] = []
    for case_id, case in cases.items():
        case = LEGACY_NAMES.normalize("affinity_case", case)
        if case.get("sheet_role") != "real":
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
            {"kind": "real", "case": case_id, "sides": sides, "diff": diff_of(case_id)}
        )
    entries = sets[case_set_item - 1]["traps"]
    # De las trampas tambien se equilibra el lado de la trampa y el modelo con el que se empareja.
    trap_in_a = _balanced_split(rng, len(entries), "A", "B")
    pairs = _balanced_split(rng, len(entries), label_26b, label_qwen)
    for entry, trap_side, model in zip(entries, trap_in_a, pairs, strict=True):
        case_id = entry["case"]
        message = _message_of(records, model, case_id)
        if message is None:
            raise SystemExit(t("cli.script.pair_sheet.trap_without_message", case=case_id))
        trap_text = shaped_trap(entry, message)
        defects = body_defects(trap_text, message)
        if defects:
            raise SystemExit(
                t(
                    "cli.script.pair_sheet.trap_badly_written",
                    case=case_id,
                    defects="; ".join(defects),
                )
            )
        sides = [(TRAP, trap_text), (model, message)]
        if trap_side == "B":
            sides.reverse()
        pending_items.append(
            {
                "kind": TRAP,
                "case": case_id,
                "trap_kind": entry["kind"],
                "sides": sides,
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
                "files": files_list,
                "more": more,
                "fewer": less,
                "diff": p["diff"],
                "A": p["sides"][0][1],
                "B": p["sides"][1][1],
            }
        )
        pairs_key[num] = {
            "kind": p["kind"],
            "case": p["case"],
            "sides": {"A": p["sides"][0][0], "B": p["sides"][1][0]},
            **({"trap_kind": p["trap_kind"]} if p["kind"] == TRAP else {}),
        }
    seen_set: set[str] = set()
    for pair in pair_items:
        for text in (pair["diff"], pair["A"], pair["B"]):
            if text in seen_set:
                raise SystemExit(t("cli.script.pair_sheet.repeated_text", pair=pair["num"]))
            seen_set.add(text)
    sheet = {
        "id": sheet_id(number, pair_items),
        "n": number,
        "optional": list(rules["optional_questions"]),
        "pairs": pair_items,
    }
    key = {
        "schema_version": 1,
        "sheet": number,
        "set": case_set_item,
        "sha256": sheet["id"],
        "seed": seed,
        "label_26b": label_26b,
        "label_qwen": label_qwen,
        "pairs": pairs_key,
        "omitted": skipped,
    }
    return sheet, key


# --- Renderizado ------------------------------------------------------------------------------------


def _instructions() -> list[tuple[str, str]]:
    """(nombre, explicacion) de cada pregunta de la hoja, en el idioma vigente."""
    return [
        (
            t(f"cli.script.pair_sheet.instruction.{q}.name"),
            t(f"cli.script.pair_sheet.instruction.{q}.text"),
        )
        for q in ("made_up", "principal", "specific", "preference")
    ]


def estimated_time(rules: dict[str, Any]) -> str:
    rules = LEGACY_NAMES.normalize_affinity_rules(rules)
    optional_ones = set(rules["optional_questions"])
    if {"principal", "specific"} <= optional_ones:
        return t("cli.script.pair_sheet.time.short")
    return t("cli.script.pair_sheet.time.long")


def _fence_for(text: str) -> str:
    streaks = [len(m) for m in re.findall(r"`+", text)]
    return "`" * max(3, max(streaks, default=0) + 1)


def render_md(sheet: dict[str, Any], rules: dict[str, Any]) -> str:
    rules = LEGACY_NAMES.normalize_affinity_rules(rules)
    optional_ones = set(rules["optional_questions"])
    lines = [
        t("cli.script.pair_sheet.sheet.title", n=sheet["n"]),
        "",
        t("cli.script.pair_sheet.sheet.id", id=sheet["id"]),
        "",
        t("cli.script.pair_sheet.sheet.intro", time=estimated_time(rules)),
        t("cli.script.pair_sheet.sheet.how"),
        "",
    ]
    for name, text in _instructions():
        lines.append(f"- **{name}**: {text}")
    lines.append("")
    optional = t("cli.script.pair_sheet.sheet.optional")
    for pair in sheet["pairs"]:
        lines += [t("cli.script.pair_sheet.pair_heading", num=pair["num"]), ""]
        lines.append(
            t(
                "cli.script.pair_sheet.sheet.diff",
                files=format_number(pair["files"]),
                more=pair["more"],
                fewer=pair["fewer"],
            )
        )
        lines.append("")
        fence = _fence_for(pair["diff"])
        lines += [fence + "diff", pair["diff"].rstrip("\n"), fence, ""]
        for side in "AB":
            text = pair[side]
            fence = _fence_for(text)
            lines += [
                t("cli.script.pair_sheet.sheet.message", side=side),
                "",
                fence,
                text.strip("\n"),
                fence,
                "",
            ]
        for side in "AB":
            lines.append(t("cli.script.pair_sheet.line.made_up", side=side) + " ")
        for side in "AB":
            mark = f" {optional}" if "principal" in optional_ones else ""
            lines.append(t("cli.script.pair_sheet.line.principal", side=side) + f"{mark} ")
        for side in "AB":
            mark = f" {optional}" if "specific" in optional_ones else ""
            lines.append(t("cli.script.pair_sheet.line.specific", side=side) + f"{mark} ")
        lines += [t("cli.script.pair_sheet.better") + " ", ""]
    return "\n".join(lines)


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
body{font-family:system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:1rem 1.5rem 6rem;color:#1b1b1b;line-height:1.45}
header.bar{position:sticky;top:0;background:#fff;border-bottom:2px solid #ccc;padding:.5rem 0;z-index:5;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
#faltan{font-weight:700}
button{font:inherit;padding:.4rem .8rem;cursor:pointer}
section.pair{border:1px solid #bbb;border-radius:6px;margin:1.5rem 0;padding:.5rem 1rem 1rem}
section.pair.complete{border-color:#2e7d32}
pre{font-family:ui-monospace,Consolas,monospace;font-size:.88rem;white-space:pre-wrap;word-break:break-word;background:#f6f6f6;border:1px solid #ddd;padding:.6rem;margin:.3rem 0}
pre.diff{max-height:28rem;overflow:auto;white-space:pre}
.messages{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media (max-width:800px){.messages{grid-template-columns:1fr}}
fieldset{border:1px solid #ccc;margin:.4rem 0;padding:.3rem .6rem}
legend{font-size:.9rem;color:#444}
label{margin-right:1rem;white-space:nowrap}
fieldset.pref{margin-top:.8rem;border-color:#555}
fieldset.pref:disabled{opacity:.5}
details.optional_q>summary{cursor:pointer;color:#555}
textarea{width:100%;height:7rem;font-family:ui-monospace,Consolas,monospace;font-size:.8rem}
dl dt{font-weight:700}
</style>
</head>
<body>
<h1>__TITLE__</h1>
<p>__INTRO__</p>
<dl>__INSTRUCTIONS__</dl>
<header class="bar">
<span id="faltan">__MISSING_SOME__</span>
<button type="button" id="descargar">__DOWNLOAD__</button>
<button type="button" id="parar">__CAN_I_STOP__</button>
<span id="aviso" role="status"></span>
</header>
<div id="pares"></div>
<h2>__TEXT_ANSWERS__</h2>
<p>__COPY_HINT__</p>
<textarea id="copia" readonly aria-label="__JSON_LABEL__"></textarea>
<script type="application/json" id="datos">__DATA__</script>
<script type="application/json" id="textos">__TEXTS__</script>
<script id="logica">
const QUESTION_FIELDS = {
  made_up: ["s", "n"],
  principal: ["s", "p", "n"],
  specific: ["s", "n"],
};
function requiredFields(data) {
  const fields = ["made_up.A", "made_up.B"];
  for (const q of ["principal", "specific"]) {
    if (!data.optional.includes(q)) fields.push(q + ".A", q + ".B");
  }
  fields.push("preference");
  return fields;
}
function missing(state, data) {
  const isMissing = [];
  for (const pair of data.pairs) {
    const e = state[pair.num] || {};
    for (const field of requiredFields(data)) {
      if (!e[field]) isMissing.push([pair.num, field]);
    }
  }
  return isMissing;
}
function exportar(state, data, partial) {
  const answers = {};
  for (const pair of data.pairs) {
    const e = state[pair.num] || {};
    const r = {};
    for (const q of Object.keys(QUESTION_FIELDS)) {
      for (const side of ["A", "B"]) {
        const v = e[q + "." + side];
        if (v) {
          r[q] = r[q] || {};
          r[q][side] = v;
        }
      }
    }
    if (e.preference) r.preference = e.preference;
    if (Object.keys(r).length) answers[pair.num] = r;
  }
  return { sheet: data.n, sha256: data.id, partial: !!partial, answers };
}
</script>
<script id="interfaz">
(function () {
  const data = JSON.parse(document.getElementById("datos").textContent);
  const T = JSON.parse(document.getElementById("textos").textContent);
  const fmt = (text, values) => text.replace(/\{(\w+)\}/g, (all, name) => (name in values ? values[name] : all));
  const key = "commit-sheet-" + data.id.slice(0, 16);
  let state = {};
  try { state = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { state = {}; }
  const NAMES = { s: T.yes, n: T.no, p: T.partial };
  const root = document.getElementById("pares");
  function radios(pair, field, values, labels) {
    const out = [];
    for (const v of values) {
      const id = "r-" + pair.num + "-" + field + "-" + v;
      out.push('<label for="' + id + '"><input type="radio" id="' + id + '" name="' + pair.num + "-" + field + '" value="' + v + '" data-pair="' + pair.num + '" data-field="' + field + '"> ' + labels[v] + "</label>");
    }
    return out.join("");
  }
  function question(pair, q, side, text) {
    return '<fieldset><legend>' + text + "</legend>" + radios(pair, q + "." + side, QUESTION_FIELDS[q], NAMES) + "</fieldset>";
  }
  function message(pair, side) {
    const opc = (q) => data.optional.includes(q);
    const principal = question(pair, "principal", side, T.ask_principal);
    const specific = question(pair, "specific", side, T.ask_specific);
    const extras = (opc("principal") || opc("specific"))
      ? '<details class="optional_q"><summary>' + T.if_you_like + "</summary>" + (opc("principal") ? principal : "") + (opc("specific") ? specific : "") + "</details>"
      : "";
    return '<div class="msg"><h3>' + fmt(T.message, { side }) + "</h3><pre>" + esc(pair[side]) + "</pre>" +
      question(pair, "made_up", side, T.ask_made_up) +
      (opc("principal") ? "" : principal) + (opc("specific") ? "" : specific) + extras + "</div>";
  }
  function esc(t) { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  for (const pair of data.pairs) {
    const sec = document.createElement("section");
    sec.className = "pair";
    sec.id = "par-" + pair.num;
    sec.innerHTML = "<h2>" + fmt(T.pair, { num: pair.num }) + "</h2>" +
      "<details><summary>" + fmt(T.diff, { files: pair.files, more: pair.more, fewer: pair.fewer }) + "</summary><pre class=\"diff\">" + esc(pair.diff) + "</pre></details>" +
      '<div class="messages">' + message(pair, "A") + message(pair, "B") + "</div>" +
      '<fieldset class="pref" id="pref-' + pair.num + '"><legend>' + T.which + "</legend>" +
      radios(pair, "preference", ["A", "B", "="], { A: fmt(T.message, { side: "A" }), B: fmt(T.message, { side: "B" }), "=": T.tie }) + "</fieldset>";
    root.appendChild(sec);
  }
  function refresh() {
    for (const input of document.querySelectorAll("input[type=radio]")) {
      const e = state[input.dataset.pair] || {};
      input.checked = e[input.dataset.field] === input.value;
    }
    for (const pair of data.pairs) {
      const e = state[pair.num] || {};
      const listo = !!(e["made_up.A"] && e["made_up.B"]);
      document.getElementById("pref-" + pair.num).disabled = !listo;
      const isMissing = missing({ [pair.num]: e }, { ...data, pairs: [pair] });
      document.getElementById("par-" + pair.num).classList.toggle("complete", isMissing.length === 0);
    }
    const n = missing(state, data).length;
    document.getElementById("faltan").textContent = n === 0 ? T.none_missing : fmt(T.missing, { n });
    document.getElementById("copia").value = JSON.stringify(exportar(state, data, n > 0), null, 1);
  }
  document.addEventListener("change", (ev) => {
    const t = ev.target;
    if (!t.dataset || !t.dataset.pair) return;
    state[t.dataset.pair] = state[t.dataset.pair] || {};
    state[t.dataset.pair][t.dataset.field] = t.value;
    try { localStorage.setItem(key, JSON.stringify(state)); } catch (e) { /* sin almacenamiento: queda el cuadro de texto */ }
    refresh();
  });
  function download(name, content) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(content, null, 1)], { type: "application/json" }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  document.getElementById("descargar").addEventListener("click", () => {
    const n = missing(state, data).length;
    download("answers-" + data.n + ".json", exportar(state, data, n > 0));
    document.getElementById("aviso").textContent = n > 0 ? fmt(T.downloaded_partial, { n }) : T.downloaded;
  });
  document.getElementById("parar").addEventListener("click", () => {
    download("answers-partial-" + data.n + ".json", exportar(state, data, true));
    document.getElementById("aviso").textContent = T.downloaded_stop;
  });
  refresh();
})();
</script>
</body>
</html>
"""


#: Los textos de la interfaz de la pagina que escribe el JavaScript (`T.<nombre>` en `interfaz`).
_PAGE_TEXTS = (
    "yes",
    "no",
    "partial",
    "tie",
    "ask_principal",
    "ask_specific",
    "ask_made_up",
    "if_you_like",
    "message",
    "pair",
    "diff",
    "which",
    "none_missing",
    "missing",
    "downloaded_partial",
    "downloaded",
    "downloaded_stop",
)


def _json_for_html(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def render_html(sheet: dict[str, Any], rules: dict[str, Any]) -> str:
    instructions = "".join(
        f"<dt>{html.escape(name)}</dt><dd>{html.escape(text)}</dd>"
        for name, text in _instructions()
    )
    texts = {name: t(f"cli.script.pair_sheet.page.{name}") for name in _PAGE_TEXTS}

    def page(name: str, **values: object) -> str:
        return html.escape(t(f"cli.script.pair_sheet.page.{name}", **values))

    replacements = {
        "__LANG__": lang(),
        "__TITLE__": html.escape(t("cli.script.pair_sheet.sheet.title_plain", n=sheet["n"])),
        "__INTRO__": page("intro", time=estimated_time(rules)),
        "__MISSING_SOME__": page("missing_some"),
        "__DOWNLOAD__": page("download"),
        "__CAN_I_STOP__": page("can_i_stop"),
        "__TEXT_ANSWERS__": page("text_answers"),
        "__COPY_HINT__": page("copy_hint"),
        "__JSON_LABEL__": page("json_label"),
        "__INSTRUCTIONS__": instructions,
        "__TEXTS__": _json_for_html(texts),
        "__DATA__": _json_for_html(sheet),
    }
    page_html = _HTML_TEMPLATE
    for marker, value in replacements.items():
        page_html = page_html.replace(marker, value)
    return page_html


def write_sheet(
    sheet: dict[str, Any],
    key: dict[str, Any],
    rules: dict[str, Any],
    sheet_dir: Path,
    key_dir: Path,
) -> dict[str, Path]:
    """Escribe `sheet-<n>.html`, `sheet-<n>.md` y `key-<n>.json`; la clave en OTRA carpeta."""
    if sheet_dir.resolve() == key_dir.resolve():
        raise SystemExit(t("cli.script.pair_sheet.key_in_sheet_dir"))
    n = sheet["n"]
    paths = {
        "html": sheet_dir / f"sheet-{n}.html",
        "md": sheet_dir / f"sheet-{n}.md",
        "key": key_dir / f"key-{n}.json",
    }
    existing = [str(r) for r in paths.values() if r.exists()]
    if existing:
        # Regenerar sortea otra vez: una hoja ya contestada quedaria emparejada con otra clave.
        raise SystemExit(t("cli.script.pair_sheet.sheet_exists", paths=", ".join(existing)))
    sheet_dir.mkdir(parents=True, exist_ok=True)
    key_dir.mkdir(parents=True, exist_ok=True)
    paths["html"].write_text(render_html(sheet, rules), encoding="utf-8", newline="\n")
    paths["md"].write_text(render_md(sheet, rules), encoding="utf-8", newline="\n")
    paths["key"].write_text(
        json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return paths


# --- Lectura de las respuestas ----------------------------------------------------------------------

# Las lineas de la hoja `.md` en los dos idiomas: una hoja escrita en uno se lee con el proceso en
# el otro (y la hoja congelada de `benchmarks/afinidad-2026-10/hoja/` es española para siempre).
_OPTIONAL_MARK = r"(?: \[(?:opcional|optional)\])?"
_MD_SHEET = re.compile(r"^(?:Hoja|Sheet):\s*([0-9a-f]{64})\s*$")
_MD_INVENTS = re.compile(
    rf"^(?:Inventa|Invents) ([AB]) \((?:s|y)/n\):{_OPTIONAL_MARK}[ \t]*(\S*)[ \t]*$"
)
_MD_PRINCIPAL = re.compile(
    rf"^(?:Lo principal|Main point) ([AB]) \((?:s|y)/p/n\):{_OPTIONAL_MARK}[ \t]*(\S*)[ \t]*$"
)
_MD_SPECIFIC = re.compile(
    rf"^(?:Espec[ií]fico|Specific) ([AB]) \((?:s|y)/n\):{_OPTIONAL_MARK}[ \t]*(\S*)[ \t]*$"
)
_MD_BETTER = _CHOICE_RE


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
        elif m := _PAIR_RE.match(line):
            pair = m.group(1)
        elif pair is not None:
            current = responses.setdefault(pair, {})
            if m := _MD_INVENTS.match(line):
                current.setdefault("made_up", {})[m.group(1)] = m.group(2)
            elif m := _MD_PRINCIPAL.match(line):
                current.setdefault("principal", {})[m.group(1)] = m.group(2)
            elif m := _MD_SPECIFIC.match(line):
                current.setdefault("specific", {})[m.group(1)] = m.group(2)
            elif m := _MD_BETTER.match(line):
                current["preference"] = m.group(1)
    return {"sha256": sha, "answers": responses}


def _normal(value: Any, question: str, pair: str) -> str | None:
    """El valor ya validado, o `None` si esta vacio."""
    if value is None:
        return None
    text = str(value).strip()
    if question == "preference":
        text = "=" if text.lower() in _TIE_WORDS else text.upper()
    else:
        text = _SYNONYMS_RESPONSE.get(text.lower(), text.lower())
    if text == "":
        return None
    if text not in _VALUES[question]:
        raise SystemExit(
            t(
                "cli.script.pair_sheet.bad_value",
                pair=pair,
                value=repr(value),
                question=_question(question),
                allowed=", ".join(_shown_value(v) for v in _VALUES[question]),
            )
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
    lista lo obligatorio segun `reglas.json` que no esta contestado; con `partial`, solo se valida lo
    que hay y `faltan` va vacio (la parada solo necesita lo contestado).
    """
    rules = LEGACY_NAMES.normalize_affinity_rules(rules)
    key = LEGACY_NAMES.normalize_commit_key(key)
    responses = LEGACY_NAMES.normalize_commit_answers(responses)
    if responses.get("sha256") != key["sha256"]:
        raise SystemExit(t("cli.script.pair_sheet.answers_other_sheet"))
    key_pairs = key["pairs"]
    unknown_ones = sorted(set(responses.get("answers", {})) - set(key_pairs))
    if unknown_ones:
        raise SystemExit(
            t("cli.script.pair_sheet.answers_unknown_pairs", pairs=", ".join(unknown_ones))
        )
    optional_ones = set(rules["optional_questions"])
    pairs_judgement: dict[str, Any] = {}
    missing: list[str] = []
    for num, meta in sorted(key_pairs.items()):
        given = responses.get("answers", {}).get(num, {})
        pair: dict[str, Any] = {"kind": meta["kind"], "case": meta["case"], "sides": meta["sides"]}
        for question in ("made_up", "principal", "specific"):
            by_side = {
                side: _normal((given.get(question) or {}).get(side), question, num) for side in "AB"
            }
            pair[question] = by_side
            if question not in optional_ones and not partial:
                missing += [
                    t(
                        "cli.script.pair_sheet.missing_answer",
                        pair=num,
                        question=f"{_question(question)} {side}",
                    )
                    for side in "AB"
                    if by_side[side] is None
                ]
        pair["preference"] = _normal(given.get("preference"), "preference", num)
        if pair["preference"] is None and not partial:
            missing.append(
                t(
                    "cli.script.pair_sheet.missing_answer",
                    pair=num,
                    question=_question("preference"),
                )
            )
        pairs_judgement[num] = pair
    judgement = {
        "schema_version": 1,
        "sheet": key["sha256"],
        "set": key.get("set"),
        "partial": partial,
        "label_26b": key["label_26b"],
        "label_qwen": key["label_qwen"],
        "pairs": pairs_judgement,
    }
    return judgement, missing


def _winner(pair: dict[str, Any]) -> str:
    choice = pair["preference"]
    return "tie" if choice == "=" else str(pair["sides"][choice])


#: Las dos respuestas de `can_stop`, como valores de maquina; `stop_text` las dice a la persona.
CAN_STOP = "stop"
GO_ON = "go_on"


def stop_text(answer: str) -> str:
    """«puedes parar» o «sigue» (`can stop` / `go on`), en el idioma vigente."""
    return t(f"cli.script.pair_sheet.stop.{answer}")


def can_stop(judgement: dict[str, Any], rules: dict[str, Any]) -> str:
    """`CAN_STOP` o `GO_ON`, y nada mas: ni hacia donde va el resultado ni quien va ganando.

    Solo contesta «puedes parar» si las 3 trampas estan contestadas y la hoja vale (criterio 0) Y el
    desenlace ya no puede cambiar con los pares que faltan: el 26B ya pasa de `max_made_up_26b`, o
    `v - c` es mayor que los pares reales sin contestar.
    """
    rules = LEGACY_NAMES.normalize_affinity_rules(rules)
    judgement = LEGACY_NAMES.normalize_commit_judgement(judgement)
    if not rules["early_stop"]:
        return GO_ON
    pair_items = judgement["pairs"].values()
    traps = [p for p in pair_items if p["kind"] == TRAP]
    if len(traps) < 3 or any(p["preference"] is None for p in traps):
        return GO_ON
    if sum(_winner(p) not in ("tie", TRAP) for p in traps) < 2:
        return GO_ON
    real = [p for p in pair_items if p["kind"] == "real"]
    model = judgement["label_26b"]
    invents = 0
    for p in real:
        side = "A" if p["sides"]["A"] == model else "B"
        invents += p["made_up"][side] == "s"
    if invents > int(rules["max_made_up_26b"]):
        return CAN_STOP
    answered = [p for p in real if p["preference"] is not None]
    c = sum(_winner(p) == model for p in answered)
    v = sum(_winner(p) == judgement["label_qwen"] for p in answered)
    unanswered = len(real) - len(answered)
    return CAN_STOP if v - c > unanswered else GO_ON


def _load_responses(args: argparse.Namespace) -> dict[str, Any]:
    if args.md is not None:
        return md_answers(args.md.read_text(encoding="utf-8"))
    return json.loads(args.answers.read_text(encoding="utf-8"))


def run_generate_commit(args: argparse.Namespace) -> int:
    data = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in data["cases"]}
    rules = read_rules(args.rules)
    traps = json.loads(args.traps.read_text(encoding="utf-8"))
    seed = args.seed if args.seed is not None else secrets.randbits(32)
    sheet, key = build_commit_sheet(
        cases=cases,
        sources=args.cases.parent / "fuentes",
        records=_records(args.jsonl),
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
        t(
            "cli.script.pair_sheet.generated_commit",
            n=format_number(len(sheet["pairs"])),
            path=paths["html"],
            key_dir=paths["key"].parent,
        )
    )
    if key["omitted"]:
        print(t("cli.script.pair_sheet.omitted", cases=", ".join(key["omitted"])), file=sys.stderr)
    return 0


def run_read_commit(args: argparse.Namespace) -> int:
    rules = read_rules(args.rules)
    key = json.loads(args.key.read_text(encoding="utf-8"))
    judgement, missing = read_commit(_load_responses(args), key, rules, partial=args.partial)
    if args.partial:
        print(stop_text(can_stop(judgement, rules)))
        return 0
    if missing:
        print(t("cli.script.pair_sheet.missing_header"), file=sys.stderr)
        for line in missing:
            print(f"  - {line}", file=sys.stderr)
        return 1
    if args.output:
        args.output.write_text(
            json.dumps(judgement, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(t("cli.script.pair_sheet.complete"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=t("cli.script.pair_sheet.help._description"))
    sub = parser.add_subparsers(dest="mode", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--sheet", type=Path, required=True)
    gen.add_argument("--key", type=Path, required=True)
    gen.add_argument("--cases", type=Path, required=True)
    gen.add_argument("--small", required=True)
    gen.add_argument("--large", required=True)
    gen.add_argument("--case", action="append", required=True)
    gen.add_argument("--seed", type=int, default=None, help=_help("seed"))
    gen.add_argument("jsonl", nargs="+", type=Path)
    gc = sub.add_parser("generate-commit", help=_help("generate_commit"))
    gc.add_argument("--cases", type=Path, default=AFFINITY_BASE / "cases.json")
    gc.add_argument("--traps", type=Path, default=_affinity_file(LEGACY_NAMES.TRAPS_FILE_NAMES))
    gc.add_argument("--rules", type=Path, default=_affinity_file(LEGACY_NAMES.RULES_FILE_NAMES))
    gc.add_argument("--trap-set", type=int, default=1, help=_help("trap_set"))
    gc.add_argument("--number", type=int, default=1, help=_help("number"))
    gc.add_argument("--seed", type=int, default=None, help=_help("seed"))
    gc.add_argument("--label-26b", default=MODEL_26B)
    gc.add_argument("--label-qwen", default=QWEN_MODEL)
    gc.add_argument("--sheet-dir", type=Path, default=AFFINITY_BASE / "sheet")
    gc.add_argument("--key-dir", type=Path, default=AFFINITY_BASE / "key")
    gc.add_argument("jsonl", nargs="+", type=Path, help=_help("jsonl"))
    lc = sub.add_parser("read-commit", help=_help("read_commit"))
    lc.add_argument("--key", type=Path, required=True)
    lc.add_argument("--rules", type=Path, default=_affinity_file(LEGACY_NAMES.RULES_FILE_NAMES))
    origin = lc.add_mutually_exclusive_group(required=True)
    origin.add_argument("--answers", type=Path, help=_help("answers"))
    origin.add_argument("--md", type=Path, help=_help("md"))
    lc.add_argument("--partial", action="store_true", help=_help("partial"))
    lc.add_argument("--output", type=Path, default=None, help=_help("output"))
    des = sub.add_parser("unblind")
    des.add_argument("--sheet", type=Path, required=True)
    des.add_argument("--key", type=Path, required=True)
    des.add_argument(
        "--json",
        type=Path,
        default=None,
        help=_help("json"),
    )
    with argparse_in_language():
        args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if args.mode == "generate-commit":
        return run_generate_commit(args)
    if args.mode == "read-commit":
        return run_read_commit(args)
    try:
        if args.mode == "generate":
            if args.key.exists() or args.sheet.exists():
                # Regenerar sortea otra vez: una hoja ya elegida quedaria emparejada con otra clave.
                raise ValueError(t("cli.script.pair_sheet.paths_exist"))
            data = json.loads(args.cases.read_text(encoding="utf-8"))
            corpus = {c["id"]: c for c in data["cases"]}
            seed = args.seed if args.seed is not None else secrets.randbits(32)
            sheet, key = generate(
                _records(args.jsonl), corpus, args.case, args.small, args.large, seed
            )
            args.sheet.write_text(sheet, encoding="utf-8")
            args.key.write_text(
                json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(
                t(
                    "cli.script.pair_sheet.generated",
                    n=format_number(len(key["pairs"])),
                    path=args.sheet,
                )
            )
            return 0
        result, missing = unblind(
            args.sheet.read_text(encoding="utf-8"),
            json.loads(args.key.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(t("cli.script.pair_sheet.error", detail=exc), file=sys.stderr)
        return 2
    if args.json and not missing:
        # Solo con la hoja entera: una decision sobre elecciones a medias parece una medida.
        args.json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(t("cli.script.pair_sheet.unblind.header"))
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for case, row in result.items():
        agreement = (
            "—" if row["agreement"] is None else f"{format_number(row['agreement'] * 100, 0)}%"
        )
        human = ", ".join(
            f"{t('cli.script.pair_sheet.verdict.tie') if k in (HUMAN_TIE, HUMAN_TIE_OLD) else k}: {v}"
            for k, v in sorted(row["human"].items())
        )
        print(
            f"| {case} | {row['pairs']} | {row['metric_prefers']} | {row['agreements']} | "
            f"{agreement} | {t(_VERDICT_KEYS[row['verdict']])} | {human} |"
        )
    if missing:
        print(
            "\n"
            + t(
                "cli.script.pair_sheet.unblind.missing",
                n=format_number(len(missing)),
                pairs=", ".join(missing),
            ),
            file=sys.stderr,
        )
        return 1
    return 0


def _help(name: str) -> str:
    return t(f"cli.script.pair_sheet.help.{name}")


if __name__ == "__main__":
    sys.exit(main())
