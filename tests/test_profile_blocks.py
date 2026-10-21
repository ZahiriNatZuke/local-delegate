"""Ayudantes de perfil por bytes de `install` (SDD cli-completion, L3a; REQ-028, REQ-045, REQ-046).

Cada caso es una ida y vuelta: se siembra un perfil, se pone el bloque, se quita, y los bytes
tienen que ser **los sembrados**. Los controles positivos van anotados en cada test: qué mutación
del código lo pone en rojo (comprobado a mano una vez, anotado en el PR de L3a).
"""

from __future__ import annotations

import codecs
import os
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from local_delegate import install, shell_profiles
from local_delegate.install import (
    ProfileEdit,
    profile_backup_path,
    remove_profile_block,
    upsert_profile_block,
    write_profile_edit,
)

BOM8 = codecs.BOM_UTF8
#: Un bloque de bash con la ruta en UTF-8 (tilde, espacio y comilla) y uno de PowerShell, ASCII.
BASH_BLOCK = shell_profiles.load_block(
    "bash", PurePosixPath("/home/josé/it's here/completion/local-delegate.bash")
)
PS_BLOCK = shell_profiles.load_block(
    "powershell", PureWindowsPath("C:/Users/José/AppData/Local/local-delegate/completion/x.ps1")
)
OTHER_PS_BLOCK = shell_profiles.load_block(
    "powershell", PureWindowsPath("C:/Users/Otro/AppData/Local/local-delegate/completion/x.ps1")
)

#: Perfiles semilla: cada codificación y fin de línea de REQ-028, con y sin salto final.
SEEDS = {
    "utf8-lf-final": b"export A=1\nalias ll='ls -l'\n",
    "utf8-lf-no-final": b"export A=1\nalias ll='ls -l'",
    "utf8-tilde-lf": "# configuración\nexport NOMBRE='José'\n".encode(),
    "utf8-bom-crlf-final": BOM8 + "Write-Host 'canción'\r\nSet-Alias g git\r\n".encode(),
    "utf8-bom-crlf-no-final": BOM8 + "Write-Host 'canción'\r\nSet-Alias g git".encode(),
    "utf16le-bom-crlf": codecs.BOM_UTF16_LE + "Set-Alias g git\r\n# ó\r\n".encode("utf-16-le"),
    "utf16be-bom-lf": codecs.BOM_UTF16_BE + "Set-Alias g git\n# ó".encode("utf-16-be"),
    "ansi-cp1252-crlf": "# configuración de José\r\nSet-Alias ñ ls\r\n".encode("cp1252"),
    "ansi-cp1252-no-final": "# configuración de José\r\nSet-Alias ñ ls".encode("cp1252"),
    "crlf-no-final": b"a\r\nb",
    "mixed-mostly-crlf": b"a\r\nb\r\nc\n",
    "empty": b"",
    "bom-only": BOM8,
}


def _apply(path: Path, edit: ProfileEdit, *, backup: bool = True) -> None:
    assert edit.reason is None, edit.skip_message()
    assert write_profile_edit(edit, backup=backup) is None


@pytest.mark.parametrize("block", [BASH_BLOCK, PS_BLOCK], ids=["bash-block", "ps-block"])
@pytest.mark.parametrize("seed", list(SEEDS), ids=list(SEEDS))
def test_round_trip_returns_the_seed_byte_for_byte(tmp_path, seed, block):
    """REQ-028: poner y quitar el bloque devuelve el perfil byte a byte.

    Control positivo: con el respaldo `latin-1` de `_decode_profile` cambiado por
    `decode("utf-8", "replace")`, los casos ANSI salen distintos; quitando el recorte del salto
    previo en `remove_profile_block`, salen distintos todos los que tienen texto.
    """
    profile = tmp_path / "profile"
    profile.write_bytes(SEEDS[seed])

    installed = upsert_profile_block(profile, block)
    assert installed.changed and installed.existed
    _apply(profile, installed)
    assert profile.read_bytes() != SEEDS[seed]

    removed = remove_profile_block(profile)
    assert removed.changed
    _apply(profile, removed)
    assert profile.read_bytes() == SEEDS[seed]


