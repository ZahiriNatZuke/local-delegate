#!/usr/bin/env python3
"""Hoja por pares, a ciegas, para validar la puntuacion automatica contra juicio humano (P-15).

La cobertura de terminos puede medir vocabulario y no correccion: el cuarto piloto de CP-3 vio al
mismo modelo pasar de 1,0 a 0 segun nombrara o describiera, y al 2B puntuar tras contradecir la
fuente. Antes de fiarse de ella en la tanda, se contrasta con la pregunta que §7 decide de verdad:
¿cual de estas dos respuestas es mejor?

- `generar` empareja, por caso, la corrida i de dos configuraciones (solo si las dos son validas y
  puntuadas), sortea que respuesta va como A y cual como B, baraja los pares y numera DESPUES. La
  clave, con los modelos y las puntuaciones automaticas, va a un fichero aparte.
- `generar-commit` y `leer-commit`: la hoja a ciegas de `local_commit_msg` del SDD
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

BASE_AFINIDAD = Path(__file__).resolve().parents[1] / "benchmarks" / "afinidad-2026-10"
MODELO_26B = "gemma4-26b-a4b"
MODELO_QWEN = "qwen36-35b-a3b"
TRAMPA = "trampa"
LINEAS_DE_CUERPO_MAX = 5
PREGUNTAS_OPCIONALES_POSIBLES = ("principal", "especifico")
_VALORES = {
    "inventa": ("s", "n"),
    "principal": ("s", "p", "n"),
    "especifico": ("s", "n"),
    "preferencia": ("A", "B", "="),
}
_RESPUESTA_SINONIMOS = {"si": "s", "sí": "s", "no": "n", "parcial": "p", "empate": "=", "": ""}


def leer_reglas(ruta: Path) -> dict[str, Any]:
    """`reglas.json`, validado. «Inventa» y la preferencia no pueden ser opcionales: son lo que
    decide la celda, y una hoja que no los pidiera no decidiria nada."""
    reglas = json.loads(ruta.read_text(encoding="utf-8"))
    maximo = reglas.get("max_inventa_26b")
    if not isinstance(maximo, int) or isinstance(maximo, bool) or maximo < 0:
        raise SystemExit("reglas.json: max_inventa_26b tiene que ser un entero >= 0")
    opcionales = reglas.get("preguntas_opcionales")
    if not isinstance(opcionales, list) or not set(opcionales) <= set(
        PREGUNTAS_OPCIONALES_POSIBLES
    ):
        raise SystemExit(
            "reglas.json: preguntas_opcionales solo admite 'principal' y 'especifico'; "
            "'inventa' y la preferencia no pueden ser opcionales"
        )
    if not isinstance(reglas.get("parada_anticipada"), bool):
        raise SystemExit("reglas.json: parada_anticipada tiene que ser true o false")
    return reglas


# --- La forma del mensaje ---------------------------------------------------------------------------


def partir_mensaje(mensaje: str) -> tuple[str, list[str], bool]:
    """`(asunto, lineas de cuerpo no vacias, hay linea en blanco entre los dos)`."""
    lineas = mensaje.strip("\n").split("\n")
    asunto, resto = lineas[0], lineas[1:]
    separado = bool(resto) and not resto[0].strip()
    return asunto, [x for x in resto if x.strip()], separado


def forma(mensaje: str) -> tuple[bool, int]:
    """Lo que tiene que copiar la trampa: si lleva cuerpo y cuantas lineas (como mucho 5)."""
    _asunto, cuerpo, _sep = partir_mensaje(mensaje)
    return bool(cuerpo), min(len(cuerpo), LINEAS_DE_CUERPO_MAX)


_VINETAS = ("- ", "* ")
# Un punto (o ! o ?) seguido de espacio y de una mayuscula es el limite entre dos frases; un
# «release.py» o un «0.18.0» no lo son porque no llevan espacio detras del punto.
_LIMITE_DE_FRASE = re.compile(r"(?<=[.!?])\s+(?=[¿¡A-ZÁÉÍÓÚÑ])")
_FIN_DE_FRASE = re.compile(r"[.!?…][\"')\]»`*]*$")


def unidades_de_cuerpo(lineas: list[str]) -> list[str]:
    """Las unidades COMPLETAS de un cuerpo: cada viñeta entera y cada frase entera de un parrafo.

    Una linea fisica no es una unidad: un cuerpo escrito a 80 columnas parte las frases por la mitad,
    y convertir cada trozo en una viñeta deja una trampa que se reconoce sin leer el diff. Las viñetas
    conservan su marca; las lineas indentadas que siguen a una viñeta son su continuacion; el resto
    se junta en texto corrido y se parte por frases.
    """
    unidades: list[str] = []
    parrafo: list[str] = []
    en_vineta = False

    def cerrar_parrafo() -> None:
        if parrafo:
            texto = " ".join(x.strip() for x in parrafo)
            unidades.extend(f.strip() for f in _LIMITE_DE_FRASE.split(texto) if f.strip())
            parrafo.clear()

    for linea in lineas:
        if not linea.strip():
            continue
        if linea.lstrip().startswith(_VINETAS):
            cerrar_parrafo()
            unidades.append(linea.strip())
            en_vineta = True
        elif en_vineta and linea[:1].isspace():
            unidades[-1] += " " + linea.strip()
        else:
            en_vineta = False
            parrafo.append(linea)
    cerrar_parrafo()
    return unidades


# Palabras que no pueden cerrar una frase: si la ultima palabra es una de ellas, la linea esta cortada.
_PALABRAS_DE_CORTE = frozenset(
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
FACTOR_DE_LARGO_MAX = 1.5  # la viñeta media de la trampa no pasa de 1,5 veces la de su pareja


def _texto_de_linea(linea: str) -> str:
    texto = linea.strip()
    return texto[2:].strip() if texto.startswith(_VINETAS) else texto


def usa_puntuacion_final(mensaje: str) -> bool:
    """Si la mayoria de las lineas de cuerpo (la mitad o mas) acaban en signo final. Sin cuerpo, no."""
    _asunto, cuerpo, _sep = partir_mensaje(mensaje)
    con_signo = sum(bool(_FIN_DE_FRASE.search(_texto_de_linea(x))) for x in cuerpo)
    return bool(cuerpo) and con_signo * 2 >= len(cuerpo)


def largo_medio_de_vineta(mensaje: str) -> float:
    """Caracteres medios por linea de cuerpo, sin la marca de viñeta. 0 si no hay cuerpo."""
    _asunto, cuerpo, _sep = partir_mensaje(mensaje)
    return sum(len(_texto_de_linea(x)) for x in cuerpo) / len(cuerpo) if cuerpo else 0.0


def defectos_de_cuerpo(mensaje: str, pareja: str | None = None) -> list[str]:
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
      tambien; si no, tampoco) y la viñeta media de la trampa no pasa de `FACTOR_DE_LARGO_MAX` veces la
      de la pareja.

    Solo se aplica a las trampas; los mensajes de los modelos no se tocan.
    """
    _asunto, cuerpo, _sep = partir_mensaje(mensaje)
    con_signo = True if pareja is None else usa_puntuacion_final(pareja)
    defectos = []
    for linea in cuerpo:
        texto = _texto_de_linea(linea)
        if texto[:1].islower():
            defectos.append(f"empieza en minuscula: {linea.strip()!r}")
        if _FIN_DE_FRASE.search(texto):
            continue
        palabras = re.findall(r"\w+", texto)
        if (
            con_signo
            or texto.endswith((",", ";", ":", "-"))
            or (palabras and palabras[-1].lower() in _PALABRAS_DE_CORTE)
        ):
            defectos.append(f"termina cortada: {linea.strip()!r}")
    if pareja is not None and cuerpo:
        if usa_puntuacion_final(mensaje) != con_signo:
            defectos.append(
                "la puntuacion final no es la de la pareja "
                f"(la pareja {'cierra' if con_signo else 'no cierra'} con signo final)"
            )
        largo, largo_pareja = largo_medio_de_vineta(mensaje), largo_medio_de_vineta(pareja)
        if largo_pareja and largo > FACTOR_DE_LARGO_MAX * largo_pareja:
            defectos.append(
                f"viñeta media de {largo:.0f} caracteres, mas de {FACTOR_DE_LARGO_MAX} veces "
                f"los {largo_pareja:.0f} de la pareja"
            )
    return defectos


