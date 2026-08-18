"""Tests de los hooks consultivos de Claude Code."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"
sys.path.insert(0, str(HOOKS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prompt = _load("suggest_delegate_prompt")
read_hook = _load("suggest_delegate_read")


def test_prompt_hook_detects_mechanical_intent():
    assert prompt.classify("Resume este archivo en cinco viñetas") == "summarize"
    assert prompt.classify("Extrae nombre y fecha como JSON") == "extract"


def test_prompt_hook_keeps_architecture_and_research_in_host():
    assert prompt.classify("Investiga y diseña la arquitectura del sistema") is None
    assert prompt.classify("Resume el research multi-fuente y decide la migración") is None


def test_hook_telemetry_contains_no_prompt_command_or_path(tmp_path, monkeypatch):
    common = _load("hook_common")
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    common.record("PreToolUse", category="read", size_kb=40)
    text = log.read_text(encoding="utf-8")
    assert "category" in text
    assert "prompt" not in text
    assert "command" not in text
    assert "path" not in text


def test_disabled_hook_emits_nothing(tmp_path, monkeypatch, capsys):
    common = _load("hook_common")
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_ENABLED", "0")
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))

    common.emit("UserPromptSubmit", "context", category="summarize")

    assert capsys.readouterr().out == ""
    assert not log.exists()


def test_read_hook_is_disabled_by_default(tmp_path, monkeypatch, capsys):
    target = tmp_path / "large.txt"
    target.write_text("x" * 40 * 1024, encoding="utf-8")
    monkeypatch.delenv("LD_HOOK_READ_ENABLED", raising=False)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"tool_input": {"file_path": str(target)}})),
    )

    read_hook.main()

    assert capsys.readouterr().out == ""


def test_read_hook_can_be_enabled_explicitly(tmp_path, monkeypatch, capsys):
    target = tmp_path / "large.txt"
    target.write_text("x" * 40 * 1024, encoding="utf-8")
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"tool_input": {"file_path": str(target)}})),
    )

    read_hook.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "Sugerencia" in payload["hookSpecificOutput"]["additionalContext"]


# --- Punteria del hook de lectura -------------------------------------------------------------
#
# Medido sobre 14 dias de uso real: de 852 lecturas, el hook avisaba en 572 y solo 29 apuntaban a
# algo delegable. Los tres tests que siguen cubren los tres motivos de descarte, y el de despues
# es el control que impide que pasen en vacio.


def _correr_hook(monkeypatch, capsys, tool_input):
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": tool_input})))
    read_hook.main()
    return capsys.readouterr().out


def test_read_hook_calla_ante_codigo(tmp_path, monkeypatch, capsys):
    """Un `.ts` de 150 KB se lee para editarlo, y eso no se delega.

    Era el caso mas frecuente del ruido: 562 de las 1 579 lecturas medidas.
    """
    target = tmp_path / "servicio.ts"
    target.write_text("x" * 150 * 1024, encoding="utf-8")

    assert _correr_hook(monkeypatch, capsys, {"file_path": str(target)}) == ""


def test_read_hook_respeta_una_franja_pedida_a_proposito(tmp_path, monkeypatch, capsys):
    """Con offset/limit el modelo ya sabe que parte quiere; sugerirle un resumen sobra."""
    target = tmp_path / "informe.md"
    target.write_text("x" * 200 * 1024, encoding="utf-8")

    salida = _correr_hook(
        monkeypatch, capsys, {"file_path": str(target), "offset": 500, "limit": 100}
    )

    assert salida == ""


def test_read_hook_calla_ante_un_archivo_mediano(tmp_path, monkeypatch, capsys):
    """20 KB esta por debajo del umbral nuevo de 32 KB."""
    target = tmp_path / "notas.md"
    target.write_text("x" * 20 * 1024, encoding="utf-8")

    assert _correr_hook(monkeypatch, capsys, {"file_path": str(target)}) == ""


def test_read_hook_sigue_avisando_del_caso_que_vale_la_pena(tmp_path, monkeypatch, capsys):
    """Control de los tres de arriba.

    Sin el, un hook roto que no sugiriera nunca dejaria los tres en verde. Este es el unico que
    falla en ese caso: 120 KB de texto leido entero es exactamente lo que el hook existe para
    atrapar.
    """
    target = tmp_path / "changelog.md"
    target.write_text("x" * 120 * 1024, encoding="utf-8")

    salida = _correr_hook(monkeypatch, capsys, {"file_path": str(target)})

    payload = json.loads(salida)
    assert "Recomendacion fuerte" in payload["hookSpecificOutput"]["additionalContext"]


def test_read_hook_registra_los_descartes_para_poder_medir_punteria(tmp_path, monkeypatch):
    """Un descarte silencioso no tiene denominador, y sin denominador no hay punteria.

    Es lo que dejo a este hook tres semanas apuntando a codigo sin que se notara.
    """
    common = _load("hook_common")
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setattr(read_hook, "record", common.record)

    target = tmp_path / "componente.tsx"
    target.write_text("x" * 90 * 1024, encoding="utf-8")
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"tool_input": {"file_path": str(target)}}))
    )

    read_hook.main()

    evento = json.loads(log.read_text(encoding="utf-8").strip())
    assert evento["suggested"] is False
    assert evento["ext"] == ".tsx"
    assert evento["motivo"] == "codigo"


def test_read_hook_no_filtra_el_nombre_del_archivo_por_la_extension(tmp_path, monkeypatch):
    """`ext` entra al log; el nombre y la ruta no. Y una extension rara tampoco."""
    common = _load("hook_common")
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setattr(read_hook, "record", common.record)

    carpeta = tmp_path / "cliente-confidencial"
    carpeta.mkdir()
    target = carpeta / "informe-secreto.md"
    target.write_text("x" * 10 * 1024, encoding="utf-8")
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"tool_input": {"file_path": str(target)}}))
    )

    read_hook.main()

    texto = log.read_text(encoding="utf-8")
    assert '"ext": ".md"' in texto
    assert "confidencial" not in texto
    assert "secreto" not in texto
    assert read_hook.extension_de("/x/y.contrato-acme-2026") == ""
