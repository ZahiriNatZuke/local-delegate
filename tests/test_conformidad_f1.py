"""Tarea 31: los tres huecos de F1 que encontro la revision de conformidad.

- REQ-F1-9: las lecturas por tools de OTROS MCP se cuentan siempre, y nunca se bloquean.
- REQ-F1-10: con el modelo que haria el resumen en enfriamiento, el bloqueo se cae.
- REQ-F1-11: el bloqueo se apaga en caliente desde un fichero, no desde el entorno, y cada evento
  dice en que estado estaba.

Cada caso lleva su control positivo: el mismo escenario con la condicion quitada tiene que
bloquear, o el test pasaria con la guarda rota.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from local_delegate import config
from local_delegate import install as inst

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"
sys.path.insert(0, str(HOOKS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = _load("hook_common")
read_hook = _load("suggest_delegate_read")
shell_hook = _load("suggest_delegate_shell")


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Telemetria, interruptor y LOG_DIR en tmp; bloqueo encendido y backend vivo por defecto."""
    log = tmp_path / "telemetria.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOQUEAR", "1")
    monkeypatch.setenv("LD_HOOK_READ_INTERRUPTOR", str(tmp_path / "bloqueo-apagado"))
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path / "logs"))
    for variable in ("LOCAL_DELEGATE_MODEL_LONG", "LOCAL_DELEGATE_MODEL_MECHANICAL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("LOCAL_DELEGATE_LONG_INPUT_CHARS", raising=False)
    monkeypatch.setattr(read_hook, "backend_disponible", lambda **k: True)
    monkeypatch.setattr(shell_hook, "backend_disponible", lambda **k: True)
    return tmp_path


def _eventos(tmp_path: Path) -> list[dict]:
    log = tmp_path / "telemetria.jsonl"
    if not log.exists():
        return []
    return [json.loads(linea) for linea in log.read_text(encoding="utf-8").splitlines()]


def _correr(hook, monkeypatch, capsys, payload: dict) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    hook.main()
    return capsys.readouterr().out


def _prosa(tmp_path: Path, kb: int = 40) -> Path:
    destino = tmp_path / "informe.md"
    destino.write_text("x" * kb * 1024, encoding="utf-8")
    return destino


def _enfriar(tmp_path: Path, modelo: str, restante_s: float) -> None:
    directorio = tmp_path / "logs"
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / "enfriamiento.json").write_text(
        json.dumps(
            {
                modelo: {
                    "fallos": 0,
                    "espera_s": 120.0,
                    "hasta": time.time() + restante_s,
                    "reentradas": 1,
                }
            }
        ),
        encoding="utf-8",
    )


# --- REQ-F1-9: lecturas por otros MCP ------------------------------------------------------------


def test_una_lectura_por_otro_mcp_se_cuenta_y_no_se_bloquea(entorno, monkeypatch, capsys):
    """Prosa grande, bloqueo encendido y backend vivo: por `Read` se bloquearia. Por un MCP ajeno
    solo se mide (P-6)."""
    destino = _prosa(entorno)
    salida = _correr(
        read_hook,
        monkeypatch,
        capsys,
        {"tool_name": "mcp__filesystem__read_text_file", "tool_input": {"path": str(destino)}},
    )
    assert salida == "", "ni bloqueo ni sugerencia"
    (evento,) = _eventos(entorno)
    assert evento["camino"] == "mcp"
    assert evento["category"] == "read", "tiene que entrar en el denominador de medir_adopcion"
    assert evento["motivo"] == "mcp_ajeno"
    assert evento["path_sha"] == common.huella_de_ruta(str(destino))
    assert str(destino) not in json.dumps(evento), "la telemetria nunca guarda rutas"


