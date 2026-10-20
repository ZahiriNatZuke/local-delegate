"""Capture the request bodies that `main` sends to the backend, one fixture per path (REQ-022).

The SDD `backend-extra-params` adds per-role parameters to the body of every chat request. Its
compatibility rule is that, with no parameters configured, every body stays byte-for-byte the
one of today, key order included. This script freezes "today": it replaces `server._post_chat`
with a fake backend that records `(model, payload)` and answers with a valid `ChatResult`, runs
each path once and writes `tests/fixtures/request_bodies/<path>.json` with

    {"commit": "<sha>", "bodies": [...], "event_keys": [...]}

Each body is stored as a list of `[key, value]` pairs (nested objects too), so that no JSON tool
can reorder it. `event_keys` is the sorted set of keys of the usage-log event of the operation.

`tests/test_request_body_compat.py` imports `capture()` and compares against these fixtures; it
prepares the environment with the suite's own fixtures (`reload_config` and the isolation of
`tests/conftest.py`). Run standalone, `prepare_environment()` does the same by hand.

Usage (from the repository root, on the commit to freeze):

    uv run python scripts/capture_request_bodies.py [--out DIR]
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from local_delegate import config, failures, i18n, server

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "request_bodies"

MECHANICAL = "gemma3-4b"
LONG = "gemma4-26b-a4b"
CODE = "qwen36-35b-a3b"
VISION = "gemma4-12b"

#: The fixed environment of every capture: language, models per role, fallback chains and a
#: backend that is not on loopback (no turn, no topology, no affinity: nothing that depends on the
#: machine). `LOCAL_DELEGATE_MAX_CHARS_LONG` is small so that a 7 000-char text goes map/reduce.
ENVIRONMENT: dict[str, str] = {
    "LOCAL_DELEGATE_LANG": "es",
    "LOCAL_DELEGATE_BASE_URL": "http://test-backend/v1",
    "LOCAL_DELEGATE_MODEL_MECHANICAL": MECHANICAL,
    "LOCAL_DELEGATE_MODEL_LONG": LONG,
    "LOCAL_DELEGATE_MODEL_CODE": CODE,
    "LOCAL_DELEGATE_MODEL_VISION": VISION,
    "LOCAL_DELEGATE_FALLBACK_MECHANICAL": "long",
    "LOCAL_DELEGATE_FALLBACK_LONG": "code",
    "LOCAL_DELEGATE_FALLBACK_CODE": "long",
    "LOCAL_DELEGATE_MAX_CHARS_LONG": "3000",
}

#: The fixtures, one per path of REQ-022 (the reduction of map/reduce counted apart).
PATHS: tuple[str, ...] = (
    "simple",
    "extract_schema",
    "extract_schema_retry",
    "map_chunk",
    "reduce",
    "vision",
    "fallback",
    "delegate_explicit",
)

_EXTRACT_ANSWER = '{"name": "Ana", "city": "Holguín"}'


def _ok(text: str = "hecho") -> server.ChatResult:
    return server.ChatResult(text=text, ok=True, finish_reason="stop")


def _minimal_png(dest: Path) -> Path:
    """A valid 1x1 PNG, written by hand so as not to depend on Pillow."""

    def block(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + block(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + block(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + block(b"IEND", b"")
    )
    dest.write_bytes(png)
    return dest


def _long_text() -> str:
    """7 000 chars in paragraphs: above `LONG_INPUT_CHARS` (role `long`) and above the 3 000 of
    `ENVIRONMENT`, so the summary goes map/reduce."""
    return "\n\n".join(f"Párrafo {i}: " + "palabra " * 60 for i in range(14))


# --- The fake backends -------------------------------------------------------------------------


def _always_ok(text: str) -> Callable[[str, dict], server.ChatResult]:
    return lambda _model, _payload: _ok(text)


def _schema_rejected(_model: str, payload: dict) -> server.ChatResult:
    """The backend answers 400 to `response_format`, as one without JSON-schema support does."""
    if "response_format" in payload:
        return server.ChatResult(
            text="[local-delegate error] HTTP 400",
            ok=False,
            error="http_400",
            error_class=failures.FailureClass.REQUEST,
        )
    return _ok(_EXTRACT_ANSWER)


def _mechanical_fails(model: str, _payload: dict) -> server.ChatResult:
    """The mechanical model fails with a skippable error; its fallback (`long`) answers."""
    if model == MECHANICAL:
        return server.ChatResult(
            text="[local-delegate error] HTTP 500",
            ok=False,
            error="http_500",
            error_class=failures.FailureClass.MODEL,
        )
    return _ok("resumen del respaldo")


# --- The paths ---------------------------------------------------------------------------------

#: One run per operation: (fake backend, action, which bodies belong to the fixture). `map_chunk`
#: and `reduce` come from the SAME operation: the chunks are every call but the last one.
_Run = tuple[
    Callable[[str, dict], server.ChatResult],
    Callable[[Path], Any],
    Callable[[list], list],
]


def _all(bodies: list) -> list:
    return bodies


def _runs() -> dict[str, _Run]:
    def summarize_long(_work: Path) -> Any:
        return server.local_summarize(text=_long_text())

    return {
        "simple": (
            _always_ok("hecho"),
            lambda _work: server.local_summarize(text="Un texto corto para resumir."),
            _all,
        ),
        "extract_schema": (
            _always_ok(_EXTRACT_ANSWER),
            lambda _work: server.local_extract(
                fields=["name", "city"], text="Ana vive en Holguín."
            ),
            _all,
        ),
        "extract_schema_retry": (
            _schema_rejected,
            lambda _work: server.local_extract(
                fields=["name", "city"], text="Ana vive en Holguín."
            ),
            _all,
        ),
        "map_chunk": (_always_ok("resumen parcial"), summarize_long, lambda b: b[:-1]),
        "reduce": (_always_ok("resumen parcial"), summarize_long, lambda b: b[-1:]),
        "vision": (
            _always_ok("un punto blanco"),
            lambda work: server.local_describe_image(path=str(_minimal_png(work / "dot.png"))),
            _all,
        ),
        "fallback": (
            _mechanical_fails,
            lambda _work: server.local_summarize(text="Un texto corto para resumir."),
            _all,
        ),
        "delegate_explicit": (
            _always_ok("HOLA"),
            lambda _work: server.local_delegate(
                task="Pasa el texto a mayúsculas.",
                input="hola",
                output_format="El texto en mayúsculas, sin nada más.",
                model=CODE,
            ),
            _all,
        ),
    }


def as_pairs(value: Any) -> Any:
    """A JSON value with every object turned into a list of `[key, value]` pairs, in order.

    `object_pairs_hook=list` gives `(key, value)` tuples; the second round trip turns them into
    lists, which is what the fixture holds once read back.
    """
    pairs = json.loads(json.dumps(value, ensure_ascii=False), object_pairs_hook=list)
    return json.loads(json.dumps(pairs, ensure_ascii=False))


def _reset_server_state() -> None:
    """What `tests/conftest.py` resets between tests, for the standalone run."""
    server._LAST_GOOD_LISTS.clear()
    server._reset_turn()
    from local_delegate import topology

    topology._forget()


def _last_event(log_dir: Path) -> dict:
    lines: list[str] = []
    for file in sorted(log_dir.glob("usage*.jsonl")):
        lines += [line for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"no usage event was written in {log_dir}")
    return json.loads(lines[-1])


def capture(name: str, work: Path) -> dict:
    """Run path `name` against the fake backend; return its bodies (as pairs) and event keys.

    The environment must already be the one of `ENVIRONMENT`, with `config.LOG_DIR` empty.
    """
    backend, action, select = _runs()[name]
    captured: list[Any] = []

    def fake_post_chat(model: str, payload: dict) -> server.ChatResult:
        # Serialized at once: `_call_model` mutates the dict afterwards (it pops
        # `response_format` before the retry without schema).
        captured.append(as_pairs(payload))
        return backend(model, payload)

    _reset_server_state()
    original = server._post_chat
    server._post_chat = fake_post_chat
    try:
        action(work)
    finally:
        server._post_chat = original
    return {
        "bodies": select(captured),
        "event_keys": sorted(_last_event(Path(config.LOG_DIR))),
    }


@contextmanager
def prepare_environment(log_dir: Path) -> Iterator[None]:
    """Standalone twin of `env_without_package_variables` + `reload_config`: no package variable
    but those of `ENVIRONMENT`, `config` reloaded and the logs in `log_dir`."""
    saved = dict(os.environ)
    try:
        for variable in config.ENVIRONMENT_VARIABLES:
            os.environ.pop(variable, None)
        os.environ.update(ENVIRONMENT)
        os.environ["LOCAL_DELEGATE_LOG_DIR"] = str(log_dir)
        importlib.reload(config)
        config.LOG_DIR = log_dir
        config.USAGE_LOG = log_dir / "usage.jsonl"
        i18n.reset()
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)
        i18n.reset()


def _head_commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="fixtures folder")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    commit = _head_commit()
    for name in PATHS:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            with prepare_environment(work):
                result = capture(name, work)
        fixture = {"commit": commit, **result}
        target = args.out / f"{name}.json"
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(fixture, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(
            f"{target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}: "
            f"{len(result['bodies'])} body(ies)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
