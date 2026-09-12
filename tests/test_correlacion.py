"""El cruce entre un bloqueo del hook y la delegacion que viene despues.

El formato de la nota vive en dos sitios —lo escribe `hook_common`, que es stdlib pura y no puede
importar el paquete, y lo lee `server`— asi que estos tests van de **ida y vuelta**: escriben con
el hook de verdad y leen con el servidor de verdad. Es la misma cautela que el test de paridad del
espejo JavaScript del panel, y por la misma razon: dos fuentes del mismo dato se desincronizan
solas.
"""

from __future__ import annotations

import json
import time

import pytest

from local_delegate import server
from local_delegate.resources.hooks import hook_common


@pytest.fixture
def notas(tmp_path, monkeypatch):
    archivo = tmp_path / "bloqueos.jsonl"
    monkeypatch.setattr(hook_common, "ruta_de_notas", lambda: archivo)
    return archivo


def test_el_identificador_del_bloqueo_llega_al_servidor(notas, tmp_path):
    """Ida y vuelta: lo escribe el hook, lo encuentra el servidor, y nadie pasa nada por el agente."""
    documento = tmp_path / "informe.md"
    documento.write_text("hola", encoding="utf-8")

    hook_common.anotar_bloqueo("abc123def456", str(documento))

    assert server._bloqueo_reciente(str(documento)) == "abc123def456"


def test_otra_ruta_no_se_lleva_el_bloqueo_ajeno(notas, tmp_path):
    """Control positivo: si cualquier lectura heredara el id, la adopcion medida seria falsa."""
    hook_common.anotar_bloqueo("abc123def456", str(tmp_path / "informe.md"))

    assert server._bloqueo_reciente(str(tmp_path / "otro.md")) is None


def test_la_misma_ruta_escrita_de_otra_forma_sigue_cruzando(notas, tmp_path):
    """El hook recibe la ruta del cliente y el servidor la recibe del agente: no coinciden letra a
    letra. En Windows ademas cambian las mayusculas y las barras."""
    documento = tmp_path / "sub" / "informe.md"
    documento.parent.mkdir()
    documento.write_text("hola", encoding="utf-8")

    hook_common.anotar_bloqueo("id-largo-1234", str(documento))
    otra_forma = str(tmp_path / "sub" / ".." / "sub" / "informe.md")

    assert server._bloqueo_reciente(otra_forma) == "id-largo-1234"


def test_un_bloqueo_viejo_ya_no_cuenta(notas, tmp_path, monkeypatch):
    """Pasada la ventana, el agente hizo otra cosa por el camino: atribuirselo infla la adopcion."""
    documento = tmp_path / "informe.md"
    hook_common.anotar_bloqueo("caducado1234", str(documento))

    viejo = json.loads(notas.read_text(encoding="utf-8").strip())
    viejo["ts"] = time.time() - server.VENTANA_DE_BLOQUEO_S - 1
    notas.write_text(json.dumps(viejo) + "\n", encoding="utf-8")

    assert server._bloqueo_reciente(str(documento)) is None


def test_gana_el_bloqueo_mas_reciente_de_esa_ruta(notas, tmp_path):
    documento = tmp_path / "informe.md"
    hook_common.anotar_bloqueo("primero12345", str(documento))
    hook_common.anotar_bloqueo("segundo12345", str(documento))

    assert server._bloqueo_reciente(str(documento)) == "segundo12345"


def test_las_notas_no_crecen_sin_freno(notas, tmp_path):
    for i in range(hook_common.MAX_NOTAS + 50):
        hook_common.anotar_bloqueo(f"id{i:010d}", str(tmp_path / f"{i}.md"))

    assert len(notas.read_text(encoding="utf-8").splitlines()) <= hook_common.MAX_NOTAS


def test_la_nota_no_guarda_la_ruta(notas, tmp_path):
    """Hereda la regla de la telemetria de hooks: ni rutas ni contenido, solo una huella."""
    documento = tmp_path / "secreto-del-cliente.md"
    hook_common.anotar_bloqueo("abc123def456", str(documento))

    crudo = notas.read_text(encoding="utf-8")
    assert "secreto-del-cliente" not in crudo
    assert str(tmp_path) not in crudo


@pytest.mark.parametrize(
    "contenido",
    ["", "no es json\n", '{"sin": "campos"}\n', '{"id": 1, "sha": null, "ts": "ayer"}\n'],
    ids=["vacio", "basura", "sin campos", "tipos raros"],
)
def test_un_fichero_de_notas_roto_no_rompe_la_tool(notas, tmp_path, contenido):
    notas.write_text(contenido, encoding="utf-8")

    assert server._bloqueo_reciente(str(tmp_path / "informe.md")) is None


def test_sin_fichero_de_notas_tampoco_pasa_nada(notas, tmp_path):
    assert not notas.exists()
    assert server._bloqueo_reciente(str(tmp_path / "informe.md")) is None


# --- Y lo que de verdad importa: que acabe en el evento del log -------------------------------


def _eventos(directorio):
    ficheros = sorted(directorio.glob("usage-*.jsonl"))
    assert ficheros, f"ningún log escrito en {directorio}"
    return [json.loads(x) for x in ficheros[-1].read_text(encoding="utf-8").splitlines()]


def test_el_evento_de_la_tool_se_queda_con_el_bloqueo(notas, tmp_path, monkeypatch):
    """Probar la función no es probar el uso: el dato tiene que llegar al log, que es lo que lee
    el panel."""
    from local_delegate import config

    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    documento = tmp_path / "informe.md"
    documento.write_text("hola", encoding="utf-8")
    hook_common.anotar_bloqueo("abc123def456", str(documento))

    server._log_event(
        tool="local_summarize",
        model="m",
        source="path",
        chars_in=10,
        chars_out=5,
        latency_ms=1,
        ok=True,
        path=str(documento),
    )

    assert _eventos(tmp_path / "logs")[-1]["bloqueo_id"] == "abc123def456"


def test_una_delegacion_espontanea_no_lleva_bloqueo(notas, tmp_path, monkeypatch):
    """Control positivo: si todo evento llevara id, «aceptado» contaría también lo que nadie
    provocó, y la adopción medida saldría inflada."""
    from local_delegate import config

    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)

    server._log_event(
        tool="local_summarize",
        model="m",
        source="path",
        chars_in=10,
        chars_out=5,
        latency_ms=1,
        ok=True,
        path=str(tmp_path / "nadie-me-bloqueo.md"),
    )

    assert "bloqueo_id" not in _eventos(tmp_path / "logs")[-1]
