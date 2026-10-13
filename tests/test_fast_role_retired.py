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

from local_delegate import chains, checks, config, server
from local_delegate.web import metrics

RETIRED_MODEL = "qwen35-2b"
RETIRED_VARIABLES = (
    "LOCAL_DELEGATE_MODEL_FAST",
    "LOCAL_DELEGATE_MAX_CHARS_FAST",
    "LOCAL_DELEGATE_FALLBACK_FAST",
)


# --- El rol ya no existe en ningún catálogo -----------------------------------
def test_the_fast_role_is_not_in_the_role_catalog(reload_config):
    reload_config()
    assert "fast" not in config.models_by_role()
    assert set(config.models_by_role()) == {"mechanical", "long", "code"}


def test_the_fast_role_has_no_cap_of_its_own(reload_config):
    """Si se quedara el tope sin el rol, `max_chars_for_role('fast')` mentiría con 12 000."""
    reload_config()
    assert "fast" not in config.MAX_CHARS_BY_ROLE
    # Un rol que no existe cae en el default, como cualquier otro nombre desconocido.
    assert config.max_chars_for_role("fast") == config.max_chars_for_role("no-existe-este-rol")


def test_the_retired_role_model_leaves_the_catalog(reload_config):
    reload_config()
    assert RETIRED_MODEL not in config.ALLOWED_MODELS
    assert config.ALLOWED_MODELS == {config.MODEL_MECHANICAL, config.MODEL_LONG, config.MODEL_CODE}


@backend_mock.mock
def test_the_panel_does_not_show_the_fast_role_row(monkeypatch):
    """El dashboard es la otra superficie que lista roles, y se desincroniza sola."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(
        return_value=httpx2.Response(200, json={"data": [], "object": "list"})
    )
    data = TestClient(metrics.app).get("/api/status").json()

    roles = {c["role"] for c in data["catalog"]}
    assert roles == {"mechanical", "long", "code", "vision"}


def test_the_fallback_chains_do_not_declare_the_fast_role(reload_config):
    """La fila «rápido -> residente -> largo» de REQ-004 era inalcanzable: se va con el rol."""
    reload_config()
    assert "fast" not in chains.TEXT_ROLES
    assert "fast" not in chains.DEFAULT_CHAINS


def test_a_chain_naming_the_retired_role_is_ignored_and_doctor_says_so(reload_config, tmp_path):
    """Nombrar `fast` en una cadena pasa a ser un error de tecleo como cualquier otro."""
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="fast")
    assert chains.resolve("code").ignored == ("fast",)
    assert checks._probe_fallback(checks.Context(home=tmp_path)).status == checks.WARN


# --- Pedir su modelo: error claro, y sin gastar backend -----------------------
def _reply(value):
    def _fn(message, model):
        field = next(iter(model.model_fields))
        return model(**{field: value})

    return _fn


def _no_answer(message, model):
    return None


@backend_mock.mock
def _delegate(monkeypatch, tmp_path, **kw):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    seen: list[dict] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    backend_mock.post("http://test-backend/v1/chat/completions").mock(side_effect=_handler)
    args = {"task": "t", "input": "i", "output_format": "bullets"}
    args.update(kw)
    return server.local_delegate(**args), seen


def test_requesting_the_retired_model_gives_a_clear_error_and_does_not_touch_the_backend(
    monkeypatch, tmp_path
):
    """Lo que ve quien tenía una llamada con `model="qwen35-2b"` escrita a mano."""
    monkeypatch.setattr(server.questions, "ask", _no_answer)
    result, seen = _delegate(monkeypatch, tmp_path, model=RETIRED_MODEL)

    assert f"modelo inválido '{RETIRED_MODEL}'" in result
    # El error nombra la alternativa: un error claro dice qué hacer, no solo que no.
    assert config.MODEL_MECHANICAL in result
    assert seen == [], "se llamó al backend con el modelo de un rol retirado"


def test_the_retired_model_is_not_valid_as_an_answer_to_the_question_either(monkeypatch, tmp_path):
    """El escape de `elicitation` no puede colar por la ventana lo que se retiró por la puerta."""
    monkeypatch.setattr(server.questions, "ask", _reply(RETIRED_MODEL))
    result, seen = _delegate(monkeypatch, tmp_path, model="no-existe")

    assert "modelo inválido" in result
    assert seen == []


# --- Las variables huérfanas: `doctor` avisa ----------------------------------
def test_without_retired_role_variables_the_check_is_ok(reload_config, tmp_path):
    """Control: el caso normal —nadie las tiene puestas— no puede dar aviso."""
    reload_config()
    result = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    assert result.status == checks.OK


def test_each_retired_role_variable_is_warned_by_name(reload_config, tmp_path):
    """Una por una, y no «alguna»: el aviso tiene que decir cuál quitar."""
    for variable in RETIRED_VARIABLES:
        reload_config(**{variable: "lo-que-sea"})
        result = checks._probe_deprecated_names(checks.Context(home=tmp_path))
        assert result.status == checks.WARN, f"{variable} puesta no dio aviso"
        assert variable in result.detail
        assert "0.30.0" in result.detail or "0.30.0" in result.fix_hint


def test_the_warning_names_them_all_when_all_three_are_there(reload_config, tmp_path):
    reload_config(**dict.fromkeys(RETIRED_VARIABLES, "lo-que-sea"))
    detail = checks._probe_deprecated_names(checks.Context(home=tmp_path)).detail
    assert all(v in detail for v in RETIRED_VARIABLES)


def test_the_check_is_in_the_registry(reload_config):
    """Un probe fuera del registro no lo ejecuta nadie: `doctor` no lo llamaría jamás.

    Desde la ola A0 del renombrado es el check general de nombres obsoletos (REQ-003), que
    sustituye a `config.rol_retirado` sin cambiar lo que avisa.
    """
    ids = [c.id for c in checks.CHECKS]
    assert "config.deprecated_names" in ids
    assert "config.rol_retirado" not in ids
    # Y en un grupo que no sale a la red: solo mira el entorno y ficheros locales.
    check = next(c for c in checks.CHECKS if c.id == "config.deprecated_names")
    assert check.group == "environment"


def test_retired_variable_in_settings_json_env_is_also_warned(reload_config, tmp_path):
    """Los hooks heredan de `env` de `settings.json`, que `doctor` no ve en su propia shell."""
    reload_config()
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"env": {"LOCAL_DELEGATE_MAX_CHARS_FAST": "9000", "OTRA": "1"}}),
        encoding="utf-8",
    )
    result = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    assert result.status == checks.WARN, "la variable del env de settings.json no dio aviso"
    assert "LOCAL_DELEGATE_MAX_CHARS_FAST" in result.detail
    assert "settings.json" in result.detail
    assert "OTRA" not in result.detail


def test_retired_variables_come_from_the_single_registry(reload_config):
    """Una sola fuente: `config` no escribe la lista a mano, la toma de `deprecations`."""
    from local_delegate import deprecations

    reload_config()
    retired = {e.old for e in deprecations.DEPRECATED_NAMES if e.is_retired}
    assert retired == set(RETIRED_VARIABLES)
    assert set(config.RETIRED_FAST_ROLE_VARIABLES) == retired
    assert retired <= config.ENVIRONMENT_VARIABLES
