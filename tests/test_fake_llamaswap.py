"""Controles contra un llama-swap v255 de verdad (carrera del TTL, alias, recarga, foto de `inflight`).

Insumos de REQ-013 (margen de «cargado con margen»), de REQ-034 (las cuatro salidas de la recarga y si
se cortan las peticiones en curso) y de la foto de peticiones en vuelo. Nada carga un modelo: cada
modelo es un servidor falso en Python (`fake_llama_server.py`) y llama-swap usa su propio `store`.

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
from fake_llamaswap import (
    DOWN,
    NOT_WATCHED,
    REFUSAL,
    SURCHARGE,
    FakeModel,
    binary_available,
    fake_llamaswap,
    real_llamaswap_pid,
)

pytestmark = [
    pytest.mark.llamaswap_real,
    pytest.mark.skipif(not binary_available(), reason="falta llama-swap-v255 de prueba"),
]


def _sleep_until(hour: float) -> None:
    time.sleep(max(0.0, hour - time.time()))


# --- (a) semántica del TTL -----------------------------------------------------------------------


def _measure_ttl(directory: Path, ttl: int) -> dict[str, object]:
    """Una petición de 3 s a un modelo con `ttl`; mira `/running` durante y tras la petición."""
    with fake_llamaswap(directory, [FakeModel("m-ttl", ttl=ttl)]) as ls:
        thread = threading.Thread(target=lambda: ls.chat("m-ttl", delay_s=3))
        start_ts = time.time()
        thread.start()
        during: dict[float, bool] = {}
        for second in (1.0, 2.0, 3.0):
            _sleep_until(start_ts + second)
            during[second] = ls.is_loaded("m-ttl")
        thread.join()
        end = ls.last_end("m-ttl")
        samples: list[tuple[float, bool]] = []
        while (elapsed := time.time() - end) < 4.4:
            samples.append((elapsed, ls.is_loaded("m-ttl")))
            time.sleep(0.1)
    unloads = [t for t, loaded in samples if not loaded]
    at_4s = [loaded for t, loaded in samples if t >= 4.0]
    return {
        "durante": during,
        "t_descarga": unloads[0] if unloads else None,
        "cargado_a_los_4s": bool(at_4s and at_4s[0]),
    }


def test_a_ttl_counts_from_request_end(tmp_path: Path) -> None:
    r = _measure_ttl(tmp_path, ttl=2)
    print(f"\n(a) durante={r['durante']} t_descarga={r['t_descarga']}")
    assert r["durante"] == {1.0: True, 2.0: True, 3.0: True}  # no se descarga mientras dura
    loaded_at_4s = r["cargado_a_los_4s"]
    assert not loaded_at_4s
    t_unload = r["t_descarga"]
    assert isinstance(t_unload, float)
    assert 2.0 <= t_unload <= 4.0


# --- (c) alias ------------------------------------------------------------------------------------


def test_c_alias_request_activity_carries_real_id(tmp_path: Path) -> None:
    models = [FakeModel("m-real", alias=("alias-m",)), FakeModel("m-otro")]
    with fake_llamaswap(tmp_path, models) as ls:
        assert ls.chat("alias-m").status_code == 200
        end = ls.last_end("m-real")
        assert ls.chat("m-otro").status_code == 200
        by_id = ls.activity("m-real", limit=1)
        by_alias = ls.activity("alias-m", limit=1)
        all_ones = ls.activity(limit=5)
    print(f"\n(c) por_id={[r['model'] for r in by_id]} por_alias={[r['model'] for r in by_alias]}")
    print(f"(c) todas={[r['model'] for r in all_ones]} campos={sorted(by_id[0])}")
    assert [r["model"] for r in by_id] == ["m-real"]  # el id real, no el alias
    assert by_alias == []  # y filtrar por el alias no devuelve nada
    assert "ts_created" not in by_id[0]  # el campo de hora de v255 se llama `timestamp`
    # `timestamp` es la hora de FIN, truncada al segundo: queda entre 1 s antes y el fin.
    difference = ls.activity_time(by_id[0]) - end
    print(f"(c) timestamp - fin = {difference:.3f} s")
    assert -1.0 <= difference <= 0.5


# --- (d) recarga con -watch-config ----------------------------------------------------------------


def test_d_valid_reload_gives_reloaded(tmp_path: Path) -> None:
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=2)]) as ls:
        output = ls.wait_reload_output(
            lambda: ls.write_config(ls.config_text([FakeModel("m", ttl=3)]))
        )
        assert output == "recargó"
        assert ls.chat("m").status_code == 200


@pytest.mark.parametrize("case", ["yaml_roto", "modelo_sin_cmd"])
def test_d_rejected_config_gives_refusal_and_old_keeps_serving(tmp_path: Path, case: str) -> None:
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=2)]) as ls:
        good_one = ls.config_text()
        bad_one = (
            "models: [\n  a: : :\n" if case == "yaml_roto" else good_one.replace("cmd:", "cmdx:")
        )
        output = ls.wait_reload_output(lambda: ls.write_config(bad_one))
        print(f"\n(d) {case}: {output} -> {ls.reload_detail!r}")
        assert output == REFUSAL
        assert "failed to reload config" in ls.reload_detail
        assert ls.chat("m").status_code == 200  # la config vieja sigue sirviendo
        ls.write_config(good_one)  # y deja el fichero como lo que corre


def test_d_without_watch_config_nothing_happens_in_ten_seconds(tmp_path: Path) -> None:
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=2)], watch_config=False) as ls:
        output = ls.wait_reload_output(
            lambda: ls.write_config(ls.config_text([FakeModel("m", ttl=3)]))
        )
        assert output == NOT_WATCHED
        assert "reloading configuration" not in ls.log_text()


def test_d_llamaswap_off_gives_down(tmp_path: Path) -> None:
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=2)]) as ls:
        ls.stop()
        output = ls.wait_reload_output(
            lambda: ls.write_config(ls.config_text([FakeModel("m", ttl=3)]))
        )
        assert output == DOWN
        assert ls.reload_detail == "conexión rechazada"


@pytest.mark.parametrize("case", ["cambia_el_modelo", "cambio_ajeno"])
def test_d_8_s_request_in_progress_on_reload(tmp_path: Path, case: str) -> None:
    """Anota si la recarga corta una petición en curso. Fija lo observado con v255."""
    models = [FakeModel("m", ttl=60)]
    new_items = (
        [FakeModel("m", ttl=61)]
        if case == "cambia_el_modelo"
        else [FakeModel("m", ttl=60), FakeModel("otro", ttl=60)]
    )
    with fake_llamaswap(tmp_path, models) as ls:
        result: dict[str, object] = {}

        def request() -> None:
            start_ts = time.time()
            try:
                response = ls.chat("m", delay_s=8, timeout=40)
                result["estado"] = response.status_code
            except httpx2.HTTPError as exc:
                result["estado"] = type(exc).__name__
            result["duracion"] = time.time() - start_ts

        thread = threading.Thread(target=request)
        thread.start()
        time.sleep(1.5)
        output = ls.wait_reload_output(lambda: ls.write_config(ls.config_text(new_items)))
        thread.join()
    print(f"\n(d) {case}: salida={output} peticion={result}")
    assert output == SURCHARGE
    # Con v255 la recarga CORTA la petición en curso (502 a los ~2 s, no los 8 s), cambie o no el
    # modelo: llama-swap apaga todos los procesos al reiniciar. Por eso REQ-034 mantiene la negativa.
    assert result["estado"] == 502
    assert float(str(result["duracion"])) < 7.0


# --- (e) foto `inflight` de la carga inicial -----------------------------------------------------


def test_e_inflight_snapshot_arrives_early_with_full_history_and_other_client(
    tmp_path: Path,
) -> None:
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)]) as ls:
        for _ in range(12):  # peticiones previas que llenan el historial de logs (~120 KB)
            assert ls.chat("m", log_kb=10).status_code == 200
        other = ls.launch_client("m", delay_s=4)
        time.sleep(1.0)
        snapshot = ls.inflight_snapshot()
        other.wait(timeout=30)
    print(
        f"\n(e) {snapshot.log_chars} caracteres de log antes de la foto, "
        f"llegó en {snapshot.seconds:.3f} s, {len(snapshot.requests)} peticiones"
    )
    assert snapshot.log_chars >= 90_000  # el historial estaba lleno (el tope ronda los 100 KB)
    assert snapshot.seconds < 1.0
    assert [p["model"] for p in snapshot.requests] == ["m"]  # la petición del otro proceso


# --- la fixture ----------------------------------------------------------------------------------


def test_fixture_does_not_touch_real_llamaswap(tmp_path: Path, record_property) -> None:
    real = real_llamaswap_pid()
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=1)]) as ls:
        assert ls.chat("m").status_code == 200
        assert ls.port != 9292
        assert real not in ls._pids
    if real is None:
        record_property("llamaswap_real", "no había ninguno en marcha: nada más que comprobar")
        return
    assert real_llamaswap_pid() == real  # sigue vivo y con el mismo PID


def test_fixture_records_pids_and_finds_them_dead(tmp_path: Path) -> None:
    with fake_llamaswap(tmp_path, [FakeModel("m", ttl=60)]) as ls:
        assert ls.chat("m").status_code == 200
        ls._record_server_pids()
        servers = [pid for pid, image in ls._pids.items() if image == "python.exe"]
        assert servers  # el servidor falso (y su lanzador) quedaron apuntados


def test_fixture_fails_if_process_left_alive_and_kills_by_pid(tmp_path: Path) -> None:
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        with fake_llamaswap(tmp_path, [FakeModel("m")], start=False) as ls:
            ls._pids[foreign.pid] = "python.exe"  # la fixture cree que lo lanzó ella
            with pytest.raises(AssertionError, match="la fixture dejó vivo el PID"):
                ls.check_processes(wait=1.0)
            ls._pids.clear()  # ya está tratado: que el cierre de la fixture no vuelva a fallar
        assert foreign.wait(timeout=10) is not None  # y lo terminó
    finally:
        if foreign.poll() is None:
            foreign.kill()
