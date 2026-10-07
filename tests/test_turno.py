"""Tests del turno (T8): núcleo puro con reloj simulado y envoltura con hilos.

Los del núcleo no duermen. Los de la envoltura usan latencias de milisegundos y un tope propio
de 2 s por test. Los nombres de modelo son los de hoy; lo que se comprueba es la topología.
"""

from __future__ import annotations

import threading
import time

import pytest

from local_delegate import turno
from local_delegate.turno import Activo, Espera, Estado, Peticion, Turno

M4B = "gemma3-4b"
M26B = "gemma4-26b-a4b"
QWEN = "qwen3.6-35b-a3b"

TOPE_S = 2.0


def choca_hoy(a: str, b: str) -> bool:
    """La topología de hoy: todo en un grupo `swap`, así que dos modelos distintos chocan."""
    return a != b


def choca_residente(a: str, b: str) -> bool:
    """Escenario E-1: el 4B en un grupo `persistent, swap: false, exclusive: false`; los demás
    en uno `swap: true, exclusive: false`. El 4B no choca con nada; 26B y Qwen chocan entre sí."""
    if M4B in (a, b):
        return False
    return a != b


def choca_4b_con_qwen(a: str, b: str) -> bool:
    """El 4B no choca con el 26B pero sí con Qwen; 26B y Qwen chocan."""
    return {a, b} in ({M4B, QWEN}, {M26B, QWEN})


def nunca_choca(a: str, b: str) -> bool:
    return False


def pet(op_id: str, rol: str, *alternativos: str, **kw) -> Peticion:
    return Peticion(op_id, frozenset({rol, *alternativos}), rol, **kw)


def activo(op_id: str, *reserva: str, desde: float = 0.0) -> Activo:
    return Activo(Espera(pet(op_id, reserva[0]), desde), frozenset(reserva))


def espera(peticion: Peticion, desde: float = 0.0) -> Espera:
    return Espera(peticion, desde)


def evaluar(estado: Estado, choca=choca_hoy, ahora: float = 0.0, sin_progreso_desde=0.0):
    return turno.evaluar(estado, choca, ahora, sin_progreso_desde, 600.0)


def llegar(estado: Estado, peticion: Peticion, ahora: float = 0.0) -> Estado:
    return Estado(estado.activos, (*estado.cola, Espera(peticion, ahora)))


# --------------------------------------------------------------------------------------------
# Núcleo puro
# --------------------------------------------------------------------------------------------


def test_nadie_se_queda_esperando_para_siempre():
    """Escenario «nadie se queda esperando para siempre»."""
    estado = Estado(activos=(activo("larga", M26B),), cola=(espera(pet("qwen", QWEN)),))
    orden = ["larga"]

    def servir(estado: Estado) -> Estado:
        decision = evaluar(estado)
        orden.extend(c.id for c in decision.concesiones)
        return decision.estado

    for n in (1, 2, 3):
        estado = servir(llegar(estado, pet(f"26b-{n}", M26B)))
    estado = servir(turno.soltar(estado, "larga"))
    estado = servir(turno.soltar(estado, "qwen"))

    assert orden == ["larga", "qwen", "26b-1", "26b-2", "26b-3"]
    assert estado.cola == ()


def test_la_afinidad_no_se_cuela_si_alguien_espera():
    """Escenario «la afinidad no se cuela si alguien espera», con `A` sintético {4B, 26B}."""
    estado = Estado(activos=(activo("propia", M26B),), cola=(espera(pet("qwen", QWEN)),))
    estado = llegar(estado, pet("classify", M4B, M26B))

    concedida = evaluar(estado).para("classify")

    assert concedida is None


def test_la_afinidad_se_une_si_nadie_espera():
    """Escenario «la afinidad se une si nadie espera» (guarda del mutante anterior)."""
    estado = llegar(Estado(activos=(activo("propia", M26B),)), pet("classify", M4B, M26B))

    concedida = evaluar(estado).para("classify")

    assert concedida is not None
    assert concedida.reserva == {"gemma4-26b-a4b"}


def test_un_residente_compatible_no_espera_e1():
    """Escenario «un residente compatible no espera (E-1)»."""
    estado = Estado(activos=(activo("propia", M26B),), cola=(espera(pet("qwen", QWEN)),))
    estado = llegar(estado, pet("classify", M4B))

    decision = evaluar(estado, choca=choca_residente)
    concedida = decision.para("classify")

    assert concedida is not None and concedida.id == "classify"
    assert concedida.reserva == {M4B}
    assert decision.estado.cola[0].id == "qwen"


