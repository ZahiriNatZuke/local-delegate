"""Densidad de Claude por evento, fusión del relleno y tramo de cobertura (coste-api-y-cuota).

Tres preguntas, un solo sitio de verdad para cada una:

- **¿Cuántos caracteres hacen un token de Claude en esta fila?** `resolver_densidad(evento)`
  (REQ-031 a REQ-033): familia de tokenizador del modelo de quien llamó (o del respaldo), clase de
  contenido (REQ-032), columna (`formato_read` si se leyó por `path`, que es lo que habría devuelto
  `Read`) y respaldo de celda en su único orden. Devuelve `c` en **centésimas** con su origen. Ni
  `server.tokens_claude` ni el JS del panel resuelven nada: solo dividen por lo que trae la fila.
- **¿Qué se sabe de quien llamó?** `fundir(filas, log_dir=...)` (REQ-006): por campo, la línea del
  log manda, luego el relleno (`atribucion-AAAAMM.json`) y por último el respaldo declarado
  (REQ-008). En el mismo paso añade la densidad resuelta. Copia cada fila: nunca muta las de la
  caché del lector.
- **¿En qué tramo de la barra cae?** `tramo(fila, ahora=..., plazo_dias=...)` (REQ-007).

Solo stdlib; no abre sockets ni lee `~/.claude`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import atribucion, config, precios, test_windows

# El respaldo declarado (REQ-008): el grupo más frecuente medido (135 de 149 atribuidas).
RESPALDO_DECLARADO = {"modelo": "claude-opus-5-5", "hilo": "subagent"}
HILOS = ("main", "subagent")

MARCA_FAMILIA_SUPUESTA = "familia supuesta"
MARCA_DENSIDAD_DE_LA_FAMILIA = "densidad de la familia"

# Clase de contenido (REQ-032): primero por la tool, luego por la extensión del `path`. La lista es
# la de `insumos/scripts/atribucion_n.py`, para que el panel y el script den lo mismo (REQ-048).
CLASE_POR_TOOL = {
    "local_lint_summary": "log",
    "local_commit_msg": "diff",
    "local_explain_code": "codigo",
}
_EXTENSIONES = {
    "prosa": ".md .markdown .txt .rst .html .htm",
    "codigo": (
        ".py .js .mjs .cjs .ts .tsx .jsx .ps1 .psm1 .sh .bash .java .go .rs .c .h .cpp .cs .rb"
        " .php .css .scss .sql .kt .swift"
    ),
    "estructurado": ".json .jsonl .yaml .yml .toml .lock .csv .xml .ini",
    "log": ".log",
    "diff": ".diff .patch",
}
CLASE_POR_EXTENSION = {ext: clase for clase, exts in _EXTENSIONES.items() for ext in exts.split()}

# Lo que la tool devuelve a Claude (`returned`) y lo que escribe a fichero (`output`) no va
# numerado: columna `sin_numerar`, y la clase depende solo de la tool (REQ-031).
_CLASE_DEVUELTA = {"local_extract": "estructurado", "local_boilerplate": "codigo"}
_CLASE_DE_SALIDA = {"local_boilerplate": "codigo"}

# Campos que el relleno aporta a la fila (REQ-005), en el orden en que se funden.
CAMPOS_DEL_RELLENO = (
    "caller_model",
    "caller_kind",
    "caller_effort",
    "n",
    "caducidades",
    "cruce",
    "banco",
)

TRAMOS = ("excluido", "al_momento", "por_relleno", "pendiente", "supuesto")
_CRUCES_SIN_REMEDIO = ("ambiguo", "sin_cruce")

_MES = re.compile(r"^(\d{4})-(\d{2})")


def _vacio(valor: object) -> bool:
    return valor is None or valor == ""


def es_imagen(evento: dict) -> bool:
    """La misma regla que `server._accounting`: unidad distinta de `chars` (o el histórico de
    `local_describe_image`, anterior al campo `input_unit`)."""
    unidad = evento.get("input_unit") or (
        "bytes" if evento.get("tool") == "local_describe_image" else "chars"
    )
    return unidad != "chars"


def _extension(path: object) -> str:
    """La extensión en minúsculas, sin depender del separador del sistema donde corre el test."""
    if not isinstance(path, str):
        return ""
    nombre = path.replace("\\", "/").rsplit("/", 1)[-1]
    punto = nombre.rfind(".")
    return nombre[punto:].lower() if punto > 0 else ""


def clase_de_contenido(evento: dict) -> str:
    """`prosa`, `codigo`, `log`, `estructurado`, `diff` u `otro`, sin leer el texto (REQ-032)."""
    por_tool = CLASE_POR_TOOL.get(str(evento.get("tool") or ""))
    if por_tool:
        return por_tool
    return CLASE_POR_EXTENSION.get(_extension(evento.get("path")), "otro")


def respaldo() -> dict:
    """El modelo y el hilo con que se valora una delegación sin modelo (REQ-008).

    `config.COSTE_RESPALDO` (`modelo` o `modelo:main|subagent`; solo `modelo` = `subagent`) manda
    sobre el declarado. Un valor vacío usa el declarado; uno que no se entiende o cuyo modelo no
    está en la tabla de precios, también, pero con `respaldo_invalido: True` para que se diga.
    """
    declarado = dict(RESPALDO_DECLARADO, respaldo_invalido=False)
    valor = str(config.COSTE_RESPALDO or "").strip()
    if valor:
        modelo, sep, hilo = valor.partition(":")
        modelo = precios.normalizar_id(modelo.strip())
        hilo = hilo.strip() if sep else "subagent"
        if modelo and hilo in HILOS and precios.entrada(modelo) is not None:
            declarado = {"modelo": modelo, "hilo": hilo, "respaldo_invalido": False}
        else:
            declarado["respaldo_invalido"] = True
    declarado["familia"] = precios.familia(declarado["modelo"])
    return declarado


def familia_y_marcas(modelo: str) -> tuple[str, list[str]]:
    """La familia de tokenizador del modelo y las marcas de supuesto que lleva (REQ-030/031)."""
    entrada = precios.entrada(modelo) if modelo else None
    if entrada is None:
        return "nueva", [MARCA_FAMILIA_SUPUESTA]
    familia = entrada["familia"]
    medidos = precios.cargar_densidad()["familias"][familia].get("medido_con", [])
    if precios.normalizar_id(modelo) in medidos:
        return familia, []
    return familia, [MARCA_DENSIDAD_DE_LA_FAMILIA]


def _celda(familia: str, clase: str, columna: str) -> list:
    """`[c100, origen]` con el respaldo de celda en su único orden (REQ-031): (1) la celda exacta,
    `medida`; (2) la misma clase en `sin_numerar`, `sin_numerar`; (3) la mayor `c` de la columna
    `sin_numerar` de la familia, `conservadora`. (2) y (3) dan menos tokens, nunca más."""
    tabla = precios.cargar_densidad()["familias"][familia]
    exacta = tabla.get(columna, {})
    if clase in exacta:
        return [int(exacta[clase]), "medida"]
    sin_numerar = tabla["sin_numerar"]
    if clase in sin_numerar:
        return [int(sin_numerar[clase]), "sin_numerar"]
    return [int(max(sin_numerar.values())), "conservadora"]


def resolver(evento: dict) -> dict:
    """`densidad`, `familia` y `marcas` de la fila (REQ-033). El modelo es `caller_model` (ya
    fundido) o, si falta, el del respaldo."""
    modelo = evento.get("caller_model") or respaldo()["modelo"]
    familia, marcas = familia_y_marcas(str(modelo))
    if es_imagen(evento):
        # La imagen sale entera del neto (REQ-038): ningún `tipo` tiene densidad.
        densidad: dict = {"text": None, "returned": None, "output": None}
    else:
        tool = str(evento.get("tool") or "")
        columna = "formato_read" if evento.get("source") == "path" else "sin_numerar"
        densidad = {
            "text": _celda(familia, clase_de_contenido(evento), columna),
            "returned": _celda(familia, _CLASE_DEVUELTA.get(tool, "prosa"), "sin_numerar"),
            "output": _celda(familia, _CLASE_DE_SALIDA.get(tool, "prosa"), "sin_numerar"),
        }
    return {"densidad": densidad, "familia": familia, "marcas": marcas}


def resolver_densidad(evento: dict) -> dict:
    """`{"text": [c100, origen], "returned": [...], "output": [...]}`; `None` en las tres si el
    evento es una imagen. Las reglas de REQ-031 y REQ-032 viven solo aquí."""
    return resolver(evento)["densidad"]


def fundir_fila(fila: dict, entrada: dict | None = None, *, respaldo_: dict | None = None) -> dict:
    """Una COPIA de la fila con el relleno, el respaldo y la densidad (REQ-006).

    Por campo: (1) el valor de la línea; (2) el del relleno; (3) el respaldo (solo modelo e hilo).
    `caller_origen` dice de dónde salió el modelo (`linea`, `relleno` o `respaldo`), que es lo que
    necesita el tramo de la barra.
    """
    nueva = dict(fila)
    entrada = entrada if isinstance(entrada, dict) else {}
    for campo in CAMPOS_DEL_RELLENO:
        if _vacio(nueva.get(campo)) and not _vacio(entrada.get(campo)):
            nueva[campo] = entrada[campo]
    if not _vacio(fila.get("caller_model")):
        origen = "linea"
    elif not _vacio(entrada.get("caller_model")):
        origen = "relleno"
    else:
        origen = "respaldo"
        r = respaldo_ if respaldo_ is not None else respaldo()
        nueva["caller_model"] = r["modelo"]
        if _vacio(nueva.get("caller_kind")):
            nueva["caller_kind"] = r["hilo"]
        if r.get("respaldo_invalido"):
            nueva["respaldo_invalido"] = True
    nueva["caller_origen"] = origen
    nueva.update(resolver(nueva))
    return nueva


def _mes(ts: object) -> str | None:
    m = _MES.match(ts) if isinstance(ts, str) else None
    return f"{m.group(1)}{m.group(2)}" if m else None


def fundir(filas: Iterable[dict], *, log_dir: Path) -> list[dict]:
    """Las filas de UN fichero del log, fundidas y resueltas, en su orden.

    Hay que pasarle el fichero ENTERO, antes de filtrar por rango: la clave de una línea sin
    `tool_use_id` lleva su ordinal dentro del fichero (`atribucion.claves_del_fichero`). El
    relleno de cada línea se busca en `atribucion-AAAAMM.json` del mes de su `ts`.
    """
    filas = list(filas)
    claves = atribucion.claves_del_fichero(filas)
    por_mes: dict[str | None, dict[str, dict]] = {}
    r = respaldo()
    # Ventanas de prueba (test-windows-out-of-metrics, REQ-005): se estampa `test_window` en la
    # COPIA; el fichero de log no cambia. Una sola lectura (cacheada) y un solo reloj por llamada.
    ventanas = test_windows.load(log_dir)
    ahora = datetime.now(UTC)
    fundidas: list[dict] = []
    for fila, clave in zip(filas, claves, strict=True):
        mes = _mes(fila.get("ts"))
        if mes not in por_mes:
            por_mes[mes] = atribucion.leer_relleno(log_dir, mes) if mes else {}
        nueva = fundir_fila(fila, por_mes[mes].get(clave), respaldo_=r)
        if ventanas.windows:
            ventana = ventanas.find(fila.get("ts"), now=ahora)
            if ventana:
                nueva["test_window"] = ventana
        fundidas.append(nueva)
    return fundidas


def fila_en_vuelo(
    *, tool: str, source: str, path: str | None = None, input_unit: str = "chars"
) -> dict:
    """La fila de la llamada en curso, fundida como la del panel, para los mensajes a Claude
    (REQ-035): con `caller_*` si la nota del hook ya está y, si no, con el respaldo."""
    fila: dict = {"tool": tool, "source": source}
    if path:
        fila["path"] = path
    if input_unit != "chars":
        fila["input_unit"] = input_unit
    try:
        fila.update(atribucion.llamada_actual())
    except Exception:
        pass  # observar nunca rompe una tool: sin atribución, respaldo
    return fundir_fila(fila)


def _instante(ts: object) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def tramo(fila: dict, *, ahora: datetime, plazo_dias: int) -> str:
    """El tramo de la barra de cobertura de una fila fundida (REQ-007), en su orden:
    `excluido`, `al_momento`, `por_relleno`, `pendiente` o `supuesto`."""
    if atribucion.excluida(fila, {"banco": fila.get("banco")}):
        return "excluido"
    origen = fila.get("caller_origen")
    if origen is None:
        origen = "linea" if not _vacio(fila.get("caller_model")) else "respaldo"
    if origen == "linea":
        return "al_momento"
    if origen == "relleno":
        return "por_relleno"
    if fila.get("cruce") in _CRUCES_SIN_REMEDIO:
        return "supuesto"
    t = _instante(fila.get("ts"))
    if t is not None and ahora - t < timedelta(days=plazo_dias):
        return "pendiente"
    return "supuesto"
