"""`llamaswap_config.model_context_size` (SDD `backend-extra-params`, T7, REQ-023).

The context of the target model, read from the llama-swap config with the existing readers
(`load_config` and `_parse_cmd_flags`), with an estimate of 8192 when it cannot be read.
"""

from __future__ import annotations

import os

import pytest

from local_delegate import llamaswap_config as lc

pytest.importorskip("yaml")

VARIABLE = "LLAMASWAP_CONFIG"


@pytest.fixture(autouse=True)
def _fresh_cache():
    lc._forget_context_sizes()
    yield
    lc._forget_context_sizes()


def _config(tmp_path, monkeypatch, cmd: str, name: str = "gemma3-4b"):
    path = tmp_path / "config.yaml"
    path.write_text(f"models:\n  {name}:\n    cmd: {cmd}\n", encoding="utf-8")
    monkeypatch.setenv(VARIABLE, str(path))
    return path


def test_estimate_constant():
    assert lc.ESTIMATED_CONTEXT == 8192


def test_ctx_size_long_flag(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "llama-server --port ${PORT} -m m.gguf --ctx-size 16384")
    assert lc.model_context_size("gemma3-4b") == (16384, False)


def test_ctx_size_short_flag(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "llama-server -m m.gguf -c 4096 --jinja")
    assert lc.model_context_size("gemma3-4b") == (4096, False)


def test_ctx_size_missing_flag_is_estimate(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "llama-server -m m.gguf")
    assert lc.model_context_size("gemma3-4b") == (8192, True)


@pytest.mark.parametrize("value", ["${CTX}", "big", "-5", "0"])
def test_ctx_size_not_a_number_is_estimate(tmp_path, monkeypatch, value):
    _config(tmp_path, monkeypatch, f"llama-server -m m.gguf --ctx-size {value}")
    assert lc.model_context_size("gemma3-4b") == (8192, True)


def test_ctx_size_unknown_model_is_estimate(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "llama-server -c 4096")
    assert lc.model_context_size("qwen-coder") == (8192, True)


@pytest.mark.parametrize("where", ["unset", "absent_file"])
def test_ctx_size_missing_config_is_estimate(tmp_path, monkeypatch, where):
    if where == "unset":
        monkeypatch.delenv(VARIABLE, raising=False)
    else:
        monkeypatch.setenv(VARIABLE, str(tmp_path / "nope.yaml"))
    assert lc.model_context_size("gemma3-4b") == (8192, True)


@pytest.mark.parametrize(
    "text", ["models: [1, 2]\n", "models:\n  gemma3-4b: 7\n", "{{{ not yaml\n", "- a\n"]
)
def test_ctx_size_odd_config_is_estimate_and_never_raises(tmp_path, monkeypatch, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv(VARIABLE, str(path))
    assert lc.model_context_size("gemma3-4b") == (8192, True)


def test_ctx_size_without_yaml_is_estimate(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "llama-server -c 4096")
    assert lc.model_context_size("gemma3-4b") == (4096, False)  # control: it can read it

    def no_yaml() -> None:
        raise RuntimeError(lc.extra_missing())

    monkeypatch.setattr(lc, "_require_yaml", no_yaml)
    assert lc.model_context_size("gemma3-4b") == (8192, True)


def test_ctx_size_cache_sees_rewrite(tmp_path, monkeypatch):
    path = _config(tmp_path, monkeypatch, "llama-server -c 4096")
    base = 1_700_000_000_000_000_000
    os.utime(path, ns=(base, base))
    assert lc.model_context_size("gemma3-4b") == (4096, False)

    # Same size, same file (same inode), mtime 100 ns later: only `st_mtime_ns` sees it.
    path.write_text(path.read_text(encoding="utf-8").replace("4096", "8000"), encoding="utf-8")
    os.utime(path, ns=(base + 100, base + 100))
    assert lc.model_context_size("gemma3-4b") == (8000, False)


def test_ctx_size_cache_is_used(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, "llama-server -c 4096")
    calls = []
    real = lc.load_config
    monkeypatch.setattr(lc, "load_config", lambda p: calls.append(p) or real(p))
    assert lc.model_context_size("gemma3-4b") == (4096, False)
    assert lc.model_context_size("gemma3-4b") == (4096, False)
    assert lc.model_context_size("other") == (8192, True)
    assert len(calls) == 1
