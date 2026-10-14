"""Tests de los hooks consultivos de Claude Code."""

from __future__ import annotations

import importlib.util
import io
import json
import re
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


# Prompts reales capturados el 2026-09-22 (Claude Code 2.1.280). Los tres contienen «summary» o
# «resumen», que el clasificador toma por intención de resumir: sin el filtro, los tres avisaban.
_SYSTEM_EVENTS = (
    (
        '<agent-message from="a77f5562467da25a7">\n[Subagent hand-back] The text below is the '
        "final report... Summary: resumen ok"
    ),
    (
        'Another Claude session sent a message:\n<agent-message from="ae9f2401d225a89d1">\n'
        "[Subagent hand-back] ... summary of findings"
    ),
    "<task-notification>\n<task-id>a77f5562467da25a7</task-id>\n<summary>Agent finished</summary>",
)


def test_prompt_hook_ignores_system_events(tmp_path, monkeypatch, capsys):
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    for text in _SYSTEM_EVENTS:
        # Control positivo: sin el prefijo de sistema, el mismo texto SÍ se clasifica. Si no,
        # el test pasaría aunque el filtro no existiera.
        body = text.split(">", 1)[1]
        assert prompt.classify(body) == "summarize"

        assert prompt.is_system_event(text)
        assert prompt.classify(text) is None
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": text})))
        prompt.main()

    assert capsys.readouterr().out == ""
    assert not log.exists()  # tampoco cuentan como prompts en la telemetría


def test_prompt_hook_matches_every_system_prefix():
    for text in (
        '<cross-session-message from="x">\nresume esto',
        "<system-reminder>\nresume esto",
        "  \n<task-notification>\nresume esto",  # espacios y saltos delante
    ):
        assert prompt.is_system_event(text), text


def test_prompt_hook_still_warns_on_real_prompt_end_to_end(tmp_path, monkeypatch, capsys):
    # Sin esto, un filtro que silenciara TODO (p. ej. `if ... or True: return`) pasaría la suite.
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"prompt": "Resume este archivo en cinco viñetas"}))
    )

    prompt.main()

    output = json.loads(capsys.readouterr().out)
    assert "local_*" in output["hookSpecificOutput"]["additionalContext"]
    event = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert event["suggested"] is True
    assert event["category"] == "summarize"


def test_prompt_hook_still_classifies_user_prompts_mentioning_tags():
    # Un usuario que cita la etiqueta a mitad de su mensaje sigue siendo un prompt.
    assert not prompt.is_system_event("Resume qué hace <task-notification> en este log")
    assert prompt.classify("Resume qué hace <task-notification> en este log") == "summarize"


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


def _run_hook(monkeypatch, capsys, tool_input):
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": tool_input})))
    read_hook.main()
    return capsys.readouterr().out


def test_read_hook_stays_quiet_on_code(tmp_path, monkeypatch, capsys):
    """Un `.ts` de 150 KB se lee para editarlo, y eso no se delega.

    Era el caso mas frecuente del ruido: 562 de las 1 579 lecturas medidas.
    """
    target = tmp_path / "service.ts"
    target.write_text("x" * 150 * 1024, encoding="utf-8")

    assert _run_hook(monkeypatch, capsys, {"file_path": str(target)}) == ""


def test_read_hook_respects_a_range_asked_on_purpose(tmp_path, monkeypatch, capsys):
    """Con offset/limit el modelo ya sabe que parte quiere; sugerirle un resumen sobra."""
    target = tmp_path / "report.md"
    target.write_text("x" * 200 * 1024, encoding="utf-8")

    output = _run_hook(monkeypatch, capsys, {"file_path": str(target), "offset": 500, "limit": 100})

    assert output == ""


def test_read_hook_stays_quiet_on_a_small_file(tmp_path, monkeypatch, capsys):
    """5 KB está por debajo del umbral, que desde el 2026-09-08 es de 8 KB y no de 32.

    Este test se llamaba «mediano» y usaba 20 KB. Falló al bajar el umbral, que es exactamente su
    trabajo: era el guardián del comportamiento que se cambió a propósito. La medición que lo
    movió está en la cabecera del hook — 24 de 24 lecturas calladas por tamaño eran documentación,
    17 de ellas entre 8 y 16 KB, o sea dentro de los 20 KB que este test daba por «mediano».
    """
    target = tmp_path / "notes.md"
    target.write_text("x" * 5 * 1024, encoding="utf-8")

    assert _run_hook(monkeypatch, capsys, {"file_path": str(target)}) == ""


