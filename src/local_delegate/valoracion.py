"""Coste equivalente a precio de API y bloque de imágenes (coste-api-y-cuota, REQ-038 y REQ-040 a
REQ-048).

Una pregunta: cuánto habría costado, a precio de lista de la API, que Claude leyera lo que leyó el
MCP server-side. **No es dinero ahorrado** (la suscripción es de tarifa plana) y el panel lo dice.

- `precio(m, hilo)`: escritura de caché del hilo (5 min en un subagente, 1 h en el principal) y
  lectura de caché, o `None` si el modelo no está en la tabla (REQ-016: nunca 0).
- `n_de(fila, agregados)`: `N` y caducidades en el orden único de REQ-042 (relleno, mediana del
  grupo con al menos 10 casos, declarado del hilo).
- `coste_evento(fila, agregados)`: `T`, cota baja y estimación de un evento (REQ-041).
- `bloque_coste(filas, agregados)`: la cifra del periodo con todo lo que la acompaña (REQ-007,
  REQ-008, REQ-016, REQ-044, REQ-046, REQ-047); `bloque_imagenes(filas)`: REQ-038.

Las filas llegan **fundidas** (`coste.fundir`, REQ-006). Solo stdlib; no abre sockets ni lee
`~/.claude`: los agregados los trae quien llama (`recalcular.leer_agregados`).
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime

from . import atribucion, coste, precios, server

#: `N` declarado por hilo (REQ-042 (3)), medido con `atribucion_n.py`: principal 127 (14 casos),
#: subagente 40 (135 casos).
N_DECLARADO = {"main": 127, "subagent": 40}
#: Casos mínimos de un grupo para usar su mediana (REQ-042 (2)).
MIN_CASOS_GRUPO = 10
#: Plazo de borrado de los transcripts sin `coste-agregados.json` (Definiciones, `H`).
PLAZO_POR_DEFECTO = atribucion.PLAZO_POR_DEFECTO

ORIGENES_N = ("relleno", "agregado", "declarado")
ORIGENES_DENSIDAD = ("medida", "sin_numerar", "conservadora")

SIN_DELEGACIONES = "sin delegaciones en el periodo"
SIN_TABLA = "no se pudo cargar la tabla de precios del paquete"
TODAS_SIN_PRECIO = "todas las delegaciones del periodo son de modelos sin precio"
COMANDO = "local-delegate recalcular-coste"
VARIABLE_RESPALDO = "LOCAL_DELEGATE_COSTE_RESPALDO"


def nombre_del_modelo(mid: str) -> str:
    """`claude-opus-5-5` → `Opus 5.5`; `claude-haiku-4-5` → `Haiku 4.5`. Solo para rótulos."""
    partes = precios.normalizar_id(str(mid)).removeprefix("claude-").split("-")
    if not partes or not partes[0]:
        return str(mid)
    return " ".join([partes[0].capitalize(), ".".join(partes[1:])]).strip()


def _hilo(fila: dict) -> str:
    hilo = fila.get("caller_kind")
    return hilo if hilo in coste.HILOS else coste.respaldo()["hilo"]


def precio(m: str, hilo: str, tabla: dict | None = None) -> dict | None:
    """`{"w": P_w(m, hilo), "r": P_r(m)}` en USD/MTok, o `None` si `m` no tiene precio."""
    entrada = precios.entrada(str(m or ""), tabla)
    if entrada is None:
        return None
    return {"w": entrada["w5m"] if hilo == "subagent" else entrada["w1h"], "r": entrada["lectura"]}


def _entero(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _n_del_grupo(agregados: dict | None, grupo: str) -> list[int]:
    n_por_mes = agregados.get("n_por_mes") if isinstance(agregados, dict) else None
    if not isinstance(n_por_mes, dict):
        return []
    valores: list[int] = []
    for grupos in n_por_mes.values():
        if isinstance(grupos, dict) and isinstance(grupos.get(grupo), list):
            valores.extend(v for v in grupos[grupo] if _entero(v) is not None)
    return valores


def n_de(fila: dict, agregados: dict | None) -> tuple[float, int, str]:
    """`(N, caducidades, origen)` de un evento, en el orden único de REQ-042:

    (1) `n` y `caducidades` del relleno; (2) la mediana de `N` del grupo (`modelo|hilo`) en los
    agregados guardados, si tiene al menos 10 casos, con 0 caducidades; (3) el declarado del hilo.
    """
    n = _entero(fila.get("n"))
    if n is not None:
        return n, _entero(fila.get("caducidades")) or 0, "relleno"
    valores = _n_del_grupo(agregados, f"{fila.get('caller_model')}|{_hilo(fila)}")
    if len(valores) >= MIN_CASOS_GRUPO:
        return statistics.median(valores), 0, "agregado"
    return N_DECLARADO[_hilo(fila)], 0, "declarado"


def tokens_netos(fila: dict) -> int:
    """`T`: tokens de Claude del texto leído server-side menos los devueltos (Definiciones). 0 en
    una imagen (REQ-038). Pasa SOLO por `server.tokens_claude`."""
    if coste.es_imagen(fila):
        return 0
    acc = server._accounting(fila)
    return server.tokens_claude(
        acc["chars_saved_text"], tipo="text", evento=fila
    ) - server.tokens_claude(acc["chars_returned"], tipo="returned", evento=fila)


def coste_evento(fila: dict, agregados: dict | None = None, tabla: dict | None = None) -> dict:
    """`T`, cota baja y estimación de UN evento (REQ-041), con `N` y su origen.

    cota baja = T × P_w(m, hilo); estimación = T × (P_w × (1 + cad) + (N − cad) × P_r). Un `T`
    negativo resta. Sin precio: `cota_baja` y `estimacion` son `None` (nunca 0).
    """
    hilo = _hilo(fila)
    modelo = str(fila.get("caller_model") or "")
    t = tokens_netos(fila)
    n, cad, origen = n_de(fila, agregados)
    p = precio(modelo, hilo, tabla)
    salida = {
        "modelo": modelo,
        "hilo": hilo,
        "esfuerzo": fila.get("caller_effort") or "sin dato",
        "T": t,
        "N": n,
        "caducidades": cad,
        "origen_n": origen,
        "cota_baja": None,
        "estimacion": None,
    }
    if p is not None:
        salida["cota_baja"] = t * p["w"] / 1e6
        salida["estimacion"] = t * (p["w"] * (1 + cad) + (n - cad) * p["r"]) / 1e6
    return salida


def _en_la_base(fila: dict, acc: dict) -> bool:
    """REQ-040: atribuible (sin fallo), de texto, con algo leído o devuelto."""
    if acc["failed"] or coste.es_imagen(fila):
        return False
    return acc["chars_saved_text"] > 0 or acc["chars_returned"] > 0


def _dinero(x: float) -> float:
    """A céntimos. Sumar 0.0 convierte el `-0.0` de un negativo diminuto en `0.0`: la API no
    devuelve un cero con signo (la fórmula no cambia; un negativo de verdad sigue negativo)."""
    return round(x, 2) + 0.0


def bloque_coste(
    filas: Iterable[dict], agregados: dict | None, *, ahora: datetime | None = None
) -> dict:
    """La cifra del periodo con sus supuestos a la vista. Sin cifra, el motivo (REQ-046)."""
    ahora = ahora or datetime.now(UTC)
    plazo = PLAZO_POR_DEFECTO
    if isinstance(agregados, dict):
        plazo = _entero(agregados.get("plazo_dias")) or PLAZO_POR_DEFECTO
    try:
        tabla = precios.cargar_precios()
        r = coste.respaldo()
    except Exception:
        # Sin tabla no hay cifra (REQ-046), pero la barra y el motivo se enseñan igual.
        tabla, r = None, dict(coste.RESPALDO_DECLARADO, respaldo_invalido=False)

    barra: Counter = Counter({t: 0 for t in coste.TRAMOS})
    excluidas_por_motivo: Counter = Counter()
    n_origen: Counter = Counter({o: 0 for o in ORIGENES_N})
    densidad_origen: Counter = Counter({o: 0 for o in ORIGENES_DENSIDAD})
    familias: Counter = Counter()
    marcas: Counter = Counter()
    fuera = {"imagenes": 0, "salida_a_fichero": 0}
    sin_precio: Counter = Counter()
    desglose: dict[tuple, dict] = {}
    respaldo_invalido = bool(r.get("respaldo_invalido"))
    cota = estimacion = 0.0
    t_total = valoradas = en_base = 0

    for fila in filas:
        acc = server._accounting(fila)
        if acc["failed"]:
            continue
        if coste.es_imagen(fila):
            fuera["imagenes"] += 1
            continue
        if acc["chars_saved_output"] > 0:
            fuera["salida_a_fichero"] += 1
        if not _en_la_base(fila, acc):
            continue
        tramo = coste.tramo(fila, ahora=ahora, plazo_dias=plazo)
        barra[tramo] += 1
        if tramo == "excluido":
            excluidas_por_motivo[atribucion.excluida(fila, {"banco": fila.get("banco")})] += 1
            continue
        en_base += 1
        if fila.get("respaldo_invalido"):
            respaldo_invalido = True
        texto = (fila.get("densidad") or {}).get("text")
        if texto:
            densidad_origen[texto[1]] += 1
        familias[str(fila.get("familia"))] += 1
        marcas.update(fila.get("marcas") or [])
        if tabla is None:
            continue
        c = coste_evento(fila, agregados, tabla)
        n_origen[c["origen_n"]] += 1
        if c["cota_baja"] is None:
            sin_precio[precios.normalizar_id(c["modelo"])] += 1
            continue
        valoradas += 1
        t_total += c["T"]
        cota += c["cota_baja"]
        estimacion += c["estimacion"]
        clave = (c["modelo"], c["hilo"], c["esfuerzo"])
        g = desglose.setdefault(
            clave,
            {
                "modelo": c["modelo"],
                "nombre": nombre_del_modelo(c["modelo"]),
                "hilo": c["hilo"],
                "esfuerzo": c["esfuerzo"],
                "casos": 0,
                "T": 0,
                "cota_baja": 0.0,
                "estimacion": 0.0,
            },
        )
        g["casos"] += 1
        g["T"] += c["T"]
        g["cota_baja"] += c["cota_baja"]
        g["estimacion"] += c["estimacion"]

    if tabla is None:
        motivo = SIN_TABLA
    elif en_base == 0:
        motivo = SIN_DELEGACIONES
    elif valoradas == 0:
        motivo = TODAS_SIN_PRECIO
    else:
        motivo = None

    con_supuesto = barra["pendiente"] + barra["supuesto"]
    return {
        "cifra": None
        if motivo
        else {"cota_baja": _dinero(cota), "estimacion": _dinero(estimacion)},
        "motivo": motivo,
        "eventos": valoradas,
        "T": t_total,
        "barra": {
            **{t: barra[t] for t in coste.TRAMOS},
            "valoradas": en_base,
            "con_modelo_supuesto": con_supuesto,
            "excluidas_por_motivo": dict(sorted(excluidas_por_motivo.items())),
            "plazo_dias": plazo,
        },
        "respaldo": {
            "modelo": r["modelo"],
            "nombre": nombre_del_modelo(r["modelo"]),
            "hilo": r["hilo"],
            "invalido": respaldo_invalido,
            "variable": VARIABLE_RESPALDO,
        },
        "n_origen": {o: n_origen[o] for o in ORIGENES_N},
        "n_declarado": dict(N_DECLARADO),
        "densidad": {
            "origen": {o: densidad_origen[o] for o in ORIGENES_DENSIDAD},
            "familias": dict(sorted(familias.items())),
            "familia_supuesta": marcas[coste.MARCA_FAMILIA_SUPUESTA],
            "densidad_de_la_familia": marcas[coste.MARCA_DENSIDAD_DE_LA_FAMILIA],
        },
        "sin_precio": {"n": sum(sin_precio.values()), "ids": sorted(sin_precio)},
        "fuera_de_la_base": fuera,
        "desglose": [
            {**g, "cota_baja": _dinero(g["cota_baja"]), "estimacion": _dinero(g["estimacion"])}
            for g in sorted(desglose.values(), key=lambda g: -g["estimacion"])
        ],
        "tabla": {
            "consultado": (tabla or {}).get("consultado"),
            "fuente": (tabla or {}).get("fuente"),
        },
        "comando": COMANDO,
    }


def bloque_imagenes(filas: Iterable[dict]) -> dict:
    """REQ-038: número de imágenes, bytes leídos server-side y caracteres devueltos a Claude, sin
    ninguna cifra de tokens de Claude. Los fallos no cuentan."""
    n = bytes_ = devueltos = 0
    for fila in filas:
        if not coste.es_imagen(fila):
            continue
        acc = server._accounting(fila)
        if acc["failed"]:
            continue
        n += 1
        bytes_ += acc["bytes_saved_image"]
        devueltos += acc["chars_returned"]
    return {"n": n, "bytes": bytes_, "chars_devueltos": devueltos}
