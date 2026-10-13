"""Ola A2 del renombrado: nombres en disco, interruptor y `deprecated_names` de los hooks.

Los hooks escriben solo los nombres nuevos (`local-delegate-blocks.jsonl`, `local-delegate-calls/`,
`local-delegate-health-*.json`, `~/.claude/local-delegate-block-off`) y el daemon sigue leyendo
los viejos, porque un hook de una versión anterior puede seguir instalado y escribiendo (REQ-005,
REQ-006, REQ-012). Con la telemetría encendida, cada evento dice qué nombres viejos leyó la
invocación, y `doctor` lo cuenta desde la cola del fichero (REQ-003).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from local_delegate import attribution, checks, config, deprecations, legacy_names, server
from local_delegate import install as inst
from local_delegate.resources.hooks import hook_common

OLD_SWITCH, NEW_SWITCH = hook_common.FILE_NAMES["switch_file"]


@pytest.fixture
def temporal(tmp_path, monkeypatch):
    """El temporal del usuario, que comparten el hook y el daemon, apuntando a `tmp_path`."""
    destino = tmp_path / "temp"
    destino.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(destino))
    return destino


@pytest.fixture
def casa(tmp_path, monkeypatch):
    """Un HOME de prueba sin interruptor configurado y con el bloqueo encendido por variable."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    for nombre in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(nombre, str(home))
    for nombre in (
        "LD_HOOK_READ_SWITCH_FILE",
        "LD_HOOK_READ_INTERRUPTOR",
        "LD_HOOK_READ_BLOQUEAR",
    ):
        monkeypatch.delenv(nombre, raising=False)
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    hook_common.DEPRECATED_SEEN.clear()
    yield home
    hook_common.DEPRECATED_SEEN.clear()


# --- Una sola tabla ---------------------------------------------------------------------------


def test_la_tabla_de_ficheros_es_la_misma_en_los_hooks_y_en_el_paquete():
    """Los hooks no importan el paquete y llevan su copia: si divergen, uno escribe donde el otro
    no lee."""
    assert hook_common.FILE_NAMES == legacy_names.FILE_NAMES


def test_el_interruptor_viejo_esta_en_el_registro_y_en_la_copia_de_los_hooks():
    entrada = deprecations.find(OLD_SWITCH)
    assert entrada is not None and entrada.kind == "switch_file" and entrada.new == NEW_SWITCH
    assert ("switch_file", OLD_SWITCH, NEW_SWITCH) in hook_common.DEPRECATED_HOOK_NAMES


# --- Temporales: escribe el nuevo, lee los dos ----------------------------------------------


def test_el_daemon_lee_las_notas_de_bloqueo_de_un_hook_viejo(temporal, tmp_path):
    """Un hook de la 0.34.0 sigue escribiendo `local-delegate-bloqueos.jsonl`: el bloqueo que
    provocó tiene que seguir contando como aceptado cuando el agente delega."""
    documento = tmp_path / "informe.md"
    viejo = temporal / "local-delegate-bloqueos.jsonl"
    nota = {"id": "viejo1234567", "sha": hook_common.path_digest(str(documento)), "ts": time.time()}
    viejo.write_text(json.dumps(nota) + "\n", encoding="utf-8")

    assert server._recent_block_id(str(documento)) == "viejo1234567"


def test_el_hook_escribe_las_notas_solo_con_el_nombre_nuevo_y_gana_la_mas_reciente(
    temporal, tmp_path
):
    documento = tmp_path / "informe.md"
    viejo = temporal / "local-delegate-bloqueos.jsonl"
    antigua = {
        "id": "viejo1234567",
        "sha": hook_common.path_digest(str(documento)),
        "ts": time.time() - 30,
    }
    viejo.write_text(json.dumps(antigua) + "\n", encoding="utf-8")

    hook_common.record_block("nuevo1234567", str(documento))

    assert (temporal / "local-delegate-blocks.jsonl").is_file()
    assert viejo.read_text(encoding="utf-8").count("\n") == 1, "el fichero viejo no se toca"
    assert server._recent_block_id(str(documento)) == "nuevo1234567"


