"""Tests de F6 (local_describe_image): payload multimodal, validaciones de imagen y log."""

from __future__ import annotations

import base64
import json

import httpx
import respx

from local_delegate import config, server

# PNG válido de 1x1 px transparente (67 bytes) — no se guarda como asset binario en el repo.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _write_png(tmp_path, name: str = "img.png") -> str:
    p = tmp_path / name
    p.write_bytes(_TINY_PNG)
    return str(p)


@respx.mock
def test_describe_image_sends_multimodal_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    path = _write_png(tmp_path)
    route = respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "una imagen vacía"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 5},
            },
        )
    )
    text = server.local_describe_image(path)
    assert "una imagen vacía" in text
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == config.MODEL_VISION
    content = body["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_describe_image_missing_file_returns_error(tmp_path):
    text = server.local_describe_image(str(tmp_path / "no-existe.png"))
    assert text.startswith("[local-delegate error]")
    assert "No existe el archivo" in text


def test_describe_image_invalid_extension_returns_error(tmp_path):
    p = tmp_path / "no-es-imagen.txt"
    p.write_text("hola", encoding="utf-8")
    text = server.local_describe_image(str(p))
    assert text.startswith("[local-delegate error]")
    assert "Extensión de imagen no soportada" in text


def test_describe_image_too_large_returns_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_IMAGE_MB", 0)
    path = _write_png(tmp_path)
    text = server.local_describe_image(path)
    assert text.startswith("[local-delegate error]")
    assert "demasiado grande" in text


def test_describe_image_rejects_path_outside_allowed_dirs(monkeypatch, tmp_path):
    root = tmp_path / "proyecto"
    root.mkdir()
    monkeypatch.setattr(config, "ALLOWED_DIRS", [root.resolve()])
    outside = tmp_path / "otro"
    outside.mkdir()
    path = _write_png(outside)
    text = server.local_describe_image(path)
    assert text.startswith("[local-delegate error]")
    assert "fuera de las raíces permitidas" in text


@respx.mock
def test_describe_image_logs_real_tokens_and_path(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    path = _write_png(tmp_path)
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "descripción"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 5},
            },
        )
    )
    server.local_describe_image(path)
    rec = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["tool"] == "local_describe_image"
    assert rec["tokens_in"] == 300
    assert rec["path"] == path


@respx.mock
def test_describe_image_feedback_uses_real_tokens(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    path = _write_png(tmp_path)
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "descripción"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 5},
            },
        )
    )
    text = server.local_describe_image(path)
    assert "leído server-side: 68 bytes imagen ≈ 300 tokens" in text


@respx.mock
def test_describe_image_omits_feedback_when_no_usage(monkeypatch, tmp_path):
    """Sin usage.prompt_tokens no se estima con chars/4: esa heurística no aplica a bytes de imagen."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setattr(config, "FEEDBACK_ENABLED", True)
    path = _write_png(tmp_path)
    respx.post("http://test-backend/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "descripción"}, "finish_reason": "stop"}]},
        )
    )
    text = server.local_describe_image(path)
    assert "leído server-side" not in text


def test_validate_image_path_accepts_all_supported_extensions(tmp_path):
    for ext, mime in server._IMAGE_MIME.items():
        p = tmp_path / f"img{ext}"
        p.write_bytes(_TINY_PNG)
        assert server._validate_image_path(str(p)) == mime


def test_config_max_image_mb_default():
    assert config.MAX_IMAGE_MB == 8


def test_config_model_vision_not_in_allowed_models():
    assert config.MODEL_VISION not in config.ALLOWED_MODELS
