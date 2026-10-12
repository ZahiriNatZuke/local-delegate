"""Tarea 26 de F3: el estado de enfriamiento compartido entre procesos (REQ-009 a REQ-012).

Todo con reloj inyectable: ningún test espera de verdad 120 s. «Dos procesos» son dos instancias de
`CooldownState` sobre el mismo fichero, que es lo que ven el daemon y un proceso stdio de la misma máquina.

Defectos de la spec que se fijan aquí, no se reinterpretan en cada consumidor:
- cuentan solo los fallos del modelo y los timeouts con el modelo cargado (tabla de F3);
- capacidad y configuración son neutras como el endpoint, la petición y lo sin clasificar: ni suman
  ni ponen a cero (decisión del plan, tarea 26);
- tras vencer, basta UN fallo para volver a enfriar, con la espera doblada y tope en Tmax (REQ-010).
"""

from __future__ import annotations

import json

import pytest

from local_delegate import cooldown
from local_delegate.failures import FailureClass

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
    return tmp_path / "cooldown.json"


def _estado(ruta, reloj, **opciones) -> cooldown.CooldownState:
    parametros = {"failures": 3, "wait_s": 120.0, "max_wait_s": 900.0, "enabled": True}
    parametros.update(opciones)
    return cooldown.CooldownState(ruta, clock=reloj, **parametros)


def _fallar(
    estado: cooldown.CooldownState, modelo: str, veces: int, clase=FailureClass.MODEL
) -> None:
    for _ in range(veces):
        estado.record_failure(modelo, clase)


# --- REQ-009: N fallos seguidos enfrían -------------------------------------------------------


