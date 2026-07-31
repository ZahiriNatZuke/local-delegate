"""Comportamiento del JavaScript del dashboard, **ejecutado** con node.

De las 674 líneas de JS del panel, hasta ahora solo una función se ejecutaba en la suite (la
paridad de `acct()` con Python); el resto se cubría con `node --check` y *grep* sobre el HTML —
que comprueba que el fichero parsea y que cierto texto está ahí, no lo que hace.

Este módulo cubre las funciones donde un fallo **cambia lo que el usuario ve**:

- `computeRange`: decide qué se le pide al backend. Si se equivoca, el panel entero enseña otro
  periodo y todo lo demás es coherente con el dato equivocado.
- `localDayKey` / `byDay`: agrupan por **tu** día natural. El log está en UTC, así que aquí es
  donde se cruza la frontera de zona horaria — y el comentario del propio código avisa: «no uses
  toISOString(): eso vuelve a UTC».
- `agg`: alimenta los donuts.
- `fmtHace`: el «hace X» del indicador de actividad.

**Los tests fijan `TZ` a una zona con offset negativo** y no confían en la del que ejecuta: con
`TZ=UTC` un `localDayKey` mal escrito pasaría igual, que es exactamente cómo estos fallos
sobreviven.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from local_delegate.web import metrics

TZ_PRUEBA = "America/Havana"  # UTC-5/-4: si algo cae a UTC, se nota


def _extraer(cabecera: str) -> str:
    """Recorta una función del `<script>` balanceando llaves. Igual que en `test_metrics.py`."""
    fuente = metrics.HTML
    i = fuente.index(cabecera)
    depth, j = 0, i
    while True:
        if fuente[j] == "{":
            depth += 1
        elif fuente[j] == "}":
            depth -= 1
            if depth == 0:
                return fuente[i : j + 1]
        j += 1


def _correr(tmp_path, funciones: list[str], cuerpo: str, preludio: str = ""):
    """Ejecuta `cuerpo` con esas funciones del panel cargadas. Devuelve lo que imprima en JSON."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    programa = tmp_path / "prueba.mjs"
    programa.write_text(
        "\n".join([preludio, *(_extraer(f) for f in funciones), cuerpo]),
        encoding="utf-8",
    )
    # El entorno se hereda ENTERO con `TZ` encima. Recortarlo a `PATH` + `TZ` mata a node en
    # Windows con SIGABRT: necesita `SYSTEMROOT` y compañía. Lo que importa aquí es fijar la zona,
    # no aislar el proceso.
    entorno = {**os.environ, "TZ": TZ_PRUEBA}
    salida = subprocess.run(
        [node, str(programa)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        env=entorno,
    )
    return json.loads(salida.stdout)


# --- computeRange: qué periodo se le pide al backend --------------------------

_DOM_FECHAS = """
const _inputs = {rangeFrom:{value:''}, rangeTo:{value:''}};
globalThis.document = {getElementById: id => _inputs[id]};
"""


def test_hoy_empieza_en_TU_medianoche_no_en_la_de_UTC(tmp_path):
    """«Hoy» tiene que empezar a tu medianoche local; en UTC empezaría a otra hora.

    Es el defecto que la propia documentación del panel señala como delicado, y con `TZ=UTC` en
    el runner un `from` mal calculado pasaría desapercibido.
    """
    resultado = _correr(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        "const r = computeRange('today');\n"
        "const d = new Date(r.from);\n"
        "console.log(JSON.stringify({\n"
        "  horaLocal: d.getHours(), minLocal: d.getMinutes(), segLocal: d.getSeconds(),\n"
        "  esMedianocheUTC: r.from.includes('T00:00:00'),\n"
        "}));",
        preludio=_DOM_FECHAS,
    )

    assert (resultado["horaLocal"], resultado["minLocal"], resultado["segLocal"]) == (0, 0, 0)
    assert not resultado["esMedianocheUTC"], (
        "el 'from' cayó en medianoche UTC: se está usando la medianoche equivocada"
    )


@pytest.mark.parametrize(("preset", "dias"), [("7", 7), ("30", 30)])
def test_los_presets_de_dias_incluyen_hoy(tmp_path, preset, dias):
    """7 días son hoy y los seis anteriores, no hoy y los siete anteriores.

    Un `off-by-one` aquí no rompe nada visible: el panel enseña un día de más y todo cuadra
    consigo mismo. Solo se caza contando.
    """
    resultado = _correr(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        f"const r = computeRange({preset!r});\n"
        "const desde = new Date(r.from), hasta = new Date(r.to);\n"
        "const medianocheHoy = new Date(hasta.getFullYear(), hasta.getMonth(), hasta.getDate());\n"
        "console.log(JSON.stringify({\n"
        "  dias: Math.round((medianocheHoy - desde) / 86400000) + 1,\n"
        "  desdeMedianoche: desde.getHours() === 0 && desde.getMinutes() === 0,\n"
        "}));",
        preludio=_DOM_FECHAS,
    )

    assert resultado["dias"] == dias
    assert resultado["desdeMedianoche"]


def test_el_mes_anterior_va_del_dia_1_al_dia_1(tmp_path):
    """Medio abierto: incluye el mes entero y no se cuela ningún evento del actual."""
    resultado = _correr(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        "const r = computeRange('prev-month');\n"
        "const desde = new Date(r.from), hasta = new Date(r.to);\n"
        "const hoy = new Date();\n"
        "console.log(JSON.stringify({\n"
        "  diaDesde: desde.getDate(), diaHasta: hasta.getDate(),\n"
        "  mesesDeDiferencia: (hasta.getFullYear()-desde.getFullYear())*12 "
        "+ (hasta.getMonth()-desde.getMonth()),\n"
        "  hastaEsEsteMes: hasta.getMonth() === hoy.getMonth(),\n"
        "}));",
        preludio=_DOM_FECHAS,
    )

    assert (resultado["diaDesde"], resultado["diaHasta"]) == (1, 1)
    assert resultado["mesesDeDiferencia"] == 1
    assert resultado["hastaEsEsteMes"], "el corte superior debe ser el día 1 del mes actual"


def test_el_rango_personalizado_cubre_el_ultimo_dia_entero(tmp_path):
    """Un `to` a las 00:00 se comería el día final completo — el error clásico de este control."""
    resultado = _correr(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        "_inputs.rangeFrom.value = '2026-03-10';\n"
        "_inputs.rangeTo.value   = '2026-03-12';\n"
        "const r = computeRange('custom');\n"
        "const desde = new Date(r.from), hasta = new Date(r.to);\n"
        "console.log(JSON.stringify({\n"
        "  desde: [desde.getDate(), desde.getHours(), desde.getMinutes()],\n"
        "  hasta: [hasta.getDate(), hasta.getHours(), hasta.getMinutes(), hasta.getSeconds()],\n"
        "}));",
        preludio=_DOM_FECHAS,
    )

    assert resultado["desde"] == [10, 0, 0]
    assert resultado["hasta"] == [12, 23, 59, 59], "el día final tiene que entrar entero"


def test_un_preset_desconocido_no_inventa_un_rango(tmp_path):
    """Sin rango, el backend aplica su default; con uno inventado, enseñaría datos arbitrarios."""
    resultado = _correr(
        tmp_path,
        ["function localMidnight(d, deltaDays){", "function computeRange(preset){"],
        "console.log(JSON.stringify(computeRange('lo-que-sea')));",
        preludio=_DOM_FECHAS,
    )
    assert resultado == {"from": None, "to": None}


# --- Agrupación por día local -------------------------------------------------


def test_la_clave_del_dia_es_la_local_y_no_la_de_UTC(tmp_path):
    """Un evento de las 21:00 en La Habana es del **día siguiente** en UTC.

    Si `localDayKey` usara `toISOString()`, ese evento saltaría de barra en el gráfico. El
    comentario del código avisa de esto; el test lo obliga.
    """
    resultado = _correr(
        tmp_path,
        ["function localDayKey(d){"],
        # 2026-03-10T02:00:00Z = 2026-03-09 21:00 en La Habana (UTC-5)
        "const d = new Date('2026-03-10T02:00:00Z');\n"
        "console.log(JSON.stringify({local: localDayKey(d), utc: d.toISOString().slice(0,10)}));",
    )

    assert resultado["utc"] == "2026-03-10"
    assert resultado["local"] == "2026-03-09", "la clave del día se calculó en UTC"


def test_byDay_agrupa_por_dia_local_y_sale_en_orden(tmp_path):
    """Los eventos llegan del backend **más recientes primero**, así que el orden lo pone `byDay`.

    Los datos entran a propósito en orden inverso al esperado: con la entrada ya ordenada, quitar
    el `sort` del código no cambiaría nada y el test aprobaría un gráfico con las barras
    desordenadas. Comprobado con un mutante.
    """
    eventos = [
        {"ts": "2026-03-11T15:00:00Z", "tool": "t", "source": "path", "chars_in": 4000},
        {"ts": "2026-03-10T02:00:00Z", "tool": "t", "source": "path", "chars_in": 4000},
        {"ts": "2026-03-09T15:00:00Z", "tool": "t", "source": "path", "chars_in": 4000},
    ]
    resultado = _correr(
        tmp_path,
        ["function localDayKey(d){", "function acct(e){", "function byDay(ev){"],
        f"const ev = {json.dumps(eventos)};\n"
        "console.log(JSON.stringify(byDay(ev).map(([k, v]) => [k, v.calls])));",
        preludio="const CPT = 4;\nconst tok = c => Math.floor(c/CPT);\n",
    )

    # Los dos primeros caen en el mismo día LOCAL (9 de marzo), el tercero en el 11.
    assert resultado == [["2026-03-09", 2], ["2026-03-11", 1]]


def test_byDay_ignora_un_ts_ilegible_en_vez_de_reventar(tmp_path):
    """Una línea con la fecha corrupta no puede dejar el gráfico en blanco."""
    eventos = [
        {"ts": "no es una fecha", "tool": "t", "source": "path", "chars_in": 4000},
        {"ts": "2026-03-09T15:00:00Z", "tool": "t", "source": "path", "chars_in": 4000},
    ]
    resultado = _correr(
        tmp_path,
        ["function localDayKey(d){", "function acct(e){", "function byDay(ev){"],
        f"console.log(JSON.stringify(byDay({json.dumps(eventos)}).length));",
        preludio="const CPT = 4;\nconst tok = c => Math.floor(c/CPT);\n",
    )
    assert resultado == 1


# --- agg: lo que alimenta los donuts ------------------------------------------


def test_agg_suma_por_clave_y_ordena_de_mayor_a_menor(tmp_path):
    """Suma por clave y ordena de mayor a menor. Los empates conservan el orden de aparición.

    Lo del empate no es una decisión de diseño sino una consecuencia de que `Array.sort` es
    estable y `Map` conserva el orden de inserción. Se fija en el test para que se vea, no para
    obligar a nada: si un día importara, tendría que ser explícito en el comparador.
    """
    eventos = [
        {"tool": "a", "n": 1},
        {"tool": "b", "n": 5},
        {"tool": "a", "n": 2},
        {"tool": "c", "n": 3},
    ]
    resultado = _correr(
        tmp_path,
        ["function agg(ev,key,valfn){"],
        f"console.log(JSON.stringify(agg({json.dumps(eventos)}, 'tool', e => e.n)));",
    )
    assert resultado == [["b", 5], ["a", 3], ["c", 3]]


def test_agg_descarta_las_categorias_a_cero(tmp_path):
    """Un donut con porciones de tamaño 0 pinta leyenda para lo que no se ve."""
    eventos = [{"tool": "a", "n": 0}, {"tool": "b", "n": 4}]
    resultado = _correr(
        tmp_path,
        ["function agg(ev,key,valfn){"],
        f"console.log(JSON.stringify(agg({json.dumps(eventos)}, 'tool', e => e.n)));",
    )
    assert resultado == [["b", 4]]


# --- fmtHace: el «hace X» del indicador ---------------------------------------


def test_fmtHace_cambia_de_unidad_en_las_fronteras(tmp_path):
    """Las fronteras exactas, que es donde vive el off-by-one de este tipo de función."""
    casos = [0, 59, 60, 119, 3599, 3600, 7199, 86399, 86400, 172800]
    resultado = _correr(
        tmp_path,
        ["function fmtHace(s){"],
        f"console.log(JSON.stringify({json.dumps(casos)}.map(fmtHace)));",
    )
    assert resultado == [
        "0s",
        "59s",
        "1 min",
        "1 min",
        "59 min",
        "1 h",
        "1 h",
        "23 h",
        "1 d",
        "2 d",
    ]