@pytest.mark.parametrize("seed", list(SEEDS), ids=list(SEEDS))
def test_install_keeps_encoding_bom_and_dominant_newline(tmp_path, seed):
    """REQ-028: el bloque entra en la codificación, con el BOM y con el fin de línea dominante.

    Control positivo: con `_dominant_newline` devolviendo siempre `"\\n"`, fallan los casos CRLF.
    """
    raw = SEEDS[seed]
    profile = tmp_path / "profile"
    profile.write_bytes(raw)
    edit = upsert_profile_block(profile, PS_BLOCK)
    data = edit.data
    assert data is not None

    for bom, codec in ((codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if raw.startswith(bom):
            assert data.startswith(bom)
            text = data[len(bom) :].decode(codec)
            break
    else:
        assert data.startswith(BOM8) == raw.startswith(BOM8)
        text = data.decode("latin-1")
    original_crlf = raw.replace(b"\x00", b"").count(b"\r\n")
    original_lf = raw.replace(b"\x00", b"").count(b"\n") - original_crlf
    newline = "\r\n" if original_crlf > original_lf else "\n"
    assert PS_BLOCK.replace("\n", newline) + newline in text
    # Lo que había sigue delante, intacto.
    assert data.startswith(raw)


@pytest.mark.parametrize(
    ("seed", "expected"),
    [
        (b"a\n", b"a\n\n{block}\n"),
        (b"a", b"a\n{block}\n"),
        (b"", b"{block}\n"),
    ],
    ids=["ends-with-newline", "no-final-newline", "empty"],
)
def test_insertion_shape(tmp_path, seed, expected):
    """La forma exacta de la inserción del plan: línea en blanco de separación solo si el texto
    acababa en salto. Control positivo: con `text + newline + newline + inserted`, falla el caso
    sin salto final."""
    profile = tmp_path / "profile"
    profile.write_bytes(seed)
    edit = upsert_profile_block(profile, BASH_BLOCK)
    assert edit.data == expected.replace(b"{block}", BASH_BLOCK.encode())


def test_missing_profile_gets_only_the_block_and_removal_empties_it(tmp_path):
    """Inexistente → `bloque + NL` en UTF-8; quitarlo deja el fichero vacío (borrarlo, si `install`
    lo creó, es cosa del manifiesto de L3b)."""
    profile = tmp_path / "dir" / ".bashrc"
    edit = upsert_profile_block(profile, BASH_BLOCK)
    assert not edit.existed
    assert edit.data == (BASH_BLOCK + "\n").encode("utf-8")
    _apply(profile, edit)
    assert profile.read_bytes() == edit.data
    assert not profile_backup_path(profile).exists()  # no había nada que copiar

    _apply(profile, remove_profile_block(profile))
    assert profile.read_bytes() == b""


def test_removal_from_a_missing_profile_is_a_no_op(tmp_path):
    edit = remove_profile_block(tmp_path / "nope")
    assert not edit.changed and edit.reason is None and not edit.existed
    assert write_profile_edit(edit) is None
    assert not (tmp_path / "nope").exists()


def test_profile_with_only_the_block_is_unchanged_and_empties_on_removal(tmp_path):
    profile = tmp_path / ".zshrc"
    profile.write_bytes((BASH_BLOCK + "\n").encode())
    assert not upsert_profile_block(profile, BASH_BLOCK).changed
    _apply(profile, remove_profile_block(profile))
    assert profile.read_bytes() == b""


def test_existing_block_is_replaced_in_place_without_moving_anything(tmp_path):
    """Con el bloque ya puesto, solo cambia lo de dentro: lo de antes y lo de después, intacto.

    Control positivo: con la inserción al final aunque haya bloque, el texto de después se mueve.
    """
    before, after = b"# antes\r\n\r\n", b"\r\n# despues, del usuario\r\n"
    old = OTHER_PS_BLOCK.replace("\n", "\r\n").encode()
    profile = tmp_path / "profile.ps1"
    profile.write_bytes(before + old + after)

    edit = upsert_profile_block(profile, PS_BLOCK)
    assert edit.data == before + PS_BLOCK.replace("\n", "\r\n").encode() + after


def test_install_is_idempotent(tmp_path):
    """REQ-029 en el ayudante: la segunda pasada no cambia nada, ni crea otra copia.

    Control positivo: si la comparación `updated == text` se quitara, la segunda pasada daría
    `changed` aunque los bytes fueran los mismos.
    """
    profile = tmp_path / ".bashrc"
    profile.write_bytes(SEEDS["utf8-lf-final"])
    _apply(profile, upsert_profile_block(profile, BASH_BLOCK))
    first = profile.read_bytes()
    second = upsert_profile_block(profile, BASH_BLOCK)
    assert not second.changed and second.reason is None
    assert write_profile_edit(second) is None
    assert profile.read_bytes() == first


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"echo a\x00b\n", "nul_bytes"),
        (f"a\n{shell_profiles.BLOCK_BEGIN}\nb\n".encode(), "marker_mismatch"),
        (f"a\n{shell_profiles.BLOCK_END}\nb\n".encode(), "marker_mismatch"),
        (
            f"{shell_profiles.BLOCK_END}\nx\n{shell_profiles.BLOCK_BEGIN}\n".encode(),
            "marker_mismatch",
        ),
        ((BASH_BLOCK + "\n" + BASH_BLOCK + "\n").encode(), "marker_mismatch"),
        (codecs.BOM_UTF16_LE + b"a\x00b", "unreadable"),  # UTF-16 con un byte suelto
    ],
    ids=["nul-without-bom", "begin-only", "end-only", "end-before-begin", "two-blocks", "odd-16"],
)
def test_dubious_profiles_are_left_untouched_with_a_reason(tmp_path, raw, reason):
    """REQ-028: lo dudoso no se toca y se informa. Control positivo: sin la comprobación de NUL,
    el primer caso se decodifica como UTF-8 y se escribiría; sin la de pareja, el segundo
    recibiría un bloque nuevo al final."""
    profile = tmp_path / "profile"
    profile.write_bytes(raw)
    for edit in (upsert_profile_block(profile, BASH_BLOCK), remove_profile_block(profile)):
        assert edit.reason == reason
        assert not edit.changed
        assert str(profile) in edit.skip_message()
        assert write_profile_edit(edit) is None
    assert profile.read_bytes() == raw


