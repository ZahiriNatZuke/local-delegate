#!/usr/bin/env python3
"""Backend OpenAI-compatible falso y deliberadamente lento, para desarrollo.

Sirve para lo que un backend real hace mal como banco de pruebas: aquí las respuestas son
deterministas y la latencia se controla, así que se puede ver el panel «En curso» de verdad
—una delegación tarda lo que tú digas— y ejercitar el chunking sin ocupar la GPU ni ensuciar
el log real con salidas de un modelo.

Implementa lo justo que consume `local-delegate`:

- ``GET  /v1/models``            → un modelo `loaded`, que es lo que mira el dashboard.
- ``POST /v1/chat/completions``  → devuelve el contenido recibido con un prefijo.

Uso típico (tres terminales, o con `&`):

    python scripts/dev/fake_backend.py --port 9595 --delay 1.5

    LOCAL_DELEGATE_LOG_DIR=/tmp/ld-logs LOCAL_DELEGATE_WEB_PORT=9494 \\
      uv run python -m local_delegate.web.metrics

    LOCAL_DELEGATE_LOG_DIR=/tmp/ld-logs \\
      LOCAL_DELEGATE_BASE_URL=http://127.0.0.1:9595/v1 \\
      uv run python -c "from local_delegate import server; \\
                        print(server.local_translate('inglés', path='documento-grande.md'))"

Y mientras corre, en otra terminal:

    curl -s http://127.0.0.1:9494/api/inflight | python -m json.tool

Con ``--truncate-first`` la primera respuesta vuelve con ``finish_reason='length'``: es la
forma de ejercitar el reintento del chunking (un trozo que vuelve cortado se vuelve a partir).
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeBackend(BaseHTTPRequestHandler):
    delay: float = 1.5
    model: str = "llama31-8b"
    truncate_first: bool = False
    _served = 0

    def log_message(self, *_args: object) -> None:
        """Silencio: el ruido interesante es el del dashboard, no el de este servidor."""

    def do_GET(self) -> None:
        # El dashboard lee el estado del catálogo de aquí; `status` es un objeto anidado.
        self._send({"data": [{"id": self.model, "status": {"value": "loaded"}}]})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        content = self._user_content(body)

        time.sleep(self.delay)  # simula una GPU trabajando

        FakeBackend._served += 1
        truncated = self.truncate_first and FakeBackend._served == 1
        self._send(
            {
                "choices": [
                    {
                        "message": {"content": f"[FAKE] {content}"},
                        "finish_reason": "length" if truncated else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": max(1, len(content) // 4),
                    "completion_tokens": max(1, len(content) // 4),
                },
            }
        )

    @staticmethod
    def _user_content(body: dict) -> str:
        """Devuelve el texto del usuario, sin el prompt de sistema que arma el server."""
        for message in reversed(body.get("messages", [])):
            if message.get("role") == "user":
                # El server manda "<instrucción>:\n\n<contenido>"; interesa el contenido.
                return str(message.get("content", "")).split(":\n\n", 1)[-1]
        return ""

    def _send(self, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9595)
    parser.add_argument("--delay", type=float, default=1.5, help="segundos por respuesta")
    parser.add_argument("--model", default="llama31-8b", help="id que se anuncia en /v1/models")
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="la primera respuesta vuelve con finish_reason=length (prueba el reintento)",
    )
    args = parser.parse_args()

    FakeBackend.delay = args.delay
    FakeBackend.model = args.model
    FakeBackend.truncate_first = args.truncate_first

    server = HTTPServer((args.host, args.port), FakeBackend)
    print(f"backend falso en http://{args.host}:{args.port}/v1 (delay {args.delay}s)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nadiós")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
