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


def test_read_hook_calla_ante_un_archivo_pequeno(tmp_path, monkeypatch, capsys):
    """5 KB está por debajo del umbral, que desde el 2026-09-08 es de 8 KB y no de 32.

    Este test se llamaba «mediano» y usaba 20 KB. Falló al bajar el umbral, que es exactamente su
    trabajo: era el guardián del comportamiento que se cambió a propósito. La medición que lo
    movió está en la cabecera del hook — 24 de 24 lecturas calladas por tamaño eran documentación,
    17 de ellas entre 8 y 16 KB, o sea dentro de los 20 KB que este test daba por «mediano».
    """
    target = tmp_path / "notas.md"
    target.write_text("x" * 5 * 1024, encoding="utf-8")

    assert _correr_hook(monkeypatch, capsys, {"file_path": str(target)}) == ""


def test_read_hook_avisa_en_la_franja_que_antes_quedaba_muda(tmp_path, monkeypatch, capsys):
    """20 KB: callaba con el umbral de 32 y ahora avisa. Es el cambio, medido por su efecto."""
    target = tmp_path / "notas.md"
    target.write_text("x" * 20 * 1024, encoding="utf-8")

    salida = _correr_hook(monkeypatch, capsys, {"file_path": str(target)})
    assert "Sugerencia" in salida, salida
    assert "Recomendacion fuerte" not in salida, "20 KB no es la banda fuerte"


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


def _default_del_hook(variable: str) -> float:
    """El default que el hook lleva escrito, leído del fuente y no de un import.

    El hook es stdlib pura y lee `os.environ` con su propio literal, así que el valor no está
    expuesto como constante: se saca del código, que es la única fuente que el hook usa de verdad.
    """
    fuente = (HOOKS / "suggest_delegate_read.py").read_text(encoding="utf-8")
    hallado = re.search(rf'os\.environ\.get\("{variable}", "([\d.]+)"\)', fuente)
    assert hallado, f"no se encontró el default de {variable} en el hook"
    return float(hallado.group(1))


def test_el_umbral_del_hook_de_lectura_no_tiene_dos_valores():
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

    for variable, en_config in (
        ("LD_HOOK_READ_SUGGEST_KB", config.HOOK_READ_SUGGEST_KB),
        ("LD_HOOK_READ_STRONG_KB", config.HOOK_READ_STRONG_KB),
    ):
        en_hook = _default_del_hook(variable)
        assert en_hook == en_config, f"{variable}: el hook dice {en_hook} y config.py {en_config}"
        fila = re.search(rf"\| `{variable}` \| `([\d.]+)` \|", recipe)
        assert fila, f"{variable} no está en la tabla de docs/recipes/claude-code-hooks.md"
        assert float(fila.group(1)) == en_hook, (
            f"{variable}: la recipe dice {fila.group(1)} y el hook {en_hook}"
        )


def test_el_docstring_del_hook_dice_los_umbrales_de_verdad():
    """La cabecera del hook es lo primero que lee quien lo abre; envejece sola."""
    fuente = (HOOKS / "suggest_delegate_read.py").read_text(encoding="utf-8")
    bajo = _default_del_hook("LD_HOOK_READ_SUGGEST_KB")
    alto = _default_del_hook("LD_HOOK_READ_STRONG_KB")
    esperado = (
        f"LD_HOOK_READ_SUGGEST_KB (default {bajo:g} KB) y "
        f"LD_HOOK_READ_STRONG_KB (default {alto:g} KB)"
    )
    assert esperado in fuente, f"el docstring del hook no dice «{esperado}»"


# --- El bloqueo de F1 -------------------------------------------------------------------------
#
# Cuatro mediciones seguidas con adopcion cero, la ultima ya con el aviso acertando el tipo de
# fichero. La conclusion no fue redactar mejor el aviso, fue dejar de sugerir. Lo que sigue cubre
# los tres tratos (bloquear, avisar, callar) y las tres formas de apagar el bloqueo.


def _correr_con_bloqueo(monkeypatch, capsys, tool_input, *, backend=True, encendido=True):
    monkeypatch.setenv("LD_HOOK_READ_BLOQUEAR", "1" if encendido else "0")
    monkeypatch.setattr(read_hook, "backend_disponible", lambda **k: backend)
    return _correr_hook(monkeypatch, capsys, tool_input)


def _decision(salida: str) -> dict:
    return json.loads(salida)["hookSpecificOutput"]