def test_read_hook_warns_in_the_band_that_used_to_stay_silent(tmp_path, monkeypatch, capsys):
    """20 KB: callaba con el umbral de 32 y ahora avisa. Es el cambio, medido por su efecto."""
    target = tmp_path / "notes.md"
    target.write_text("x" * 20 * 1024, encoding="utf-8")

    output = _run_hook(monkeypatch, capsys, {"file_path": str(target)})
    assert "Sugerencia" in output, output
    assert "Recomendacion fuerte" not in output, "20 KB no es la banda fuerte"


def test_read_hook_still_warns_about_the_case_worth_it(tmp_path, monkeypatch, capsys):
    """Control de los tres de arriba.

    Sin el, un hook roto que no sugiriera nunca dejaria los tres en verde. Este es el unico que
    falla en ese caso: 120 KB de texto leido entero es exactamente lo que el hook existe para
    atrapar.
    """
    target = tmp_path / "changelog.md"
    target.write_text("x" * 120 * 1024, encoding="utf-8")

    output = _run_hook(monkeypatch, capsys, {"file_path": str(target)})

    payload = json.loads(output)
    assert "Recomendacion fuerte" in payload["hookSpecificOutput"]["additionalContext"]


def test_read_hook_records_the_discards_to_measure_aim(tmp_path, monkeypatch):
    """Un descarte silencioso no tiene denominador, y sin denominador no hay punteria.

    Es lo que dejo a este hook tres semanas apuntando a codigo sin que se notara.
    """
    common = _load("hook_common")
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setattr(read_hook, "record", common.record)

    target = tmp_path / "component.tsx"
    target.write_text("x" * 90 * 1024, encoding="utf-8")
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"tool_input": {"file_path": str(target)}}))
    )

    read_hook.main()

    event = json.loads(log.read_text(encoding="utf-8").strip())
    assert event["suggested"] is False
    assert event["ext"] == ".tsx"
    assert event["reason"] == "code"


def test_read_hook_does_not_leak_the_file_name_through_the_extension(tmp_path, monkeypatch):
    """`ext` entra al log; el nombre y la ruta no. Y una extension rara tampoco."""
    common = _load("hook_common")
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setattr(read_hook, "record", common.record)

    folder = tmp_path / "confidential-client"
    folder.mkdir()
    target = folder / "secret-report.md"
    target.write_text("x" * 10 * 1024, encoding="utf-8")
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"tool_input": {"file_path": str(target)}}))
    )

    read_hook.main()

    text = log.read_text(encoding="utf-8")
    assert '"ext": ".md"' in text
    assert "confidencial" not in text
    assert "secreto" not in text
    assert read_hook.extension_of("/x/y.contrato-acme-2026") == ""


def _hook_default(variable: str) -> float:
    """El default que el hook lleva escrito, leído del fuente y no de un import.

    El hook es stdlib pura y lee `os.environ` con su propio literal, así que el valor no está
    expuesto como constante: se saca del código, que es la única fuente que el hook usa de verdad.
    """
    source = (HOOKS / "suggest_delegate_read.py").read_text(encoding="utf-8")
    found = re.search(rf'os\.environ\.get\("{variable}", "([\d.]+)"\)', source)
    assert found, f"no se encontró el default de {variable} en el hook"
    return float(found.group(1))


def test_the_read_hook_threshold_does_not_have_two_values():
    """El mismo número vive en tres sitios; que se separen es el defecto recurrente de este repo.

    El hook **no puede importar `config`** —es stdlib pura porque se copia al HOME del usuario—,
    así que la duplicación no se puede eliminar: solo atar. `config.py` declara estas variables
    para que el inventario de aislamiento las vea (REQ-022), y la tabla de la recipe es lo que lee
    quien las cambia a mano. Si los tres no dicen lo mismo, el usuario configura un valor creyendo
    otro.
    """
    from local_delegate import config

    recipe = (Path(__file__).parents[1] / "docs" / "recipes" / "claude-code-hooks.md").read_text(
        encoding="utf-8"
    )

    for variable, in_config in (
        ("LD_HOOK_READ_SUGGEST_KB", config.HOOK_READ_SUGGEST_KB),
        ("LD_HOOK_READ_STRONG_KB", config.HOOK_READ_STRONG_KB),
    ):
        in_hook = _hook_default(variable)
        assert in_hook == in_config, f"{variable}: el hook dice {in_hook} y config.py {in_config}"
        row = re.search(rf"\| `{variable}` \| `([\d.]+)` \|", recipe)
        assert row, f"{variable} no está en la tabla de docs/recipes/claude-code-hooks.md"
        assert float(row.group(1)) == in_hook, (
            f"{variable}: la recipe dice {row.group(1)} y el hook {in_hook}"
        )


