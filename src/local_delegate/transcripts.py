"""Lectura de los transcripts de Claude Code, SOLO para `local-delegate recalcular-coste`.

El daemon y el panel no importan este módulo (REQ-073): leer `~/.claude/projects` es cosa del
comando que lanza el usuario. Todo lo que sale de aquí son números, fechas, ids de modelo y
niveles de esfuerzo; las rutas (`path` de la tool, fichero del transcript) y los ids de sesión se
usan en memoria y no se devuelven en ninguna estructura que se escriba a disco.

Port de `insumos/scripts/atribucion_n.py` (cruce y `N`), `calibracion.py` (peticiones y rechazos)
y `cotejo.py` (`cost-state`), con las mismas reglas, para que T8 pueda comparar cifra a cifra:

- `leer(raiz)` recorre los `*.jsonl` una sola vez y devuelve un `Indice`.
- `casar(lineas, indice, desde=...)` casa cada línea del log con su `tool_use` (REQ-004).
- `n_y_caducidades(indice, delegacion)` (REQ-043) y `percentil` (interpolación lineal).
- `cost_state(indice)` da las filas «modelo × sesión» para el cotejo (REQ-014).

Una línea JSON rota se salta y se cuenta (REQ-061); un fichero ilegible, también.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import precios

PREFIJO = "mcp__local-delegate__"

#: TTL de la caché de cada hilo (REQ-043): el principal escribe a 1 h, los subagentes a 5 min.
TTL_S = {"main": 3600, "subagent": 300}

#: Ventana del cruce por tiempo (REQ-004).
ANTES = timedelta(seconds=1)
DESPUES = timedelta(seconds=2)
SIN_RESULTADO = timedelta(minutes=15)

#: Las seis columnas de `modelUsage` que entran en el cotejo.
CAMPOS_COTEJO = precios.CAMPOS_COTEJO


def instante(valor: object) -> datetime | None:
    """`datetime` con zona (UTC si no trae) o `None`."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        t = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


@dataclass
class Delegacion:
    """Un `tool_use` de una tool de local-delegate, con lo que el relleno necesita.

    `path` y `hilo` (el fichero) viven solo en memoria: sirven para desempatar y para contar `N`.
    """

    tool: str
    ts_use: datetime | None
    hilo: str
    kind: str
    modelo: str | None
    esfuerzo: str | None
    path: str | None
    banco: bool
    mid: str | None
    ts_res: datetime | None = None


@dataclass
class Hilo:
    kind: str
    peticiones: dict[str, datetime] = field(default_factory=dict)
    compactaciones: list[datetime] = field(default_factory=list)


@dataclass
class Indice:
    """Lo que el comando necesita de los transcripts, leído en una sola pasada."""

    delegaciones: dict[str, Delegacion] = field(default_factory=dict)
    hilos: dict[str, Hilo] = field(default_factory=dict)
    #: `message.id` → (ts de su primera aparición, sesión, coste a precio de lista o `None`).
    peticiones: dict[str, tuple[datetime, object, float | None]] = field(default_factory=dict)
    #: (tipo, resetsAt) → primer rechazo visto (REQ-051).
    rechazos: dict[tuple[str, object], datetime] = field(default_factory=dict)
    #: (sesión, startTime) → (orden, modelUsage) de la ÚLTIMA línea `cost-state` por posición.
    costes: dict[tuple[object, object], tuple[int, dict]] = field(default_factory=dict)
    ficheros: int = 0
    ficheros_ilegibles: int = 0
    lineas_corruptas: int = 0


def coste_de_peticion(mensaje: dict) -> float | None:
    """Coste a precio de lista de una petición (USD), con la escritura a 5 min y a 1 h separadas
    según `usage.cache_creation`; `None` si el modelo no tiene precio (REQ-051)."""
    p = precios.entrada(str(mensaje.get("model") or ""))
    if p is None:
        return None
    u = mensaje.get("usage") if isinstance(mensaje.get("usage"), dict) else {}
    cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    w5 = cc.get("ephemeral_5m_input_tokens")
    w1 = cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        w5, w1 = u.get("cache_creation_input_tokens") or 0, 0
    return (
        (u.get("input_tokens") or 0) * p["entrada"]
        + (w5 or 0) * p["w5m"]
        + (w1 or 0) * p["w1h"]
        + (u.get("cache_read_input_tokens") or 0) * p["lectura"]
        + (u.get("output_tokens") or 0) * p["salida"]
    ) / 1e6


def _quota_limits(valor: object) -> list:
    if isinstance(valor, list):
        return valor
    return [valor] if isinstance(valor, dict) else []