def test_e1_no_se_aplica_si_choca_con_lo_que_pide_la_cola():
    """El 4B es compatible con `activos` (26B) pero choca con lo que pide la cabeza (Qwen)."""
    estado = Estado(activos=(activo("propia", M26B),), cola=(espera(pet("qwen", QWEN)),))
    estado = llegar(estado, pet("classify", M4B))

    concedida = evaluar(estado, choca=choca_4b_con_qwen).para("classify")

    assert concedida is None


def test_sin_progreso_la_cabeza_se_concede_forzada_a_los_600():
    estado = Estado(activos=(activo("larga", M26B),), cola=(espera(pet("qwen", QWEN), 0.0),))

    assert evaluar(estado, ahora=599.0, sin_progreso_desde=0.0).para("qwen") is None
    decision = evaluar(estado, ahora=600.0, sin_progreso_desde=0.0).para("qwen")

    assert decision is not None
    assert decision.forzada
    assert decision.modelo == QWEN


def test_una_llamada_que_termina_en_el_599_no_deja_forzar_a_los_600():
    """Mutante 2: medir la espera total en vez de la falta de progreso."""
    estado = Estado(activos=(activo("larga", M26B),), cola=(espera(pet("qwen", QWEN), 0.0),))

    decision = evaluar(estado, ahora=600.0, sin_progreso_desde=599.0).para("qwen")

    assert not (decision is not None and decision.forzada)
    assert decision is None


@pytest.mark.parametrize(
    ("aceptable", "orden_cadena"),
    [
        # Salto con `A = {destino}`: el destino, aunque el rol sea otro.
        ({M26B}, (QWEN, M26B)),
        # Paso `cargado`: el primero del conjunto en el orden de la cadena (no el primero por id).
        ({M4B, M26B}, (QWEN, M26B, M4B)),
    ],
)
def test_forzada_de_un_salto_usa_el_orden_de_la_cadena(aceptable, orden_cadena):
    salto = Peticion("salto", frozenset(aceptable), QWEN, orden_cadena)
    estado = Estado(activos=(activo("otra", QWEN),), cola=(espera(salto, 0.0),))

    decision = evaluar(estado, ahora=600.0, sin_progreso_desde=0.0).para("salto")

    assert decision is not None and decision.forzada
    assert decision.modelo == "gemma4-26b-a4b"


def test_eleccion_tras_una_forzada_vuelve_a_la_cabeza():
    """REQ-003, «Elección»: ningún modelo de `A'` cabe sin contar la propia operación."""
    op = pet("op", M4B, M26B)
    forzada = Activo(Espera(pet("forzada", QWEN), 0.0), frozenset({QWEN}), forzada=True)
    estado = Estado(
        activos=(Activo(Espera(op, 0.0), frozenset({M4B, M26B})), forzada),
        cola=(espera(pet("detras", M26B), 5.0),),
    )

    assert turno.compatibles_al_elegir(estado, "op", choca_hoy) == frozenset()
    estado = turno.volver_a_la_cabeza(estado, "op")

    assert estado.cola[0].id == op.id
    assert estado.activo("op") is None
    assert estado.cola[0].desde == 0.0  # no pierde su puesto


def test_elegir_reduce_al_primer_candidato_que_cabe():
    """`elegir` respeta el orden de los candidatos y se salta los que chocan."""
    op = pet("op", M4B, M26B, QWEN)
    otro = activo("otro", M26B)
    estado = Estado(activos=(Activo(Espera(op, 0.0), frozenset({M4B, M26B, QWEN})), otro))

    estado, modelo = turno.elegir(estado, "op", [QWEN, M26B, M4B], choca_4b_con_qwen)

    assert modelo == M26B  # Qwen choca con el 26B de `otro`; el 26B es el siguiente
    propio = estado.activo("op")
    assert propio is not None and propio.reserva == {M26B}
    assert estado.cola == ()


def test_elegir_vuelve_a_la_cabeza_si_ninguno_cabe():
    """Tras una forzada de otra, `elegir` no reduce: devuelve la operación a la cabeza."""
    op = pet("op", M4B, M26B)
    forzada = Activo(Espera(pet("forzada", QWEN), 0.0), frozenset({QWEN}), forzada=True)
    estado = Estado(
        activos=(Activo(Espera(op, 0.0), frozenset({M4B, M26B})), forzada),
        cola=(espera(pet("detras", M26B), 5.0),),
    )

    estado, modelo = turno.elegir(estado, "op", [M4B, M26B], choca_hoy)

    assert modelo is None
    assert [e.id for e in estado.cola] == ["op", "detras"]
    assert estado.activo("op") is None


def test_elegir_sin_candidatos_de_la_reserva_falla():
    estado = Estado(activos=(activo("op", M4B),))
    with pytest.raises(ValueError):
        turno.elegir(estado, "op", [QWEN], choca_hoy)