def test_tres_fallos_seguidos_enfrian_el_modelo_120_s(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    enfriado = estado.lookup("m")
    assert enfriado is not None
    assert enfriado.remaining_s == pytest.approx(120.0)
    assert enfriado.reentries == 1


def test_dos_fallos_no_enfrian(ruta, reloj):
    """Control positivo del anterior: el umbral es N, no «cualquier fallo»."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    assert estado.lookup("m") is None


def test_los_fallos_de_dos_procesos_se_suman(ruta, reloj):
    """REQ-009 y REQ-012: el daemon y un proceso stdio ven el mismo contador."""
    daemon = _estado(ruta, reloj)
    stdio = _estado(ruta, reloj)
    _fallar(daemon, "m", 2)
    _fallar(stdio, "m", 1)
    assert daemon.lookup("m") is not None
    assert stdio.lookup("m") is not None


def test_el_timeout_con_el_modelo_cargado_tambien_cuenta(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3, clase=FailureClass.READ_TIMEOUT)
    assert estado.lookup("m") is not None


def test_cada_modelo_lleva_su_propio_contador(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "a", 2)
    _fallar(estado, "b", 2)
    assert estado.lookup("a") is None
    assert estado.lookup("b") is None


# --- REQ-011: el éxito pone a cero y las clases neutras no tocan nada ---------------------------


def test_un_exito_pone_el_contador_a_cero(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    estado.record_success("m")
    _fallar(estado, "m", 2)
    assert estado.lookup("m") is None


@pytest.mark.parametrize(
    "neutra",
    [
        FailureClass.ENDPOINT,
        FailureClass.REQUEST,
        FailureClass.UNCLASSIFIED,
        FailureClass.CAPACITY,
        FailureClass.CONFIGURATION,
    ],
)
def test_las_clases_neutras_ni_suman_ni_ponen_a_cero(ruta, reloj, neutra):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    _fallar(estado, "m", 5, clase=neutra)  # no suman...
    assert estado.lookup("m") is None
    _fallar(estado, "m", 1)  # ...ni han puesto a cero: este es el tercero que cuenta
    assert estado.lookup("m") is not None


# --- REQ-010: vencimiento, prueba y espera doblada ----------------------------------------------


def test_vencido_el_enfriamiento_el_modelo_vuelve_a_recibir(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(120.1)
    assert estado.lookup("m") is None


def test_vencido_y_un_exito_el_modelo_queda_limpio(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    estado.record_success("m")
    assert estado.active() == {}
    _fallar(estado, "m", 2)
    assert estado.lookup("m") is None, "el contador no volvió a cero"
    _fallar(estado, "m", 1)
    assert estado.lookup("m").remaining_s == pytest.approx(120.0), "la espera no volvió a la base"


def test_vencido_y_un_solo_fallo_vuelve_a_enfriar_con_la_espera_doblada(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    _fallar(estado, "m", 1)
    enfriado = estado.lookup("m")
    assert enfriado is not None, "tras vencer tiene que bastar UN fallo"
    assert enfriado.remaining_s == pytest.approx(240.0)
    assert enfriado.reentries == 2


def test_la_espera_nunca_pasa_de_tmax(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    esperas = []
    for _ in range(8):
        reloj.avanzar(1000)
        _fallar(estado, "m", 1)
        esperas.append(estado.lookup("m").remaining_s)
    assert esperas[:3] == [pytest.approx(240.0), pytest.approx(480.0), pytest.approx(900.0)]
    assert max(esperas) == pytest.approx(900.0)
    # Lo que de verdad importa del tope: pasados Tmax segundos, el modelo QUEDA LIBRE. Mirar solo el
    # restante no basta: la lectura lo recorta y tapaba una espera guardada sin límite (mutante vivo).
    reloj.avanzar(900.1)
    assert estado.lookup("m") is None, "pasado Tmax el modelo sigue enfriado"


def test_la_espera_guardada_tampoco_pasa_de_tmax(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    for _ in range(8):
        reloj.avanzar(1000)
        _fallar(estado, "m", 1)
    entrada = json.loads(ruta.read_text(encoding="utf-8"))["m"]
    assert entrada["wait_s"] <= 900.0
    assert entrada["until"] - reloj.ahora <= 900.0


def test_un_vencimiento_en_el_futuro_lejano_se_recorta_a_tmax(ruta, reloj):
    """Un cambio de hora puede dejar un `until` absurdo: ningún enfriamiento es permanente."""
    ruta.write_text(
        json.dumps(
            {"m": {"failures": 0, "wait_s": 120.0, "until": INICIO + 10**7, "reentries": 1}}
        ),
        encoding="utf-8",
    )
    estado = _estado(ruta, reloj)
    enfriado = estado.lookup("m")
    assert enfriado is not None
    assert enfriado.remaining_s <= 900.0
    # Y VENCE: recortar contra «ahora» en cada lectura dejaba siempre 900 s por delante, o sea un
    # enfriamiento permanente, justo lo que la spec prohíbe.
    reloj.avanzar(900.1)
    assert estado.lookup("m") is None, "el vencimiento lejano no vence nunca"


# --- REQ-012: el estado ilegible nunca bloquea ni falla -----------------------------------------


def test_un_fichero_corrupto_se_lee_como_sin_enfriamiento(ruta, reloj):
    ruta.write_text("{esto no es json", encoding="utf-8")
    estado = _estado(ruta, reloj)
    assert estado.lookup("m") is None
    _fallar(estado, "m", 3)  # no lanza
    assert estado.lookup("m") is not None, "tras un fichero corrupto se vuelve a escribir bien"


def test_un_bloqueo_ocupado_no_bloquea_ni_falla(ruta, reloj, monkeypatch):
    class BloqueoOcupado:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            raise cooldown.Timeout(str(ruta))

        def __exit__(self, *_exc) -> None:
            return None

    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    monkeypatch.setattr(cooldown, "FileLock", BloqueoOcupado)
    assert estado.lookup("m") is None, "sin el bloqueo se sigue como si no hubiera enfriamiento"
    _fallar(estado, "otro", 3)  # no lanza


def test_el_fichero_solo_guarda_contadores_y_fechas(ruta, reloj):
    """Privacidad (spec, no funcionales): nombres de modelo, contadores y fechas; nunca contenido."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    _fallar(estado, "n", 1)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert set(datos) == {"m", "n"}
    for entrada in datos.values():
        assert set(entrada) == {"failures", "wait_s", "until", "reentries"}
        assert all(valor is None or isinstance(valor, (int, float)) for valor in entrada.values())


# --- REQ-014: apagado ---------------------------------------------------------------------------


def test_apagado_no_registra_ni_enfria(ruta, reloj):
    estado = _estado(ruta, reloj, enabled=False)
    _fallar(estado, "m", 10)
    assert estado.lookup("m") is None
    assert not ruta.exists(), "apagado no debe ni tocar el fichero"
    assert not (ruta.parent / cooldown.EVENTS_FILE).exists(), "ni el de episodios"


# --- Tarea 30: los episodios, que el criterio de P-4 cuenta y el fichero de estado no guarda -----


def _eventos(ruta) -> list[dict]:
    destino = ruta.parent / cooldown.EVENTS_FILE
    if not destino.exists():
        return []
    return [json.loads(linea) for linea in destino.read_text(encoding="utf-8").splitlines()]


def test_entrar_deja_un_evento_con_la_clase_que_lo_disparo(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    assert _eventos(ruta) == [], "un fallo por debajo de N no es un episodio"
    _fallar(estado, "m", 1, clase=FailureClass.READ_TIMEOUT)
    (evento,) = _eventos(ruta)
    assert evento["event"] == "enter"
    assert evento["model"] == "m"
    assert evento["class"] == "read_timeout"
    assert evento["reentries"] == 1
    assert evento["wait_s"] == pytest.approx(120.0)
    assert evento["ts"].startswith("2027-01-15T08:00:00")


def test_reentrar_tras_vencer_deja_su_evento_con_la_espera_doblada(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    _fallar(estado, "m", 1)
    assert [e["event"] for e in _eventos(ruta)] == ["enter", "reenter"]
    reentra = _eventos(ruta)[1]
    assert reentra["reentries"] == 2
    assert reentra["wait_s"] == pytest.approx(240.0)


def test_los_fallos_durante_el_enfriamiento_no_dejan_evento(ruta, reloj):
    """Solo le llegan llamadas con `model` explicito (REQ-005): no abren ni alargan un episodio."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    _fallar(estado, "m", 4)
    assert [e["event"] for e in _eventos(ruta)] == ["enter"]


def test_el_exito_tras_vencer_cierra_el_episodio_como_recuperado(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    estado.record_success("m")
    limpia = _eventos(ruta)[-1]
    assert limpia["event"] == "clear"
    assert limpia["after_expiry"] is True
    assert limpia["reentries"] == 1


def test_el_exito_antes_de_vencer_se_distingue(ruta, reloj):
    """Un exito durante el enfriamiento solo puede venir de `model` explicito: no es una prueba
    tras vencer, y el criterio no debe contarlo como recuperacion."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(10)
    estado.record_success("m")
    assert _eventos(ruta)[-1]["after_expiry"] is False


def test_el_exito_de_un_modelo_con_fallos_sueltos_no_es_un_episodio(ruta, reloj):
    """Control positivo de los dos anteriores: limpiar un contador no es cerrar un enfriamiento."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 2)
    estado.record_success("m")
    estado.record_success("otro")
    assert _eventos(ruta) == []


def test_los_eventos_de_dos_procesos_van_al_mismo_fichero(ruta, reloj):
    daemon = _estado(ruta, reloj)
    stdio = _estado(ruta, reloj)
    _fallar(daemon, "m", 2)
    _fallar(stdio, "m", 1)
    reloj.avanzar(121)
    daemon.record_success("m")
    assert [e["event"] for e in _eventos(ruta)] == ["enter", "clear"]


def test_el_fichero_de_episodios_solo_guarda_nombres_contadores_y_fechas(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    reloj.avanzar(121)
    _fallar(estado, "m", 1)
    reloj.avanzar(241)
    estado.record_success("m")
    permitidas = {"ts", "model", "event", "class", "reentries", "wait_s", "after_expiry"}
    eventos = _eventos(ruta)
    assert len(eventos) == 3
    for evento in eventos:
        assert set(evento) <= permitidas
        assert evento["event"] in {"enter", "reenter", "clear"}


def test_sin_disco_para_los_episodios_el_enfriamiento_sigue(ruta, reloj, monkeypatch):
    """REQ-012 tambien para el registro: que no se pueda escribir no hace fallar ni deshace nada."""

    def sin_disco(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(cooldown, "_append_lines", sin_disco)
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)  # no lanza
    assert estado.lookup("m") is not None


# --- Ola A4 del renombrado: `cooldown.json`, `enfriamiento.json` y su escritura doble -----------
#
# REQ-005 (excepción): mientras viva la entrada `legacy_write` de `deprecations`, el daemon escribe
# también `enfriamiento.json` con las claves viejas, para los hooks de una versión anterior.
# REQ-006: se lee `cooldown.json` y, si no existe, `enfriamiento.json` traducido; gana el nuevo.


def _viejo(ruta) -> dict:
    return json.loads(ruta.with_name("enfriamiento.json").read_text(encoding="utf-8"))


def _nuevo(ruta) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def _mismo_estado(ruta) -> None:
    """Los dos ficheros dicen lo mismo: el viejo, traducido, es igual al nuevo."""
    viejo = {modelo: cooldown._entry(entrada) for modelo, entrada in _viejo(ruta).items()}
    assert viejo == _nuevo(ruta)


def test_la_escritura_doble_deja_el_mismo_estado_tras_entrar_reentrar_y_limpiar(ruta, reloj):
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    assert _nuevo(ruta)["m"]["until"] is not None, "tras entrar"
    _mismo_estado(ruta)
    reloj.avanzar(121)
    _fallar(estado, "m", 1)
    assert _nuevo(ruta)["m"]["reentries"] == 2, "tras reentrar"
    _mismo_estado(ruta)
    reloj.avanzar(241)
    estado.record_success("m")
    assert _nuevo(ruta) == {}, "tras limpiar"
    _mismo_estado(ruta)
    assert [e["event"] for e in _eventos(ruta)] == ["enter", "reenter", "clear"]


def test_el_fichero_viejo_lleva_las_claves_viejas_que_lee_un_hook_anterior(ruta, reloj):
    """Un hook de la 0.34.0 lee `data[modelo]["hasta"]` de `enfriamiento.json`."""
    estado = _estado(ruta, reloj)
    _fallar(estado, "m", 3)
    entrada = _viejo(ruta)["m"]
    assert set(entrada) == {"fallos", "espera_s", "hasta", "reentradas"}
    assert entrada["hasta"] == pytest.approx(INICIO + 120.0)


def test_un_estado_viejo_de_un_daemon_anterior_se_lee_si_no_hay_nuevo(ruta, reloj):
    ruta.with_name("enfriamiento.json").write_text(
        json.dumps({"m": {"fallos": 0, "espera_s": 120.0, "hasta": INICIO + 60, "reentradas": 1}}),
        encoding="utf-8",
    )
    estado = _estado(ruta, reloj)
    enfriado = estado.lookup("m")
    assert enfriado is not None, "el estado viejo no se leyó"
    assert enfriado.remaining_s == pytest.approx(60.0)
    # Y la siguiente escritura parte de él: el nuevo nace con el modelo enfriado, en claves nuevas.
    _fallar(estado, "n", 1)
    assert _nuevo(ruta)["m"]["until"] == pytest.approx(INICIO + 60)
    assert set(_nuevo(ruta)["m"]) == {"failures", "wait_s", "until", "reentries"}


def test_con_los_dos_ficheros_gana_el_nuevo(ruta, reloj):
    ruta.with_name("enfriamiento.json").write_text(
        json.dumps({"m": {"fallos": 0, "espera_s": 120.0, "hasta": INICIO + 60, "reentradas": 1}}),
        encoding="utf-8",
    )
    ruta.write_text("{}", encoding="utf-8")
    assert _estado(ruta, reloj).lookup("m") is None


def test_sin_su_entrada_legacy_write_no_se_escribe_el_fichero_viejo(ruta, reloj, monkeypatch):
    """La excepción tiene horizonte: al retirar la entrada del registro, deja de escribirse."""
    from local_delegate import deprecations

    assert cooldown.legacy_write_enabled()
    sin_ella = tuple(e for e in deprecations.DEPRECATED_NAMES if e.kind != "legacy_write")
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", sin_ella)
    assert not cooldown.legacy_write_enabled()
    _fallar(_estado(ruta, reloj), "m", 3)
    assert ruta.exists()
    assert not ruta.with_name("enfriamiento.json").exists()


def test_from_config_escribe_cooldown_json_y_el_registro_nuevo(tmp_path, monkeypatch):
    from local_delegate import config

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "COOLDOWN", True)
    monkeypatch.setattr(config, "COOLDOWN_FAILURES", 1)
    cooldown.from_config().record_failure("m", FailureClass.MODEL)
    assert (tmp_path / "cooldown.json").exists()
    assert (tmp_path / "enfriamiento.json").exists()
    assert (tmp_path / "cooldown-events.jsonl").exists()
    assert not (tmp_path / "enfriamiento-eventos.jsonl").exists()


# --- La copia de los hooks: lee los dos ficheros (gana `cooldown.json`) --------------------------


@pytest.fixture
def hook(tmp_path, monkeypatch):
    from local_delegate.resources.hooks import hook_common

    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path))
    return hook_common


def _escribir(ruta, datos: dict) -> None:
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def test_el_hook_nuevo_ve_el_modelo_enfriado_por_un_daemon_viejo(hook, tmp_path):
    import time

    _escribir(tmp_path / "enfriamiento.json", {"m": {"hasta": time.time() + 60}})
    assert hook.cooled_model("m")


def test_el_hook_nuevo_lee_cooldown_json_y_ahi_gana_el_nuevo(hook, tmp_path):
    import time

    _escribir(tmp_path / "cooldown.json", {"m": {"until": time.time() + 60}})
    assert hook.cooled_model("m")
    _escribir(tmp_path / "enfriamiento.json", {"n": {"hasta": time.time() + 60}})
    assert not hook.cooled_model("n"), "con cooldown.json presente no se mira el viejo"


def test_el_hook_lee_lo_que_escribe_el_daemon(hook, tmp_path, reloj):
    import time

    reloj.ahora = time.time()
    _fallar(_estado(tmp_path / "cooldown.json", reloj), "m", 3)
    assert hook.cooled_model("m")
    assert not hook.cooled_model("otro")


def test_la_tabla_de_claves_del_hook_es_la_del_paquete():
    from local_delegate import legacy_names
    from local_delegate.resources.hooks import hook_common

    assert hook_common.COOLDOWN_STATE_KEYS == legacy_names.FORMATS["cooldown_state"]["keys"]
    assert hook_common.FILE_NAMES["cooldown_state"] == legacy_names.FILE_NAMES["cooldown_state"]
