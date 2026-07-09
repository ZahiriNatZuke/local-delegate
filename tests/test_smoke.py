"""Smoke tests: el paquete importa, registra sus 11 tools y su config está desacoplada."""

from __future__ import annotations

import asyncio

from local_delegate import config, server

EXPECTED_TOOLS = {
    "local_summarize",
    "local_classify",
    "local_extract",
    "local_boilerplate",
    "local_delegate",
    "local_lint_summary",
    "local_commit_msg",
    "local_translate",
    "local_explain_code",
    "local_status",
    "local_describe_image",
}


def test_eleven_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    assert len(tools) == 11


def test_config_defaults():
    assert config.BASE_URL == "http://127.0.0.1:9292/v1"
    assert config.AUTOSTART is False  # opt-in por defecto
    assert config.WEB_ENABLED is True
    # el log vive en el dir de datos de usuario, no en una ruta de máquina concreta
    assert config.USAGE_LOG.name == "usage.jsonl"


def test_allowed_models_derived_from_roles():
    assert config.MODEL_MECHANICAL in config.ALLOWED_MODELS
    assert config.MODEL_CODE in config.ALLOWED_MODELS


def test_dashboard_html_present():
    from local_delegate.web import metrics

    assert metrics.HTML.lstrip().startswith("<!doctype html>")
    assert "<script>" in metrics.HTML
