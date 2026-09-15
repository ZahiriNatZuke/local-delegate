"""Clasificación contra respuestas REALES del backend (REQ-020), no escritas a mano.

Las fixtures de `tests/fixtures/backend/` se capturaron el 2026-09-15 contra llama-swap v255 y
llama-server b10909 (protocolo-f2.md §10, sesión 8), con la clase esperada escrita ANTES de capturar.
Cada una lleva sus versiones: si el backend cambia, se recapturan, no se retocan.

Lo que ve el cliente se reconstruye igual que en `_post_chat`: una respuesta HTTP se convierte en
`Respuesta` con el cuerpo recortado a 300 caracteres, y un `ReadTimeout` se clasifica con la señal
de carga que daba `/running` al vencer.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest

from local_delegate.fallos import Clase, Respuesta, clasificar

FIXTURES = Path(__file__).parent / "fixtures" / "backend"


def _captura(nombre: str) -> dict:
    return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))


def _modelo_cargado_al_terminar(doc: dict) -> bool | None:
    """La señal de REQ-018 tal como la dio llama-swap cuando la petición terminó."""
    modelo = doc["peticion"]["model"]
    for entrada in doc["running_al_terminar"].get("running", []):
        if entrada.get("model") == modelo:
            return entrada.get("state") == "ready"
    return None


def _clasificar_captura(doc: dict) -> Clase | None:
    if "excepcion" in doc:
        assert doc["excepcion"]["tipo"] == "ReadTimeout", (
            "solo se capturó ReadTimeout como excepción"
        )
        return clasificar(
            httpx2.ReadTimeout(doc["excepcion"]["mensaje"]),
            modelo_cargado=_modelo_cargado_al_terminar(doc),
        )
    respuesta = doc["respuesta"]
    return clasificar(
        Respuesta(
            status=respuesta["status"], datos=respuesta["json"], texto=respuesta["texto"][:300]
        )
    )


def test_todas_las_capturas_llevan_version_y_clase_esperada():
    capturas = sorted(FIXTURES.glob("*.json"))
    assert len(capturas) == 6, "se capturaron seis casos; si cambia el número, cambia este test"
    for ruta in capturas:
        doc = json.loads(ruta.read_text(encoding="utf-8"))
        assert doc["versiones"] == {
            "llama-swap": "v255 (7761aa1)",
            "llama-server": "b10909 (a2878d30d)",
        }
        assert doc["clase_esperada"], ruta.name


@pytest.mark.parametrize("nombre", ["oom-con-perfil", "error-carga"])
def test_el_modelo_que_no_se_puede_montar_es_de_capacidad(nombre):
    """OOM con la política del driver y modelo inexistente: llama-swap da el MISMO 500 a los dos."""
    doc = _captura(nombre)
    assert doc["clase_esperada"] == Clase.CAPACIDAD.value
    assert _clasificar_captura(doc) is Clase.CAPACIDAD


def test_el_timeout_durante_la_carga_es_de_capacidad():
    """`/running` decía `starting` al vencer: no se le cuenta el fallo a un modelo lento de montar."""
    doc = _captura("timeout-durante-carga")
    assert _modelo_cargado_al_terminar(doc) is False
    assert _clasificar_captura(doc) is Clase.CAPACIDAD


def test_el_mismo_timeout_con_el_modelo_ya_cargado_seria_de_lectura():
    """Control positivo del anterior: la misma captura con la señal cambiada cambia de clase."""
    doc = _captura("timeout-durante-carga")
    assert (
        clasificar(httpx2.ReadTimeout(doc["excepcion"]["mensaje"]), modelo_cargado=True)
        is Clase.TIMEOUT_LECTURA
    )


def test_la_peticion_durante_la_carga_termina_bien_y_no_es_un_fallo():
    doc = _captura("peticion-durante-carga")
    estados = [
        entrada["state"]
        for muestra in doc["muestras_running"]
        for entrada in muestra["running"].get("running", [])
    ]
    assert "starting" in estados, "la captura tiene que haber visto la carga en curso"
    assert _modelo_cargado_al_terminar(doc) is True
    assert _clasificar_captura(doc) is None


def test_el_oom_sin_perfil_no_llego_a_timeout_y_queda_sin_capturar():
    """Sin la política el modelo desbordó y RESPONDIÓ (200 en 8 s): no hay `ReadTimeout` que clasificar.

    La clase esperada (`timeout_lectura`) queda sin prueba real; este test fija que la captura no la
    demuestra, para que nadie la cite como si lo hiciera.
    """
    doc = _captura("oom-sin-perfil")
    assert doc["clase_esperada"] == Clase.TIMEOUT_LECTURA.value
    assert "excepcion" not in doc
    assert doc["respuesta"]["status"] == 200
    assert _clasificar_captura(doc) is None


def test_el_razonamiento_que_agota_max_tokens_es_de_configuracion():
    """La captura real llega con `content: ""` (no nulo), `finish_reason: length` y razonamiento."""
    doc = _captura("length-con-razonamiento")
    mensaje = doc["respuesta"]["json"]["choices"][0]["message"]
    assert mensaje["content"] == "", "la captura es la que destapó el vacío: si cambia, recapturar"
    assert mensaje["reasoning_content"].strip()
    assert _clasificar_captura(doc) is Clase.CONFIGURACION


def test_un_500_de_llama_swap_que_no_es_de_carga_sigue_siendo_del_modelo():
    """Control positivo del patrón: otro 500 del mismo origen, sin el texto de carga, no es capacidad."""
    cuerpo = '{"src":"llama-swap","error":{"message":"upstream error","type":"server_error"}}'
    assert clasificar(Respuesta(status=500, texto=cuerpo)) is Clase.MODELO


def test_ninguna_captura_lleva_rutas_ni_credenciales():
    """`personal-security-check` busca datos personales, no cabeceras: esto lo comprueba aquí."""
    for ruta in FIXTURES.glob("*.json"):
        texto = ruta.read_text(encoding="utf-8")
        for fuga in ("Projects", "Users", "Authorization", "Bearer", "apiKey"):
            assert fuga not in texto, f"{ruta.name} contiene {fuga!r}"
