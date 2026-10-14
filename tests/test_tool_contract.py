"""El contrato de las tools MCP (ola B2b-1; REQ-010 y REQ-027).

- Las descripciones (docstrings, descripciones de parámetro, títulos de anotación y la descripción
  del servidor) están en inglés y **no cambian** con `LOCAL_DELEGATE_LANG`: el cliente MCP las
  cachea por sesión y un modelo decide con ellas si delega.
- Los nombres de tool, los parámetros, sus tipos y sus valores por defecto son los de la 0.35.0
  (`tests/data/tool_schema_0_35.json`, sin descripciones): una firma cambiada rompe a los clientes.
- `_local_delegate` lleva solo las claves nuevas (`truncated`, `warning`, `read_server_side`,
  `fallback`, `raw`) y los marcadores son los de REQ-010.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import config, i18n, server

ROOT = Path(__file__).parents[1]
SNAPSHOT = ROOT / "tests" / "data" / "tool_schema_0_35.json"
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
_ACCENTS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡«»]")
#: Las claves viejas de `_local_delegate` (REQ-010): no puede salir ninguna.
OLD_KEYS = {"truncado", "aviso", "leido_server_side", "tokens_aprox", "respaldo", "crudo"}
OLD_FALLBACK_KEYS = {"respondio", "en_lugar_de", "motivo", "clase"}


def _strip_descriptions(value):
    if isinstance(value, dict):
        return {k: _strip_descriptions(v) for k, v in value.items() if k != "description"}
    if isinstance(value, list):
        return [_strip_descriptions(v) for v in value]
    return value


def _spanish_words() -> set[str]:
    lexicon = json.loads(
        (ROOT / "scripts" / "data" / "spanish_lexicon.json").read_text(encoding="utf-8")
    )
    return set(lexicon["es"]) - set(lexicon["en"])


_LISTING = (
    "import asyncio, json\n"
    "from local_delegate import server\n"
    "tools = asyncio.run(server.mcp.list_tools())\n"
    "print(json.dumps([t.model_dump(mode='json', exclude_none=True) for t in tools]))\n"
)


def _listing_in_a_process(tmp_path, lang: str) -> list[dict]:
    """La lista de tools de un proceso que ARRANCA con ese idioma: las descripciones y los títulos
    se fijan al importar `server`, así que cambiar el idioma después no probaría nada."""
    env = {**os.environ, "LOCAL_DELEGATE_LANG": lang, "LOCAL_DELEGATE_LOG_DIR": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, "-c", _LISTING],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(done.stdout)


def test_descriptions_do_not_depend_on_the_language(tmp_path):
    """REQ-027. Control: que `_annotations` o un docstring dependan de `i18n` hace que la lista
    de un proceso en español y la de uno en inglés difieran."""
    spanish = _listing_in_a_process(tmp_path, "es")
    english = _listing_in_a_process(tmp_path, "en")
    assert spanish == english
    assert len(spanish) == 11


def test_server_description_and_titles_are_english_literals():
    assert server.mcp.title == "Local Delegate"
    assert set(server.TOOL_TITLES) == {t.name for t in asyncio.run(server.mcp.list_tools())}
    for tool in asyncio.run(server.mcp.list_tools()):
        assert tool.annotations is not None
        assert tool.annotations.title == server.TOOL_TITLES[tool.name]


def test_names_parameters_and_defaults_are_those_of_0_35():
    """Una tool, un parámetro, un tipo o un valor por defecto cambiados rompen a los clientes.
    Control: renombrar `max_words` de `local_summarize` hace fallar la igualdad de esa tool."""
    frozen = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in tools} == set(frozen)
    for tool in tools:
        dumped = tool.model_dump(mode="json", exclude_none=True, by_alias=True)
        annotations = dict(dumped.get("annotations", {}))
        annotations.pop("title", None)
        current = {
            "annotations": annotations,
            "input_schema": _strip_descriptions(dumped["inputSchema"]),
        }
        assert current == frozen[tool.name], tool.name


def test_descriptions_have_no_spanish():
    """REQ-027: docstrings, descripciones de parámetro, títulos y la del servidor en inglés.
    Control: dejar un `Args:` con «Ruta a un archivo» hace fallar el de palabras españolas."""
    words = _spanish_words()
    texts = [server.SERVER_DESCRIPTION, *server.TOOL_TITLES.values()]
    for tool in asyncio.run(server.mcp.list_tools()):
        texts.append(tool.description or "")
        schema = tool.model_dump(mode="json", by_alias=True)["inputSchema"]
        texts.extend(p.get("description", "") for p in schema.get("properties", {}).values())
    joined = "\n".join(texts)
    assert not _ACCENTS.search(joined), _ACCENTS.findall(joined)
    found = sorted({w.lower() for w in _WORD.findall(joined)} & words)
    assert not found, found
    assert "PREFER this tool" in joined  # guarda: los docstrings llegaron a mirarse


# --- `_local_delegate` y marcadores (REQ-010) ---------------------------------------------------


def _backend(monkeypatch, content: str, *, base: str, finish: str = "stop") -> None:
    monkeypatch.setattr(config, "BASE_URL", base)
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    monkeypatch.setattr(config, "FALLBACK", False)
    backend_mock.post(f"{base}/chat/completions").mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )
    )


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    return set()


@pytest.mark.parametrize("lang", ["es", "en"])
@backend_mock.mock
def test_extract_meta_uses_the_new_keys(monkeypatch, tmp_path, lang):
    """Salida truncada (B2c: en un trozo del troceado) leída de un `path`: `truncated`, `warning`
    y `read_server_side`. Control: volver a `meta["truncado"]` deja una clave vieja y falla el
    «ninguna vieja»."""
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()
    _backend(monkeypatch, '{"a": "1"}', base=f"http://contract-{lang}/v1", finish="length")
    monkeypatch.setitem(config.MAX_CHARS_BY_ROLE, "mechanical", 500)
    source = tmp_path / "in.txt"
    source.write_text("a=1\n" * 400, encoding="utf-8")
    result = server.local_extract(fields=["a"], path=str(source))
    meta = result["_local_delegate"]
    assert meta["truncated"] is True and meta["warning"]
    assert set(meta["read_server_side"]) == {"chars", "approx_tokens"}
    assert not _keys(result) & OLD_KEYS


@backend_mock.mock
def test_extract_error_uses_raw(monkeypatch):
    _backend(monkeypatch, "not json", base="http://contract-raw/v1")
    result = server.local_extract(fields=["a"], text="a=1")
    assert set(result["_local_delegate"]) == {"error", "raw"}
    assert result["_local_delegate"]["raw"] == "not json"


def test_fallback_info_uses_the_new_keys():
    """REQ-010: `fallback.{answered_by, instead_of, reason, class}`, también en el aviso visible.
    Control: devolver `respondio` deja la clave vieja y falla la igualdad de conjuntos."""
    attempts = [
        server.Attempt("gemma3-4b", False, "timeout", "model", 10),
        server.Attempt("gemma4-26b-a4b", True, None, None, 10),
    ]
    result = server.ChatResult(text="ok", ok=True, finish_reason="stop")
    info = server._fallback_info("gemma3-4b", result, attempts)
    assert info is not None
    assert set(info) == {"answered_by", "instead_of", "reason", "class"}
    assert not set(info) & OLD_FALLBACK_KEYS
    notice = server._fallback_notice(info)
    assert notice.startswith("\n\n[local-delegate warning: ")


@pytest.mark.parametrize("lang", ["es", "en"])
def test_markers_are_the_new_ones_in_both_languages(monkeypatch, lang):
    """Los marcadores no cambian con el idioma; el texto detrás, sí. Control: dejar `aviso` en
    `sections.WARNING_MARKER` hace fallar el primer assert en los dos idiomas."""
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()
    assert server.WARNING_MARKER == "[local-delegate warning: "
    assert server.FALLBACK_MARKER == "[local-delegate fallback: "
    prefix = server._truncation_prefix("x" * 10, True, 20)
    assert prefix.startswith("[local-delegate: input truncated — ")
    assert prefix.endswith("10 de 20 chars]\n" if lang == "es" else "10 of 20 chars]\n")
    for old in ("aviso", "respaldo", "entrada truncada"):
        assert old not in server.WARNING_MARKER + server.FALLBACK_MARKER + prefix
