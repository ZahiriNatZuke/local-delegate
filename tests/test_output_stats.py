"""El almacén de lo que esta máquina ha observado del tamaño de salida de cada ejecutable.

Es la mitad que evita que el criterio quede calibrado al perfil del autor, que es exactamente el
defecto que hundió al hook anterior: su regex se ajustó a lo que se usa aquí y acertaba el 0,3 %.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stats = _load("output_stats")
policy = _load("output_policy")

KB = 1024


def test_registra_y_devuelve_lo_que_la_decision_necesita(tmp_path):
    almacen = tmp_path / "stats.json"
    for tamano in (20 * KB, 30 * KB, 100, 200, 50 * KB):
        stats.registrar("make", tamano, ruta=almacen)

    dato = stats.estadistica("make", ruta=almacen, umbral=8 * KB)
    assert dato.muestras == 5
    assert dato.grandes == 3
    assert dato.truncadas == 0
    # Y encaja con lo que consume la decisión, que es el único motivo de que exista.
    assert policy.es_candidato("make", dato) is True


def test_una_salida_truncada_se_anota_como_tal(tmp_path):
    almacen = tmp_path / "stats.json"
    stats.registrar("cargo", 90 * KB, truncada=True, ruta=almacen)
    stats.registrar("cargo", 10, truncada=False, ruta=almacen)

    dato = stats.estadistica("cargo", ruta=almacen, umbral=8 * KB)
    assert (dato.muestras, dato.grandes, dato.truncadas) == (2, 1, 1)


def test_el_almacen_no_guarda_comandos_ni_argumentos_ni_rutas(tmp_path):
    """REQ-015: la misma política que la telemetría de uso. Lo que no se guarda no se filtra."""
    almacen = tmp_path / "stats.json"
    stats.registrar("npm", 40 * KB, ruta=almacen)

    crudo = almacen.read_text(encoding="utf-8")
    assert "npm" in crudo  # el ejecutable normalizado sí
    for prohibido in ("/home", "C:\\", "--", "run build", "tmp"):
        assert prohibido not in crudo, prohibido


def test_solo_se_guardan_las_ultimas_muestras(tmp_path):
    """La ventana acota el fichero y hace que el criterio se adapte a un proyecto nuevo."""
    almacen = tmp_path / "stats.json"
    for i in range(stats.MUESTRAS_POR_EJECUTABLE + 15):
        stats.registrar("go", i, ruta=almacen)

    guardadas = json.loads(almacen.read_text(encoding="utf-8"))["ejecutables"]["go"]
    assert len(guardadas) == stats.MUESTRAS_POR_EJECUTABLE
    # Las últimas, no las primeras: si se quedara con las viejas, nunca aprendería nada nuevo.
    assert guardadas[-1][0] == stats.MUESTRAS_POR_EJECUTABLE + 14


def test_se_guardan_tamanos_y_no_un_grande_si_o_no(tmp_path):
    """Para que el replay pueda recalcular con otro umbral sin volver a recoger nada.

    El umbral bueno lo fija esa medición, así que un almacén que guardara el veredicto en vez del
    dato obligaría a tirar el corpus cada vez que se cambia el umbral.
    """
    almacen = tmp_path / "stats.json"
    stats.registrar("pytest", 12 * KB, ruta=almacen)

    con_umbral_bajo = stats.estadistica("pytest", ruta=almacen, umbral=8 * KB)
    con_umbral_alto = stats.estadistica("pytest", ruta=almacen, umbral=100 * KB)
    assert con_umbral_bajo.grandes == 1
    assert con_umbral_alto.grandes == 0


def test_el_aprendizaje_funciona_con_la_telemetria_apagada(tmp_path, monkeypatch):
    """REQ-021: el almacén tiene ubicación propia y no cuelga de la telemetría.

    La telemetría es opt-in y está vacía en la mayoría de máquinas. Si el aprendizaje dependiera
    de ella sería un no-op casi siempre — y ningún test lo vería, porque los tests la encienden.
    Aquí se apaga explícitamente, que es la única forma de que este test signifique algo.
    """
    monkeypatch.delenv("LD_HOOK_TELEMETRY_LOG", raising=False)
    almacen = tmp_path / "stats.json"

    stats.registrar("gradle", 60 * KB, ruta=almacen)

    assert almacen.exists()
    assert stats.estadistica("gradle", ruta=almacen, umbral=8 * KB).grandes == 1


def test_un_almacen_ausente_no_es_un_error(tmp_path):
    vacio = stats.estadistica("nunca-visto", ruta=tmp_path / "no-existe.json")
    assert vacio == policy.Estadistica()
    assert stats.cargar(tmp_path / "no-existe.json") == {}


def test_un_almacen_corrupto_se_ignora_en_vez_de_romper_el_comando(tmp_path):
    """Un hook corre dentro de la operación del usuario: perder el aprendizaje es preferible."""
    for basura in ("{no es json", "[]", '{"version": 99, "ejecutables": {}}', ""):
        almacen = tmp_path / "roto.json"
        almacen.write_text(basura, encoding="utf-8")
        assert stats.cargar(almacen) == {}, basura
        # Y se puede seguir escribiendo encima: el fichero malo no deja el almacén inservible.
        stats.registrar("make", 9 * KB, ruta=almacen)
        assert stats.estadistica("make", ruta=almacen, umbral=8 * KB).muestras == 1


def test_las_muestras_con_forma_rara_se_descartan_una_a_una(tmp_path):
    """Media línea corrupta no tira el resto: se conserva lo que sí se entiende."""
    almacen = tmp_path / "mixto.json"
    almacen.write_text(
        json.dumps(
            {
                "version": stats.VERSION,
                # Una clave vacía y muestras con forma rara. No se prueba una clave no-string
                # porque JSON no las tiene: sería un caso que no puede darse.
                "ejecutables": {"make": [[100, 0], "basura", [200, 1], [3]], "": [[1, 0]]},
            }
        ),
        encoding="utf-8",
    )
    assert stats.cargar(almacen) == {"make": [[100, 0], [200, 1]]}


def test_el_numero_de_ejecutables_esta_acotado(tmp_path, monkeypatch):
    """Para que un fichero de estadísticas no crezca sin final."""
    monkeypatch.setattr(stats, "MAX_EJECUTABLES", 3)
    almacen = tmp_path / "stats.json"
    for nombre in ("a", "b", "c"):
        stats.registrar(nombre, 100, ruta=almacen)
        stats.registrar(nombre, 100, ruta=almacen)
    stats.registrar("recien-llegado", 100, ruta=almacen)

    guardados = stats.cargar(almacen)
    assert len(guardados) == 3
    assert "recien-llegado" in guardados, "el que acaba de verse no puede ser el que se tire"


def test_la_ruta_del_almacen_es_inyectable_y_por_defecto_va_al_directorio_de_datos(monkeypatch):
    """Sin inyección, el replay que mide el criterio no se puede aislar del almacén real."""
    monkeypatch.setenv("LD_HOOK_OUTPUT_STATS", "/un/sitio/mio.json")
    assert stats.ruta_por_defecto() == Path("/un/sitio/mio.json")

    monkeypatch.delenv("LD_HOOK_OUTPUT_STATS", raising=False)
    por_defecto = stats.ruta_por_defecto()
    assert por_defecto.name == stats.FICHERO
    assert por_defecto.parent.name == stats.APP


def test_el_umbral_se_lee_del_entorno_y_un_valor_ilegible_no_revienta(monkeypatch):
    monkeypatch.setenv("LD_HOOK_OUTPUT_UMBRAL_KB", "32")
    assert stats.umbral_bytes() == 32 * KB

    monkeypatch.setenv("LD_HOOK_OUTPUT_UMBRAL_KB", "no soy un numero")
    assert stats.umbral_bytes() == int(stats.UMBRAL_KB_POR_DEFECTO * KB)


def test_los_umbrales_de_decision_se_leen_del_entorno(monkeypatch):
    """Se leen aquí y no en `output_policy` porque aquel es puro: si tocara el entorno, el replay
    no podría fijar los valores desde fuera para medir el criterio."""
    monkeypatch.setenv("LD_HOOK_OUTPUT_MIN_MUESTRAS", "12")
    monkeypatch.setenv("LD_HOOK_OUTPUT_PROPORCION", "0.8")
    leidos = stats.umbrales()
    assert (leidos.minimo_muestras, leidos.proporcion) == (12, 0.8)

    monkeypatch.setenv("LD_HOOK_OUTPUT_PROPORCION", "no soy un numero")
    assert stats.umbrales().proporcion == stats.PROPORCION_POR_DEFECTO

    monkeypatch.delenv("LD_HOOK_OUTPUT_MIN_MUESTRAS", raising=False)
    monkeypatch.delenv("LD_HOOK_OUTPUT_PROPORCION", raising=False)
    assert stats.umbrales() == policy.Umbrales(
        minimo_muestras=stats.MIN_MUESTRAS_POR_DEFECTO,
        proporcion=stats.PROPORCION_POR_DEFECTO,
    )


def test_registrar_sin_ejecutable_no_escribe_nada(tmp_path):
    almacen = tmp_path / "stats.json"
    stats.registrar("", 90 * KB, ruta=almacen)
    assert not almacen.exists()