def _leer_linea(indice: Indice, r: dict, nombre: str, hilo: Hilo, banco: bool, orden: list[int]):
    tipo = r.get("type")
    if tipo == "system" and r.get("subtype") == "compact_boundary":
        t = instante(r.get("timestamp"))
        if t:
            hilo.compactaciones.append(t)
    elif tipo == "cost-state":
        orden[0] += 1
        uso = r.get("modelUsage")
        indice.costes[(r.get("sessionId"), r.get("startTime"))] = (
            orden[0],
            uso if isinstance(uso, dict) else {},
        )
    elif tipo == "assistant":
        mensaje = r.get("message") if isinstance(r.get("message"), dict) else {}
        t = instante(r.get("timestamp"))
        if mensaje.get("model") == "<synthetic>":
            for q in _quota_limits(r.get("quotaLimits")):
                if isinstance(q, dict) and q.get("status") == "rejected" and t:
                    clave = (str(q.get("rateLimitType")), q.get("resetsAt"))
                    indice.rechazos[clave] = min(t, indice.rechazos.get(clave, t))
            return
        mid = mensaje.get("id") or r.get("requestId")
        if mid and t:
            hilo.peticiones.setdefault(mid, t)
            if mid not in indice.peticiones:
                indice.peticiones[mid] = (t, r.get("sessionId"), coste_de_peticion(mensaje))
        contenido = mensaje.get("content")
        for bloque in contenido if isinstance(contenido, list) else []:
            if not (isinstance(bloque, dict) and bloque.get("type") == "tool_use"):
                continue
            nombre_tool = str(bloque.get("name") or "")
            if not nombre_tool.startswith(PREFIJO):
                continue
            entrada = bloque.get("input") if isinstance(bloque.get("input"), dict) else {}
            esfuerzo = r.get("effort")
            camino = entrada.get("path")
            indice.delegaciones[str(bloque.get("id"))] = Delegacion(
                tool=nombre_tool[len(PREFIJO) :],
                ts_use=t,
                hilo=nombre,
                kind=hilo.kind,
                modelo=mensaje.get("model") if isinstance(mensaje.get("model"), str) else None,
                esfuerzo=esfuerzo if isinstance(esfuerzo, str) and esfuerzo else None,
                path=camino if isinstance(camino, str) and camino else None,
                banco=banco,
                mid=mid,
            )
    elif tipo == "user":
        mensaje = r.get("message") if isinstance(r.get("message"), dict) else {}
        contenido = mensaje.get("content")
        for bloque in contenido if isinstance(contenido, list) else []:
            if not (isinstance(bloque, dict) and bloque.get("type") == "tool_result"):
                continue
            d = indice.delegaciones.get(str(bloque.get("tool_use_id")))
            if d is not None and d.ts_res is None:
                d.ts_res = instante(r.get("timestamp"))


def leer(raiz: Path) -> Indice:
    """Recorre `raiz/**/*.jsonl` (en orden de ruta) y devuelve el índice. Nunca lanza por un
    fichero o una línea: los cuenta."""
    indice = Indice()
    raiz = Path(raiz)
    if not raiz.is_dir():
        return indice
    orden = [0]
    for fichero in sorted(raiz.rglob("*.jsonl")):
        partes = fichero.relative_to(raiz).parts
        kind = "subagent" if "subagents" in partes[:-1] else "main"
        banco = "Temp" in partes[0] if len(partes) > 1 else False
        nombre = str(fichero)
        hilo = indice.hilos.setdefault(nombre, Hilo(kind=kind))
        indice.ficheros += 1
        try:
            with fichero.open(encoding="utf-8", errors="replace") as flujo:
                for linea in flujo:
                    if not linea.strip():
                        continue
                    try:
                        r = json.loads(linea)
                    except ValueError:
                        indice.lineas_corruptas += 1
                        continue
                    if isinstance(r, dict):
                        _leer_linea(indice, r, nombre, hilo, banco, orden)
        except OSError:
            indice.ficheros_ilegibles += 1
    for hilo in indice.hilos.values():
        hilo.compactaciones.sort()
    return indice


# --- N y caducidades (REQ-043) ---------------------------------------------------------------


def n_y_caducidades(indice: Indice, d: Delegacion) -> tuple[int, int]:
    """`N` y caducidades de una delegación, dentro de su hilo (REQ-043).

    Petición = línea `assistant` no `<synthetic>`, una por `message.id` (su primera aparición).
    `t0` = el `tool_result` (o el `tool_use` si falta). `N` = peticiones con `ts > t0`, sin la que
    lleva el `tool_use` y anteriores al primer `compact_boundary` posterior a `t0`. Caducidad =
    hueco mayor que el TTL del hilo entre `t0` y la primera, o entre dos seguidas.
    """
    hilo = indice.hilos[d.hilo]
    t0 = d.ts_res or d.ts_use
    if t0 is None:
        return 0, 0
    corte = next((c for c in hilo.compactaciones if c > t0), None)
    posteriores = sorted(
        t
        for mid, t in hilo.peticiones.items()
        if t > t0 and (corte is None or t < corte) and mid != d.mid
    )
    ttl = TTL_S.get(d.kind, TTL_S["main"])
    previo, caducidades = t0, 0
    for t in posteriores:
        if (t - previo).total_seconds() > ttl:
            caducidades += 1
        previo = t
    return len(posteriores), caducidades