def test_la_nota_de_atribucion_de_un_hook_viejo_se_sigue_encontrando(temporal):
    viejo = temporal / "local-delegate-llamadas"
    viejo.mkdir()
    nota = {"tool_use_id": "toolu_viejo", "ts": time.time(), "agent_type": "general-purpose"}
    (viejo / "toolu_viejo.json").write_text(json.dumps(nota), encoding="utf-8")

    assert attribution.read_note("toolu_viejo") == nota

    assert hook_common.record_call({"tool_use_id": "toolu_nuevo", "agent_type": "Explore"})
    assert (temporal / "local-delegate-calls" / "toolu_nuevo.json").is_file()
    assert not (viejo / "toolu_nuevo.json").exists()
    assert attribution.read_note("toolu_nuevo")["agent_type"] == "Explore"


def test_la_marca_de_salud_usa_el_nombre_nuevo(temporal, monkeypatch):
    monkeypatch.setattr(hook_common, "_probe", lambda _timeout: True)

    assert hook_common.backend_available() is True

    nombres = sorted(p.name for p in temporal.iterdir())
    assert len(nombres) == 1 and nombres[0].startswith("local-delegate-health-"), nombres


# --- El interruptor -------------------------------------------------------------------------


def test_el_interruptor_viejo_sigue_apagando_y_queda_anotado(casa):
    (casa / ".claude" / OLD_SWITCH).write_text("", encoding="utf-8")

    assert hook_common.block_state() == "off_file"
    assert OLD_SWITCH in hook_common.DEPRECATED_SEEN


def test_el_interruptor_nuevo_apaga_sin_aviso(casa):
    (casa / ".claude" / NEW_SWITCH).write_text("", encoding="utf-8")

    assert hook_common.block_state() == "off_file"
    assert hook_common.DEPRECATED_SEEN == set()


def test_sin_interruptor_manda_la_variable(casa):
    """Control de los dos anteriores: sin ningún fichero, el bloqueo está encendido."""
    assert hook_common.block_state() == "on"
    assert hook_common.DEPRECATED_SEEN == set()


# --- `deprecated_names` en la telemetría, con el hook INSTALADO --------------------------------


def _correr_hook_instalado(home: Path, variables: dict[str, str]) -> subprocess.CompletedProcess:
    inst.apply(
        inst.plan_install(
            inst.Options(
                home=home,
                components={"hooks"},
                targets={"claude"},
                python_exe="python3",
                use_cli=False,
            )
        ),
        dry_run=False,
        out=lambda *_a: None,
    )
    hooks_dir = home / ".claude" / "hooks" / inst.HOOKS_SUBDIR
    quitar = {
        "LD_HOOK_READ_BLOCK",
        "LD_HOOK_READ_BLOQUEAR",
        "LD_HOOK_READ_SWITCH_FILE",
        "LD_HOOK_READ_INTERRUPTOR",
        "LD_HOOK_TELEMETRY_LOG",
    }
    env = {k: v for k, v in os.environ.items() if k not in quitar}
    env.update({"HOME": str(home), "USERPROFILE": str(home), **variables})
    proc = subprocess.run(
        [sys.executable, str(hooks_dir / "suggest_delegate_prompt.py")],
        input=json.dumps({"prompt": "Hola", "session_id": "s-a2"}),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def _ultimo_evento(log: Path) -> dict:
    return json.loads(log.read_text(encoding="utf-8").splitlines()[-1])


def test_el_evento_dice_que_nombres_viejos_leyo_el_hook(tmp_path):
    log = tmp_path / "telemetry.jsonl"
    _correr_hook_instalado(
        tmp_path, {"LD_HOOK_READ_BLOQUEAR": "1", "LD_HOOK_TELEMETRY_LOG": str(log)}
    )

    evento = _ultimo_evento(log)
    assert evento["block"] == "on"
    assert evento["deprecated_names"] == ["LD_HOOK_READ_BLOQUEAR"]


def test_el_interruptor_viejo_tambien_viaja_en_el_evento(tmp_path):
    log = tmp_path / "telemetry.jsonl"
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / OLD_SWITCH).write_text("", encoding="utf-8")
    _correr_hook_instalado(tmp_path, {"LD_HOOK_READ_BLOCK": "1", "LD_HOOK_TELEMETRY_LOG": str(log)})

    evento = _ultimo_evento(log)
    assert evento["block"] == "off_file"
    assert evento["deprecated_names"] == [OLD_SWITCH]


