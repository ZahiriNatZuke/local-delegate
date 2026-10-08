"""Servidor OpenAI mínimo para probar llama-swap sin cargar ningún modelo.

llama-swap lo lanza como el `cmd` de un modelo, con `--port ${PORT}`. Responde a `/health`,
`/v1/models` y `/v1/chat/completions`; esta última tarda lo que se le pida y **apunta la hora de
llegada** de cada petición, que es lo que miden los controles de la carrera del TTL.

El retraso sale, por orden, del campo `delay_s` del cuerpo de la petición y de `--delay`. El campo
`log_kb` hace que el servidor escriba esa cantidad de KB en su salida estándar.

Cada petición deja **dos** líneas JSON en el fichero `--record`: una `arrival`, escrita nada más
recibirla (antes de esperar), y una `end`, escrita justo antes de responder. Ambas llevan `ts`
(`time.time()`, la hora del sistema con la que llama-swap apunta `lastUse` y la actividad), `model`
(lo que dice el cuerpo: el id real si llama-swap tradujo un alias), `path` y `pid`, más el campo `mark` del cuerpo (si lo hay) para reconocer cada petición.

`--pid-file` añade una línea con el PID de este proceso y el de su padre (en Windows, el lanzador del
entorno virtual), para que la fixture sepa qué tiene que haber muerto al terminar; si llama-swap
descarga y vuelve a cargar el modelo, el fichero acumula una línea por arranque.

Se ejecuta con el mismo intérprete que la suite (`sys.executable`); no usa más que la biblioteca
estándar.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_LOCK = threading.Lock()


def _append_record(record: Path | None, line: dict[str, object]) -> None:
    if record is None:
        return
    with _LOCK, record.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def create_server(
    port: int, *, delay: float = 0.0, record: Path | None = None
) -> ThreadingHTTPServer:
    """Devuelve el servidor ya enlazado a `127.0.0.1:puerto`, sin arrancar."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            return

        def _respond(self, state: int, body: dict[str, object] | str) -> None:
            if isinstance(body, str):
                data, kind = body.encode("utf-8"), "text/plain"
            else:
                data, kind = json.dumps(body).encode("utf-8"), "application/json"
            self.send_response(state)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path.startswith("/health"):
                self._respond(200, "OK")
            elif self.path.startswith("/v1/models"):
                self._respond(200, {"object": "list", "data": [{"id": "falso"}]})
            else:
                self._respond(404, {"error": "no existe"})

        def do_POST(self) -> None:
            arrival = time.time()
            long = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(long) if long else b""
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            wait = float(body.get("delay_s", delay))
            log_kb = int(body.get("log_kb", 0))
            data = {
                "model": body.get("model"),
                "mark": body.get("mark"),
                "path": self.path,
                "pid": os.getpid(),
            }
            _append_record(record, {"event": "arrival", "ts": arrival, **data})
            if log_kb > 0:
                # Lo que escribe un servidor real en su salida estándar: llama-swap lo guarda en el
                # historial de logs que manda al abrir `/api/events`.
                print(("x" * 99 + "\n") * (log_kb * 10), end="", flush=True)
            if wait > 0:
                time.sleep(wait)
            _append_record(record, {"event": "end", "ts": time.time(), **data})
            self._respond(
                200,
                {
                    "id": "chatcmpl-falso",
                    "object": "chat.completion",
                    "model": body.get("model", "falso"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--record", type=Path, default=None)
    parser.add_argument("--pid-file", type=Path, default=None)
    args = parser.parse_args()
    if args.pid_file is not None:
        with args.pid_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"pid": os.getpid(), "ppid": os.getppid()}) + "\n")
    server = create_server(args.port, delay=args.delay, record=args.record)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
