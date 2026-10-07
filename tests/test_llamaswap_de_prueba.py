"""Controles contra un llama-swap v255 de verdad (carrera del TTL, alias, recarga, foto de `inflight`).

Insumos de REQ-013 (margen de «cargado con margen»), de REQ-034 (las cuatro salidas de la recarga y si
se cortan las peticiones en curso) y de la foto de peticiones en vuelo. Nada carga un modelo: cada
modelo es un servidor falso en Python (`servidor_falso_llama.py`) y llama-swap usa su propio `store`.

Estos tests **no se saltan** en la PC de quien implementa (`pytest -rs` no puede listar ninguno de
este fichero): si falta el binario es que el entorno está mal, no que no haya nada que comprobar.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx2
import pytest
from llamaswap_de_prueba import (
    CAIDO,
    NO_VIGILA,
    RECARGO,
    RECHAZO,
    ModeloPrueba,
    binario_disponible,
    llamaswap_de_prueba,
    pid_del_llamaswap_real,
)

pytestmark = [
    pytest.mark.llamaswap_real,
    pytest.mark.skipif(not binario_disponible(), reason="falta llama-swap-v255 de prueba"),
]


def _dormir_hasta(hora: float) -> None:
    time.sleep(max(0.0, hora - time.time()))


# --- (a) semántica del TTL -----------------------------------------------------------------------


def _medir_ttl(directorio: Path, ttl: int) -> dict[str, object]:
    """Una petición de 3 s a un modelo con `ttl`; mira `/running` durante y tras la petición."""
    with llamaswap_de_prueba(directorio, [ModeloPrueba("m-ttl", ttl=ttl)]) as ls:
        hilo = threading.Thread(target=lambda: ls.chat("m-ttl", retraso_s=3))
        inicio = time.time()
        hilo.start()
        durante: dict[float, bool] = {}
        for segundo in (1.0, 2.0, 3.0):
            _dormir_hasta(inicio + segundo)
            durante[segundo] = ls.esta_cargado("m-ttl")
        hilo.join()
        fin = ls.ultimo_fin("m-ttl")
        muestras: list[tuple[float, bool]] = []
        while (transcurrido := time.time() - fin) < 4.4:
            muestras.append((transcurrido, ls.esta_cargado("m-ttl")))
            time.sleep(0.1)
    descargas = [t for t, cargado in muestras if not cargado]
    a_los_4s = [cargado for t, cargado in muestras if t >= 4.0]
    return {
        "durante": durante,
        "t_descarga": descargas[0] if descargas else None,
        "cargado_a_los_4s": bool(a_los_4s and a_los_4s[0]),
    }


def test_a_el_ttl_cuenta_desde_el_fin_de_la_peticion(tmp_path: Path) -> None:
    r = _medir_ttl(tmp_path, ttl=2)
    print(f"\n(a) durante={r['durante']} t_descarga={r['t_descarga']}")
    assert r["durante"] == {1.0: True, 2.0: True, 3.0: True}  # no se descarga mientras dura
    cargado_a_los_4s = r["cargado_a_los_4s"]
    assert not cargado_a_los_4s
    t_descarga = r["t_descarga"]
    assert isinstance(t_descarga, float)
    assert 2.0 <= t_descarga <= 4.0


# --- (c) alias ------------------------------------------------------------------------------------


def test_c_la_actividad_de_una_peticion_por_alias_lleva_el_id_real(tmp_path: Path) -> None:
    modelos = [ModeloPrueba("m-real", alias=("alias-m",)), ModeloPrueba("m-otro")]
    with llamaswap_de_prueba(tmp_path, modelos) as ls:
        assert ls.chat("alias-m").status_code == 200
        fin = ls.ultimo_fin("m-real")
        assert ls.chat("m-otro").status_code == 200
        por_id = ls.actividad("m-real", limite=1)
        por_alias = ls.actividad("alias-m", limite=1)
        todas = ls.actividad(limite=5)
    print(
        f"\n(c) por_id={[r['model'] for r in por_id]} por_alias={[r['model'] for r in por_alias]}"
    )
    print(f"(c) todas={[r['model'] for r in todas]} campos={sorted(por_id[0])}")
    assert [r["model"] for r in por_id] == ["m-real"]  # el id real, no el alias
    assert por_alias == []  # y filtrar por el alias no devuelve nada
    assert "ts_created" not in por_id[0]  # el campo de hora de v255 se llama `timestamp`
    # `timestamp` es la hora de FIN, truncada al segundo: queda entre 1 s antes y el fin.
    diferencia = ls.hora_de_actividad(por_id[0]) - fin
    print(f"(c) timestamp - fin = {diferencia:.3f} s")
    assert -1.0 <= diferencia <= 0.5


# --- (d) recarga con -watch-config ----------------------------------------------------------------


def test_d_recarga_valida_sale_recargo(tmp_path: Path) -> None:
    with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m", ttl=2)]) as ls:
        salida = ls.esperar_salida_recarga(
            lambda: ls.escribir_config(ls.texto_config([ModeloPrueba("m", ttl=3)]))
        )
        assert salida == "recargó"
        assert ls.chat("m").status_code == 200


@pytest.mark.parametrize("caso", ["yaml_roto", "modelo_sin_cmd"])
def test_d_config_rechazada_sale_rechazo_y_la_vieja_sigue_sirviendo(
    tmp_path: Path, caso: str
) -> None:
    with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m", ttl=2)]) as ls:
        buena = ls.texto_config()
        mala = "models: [\n  a: : :\n" if caso == "yaml_roto" else buena.replace("cmd:", "cmdx:")
        salida = ls.esperar_salida_recarga(lambda: ls.escribir_config(mala))
        print(f"\n(d) {caso}: {salida} -> {ls.detalle_recarga!r}")
        assert salida == RECHAZO
        assert "failed to reload config" in ls.detalle_recarga
        assert ls.chat("m").status_code == 200  # la config vieja sigue sirviendo
        ls.escribir_config(buena)  # y deja el fichero como lo que corre


def test_d_sin_watch_config_no_pasa_nada_en_diez_segundos(tmp_path: Path) -> None:
    with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m", ttl=2)], watch_config=False) as ls:
        salida = ls.esperar_salida_recarga(
            lambda: ls.escribir_config(ls.texto_config([ModeloPrueba("m", ttl=3)]))
        )
        assert salida == NO_VIGILA
        assert "reloading configuration" not in ls.log_texto()


def test_d_llamaswap_apagado_sale_caido(tmp_path: Path) -> None:
    with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m", ttl=2)]) as ls:
        ls.detener()
        salida = ls.esperar_salida_recarga(
            lambda: ls.escribir_config(ls.texto_config([ModeloPrueba("m", ttl=3)]))
        )
        assert salida == CAIDO
        assert ls.detalle_recarga == "conexión rechazada"


@pytest.mark.parametrize("caso", ["cambia_el_modelo", "cambio_ajeno"])
def test_d_peticion_de_8_s_en_curso_al_recargar(tmp_path: Path, caso: str) -> None:
    """Anota si la recarga corta una petición en curso. Fija lo observado con v255."""
    modelos = [ModeloPrueba("m", ttl=60)]
    nuevos = (
        [ModeloPrueba("m", ttl=61)]
        if caso == "cambia_el_modelo"
        else [ModeloPrueba("m", ttl=60), ModeloPrueba("otro", ttl=60)]
    )
    with llamaswap_de_prueba(tmp_path, modelos) as ls:
        resultado: dict[str, object] = {}

        def pedir() -> None:
            inicio = time.time()
            try:
                respuesta = ls.chat("m", retraso_s=8, timeout=40)
                resultado["estado"] = respuesta.status_code
            except httpx2.HTTPError as exc:
                resultado["estado"] = type(exc).__name__
            resultado["duracion"] = time.time() - inicio

        hilo = threading.Thread(target=pedir)
        hilo.start()
        time.sleep(1.5)
        salida = ls.esperar_salida_recarga(lambda: ls.escribir_config(ls.texto_config(nuevos)))
        hilo.join()
    print(f"\n(d) {caso}: salida={salida} peticion={resultado}")
    assert salida == RECARGO
    # Con v255 la recarga CORTA la petición en curso (502 a los ~2 s, no los 8 s), cambie o no el
    # modelo: llama-swap apaga todos los procesos al reiniciar. Por eso REQ-034 mantiene la negativa.
    assert resultado["estado"] == 502
    assert float(str(resultado["duracion"])) < 7.0


# --- (e) foto `inflight` de la carga inicial -----------------------------------------------------


def test_e_la_foto_inflight_llega_pronto_con_el_historial_lleno_y_trae_a_otro_cliente(
    tmp_path: Path,
) -> None:
    with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m", ttl=60)]) as ls:
        for _ in range(12):  # peticiones previas que llenan el historial de logs (~120 KB)
            assert ls.chat("m", log_kb=10).status_code == 200
        otro = ls.lanzar_cliente("m", retraso_s=4)
        time.sleep(1.0)
        foto = ls.foto_inflight()
        otro.wait(timeout=30)
    print(
        f"\n(e) {foto.caracteres_de_log} caracteres de log antes de la foto, "
        f"llegó en {foto.segundos:.3f} s, {len(foto.peticiones)} peticiones"
    )
    assert foto.caracteres_de_log >= 90_000  # el historial estaba lleno (el tope ronda los 100 KB)
    assert foto.segundos < 1.0
    assert [p["model"] for p in foto.peticiones] == ["m"]  # la petición del otro proceso


# --- la fixture ----------------------------------------------------------------------------------


def test_la_fixture_no_toca_el_llamaswap_real(tmp_path: Path, record_property) -> None:
    real = pid_del_llamaswap_real()
    with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m", ttl=1)]) as ls:
        assert ls.chat("m").status_code == 200
        assert ls.puerto != 9292
        assert real not in ls._pids
    if real is None:
        record_property("llamaswap_real", "no había ninguno en marcha: nada más que comprobar")
        return
    assert pid_del_llamaswap_real() == real  # sigue vivo y con el mismo PID


def test_la_fixture_apunta_los_pid_y_los_encuentra_muertos(tmp_path: Path) -> None:
    with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m", ttl=60)]) as ls:
        assert ls.chat("m").status_code == 200
        ls._apuntar_pids_de_los_servidores()
        servidores = [pid for pid, imagen in ls._pids.items() if imagen == "python.exe"]
        assert servidores  # el servidor falso (y su lanzador) quedaron apuntados


def test_la_fixture_falla_si_deja_un_proceso_vivo_y_lo_mata_por_pid(tmp_path: Path) -> None:
    ajeno = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        with llamaswap_de_prueba(tmp_path, [ModeloPrueba("m")], arrancar=False) as ls:
            ls._pids[ajeno.pid] = "python.exe"  # la fixture cree que lo lanzó ella
            with pytest.raises(AssertionError, match="la fixture dejó vivo el PID"):
                ls.comprobar_procesos(espera=1.0)
            ls._pids.clear()  # ya está tratado: que el cierre de la fixture no vuelva a fallar
        assert ajeno.wait(timeout=10) is not None  # y lo terminó
    finally:
        if ajeno.poll() is None:
            ajeno.kill()
