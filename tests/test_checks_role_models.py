"""`service.role_models`: each role's model id against the ids `/models` lists.

A role whose model the backend does not serve passed `doctor` as healthy, and every tool of that
role failed later with the backend's «model not found». The `/models` here is always simulated: a
fake `backend_models`, a fake answer of the daemon, or a fake `httpx2.Client` for the direct probe.
"""

from __future__ import annotations

import backend_mock
import httpx2
import pytest
from conftest import make_home
from fastapi.testclient import TestClient
from test_checks import make_ctx, result_for

from local_delegate import backend_params, checks, config, failures, i18n, probes

# At import time and not inside the test: `backend_mock.mock` swaps `httpx2.Client` for a function
# while the test runs, and `TestClient` subclasses it when its module is first imported.
from local_delegate.web import metrics

ROLES = {"mechanical": "mech-a", "long": "long-b", "code": "code-c", "vision": "vision-d"}


@pytest.fixture(autouse=True)
def _role_models(monkeypatch):
    """Known ids for the four roles, so no test depends on the defaults of the day."""
    for role, model in ROLES.items():
        monkeypatch.setattr(config, checks.ROLE_MODEL_VARS[role][0], model)


def _ctx(tmp_path, models, *, healthy=True, source="direct"):
    view = failures.BackendView(healthy, "" if healthy else "no responde", None, source, models)
    return make_ctx(make_home(tmp_path), backend_models=lambda: view)


def test_every_role_has_its_variable():
    """A role added to `ROLES` without its variable would be skipped in silence."""
    assert set(checks.ROLE_MODEL_VARS) == set(backend_params.ROLES)
    for attribute, variable in checks.ROLE_MODEL_VARS.values():
        assert hasattr(config, attribute)
        assert variable == f"LOCAL_DELEGATE_{attribute}"


def test_all_roles_served_is_ok(tmp_path):
    r = result_for("service.role_models", _ctx(tmp_path, tuple(ROLES.values()) + ("other",)))
    assert r.status == checks.OK
    assert "code: code-c" in r.detail


@pytest.mark.parametrize("role", ["mechanical", "long", "code"])
def test_a_text_role_missing_is_warn_with_id_and_variable(tmp_path, role):
    served = tuple(m for r, m in ROLES.items() if r != role)
    r = result_for("service.role_models", _ctx(tmp_path, served))
    assert r.status == checks.WARN
    assert checks.is_warning(r.status)
    assert f"{role}: {ROLES[role]}" in r.detail
    assert checks.ROLE_MODEL_VARS[role][1] in r.fix_hint


def test_two_missing_names_both_variables(tmp_path):
    r = result_for("service.role_models", _ctx(tmp_path, ("mech-a", "vision-d")))
    assert r.status == checks.WARN
    assert "LOCAL_DELEGATE_MODEL_LONG" in r.fix_hint
    assert "LOCAL_DELEGATE_MODEL_CODE" in r.fix_hint
    assert "LOCAL_DELEGATE_MODEL_MECHANICAL" not in r.fix_hint


def test_only_vision_missing_is_ok_with_a_note(tmp_path):
    """Vision only serves `local_describe_image`: a backend without an image model is valid."""
    r = result_for("service.role_models", _ctx(tmp_path, ("mech-a", "long-b", "code-c")))
    assert r.status == checks.OK
    assert "vision: vision-d" in r.detail
    assert "LOCAL_DELEGATE_MODEL_VISION" in r.detail


def test_a_role_without_a_model_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_CODE", "")
    r = result_for("service.role_models", _ctx(tmp_path, ("mech-a", "long-b", "vision-d")))
    assert r.status == checks.OK
    assert "code" not in r.detail


def test_an_alias_listed_by_models_counts(tmp_path, monkeypatch):
    """llama-swap lists aliases with `includeAliasesInList`; the id the role uses is one of them."""
    monkeypatch.setattr(config, "MODEL_LONG", "long-alias")
    served = ("mech-a", "long-b", "long-alias", "code-c", "vision-d")
    assert result_for("service.role_models", _ctx(tmp_path, served)).status == checks.OK


def test_an_id_without_tag_counts_as_its_latest_tag(tmp_path, monkeypatch):
    """Ollama lists `llama3.1:latest` and answers a request for `llama3.1` (config.py documents it)."""
    monkeypatch.setattr(config, "MODEL_MECHANICAL", "llama3.1")
    served = ("llama3.1:latest", "long-b", "code-c", "vision-d")
    assert result_for("service.role_models", _ctx(tmp_path, served)).status == checks.OK


def test_a_tagged_id_does_not_match_another_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_MECHANICAL", "llama3.1:8b")
    served = ("llama3.1:latest", "long-b", "code-c", "vision-d")
    assert result_for("service.role_models", _ctx(tmp_path, served)).status == checks.WARN


def test_a_text_role_and_vision_missing_warn_without_the_vision_variable(tmp_path):
    r = result_for("service.role_models", _ctx(tmp_path, ("mech-a", "long-b")))
    assert r.status == checks.WARN
    assert "code: code-c" in r.detail
    assert "vision: vision-d" in r.detail
    assert "LOCAL_DELEGATE_MODEL_CODE" in r.fix_hint
    assert "LOCAL_DELEGATE_MODEL_VISION" not in r.fix_hint


def test_an_empty_list_warns_for_every_text_role(tmp_path):
    r = result_for("service.role_models", _ctx(tmp_path, ()))
    assert r.status == checks.WARN
    for variable in ("MECHANICAL", "LONG", "CODE"):
        assert f"LOCAL_DELEGATE_MODEL_{variable}" in r.fix_hint