def test_the_hook_docstring_states_the_real_thresholds():
    """La cabecera del hook es lo primero que lee quien lo abre; envejece sola."""
    source = (HOOKS / "suggest_delegate_read.py").read_text(encoding="utf-8")
    low = _hook_default("LD_HOOK_READ_SUGGEST_KB")
    high = _hook_default("LD_HOOK_READ_STRONG_KB")
    expected = (
        f"LD_HOOK_READ_SUGGEST_KB (default {low:g} KB) y "
        f"LD_HOOK_READ_STRONG_KB (default {high:g} KB)"
    )
    assert expected in source, f"el docstring del hook no dice «{expected}»"


# --- El bloqueo de F1 -------------------------------------------------------------------------
#
# Cuatro mediciones seguidas con adopcion cero, la ultima ya con el aviso acertando el tipo de
# fichero. La conclusion no fue redactar mejor el aviso, fue dejar de sugerir. Lo que sigue cubre
# los tres tratos (bloquear, avisar, callar) y las tres formas de apagar el bloqueo.


def _run_with_block(monkeypatch, capsys, tool_input, *, backend=True, enabled=True):
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1" if enabled else "0")
    monkeypatch.setattr(read_hook, "backend_available", lambda **k: backend)
    return _run_hook(monkeypatch, capsys, tool_input)


def _decision(output: str) -> dict:
    return json.loads(output)["hookSpecificOutput"]


def test_large_prose_is_blocked_and_the_message_says_the_way_out(tmp_path, monkeypatch, capsys):
    """El caso acotado: un `.md` de 40 KB leido entero, con el backend vivo."""
    target = tmp_path / "report.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")

    decision = _decision(_run_with_block(monkeypatch, capsys, {"file_path": str(target)}))

    assert decision["permissionDecision"] == "deny"
    reason = decision["permissionDecisionReason"]
    assert "local_summarize" in reason, "el bloqueo tiene que nombrar la tool que sirve"
    assert str(target) in reason, "y el path, para que llamarla sea copiar y pegar"
    assert "offset" in reason, "y la salida de emergencia: leer por franjas"


def test_a_large_json_is_warned_about_but_not_blocked(tmp_path, monkeypatch, capsys):
    """Control positivo del anterior. Un `state.json` se lee para sacar un valor exacto."""
    target = tmp_path / "state.json"
    target.write_text("x" * 40 * 1024, encoding="utf-8")

    decision = _decision(_run_with_block(monkeypatch, capsys, {"file_path": str(target)}))

    assert "permissionDecision" not in decision
    assert "local_extract" in decision["additionalContext"]


def test_code_still_says_nothing(tmp_path, monkeypatch, capsys):
    """Ni bloqueo ni aviso: el mercado medido es documentacion, no codigo."""
    target = tmp_path / "service.py"
    target.write_text("x" * 200 * 1024, encoding="utf-8")

    assert _run_with_block(monkeypatch, capsys, {"file_path": str(target)}) == ""


def test_a_range_asked_on_purpose_is_not_blocked(tmp_path, monkeypatch, capsys):
    """Es la salida de emergencia que el propio mensaje del bloqueo ofrece: tiene que funcionar."""
    target = tmp_path / "report.md"
    target.write_text("x" * 200 * 1024, encoding="utf-8")

    output = _run_with_block(
        monkeypatch, capsys, {"file_path": str(target), "offset": 100, "limit": 50}
    )

    assert output == ""


def test_without_backend_it_is_not_blocked_even_when_due(tmp_path, monkeypatch, capsys):
    """Bloquear sin sitio a donde delegar deja al agente sin forma de leer el fichero."""
    target = tmp_path / "report.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")

    decision = _decision(
        _run_with_block(monkeypatch, capsys, {"file_path": str(target)}, backend=False)
    )

    assert "permissionDecision" not in decision, "sin backend, la lectura pasa"
    assert (
        "Sugerencia" in decision["additionalContext"]
        or "Recomendacion" in (decision["additionalContext"])
    )


