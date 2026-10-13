"""Tarea 27 de F3 y T12 de `daemon-reparte-el-backend`: las cadenas de respaldo por rol.

Lo que se fija arriba es la RESOLUCIÓN de la cadena con la configuración vigente (REQ-003, REQ-004 y
REQ-014 de F3); el salto en sí se prueba en `test_fallback.py` y en el bloque de T12 de abajo. Una
cadena es una lista ordenada de pasos, ya sin repetidos, sin el propio modelo principal y solo con
modelos del catálogo de texto o el paso `loaded`.

Defectos (REQ-020, que enmienda REQ-004 de F3), con `loaded` = los alternativos con celda aprobada
que ya están cargados, resueltos al saltar (REQ-019). Sin bloque B no tiene miembros:
- código   -> loaded -> largo
- largo    -> loaded -> código
- mecánico -> loaded -> largo
- visión   -> ninguna
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import chains, checks, config, server, topology

MECHANICAL = "gemma3-4b"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"
#: El modelo del rol `fast`, retirado en la 0.30.0. Se conserva como caso de «esto ya NO está en el
#: catálogo», que es exactamente lo que pasó a ser.
RETIRED = "qwen35-2b"

TOPOLOGY_FIXTURES = Path(__file__).parent / "fixtures" / "topology"


def _config_llamaswap(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


#: Dos modelos con TTL efectivo 0 (uno por `ttl: 0`, otro por `globalTTL` 0) y uno con TTL 120.
TWO_RESIDENTS = """\
globalTTL: 0
models:
  gemma3-4b: {}
  gemma4-26b-a4b:
    ttl: 120
  qwen35-2b: {}
groups:
  swap:
    swap: true
    members: [gemma4-26b-a4b]
  fijos:
    persistent: true
    exclusive: false
    swap: false
    members: [gemma3-4b, qwen35-2b]
