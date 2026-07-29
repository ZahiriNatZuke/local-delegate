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


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "check_vendor", ROOT / "scripts" / "check_vendor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_vendor = _load_script()


@pytest.fixture
def vendor_copia(tmp_path):
    """Copia intacta del directorio vendorizado. Devuelve la ruta de su manifiesto."""
    destino = tmp_path / "vendor"
    shutil.copytree(VENDOR_REAL, destino)
    return destino / "vendor.json"


def _sin_red(monkeypatch, osv=None, npm=None):
    """Sustituye la única función que sale a internet.

    `osv` y `npm` son callables sin argumentos que devuelven el cuerpo de la respuesta o lanzan.
    """

    def falso(url, payload=None):
        if url == check_vendor.OSV_URL:
            if osv is None:
                raise AssertionError("el test no esperaba una consulta a OSV")
            return osv()
        if npm is None:
            raise AssertionError("el test no esperaba una consulta a npm")
        return npm()

    monkeypatch.setattr(check_vendor, "_pedir_json", falso)


# --- integridad: lo que TIENE que romper el CI ---------------------------------------------------
def test_blob_alterado_falla(vendor_copia):
    """El test que de verdad importa: si el contenido cambia, el script lo canta."""
    blob = vendor_copia.parent / "chart.umd.min.js"
    datos = blob.read_bytes()
    blob.write_bytes(datos[:-1] + b"X")  # un solo byte distinto

    assert check_vendor.main(["--offline", "--manifest", str(vendor_copia)]) == (
        check_vendor.FALLO_INTEGRIDAD
    )


def test_blob_ausente_falla(vendor_copia):
    (vendor_copia.parent / "chart.umd.min.js").unlink()

    assert check_vendor.main(["--offline", "--manifest", str(vendor_copia)]) == (
        check_vendor.FALLO_INTEGRIDAD
    )


def test_fichero_sin_declarar_falla(vendor_copia):
    """Un vendorizado no declarado es el punto ciego que este cambio viene a cerrar."""
    (vendor_copia.parent / "intruso.min.js").write_text("window.x = 1", encoding="utf-8")

    assert check_vendor.main(["--offline", "--manifest", str(vendor_copia)]) == (
        check_vendor.FALLO_INTEGRIDAD
    )


def test_manifiesto_ilegible_falla(tmp_path):
    roto = tmp_path / "vendor.json"
    roto.write_text("{esto no es json", encoding="utf-8")

    assert check_vendor.main(["--offline", "--manifest", str(roto)]) == (
        check_vendor.FALLO_MANIFIESTO
    )


def test_manifiesto_real_cuadra_con_el_blob():
    """Solo lectura sobre el árbol real: el hash declarado es el del fichero que se publica."""
    manifiesto = json.loads((VENDOR_REAL / "vendor.json").read_text(encoding="utf-8"))
    errores = check_vendor.comprobar_integridad(manifiesto, VENDOR_REAL)

    assert errores == []


def test_el_manifiesto_declara_la_trampa_del_banner():
    """REQ-006: sin esta nota, el siguiente que verifique a mano concluirá que el blob está mal."""
    texto = (VENDOR_REAL / "vendor.json").read_text(encoding="utf-8")

    assert "jsDelivr" in texto
    assert "274" in texto


# --- CVEs: lo que TIENE que romper el CI ---------------------------------------------------------
def test_vulnerabilidad_confirmada_falla(vendor_copia, monkeypatch):
    _sin_red(
        monkeypatch,
        osv=lambda: {"vulns": [{"id": "GHSA-xxxx-yyyy-zzzz"}]},
        npm=lambda: {"version": "4.4.1"},
    )

    assert check_vendor.main(["--manifest", str(vendor_copia)]) == (
        check_vendor.FALLO_VULNERABILIDAD
    )


# --- red: lo que solo puede AVISAR ---------------------------------------------------------------
def _caido():
    raise check_vendor.ServicioNoDisponible("simulado")