def test_a_directory_in_place_of_the_profile_is_unreadable(tmp_path):
    profile = tmp_path / ".bashrc"
    profile.mkdir()
    assert upsert_profile_block(profile, BASH_BLOCK).reason == "unreadable"


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"no se pueden crear enlaces simbólicos aquí (Windows sin privilegio): {exc}")


def test_symlinked_profile_is_written_at_its_target_and_stays_a_link(tmp_path):
    """REQ-045: `.zshrc` enlazado a `dotfiles/zshrc` sigue siendo enlace, el destino vuelve byte a
    byte, y la copia propia va junto al destino. Control positivo: con `os.replace` desde un
    temporal sobre `edit.path`, el enlace se convierte en fichero."""
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "zshrc"
    real.write_bytes(SEEDS["utf8-tilde-lf"])
    link = tmp_path / ".zshrc"
    _symlink_or_skip(link, real)

    edit = upsert_profile_block(link, BASH_BLOCK)
    assert edit.target == real.resolve()
    _apply(link, edit)
    assert link.is_symlink()
    assert BASH_BLOCK.encode() in real.read_bytes()
    assert profile_backup_path(real.resolve()).read_bytes() == SEEDS["utf8-tilde-lf"]
    assert not profile_backup_path(link).exists()

    _apply(link, remove_profile_block(link))
    assert link.is_symlink()
    assert real.read_bytes() == SEEDS["utf8-tilde-lf"]


