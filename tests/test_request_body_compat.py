"""REQ-022 (SDD `backend-extra-params`, T1): sin parámetros, el cuerpo es el de hoy.

Cada camino que llega al backend se corre contra un backend falso (`server._post_chat` parcheado)
y su cuerpo se compara, **con el orden de claves**, con la fixture que generó
`scripts/capture_request_bodies.py` sobre `f2dd267`, antes de tocar `server.py`. Del evento del log
de uso se compara el **conjunto** de claves, no los valores (la latencia y la hora cambian).

La comparación es de JSON parseado con `object_pairs_hook=list`: dos cuerpos con las mismas claves
en otro orden son distintos, y un `1` frente a un `1.0` también.

`MODES` es el eje «sin parámetros» (REQ-022): sin fichero de parámetros, con
`{"version": 1, "roles": {}}` y con un rol vacío (`{"code": {}}`). Los tres deben dar exactamente
estos cuerpos (T10).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from local_delegate import backend_params

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "capture_request_bodies.py"
FIXTURES = ROOT / "tests" / "fixtures" / "request_bodies"
#: El commit de `main` cuyo cuerpo se congeló (REQ-022).
BASE_COMMIT = "f2dd267"

# Mismo criterio que `test_ci_gate.py`: `scripts/` no viaja en el sdist.
if not SCRIPT.is_file():
    pytest.skip(
        "scripts/ no está en el árbol (sdist): estas pruebas necesitan el repositorio",
        allow_module_level=True,
    )


def _load_script():
    spec = importlib.util.spec_from_file_location("capture_request_bodies", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture_request_bodies = _load_script()
PATHS = capture_request_bodies.PATHS
#: «Sin parámetros» en todas sus formas: el documento que se escribe en `LOG_DIR` (o ninguno).
_DOCUMENTS: dict[str, dict | None] = {
    "no_file": None,
    "empty_roles": {"version": 1, "roles": {}},
    "empty_role": {"version": 1, "roles": {"code": {}}},
}
MODES = tuple(_DOCUMENTS)


def _fixture(name: str) -> dict:
    text = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    return json.loads(text, object_pairs_hook=list)


def _field(pairs: list, key: str):
    """El valor de `key` en un objeto leído como lista de pares."""
    return next(value for k, value in pairs if k == key)


@pytest.fixture
def captured(request, reload_config, tmp_path):
    """Corre el camino con el entorno fijado de la captura; `tmp_path` es el `LOG_DIR`."""
    name, mode = request.param
    reload_config(**capture_request_bodies.ENVIRONMENT)
    backend_params._forget()
    document = _DOCUMENTS[mode]
    if document is not None:
        backend_params.path().write_text(json.dumps(document), encoding="utf-8")
    try:
        return name, capture_request_bodies.capture(name, tmp_path)
    finally:
        backend_params._forget()


_CASES = [(name, mode) for name in PATHS for mode in MODES]
_IDS = [f"{name}-{mode}" for name, mode in _CASES]


def test_there_is_one_fixture_per_path_and_all_come_from_the_base_commit():
    """Las 8 fixtures del plan, cada una anotando `f2dd267`, y ninguna de más."""
    on_disk = sorted(path.stem for path in FIXTURES.glob("*.json"))
    assert on_disk == sorted(PATHS)
    for name in PATHS:
        fixture = _fixture(name)
        assert _field(fixture, "commit").startswith(BASE_COMMIT), name
        assert _field(fixture, "bodies"), f"{name}: la fixture no tiene cuerpos"


@pytest.mark.parametrize("captured", _CASES, ids=_IDS, indirect=True)
def test_body_matches_main(captured):
    name, result = captured
    expected = _field(_fixture(name), "bodies")
    # Se guardan como pares: la fixture leída con `object_pairs_hook=list` y lo capturado (que
    # `capture` ya convierte con el mismo gancho) tienen la misma forma.
    assert len(result["bodies"]) == len(expected), f"{name}: otro número de llamadas al backend"
    for index, (body, want) in enumerate(zip(result["bodies"], expected, strict=True)):
        assert body == want, f"{name}: el cuerpo {index} no es el de {BASE_COMMIT}"


#: Keys added to the usage event after the base commit, on purpose and additive: a reader of the
#: old format ignores them. `pieces` (issue #454) goes with `chunks` on chunked events only.
_ADDED_EVENT_KEYS = {"map_chunk": {"pieces"}, "reduce": {"pieces"}}


@pytest.mark.parametrize("captured", _CASES, ids=_IDS, indirect=True)
def test_event_keys_match_main(captured):
    name, result = captured
    expected = set(_field(_fixture(name), "event_keys")) | _ADDED_EVENT_KEYS.get(name, set())
    assert set(result["event_keys"]) == expected, name
