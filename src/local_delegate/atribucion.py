"""Quién pidió cada delegación: modelo, hilo y esfuerzo de quien llama (coste-api-y-cuota).

Tres preguntas, y las reglas que varios consumidores necesitan, en un solo sitio:

- **Al momento** (REQ-002, REQ-003): el hook `anotar_llamada.py` deja una nota por `tool_use_id`
  con `agent_id`, `agent_type`, `effort` y `transcript_path`; `resolver_llamada` la lee y busca el
  modelo en la cola del transcript que señala la nota. `llamada_actual` lo hace una vez por
  petición y lo memoriza en el dict que el middleware pone en `clients`.
- **El relleno a posteriori** (REQ-005): la clave de cada línea del log (`claves_del_fichero`) y
  los `atribucion-AAAAMM.json` (`leer_relleno`, `escribir_relleno`), donde una entrada solo se
  sustituye por otra de cruce mejor.
- **Lo que no cuenta** (REQ-007) y **cuánto viven los transcripts** (enmienda 1):
  `excluida` y `plazo_de_borrado`.

Solo stdlib. La nota la escribe un hook que no puede importar este módulo, así que su formato vive
en dos sitios y lo ata un test de ida y vuelta (`tests/test_atribucion.py`).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from . import clients, precios
from .resources.hooks import hook_common

#: Una nota de más de diez minutos ya no cuenta (REQ-003).
VIGENCIA_DE_NOTA_S = hook_common.VIGENCIA_DE_NOTA_S

#: Cuánto del final del transcript se lee como mucho, y en cuánto tiempo (REQ-003).
COLA_BYTES = 256 * 1024
PRESUPUESTO_S = 0.050

#: Clientes cuyas delegaciones no se valoran, con el rótulo del tramo `excluido` (REQ-007).
CLIENTES_EXCLUIDOS = {"codex-mcp-client": "no es Claude", "mcp": "pruebas"}

#: Orden de los cruces del relleno: una entrada solo se sustituye por otra de rango MAYOR (REQ-005).
RANGO_DE_CRUCE = {"exacto": 2, "ventana": 1, "ventana+path": 1, "ambiguo": 0, "sin_cruce": 0}

#: `cleanupPeriodDays` por defecto de Claude Code (enmienda 1).
PLAZO_POR_DEFECTO = 30

_VERSION_RELLENO = 1


# --- Al momento ---------------------------------------------------------------------------------


def _valido(tool_use_id: object) -> bool:
    return isinstance(tool_use_id, str) and bool(hook_common.PATRON_TOOL_USE_ID.match(tool_use_id))


def leer_nota(tool_use_id: str, *, directorio: Path | None = None) -> dict | None:
    """La nota que dejó el hook para ese `tool_use_id`, o `None`. Nunca lanza.

    Una nota ilegible, a medias o de otro id cuenta como «sin nota».
    """
    try:
        if not _valido(tool_use_id):
            return None
        base = directorio or hook_common.directorio_de_notas_de_llamadas()
        nota = json.loads((base / f"{tool_use_id}.json").read_text(encoding="utf-8"))
        if not isinstance(nota, dict) or nota.get("tool_use_id") != tool_use_id:
            return None
        return nota
    except (OSError, ValueError, TypeError):
        return None


def _raiz_de_proyectos() -> Path:
    return Path.home() / ".claude" / "projects"


def _ruta_segura(ruta: Path, raiz: Path) -> Path | None:
    """La ruta resuelta si cuelga de `raiz` y acaba en `.jsonl`; si no, `None`.

    La nota vive en un temporal que cualquier proceso local puede escribir: sin esta comprobación,
    el daemon abriría el fichero que le dijeran.
    """
    try:
        resuelta = ruta.resolve()
        if resuelta.suffix != ".jsonl" or not resuelta.is_relative_to(raiz.resolve()):
            return None
        return resuelta
    except (OSError, ValueError, RuntimeError):
        return None


def _transcript_de(nota: dict, raiz: Path) -> Path | None:
    """El transcript donde está el `tool_use`: el del subagente si la nota trae `agent_id`.

    La nota de un subagente trae el `transcript_path` del PRINCIPAL (medido); el suyo es
    `<sesión>/subagents/agent-<agent_id>.jsonl`.
    """
    camino = nota.get("transcript_path")
    if not isinstance(camino, str) or not camino:
        return None
    principal = _ruta_segura(Path(camino), raiz)
    if principal is None:
        return None
    agente = nota.get("agent_id")
    if not agente:
        return principal
    if not isinstance(agente, str):
        return None
    return _ruta_segura(principal.with_suffix("") / "subagents" / f"agent-{agente}.jsonl", raiz)


def _modelo_de_la_linea(linea: bytes, tool_use_id: str) -> str | None:
    """`message.model` si la línea es la del `tool_use` con ese id; si no, `None`."""
    try:
        datos = json.loads(linea)
        mensaje = datos.get("message") if isinstance(datos, dict) else None
        if not isinstance(mensaje, dict):
            return None
        contenido = mensaje.get("content")
        if not isinstance(contenido, list):
            return None
        for bloque in contenido:
            if (
                isinstance(bloque, dict)
                and bloque.get("type") == "tool_use"
                and bloque.get("id") == tool_use_id
            ):
                modelo = mensaje.get("model")
                return modelo if isinstance(modelo, str) and modelo else None
    except (ValueError, TypeError):
        return None
    return None


def _buscar_modelo(
    ruta: Path, tool_use_id: str, *, reloj: Callable[[], float], abrir: Callable[..., Any]
) -> str | None:
    """Busca la línea del `tool_use` de atrás adelante en la cola del transcript.

    Lee como mucho `COLA_BYTES` y corta al pasar `PRESUPUESTO_S` medido con `reloj`. Lo que no
    encuentra lo cierra el relleno a posteriori.
    """
    inicio = reloj()
    aguja = tool_use_id.encode("ascii")
    try:
        with abrir(ruta, "rb") as flujo:
            flujo.seek(0, os.SEEK_END)
            tamano = flujo.tell()
            desde = max(0, tamano - COLA_BYTES)
            flujo.seek(desde)
            cola = flujo.read(tamano - desde)
    except (OSError, ValueError):
        return None
    lineas = cola.split(b"\n")
    if desde > 0:
        lineas = lineas[1:]  # la primera está cortada por la mitad
    for linea in reversed(lineas):
        if reloj() - inicio > PRESUPUESTO_S:
            return None
        if aguja not in linea:
            continue
        modelo = _modelo_de_la_linea(linea, tool_use_id)
        if modelo:
            return modelo
    return None


def _admite_esfuerzo(modelo: str) -> bool:
    try:
        entrada = precios.entrada(modelo)
    except Exception:
        return True
    return True if entrada is None else bool(entrada.get("admite_esfuerzo", True))


def resolver_llamada(
    tool_use_id: str | None,
    *,
    notas: Path | None = None,
    ahora: float | None = None,
    reloj: Callable[[], float] = time.monotonic,
    abrir: Callable[..., Any] = open,
    proyectos: Path | None = None,
) -> dict:
    """Los campos `caller_*` de una llamada (REQ-003); `{}` si no hay nota vigente.

    `notas` es el directorio de notas (por defecto, el del hook) y `proyectos` la raíz de la que
    tiene que colgar el transcript (por defecto, `~/.claude/projects`). Nunca devuelve el id de
    sesión ni nada más del transcript que el modelo.
    """
    if not tool_use_id or not _valido(tool_use_id):
        return {}
    nota = leer_nota(tool_use_id, directorio=notas)
    if nota is None:
        return {}
    momento = time.time() if ahora is None else ahora
    try:
        if momento - float(nota["ts"]) > VIGENCIA_DE_NOTA_S:
            return {}
    except (KeyError, TypeError, ValueError):
        return {}

    agente = nota.get("agent_id")
    r: dict = {"caller_kind": "subagent" if agente else "main", "caller_src": "hook"}
    tipo = nota.get("agent_type")
    if agente and isinstance(tipo, str) and tipo:
        r["caller_agent_type"] = tipo
    esfuerzo = nota.get("effort")
    if isinstance(esfuerzo, str) and esfuerzo:
        r["caller_effort"] = esfuerzo

    ruta = _transcript_de(nota, proyectos or _raiz_de_proyectos())
    modelo = (
        _buscar_modelo(ruta, tool_use_id, reloj=reloj, abrir=abrir) if ruta is not None else None
    )
    if modelo:
        r["caller_model"] = precios.normalizar_id(modelo)
        r["caller_src"] = "hook+transcript"
        if "caller_effort" not in r and not _admite_esfuerzo(r["caller_model"]):
            r["caller_effort"] = "n/a"  # Haiku 4.5: no admite esfuerzo y no es un dato que falte
    return r


def llamada_actual() -> dict:
    """La atribución de la petición en curso, resuelta UNA vez por petición; `{}` fuera de una.

    Se memoriza en el dict que el middleware pone por petición (`clients.memoria_de_peticion`),
    nunca en el módulo: en el daemon un dict del módulo crecería sin límite.
    """
    tool_use_id = clients.tool_use_id_actual()
    if not tool_use_id:
        return {}
    memoria = clients.memoria_de_peticion()
    if memoria is not None and tool_use_id in memoria:
        return memoria[tool_use_id]
    resultado = resolver_llamada(tool_use_id)
    if memoria is not None:
        memoria[tool_use_id] = resultado
    return resultado


# --- Relleno a posteriori (REQ-005) -------------------------------------------------------------


def claves_del_fichero(filas: Iterable[dict]) -> list[str]:
    """La clave de cada línea del log, en el orden del fichero ENTERO.

    `tool_use_id` si la línea lo trae; si no, `ts|tool|ordinal`, con `ordinal` la posición de la
    línea entre las de su misma `(ts, tool)`. El log solo crece por el final, así que una línea
    nueva no cambia la clave de las anteriores. `(ts, tool)` sola repite: `ts` va en segundos y dos
    subagentes llaman a la vez a la misma tool.
    """
    vistos: dict[tuple[str, str], int] = {}
    claves: list[str] = []
    for fila in filas:
        tool_use_id = fila.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id:
            claves.append(tool_use_id)
            continue
        par = (str(fila.get("ts", "")), str(fila.get("tool", "")))
        ordinal = vistos.get(par, 0)
        vistos[par] = ordinal + 1
        claves.append(f"{par[0]}|{par[1]}|{ordinal}")
    return claves


def ruta_de_relleno(log_dir: Path, mes: str) -> Path:
    """`atribucion-AAAAMM.json` junto al log."""
    return Path(log_dir) / f"atribucion-{mes}.json"


def leer_relleno(log_dir: Path, mes: str) -> dict[str, dict]:
    """Las entradas del relleno de ese mes (`{clave: entrada}`); `{}` si no hay o no se lee."""
    try:
        datos = json.loads(ruta_de_relleno(log_dir, mes).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entradas = datos.get("entradas") if isinstance(datos, dict) else None
    if not isinstance(entradas, dict):
        return {}
    return {k: v for k, v in entradas.items() if isinstance(v, dict)}


def _rango(entrada: dict) -> int:
    return RANGO_DE_CRUCE.get(str(entrada.get("cruce")), -1)


def escribir_relleno(log_dir: Path, mes: str, entradas: dict[str, dict]) -> dict[str, dict]:
    """Funde `entradas` con lo que ya hay y lo escribe de forma atómica. Devuelve el resultado.

    Una entrada existente no se borra nunca, y solo la sustituye otra de cruce MEJOR
    (`exacto` > `ventana` = `ventana+path` > `ambiguo` = `sin_cruce`).
    """
    fundidas = leer_relleno(log_dir, mes)
    for clave, nueva in entradas.items():
        vieja = fundidas.get(clave)
        if vieja is None or _rango(nueva) > _rango(vieja):
            fundidas[clave] = nueva
    destino = ruta_de_relleno(log_dir, mes)
    destino.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(dir=destino.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as flujo:
            json.dump(
                {"version": _VERSION_RELLENO, "entradas": fundidas},
                flujo,
                ensure_ascii=False,
                sort_keys=True,
            )
        os.replace(temporal, destino)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise
    return fundidas


# --- Lo que no cuenta y cuánto viven los transcripts ---------------------------------------------


def excluida(fila: dict, entrada_relleno: dict | None = None) -> str | None:
    """El motivo por el que la delegación no se valora (REQ-007), o `None` si cuenta.

    `no es Claude` (Codex) o `pruebas` (el cliente `mcp` de los scripts, o un transcript de banco
    que el relleno marcó `banco`).
    """
    motivo = CLIENTES_EXCLUIDOS.get(str(fila.get("client") or ""))
    if motivo:
        return motivo
    if isinstance(entrada_relleno, dict) and entrada_relleno.get("banco"):
        return "pruebas"
    return None


def plazo_de_borrado(claude_dir: Path) -> int:
    """`H`: `cleanupPeriodDays` de `claude_dir/settings.json`, o 30 si falta o no es un entero
    positivo (enmienda 1)."""
    try:
        datos = json.loads((Path(claude_dir) / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return PLAZO_POR_DEFECTO
    valor = datos.get("cleanupPeriodDays") if isinstance(datos, dict) else None
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        return PLAZO_POR_DEFECTO
    return valor