def test_broken_symlink_is_left_alone(tmp_path):
    link = tmp_path / ".zshrc"
    _symlink_or_skip(link, tmp_path / "missing")
    edit = upsert_profile_block(link, BASH_BLOCK)
    assert edit.reason == "broken_link" and not edit.changed


def test_own_backup_never_touches_the_users_bak_and_is_created_once(tmp_path):
    """REQ-046: `.bashrc.bak` del usuario intacto; `.local-delegate.bak` con el estado previo a la
    primera instalación, que una segunda instalación no pisa.

    Control positivo: con `install._backup` (que copia a `<perfil>.bak`) en lugar de la copia
    propia, el `.bashrc.bak` sembrado cambia; sin el `if not copy.exists()`, la segunda
    instalación pisa la copia con el perfil ya modificado.
    """
    profile = tmp_path / ".bashrc"
    seed = SEEDS["utf8-lf-final"]
    profile.write_bytes(seed)
    users_bak = tmp_path / ".bashrc.bak"
    users_bak.write_bytes(b"# copia del usuario\n")

    _apply(profile, upsert_profile_block(profile, BASH_BLOCK))
    own = profile_backup_path(profile)
    assert own.name == ".bashrc.local-delegate.bak"
    assert own.read_bytes() == seed

    other = shell_profiles.load_block("bash", PurePosixPath("/otra/ruta/local-delegate.bash"))
    _apply(profile, upsert_profile_block(profile, other))
    assert own.read_bytes() == seed  # sigue guardando el estado previo a la primera
    _apply(profile, remove_profile_block(profile))
    assert profile.read_bytes() == seed
    assert users_bak.read_bytes() == b"# copia del usuario\n"


def test_an_existing_own_backup_is_not_overwritten_and_backup_false_skips_it(tmp_path):
    profile = tmp_path / ".zshrc"
    profile.write_bytes(b"x\n")
    own = profile_backup_path(profile)
    own.write_bytes(b"estado anterior\n")
    _apply(profile, upsert_profile_block(profile, BASH_BLOCK))
    assert own.read_bytes() == b"estado anterior\n"

    other = tmp_path / ".bashrc"
    other.write_bytes(b"y\n")
    _apply(other, upsert_profile_block(other, BASH_BLOCK), backup=False)
    assert not profile_backup_path(other).exists()


@pytest.mark.skipif(
    sys.platform != "win32" and hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root escribe en ficheros de solo lectura",
)
def test_write_error_is_returned_not_raised(tmp_path):
    """REQ-028: un perfil de solo lectura da el error devuelto (`nombre (motivo)`), sin lanzar, y
    el perfil sigue igual. Control positivo: sin el `except OSError`, el test ve la excepción."""
    profile = tmp_path / ".bashrc"
    profile.write_bytes(b"x\n")
    edit = upsert_profile_block(profile, BASH_BLOCK)
    os.chmod(profile, stat.S_IREAD)
    try:
        error = write_profile_edit(edit, backup=False)
    finally:
        os.chmod(profile, stat.S_IREAD | stat.S_IWRITE)
    assert error is not None and error.startswith(".bashrc (")
    assert profile.read_bytes() == b"x\n"


def test_positive_control_of_deviation_1_the_text_helpers_lose_an_ansi_profile(tmp_path):
    """Desviación 1: con `_read_text` + `upsert_block`, un perfil de 5.1 en ANSI con tildes se
    pierde entero; con `upsert_profile_block`, no. Si un día `_read_text` dejara de devolver ""
    ante un fichero que no es UTF-8, este test lo diría y la desviación sobraría."""
    profile = tmp_path / "profile.ps1"
    profile.write_bytes(SEEDS["ansi-cp1252-crlf"])

    old = install.upsert_block(
        install._read_text(profile), PS_BLOCK, shell_profiles.BLOCK_BEGIN, shell_profiles.BLOCK_END
    )
    assert "Set-Alias" not in old  # la ruta de texto se come el perfil

    new = upsert_profile_block(profile, PS_BLOCK).data
    assert new is not None and new.startswith(SEEDS["ansi-cp1252-crlf"])
