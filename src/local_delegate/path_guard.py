"""The server's door to the protected-path rules (`resources/hooks/path_rules.py`).

The rules live next to the hooks because the read hook needs the same answer and runs with a bare
`python` that cannot import this package. Here they get the values `config` already parsed:
`LOCAL_DELEGATE_DENY_PATHS`, `LOCAL_DELEGATE_ALLOWED_DIRS`, the data folder and `LLAMASWAP_CONFIG`.
"""

from __future__ import annotations

import os

from . import config
from .resources.hooks import path_rules

READ = path_rules.READ
WRITE = path_rules.WRITE
KIND_CREDENTIAL = path_rules.KIND_CREDENTIAL
KIND_AUTOSTART = path_rules.KIND_AUTOSTART
KIND_EXECUTABLE_CONFIG = path_rules.KIND_EXECUTABLE_CONFIG
KIND_NETWORK = path_rules.KIND_NETWORK
KIND_USER = path_rules.KIND_USER
Denial = path_rules.Denial


def check(path: str | os.PathLike[str], mode: str) -> Denial | None:
    """The reason `path` cannot be used for `mode` (`READ` or `WRITE`), or `None` if it can."""
    return path_rules.check(
        path,
        mode,
        deny_paths=config.DENY_PATHS,
        allowed_dirs=config.ALLOWED_DIRS,
        log_dir=config.LOG_DIR,
        llamaswap_config=config.llamaswap_config_path(),
    )