def trampa_con_forma(trampa: dict[str, Any], mensaje_pareja: str) -> str:
    """El mensaje de la trampa con la forma del mensaje con el que se empareja.

    Regla de forma, escrita antes de la tanda: si el mensaje del modelo tiene cuerpo, la trampa lleva
    el asunto mas tantas unidades de su cuerpo como lineas de cuerpo tenga ese mensaje (como mucho 5);
    si no lo tiene, solo el asunto. Una unidad es una viñeta entera o una frase entera (nunca una linea
    fisica del cuerpo) y, al recortar, se quitan unidades enteras. Si la trampa no tiene tantas
    unidades, lleva las que tiene.

    Ademas copia la puntuacion final de la pareja (si la mayoria de sus lineas no cierran con punto,
    la trampa tampoco) y, si sus n primeras unidades pasan de `FACTOR_DE_LARGO_MAX` veces la viñeta
    media de la pareja, lleva las n unidades MAS CORTAS, en su orden. Nunca acorta una frase.
    """
    _asunto, cuerpo_modelo, separado = partir_mensaje(mensaje_pareja)
    n = min(len(cuerpo_modelo), LINEAS_DE_CUERPO_MAX)
    if n == 0:
        return str(trampa["asunto"])
    unidades = unidades_de_cuerpo([str(x) for x in trampa["cuerpo"]])
    lineas = unidades[:n]
    largo_pareja = largo_medio_de_vineta(mensaje_pareja)

    def largo(unidades_: list[str]) -> float:
        return sum(len(_texto_de_linea(x)) for x in unidades_) / len(unidades_)

    if len(unidades) > n and largo(lineas) > FACTOR_DE_LARGO_MAX * largo_pareja:
        elegidas = sorted(sorted(range(len(unidades)), key=lambda i: (len(unidades[i]), i))[:n])
        lineas = [unidades[i] for i in elegidas]
    if not usa_puntuacion_final(mensaje_pareja):
        lineas = [
            x[:-1].rstrip() if x.endswith(".") and not x.endswith("..") else x for x in lineas
        ]
    con_vinetas = sum(x.lstrip().startswith(_VINETAS) for x in cuerpo_modelo) * 2 >= len(
        cuerpo_modelo
    )
    if con_vinetas:
        lineas = [x if x.startswith(_VINETAS) else f"- {x}" for x in lineas]
    return "\n".join([str(trampa["asunto"]), *([""] if separado else []), *lineas])