def percentil(valores: Iterable[float], q: float) -> float | None:
    """Percentil con interpolación lineal entre rangos (la mediana de un número par de casos es la
    media de los dos centrales). `None` sin valores."""
    xs = sorted(valores)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    bajo = int(k)
    alto = min(bajo + 1, len(xs) - 1)
    return xs[bajo] + (xs[alto] - xs[bajo]) * (k - bajo)


def mediana(valores: Iterable[float]) -> float | None:
    return percentil(valores, 0.5)


# --- Cruce de las líneas del log (REQ-004) ----------------------------------------------------


def _mismo_path(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _admite_esfuerzo(modelo: str) -> bool:
    e = precios.entrada(modelo)
    return True if e is None else bool(e.get("admite_esfuerzo", True))


def entrada_de(indice: Indice, d: Delegacion, cruce: str) -> dict:
    """La entrada del relleno de una línea casada (REQ-005): sin rutas, ids de sesión ni texto."""
    n, cad = n_y_caducidades(indice, d)
    modelo = precios.normalizar_id(d.modelo) if d.modelo else None
    esfuerzo = d.esfuerzo
    if esfuerzo is None and modelo and not _admite_esfuerzo(modelo):
        esfuerzo = "n/a"  # Haiku 4.5: no admite esfuerzo, no es un dato que falte (REQ-003)
    entrada: dict = {"cruce": cruce, "banco": d.banco, "n": n, "caducidades": cad}
    if modelo:
        entrada["caller_model"] = modelo
    entrada["caller_kind"] = d.kind
    if esfuerzo:
        entrada["caller_effort"] = esfuerzo
    return entrada


def _por_tool(indice: Indice) -> dict[str, list[tuple[str, Delegacion]]]:
    grupos: dict[str, list[tuple[str, Delegacion]]] = {}
    for tid, d in indice.delegaciones.items():
        if d.ts_use is not None:
            grupos.setdefault(d.tool, []).append((tid, d))
    return grupos


def necesita_relleno(fila: dict) -> bool:
    """Una línea sin `caller_model`, o a la que le falta `N` (REQ-004)."""
    return not fila.get("caller_model") or fila.get("n") is None


def casar(
    lineas: Iterable[tuple[str, dict]], indice: Indice, *, desde: datetime
) -> dict[str, dict]:
    """`{clave: entrada}` para las líneas del log con `ts >= desde` que lo necesitan (REQ-004).

    `lineas` son pares `(clave, fila)` con la clave de `atribucion.claves_del_fichero` calculada
    sobre el fichero ENTERO. Con `tool_use_id`, el cruce es exacto. Sin él, son candidatos los
    `tool_use` de la misma tool con el `ts` de la línea en [`tool_use` − 1 s, `tool_result` + 2 s]
    (o `tool_use` + 15 min si falta el resultado); con varios, el ÚNICO desempate es el `path`
    igual. Si sigue habiendo más de uno, `ambiguo`; con ninguno, `sin_cruce`.
    """
    grupos = _por_tool(indice)
    resultado: dict[str, dict] = {}
    for clave, fila in lineas:
        t = instante(fila.get("ts"))
        if t is None or t < desde or not necesita_relleno(fila):
            continue
        tool_use_id = fila.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id:
            d = indice.delegaciones.get(tool_use_id)
            resultado[clave] = (
                entrada_de(indice, d, "exacto")
                if d is not None
                else {"cruce": "sin_cruce", "banco": False}
            )
            continue
        candidatos = []
        for _tid, d in grupos.get(str(fila.get("tool") or ""), []):
            fin = d.ts_res or (d.ts_use + SIN_RESULTADO)
            if d.ts_use - ANTES <= t <= fin + DESPUES:
                candidatos.append(d)
        if len(candidatos) == 1:
            resultado[clave] = entrada_de(indice, candidatos[0], "ventana")
        elif len(candidatos) > 1:
            mismos = [d for d in candidatos if _mismo_path(d.path, fila.get("path"))]
            if len(mismos) == 1:
                resultado[clave] = entrada_de(indice, mismos[0], "ventana+path")
            else:
                resultado[clave] = {"cruce": "ambiguo", "banco": False}
        else:
            resultado[clave] = {"cruce": "sin_cruce", "banco": False}
    return resultado


# --- Cotejo (REQ-014) -------------------------------------------------------------------------


def cost_state(indice: Indice) -> list[dict]:
    """Filas «modelo × sesión» de la ÚLTIMA línea `cost-state` por posición de cada
    `(sessionId, startTime)`: `{"modelo", <los seis campos>}`. Sin ids de sesión."""
    filas: list[dict] = []
    for _orden, uso in sorted(indice.costes.values(), key=lambda x: x[0]):
        for modelo, valores in uso.items():
            if not isinstance(valores, dict):
                continue
            fila = {"modelo": str(modelo)}
            for campo in CAMPOS_COTEJO:
                fila[campo] = valores.get(campo) or 0
            filas.append(fila)
    return filas
