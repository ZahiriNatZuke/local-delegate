"""La fixture `real_profiles_untouchable` de conftest está activa (SDD cli-completion, L3a).

Como `tests/test_environment_isolation.py` con el entorno: si la fixture dejara de ser autouse, o
dejara de sustituir alguna de las dos salidas al sistema, un test cualquiera podría averiguar el
`$PROFILE` real del usuario y acabar escribiendo en él. Estos tests lo dirían.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import PROFILE_GUARD

from local_delegate import shell_profiles

#: Los originales, guardados al importar (antes de que la fixture los sustituya).
ORIGINAL_RUN = shell_profiles._default_run
ORIGINAL_DOCUMENTS = shell_profiles._documents_folder

PWSH = shell_profiles.ShellTarget("powershell", "pwsh", "pwsh")


def test_the_fixture_ran_without_being_requested(request):
    """Control positivo de los demás: si la fixture no fuera autouse, no habría marca."""
    assert request.node.stash.get(PROFILE_GUARD, None) is True
    assert shell_profiles._default_run is not ORIGINAL_RUN
    assert shell_profiles._documents_folder is not ORIGINAL_DOCUMENTS


def test_a_real_query_fails_the_test_instead_of_being_swallowed():
    """La consulta captura `OSError` y `SubprocessError`; el doble lanza algo que no hereda de
    `Exception`, así que la llamada real no se convierte en un «falló, uso el respaldo» mudo."""
    with pytest.raises(pytest.fail.Exception):
        shell_profiles.query_powershell("pwsh")


def test_real_home_lookups_fail_by_every_path(tmp_path):
    with pytest.raises(pytest.fail.Exception):
        shell_profiles.profile_path(PWSH, tmp_path, simulated=False)
    with pytest.raises(pytest.fail.Exception):
        shell_profiles.profile_path(
            PWSH, tmp_path, simulated=False, query=lambda _e: (None, None), platform="win32"
        )


def test_injected_runner_still_works():
    """La fixture no sustituye `query_powershell`: los tests que inyectan `run=` funcionan."""
    calls = []

    def run(cmd, *, env, timeout):
        calls.append(cmd)
        raise FileNotFoundError(cmd[0])

    assert shell_profiles.query_powershell("pwsh", run=run) == (None, None)
    assert calls


def test_simulated_home_needs_no_real_lookup(tmp_path):
    location = shell_profiles.profile_path(PWSH, tmp_path, simulated=True, platform="win32")
    assert location.path == tmp_path / "Documents" / "PowerShell" / "profile.ps1"
    assert isinstance(location.path, Path)


@pytest.mark.real_profile_query
def test_the_marker_is_the_only_off_switch(request):
    """Con el marcador, la fixture no sustituye nada (y no se llama a nada real aquí)."""
    assert request.node.stash.get(PROFILE_GUARD, None) is False
    assert shell_profiles._default_run is ORIGINAL_RUN
    assert shell_profiles._documents_folder is ORIGINAL_DOCUMENTS