def resumen_del_diff(diff: str) -> tuple[int, int, int]:
    """`(ficheros, lineas anadidas, lineas quitadas)` de un diff unificado."""
    ficheros = mas = menos = 0
    for linea in diff.replace("\r\n", "\n").split("\n"):
        if linea.startswith("diff --git "):
            ficheros += 1
        elif linea.startswith("+") and not linea.startswith("+++"):
            mas += 1
        elif linea.startswith("-") and not linea.startswith("---"):
            menos += 1
    return ficheros, mas, menos


# --- Construir la hoja ------------------------------------------------------------------------------


def _mensaje_de(registros: list[dict[str, Any]], label: str, caso: str) -> str | None:
    """La respuesta del ULTIMO intento de la corrida 1, si termino bien."""
    ultimo = None
    for r in registros:
        if r.get("label") == label and r.get("case") == caso and int(r.get("run", 1)) == 1:
            ultimo = r
    if ultimo is None or ultimo.get("descartada") or ultimo.get("outcome") != "ok":
        return None
    texto = ultimo.get("response")
    if not isinstance(texto, str) or not texto.strip():
        return None
    return texto


def _reparto_equilibrado(azar: random.Random, n: int, a: str, b: str) -> list[str]:
    """`n` etiquetas barajadas, la mitad `a` y la mitad `b`; si `n` es impar, quien se lleva la
    sobrante lo sortea `azar`. Asi la diferencia entre las dos es 0 o 1, nunca la del azar."""
    de_a = n // 2 + (azar.randint(0, 1) if n % 2 else 0)
    etiquetas = [a] * de_a + [b] * (n - de_a)
    azar.shuffle(etiquetas)
    return etiquetas