def test_con_nombres_nuevos_el_evento_no_lleva_la_clave(tmp_path):
    """Control: la clave solo aparece cuando se leyó algo viejo."""
    log = tmp_path / "telemetry.jsonl"
    _correr_hook_instalado(tmp_path, {"LD_HOOK_READ_BLOCK": "1", "LD_HOOK_TELEMETRY_LOG": str(log)})

    evento = _ultimo_evento(log)
    assert evento["block"] == "on"
    assert "deprecated_names" not in evento


def test_sin_telemetria_no_se_escribe_nada(tmp_path):
    _correr_hook_instalado(tmp_path, {"LD_HOOK_READ_BLOQUEAR": "1"})

    assert not list(tmp_path.glob("**/*.jsonl")), "sin LD_HOOK_TELEMETRY_LOG no hay evento"


# --- `doctor` lee la cola de la telemetría ---------------------------------------------------


def _evento(cuando: datetime, nombres: list[str] | None = None) -> dict:
    fila: dict = {"ts": cuando.isoformat(), "event": "UserPromptSubmit", "block": "on"}
    if nombres:
        fila["deprecated_names"] = nombres
    return fila


def _escribir_telemetria(path: Path, filas: list[dict], relleno: int = 0) -> None:
    lineas = [json.dumps(f) for f in filas]
    # Relleno de eventos viejos al principio: obliga a leer por bloques desde el final.
    viejo = json.dumps(_evento(datetime.now(UTC) - timedelta(days=60)))
    path.write_text("\n".join([viejo] * relleno + lineas) + "\n", encoding="utf-8")


def test_la_cola_de_7_dias_da_los_nombres_y_no_mira_mas_atras(tmp_path):
    ahora = datetime.now(UTC)
    log = tmp_path / "telemetry.jsonl"
    _escribir_telemetria(
        log,
        [
            _evento(ahora - timedelta(days=9), ["LD_HOOK_READ_INTERRUPTOR"]),
            _evento(ahora - timedelta(days=2), ["LD_HOOK_READ_BLOQUEAR"]),
            _evento(ahora - timedelta(hours=1)),
            _evento(ahora, [OLD_SWITCH]),
        ],
        relleno=3000,
    )
    assert log.stat().st_size > 2 * checks._TAIL_BLOCK, "el caso tiene que cruzar bloques"

    nombres = checks.deprecated_names_in_hook_telemetry(log, now=ahora)

    assert nombres == {"LD_HOOK_READ_BLOQUEAR", OLD_SWITCH}


def test_doctor_avisa_de_lo_que_leyeron_los_hooks(tmp_path, monkeypatch):
    log = tmp_path / "telemetry.jsonl"
    _escribir_telemetria(log, [_evento(datetime.now(UTC), ["LD_HOOK_READ_BLOQUEAR"])])
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)
    for nombre in config.DEPRECATED_ENV_VALUES:
        monkeypatch.setitem(config.DEPRECATED_ENV_VALUES, nombre, None)
    ctx = checks.Context(home=tmp_path)

    resultado = checks._probe_deprecated_names(ctx)

    assert resultado.status == checks.WARN
    assert "leído por los hooks" in resultado.detail
    assert "LD_HOOK_READ_BLOQUEAR está obsoleto: usa LD_HOOK_READ_BLOCK" in resultado.detail


def test_doctor_avisa_del_interruptor_viejo_en_claude(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    for nombre in config.DEPRECATED_ENV_VALUES:
        monkeypatch.setitem(config.DEPRECATED_ENV_VALUES, nombre, None)
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / OLD_SWITCH).write_text("", encoding="utf-8")

    resultado = checks._probe_deprecated_names(checks.Context(home=tmp_path))

    assert resultado.status == checks.WARN
    assert f"renombra {OLD_SWITCH} a {NEW_SWITCH}" in resultado.fix_hint