def test_the_block_starts_off(tmp_path, monkeypatch, capsys):
    """Se enciende cuando este escrito el criterio de la quinta medicion, no antes."""
    target = tmp_path / "report.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")
    monkeypatch.delenv("LD_HOOK_READ_BLOCK", raising=False)
    monkeypatch.setattr(read_hook, "backend_available", lambda **k: True)

    decision = _decision(_run_hook(monkeypatch, capsys, {"file_path": str(target)}))

    assert "permissionDecision" not in decision


def test_turning_off_does_not_need_a_session_restart(tmp_path, monkeypatch, capsys):
    """La variable se consulta en CADA invocacion: un freno que exige reiniciar no es un freno."""
    target = tmp_path / "report.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")
    monkeypatch.setattr(read_hook, "backend_available", lambda **k: True)

    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    assert "deny" in _run_hook(monkeypatch, capsys, {"file_path": str(target)})

    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "0")
    assert "deny" not in _run_hook(monkeypatch, capsys, {"file_path": str(target)})


def test_each_event_says_which_script_ran_and_in_which_session(tmp_path, monkeypatch):
    """Sin esto una medicion no se puede leer: una sesion abierta hereda el entorno del lanzador."""
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    monkeypatch.setattr(read_hook, "backend_available", lambda **k: True)
    target = tmp_path / "report.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"session_id": "s-42", "tool_input": {"file_path": str(target)}})),
    )

    read_hook.main()

    event = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert event["session_id"] == "s-42"
    assert len(event["version"]) == 8, "la huella del script que corrio"
    assert event["blocked"] is True
    assert len(event["id"]) == 12, "el identificador que permite cruzarlo con la delegacion"
    # La telemetria sigue sin llevar rutas ni contenido.
    assert str(target) not in json.dumps(event)


def test_the_fingerprint_groups_by_file_without_saying_which(tmp_path, monkeypatch, capsys):
    """Sin esto, «de las lecturas acotadas, cuantas eran de un fichero que acabo leyendose
    entero» no se puede responder: la telemetria no guarda rutas, a proposito.

    La huella lo permite —el mismo fichero da el mismo valor— sin que el log diga nunca que
    fichero era.
    """
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    document = tmp_path / "the-client-report.md"
    document.write_text("x" * 40 * 1024, encoding="utf-8")

    # Primero una franja, despues el fichero entero: dos eventos del MISMO fichero.
    _run_hook(monkeypatch, capsys, {"file_path": str(document), "limit": 20})
    _run_hook(monkeypatch, capsys, {"file_path": str(document)})

    events = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [e["reason"] for e in events[:1]] == ["bounded"]
    assert events[0]["path_sha"] == events[1]["path_sha"], "el mismo fichero, la misma huella"

    raw = log.read_text(encoding="utf-8")
    assert "the-client-report" not in raw
    assert str(tmp_path) not in raw


def test_two_distinct_files_are_not_confused(tmp_path, monkeypatch, capsys):
    """Control positivo: una huella constante agruparia todo y la medicion diria cualquier cosa."""
    log = tmp_path / "telemetry.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    for name in ("one.md", "two.md"):
        file = tmp_path / name
        file.write_text("x" * 40 * 1024, encoding="utf-8")
        _run_hook(monkeypatch, capsys, {"file_path": str(file)})

    events = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert events[0]["path_sha"] != events[1]["path_sha"]


# --- Sesión, versión y bloqueo en la telemetría del prompt (SDD subagente-lector-local) ----------


def _prompt_event(tmp_path, monkeypatch, text: str, **env: str) -> dict:
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"prompt": text, "session_id": "s-123"}))
    )
    prompt.main()
    return json.loads(log.read_text(encoding="utf-8").splitlines()[-1])


def test_every_prompt_event_carries_session_version_and_block(tmp_path, monkeypatch):
    # Los dos caminos: el que sugiere y el que no. El banco de `scripts/` valida CADA corrida por
    # este evento, así que tiene que existir aunque el hook calle.
    for text in ("Resume este archivo en cinco viñetas", "Hola, ¿qué tal?"):
        event = _prompt_event(
            tmp_path,
            monkeypatch,
            text,
            LD_HOOK_READ_BLOCK="1",
            LD_HOOK_READ_SWITCH_FILE=str(tmp_path / "missing"),
        )
        assert event["session_id"] == "s-123", text
        assert event["version"]  # huella del script que corrió
        assert event["block"] == "on"