def test_la_misma_lectura_por_read_si_se_bloquea(entorno, monkeypatch, capsys):
    """Control positivo del anterior: lo que lo deja pasar es el camino, no el escenario."""
    destino = _prosa(entorno)
    salida = _correr(
        read_hook,
        monkeypatch,
        capsys,
        {"tool_name": "Read", "tool_input": {"file_path": str(destino)}},
    )
    assert json.loads(salida)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_una_lectura_multiple_por_otro_mcp_tambien_se_cuenta(entorno, monkeypatch, capsys):
    destino = _prosa(entorno)
    salida = _correr(
        read_hook,
        monkeypatch,
        capsys,
        {
            "tool_name": "mcp__filesystem__read_multiple_files",
            "tool_input": {"paths": [str(destino), str(destino)]},
        },
    )
    assert salida == ""
    (evento,) = _eventos(entorno)
    assert evento["camino"] == "mcp"


def test_el_instalador_registra_el_hook_para_las_lecturas_de_otros_mcp():
    patron = inst._MCP_READ_HOOK[2]
    assert inst._MCP_READ_HOOK[0] == inst._READ_HOOK[0], "el mismo script decide los dos caminos"
    for lectura in (
        "mcp__filesystem__read_text_file",
        "mcp__filesystem__read_file",
        "mcp__filesystem__read_multiple_files",
        "mcp__github__get_file_contents",
        "mcp__obsidian__read_note",
    ):
        assert re.fullmatch(patron, lectura), lectura
    for otra in (
        "mcp__filesystem__write_file",
        "mcp__local-delegate__local_summarize",
        "mcp__filesystem__list_directory",
        "Read",
    ):
        assert not re.fullmatch(patron, otra), otra


# --- REQ-F1-10: el modelo del resumen en enfriamiento ----------------------------------------------


def test_con_el_modelo_largo_enfriado_la_prosa_no_se_bloquea(entorno, monkeypatch, capsys):
    destino = _prosa(entorno)  # 40 KB > 6000 chars: el resumen iria al modelo largo
    _enfriar(entorno, "gemma4-26b-a4b", 100)
    salida = _correr(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(destino)}})
    assert "deny" not in salida
    assert any(e.get("motivo") == "modelo_enfriado" for e in _eventos(entorno))


def test_un_enfriamiento_vencido_no_quita_el_bloqueo(entorno, monkeypatch, capsys):
    destino = _prosa(entorno)
    _enfriar(entorno, "gemma4-26b-a4b", -5)
    salida = _correr(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(destino)}})
    assert "deny" in salida


def test_otro_modelo_enfriado_no_quita_el_bloqueo(entorno, monkeypatch, capsys):
    destino = _prosa(entorno)
    _enfriar(entorno, "qwen36-35b-a3b", 100)
    salida = _correr(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(destino)}})
    assert "deny" in salida


def test_el_modelo_se_toma_de_la_variable_si_esta(entorno, monkeypatch, capsys):
    destino = _prosa(entorno)
    monkeypatch.setenv("LOCAL_DELEGATE_MODEL_LONG", "mi-largo")
    _enfriar(entorno, "mi-largo", 100)
    salida = _correr(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(destino)}})
    assert "deny" not in salida


def test_un_fichero_de_enfriamiento_corrupto_no_quita_el_bloqueo(entorno, monkeypatch, capsys):
    destino = _prosa(entorno)
    (entorno / "logs").mkdir()
    (entorno / "logs" / "enfriamiento.json").write_text("{roto", encoding="utf-8")
    salida = _correr(read_hook, monkeypatch, capsys, {"tool_input": {"file_path": str(destino)}})
    assert "deny" in salida


def test_el_volcado_por_shell_tambien_respeta_el_enfriamiento(entorno, monkeypatch, capsys):
    destino = _prosa(entorno)
    payload = {"tool_input": {"command": f"cat {destino}"}}
    assert "deny" in _correr(shell_hook, monkeypatch, capsys, payload), (
        "control: sin enfriar bloquea"
    )
    _enfriar(entorno, "gemma4-26b-a4b", 100)
    assert "deny" not in _correr(shell_hook, monkeypatch, capsys, payload)
    assert _eventos(entorno)[-1]["motivo"] == "modelo_enfriado"


