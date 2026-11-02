"""The real dashboard served in a thread, on a port the system assigns.

The browser tests (`test_dashboard_ui.py`, `test_panel_xss_ui.py`) used to listen on fixed ports
(9495 shared by a dozen tests, 9486–9499, 9511) and relied on `xdist_group` + `--dist loadgroup`
to run them all in one worker. That grouping is not a guarantee: pytest 9.2 stopped honouring the
node-id suffix that pytest-xdist 3.8.0 uses for `loadgroup` (pytest-dev/pytest-xdist#1386), the
module was spread over four workers and 18 tests failed with `address already in use`.

Here uvicorn binds port 0 itself and the port is read back from the listening socket, so there is
no window between choosing a port and taking it, and two servers can never ask for the same one.
"""

from __future__ import annotations

import threading
import time
from typing import Self

import uvicorn

from local_delegate.web import metrics


class PanelServer:
    """`with PanelServer() as server:` serves `metrics.app`; `server.url` is its root URL."""

    def __init__(self, what: str = "el dashboard") -> None:
        self._what = what
        self._server = uvicorn.Server(
            uvicorn.Config(metrics.app, host="127.0.0.1", port=0, log_level="error")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.port = 0
        self.url = ""

    def __enter__(self) -> Self:
        self._thread.start()
        for _ in range(200):
            if self._server.started:
                self.port = self._server.servers[0].sockets[0].getsockname()[1]
                self.url = f"http://127.0.0.1:{self.port}/"
                return self
            if not self._thread.is_alive():
                break
            time.sleep(0.05)
        self._server.should_exit = True
        self._thread.join(timeout=10)
        raise RuntimeError(f"{self._what} no llegó a levantar")

    def __exit__(self, *_exc) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
