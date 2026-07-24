#!/usr/bin/env python3
"""Canary end-to-end: MCP local en macOS -> backend OpenAI remoto.

Solo usa la biblioteca estandar. Lanza la revision indicada con ``uvx``, habla MCP
por stdio, prueba un path que existe unicamente en la Mac, concurrencia y reinicio.
El bearer token se hereda desde ``LOCAL_DELEGATE_API_KEY`` y nunca se imprime.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# La version MCP es la fecha de la revision de la especificacion, no la fecha actual.
# Debe mantenerse alineada con LATEST_PROTOCOL_VERSION del SDK `mcp` usado por el paquete.
PROTOCOL_VERSION = "2025-11-25"


class CanaryError(RuntimeError):
    """Fallo verificable del canary."""


@dataclass
class ToolResult:
    name: str
    elapsed_ms: int
    text: str


class McpStdioClient:
    def __init__(self, command: list[str], env: dict[str, str], timeout: float) -> None:
        self.command = command
        self.env = env
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self.pending: dict[int, dict[str, Any]] = {}
        self.next_id = 1

    def __enter__(self) -> McpStdioClient:
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=self.env,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        response = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "local-delegate-macos-canary", "version": "1"},
            },
        )
        if "protocolVersion" not in response:
            raise CanaryError("initialize no devolvio una version de protocolo MCP")
        self.notify("notifications/initialized", {})
        return self

    def __exit__(self, *_args: object) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            for line in self.process.stdout:
                line = line.strip()
                if line:
                    self.messages.put(json.loads(line))
        except BaseException as exc:  # pragma: no cover - depende del subprocess
            self.messages.put(exc)

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        if self.process.poll() is not None:
            raise CanaryError(f"el proceso MCP termino con codigo {self.process.returncode}")
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def send_request(self, method: str, params: dict[str, Any]) -> int:
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return request_id

    def await_response(self, request_id: int) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while request_id not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CanaryError(f"timeout esperando respuesta MCP id={request_id}")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise CanaryError(f"timeout esperando respuesta MCP id={request_id}") from exc
            if isinstance(message, BaseException):
                raise CanaryError(f"salida MCP invalida: {message}") from message
            if "id" in message:
                self.pending[int(message["id"])] = message
        message = self.pending.pop(request_id)
        if "error" in message:
            error = message["error"]
            raise CanaryError(f"error JSON-RPC {error.get('code')}: {error.get('message')}")
        return message.get("result", {})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.await_response(self.send_request(method, params))

    def send_tool(self, name: str, arguments: dict[str, Any]) -> tuple[int, float, str]:
        return (
            self.send_request("tools/call", {"name": name, "arguments": arguments}),
            time.monotonic(),
            name,
        )

    def await_tool(self, sent: tuple[int, float, str]) -> ToolResult:
        request_id, started, name = sent
        result = self.await_response(request_id)
        text = "\n".join(
            item.get("text", "") for item in result.get("content", []) if item.get("type") == "text"
        )
        if result.get("isError") or "[local-delegate error]" in text:
            raise CanaryError(f"{name} fallo: {text[:240]}")
        return ToolResult(
            name=name, elapsed_ms=round((time.monotonic() - started) * 1000), text=text
        )


def _http_models(base_url: str, api_key: str, *, authenticated: bool, timeout: float) -> int:
    headers = {}
    if authenticated and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(f"{base_url.rstrip('/')}/models", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError as exc:
        raise CanaryError(f"no se pudo alcanzar {base_url}: {exc}") from exc


def _package_command(source: str) -> list[str]:
    return ["uvx", "--refresh", "--from", source, "local-delegate-mcp"]


def _tool_cases(mac_path: Path, count: int) -> list[tuple[str, dict[str, Any]]]:
    base: list[tuple[str, dict[str, Any]]] = [
        ("local_summarize", {"path": str(mac_path), "max_words": 60}),
        (
            "local_classify",
            {
                "text": "El build termino correctamente y no hubo errores.",
                "labels": ["ok", "error", "desconocido"],
            },
        ),
        (
            "local_summarize",
            {
                "text": "La prueba conecta una Mac a una GPU remota. " * 20,
                "max_words": 45,
            },
        ),
    ]
    while len(base) < count:
        index = len(base) + 1
        base.append(
            (
                "local_classify",
                {
                    "text": f"Canary remoto numero {index}: operacion completada.",
                    "labels": ["completada", "fallida"],
                },
            )
        )
    return base[:count]


def _run_stage(
    command: list[str], env: dict[str, str], timeout: float, cases: list[tuple[str, dict[str, Any]]]
) -> list[ToolResult]:
    results: list[ToolResult] = []
    with McpStdioClient(command, env, timeout) as client:
        tools = client.request("tools/list", {}).get("tools", [])
        names = {tool.get("name") for tool in tools}
        required = {"local_status", "local_classify", "local_summarize"}
        missing = sorted(required - names)
        if missing:
            raise CanaryError(f"faltan tools MCP: {', '.join(missing)}")

        status = client.await_tool(client.send_tool("local_status", {}))
        if env["LOCAL_DELEGATE_BASE_URL"] not in status.text:
            raise CanaryError("local_status no refleja el backend remoto configurado")

        index = 0
        while index < len(cases):
            pair = cases[index : index + 2]
            sent = [client.send_tool(name, arguments) for name, arguments in pair]
            results.extend(client.await_tool(item) for item in sent)
            index += len(pair)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LOCAL_DELEGATE_BASE_URL", ""),
        help="Endpoint remoto terminado en /v1 (o LOCAL_DELEGATE_BASE_URL).",
    )
    parser.add_argument(
        "--package-source",
        required=True,
        help="Paquete/version o git+https://...git@COMMIT para uvx.",
    )
    parser.add_argument(
        "--calls", type=int, default=20, help="Llamadas de inferencia (default: 20)."
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout por respuesta MCP.")
    parser.add_argument(
        "--expect-auth",
        action="store_true",
        help="Exige 401/403 sin token y 200 con LOCAL_DELEGATE_API_KEY.",
    )
    args = parser.parse_args()
    if not args.base_url or not args.base_url.rstrip("/").endswith("/v1"):
        parser.error("--base-url debe ser una URL explicita terminada en /v1")
    if args.calls < 2:
        parser.error("--calls debe ser al menos 2")
    if not shutil_which("uvx"):
        parser.error("uvx no esta instalado o no aparece en PATH")

    api_key = os.environ.get("LOCAL_DELEGATE_API_KEY", "")
    if args.expect_auth and not api_key:
        parser.error("--expect-auth requiere LOCAL_DELEGATE_API_KEY en el entorno")

    auth_status = _http_models(args.base_url, api_key, authenticated=True, timeout=args.timeout)
    if auth_status != 200:
        raise CanaryError(f"GET /models autenticado devolvio HTTP {auth_status}")
    unauth_status = _http_models(args.base_url, api_key, authenticated=False, timeout=args.timeout)
    if args.expect_auth and unauth_status not in {401, 403}:
        raise CanaryError(
            f"GET /models sin token devolvio HTTP {unauth_status}; se esperaba 401/403"
        )

    command = _package_command(args.package_source)
    with tempfile.TemporaryDirectory(prefix="local-delegate-mac-canary-") as temp_dir:
        root = Path(temp_dir)
        mac_path = root / "solo-en-esta-mac.txt"
        mac_path.write_text(
            "Este archivo temporal existe solamente en la Mac que ejecuta el MCP. " * 80,
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "LOCAL_DELEGATE_BASE_URL": args.base_url,
                "LOCAL_DELEGATE_AUTOSTART": "0",
                "LOCAL_DELEGATE_WEB": "0",
                "LOCAL_DELEGATE_ALLOWED_DIRS": str(root),
                "LOCAL_DELEGATE_LOG": str(root / "usage.jsonl"),
                "LOCAL_DELEGATE_TIMEOUT": str(args.timeout),
            }
        )

        cases = _tool_cases(mac_path, args.calls)
        split = max(1, len(cases) // 2)
        first = _run_stage(command, env, args.timeout, cases[:split])
        # Un proceso nuevo prueba que Claude puede reconectar el MCP sin cambiar config.
        second = _run_stage(command, env, args.timeout, cases[split:])
        results = first + second

    summary = {
        "status": "PASS",
        "package_source": args.package_source,
        "base_url": args.base_url,
        "authenticated_endpoint": bool(api_key),
        "unauthenticated_http_status": unauth_status,
        "inference_calls": len(results),
        "process_starts": 2,
        "concurrency": 2,
        "mac_only_path": "PASS",
        "p95_ms": sorted(item.elapsed_ms for item in results)[int((len(results) - 1) * 0.95)],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def shutil_which(command: str) -> str | None:
    """Equivalente minimo a shutil.which, import local mantenido simple para el canary."""
    from shutil import which

    return which(command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CanaryError as exc:
        print(f"CANARY FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