def test_osv_caido_no_falla(vendor_copia, monkeypatch, capsys):
    """Un servicio ajeno caído no puede bloquear un PR legítimo: la integridad ya se comprobó."""
    _sin_red(monkeypatch, osv=_caido, npm=lambda: {"version": "4.4.1"})

    assert check_vendor.main(["--manifest", str(vendor_copia)]) == check_vendor.OK
    assert "AVISO" in capsys.readouterr().out


def test_npm_caido_no_falla(vendor_copia, monkeypatch, capsys):
    _sin_red(monkeypatch, osv=lambda: {"vulns": []}, npm=_caido)

    assert check_vendor.main(["--manifest", str(vendor_copia)]) == check_vendor.OK
    assert "AVISO" in capsys.readouterr().out


def test_osv_malformado_no_falla(vendor_copia, monkeypatch, capsys):
    """No saber nada se trata como servicio caído: avisa, no rompe."""
    _sin_red(monkeypatch, osv=lambda: {"vulns": "esto debería ser una lista"}, npm=_caido)

    assert check_vendor.main(["--manifest", str(vendor_copia)]) == check_vendor.OK
    assert "AVISO" in capsys.readouterr().out


def test_version_nueva_avisa_sin_fallar(vendor_copia, monkeypatch, capsys):
    _sin_red(monkeypatch, osv=lambda: {"vulns": []}, npm=lambda: {"version": "4.5.1"})

    assert check_vendor.main(["--manifest", str(vendor_copia)]) == check_vendor.OK
    salida = capsys.readouterr().out
    assert "AVISO" in salida
    assert "4.5.1" in salida


def test_version_al_dia_no_avisa(vendor_copia, monkeypatch, capsys):
    _sin_red(monkeypatch, osv=lambda: {"vulns": []}, npm=lambda: {"version": "4.4.1"})

    assert check_vendor.main(["--manifest", str(vendor_copia)]) == check_vendor.OK
    assert "AVISO" not in capsys.readouterr().out


def test_integridad_manda_sobre_la_vulnerabilidad(vendor_copia, monkeypatch):
    """Con las dos cosas rotas, el código de salida es el del diagnóstico más fiable."""
    blob = vendor_copia.parent / "chart.umd.min.js"
    blob.write_bytes(b"contenido sustituido")
    _sin_red(
        monkeypatch, osv=lambda: {"vulns": [{"id": "GHSA-x"}]}, npm=lambda: {"version": "4.4.1"}
    )

    assert check_vendor.main(["--manifest", str(vendor_copia)]) == (check_vendor.FALLO_INTEGRIDAD)


# --- comparación de versiones --------------------------------------------------------------------
@pytest.mark.parametrize(
    ("version", "esperado"),
    [
        ("4.4.1", (4, 4, 1)),
        ("4.5", (4, 5)),
        ("5.0.0-beta.1", (5, 0, 0)),
        ("no-una-version", None),
        ("", None),
    ],
)
def test_clave_version(version, esperado):
    assert check_vendor._clave_version(version) == esperado


def test_version_incomparable_avisa_sin_fallar(vendor_copia, monkeypatch, capsys):
    _sin_red(monkeypatch, osv=lambda: {"vulns": []}, npm=lambda: {"version": "latest-stable"})

    assert check_vendor.main(["--manifest", str(vendor_copia)]) == check_vendor.OK
    assert "AVISO" in capsys.readouterr().out


# --- summary del job -----------------------------------------------------------------------------
def test_el_informe_va_tambien_al_summary(vendor_copia, monkeypatch, tmp_path):
    """Un aviso enterrado en el log de un job verde no lo lee nadie (F3 de la revisión del plan)."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _sin_red(monkeypatch, osv=lambda: {"vulns": []}, npm=lambda: {"version": "4.5.1"})

    check_vendor.main(["--manifest", str(vendor_copia)])

    assert "4.5.1" in summary.read_text(encoding="utf-8")
