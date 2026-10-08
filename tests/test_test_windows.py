"""Las ventanas de prueba: forma del fichero, la regla del borde y la escritura segura (T1).

Cada test usa `tmp_path` como `LOG_DIR`: nunca toca el fichero real de la máquina.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
from datetime import UTC, datetime, timedelta

import pytest
from filelock import FileLock

from local_delegate import test_windows as tw


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _escribir(tmp_path, data) -> None:
    (tmp_path / tw.FILE_NAME).write_text(
        data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
    )


# --- Forma del fichero (REQ-001) -----------------------------------------------------------------


def test_start_stop_add_dejan_la_forma_del_fichero(tmp_path):
    t0 = datetime(2026, 10, 8, 1, 20, 5, 255000, tzinfo=UTC)
    w = tw.start(tmp_path, "ola 11", now=t0)
    assert w.id == "w-20261008T012005Z"
    tw.stop(tmp_path, w.id, now=t0 + timedelta(seconds=146, microseconds=289000))
    data = json.loads((tmp_path / tw.FILE_NAME).read_text(encoding="utf-8"))
    assert data["version"] == 1
    (entrada,) = data["windows"]
    assert set(entrada) == {"id", "start", "end", "label", "created_at"}
    assert entrada["start"] == "2026-10-08T01:20:05.255Z"
    assert entrada["end"] == "2026-10-08T01:22:31.544Z"
    assert entrada["label"] == "ola 11"
    assert entrada["created_at"].endswith("Z")


def test_el_id_lleva_sufijo_si_se_repite(tmp_path):
    t0 = datetime(2026, 10, 8, 1, 0, 0, tzinfo=UTC)
    ids = [tw.start(tmp_path, now=t0).id for _ in range(3)]
    assert ids == ["w-20261008T010000Z", "w-20261008T010000Z-2", "w-20261008T010000Z-3"]


# --- La regla del borde (REQ-002) ----------------------------------------------------------------


@pytest.fixture
def ola11(tmp_path):
    tw.add(tmp_path, "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z", "ola 11")
    return tw.load(tmp_path)


@pytest.mark.parametrize(
    ("hora", "dentro"),
    [
        ("01:20:04", False),
        ("01:20:05", True),
        ("01:22:31", True),
        ("01:22:32", False),
        ("01:22:33", False),
    ],
)
def test_el_segundo_del_borde(ola11, hora, dentro):
    ts = f"2026-10-08T{hora}+00:00"
    assert (ola11.find(ts) is not None) is dentro, ts


def test_una_marca_sin_zona_es_utc_y_una_ilegible_no_esta_en_ninguna(ola11):
    assert ola11.find("2026-10-08T01:21:00") == "w-20261008T012005Z"
    assert ola11.find("ayer") is None
    assert ola11.find(None) is None


def test_una_ventana_abierta_llega_hasta_ahora(tmp_path):
    t0 = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)
    tw.start(tmp_path, now=t0)
    ventanas = tw.load(tmp_path)
    ahora = t0 + timedelta(minutes=5)
    assert ventanas.find(ahora - timedelta(seconds=1), now=ahora) is not None
    assert ventanas.find(ahora + timedelta(seconds=1), now=ahora) is None


def test_solapadas_se_estampa_la_primera_por_inicio(tmp_path):
    tw.add(tmp_path, "2026-10-08T02:00:00Z", "2026-10-08T03:00:00Z", "b")
    tw.add(tmp_path, "2026-10-08T01:00:00Z", "2026-10-08T04:00:00Z", "a")
    assert tw.load(tmp_path).find("2026-10-08T02:30:00Z") == "w-20261008T010000Z"


# --- Lectura tolerante (REQ-003) -----------------------------------------------------------------


def test_sin_fichero_no_hay_ventanas_ni_error(tmp_path):
    v = tw.load(tmp_path)
    assert (v.windows, v.ignored, v.error, v.exists) == ([], 0, None, False)
    assert v.find("2026-10-08T01:00:00Z") is None


@pytest.mark.parametrize(
    ("contenido", "motivo"),
    [
        ("{roto", "JSON roto"),
        ({"version": 2, "windows": []}, "versión desconocida"),
        ([1, 2], "no es un objeto"),
    ],
)
def test_un_fichero_ilegible_da_error_y_no_lanza(tmp_path, contenido, motivo):
    _escribir(tmp_path, contenido)
    v = tw.load(tmp_path)
    assert v.windows == []
    assert v.error is not None and motivo in v.error
    assert v.find("2026-10-08T01:00:00Z") is None


def test_las_entradas_ilegibles_se_ignoran_solas(tmp_path):
    buena = {"id": "w-1", "start": "2026-10-08T01:00:00Z", "end": "2026-10-08T02:00:00Z"}
    _escribir(
        tmp_path,
        {
            "version": 1,
            "windows": [
                buena,
                {"id": "w-2", "end": "2026-10-08T02:00:00Z"},  # falta start
                {"id": "w-3", "start": "no-es-fecha", "end": None},
                {"id": "w-4", "start": "2026-10-08T03:00:00Z", "end": "2026-10-08T02:00:00Z"},
                {**buena},  # id repetido
            ],
        },
    )
    v = tw.load(tmp_path)
    assert [w.id for w in v.windows] == ["w-1"]
    assert v.ignored == 4
    assert v.error is None


def test_la_lectura_se_cachea_y_se_renueva_al_escribir(tmp_path):
    tw.add(tmp_path, "2026-10-08T01:00:00Z", "2026-10-08T02:00:00Z")
    a = tw.load(tmp_path)
    assert tw.load(tmp_path) is a
    tw.add(tmp_path, "2026-10-08T03:00:00Z", "2026-10-08T04:00:00Z")
    b = tw.load(tmp_path)
    assert b is not a and len(b.windows) == 2


# --- Escritura segura (REQ-010) ------------------------------------------------------------------


@pytest.mark.parametrize("operacion", ["start", "stop", "add"])
def test_no_se_pisa_un_fichero_ilegible(tmp_path, operacion):
    _escribir(tmp_path, "{roto")
    antes = _sha(tmp_path / tw.FILE_NAME)
    with pytest.raises(tw.TestWindowError, match="ilegible"):
        if operacion == "start":
            tw.start(tmp_path)
        elif operacion == "stop":
            tw.stop(tmp_path)
        else:
            tw.add(tmp_path, "2026-10-08T01:00:00Z", "2026-10-08T02:00:00Z")
    assert _sha(tmp_path / tw.FILE_NAME) == antes


def test_con_el_cerrojo_ocupado_se_rinde(tmp_path):
    ajeno = FileLock(str(tmp_path / tw.LOCK_NAME))
    with ajeno, pytest.raises(tw.TestWindowError, match="ocupado"):
        tw.start(tmp_path, lock_timeout=0.2)
    assert not (tmp_path / tw.FILE_NAME).exists()


def _abrir(log_dir: str, etiqueta: str) -> None:
    from pathlib import Path

    from local_delegate import test_windows

    test_windows.start(Path(log_dir), etiqueta, now=datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC))


def test_dos_procesos_abren_a_la_vez_y_quedan_las_dos(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    procesos = [ctx.Process(target=_abrir, args=(str(tmp_path), f"p{i}")) for i in range(2)]
    for p in procesos:
        p.start()
    for p in procesos:
        p.join(60)
        assert p.exitcode == 0
    v = tw.load(tmp_path)
    assert len(v.open_windows()) == 2
    assert len({w.id for w in v.windows}) == 2
    assert {w.label for w in v.windows} == {"p0", "p1"}


# --- stop y add (REQ-007, REQ-008, en el módulo) -------------------------------------------------


def test_stop_sin_id_con_varias_abiertas_no_cierra_ninguna(tmp_path):
    a = tw.start(tmp_path, now=datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC))
    b = tw.start(tmp_path, now=datetime(2026, 10, 8, 9, 0, 1, tzinfo=UTC))
    with pytest.raises(tw.TestWindowError) as info:
        tw.stop(tmp_path)
    assert a.id in str(info.value) and b.id in str(info.value)
    assert len(tw.load(tmp_path).open_windows()) == 2


def test_stop_de_una_cerrada_o_inexistente_falla(tmp_path):
    w = tw.start(tmp_path, now=datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC))
    tw.stop(tmp_path, w.id, now=datetime(2026, 10, 8, 9, 5, 0, tzinfo=UTC))
    with pytest.raises(tw.TestWindowError, match="ya estaba cerrada"):
        tw.stop(tmp_path, w.id)
    with pytest.raises(tw.TestWindowError, match="no existe"):
        tw.stop(tmp_path, "w-nada")
    with pytest.raises(tw.TestWindowError, match="ninguna ventana abierta"):
        tw.stop(tmp_path)


def test_add_repetido_no_duplica(tmp_path):
    _, creada = tw.add(tmp_path, "2026-09-15T19:31:14Z", "2026-09-15T19:35:14Z", "P-4")
    assert creada
    _, creada = tw.add(tmp_path, "2026-09-15T19:31:14+00:00", "2026-09-15T19:35:14.000", "otra")
    assert not creada
    assert len(tw.load(tmp_path).windows) == 1


@pytest.mark.parametrize(
    ("inicio", "fin"),
    [
        ("2026-10-08T02:00:00Z", "2026-10-08T01:00:00Z"),
        ("2026-10-08T01:00:00Z", "2026-10-08T01:00:00Z"),
        ("ayer", "hoy"),
    ],
)
def test_add_rechaza_fechas_rotas_o_al_reves(tmp_path, inicio, fin):
    with pytest.raises(tw.TestWindowError):
        tw.add(tmp_path, inicio, fin)


def test_stale_cuenta_las_abiertas_de_mas_de_doce_horas(tmp_path):
    ahora = datetime(2026, 10, 8, 22, 0, 0, tzinfo=UTC)
    vieja = tw.start(tmp_path, now=ahora - timedelta(hours=13))
    tw.start(tmp_path, now=ahora - timedelta(hours=1))
    assert [w.id for w in tw.load(tmp_path).stale(ahora)] == [vieja.id]