def test_la_prosa_grande_se_bloquea_y_el_mensaje_dice_por_donde_salir(
    tmp_path, monkeypatch, capsys
):
    """El caso acotado: un `.md` de 40 KB leido entero, con el backend vivo."""
    target = tmp_path / "informe.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")

    decision = _decision(_correr_con_bloqueo(monkeypatch, capsys, {"file_path": str(target)}))

    assert decision["permissionDecision"] == "deny"
    motivo = decision["permissionDecisionReason"]
    assert "local_summarize" in motivo, "el bloqueo tiene que nombrar la tool que sirve"
    assert str(target) in motivo, "y el path, para que llamarla sea copiar y pegar"
    assert "offset" in motivo, "y la salida de emergencia: leer por franjas"


def test_un_json_grande_se_avisa_pero_no_se_bloquea(tmp_path, monkeypatch, capsys):
    """Control positivo del anterior. Un `state.json` se lee para sacar un valor exacto."""
    target = tmp_path / "state.json"
    target.write_text("x" * 40 * 1024, encoding="utf-8")

    decision = _decision(_correr_con_bloqueo(monkeypatch, capsys, {"file_path": str(target)}))

    assert "permissionDecision" not in decision
    assert "local_extract" in decision["additionalContext"]


def test_el_codigo_sigue_sin_decir_nada(tmp_path, monkeypatch, capsys):
    """Ni bloqueo ni aviso: el mercado medido es documentacion, no codigo."""
    target = tmp_path / "servicio.py"
    target.write_text("x" * 200 * 1024, encoding="utf-8")

    assert _correr_con_bloqueo(monkeypatch, capsys, {"file_path": str(target)}) == ""


def test_una_franja_pedida_a_proposito_no_se_bloquea(tmp_path, monkeypatch, capsys):
    """Es la salida de emergencia que el propio mensaje del bloqueo ofrece: tiene que funcionar."""
    target = tmp_path / "informe.md"
    target.write_text("x" * 200 * 1024, encoding="utf-8")

    salida = _correr_con_bloqueo(
        monkeypatch, capsys, {"file_path": str(target), "offset": 100, "limit": 50}
    )

    assert salida == ""


def test_sin_backend_no_se_bloquea_aunque_toque(tmp_path, monkeypatch, capsys):
    """Bloquear sin sitio a donde delegar deja al agente sin forma de leer el fichero."""
    target = tmp_path / "informe.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")

    decision = _decision(
        _correr_con_bloqueo(monkeypatch, capsys, {"file_path": str(target)}, backend=False)
    )

    assert "permissionDecision" not in decision, "sin backend, la lectura pasa"
    assert (
        "Sugerencia" in decision["additionalContext"]
        or "Recomendacion" in (decision["additionalContext"])
    )


def test_el_bloqueo_nace_apagado(tmp_path, monkeypatch, capsys):
    """Se enciende cuando este escrito el criterio de la quinta medicion, no antes."""
    target = tmp_path / "informe.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")
    monkeypatch.delenv("LD_HOOK_READ_BLOQUEAR", raising=False)
    monkeypatch.setattr(read_hook, "backend_disponible", lambda **k: True)

    decision = _decision(_correr_hook(monkeypatch, capsys, {"file_path": str(target)}))

    assert "permissionDecision" not in decision


def test_el_apagado_no_necesita_reiniciar_la_sesion(tmp_path, monkeypatch, capsys):
    """La variable se consulta en CADA invocacion: un freno que exige reiniciar no es un freno."""
    target = tmp_path / "informe.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")
    monkeypatch.setattr(read_hook, "backend_disponible", lambda **k: True)

    monkeypatch.setenv("LD_HOOK_READ_BLOQUEAR", "1")
    assert "deny" in _correr_hook(monkeypatch, capsys, {"file_path": str(target)})

    monkeypatch.setenv("LD_HOOK_READ_BLOQUEAR", "0")
    assert "deny" not in _correr_hook(monkeypatch, capsys, {"file_path": str(target)})


def test_cada_evento_dice_que_script_corrio_y_en_que_sesion(tmp_path, monkeypatch):
    """Sin esto una medicion no se puede leer: una sesion abierta hereda el entorno del lanzador."""
    log = tmp_path / "telemetria.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(log))
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOQUEAR", "1")
    monkeypatch.setattr(read_hook, "backend_disponible", lambda **k: True)
    target = tmp_path / "informe.md"
    target.write_text("x" * 40 * 1024, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"session_id": "s-42", "tool_input": {"file_path": str(target)}})),
    )

    read_hook.main()

    evento = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert evento["session_id"] == "s-42"
    assert len(evento["version"]) == 8, "la huella del script que corrio"
    assert evento["blocked"] is True
    assert len(evento["id"]) == 12, "el identificador que permite cruzarlo con la delegacion"
    # La telemetria sigue sin llevar rutas ni contenido.
    assert str(target) not in json.dumps(evento)