def test_los_defectos_del_hook_son_los_de_config():
    """El hook es stdlib y no puede importar `config`: lleva su copia, y esto la ata."""
    fuente = (Path(config.__file__)).read_text(encoding="utf-8")
    for rol, variable in (("long", "LONG"), ("mechanical", "MECHANICAL")):
        defecto = re.search(rf'"LOCAL_DELEGATE_MODEL_{variable}",\s*"([^"]+)"', fuente)
        assert defecto, variable
        assert common.MODELOS_POR_DEFECTO[rol] == defecto.group(1)
    umbral = re.search(r'"LOCAL_DELEGATE_LONG_INPUT_CHARS",\s*(\d+)', fuente)
    assert umbral and common.UMBRAL_LARGO_CHARS == int(umbral.group(1))


def test_el_directorio_de_logs_del_hook_es_el_de_config(monkeypatch):
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)
    assert common.directorio_de_logs() == config._default_log_dir()


# --- REQ-F1-11: apagado en caliente por fichero, y el estado en cada evento -----------------------


def test_el_fichero_interruptor_apaga_el_bloqueo_aunque_la_variable_diga_1(
    entorno, monkeypatch, capsys
):
    destino = _prosa(entorno)
    payload = {"tool_input": {"file_path": str(destino)}}
    assert "deny" in _correr(read_hook, monkeypatch, capsys, payload)
    (entorno / "bloqueo-apagado").write_text("", encoding="utf-8")
    assert "deny" not in _correr(read_hook, monkeypatch, capsys, payload)


def test_cada_evento_anota_el_estado_del_bloqueo(entorno, monkeypatch, capsys):
    destino = _prosa(entorno)
    franja = {"tool_input": {"file_path": str(destino), "offset": 1, "limit": 10}}
    _correr(read_hook, monkeypatch, capsys, franja)
    (entorno / "bloqueo-apagado").write_text("", encoding="utf-8")
    _correr(read_hook, monkeypatch, capsys, franja)
    monkeypatch.setenv("LD_HOOK_READ_BLOQUEAR", "0")
    (entorno / "bloqueo-apagado").unlink()
    _correr(read_hook, monkeypatch, capsys, franja)
    _correr(shell_hook, monkeypatch, capsys, {"tool_input": {"command": "git status"}})
    assert [e["bloqueo"] for e in _eventos(entorno)] == [
        "encendido",
        "apagado_fichero",
        "apagado_variable",
        "apagado_variable",
    ]


class _Backend(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args) -> None:
        pass


def test_el_apagado_no_necesita_relanzar_nada(tmp_path):
    """Dos invocaciones del hook como PROCESOS aparte, con el mismo entorno heredado: entre una y
    otra solo cambia el fichero. Es lo que hace el cliente real, que lanza un proceso por lectura;
    cambiar `os.environ` dentro del mismo proceso no lo demostraba."""
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        destino = _prosa(tmp_path)
        interruptor = tmp_path / "bloqueo-apagado"
        env = {
            **os.environ,
            "LD_HOOK_READ_BLOQUEAR": "1",
            "LD_HOOK_READ_INTERRUPTOR": str(interruptor),
            "LD_HOOK_ENABLED": "1",
            "LOCAL_DELEGATE_BASE_URL": f"http://127.0.0.1:{servidor.server_address[1]}/v1",
            "LOCAL_DELEGATE_LOG_DIR": str(tmp_path / "logs"),
        }
        entrada = json.dumps({"tool_input": {"file_path": str(destino)}})

        def invocar() -> str:
            return subprocess.run(
                [sys.executable, str(HOOKS / "suggest_delegate_read.py"), "--enabled"],
                input=entrada,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=True,
            ).stdout

        assert "deny" in invocar(), "control: encendido y con backend, bloquea"
        interruptor.write_text("", encoding="utf-8")
        assert "deny" not in invocar()
        interruptor.unlink()
        assert "deny" in invocar(), "y quitar el fichero lo vuelve a encender, sin relanzar"
    finally:
        servidor.shutdown()