def test_con_activos_vacio_la_reserva_es_todo_a():
    concedida = evaluar(llegar(Estado(), pet("w1", M4B, M26B, QWEN))).para("w1")

    assert concedida is not None
    assert concedida.reserva == {M4B, M26B, QWEN}
    assert concedida.modelo is None


# --------------------------------------------------------------------------------------------
# Envoltura con hilos
# --------------------------------------------------------------------------------------------


class Reloj:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Pedido:
    """Un `pedir` en su propio hilo, con la concesión y su instante (reloj real)."""

    def __init__(self, t: Turno, peticion: Peticion) -> None:
        self.concesion: turno.Concesion | None = None
        self.error: BaseException | None = None
        self.instante: float | None = None
        self.avisos: list[tuple[int, tuple[str, ...]]] = []
        self.listo = threading.Event()

        def correr() -> None:
            try:
                self.concesion = t.pedir(peticion, lambda *a: self.avisos.append(a))
                self.instante = time.monotonic()
            except BaseException as exc:
                self.error = exc
            finally:
                self.listo.set()

        self.hilo = threading.Thread(target=correr, daemon=True)
        self.hilo.start()


def esperar_en_cola(t: Turno, op_id: str) -> None:
    limite = time.monotonic() + TOPE_S
    while t.foto().en_cola(op_id) is None:
        assert time.monotonic() < limite, f"{op_id} no llegó a la cola"
        time.sleep(0.002)


def test_envoltura_sin_progreso_se_fuerza_por_la_comprobacion_periodica():
    """Mutante 1: `wait()` sin tope no despierta nunca si nadie llega ni sale."""
    reloj = Reloj()
    t = Turno(choca_hoy, tic=0.02, reloj=reloj)
    t.pedir(pet("larga", M26B))
    w = Pedido(t, pet("qwen", QWEN))
    esperar_en_cola(t, "qwen")

    reloj.t = 600.0
    w.listo.wait(TOPE_S)

    decision = w.concesion
    assert decision is not None and decision.forzada


def test_envoltura_llamada_larga_en_vuelo_no_se_fuerza():
    """Escenario «llamada larga con plazo HTTP mayor que 600 s»: 700 s en vuelo."""
    reloj = Reloj()
    t = Turno(choca_hoy, tic=0.02, reloj=reloj)
    t.pedir(pet("larga", M26B))
    llamada = t.en_vuelo()
    llamada.__enter__()
    w = Pedido(t, pet("qwen", QWEN))
    esperar_en_cola(t, "qwen")

    reloj.t = 650.0
    w.listo.wait(0.2)  # varios tics a 650 s simulados
    assert w.concesion is None, "forzada con una llamada en vuelo"

    reloj.t = 700.0
    llamada.__exit__(None, None, None)
    t.soltar("larga")
    w.listo.wait(TOPE_S)
    decision = w.concesion
    assert decision is not None
    assert not decision.forzada


def test_cuando_una_reserva_se_reduce_la_cola_se_vuelve_a_mirar():
    """Escenario «cuando una reserva se reduce, la cola se vuelve a mirar»."""
    t = Turno(choca_hoy, tic=5.0)
    w1 = t.pedir(pet("w1", M4B, M26B, QWEN))
    assert w1.reserva == {M4B, M26B, QWEN}
    w2 = Pedido(t, pet("w2", M26B))
    esperar_en_cola(t, "w2")

    t.reducir("w1", M26B)
    for _ in range(3):  # W1 sigue con sus 3 trozos de 50 ms
        with t.en_vuelo():
            time.sleep(0.05)
    w1_termino = time.monotonic()
    t.soltar("w1")
    w2.listo.wait(TOPE_S)

    assert w2.instante is not None
    w2_empezo = w2.instante
    assert w2_empezo < w1_termino


def test_una_espera_abandonada_deja_pasar_a_la_siguiente_compatible():
    t = Turno(choca_hoy, tic=5.0)
    t.pedir(pet("larga", M26B))
    cabeza = Pedido(t, pet("qwen", QWEN))
    esperar_en_cola(t, "qwen")
    siguiente = Pedido(t, pet("26b", M26B))
    esperar_en_cola(t, "26b")

    assert t.abandonar("qwen")
    concedida_a_tiempo = siguiente.listo.wait(0.2) and siguiente.concesion is not None

    assert concedida_a_tiempo
    cabeza.listo.wait(TOPE_S)
    assert isinstance(cabeza.error, turno.EsperaAbandonada)
    assert t.foto().en_cola("qwen") is None


def test_cambio_de_topologia_concede_a_una_espera_que_ahora_cabe():
    t = Turno(choca_hoy, tic=5.0)
    t.pedir(pet("larga", M26B))
    w = Pedido(t, pet("qwen", QWEN))
    esperar_en_cola(t, "qwen")

    t.cambio_topologia(nunca_choca)
    concedida_a_tiempo = w.listo.wait(0.2) and w.concesion is not None

    assert concedida_a_tiempo


