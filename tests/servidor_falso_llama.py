"""Servidor OpenAI mínimo para probar llama-swap sin cargar ningún modelo.

llama-swap lo lanza como el `cmd` de un modelo, con `--port ${PORT}`. Responde a `/health`,
`/v1/models` y `/v1/chat/completions`; esta última tarda lo que se le pida y **apunta la hora de
llegada** de cada petición, que es lo que miden los controles de la carrera del TTL.

El retraso sale, por orden, del campo `retraso_s` del cuerpo de la petición y de `--retraso`. El campo
`log_kb` hace que el servidor escriba esa cantidad de KB en su salida estándar.

Cada petición deja **dos** líneas JSON en el fichero `--registro`: una `llegada`, escrita nada más
recibirla (antes de esperar), y una `fin`, escrita justo antes de responder. Ambas llevan `ts`
(`time.time()`, la hora del sistema con la que llama-swap apunta `lastUse` y la actividad), `modelo`
(lo que dice el cuerpo: el id real si llama-swap tradujo un alias), `ruta` y `pid`, más el campo `marca` del cuerpo (si lo hay) para reconocer cada petición.

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

_CANDADO = threading.Lock()


def _anotar(registro: Path | None, linea: dict[str, object]) -> None:
    if registro is None:
        return
    with _CANDADO, registro.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linea) + "\n")


def crear_servidor(
    puerto: int, *, retraso: float = 0.0, registro: Path | None = None
) -> ThreadingHTTPServer:
    """Devuelve el servidor ya enlazado a `127.0.0.1:puerto`, sin arrancar."""

    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            return

        def _responder(self, estado: int, cuerpo: dict[str, object] | str) -> None:
            if isinstance(cuerpo, str):
                datos, tipo = cuerpo.encode("utf-8"), "text/plain"
            else:
                datos, tipo = json.dumps(cuerpo).encode("utf-8"), "application/json"
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self) -> None:
            if self.path.startswith("/health"):
                self._responder(200, "OK")
            elif self.path.startswith("/v1/models"):
                self._responder(200, {"object": "list", "data": [{"id": "falso"}]})
            else:
                self._responder(404, {"error": "no existe"})

        def do_POST(self) -> None:
            llegada = time.time()
            largo = int(self.headers.get("Content-Length") or 0)
            crudo = self.rfile.read(largo) if largo else b""
            try:
                cuerpo = json.loads(crudo or b"{}")
            except ValueError:
                cuerpo = {}
            if not isinstance(cuerpo, dict):
                cuerpo = {}
            espera = float(cuerpo.get("retraso_s", retraso))
            kb_de_log = int(cuerpo.get("log_kb", 0))
            datos = {
                "modelo": cuerpo.get("model"),
                "marca": cuerpo.get("marca"),
                "ruta": self.path,
                "pid": os.getpid(),
            }
            _anotar(registro, {"evento": "llegada", "ts": llegada, **datos})
            if kb_de_log > 0:
                # Lo que escribe un servidor real en su salida estándar: llama-swap lo guarda en el
                # historial de logs que manda al abrir `/api/events`.
                print(("x" * 99 + "\n") * (kb_de_log * 10), end="", flush=True)
            if espera > 0:
                time.sleep(espera)
            _anotar(registro, {"evento": "fin", "ts": time.time(), **datos})
            self._responder(
                200,
                {
                    "id": "chatcmpl-falso",
                    "object": "chat.completion",
                    "model": cuerpo.get("model", "falso"),
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

    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    servidor.daemon_threads = True
    return servidor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--retraso", type=float, default=0.0)
    parser.add_argument("--registro", type=Path, default=None)
    parser.add_argument("--pid-file", type=Path, default=None)
    args = parser.parse_args()
    if args.pid_file is not None:
        with args.pid_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"pid": os.getpid(), "ppid": os.getppid()}) + "\n")
    servidor = crear_servidor(args.port, retraso=args.retraso, registro=args.registro)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
