"""Tarea 26 de F3: el estado de enfriamiento compartido entre procesos (REQ-009 a REQ-012).

Todo con reloj inyectable: ningún test espera de verdad 120 s. «Dos procesos» son dos instancias de
`Estado` sobre el mismo fichero, que es lo que ven el daemon y un proceso stdio de la misma máquina.

Defectos de la spec que se fijan aquí, no se reinterpretan en cada consumidor:
- cuentan solo los fallos del modelo y los timeouts con el modelo cargado (tabla de F3);
- capacidad y configuración son neutras como el endpoint, la petición y lo sin clasificar: ni suman
  ni ponen a cero (decisión del plan, tarea 26);
- tras vencer, basta UN fallo para volver a enfriar, con la espera doblada y tope en Tmax (REQ-010).
"""

from __future__ import annotations

import json

import pytest

from local_delegate import enfriamiento
from local_delegate.fallos import Clase

INICIO = 1_800_000_000.0


class Reloj:
    def __init__(self) -> None:
        self.ahora = INICIO

    def __call__(self) -> float:
        return self.ahora

    def avanzar(self, segundos: float) -> None:
        self.ahora += segundos


@pytest.fixture
def reloj() -> Reloj:
    return Reloj()


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "enfriamiento.json"


def _estado(ruta, reloj, **opciones) -> enfriamiento.Estado:
    parametros = {"fallos": 3, "espera_s": 120.0, "espera_max_s": 900.0, "activo": True}
    parametros.update(opciones)
    return enfriamiento.Estado(ruta, reloj=reloj, **parametros)


def _fallar(estado: enfriamiento.Estado, modelo: str, veces: int, clase=Clase.MODELO) -> None:
    for _ in range(veces):
        estado.registrar_fallo(modelo, clase)


# --- REQ-009: N fallos seguidos enfrían -------------------------------------------------------


