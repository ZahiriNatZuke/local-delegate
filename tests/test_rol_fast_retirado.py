"""El rol `fast` se retira en la 0.30.0, y no en silencio.

Por qué se retira: **no tenía carga real**. Medido el 2026-09-15 sobre el log de uso —que cubre
también las llamadas de la Mac, porque delega en el backend de esta PC—: 5 registros de `qwen35-2b`
sobre 164, y 3 de esos 5 eran del test de concurrencia. Los otros 2 fueron `local_delegate` con
`model` explícito, ambos del 23 de julio. Ninguna tool lo enrutaba: `MODEL_FAST` solo aparecía en la
lista que imprime `local_status`, en la fila del panel y en una cadena de respaldo inalcanzable.

Retirar un rol tiene **dos superficies visibles**, y las dos se prueban aquí:

1. **Pedir su modelo da un error claro**, con la lista de válidos, y sin gastar backend. Sale gratis
   —el modelo deja de estar en `ALLOWED_MODELS`— pero justo por eso hay que fijarlo con un test: si
   alguien lo devolviera al catálogo «por compatibilidad», el error se volvería silencio.
2. **Las tres variables huérfanas no se ignoran calladas.** `LOCAL_DELEGATE_MODEL_FAST`,
   `LOCAL_DELEGATE_MAX_CHARS_FAST` y `LOCAL_DELEGATE_FALLBACK_FAST` dejan de tener efecto, y quien
   las tenga puestas merece enterarse. Se avisa desde `doctor` y no rompiendo el arranque: romperlo
   dejaría sin servicio a quien actualice con la variable puesta, que es justo el que no hizo nada
   malo.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2
from fastapi.testclient import TestClient

from local_delegate import cadenas, checks, config, server
from local_delegate.web import metrics

MODELO_RETIRADO = "qwen35-2b"
VARIABLES_RETIRADAS = (
    "LOCAL_DELEGATE_MODEL_FAST",
    "LOCAL_DELEGATE_MAX_CHARS_FAST",
    "LOCAL_DELEGATE_FALLBACK_FAST",
)


# --- El rol ya no existe en ningún catálogo -----------------------------------
def test_el_rol_rapido_no_esta_en_el_catalogo_de_roles(recargar_config):
    recargar_config()
    assert "fast" not in config.modelos_por_rol()
    assert set(config.modelos_por_rol()) == {"mechanical", "long", "code"}


def test_el_rol_rapido_no_tiene_tope_propio(recargar_config):
    """Si se quedara el tope sin el rol, `max_chars_for_role('fast')` mentiría con 12 000."""
    recargar_config()
    assert "fast" not in config.MAX_CHARS_POR_ROL
    # Un rol que no existe cae en el default, como cualquier otro nombre desconocido.
    assert config.max_chars_for_role("fast") == config.max_chars_for_role("no-existe-este-rol")


def test_el_modelo_del_rol_retirado_sale_del_catalogo(recargar_config):
    recargar_config()
    assert MODELO_RETIRADO not in config.ALLOWED_MODELS
    assert config.ALLOWED_MODELS == {config.MODEL_MECHANICAL, config.MODEL_LONG, config.MODEL_CODE}


@backend_mock.mock
def test_el_panel_no_ensena_la_fila_del_rol_rapido(monkeypatch):
    """El dashboard es la otra superficie que lista roles, y se desincroniza sola."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(
        return_value=httpx2.Response(200, json={"data": [], "object": "list"})
    )
    data = TestClient(metrics.app).get("/api/status").json()

    roles = {c["role"] for c in data["catalog"]}
    assert roles == {"mechanical", "long", "code", "vision"}


def test_las_cadenas_de_respaldo_no_declaran_el_rol_rapido(recargar_config):
    """La fila «rápido -> residente -> largo» de REQ-004 era inalcanzable: se va con el rol."""
    recargar_config()
    assert "fast" not in cadenas.ROLES_DE_TEXTO
    assert "fast" not in cadenas.CADENAS_POR_DEFECTO


