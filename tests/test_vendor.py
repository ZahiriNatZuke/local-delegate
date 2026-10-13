"""Pruebas de `scripts/check_vendor.py`, el vigilante del vendorizado.

Dos reglas gobiernan este archivo:

1. **Lo que hay que probar es que la detección detecta.** Un test que solo compruebe «con el
   fichero bueno pasa» no prueba nada: pasaría igual con un script que devolviera `0` siempre. Los
   tests que valen son los inversos — blob alterado, fichero ausente, fichero sin declarar — y
   exigen que el script **falle**.
2. **Siempre sobre copias en `tmp_path`, nunca sobre el fichero real.** Un test que escriba en
   `src/local_delegate/resources/vendor/chart.umd.min.js` puede dejar el repo sucio si falla a
   mitad, y es justo el fichero cuya integridad estamos protegiendo.

Ningún test sale a la red: se sustituye `_pedir_json`, por donde pasa toda la salida a internet, y
lo que se prueba es la **lógica de decisión** (qué rompe y qué solo avisa), no OSV ni npm.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
VENDOR_REAL = ROOT / "src" / "local_delegate" / "resources" / "vendor"
SCRIPTS = ROOT / "scripts"

# `scripts/` no viaja en el sdist (ver `[tool.hatch.build.targets.sdist]`), así que estas pruebas
# no pueden correr sobre un tarball desempaquetado. La condición mira el **directorio**, no el
# fichero: si `scripts/` está pero `check_vendor.py` no, eso es un borrado accidental y el test
# tiene que fallar, no saltarse. Un skip que tape eso deja el vigilante del vendorizado sin
# cobertura y el CI en verde.
if not SCRIPTS.is_dir():
    pytest.skip(
        "scripts/ no está en el árbol (sdist): estas pruebas necesitan el repositorio",
        allow_module_level=True,
    )


def _load_script():
    spec = importlib.util.spec_from_file_location("check_vendor", SCRIPTS / "check_vendor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_vendor = _load_script()

# La versión vendorizada se LEE del manifiesto, nunca se escribe en este archivo: si se clava,
# cada subida de Chart.js obliga a tocar tests que no tienen nada que ver con lo que prueban.
# Pasó al subir de 4.4.1 a 4.5.1, y por eso los tests de versión usan `VENDORED_VERSION`
# («al día») y `MUCH_LATER` («hay una más nueva») en vez de números concretos.
VENDORED_VERSION = next(
    f["version"]
    for f in json.loads((VENDOR_REAL / "vendor.json").read_text(encoding="utf-8"))["files"]
    if f["file"] == "chart.umd.min.js"
)
MUCH_LATER = "99.0.0"


@pytest.fixture
def vendor_copy(tmp_path):
    """Copia intacta del directorio vendorizado. Devuelve la ruta de su manifiesto."""
    dest = tmp_path / "vendor"
    shutil.copytree(VENDOR_REAL, dest)
    return dest / "vendor.json"


def _without_network(monkeypatch, osv=None, npm=None):
    """Sustituye la única función que sale a internet.

    `osv` y `npm` son callables sin argumentos que devuelven el cuerpo de la respuesta o lanzan.
    """

    def fake(url, payload=None):
        if url == check_vendor.OSV_URL:
            if osv is None:
                raise AssertionError("el test no esperaba una consulta a OSV")
            return osv()
        if npm is None:
            raise AssertionError("el test no esperaba una consulta a npm")
        return npm()

    monkeypatch.setattr(check_vendor, "_fetch_json", fake)


# --- integridad: lo que TIENE que romper el CI ---------------------------------------------------
def test_altered_blob_fails(vendor_copy):
    """El test que de verdad importa: si el contenido cambia, el script lo canta."""
    blob = vendor_copy.parent / "chart.umd.min.js"
    data = blob.read_bytes()
    blob.write_bytes(data[:-1] + b"X")  # un solo byte distinto

    assert check_vendor.main(["--offline", "--manifest", str(vendor_copy)]) == (
        check_vendor.INTEGRITY_FAILURE
    )


def test_missing_blob_fails(vendor_copy):
    (vendor_copy.parent / "chart.umd.min.js").unlink()

    assert check_vendor.main(["--offline", "--manifest", str(vendor_copy)]) == (
        check_vendor.INTEGRITY_FAILURE
    )


def test_undeclared_file_fails(vendor_copy):
    """Un vendorizado no declarado es el punto ciego que este cambio viene a cerrar."""
    (vendor_copy.parent / "intruso.min.js").write_text("window.x = 1", encoding="utf-8")

    assert check_vendor.main(["--offline", "--manifest", str(vendor_copy)]) == (
        check_vendor.INTEGRITY_FAILURE
    )


def test_unreadable_manifest_fails(tmp_path):
    broken = tmp_path / "vendor.json"
    broken.write_text("{esto no es json", encoding="utf-8")

    assert check_vendor.main(["--offline", "--manifest", str(broken)]) == (
        check_vendor.MANIFEST_FAILURE
    )


def test_real_manifest_matches_the_blob():
    """Solo lectura sobre el árbol real: el hash declarado es el del fichero que se publica."""
    manifest = json.loads((VENDOR_REAL / "vendor.json").read_text(encoding="utf-8"))
    errors = check_vendor.check_integrity(manifest, VENDOR_REAL)

    assert errors == []


def test_the_manifest_declares_the_banner_trap():
    """REQ-006: sin esta nota, el siguiente que verifique a mano concluirá que el blob está mal."""
    text = (VENDOR_REAL / "vendor.json").read_text(encoding="utf-8")

    assert "jsDelivr" in text
    assert "274" in text


def test_gitattributes_protects_the_vendored_copy_from_normalization():
    """La premisa sin la que nada de esto funciona, y que el CI de Windows cazó.

    Con `core.autocrlf=true` —el valor por defecto de Git for Windows y el del runner
    `windows-latest`— git convierte los LF del blob en CRLF al hacer checkout: 205 139 bytes en
    vez de 205 125, y el hash deja de cuadrar sin que nadie haya tocado nada. Este test fija el
    `-text` que lo impide; borrarlo rompe el vigilante en toda máquina Windows.
    """
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "resources/vendor/** -text" in text


def test_the_crlf_hint_shows_when_due(vendor_copy):
    """Un fin de línea distinto no es un ataque; el mensaje tiene que decirlo."""
    blob = vendor_copy.parent / "chart.umd.min.js"
    blob.write_bytes(blob.read_bytes().replace(b"\n", b"\r\n"))
    manifest = json.loads(vendor_copy.read_text(encoding="utf-8"))

    errors = check_vendor.check_integrity(manifest, vendor_copy.parent)

    assert len(errors) == 1
    assert "PISTA" in errors[0]
    assert ".gitattributes" in errors[0]


# --- CVEs: lo que TIENE que romper el CI ---------------------------------------------------------
def test_confirmed_vulnerability_fails(vendor_copy, monkeypatch):
    _without_network(
        monkeypatch,
        osv=lambda: {"vulns": [{"id": "GHSA-xxxx-yyyy-zzzz"}]},
        npm=lambda: {"version": VENDORED_VERSION},
    )

    assert check_vendor.main(["--manifest", str(vendor_copy)]) == (
        check_vendor.VULNERABILITY_FAILURE
    )


# --- red: lo que solo puede AVISAR ---------------------------------------------------------------
def _down():
    raise check_vendor.ServiceUnavailable("simulado")


def test_osv_down_does_not_fail(vendor_copy, monkeypatch, capsys):
    """Un servicio ajeno caído no puede bloquear un PR legítimo: la integridad ya se comprobó."""
    _without_network(monkeypatch, osv=_down, npm=lambda: {"version": VENDORED_VERSION})

    assert check_vendor.main(["--manifest", str(vendor_copy)]) == check_vendor.OK
    assert "AVISO" in capsys.readouterr().out


def test_npm_down_does_not_fail(vendor_copy, monkeypatch, capsys):
    _without_network(monkeypatch, osv=lambda: {"vulns": []}, npm=_down)

    assert check_vendor.main(["--manifest", str(vendor_copy)]) == check_vendor.OK
    assert "AVISO" in capsys.readouterr().out


def test_malformed_osv_does_not_fail(vendor_copy, monkeypatch, capsys):
    """No saber nada se trata como servicio caído: avisa, no rompe."""
    _without_network(monkeypatch, osv=lambda: {"vulns": "esto debería ser una lista"}, npm=_down)

    assert check_vendor.main(["--manifest", str(vendor_copy)]) == check_vendor.OK
    assert "AVISO" in capsys.readouterr().out


def test_new_version_warns_without_failing(vendor_copy, monkeypatch, capsys):
    _without_network(monkeypatch, osv=lambda: {"vulns": []}, npm=lambda: {"version": MUCH_LATER})

    assert check_vendor.main(["--manifest", str(vendor_copy)]) == check_vendor.OK
    output = capsys.readouterr().out
    assert "AVISO" in output
    assert MUCH_LATER in output


def test_up_to_date_version_does_not_warn(vendor_copy, monkeypatch, capsys):
    _without_network(
        monkeypatch, osv=lambda: {"vulns": []}, npm=lambda: {"version": VENDORED_VERSION}
    )

    assert check_vendor.main(["--manifest", str(vendor_copy)]) == check_vendor.OK
    assert "AVISO" not in capsys.readouterr().out


def test_integrity_takes_precedence_over_the_vulnerability(vendor_copy, monkeypatch):
    """Con las dos cosas rotas, el código de salida es el del diagnóstico más fiable."""
    blob = vendor_copy.parent / "chart.umd.min.js"
    blob.write_bytes(b"contenido sustituido")
    _without_network(
        monkeypatch,
        osv=lambda: {"vulns": [{"id": "GHSA-x"}]},
        npm=lambda: {"version": VENDORED_VERSION},
    )

    assert check_vendor.main(["--manifest", str(vendor_copy)]) == (check_vendor.INTEGRITY_FAILURE)


# --- comparación de versiones --------------------------------------------------------------------
@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("4.4.1", (4, 4, 1)),
        ("4.5", (4, 5)),
        ("5.0.0-beta.1", (5, 0, 0)),
        ("no-una-version", None),
        ("", None),
    ],
)
def test_version_key(version, expected):
    assert check_vendor._version_key(version) == expected


def test_incomparable_version_warns_without_failing(vendor_copy, monkeypatch, capsys):
    _without_network(
        monkeypatch, osv=lambda: {"vulns": []}, npm=lambda: {"version": "latest-stable"}
    )

    assert check_vendor.main(["--manifest", str(vendor_copy)]) == check_vendor.OK
    assert "AVISO" in capsys.readouterr().out


# --- summary del job -----------------------------------------------------------------------------
def test_the_report_also_goes_to_the_summary(vendor_copy, monkeypatch, tmp_path):
    """Un aviso enterrado en el log de un job verde no lo lee nadie (F3 de la revisión del plan)."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _without_network(monkeypatch, osv=lambda: {"vulns": []}, npm=lambda: {"version": MUCH_LATER})

    check_vendor.main(["--manifest", str(vendor_copy)])

    content = summary.read_text(encoding="utf-8")
    assert "AVISO" in content
    assert MUCH_LATER in content