"""


# --- Defectos ---------------------------------------------------------------------------------


def test_default_chains_are_the_ones_in_the_spec(reload_config):
    """REQ-020: `loaded` primero y ninguna lleva al mecánico desde código o largo."""
    reload_config()
    assert chains.resolve("code").steps == (chains.LOADED, LONG)
    assert chains.resolve("long").steps == (chains.LOADED, CODE)
    assert chains.resolve("mechanical").steps == (chains.LOADED, LONG)
    # Sin bloque B, las efectivas (REQ-020): `code -> long`, `long -> code`, `mechanical -> long`.
    assert chains.resolve("code").models == (LONG,)
    assert chains.resolve("long").models == (CODE,)
    assert chains.resolve("mechanical").models == (LONG,)


def test_vision_has_no_chain(reload_config):
    """Visión queda fuera de `ALLOWED_MODELS` a propósito: su cadena se resuelve vacía ANTES."""
    reload_config()
    assert chains.resolve("vision").models == ()


# --- El residente (REQ-023): solo si la config tiene un modelo con TTL efectivo 0 -----------------


def test_without_llamaswap_config_no_resident_nor_mechanical_fallback(reload_config, monkeypatch):
    """Sustituye a «sin config, el residente es el mecánico»: el residente fantasma desaparece."""
    reload_config()
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    assert chains.residents() is None
    lines = "\n".join(chains.describe())
    assert "sin residente" in lines
    assert MECHANICAL not in lines.split("code:")[0], "ni el mecánico como residente"


def test_persistent_group_with_ttl_not_resident(reload_config, monkeypatch, tmp_path):
    """Sustituye a «el residente sale del grupo persistent»: con la config del 2026-09-15 (4B en un
    grupo `persistent` con TTL 600) llama-swap lo descarga, así que no es residente."""
    reload_config()
    path = tmp_path / "config.yaml"
    path.write_bytes((TOPOLOGY_FIXTURES / "pre-no-resident-20261006.yaml").read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))
    assert chains.residents() == ()
    assert chains.residents_text() == "sin residente"
    # Y la cadena no cambia por haber un grupo persistent: `loaded` no es «el del grupo».
    assert chains.resolve("code").steps == (chains.LOADED, LONG)


def test_with_several_residents_all_named(reload_config, monkeypatch, tmp_path):
    """Sustituye a «con varios miembros gana el primero»: ya no se elige uno, se dicen los que hay,
    también los que no están en el catálogo (el del rol retirado): es lo que llama-swap retiene."""
    reload_config()
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_config_llamaswap(tmp_path, TWO_RESIDENTS)))
    assert chains.residents() == (MECHANICAL, RETIRED)
    assert chains.residents_text() == f"residente: {MECHANICAL}, {RETIRED}"


def test_without_pyyaml_unknown_and_no_mechanical_fallback(reload_config, monkeypatch, tmp_path):
    """Sustituye a «sin pyyaml cae al mecánico y lo dice»: sin PyYAML no se sabe, y se dice."""
    reload_config()
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_config_llamaswap(tmp_path, TWO_RESIDENTS)))
    monkeypatch.setattr(topology, "yaml", None)
    assert chains.residents() is None
    assert chains.residents_text().startswith("sin residente")


def test_local_status_shows_chains_with_loaded(reload_config, monkeypatch):
    """Sustituye a «local_status dice el residente y su origen»: dice las cadenas con su paso."""
    reload_config()
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    lines = chains.describe()
    assert f"  code: loaded -> {LONG}" in lines
    assert f"  long: loaded -> {CODE}" in lines
    assert f"  mechanical: loaded -> {LONG}" in lines
    assert not any("defecto: el modelo del rol" in line for line in lines)


# --- Sobrescribir -----------------------------------------------------------------------------


def test_a_chain_is_overridden_with_roles_and_models(reload_config):
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE=f"long, {MECHANICAL}")
    assert chains.resolve("code").models == (LONG, MECHANICAL)


def test_an_empty_chain_disables_the_fallback_for_that_role(reload_config):
    reload_config(LOCAL_DELEGATE_FALLBACK_LONG="")
    assert chains.resolve("long").steps == ()
    assert chains.resolve("code").steps == (chains.LOADED, LONG), "los demás no cambian"


def test_none_also_disables_because_windows_does_not_keep_empty_variables(reload_config):
    """En Windows fijar una variable a "" la BORRA: en el daemon real la cadena vacía no existe.

    `monkeypatch.setenv` sí guarda "" en el diccionario de Python, así que el test de arriba pasa
    igual y no lo habría destapado. `none` es la forma que funciona en las tres plataformas.
    """
    reload_config(LOCAL_DELEGATE_FALLBACK_LONG="none")
    assert chains.resolve("long").models == ()
    assert chains.resolve("long").ignored == ()


def test_an_unknown_model_is_ignored_and_reported(reload_config):
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="long,modelo-que-no-existe")
    chain = chains.resolve("code")
    assert chain.models == (LONG,)
    assert chain.ignored == ("modelo-que-no-existe",)


def test_duplicates_and_the_model_itself_are_removed(reload_config):
    """Largo y código consolidados en uno: ese modelo no se reintenta contra sí mismo."""
    reload_config(LOCAL_DELEGATE_MODEL_CODE=LONG)
    assert chains.resolve("long").steps == (chains.LOADED,)
    assert chains.resolve("code").steps == (chains.LOADED,)
    # Y los repetidos dentro de una misma cadena se quitan: «long,code,long» con los dos roles
    # consolidados en un modelo es tres veces el mismo candidato.
    reload_config(
        LOCAL_DELEGATE_MODEL_CODE=LONG, LOCAL_DELEGATE_FALLBACK_MECHANICAL="long,code,long"
    )
    assert chains.resolve("mechanical").models == (LONG,)


# --- Variables (REQ-014) ----------------------------------------------------------------------


def test_the_fallback_comes_enabled_with_two_hops(reload_config):
    reload_config()
    assert config.FALLBACK is True
    assert config.FALLBACK_MAX_HOPS == 2


def test_the_new_variables_are_in_the_inventory(reload_config):
    reload_config()
    for name in (
        "LOCAL_DELEGATE_FALLBACK",
        "LOCAL_DELEGATE_FALLBACK_MAX_HOPS",
        "LOCAL_DELEGATE_FALLBACK_MECHANICAL",
        "LOCAL_DELEGATE_FALLBACK_LONG",
        "LOCAL_DELEGATE_FALLBACK_CODE",
        "LOCAL_DELEGATE_FALLBACK_FAST",
        "LLAMASWAP_CONFIG",
        "LLAMASWAP_EXE",
        "LLAMASWAP_LISTEN",
        "LLAMASWAP_WATCH_CONFIG",
    ):
        assert name in config.ENVIRONMENT_VARIABLES, name


def test_nobody_outside_config_reads_llamaswap_from_the_environment():
    """Tres sitios leían `LLAMASWAP_CONFIG` con `os.environ` directo: dos fuentes para un dato.

    El guardián de `test_environment_isolation.py` solo mira `config.py`, así que por ahí la suite
    volvía a heredar el entorno de la máquina.
    """
    package = Path(config.__file__).parent
    direct_read = re.compile(r"os\.environ[^\n]*LLAMASWAP_")
    culprits = [
        f"{path.name}:{number}"
        for path in package.rglob("*.py")
        if path.name != "config.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if direct_read.search(line)
    ]
    assert culprits == []


# --- doctor -----------------------------------------------------------------------------------


def test_doctor_warns_about_an_unknown_model_in_a_chain(reload_config, tmp_path):
    reload_config(LOCAL_DELEGATE_FALLBACK_CODE="long,modelo-que-no-existe")
    result = checks._probe_fallback(checks.Context(home=tmp_path))
    assert result.status == checks.WARN
    assert "modelo-que-no-existe" in result.detail
    assert "LOCAL_DELEGATE_FALLBACK_CODE" in result.detail


def test_doctor_does_not_warn_with_the_default_chains(reload_config, tmp_path):
    reload_config()
    result = checks._probe_fallback(checks.Context(home=tmp_path))
    assert result.status == checks.OK


# El bloque «`fast` es inalcanzable desde las tools» se retiró con el rol (0.30.0): comprobaba que
# ninguna tool enrutaba a él, que era el argumento para quitarlo. Lo que queda por proteger —que su
# modelo ya no se pueda pedir a mano— vive en `test_rol_fast_retirado.py`.


# --- T12 de `daemon-reparte-el-backend`: cadenas sin residente (REQ-019 a REQ-023) -------------
#
# El paso `loaded` sustituye a `residente`: el conjunto de alternativos con celda aprobada que ya
# están cargados, resuelto en el momento del salto. Sin bloque B (sin proveedor registrado) no tiene
# miembros: se salta sin gastar salto y sin tocar la red. Los escenarios van sobre `backend_mock`,
# que responde según el modelo pedido, y miran los `Attempt` reales que devuelve `_with_fallback`.

URL = "http://test-backend/v1/chat/completions"
CAPACITY_ERROR = '{"error":{"message":"unspecific error: upstream command exited prematurely"}}'
TODAY = Path(__file__).parent / "fixtures" / "topology" / "today.yaml"
DIFF = "diff --git a/x b/x\n+hola\n"


def _ok(content: str = "hecho") -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    )


def _failure(status: int = 500, text: str = "boom") -> httpx2.Response:
    return httpx2.Response(status, text=text)


def _backend(responses: dict) -> list[str]:
    """El POST de chat con una respuesta por modelo; devuelve los modelos pedidos, en orden.

    Un modelo sin respuesta hace fallar el test.
    """
    backend_mock._routes.clear()
    requested: list[str] = []

    def effect(request: httpx2.Request):
        model = json.loads(request.content)["model"]
        requested.append(model)
        if model not in responses:
            raise AssertionError(f"se llamó a un modelo sin respuesta: {model}")
        return responses[model]

    backend_mock.post(URL).mock(side_effect=effect)
    return requested


@pytest.fixture
def attempts(monkeypatch) -> list:
    """Los `Attempt` de cada `_with_fallback`, en orden: las llamadas reales al backend."""
    seen_set: list = []
    original = server._with_fallback

    def spy(*args, **kwargs):
        result = original(*args, **kwargs)
        seen_set.extend(result[2])
        return result

    monkeypatch.setattr(server, "_with_fallback", spy)
    return seen_set


def _text(chars: int) -> str:
    paragraph = ("palabra " * 375).strip() + "\n\n"
    return (paragraph * (chars // len(paragraph) + 1))[:chars]


@backend_mock.mock
def test_code_never_falls_to_mechanical(reload_config, attempts):
    """Escenario «código nunca cae al mecánico»: el 4B no es candidato, no hay celdas aprobadas."""
    reload_config()
    _backend({CODE: _failure(500), LONG: _ok("mensaje"), MECHANICAL: _ok("del 4B")})

    server.local_commit_msg(diff=DIFF)

    assert attempts[0].model == CODE
    assert attempts[1].model == "gemma4-26b-a4b"
    assert MECHANICAL not in [i.model for i in attempts]


@backend_mock.mock
def test_long_hops_to_code_and_mechanical_to_long(reload_config, attempts):
    reload_config()
    _backend({LONG: _failure(500), CODE: _ok("resumen"), MECHANICAL: _ok("del 4B")})
    server.local_summarize(text=_text(10_000))
    assert "gemma3-4b" not in [i.model for i in attempts]
    assert [i.model for i in attempts] == [LONG, CODE]

    attempts.clear()
    _backend({MECHANICAL: _failure(500), LONG: _ok("a")})
    server.local_classify(text="hola", labels=["a", "b"])
    assert [i.model for i in attempts] == [MECHANICAL, LONG]


@backend_mock.mock
def test_capacity_failure_with_nothing_loaded(reload_config, attempts):
    """Escenario: sin `loaded` un fallo de capacidad no salta y vuelve el error de siempre."""
    reload_config()
    _backend({CODE: _failure(500, CAPACITY_ERROR), MECHANICAL: _ok(), LONG: _ok()})

    output = server.local_explain_code(code="x = 1")

    assert [i.model for i in attempts] == ["qwen36-35b-a3b"]
    assert output.startswith("[local-delegate error]")


@backend_mock.mock
def test_empty_loaded_spends_no_hop(reload_config, attempts):
    """Con un solo salto, `code → loaded → long` llega a `long`: el paso vacío no lo gasta."""
    reload_config(LOCAL_DELEGATE_FALLBACK_MAX_HOPS="1")
    assert config.FALLBACK_MAX_HOPS == 1
    assert chains.resolve("code").steps == (chains.LOADED, LONG)
    _backend({CODE: _failure(500), LONG: _ok("mensaje")})

    server.local_commit_msg(diff=DIFF)

    assert attempts[-1].model == "gemma4-26b-a4b"
    assert [i.model for i in attempts] == [CODE, LONG]


def test_loaded_members_without_provider_does_not_query_network(reload_config, monkeypatch):
    """Sin bloque B no hay proveedor: `loaded` se resuelve vacío y sin tocar la red (REQ-019)."""
    reload_config()
    requested_paths: list[str] = []
    original = backend_mock._handler

    def spy(request):
        requested_paths.append(f"{request.method} {request.url}")
        return original(request)

    monkeypatch.setattr(backend_mock, "_handler", spy)
    with backend_mock.mock:
        members = chains.loaded_members(
            "local_commit_msg", CODE, own_items=frozenset(), nobody_else=True
        )

    assert members == ()
    assert requested_paths == []


@backend_mock.mock
def test_with_provider_hop_goes_to_loaded_member(reload_config, attempts):
    """El camino con miembros ya existe (el proveedor lo registra T15): recibe tool y fallido."""
    reload_config()
    seen_set: list[tuple] = []

    def provider(tool, has_failed, own_items, nobody_else, role):
        seen_set.append((tool, has_failed))
        return (MECHANICAL,)

    previous_provider = chains._loaded_provider
    chains.register_loaded_provider(provider)
    try:
        _backend({CODE: _failure(500), MECHANICAL: _ok("del 4B"), LONG: _ok()})
        server.local_commit_msg(diff=DIFF)
    finally:
        chains.register_loaded_provider(previous_provider)

    assert seen_set == [("local_commit_msg", CODE)]
    assert [i.model for i in attempts] == [CODE, MECHANICAL]


@pytest.fixture
def offline_status(monkeypatch):
    """`local_status` sin backend, GPU ni llama-swap: solo interesa lo que dice de las cadenas."""
    monkeypatch.setattr(
        server,
        "probe_backend",
        lambda: server.BackendState(False, [], True, "rechazada", "sin red en los tests", None),
    )
    for name in ("_vram_info", "_ram_info", "_llamaswap_groups"):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)


def test_status_no_longer_mentions_ghost_resident(
    reload_config, monkeypatch, tmp_path, offline_status
):
    """Escenario: con la config de hoy (un solo grupo `swap`, TTL 120) no hay residente."""
    reload_config()
    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    doctor = checks._probe_fallback(checks.Context(home=tmp_path))
    text = server.local_status() + "\n" + doctor.detail

    assert "residente gemma3-4b" not in text
    assert "defecto: el modelo del rol" not in text
    assert "sin residente" in text
    assert "sin residente" in doctor.detail
    assert doctor.detail == "cadenas válidas; sin residente"


def test_with_ttl_0_in_persistent_group_describe_names_resident(
    reload_config, monkeypatch, tmp_path
):
    reload_config()
    path = tmp_path / "llamaswap.yaml"
    path.write_text(
        "globalTTL: 120\n"
        "models:\n"
        "  gemma3-4b:\n    ttl: 0\n"
        "  gemma4-26b-a4b: {}\n"
        "  qwen36-35b-a3b: {}\n"
        "groups:\n"
        "  swap:\n    swap: true\n    members: [gemma4-26b-a4b, qwen36-35b-a3b]\n"
        "  resident:\n    persistent: true\n    exclusive: false\n    members: [gemma3-4b]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(path))

    lines = "\n".join(chains.describe())

    assert "residente: gemma3-4b" in lines
    assert "sin residente" not in lines


# --- Corrección tras la revisión de la ola 6 ---------------------------------------------------


@backend_mock.mock
def test_loaded_member_repeating_later_step_not_called_twice(reload_config):
    """`code -> loaded -> long` con `loaded` = el 26B: si el 26B falla, el paso `long` no lo repite."""
    reload_config()
    previous_provider = chains._loaded_provider
    chains.register_loaded_provider(lambda *_: (LONG,))
    try:
        requested = _backend({CODE: _failure(500, "original"), LONG: _failure(500, "otro")})
        output = server.local_commit_msg(diff=DIFF)
    finally:
        chains.register_loaded_provider(previous_provider)

    assert requested == [CODE, LONG]
    # REQ-008: la línea de «también fallaron» no repite modelo.
    line = next(line for line in output.splitlines() if "también fallaron" in line)
    assert line.count(LONG) == 1, line


def test_without_topology_resident_states_reason(reload_config, monkeypatch, tmp_path):
    """Con una config legible pero `matrix`, «no se sabe: matrix», como «Turno: no (matrix)»."""
    reload_config()
    matrix = (
        "models:\n  gemma4-26b-a4b: {}\n  qwen36-35b-a3b: {}\n"
        "routing:\n  router:\n    use: matrix\n    settings:\n      matrix: {}\n"
    )
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_config_llamaswap(tmp_path, matrix)))
    snapshot = topology.snapshot()
    assert isinstance(snapshot, topology.NoTopology) and snapshot.reason == topology.MATRIX

    assert chains.residents_text() == "sin residente (no se sabe: matrix)"
    assert "  sin residente (no se sabe: matrix)" in chains.describe()
    monkeypatch.delenv("LLAMASWAP_CONFIG")
    assert chains.residents_text() == "sin residente (no se sabe: sin LLAMASWAP_CONFIG)"