def test_tres_fallos_seguidos_enfrian_el_modelo_120_s(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    enfriado = estado.consultar("m")
    assert enfriado is not None
    assert enfriado.restante_s == pytest.approx(120.0)
    assert enfriado.reentradas == 1


def test_dos_fallos_no_enfrian(ruta, reloj):
    """Control positivo del anterior: el umbral es N, no «cualquier fallo»."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    assert estado.consultar("m") is None


def test_los_fallos_de_dos_procesos_se_suman(ruta, reloj):
    """REQ-009 y REQ-012: el daemon y un proceso stdio ven el mismo contador."""
    daemon = _estado(ruta, reloj)
    stdio = _estado(ruta, reloj)
    _fallar(daemon, "m", 2)
    _fallar(stdio, "m", 1)
    assert daemon.consultar("m") is not None
    assert stdio.consultar("m") is not None


def test_el_timeout_con_el_modelo_cargado_tambien_cuenta(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3, clase=Clase.TIMEOUT_LECTURA)
    assert estado.consultar("m") is not None


def test_cada_modelo_lleva_su_propio_contador(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "a", 2)
    _fallar(estado, "b", 2)
    assert estado.consultar("a") is None
    assert estado.consultar("b") is None


# --- REQ-011: el éxito pone a cero y las clases neutras no tocan nada ---------------------------


def test_un_exito_pone_el_contador_a_cero(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    estado.registrar_exito("m")
    _fallar(estado, "m", 2)
    assert estado.consultar("m") is None


@pytest.mark.parametrize(
    "neutra",
    [Clase.ENDPOINT, Clase.PETICION, Clase.SIN_CLASIFICAR, Clase.CAPACIDAD, Clase.CONFIGURACION],
)
def test_las_clases_neutras_ni_suman_ni_ponen_a_cero(ruta, reloj, neutra):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    _fallar(estado, "m", 5, clase=neutra)  # no suman...
    assert estado.consultar("m") is None
    _fallar(estado, "m", 1)  # ...ni han puesto a cero: este es el tercero que cuenta
    assert estado.consultar("m") is not None


# --- REQ-010: vencimiento, prueba y espera doblada ----------------------------------------------


def test_vencido_el_enfriamiento_el_modelo_vuelve_a_recibir(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(120.1)
    assert estado.consultar("m") is None


def test_vencido_y_un_exito_el_modelo_queda_limpio(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    estado.registrar_exito("m")
    assert estado.activos() == {}
    _fallar(estado, "m", 2)
    assert estado.consultar("m") is None, "el contador no volvió a cero"
    _fallar(estado, "m", 1)
    assert estado.consultar("m").restante_s == pytest.approx(120.0), "la espera no volvió a la base"


def test_vencido_y_un_solo_fallo_vuelve_a_enfriar_con_la_espera_doblada(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    _fallar(estado, "m", 1)
    enfriado = estado.consultar("m")
    assert enfriado is not None, "tras vencer tiene que bastar UN fallo"
    assert enfriado.restante_s == pytest.approx(240.0)
    assert enfriado.reentradas == 2


def test_la_espera_nunca_pasa_de_tmax(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    esperas = []
    for _ in range(8):
        reloj.avanzar(1000)
        _fallar(estado, "m", 1)
        esperas.append(estado.consultar("m").restante_s)
    assert esperas[:3] == [pytest.approx(240.0), pytest.approx(480.0), pytest.approx(900.0)]
    assert max(esperas) == pytest.approx(900.0)
    # Lo que de verdad importa del tope: pasados Tmax segundos, el modelo QUEDA LIBRE. Mirar solo el
    # restante no basta: la lectura lo recorta y tapaba una espera guardada sin límite (mutante vivo).
    reloj.avanzar(900.1)
    assert estado.consultar("m") is None, "pasado Tmax el modelo sigue enfriado"


def test_la_espera_guardada_tampoco_pasa_de_tmax(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    for _ in range(8):
        reloj.avanzar(1000)
        _fallar(estado, "m", 1)
    entrada = json.loads(ruta.read_text(encoding="utf-8"))["m"]
    assert entrada["espera_s"] <= 900.0
    assert entrada["hasta"] - reloj.ahora <= 900.0


def test_un_vencimiento_en_el_futuro_lejano_se_recorta_a_tmax(ruta, reloj):
    """Un cambio de hora puede dejar un `hasta` absurdo: ningún enfriamiento es permanente."""
    ruta.write_text(
        json.dumps(
            {"m": {"fallos": 0, "espera_s": 120.0, "hasta": INICIO + 10**7, "reentradas": 1}}
        ),
        encoding="utf-8",
    )
    estado = _estado(ruta, reloj)
    enfriado = estado.consultar("m")
    assert enfriado is not None
    assert enfriado.restante_s <= 900.0
    # Y VENCE: recortar contra «ahora» en cada lectura dejaba siempre 900 s por delante, o sea un
    # enfriamiento permanente, justo lo que la spec prohíbe.
    reloj.avanzar(900.1)
    assert estado.consultar("m") is None, "el vencimiento lejano no vence nunca"


# --- REQ-012: el estado ilegible nunca bloquea ni falla -----------------------------------------


def test_un_fichero_corrupto_se_lee_como_sin_enfriamiento(ruta, reloj):
    ruta.write_text("{esto no es json", encoding="utf-8")
    estado = _estado(ruta, reloj)
    assert estado.consultar("m") is None
    _fallar(estado, "m", 3)  # no lanza
    assert estado.consultar("m") is not None, "tras un fichero corrupto se vuelve a escribir bien"


def test_un_bloqueo_ocupado_no_bloquea_ni_falla(ruta, reloj, monkeypatch):
    class BloqueoOcupado:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            raise enfriamiento.Timeout(str(ruta))

        def __exit__(self, *_exc) -> None:
            return None

    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    monkeypatch.setattr(enfriamiento, "FileLock", BloqueoOcupado)
    assert estado.consultar("m") is None, "sin el bloqueo se sigue como si no hubiera enfriamiento"
    _fallar(estado, "otro", 3)  # no lanza


def test_el_fichero_solo_guarda_contadores_y_fechas(ruta, reloj):
    """Privacidad (spec, no funcionales): nombres de modelo, contadores y fechas; nunca contenido."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    _fallar(estado, "n", 1)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert set(datos) == {"m", "n"}
    for entrada in datos.values():
        assert set(entrada) == {"fallos", "espera_s", "hasta", "reentradas"}
        assert all(valor is None or isinstance(valor, (int, float)) for valor in entrada.values())


# --- REQ-014: apagado ---------------------------------------------------------------------------


def test_apagado_no_registra_ni_enfria(ruta, reloj):
    estado = _estado(ruta, reloj, activo=False)
    _fallar(estado, "m", 10)
    assert estado.consultar("m") is None
    assert not ruta.exists(), "apagado no debe ni tocar el fichero"
    assert not (ruta.parent / enfriamiento.FICHERO_EVENTOS).exists(), "ni el de episodios"


# --- Tarea 30: los episodios, que el criterio de P-4 cuenta y el fichero de estado no guarda -----


def _eventos(ruta) -> list[dict]:
    destino = ruta.parent / enfriamiento.FICHERO_EVENTOS
    if not destino.exists():
        return []
    return [json.loads(linea) for linea in destino.read_text(encoding="utf-8").splitlines()]


def test_entrar_deja_un_evento_con_la_clase_que_lo_disparo(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    assert _eventos(ruta) == [], "un fallo por debajo de N no es un episodio"
    _fallar(estado, "m", 1, clase=Clase.TIMEOUT_LECTURA)
    (evento,) = _eventos(ruta)
    assert evento["evento"] == "entra"
    assert evento["modelo"] == "m"
    assert evento["clase"] == "timeout_lectura"
    assert evento["reentradas"] == 1
    assert evento["espera_s"] == pytest.approx(120.0)
    assert evento["ts"].startswith("2027-01-15T08:00:00")


def test_reentrar_tras_vencer_deja_su_evento_con_la_espera_doblada(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    _fallar(estado, "m", 1)
    assert [e["evento"] for e in _eventos(ruta)] == ["entra", "reentra"]
    reentra = _eventos(ruta)[1]
    assert reentra["reentradas"] == 2
    assert reentra["espera_s"] == pytest.approx(240.0)


def test_los_fallos_durante_el_enfriamiento_no_dejan_evento(ruta, reloj):
    """Solo le llegan llamadas con `model` explicito (REQ-005): no abren ni alargan un episodio."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    _fallar(estado, "m", 4)
    assert [e["evento"] for e in _eventos(ruta)] == ["entra"]


def test_el_exito_tras_vencer_cierra_el_episodio_como_recuperado(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    estado.registrar_exito("m")
    limpia = _eventos(ruta)[-1]
    assert limpia["evento"] == "limpia"
    assert limpia["tras_vencer"] is True
    assert limpia["reentradas"] == 1


def test_el_exito_antes_de_vencer_se_distingue(ruta, reloj):
    """Un exito durante el enfriamiento solo puede venir de `model` explicito: no es una prueba
    tras vencer, y el criterio no debe contarlo como recuperacion."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(10)
    estado.registrar_exito("m")
    assert _eventos(ruta)[-1]["tras_vencer"] is False


def test_el_exito_de_un_modelo_con_fallos_sueltos_no_es_un_episodio(ruta, reloj):
    """Control positivo de los dos anteriores: limpiar un contador no es cerrar un enfriamiento."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    estado.registrar_exito("m")
    estado.registrar_exito("otro")
    assert _eventos(ruta) == []


def test_los_eventos_de_dos_procesos_van_al_mismo_fichero(ruta, reloj):
    daemon = _estado(ruta, reloj)
    stdio = _estado(ruta, reloj)
    _fallar(daemon, "m", 2)
    _fallar(stdio, "m", 1)
    reloj.avanzar(121)
    daemon.registrar_exito("m")
    assert [e["evento"] for e in _eventos(ruta)] == ["entra", "limpia"]


def test_el_fichero_de_episodios_solo_guarda_nombres_contadores_y_fechas(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    _fallar(estado, "m", 1)
    reloj.avanzar(241)
    estado.registrar_exito("m")
    permitidas = {"ts", "modelo", "evento", "clase", "reentradas", "espera_s", "tras_vencer"}
    eventos = _eventos(ruta)
    assert len(eventos) == 3
    for evento in eventos:
        assert set(evento) <= permitidas
        assert evento["evento"] in {"entra", "reentra", "limpia"}


def test_sin_disco_para_los_episodios_el_enfriamiento_sigue(ruta, reloj, monkeypatch):
    """REQ-012 tambien para el registro: que no se pueda escribir no hace fallar ni deshace nada."""

    def sin_disco(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(enfriamiento, "_anadir_lineas", sin_disco)
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)  # no lanza
    assert estado.consultar("m") is not None