def test_backend_down_or_no_list_is_unknown(tmp_path):
    down = result_for("service.role_models", _ctx(tmp_path / "a", None, healthy=False))
    no_list = result_for("service.role_models", _ctx(tmp_path / "b", None))
    no_list_daemon = result_for("service.role_models", _ctx(tmp_path / "c", None, source="daemon"))
    assert {down.status, no_list.status, no_list_daemon.status} == {checks.UNKNOWN}
    assert len({down.detail, no_list.detail, no_list_daemon.detail}) == 3
    # The direct probe has no daemon in the middle: its text does not blame one.
    assert "daemon" not in no_list.detail
    assert "daemon" in no_list_daemon.detail


def test_one_doctor_run_probes_the_backend_once(tmp_path):
    calls = []

    def backend():
        calls.append(1)
        return failures.BackendView(True, "", None, "direct", tuple(ROLES.values()))

    ctx = make_ctx(make_home(tmp_path), backend_models=backend)
    results = {c.id: r for c, r in checks.run_all(ctx)}
    assert results["service.backend"].status == checks.OK
    assert results["service.role_models"].status == checks.OK
    assert calls == [1]


# --- Where the ids come from: the daemon and the direct probe -----------------------------------


def _daemon_ctx(tmp_path, monkeypatch, seen):
    from local_delegate import daemon

    monkeypatch.setattr(daemon, "query_backend", lambda host, port, timeout=1.0: seen)
    return make_ctx(make_home(tmp_path), backend_models=checks._default_backend_models)


def test_the_ids_come_from_the_daemon(tmp_path, monkeypatch):
    models = [{"id": m, "status": "loaded"} for m in ("mech-a", "long-b", "vision-d")]
    ctx = _daemon_ctx(
        tmp_path, monkeypatch, {"available": True, "models": models, "models_stale": False}
    )
    r = result_for("service.role_models", ctx)
    assert r.status == checks.WARN
    assert "code: code-c" in r.detail


def test_the_roles_are_the_daemons_when_it_sends_them(tmp_path, monkeypatch):
    """`LOCAL_DELEGATE_MODEL_CODE` only in the daemon's launcher: this console has another id."""
    daemon_roles = {**ROLES, "code": "daemon-code"}
    models = [{"id": m, "status": "loaded"} for m in daemon_roles.values()]
    seen = {"available": True, "models": models, "role_models": daemon_roles}
    r = result_for("service.role_models", _daemon_ctx(tmp_path / "a", monkeypatch, seen))
    assert r.status == checks.OK
    assert "code: daemon-code" in r.detail
    assert "daemon" in r.detail

    # And the other way: the console's id is served, the daemon's is not.
    models = [{"id": m, "status": "loaded"} for m in ROLES.values()]
    seen = {"available": True, "models": models, "role_models": daemon_roles}
    r = result_for("service.role_models", _daemon_ctx(tmp_path / "b", monkeypatch, seen))
    assert r.status == checks.WARN
    assert "code: daemon-code" in r.detail


def test_an_older_daemon_without_roles_uses_this_console_and_says_so(tmp_path, monkeypatch):
    models = [{"id": m, "status": "loaded"} for m in ROLES.values()]
    r = result_for(
        "service.role_models",
        _daemon_ctx(tmp_path, monkeypatch, {"available": True, "models": models}),
    )
    assert r.status == checks.OK
    assert i18n.t("doctor.probe.role_models.from_console") in r.detail


@backend_mock.mock
def test_the_daemon_endpoint_sends_its_role_models(monkeypatch):
    """`/api/backend` carries the ids and each role's model with the daemon's config."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(
        return_value=httpx2.Response(200, json={"data": [{"id": "mech-a"}]})
    )
    backend_mock.get("http://test-backend/running").mock(
        return_value=httpx2.Response(200, json={"running": []})
    )
    body = TestClient(metrics.app).get("/api/backend").json()
    assert body["role_models"] == ROLES
    assert failures.model_ids(body["models"]) == ("mech-a",)


def test_a_daemon_without_models_is_unknown(tmp_path, monkeypatch):
    ctx = _daemon_ctx(tmp_path, monkeypatch, {"available": True})
    assert result_for("service.role_models", ctx).status == checks.UNKNOWN
    assert result_for("service.backend", ctx).status == checks.OK


class _Response:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.is_success = 200 <= status < 300

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _fake_client(monkeypatch, response):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers=None):
            assert url.endswith("/models")
            return response

    monkeypatch.setattr(httpx2, "Client", Client)


def test_the_direct_probe_reads_the_ids_of_a_cloud_backend(monkeypatch):
    """An OpenAI-compatible `/models`: `{"object": "list", "data": [{"id": ...}]}`."""
    monkeypatch.setattr(config, "BASE_URL", "https://api.example.com/v1")
    body = {"object": "list", "data": [{"id": "mech-a", "object": "model"}, "junk", {"id": 3}]}
    _fake_client(monkeypatch, _Response(body))
    view = probes.backend_probe()
    assert view.healthy
    assert view.models == ("mech-a",)


def test_the_direct_probe_with_a_body_without_list_keeps_healthy(monkeypatch):
    _fake_client(monkeypatch, _Response(ValueError("not json")))
    view = probes.backend_probe()
    assert view.healthy
    assert view.models is None


def test_model_ids_is_none_when_not_a_list():
    assert failures.model_ids(None) is None
    assert failures.model_ids({"id": "x"}) is None
    assert failures.model_ids([]) == ()
