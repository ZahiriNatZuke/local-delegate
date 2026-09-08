"""Lo que esta maquina ha observado del tamano de salida de cada ejecutable.

Es la mitad que hace que el criterio no este calibrado al perfil de nadie: la semilla de
`output_policy` dice lo que suele ser ruidoso en general, y esto dice lo que es ruidoso **aqui**.

Tres decisiones que no son de gusto:

- **Almacen propio, no colgado de la telemetria** (REQ-021). La telemetria de los hooks es opt-in
  y esta vacia en la mayoria de maquinas; si el aprendizaje dependiera de ella seria un no-op casi
  siempre, y los tests no lo verian porque la encienden.
- **La ruta es un parametro**, no una constante. Sin eso, el replay que tiene que medir el
  criterio contra un corpus real no se puede aislar del almacen de esta maquina.
- **Ni comandos, ni argumentos, ni rutas** (REQ-015). Solo el ejecutable ya normalizado y
  magnitudes, igual que la telemetria de uso.

Solo stdlib: estos scripts corren fuera del paquete y no pueden importarlo.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from output_policy import Estadistica, Umbrales

APP = "local-delegate"
FICHERO = "output-stats.json"
VERSION = 1

#: Cuantas muestras se guardan por ejecutable. Una ventana corta se adapta rapido a un proyecto
#: nuevo; una larga aguanta mejor el ruido. Se guardan los TAMANOS y no un «grande: si/no» para
#: que el replay pueda recalcular con otro umbral sin volver a recoger nada.
MUESTRAS_POR_EJECUTABLE = 20

#: Tope de ejecutables distintos, para que un fichero de estadisticas no crezca sin final. Al
#: pasarse se descarta el que menos se ha visto, que es el que menos dice.
MAX_EJECUTABLES = 500

#: A partir de aqui una salida se considera «grande». Provisional a proposito: el valor bueno lo
#: fija la medicion del replay (REQ-016b), no esta constante. El punto de partida sale del corpus
#: medido: 42 salidas de 8 KB o mas en 21 dias.
UMBRAL_KB_POR_DEFECTO = 8.0

#: Idem: los fija el replay. Aqui solo hay un punto de partida con el que arrancar.
MIN_MUESTRAS_POR_DEFECTO = 5
PROPORCION_POR_DEFECTO = 0.5


def _directorio_de_datos() -> Path:
    """El mismo sitio donde el paquete guarda su log, calculado sin `platformdirs`.

    Se replica a mano porque un hook es stdlib pura. Si esto y `config._default_log_dir()` se
    separaran, lo peor que pasa es que el almacen viva en otro directorio: no comparten fichero.
    """
    if sys.platform == "win32":
        raiz = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin":
        raiz = os.path.expanduser("~/Library/Application Support")
    else:
        raiz = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(raiz) / APP


def ruta_por_defecto() -> Path:
    """`LD_HOOK_OUTPUT_STATS` si esta puesta; si no, el directorio de datos del usuario."""
    puesta = os.environ.get("LD_HOOK_OUTPUT_STATS", "").strip()
    return Path(puesta) if puesta else _directorio_de_datos() / FICHERO


def umbral_bytes() -> int:
    """`LD_HOOK_OUTPUT_UMBRAL_KB` en bytes."""
    return int(max(_numero("LD_HOOK_OUTPUT_UMBRAL_KB", UMBRAL_KB_POR_DEFECTO), 0) * 1024)


def _numero(nombre: str, default: float) -> float:
    """Un valor ilegible cae al default en vez de reventar: esto corre dentro de un comando."""
    try:
        return float(os.environ.get(nombre, "") or default)
    except ValueError:
        return default


def umbrales() -> Umbrales:
    """Los umbrales de decision, leidos del entorno.

    Se leen aqui y no en `output_policy` porque aquel es puro a proposito: si tocara el entorno,
    el replay que tiene que medir el criterio no podria fijar los valores desde fuera.
    """
    return Umbrales(
        minimo_muestras=int(_numero("LD_HOOK_OUTPUT_MIN_MUESTRAS", MIN_MUESTRAS_POR_DEFECTO)),
        proporcion=_numero("LD_HOOK_OUTPUT_PROPORCION", PROPORCION_POR_DEFECTO),
    )


def cargar(ruta: Path | None = None) -> dict[str, list[list[int]]]:
    """Las muestras por ejecutable. Un almacen ausente o corrupto da `{}`, nunca una excepcion.

    Un hook corre dentro de la operacion del usuario: aqui perder el aprendizaje es preferible a
    romperle el comando por un fichero mal escrito.
    """
    destino = ruta or ruta_por_defecto()
    try:
        crudo = json.loads(Path(destino).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(crudo, dict) or crudo.get("version") != VERSION:
        return {}
    ejecutables = crudo.get("ejecutables")
    if not isinstance(ejecutables, dict):
        return {}
    limpio: dict[str, list[list[int]]] = {}
    for nombre, muestras in ejecutables.items():
        if not nombre or not isinstance(nombre, str) or not isinstance(muestras, list):
            continue
        buenas = [m for m in muestras if isinstance(m, list) and len(m) == 2]
        if buenas:
            limpio[nombre] = buenas[-MUESTRAS_POR_EJECUTABLE:]
    return limpio


def _guardar(datos: dict[str, list[list[int]]], destino: Path) -> None:
    """Escritura atomica: fichero temporal en el mismo directorio y `os.replace`.

    Dos hooks a la vez pueden pisarse y perder una muestra —el que escriba ultimo gana—, y se
    asume: esto es estadistica de ventana, no contabilidad. Lo que NO puede pasar es que alguien
    lea un fichero a medio escribir, y de eso si protege el `replace`.
    """
    payload = {"version": VERSION, "ejecutables": datos}
    destino.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(dir=str(destino.parent), suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        os.replace(temporal, destino)
    except OSError:
        # La escritura fallo (disco lleno, permisos, el destino en un volumen distinto). Se
        # intenta no dejar el temporal tirado, y si ni eso se puede, se deja: un `.tmp` huerfano
        # en el directorio de datos es preferible a romperle el comando al usuario por no poder
        # limpiar. El almacen anterior sigue intacto, porque `os.replace` no llego a correr.
        try:
            os.unlink(temporal)
        except OSError:
            pass


def registrar(
    ejecutable: str,
    tamano: int,
    truncada: bool = False,
    *,
    ruta: Path | None = None,
) -> None:
    """Anota una ejecucion. Silencioso por contrato: nunca imprime ni propaga.

    `ejecutable` tiene que venir ya normalizado por `output_policy`: aqui no se vuelve a mirar el
    comando, entre otras cosas porque el comando no llega hasta aqui.
    """
    if not ejecutable:
        return
    destino = Path(ruta or ruta_por_defecto())
    datos = cargar(destino)
    muestras = datos.setdefault(ejecutable, [])
    muestras.append([max(int(tamano), 0), 1 if truncada else 0])
    datos[ejecutable] = muestras[-MUESTRAS_POR_EJECUTABLE:]
    if len(datos) > MAX_EJECUTABLES:
        # El actual se excluye del desalojo, y no por cortesia: acaba de estrenarse, asi que es
        # siempre el que menos muestras tiene y seria siempre el elegido — con lo que el tope no
        # desalojaria nunca a nadie y el fichero crecerria igual.
        otros = [nombre for nombre in datos if nombre != ejecutable]
        if otros:
            del datos[min(otros, key=lambda nombre: len(datos[nombre]))]
    try:
        _guardar(datos, destino)
    except OSError:
        # `_guardar` se traga sus propios fallos de escritura, pero el `mkdir` y el `mkstemp`
        # que lo preceden pueden reventar por su cuenta (ruta invalida en la variable de
        # entorno, directorio de solo lectura). Aqui el aprendizaje es best-effort por
        # contrato: perder una muestra no puede costarle al usuario el comando que estaba
        # ejecutando.
        pass


def estadistica(
    ejecutable: str,
    *,
    ruta: Path | None = None,
    umbral: int | None = None,
    datos: dict[str, list[list[int]]] | None = None,
) -> Estadistica:
    """Lo que `output_policy.es_candidato()` necesita saber de este ejecutable.

    `datos` permite pasar el almacen ya cargado: en un replay de miles de comandos, releer el
    fichero en cada vuelta es lo que hace la diferencia entre medir y esperar.
    """
    tabla = cargar(ruta) if datos is None else datos
    muestras = tabla.get(ejecutable) or []
    if not muestras:
        return Estadistica()
    tope = umbral_bytes() if umbral is None else umbral
    grandes = sum(1 for tamano, _truncada in muestras if tamano >= tope)
    truncadas = sum(1 for _tamano, truncada in muestras if truncada)
    return Estadistica(muestras=len(muestras), grandes=grandes, truncadas=truncadas)
