"""`local-delegate recalcular-coste`: relleno, agregados de `N`, cotejo real y puntos de cuota.

Lo lanza el usuario (REQ-070). Lee los transcripts de `claude_dir/projects`, el registro del
statusline (`claude_dir/cuota-statusline.jsonl`) y el log de uso, y escribe SOLO en el
directorio de logs (REQ-074):

- `atribucion-AAAAMM.json` por mes, con `atribucion.escribir_relleno` (REQ-004, REQ-005);
- `coste-agregados.json`, cuyo formato lee y escribe solo este módulo (ver el plan):
  `{"version", "generado", "plazo_dias", "cotejo", "n_por_mes", "puntos", "descartes",
  "reinicios", "fuentes"}`.

Nada de lo que escribe lleva rutas, ids de sesión ni texto (REQ-072). Lanzado dos veces con los
mismos datos, deja los mismos ficheros salvo `generado` (REQ-074).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import atribucion, coste, cuota, precios, transcripts

NOMBRE = "coste-agregados.json"
VERSION = 1

#: Los agregados de `N` de un mes que terminó hace más de esto no se recalculan (REQ-071).
MES_CERRADO = timedelta(days=30)

_FICHERO_DE_MES = re.compile(r"^usage-(\d{6})\.jsonl$")


# --- coste-agregados.json -----------------------------------------------------------------------


def ruta(log_dir: Path) -> Path:
    return Path(log_dir) / NOMBRE


def leer_agregados(log_dir: Path) -> dict | None:
    """El último `coste-agregados.json`, o `None` si no existe, no se lee o no tiene la forma."""
    try:
        datos = json.loads(ruta(log_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def escribir_agregados(log_dir: Path, agregados: dict) -> None:
    """Escribe el JSON de forma atómica (temporal en el mismo directorio y `os.replace`)."""
    destino = ruta(log_dir)
    destino.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(dir=destino.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as flujo:
            json.dump(agregados, flujo, ensure_ascii=False, sort_keys=True, indent=1)
        os.replace(temporal, destino)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            # Limpieza de mejor esfuerzo: si el temporal ya no está o no se puede borrar, se
            # ignora para que el `raise` de abajo propague el error original y no este.
            pass
        raise


# --- El log de uso --------------------------------------------------------------------------


def _ficheros_del_log(log_dir: Path) -> list[tuple[Path, str]]:
    salida = []
    if Path(log_dir).is_dir():
        for p in sorted(Path(log_dir).glob("usage-*.jsonl")):
            m = _FICHERO_DE_MES.match(p.name)
            if m:
                salida.append((p, m.group(1)))
    return salida


def _leer_log(path: Path) -> list[dict]:
    """Las filas del fichero como las lee el panel: las líneas rotas se saltan (no cambian el
    ordinal de las demás, que solo cuenta líneas con `ts` y `tool`)."""
    filas: list[dict] = []
    try:
        with path.open(encoding="utf-8") as flujo:
            for linea in flujo:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    fila = json.loads(linea)
                except ValueError:
                    continue
                if isinstance(fila, dict):
                    filas.append(fila)
    except OSError:
        return []
    return filas


def _mes(ts: object) -> str | None:
    t = transcripts.instante(ts)
    return f"{t:%Y%m}" if t else None


def _fin_de_mes(mes: str) -> datetime:
    anio, m = int(mes[:4]), int(mes[4:6])
    return datetime(anio + (m == 12), (m % 12) + 1, 1, tzinfo=UTC)


# --- Agregados de N (REQ-042 (2), REQ-071) --------------------------------------------------


def _n_del_fichero(fundidas: list[dict]) -> dict[str, dict[str, list[int]]]:
    """`{mes: {"modelo|hilo": [N, ...]}}` de las delegaciones atribuibles con `N` del relleno que
    no están excluidas (ni clientes de pruebas ni bancos)."""
    por_mes: dict[str, dict[str, list[int]]] = {}
    for f in fundidas:
        if f.get("ok") is False or f.get("caller_origen") == "respaldo":
            continue
        n = f.get("n")
        if isinstance(n, bool) or not isinstance(n, int):
            continue
        if atribucion.excluida(f, {"banco": f.get("banco")}):
            continue
        mes = _mes(f.get("ts"))
        modelo, hilo = f.get("caller_model"), f.get("caller_kind")
        if not mes or not modelo or hilo not in coste.HILOS:
            continue
        por_mes.setdefault(mes, {}).setdefault(f"{modelo}|{hilo}", []).append(n)
    return por_mes


def _fundir_n_por_mes(nuevos: dict, previos: dict, *, ahora: datetime) -> dict:
    """Un mes cerrado hace más de 30 días conserva lo guardado; los demás se recalculan."""
    salida: dict = {}
    for mes in sorted(set(nuevos) | set(previos)):
        cerrado = ahora - _fin_de_mes(mes) > MES_CERRADO
        if mes in previos and (cerrado or mes not in nuevos):
            salida[mes] = previos[mes]
        else:
            salida[mes] = {g: sorted(v) for g, v in sorted(nuevos[mes].items())}
    return salida


# --- Cotejo (REQ-014) -----------------------------------------------------------------------


def _cotejo(indice: transcripts.Indice, *, ahora: datetime) -> dict | None:
    filas = transcripts.cost_state(indice)
    if not filas:
        return None
    tabla = precios.cargar_precios()
    resultados = precios.cotejar(filas, tabla)
    sin_precio = sorted(
        {precios.normalizar_id(f["modelo"]) for f, r in zip(filas, resultados) if r == "sin_precio"}
    )
    return {
        "fecha": ahora.isoformat(timespec="seconds"),
        "version_tabla": tabla.get("consultado"),
        "juzgadas": sum(1 for r in resultados if r is not None),
        "fuera": sum(1 for r in resultados if r == "fuera"),
        "sin_precio": sin_precio,
        "veredicto": precios.veredicto(resultados),
    }


# --- Puntos de cuota (REQ-051 a REQ-054, REQ-071) -------------------------------------------


def _clave_de_punto(p: dict) -> tuple:
    return (p.get("fuente"), p.get("tipo"), p.get("inicio"), p.get("fin"))


def _sumar(destino: dict[str, Counter], origen: dict[str, Counter]) -> None:
    for tipo, conteo in origen.items():
        destino.setdefault(tipo, Counter()).update(conteo)


def _puntos(
    claude_dir: Path, indice: transcripts.Indice, previos: list, *, ahora: datetime
) -> tuple[list[dict], dict[str, dict[str, int]], bool]:
    descartes = cuota.descartes_vacios()
    if indice.lineas_corruptas or indice.ficheros_ilegibles:
        for tipo in cuota.TIPOS:
            descartes[tipo]["linea_corrupta"] += indice.lineas_corruptas + indice.ficheros_ilegibles
    peticiones = list(indice.peticiones.values())
    nuevos = cuota.puntos_de_rechazo(indice.rechazos, peticiones)

    registro = Path(claude_dir) / "cuota-statusline.jsonl"
    hay_registro = registro.is_file()
    if hay_registro:
        try:
            with registro.open(encoding="utf-8", errors="replace") as flujo:
                por_tipo, sesiones, d = cuota.sanear(flujo)
        except OSError:
            por_tipo, sesiones, d = {}, set(), cuota.descartes_vacios()
            for tipo in cuota.TIPOS:
                d[tipo]["linea_corrupta"] += 1
        _sumar(descartes, d)
        del_statusline, d = cuota.puntos_del_statusline(por_tipo, sesiones, peticiones)
        _sumar(descartes, d)
        nuevos += del_statusline

    # Fundir con los del JSON anterior por (fuente, tipo, inicio, fin): un punto cuyo transcript
    # ya se borró sigue ahí hasta que caduca (REQ-071).
    previos, d = cuota.separar_mal_formados(previos)
    _sumar(descartes, d)
    por_clave = {_clave_de_punto(p): p for p in previos}
    for p in nuevos:
        por_clave[_clave_de_punto(p)] = p
    vivos = [p for p in por_clave.values() if cuota.vigentes([p], ahora)]
    puntos, d = cuota.quitar_solapados(vivos)
    _sumar(descartes, d)
    limpios = {tipo: dict(sorted(c.items())) for tipo, c in descartes.items()}
    return puntos, limpios, hay_registro


# --- El comando -----------------------------------------------------------------------------


def ejecutar(
    claude_dir: Path,
    log_dir: Path,
    *,
    ahora: datetime | None = None,
    reiniciar: str | None = None,
) -> dict:
    """Recalcula todo y devuelve un resumen con conteos (sin rutas)."""
    ahora = ahora or datetime.now(UTC)
    claude_dir, log_dir = Path(claude_dir), Path(log_dir)
    plazo = atribucion.plazo_de_borrado(claude_dir)
    proyectos = claude_dir / "projects"
    hay_transcripts = proyectos.is_dir()
    indice = transcripts.leer(proyectos)
    previo = leer_agregados(log_dir) or {}

    # 1. Relleno, por fichero y con las claves del fichero ENTERO (REQ-004, REQ-005).
    desde = ahora - timedelta(days=plazo)
    cruces: Counter = Counter()
    lineas_en_plazo = 0
    ficheros = _ficheros_del_log(log_dir)
    filas_por_fichero = []
    for path, _ym in ficheros:
        filas = _leer_log(path)
        filas_por_fichero.append(filas)
        if not hay_transcripts:
            continue  # sin transcripts no hay nada con qué casar: no se marca nada `sin_cruce`
        claves = atribucion.claves_del_fichero(filas)
        entradas = transcripts.casar(zip(claves, filas, strict=True), indice, desde=desde)
        por_mes: dict[str, dict[str, dict]] = {}
        for clave, fila in zip(claves, filas, strict=True):
            if clave in entradas:
                mes = _mes(fila.get("ts"))
                if mes:
                    por_mes.setdefault(mes, {})[clave] = entradas[clave]
        for mes, del_mes in sorted(por_mes.items()):
            atribucion.escribir_relleno(log_dir, mes, del_mes)
        lineas_en_plazo += len(entradas)
        cruces.update(e["cruce"] for e in entradas.values())

    # 2. Agregados de N, sobre las filas fundidas con el relleno ya escrito.
    nuevos_n: dict[str, dict[str, list[int]]] = {}
    for filas in filas_por_fichero:
        for mes, grupos in _n_del_fichero(coste.fundir(filas, log_dir=log_dir)).items():
            destino = nuevos_n.setdefault(mes, {})
            for grupo, valores in grupos.items():
                destino.setdefault(grupo, []).extend(valores)
    previos_n = previo.get("n_por_mes") if isinstance(previo.get("n_por_mes"), dict) else {}
    n_por_mes = _fundir_n_por_mes(nuevos_n, previos_n, ahora=ahora)

    # 3. Cotejo real; sin filas `cost-state`, se conserva el último.
    cotejo = _cotejo(indice, ahora=ahora)
    if cotejo is None and isinstance(previo.get("cotejo"), dict):
        cotejo = previo["cotejo"]

    # 4. Puntos de cuota y reinicios.
    previos_puntos = previo.get("puntos") if isinstance(previo.get("puntos"), list) else []
    puntos, descartes, hay_registro = _puntos(claude_dir, indice, previos_puntos, ahora=ahora)
    reinicios = {tipo: None for tipo in cuota.TIPOS}
    if isinstance(previo.get("reinicios"), dict):
        reinicios.update({t: previo["reinicios"].get(t) for t in cuota.TIPOS})
    if reiniciar:
        reinicios[reiniciar] = ahora.isoformat(timespec="seconds")

    agregados = {
        "version": VERSION,
        "generado": ahora.isoformat(timespec="seconds"),
        "plazo_dias": plazo,
        "cotejo": cotejo,
        "n_por_mes": n_por_mes,
        "puntos": puntos,
        "descartes": descartes,
        "reinicios": reinicios,
        "fuentes": {"transcripts": hay_transcripts, "statusline": hay_registro},
    }
    escribir_agregados(log_dir, agregados)

    estado = cuota.estado(agregados, ahora)
    return {
        "plazo_dias": plazo,
        "transcripts": indice.ficheros,
        "lineas_corruptas": indice.lineas_corruptas + indice.ficheros_ilegibles,
        "lineas_rellenadas": lineas_en_plazo,
        "cruces": dict(sorted(cruces.items())),
        "cotejo": cotejo,
        "n_casos": sum(len(v) for g in n_por_mes.values() for v in g.values()),
        "puntos": dict(Counter(f"{p['fuente']}:{p['tipo']}" for p in puntos)),
        "descartes": descartes,
        "cuota": {t: e["estado"] for t, e in estado.items()},
        "reinicios": reinicios,
    }


def texto_del_resumen(r: dict) -> str:
    """El resumen para la terminal: conteos, nunca rutas."""
    lineas = [
        f"Plazo de borrado de los transcripts: {r['plazo_dias']} días.",
        f"Transcripts leídos: {r['transcripts']} (líneas ilegibles: {r['lineas_corruptas']}).",
        f"Líneas del log rellenadas: {r['lineas_rellenadas']} "
        + (
            "(" + ", ".join(f"{k}: {v}" for k, v in r["cruces"].items()) + ")"
            if r["cruces"]
            else "(ninguna)"
        )
        + ".",
        f"Casos de N en los agregados: {r['n_casos']}.",
    ]
    c = r.get("cotejo")
    if c:
        lineas.append(
            f"Cotejo de precios ({c.get('version_tabla')}): {c.get('veredicto')}; "
            f"{c.get('juzgadas')} filas juzgadas, {c.get('fuera')} fuera, "
            f"sin precio: {', '.join(c.get('sin_precio') or []) or 'ninguno'}."
        )
    else:
        lineas.append("Cotejo de precios: sin datos de coste en los transcripts.")
    for tipo in cuota.TIPOS:
        d = r["descartes"].get(tipo) or {}
        lineas.append(
            f"Cuota {tipo}: {r['cuota'][tipo]}; puntos: "
            f"{r['puntos'].get('statusline:' + tipo, 0)} del statusline, "
            f"{r['puntos'].get('rechazo:' + tipo, 0)} de rechazo; descartes: "
            + (", ".join(f"{k} {v}" for k, v in d.items()) or "ninguno")
            + "."
        )
    return "\n".join(lineas)
