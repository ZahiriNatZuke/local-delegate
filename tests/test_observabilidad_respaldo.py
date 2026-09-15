"""Tarea 29 de F3: lo que el salto deja en el log y en `local_status` (REQ-013, REQ-019).

Los campos del log son ADITIVOS: un evento sin salto se escribe exactamente como antes, y `model`
sigue siendo el modelo que respondió, para que el histórico se lea igual. Los tests de la cuenta y
del panel están en `test_metrics.py`, junto a la paridad con el JavaScript.
"""

from __future__ import annotations

import json
import time

import backend_mock
import httpx2
import pytest
from test_respaldo import (
    CODIGO,
    LARGO,
    MECANICO,
    _backend,
    _enfriar,
    _estado_fichero,
    _fallo,
    _ok,
    _texto,
    _ultimo_evento,
)

from local_delegate import enfriamiento, server
from local_delegate.fallos import Clase

CAMPOS_NUEVOS = ("model_requested", "fallback_reason", "fallback_class", "error_class")


# --- El log ------------------------------------------------------------------------------------


@backend_mock.mock
def test_el_log_registra_pedido_respondido_y_la_causa_del_salto(recargar_config, tmp_path):
    recargar_config()
    _backend({LARGO: _fallo(500), MECANICO: _ok("resumen")})

    server.local_summarize(text=_texto(10_000))

    evento = _ultimo_evento(tmp_path)
    assert evento["model"] == MECANICO, "`model` es el que respondió"
    assert evento["model_requested"] == LARGO
    assert evento["fallback_reason"] == "http_500"
    assert evento["fallback_class"] == "modelo"
    assert evento["chunks"] == 2, "la llamada del respaldo también cuenta"
    assert "error_class" not in evento


@backend_mock.mock
def test_en_trozos_chunks_cuenta_tambien_las_llamadas_del_respaldo(recargar_config, tmp_path):
    recargar_config()
    _backend({LARGO: [_ok("uno"), _fallo(500)], MECANICO: _ok("otro")})

    server.local_translate(target_lang="inglés", text=_texto(12_000))

    evento = _ultimo_evento(tmp_path)
    assert evento["chunks"] == 5  # largo, largo que falla, y tres del residente
    assert evento["model"] == MECANICO
    assert evento["model_requested"] == LARGO


@backend_mock.mock
def test_sin_salto_el_evento_se_escribe_como_antes(recargar_config, tmp_path):
    recargar_config()
    _backend({MECANICO: _ok("a")})

    server.local_classify(text="hola", labels=["a", "b"])

    evento = _ultimo_evento(tmp_path)
    assert evento["model"] == MECANICO
    assert not any(campo in evento for campo in (*CAMPOS_NUEVOS, "chunks"))


@backend_mock.mock
def test_el_razonamiento_agotado_queda_como_causa_de_configuracion(recargar_config, tmp_path):
    recargar_config()
    agotado = httpx2.Response(
        200,
        json={
            "choices": [
                {"message": {"content": "", "reasoning_content": "x"}, "finish_reason": "length"}
            ]
        },
    )
    _backend({MECANICO: agotado})

    server.local_classify(text="hola", labels=["a", "b"])

    evento = _ultimo_evento(tmp_path)
    assert evento["error_class"] == "configuracion"
    assert evento["error"] == "config_max_tokens"
    assert "model_requested" not in evento


@backend_mock.mock
def test_el_salto_por_enfriamiento_se_registra_con_su_causa(recargar_config, tmp_path):
    recargar_config()
    _enfriar(tmp_path, CODIGO)
    _backend({MECANICO: _ok("explicado")})

    server.local_explain_code(code="x = 1")

    evento = _ultimo_evento(tmp_path)
    assert evento["model"] == MECANICO
    assert evento["model_requested"] == CODIGO
    assert evento["fallback_class"] == "enfriamiento"
    assert "chunks" not in evento, "el modelo enfriado no se llamó: una sola llamada"


@backend_mock.mock
def test_en_map_reduce_el_salto_tambien_queda_en_el_log(recargar_config, tmp_path):
    recargar_config()
    _backend({CODIGO: _fallo(500), MECANICO: _ok("- a: cambia")})
    diff = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n" + "+linea de codigo nueva\n" * 200 for i in range(6)
    )

    server.local_commit_msg(diff=diff)

    evento = _ultimo_evento(tmp_path)
    assert evento["model"] == MECANICO and evento["model_requested"] == CODIGO
    assert evento["fallback_class"] == "modelo"


# --- local_status ------------------------------------------------------------------------------


@pytest.fixture
def status_sin_red(monkeypatch):
    """`local_status` consulta backend, GPU y llama-swap: aquí solo interesa lo que dice del estado."""
    monkeypatch.setattr(server, "_models_with_status", lambda: (False, []))
    for nombre in ("_vram_info", "_ram_info", "_llamaswap_running", "_llamaswap_groups"):
        monkeypatch.setattr(server, nombre, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)


def _linea_de(texto: str, modelo: str) -> str:
    lineas = [linea for linea in texto.splitlines() if modelo in linea and "quedan" in linea]
    assert len(lineas) == 1, texto
    return lineas[0]


def test_local_status_lista_el_modelo_enfriado_con_lo_que_le_queda(
    recargar_config, tmp_path, status_sin_red
):
    recargar_config()
    estado = enfriamiento.desde_config()
    for _ in range(3):
        estado.registrar_fallo(CODIGO, Clase.MODELO)

    linea = _linea_de(server.local_status(), CODIGO)

    assert "1 vez seguida" in linea
    restante = int(linea.split("quedan ")[1].split(" s")[0])
    assert 100 <= restante <= 120


def test_local_status_cuenta_las_reentradas_seguidas(recargar_config, tmp_path, status_sin_red):
    recargar_config()
    vencido = {CODIGO: {"fallos": 0, "espera_s": 120.0, "hasta": time.time() - 1, "reentradas": 1}}
    _estado_fichero(tmp_path).write_text(json.dumps(vencido), encoding="utf-8")
    enfriamiento.desde_config().registrar_fallo(CODIGO, Clase.MODELO)

    linea = _linea_de(server.local_status(), CODIGO)

    assert "2 veces seguidas" in linea
    assert int(linea.split("quedan ")[1].split(" s")[0]) > 120, "la espera se dobló"


def test_local_status_sin_enfriados_lo_dice(recargar_config, tmp_path, status_sin_red):
    recargar_config()

    texto = server.local_status()

    assert "Enfriamiento: encendido" in texto
    assert "ningún modelo enfriado" in texto


def test_local_status_con_el_enfriamiento_apagado_lo_dice(
    recargar_config, tmp_path, status_sin_red
):
    recargar_config(LOCAL_DELEGATE_COOLDOWN="0")
    _enfriar(tmp_path, CODIGO)

    texto = server.local_status()

    assert "Enfriamiento: apagado" in texto
    assert "quedan" not in texto