def id_de_hoja(numero: int, pares: list[dict[str, Any]]) -> str:
    contenido = json.dumps({"n": numero, "pares": pares}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


def construir_hoja_commit(
    *,
    casos: dict[str, dict[str, Any]],
    fuentes: Path,
    registros: list[dict[str, Any]],
    trampas: dict[str, Any],
    reglas: dict[str, Any],
    juego: int,
    numero: int,
    semilla: int,
    label_26b: str = MODELO_26B,
    label_qwen: str = MODELO_QWEN,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """`(hoja, clave)`: 30 pares reales y 3 trampa, barajados, numerados DESPUES de barajar.

    La hoja lleva los diffs y los mensajes tal como los devolvio la tool y nada mas: ni ids de
    modelo, ni etiquetas, ni latencias. La clave dice quien es cada lado y cual es la trampa.
    """
    azar = random.Random(semilla)
    juegos = trampas["juegos"]
    if not 1 <= juego <= len(juegos):
        raise SystemExit(f"trampas.json no tiene el juego {juego}")

    def diff_de(caso_id: str) -> str:
        nombre = casos[caso_id]["source_file"]
        return (
            (fuentes / nombre).read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        )

    reales: list[tuple[str, str, str]] = []
    omitidos: list[str] = []
    for caso_id, caso in casos.items():
        if caso.get("rol_en_hoja") != "real":
            continue
        a = _mensaje_de(registros, label_26b, caso_id)
        b = _mensaje_de(registros, label_qwen, caso_id)
        if a is None or b is None:
            omitidos.append(caso_id)
            continue
        reales.append((caso_id, a, b))
    # El lado NO se sortea par a par: con 30 pares, un sorteo independiente deja a un modelo en A en 23
    # (p = 0,005) y, como uno escribe cuerpo largo y el otro corto, la hoja queda casi siempre como
    # «A largo, B corto». Una permutacion equilibrada: la mitad exacta (o con diferencia 1) por lado.
    en_a = _reparto_equilibrado(azar, len(reales), label_26b, label_qwen)
    pendientes: list[dict[str, Any]] = []
    for (caso_id, a, b), primero in zip(reales, en_a, strict=True):
        lados = [(label_26b, a), (label_qwen, b)]
        if primero != label_26b:
            lados.reverse()
        pendientes.append(
            {"tipo": "real", "caso": caso_id, "lados": lados, "diff": diff_de(caso_id)}
        )
    entradas = juegos[juego - 1]["trampas"]
    # De las trampas tambien se equilibra el lado de la trampa y el modelo con el que se empareja.
    trampa_en_a = _reparto_equilibrado(azar, len(entradas), "A", "B")
    parejas = _reparto_equilibrado(azar, len(entradas), label_26b, label_qwen)
    for entrada, lado_trampa, modelo in zip(entradas, trampa_en_a, parejas, strict=True):
        caso_id = entrada["caso"]
        mensaje = _mensaje_de(registros, modelo, caso_id)
        if mensaje is None:
            raise SystemExit(f"la trampa de {caso_id} no tiene mensaje del modelo elegido")
        texto_trampa = trampa_con_forma(entrada, mensaje)
        defectos = defectos_de_cuerpo(texto_trampa, mensaje)
        if defectos:
            raise SystemExit(
                f"la trampa de {caso_id} se reconoce por mal escrita: {'; '.join(defectos)}"
            )
        lados = [(TRAMPA, texto_trampa), (modelo, mensaje)]
        if lado_trampa == "B":
            lados.reverse()
        pendientes.append(
            {
                "tipo": TRAMPA,
                "caso": caso_id,
                "trampa_tipo": entrada["tipo"],
                "lados": lados,
                "diff": diff_de(caso_id),
            }
        )
    azar.shuffle(pendientes)

    pares: list[dict[str, Any]] = []
    clave_pares: dict[str, Any] = {}
    for posicion, p in enumerate(pendientes, 1):
        num = f"{posicion:02d}"
        ficheros, mas, menos = resumen_del_diff(p["diff"])
        pares.append(
            {
                "num": num,
                "ficheros": ficheros,
                "mas": mas,
                "menos": menos,
                "diff": p["diff"],
                "A": p["lados"][0][1],
                "B": p["lados"][1][1],
            }
        )
        clave_pares[num] = {
            "tipo": p["tipo"],
            "caso": p["caso"],
            "lados": {"A": p["lados"][0][0], "B": p["lados"][1][0]},
            **({"trampa_tipo": p["trampa_tipo"]} if p["tipo"] == TRAMPA else {}),
        }
    vistos: set[str] = set()
    for par in pares:
        for texto in (par["diff"], par["A"], par["B"]):
            if texto in vistos:
                raise SystemExit(
                    f"par {par['num']}: un diff o un mensaje aparece dos veces en la hoja"
                )
            vistos.add(texto)
    hoja = {
        "id": id_de_hoja(numero, pares),
        "n": numero,
        "opcionales": list(reglas["preguntas_opcionales"]),
        "pares": pares,
    }
    clave = {
        "schema_version": 1,
        "hoja": numero,
        "juego": juego,
        "sha256": hoja["id"],
        "semilla": semilla,
        "label_26b": label_26b,
        "label_qwen": label_qwen,
        "pares": clave_pares,
        "omitidos": omitidos,
    }
    return hoja, clave


# --- Renderizado ------------------------------------------------------------------------------------

_INSTRUCCIONES = [
    (
        "Inventa (si/no)",
        "¿El mensaje dice algo que el diff no hace? Lo que el mensaje se deja fuera no se marca aquí, sino en «lo principal».",
    ),
    ("Lo principal (si/parcial/no)", "¿Nombra el cambio más importante del diff?"),
    ("Específico (si/no)", "¿Se entiende sin abrir el diff?"),
    ("Preferencia", "A, B o empate, después de marcar los dos mensajes."),
]


def tiempo_estimado(reglas: dict[str, Any]) -> str:
    opcionales = set(reglas["preguntas_opcionales"])
    if {"principal", "especifico"} <= opcionales:
        return "unos 45–60 minutos (solo «inventa» y la preferencia son obligatorias)"
    return "entre 60 y 90 minutos"


def _valla_para(texto: str) -> str:
    rachas = [len(m) for m in re.findall(r"`+", texto)]
    return "`" * max(3, max(rachas, default=0) + 1)


def renderizar_md(hoja: dict[str, Any], reglas: dict[str, Any]) -> str:
    opcionales = set(reglas["preguntas_opcionales"])
    lineas = [
        f"# Hoja {hoja['n']}: mensajes de commit, a ciegas",
        "",
        f"Hoja: {hoja['id']}",
        "",
        f"En cada par hay dos mensajes de commit para el mismo cambio. Tiempo estimado: {tiempo_estimado(reglas)}.",
        "Puedes hacerlo en varias sentadas. Escribe la respuesta detrás de los dos puntos de cada línea.",
        "",
    ]
    for nombre, texto in _INSTRUCCIONES:
        lineas.append(f"- **{nombre}**: {texto}")
    lineas.append("")
    for par in hoja["pares"]:
        lineas += [f"## Par {par['num']}", ""]
        lineas.append(f"Diff: {par['ficheros']} ficheros, +{par['mas']} −{par['menos']}")
        lineas.append("")
        valla = _valla_para(par["diff"])
        lineas += [valla + "diff", par["diff"].rstrip("\n"), valla, ""]
        for lado in "AB":
            texto = par[lado]
            valla = _valla_para(texto)
            lineas += [f"### Mensaje {lado}", "", valla, texto.strip("\n"), valla, ""]
        for lado in "AB":
            lineas.append(f"Inventa {lado} (s/n): ")
        for lado in "AB":
            marca = " [opcional]" if "principal" in opcionales else ""
            lineas.append(f"Lo principal {lado} (s/p/n):{marca} ")
        for lado in "AB":
            marca = " [opcional]" if "especifico" in opcionales else ""
            lineas.append(f"Específico {lado} (s/n):{marca} ")
        lineas += ["Mejor (A/B/=): ", ""]
    return "\n".join(lineas)


_PLANTILLA_HTML = r"""<!DOCTYPE html>
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


def renderizar_html(hoja: dict[str, Any], reglas: dict[str, Any]) -> str:
    datos = json.dumps(hoja, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    instrucciones = "".join(
        f"<dt>{html.escape(nombre)}</dt><dd>{html.escape(texto)}</dd>"
        for nombre, texto in _INSTRUCCIONES
    )
    return (
        _PLANTILLA_HTML.replace("__N__", str(hoja["n"]))
        .replace("__TIEMPO__", html.escape(tiempo_estimado(reglas)))
        .replace("__INSTRUCCIONES__", instrucciones)
        .replace("__DATOS__", datos)
    )


def escribir_hoja(
    hoja: dict[str, Any],
    clave: dict[str, Any],
    reglas: dict[str, Any],
    dir_hoja: Path,
    dir_clave: Path,
) -> dict[str, Path]:
    """Escribe `hoja-<n>.html`, `hoja-<n>.md` y `clave-<n>.json`; la clave en OTRA carpeta."""
    if dir_hoja.resolve() == dir_clave.resolve():
        raise SystemExit("la clave no puede ir en la carpeta de la hoja")
    n = hoja["n"]
    rutas = {
        "html": dir_hoja / f"hoja-{n}.html",
        "md": dir_hoja / f"hoja-{n}.md",
        "clave": dir_clave / f"clave-{n}.json",
    }
    existentes = [str(r) for r in rutas.values() if r.exists()]
    if existentes:
        # Regenerar sortea otra vez: una hoja ya contestada quedaria emparejada con otra clave.
        raise SystemExit(f"ya existen {', '.join(existentes)}; elige otro numero de hoja")
    dir_hoja.mkdir(parents=True, exist_ok=True)
    dir_clave.mkdir(parents=True, exist_ok=True)
    rutas["html"].write_text(renderizar_html(hoja, reglas), encoding="utf-8", newline="\n")
    rutas["md"].write_text(renderizar_md(hoja, reglas), encoding="utf-8", newline="\n")
    rutas["clave"].write_text(
        json.dumps(clave, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return rutas


# --- Lectura de las respuestas ----------------------------------------------------------------------

_MD_HOJA = re.compile(r"^Hoja:\s*([0-9a-f]{64})\s*$")
_MD_INVENTA = re.compile(r"^Inventa ([AB]) \(s/n\):(?: \[opcional\])?[ \t]*(\S*)[ \t]*$")
_MD_PRINCIPAL = re.compile(r"^Lo principal ([AB]) \(s/p/n\):(?: \[opcional\])?[ \t]*(\S*)[ \t]*$")
_MD_ESPECIFICO = re.compile(r"^Espec[ií]fico ([AB]) \(s/n\):(?: \[opcional\])?[ \t]*(\S*)[ \t]*$")
_MD_MEJOR = re.compile(r"^Mejor \(A/B/=\):[ \t]*(\S*)[ \t]*$")


def respuestas_de_md(hoja_md: str) -> dict[str, Any]:
    """Las respuestas escritas a mano en la hoja `.md`, como el JSON de la pagina.

    Se salta lo que va dentro de una valla: el mensaje lo escribio un modelo, y una linea
    «Mejor (A/B/=): A» dentro de el no puede votar por nadie.
    """
    sha: str | None = None
    respuestas: dict[str, Any] = {}
    par: str | None = None
    valla: str | None = None
    for linea in hoja_md.splitlines():
        if valla is not None:
            if linea == valla:
                valla = None
            continue
        if re.fullmatch(r"`{3,}(?:diff)?", linea) or linea.startswith("```"):
            valla = re.match(r"`+", linea).group(0)  # type: ignore[union-attr]
            continue
        if m := _MD_HOJA.match(linea):
            sha = m.group(1)
        elif m := re.match(r"^## Par (\d+)\s*$", linea):
            par = m.group(1)
        elif par is not None:
            actual = respuestas.setdefault(par, {})
            if m := _MD_INVENTA.match(linea):
                actual.setdefault("inventa", {})[m.group(1)] = m.group(2)
            elif m := _MD_PRINCIPAL.match(linea):
                actual.setdefault("principal", {})[m.group(1)] = m.group(2)
            elif m := _MD_ESPECIFICO.match(linea):
                actual.setdefault("especifico", {})[m.group(1)] = m.group(2)
            elif m := _MD_MEJOR.match(linea):
                actual["preferencia"] = m.group(1)
    return {"sha256": sha, "respuestas": respuestas}


def _normal(valor: Any, pregunta: str, par: str) -> str | None:
    """El valor ya validado, o `None` si esta vacio."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if pregunta == "preferencia":
        texto = texto.upper() if texto.lower() not in ("empate", "=") else "="
        texto = {"EMPATE": "="}.get(texto, texto)
    else:
        texto = _RESPUESTA_SINONIMOS.get(texto.lower(), texto.lower())
    if texto == "":
        return None
    if texto not in _VALORES[pregunta]:
        raise SystemExit(
            f"par {par}: el valor {valor!r} no es valido para {pregunta} "
            f"(admite {', '.join(_VALORES[pregunta])})"
        )
    return texto


def leer_commit(
    respuestas: dict[str, Any],
    clave: dict[str, Any],
    reglas: dict[str, Any],
    *,
    parcial: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """`(juicio, faltan)`: las respuestas ya validadas y destapadas con la clave.

    Valida que son de ESA hoja (`sha256`) y que los valores son validos. Con la hoja entera, `faltan`
    lista lo obligatorio segun `reglas.json` que no esta contestado; con `parcial`, solo se valida lo
    que hay y `faltan` va vacio (la parada solo necesita lo contestado).
    """
    if respuestas.get("sha256") != clave["sha256"]:
        raise SystemExit(
            "las respuestas no son de esta hoja: el sha256 no coincide con el de la clave"
        )
    pares_clave = clave["pares"]
    desconocidos = sorted(set(respuestas.get("respuestas", {})) - set(pares_clave))
    if desconocidos:
        raise SystemExit(
            f"las respuestas traen pares que la hoja no tiene: {', '.join(desconocidos)}"
        )
    opcionales = set(reglas["preguntas_opcionales"])
    juicio_pares: dict[str, Any] = {}
    faltan: list[str] = []
    for num, meta in sorted(pares_clave.items()):
        dadas = respuestas.get("respuestas", {}).get(num, {})
        par: dict[str, Any] = {"tipo": meta["tipo"], "caso": meta["caso"], "lados": meta["lados"]}
        for pregunta in ("inventa", "principal", "especifico"):
            por_lado = {
                lado: _normal((dadas.get(pregunta) or {}).get(lado), pregunta, num) for lado in "AB"
            }
            par[pregunta] = por_lado
            if pregunta not in opcionales and not parcial:
                faltan += [
                    f"par {num}: {pregunta} {lado}" for lado in "AB" if por_lado[lado] is None
                ]
        par["preferencia"] = _normal(dadas.get("preferencia"), "preferencia", num)
        if par["preferencia"] is None and not parcial:
            faltan.append(f"par {num}: preferencia")
        juicio_pares[num] = par
    juicio = {
        "schema_version": 1,
        "hoja": clave["sha256"],
        "juego": clave.get("juego"),
        "parcial": parcial,
        "label_26b": clave["label_26b"],
        "label_qwen": clave["label_qwen"],
        "pares": juicio_pares,
    }
    return juicio, faltan


def _ganador(par: dict[str, Any]) -> str:
    eleccion = par["preferencia"]
    return "empate" if eleccion == "=" else str(par["lados"][eleccion])


def puedes_parar(juicio: dict[str, Any], reglas: dict[str, Any]) -> str:
    """«puedes parar» o «sigue», y nada mas: ni hacia donde va el resultado ni quien va ganando.

    Solo contesta «puedes parar» si las 3 trampas estan contestadas y la hoja vale (criterio 0) Y el
    desenlace ya no puede cambiar con los pares que faltan: el 26B ya pasa de `max_inventa_26b`, o
    `v - c` es mayor que los pares reales sin contestar.
    """
    if not reglas["parada_anticipada"]:
        return "sigue"
    pares = juicio["pares"].values()
    trampas = [p for p in pares if p["tipo"] == TRAMPA]
    if len(trampas) < 3 or any(p["preferencia"] is None for p in trampas):
        return "sigue"
    if sum(_ganador(p) not in ("empate", TRAMPA) for p in trampas) < 2:
        return "sigue"
    reales = [p for p in pares if p["tipo"] == "real"]
    modelo = juicio["label_26b"]
    inventa = 0
    for p in reales:
        lado = "A" if p["lados"]["A"] == modelo else "B"
        inventa += p["inventa"][lado] == "s"
    if inventa > int(reglas["max_inventa_26b"]):
        return "puedes parar"
    contestados = [p for p in reales if p["preferencia"] is not None]
    c = sum(_ganador(p) == modelo for p in contestados)
    v = sum(_ganador(p) == juicio["label_qwen"] for p in contestados)
    sin_contestar = len(reales) - len(contestados)
    return "puedes parar" if v - c > sin_contestar else "sigue"


def _cargar_respuestas(args: argparse.Namespace) -> dict[str, Any]:
    if args.md is not None:
        return respuestas_de_md(args.md.read_text(encoding="utf-8"))
    return json.loads(args.respuestas.read_text(encoding="utf-8"))


def ejecutar_generar_commit(args: argparse.Namespace) -> int:
    datos = json.loads(args.cases.read_text(encoding="utf-8"))
    casos = {c["id"]: c for c in datos["cases"]}
    reglas = leer_reglas(args.reglas)
    trampas = json.loads(args.trampas.read_text(encoding="utf-8"))
    semilla = args.semilla if args.semilla is not None else secrets.randbits(32)
    hoja, clave = construir_hoja_commit(
        casos=casos,
        fuentes=args.cases.parent / "fuentes",
        registros=_registros(args.jsonl),
        trampas=trampas,
        reglas=reglas,
        juego=args.juego,
        numero=args.numero,
        semilla=semilla,
        label_26b=args.label_26b,
        label_qwen=args.label_qwen,
    )
    rutas = escribir_hoja(hoja, clave, reglas, args.hoja_dir, args.clave_dir)
    print(
        f"{len(hoja['pares'])} pares en {rutas['html']}; la clave ({rutas['clave'].parent}) no se abre"
    )
    if clave["omitidos"]:
        print(f"omitidos por falta de mensaje: {', '.join(clave['omitidos'])}", file=sys.stderr)
    return 0


def ejecutar_leer_commit(args: argparse.Namespace) -> int:
    reglas = leer_reglas(args.reglas)
    clave = json.loads(args.clave.read_text(encoding="utf-8"))
    juicio, faltan = leer_commit(_cargar_respuestas(args), clave, reglas, parcial=args.parcial)
    if args.parcial:
        print(puedes_parar(juicio, reglas))
        return 0
    if faltan:
        print("Falta por contestar, y no se produce nada hasta completarlo:", file=sys.stderr)
        for linea in faltan:
            print(f"  - {linea}", file=sys.stderr)
        return 1
    if args.salida:
        args.salida.write_text(
            json.dumps(juicio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
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
    gc = sub.add_parser("generar-commit", help="hoja a ciegas de local_commit_msg (REQ-042)")
    gc.add_argument("--cases", type=Path, default=BASE_AFINIDAD / "cases.json")
    gc.add_argument("--trampas", type=Path, default=BASE_AFINIDAD / "trampas.json")
    gc.add_argument("--reglas", type=Path, default=BASE_AFINIDAD / "reglas.json")
    gc.add_argument("--juego", type=int, default=1, help="juego de trampas (1 a 3)")
    gc.add_argument("--numero", type=int, default=1, help="numero de hoja")
    gc.add_argument("--semilla", type=int, default=None, help="solo para pruebas")
    gc.add_argument("--label-26b", default=MODELO_26B)
    gc.add_argument("--label-qwen", default=MODELO_QWEN)
    gc.add_argument("--hoja-dir", type=Path, default=BASE_AFINIDAD / "hoja")
    gc.add_argument("--clave-dir", type=Path, default=BASE_AFINIDAD / "clave")
    gc.add_argument(
        "jsonl", nargs="+", type=Path, help="resultados de la tanda con --save-responses"
    )
    lc = sub.add_parser("leer-commit", help="valida las respuestas de la hoja de commit")
    lc.add_argument("--clave", type=Path, required=True)
    lc.add_argument("--reglas", type=Path, default=BASE_AFINIDAD / "reglas.json")
    origen = lc.add_mutually_exclusive_group(required=True)
    origen.add_argument("--respuestas", type=Path, help="respuestas-<n>.json de la pagina")
    origen.add_argument("--md", type=Path, help="la hoja .md contestada a mano")
    lc.add_argument("--parcial", action="store_true", help="solo contesta «puedes parar» o «sigue»")
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
    if args.modo == "generar-commit":
        return ejecutar_generar_commit(args)
    if args.modo == "leer-commit":
        return ejecutar_leer_commit(args)
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