def test_el_gancho_por_tic_deja_ver_una_topologia_nueva_a_quien_ya_espera():
    """T10 (revisión): nadie llega ni sale y nadie llama a `cambio_topologia` desde fuera.

    El gancho `al_tic` (fuera del cerrojo) es el único que trae la topología nueva, y la
    reevaluación de ese mismo tic la usa. Mutante: `_esperar` no llama al gancho → la espera sigue
    con el `choca` viejo y falla `assert concedida_a_tiempo`.
    """
    llamadas: list[bool] = []
    t: Turno

    def al_tic() -> None:
        llamadas.append(t._cond._is_owned())  # type: ignore[attr-defined]
        t.cambio_topologia(nunca_choca)

    t = Turno(choca_hoy, tic=0.02, al_tic=al_tic)
    t.pedir(pet("larga", M26B))
    w = Pedido(t, pet("qwen", QWEN))
    esperar_en_cola(t, "qwen")

    concedida_a_tiempo = w.listo.wait(TOPE_S) and w.concesion is not None

    assert concedida_a_tiempo
    assert llamadas and not any(llamadas)  # siempre fuera del cerrojo


def test_orden_de_adquisicion_pedir_con_plaza_lanza():
    t = Turno(choca_hoy)
    with turno.plaza_tomada(), pytest.raises(AssertionError):
        t.pedir(pet("op", M26B))
    assert not turno.tiene_plaza()
    assert t.pedir(pet("op", M26B)).modelo == M26B  # sin la marca, se concede


def test_avisos_de_espera_y_volver_a_la_cabeza_con_hilos():
    """`al_esperar` recibe posición y modelos en uso; `volver` re-espera en la cabeza."""
    t = Turno(choca_hoy, tic=0.02)
    op = t.pedir(pet("op", M4B, M26B))
    assert op.modelo is None
    # Una forzada de otra deja la reserva de `op` sin modelo que quepa.
    forzada = Activo(Espera(pet("f", QWEN), 0.0), frozenset({QWEN}), forzada=True)
    with t._cond:  # montaje directo del estado tras una forzada
        t._estado = Estado(activos=(*t._estado.activos, forzada))
    assert t.compatibles("op") == frozenset()
    otra = Pedido(t, pet("otra", M26B))
    esperar_en_cola(t, "otra")

    resultado: list[turno.Concesion] = []
    hilo = threading.Thread(target=lambda: resultado.append(t.volver("op")), daemon=True)
    hilo.start()
    limite = time.monotonic() + TOPE_S
    while t.foto().cola[:1] == () or t.foto().cola[0].id != "op":
        assert time.monotonic() < limite
        time.sleep(0.002)
    assert [e.id for e in t.foto().cola] == ["op", "otra"]
    while len(otra.avisos) < 2:
        assert time.monotonic() < limite, otra.avisos
        time.sleep(0.002)
    assert otra.avisos[:2] == [(1, (M4B, M26B, QWEN)), (2, (QWEN,))]

    t.soltar("f")
    hilo.join(TOPE_S)
    assert resultado and resultado[0].reserva == {M4B, M26B}
    assert otra.concesion is None  # el 26B choca con la reserva {4B, 26B} de `op`


def test_el_abandono_por_excepcion_en_el_gancho_limpia_la_cola():
    t = Turno(choca_hoy, tic=5.0)
    t.pedir(pet("larga", M26B))

    def gancho(posicion, en_uso):
        raise RuntimeError("fallo del gancho")

    with pytest.raises(RuntimeError):
        t.pedir(pet("qwen", QWEN), gancho)
    assert t.foto().cola == ()


def test_envoltura_elegir_tras_una_forzada_espera_y_elige():
    """`Turno.elegir`: sin modelo que quepa vuelve a la cabeza, espera y elige al concederse."""
    t = Turno(choca_hoy, tic=0.02)
    t.pedir(pet("op", M4B, M26B))
    forzada = Activo(Espera(pet("f", QWEN), 0.0), frozenset({QWEN}), forzada=True)
    with t._cond:  # montaje directo del estado tras una forzada
        t._estado = Estado(activos=(*t._estado.activos, forzada))

    resultado: list[str] = []
    hilo = threading.Thread(target=lambda: resultado.append(t.elegir("op", [M26B, M4B])))
    hilo.daemon = True
    hilo.start()
    esperar_en_cola(t, "op")
    assert resultado == []

    t.soltar("f")
    hilo.join(TOPE_S)
    assert resultado == [M26B]
    propio = t.foto().activo("op")
    assert propio is not None and propio.reserva == {M26B}