def test_una_cadena_que_nombre_el_rol_retirado_se_ignora_y_doctor_lo_dice(
    recargar_config, tmp_path
):
    """Nombrar `fast` en una cadena pasa a ser un error de tecleo como cualquier otro."""
    recargar_config(LOCAL_DELEGATE_FALLBACK_CODE="fast")
    assert cadenas.resolver("code").ignorados == ("fast",)
    assert checks._probe_fallback(checks.Context(home=tmp_path)).status == checks.WARN


# --- Pedir su modelo: error claro, y sin gastar backend -----------------------
def _responde(valor):
    def _fn(mensaje, modelo):
        campo = next(iter(modelo.model_fields))
        return modelo(**{campo: valor})

    return _fn


def _no_responde(mensaje, modelo):
    return None


@backend_mock.mock
def _delegar(monkeypatch, tmp_path, **kw):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    vistos: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        vistos.append(json.loads(request.content))
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    args = {"task": "t", "input": "i", "output_format": "bullets"}
    args.update(kw)
    return server.local_delegate(**args), vistos


def test_pedir_el_modelo_retirado_da_error_claro_y_no_toca_el_backend(monkeypatch, tmp_path):
    """Lo que ve quien tenía una llamada con `model="qwen35-2b"` escrita a mano."""
    monkeypatch.setattr(server.preguntas, "preguntar", _no_responde)
    resultado, vistos = _delegar(monkeypatch, tmp_path, model=MODELO_RETIRADO)

    assert f"modelo inválido '{MODELO_RETIRADO}'" in resultado
    # El error nombra la alternativa: un error claro dice qué hacer, no solo que no.
    assert config.MODEL_MECHANICAL in resultado
    assert vistos == [], "se llamó al backend con el modelo de un rol retirado"


def test_el_modelo_retirado_tampoco_vale_como_respuesta_a_la_pregunta(monkeypatch, tmp_path):
    """El escape de `elicitation` no puede colar por la ventana lo que se retiró por la puerta."""
    monkeypatch.setattr(server.preguntas, "preguntar", _responde(MODELO_RETIRADO))
    resultado, vistos = _delegar(monkeypatch, tmp_path, model="no-existe")

    assert "modelo inválido" in resultado
    assert vistos == []


# --- Las variables huérfanas: `doctor` avisa ----------------------------------
def test_sin_variables_del_rol_retirado_el_check_esta_en_ok(recargar_config, tmp_path):
    """Control: el caso normal —nadie las tiene puestas— no puede dar aviso."""
    recargar_config()
    resultado = checks._probe_rol_retirado(checks.Context(home=tmp_path))
    assert resultado.status == checks.OK


def test_cada_variable_del_rol_retirado_se_avisa_por_su_nombre(recargar_config, tmp_path):
    """Una por una, y no «alguna»: el aviso tiene que decir cuál quitar."""
    for variable in VARIABLES_RETIRADAS:
        recargar_config(**{variable: "lo-que-sea"})
        resultado = checks._probe_rol_retirado(checks.Context(home=tmp_path))
        assert resultado.status == checks.WARN, f"{variable} puesta no dio aviso"
        assert variable in resultado.detail
        assert "0.30.0" in resultado.detail or "0.30.0" in resultado.fix_hint


def test_el_aviso_las_nombra_todas_cuando_estan_las_tres(recargar_config, tmp_path):
    recargar_config(**dict.fromkeys(VARIABLES_RETIRADAS, "lo-que-sea"))
    detalle = checks._probe_rol_retirado(checks.Context(home=tmp_path)).detail
    assert all(v in detalle for v in VARIABLES_RETIRADAS)


def test_el_check_esta_en_el_registro(recargar_config):
    """Un probe fuera del registro no lo ejecuta nadie: `doctor` no lo llamaría jamás."""
    ids = [c.id for c in checks.CHECKS]
    assert "config.rol_retirado" in ids
    # Y en un grupo que no sale a la red: solo mira variables de entorno.
    check = next(c for c in checks.CHECKS if c.id == "config.rol_retirado")
    assert check.group == "entorno"
