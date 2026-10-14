"""La regla del idioma (REQ-018, REQ-019, REQ-047 lectura), el catálogo y su aislamiento (REQ-043).

Los tests prueban la función REAL, `hook_common.resolve_language`, con el entorno, el fichero de
preferencia y la API de Windows inyectados: así cada caso es el mismo en Linux, macOS y Windows, y
cada paso de la precedencia tiene un caso que solo él decide (afirmando el idioma **y** el origen).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import SUITE_LANGUAGE

from local_delegate import config, i18n
from local_delegate.resources.hooks import hook_common

HOOKS_DIR = Path(hook_common.__file__).parent


def _prefer(directory: Path, lang: str, source: str = "variable") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "language.json"
    path.write_text(json.dumps({"lang": lang, "source": source}), encoding="utf-8")
    return path


class _FakeKernel32:
    """`kernel32` con interfaz y formato regional DISTINTOS: si se mira el formato, se nota."""

    def __init__(self, ui_langid: int, lcid: int = 0x0C0A) -> None:
        self.ui_langid = ui_langid
        self.lcid = lcid

    def GetUserDefaultUILanguage(self) -> int:
        return self.ui_langid

    def GetUserDefaultLCID(self) -> int:
        return self.lcid

    def GetUserDefaultLangID(self) -> int:
        return self.lcid


class _BrokenKernel32:
    def GetUserDefaultUILanguage(self) -> int:
        raise OSError("sin API")


# --- REQ-019: la gramática ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("es", "es"),
        ("en", "en"),
        ("EN", "en"),
        ("es-MX", "es"),
        ("en_US", "en"),
        ("es-419", "es"),
        (" es ", "es"),
        ("fr", None),
        ("english", None),
        ("es-", None),
        ("es_ESP", None),
        ("es-4190", None),
        ("", None),
        (None, None),
    ],
)
def test_the_grammar_of_the_variable(value, expected):
    assert hook_common.parse_language(value) == expected


# --- REQ-018: los nueve casos de la spec, uno por paso --------------------------------------------


def _resolve(tmp_path: Path, env: dict[str, str], platform: str = "linux", ui_lang=None):
    return hook_common.resolve_language(tmp_path, env=env, platform=platform, ui_lang=ui_lang)


def test_case_1_language_list_wins_over_a_declared_lang(tmp_path):
    res = _resolve(tmp_path, {"LANGUAGE": "es:en", "LANG": "en_US.UTF-8"})
    assert (res.lang, res.source) == ("es", "system")


def test_case_2_language_list_is_ignored_when_the_locale_is_undeclared(tmp_path):
    res = _resolve(tmp_path, {"LANGUAGE": "es", "LANG": "C"})
    assert (res.lang, res.source) == ("en", "fallback")


def test_case_3_lc_all_wins_over_lang(tmp_path):
    res = _resolve(tmp_path, {"LC_ALL": "en_US.UTF-8", "LANG": "es_ES.UTF-8"})
    assert (res.lang, res.source) == ("en", "system")


@pytest.mark.parametrize("value", ["C.UTF-8", "C.utf8", "POSIX", "C"])
def test_case_4_c_utf8_counts_as_undeclared(tmp_path, value):
    # El idioma sale `en` también si se tratara como declarado: el origen es lo que distingue.
    res = _resolve(tmp_path, {"LANG": value})
    assert (res.lang, res.source) == ("en", "fallback")


def test_case_5_windows_uses_the_interface_not_the_regional_format(tmp_path, monkeypatch):
    # Interfaz en-US (0x0409) y formato regional es-ES (0x0C0A) en el kernel32 falso.
    assert hook_common._windows_ui_language(_FakeKernel32(0x0409, lcid=0x0C0A)) == "en_US"
    monkeypatch.setattr(hook_common, "_windows_ui_language", lambda: "en_US")
    res = _resolve(tmp_path, {"LANG": "es_ES.UTF-8"}, platform="win32")
    assert (res.lang, res.source) == ("en", "system")


def test_case_6_windows_ignores_lang_from_git_bash(tmp_path):
    res = _resolve(tmp_path, {"LANG": "en_US.UTF-8"}, platform="win32", ui_lang="es-ES")
    assert (res.lang, res.source) == ("es", "system")


def test_case_7_the_preference_wins_over_the_system(tmp_path):
    _prefer(tmp_path, "es")
    res = _resolve(tmp_path, {"LANG": "en_US.UTF-8"})
    assert (res.lang, res.source) == ("es", "preference")


def test_case_8_the_variable_wins_over_the_preference(tmp_path):
    _prefer(tmp_path, "es")
    res = _resolve(tmp_path, {"LOCAL_DELEGATE_LANG": "en", "LANG": "es_ES.UTF-8"})
    assert (res.lang, res.source) == ("en", "variable")


def test_case_9_an_invalid_variable_is_ignored_with_a_warning(tmp_path):
    res = _resolve(tmp_path, {"LOCAL_DELEGATE_LANG": "fr", "LANG": "es_ES.UTF-8"})
    assert (res.lang, res.source) == ("es", "system")
    assert ("invalid_variable", "fr") in res.warnings


# --- Más allá de los nueve casos ------------------------------------------------------------------


def test_lc_messages_wins_over_lang(tmp_path):
    res = _resolve(tmp_path, {"LC_MESSAGES": "es_ES.UTF-8", "LANG": "en_US.UTF-8"})
    assert (res.lang, res.source) == ("es", "system")


def test_nothing_declared_is_the_english_fallback(tmp_path):
    res = _resolve(tmp_path, {})
    assert (res.lang, res.source, res.warnings) == ("en", "fallback", ())


def test_a_declared_non_spanish_system_is_english_from_the_system(tmp_path):
    res = _resolve(tmp_path, {"LANG": "fr_FR.UTF-8"})
    assert (res.lang, res.source) == ("en", "system")


def test_estonian_does_not_start_with_es(tmp_path):
    res = _resolve(tmp_path, {"LANG": "en_US.UTF-8", "LANGUAGE": "est:en"})
    assert (res.lang, res.source) == ("en", "system")


@pytest.mark.parametrize("value", ["", "   "])
def test_an_empty_variable_is_unset_without_warning(tmp_path, value):
    res = _resolve(tmp_path, {"LOCAL_DELEGATE_LANG": value, "LANG": "es_ES.UTF-8"})
    assert (res.lang, res.source, res.warnings) == ("es", "system", ())


def test_an_unreadable_preference_is_ignored_with_a_warning(tmp_path):
    (tmp_path / "language.json").write_text("{roto", encoding="utf-8")
    res = _resolve(tmp_path, {"LANG": "es_ES.UTF-8"})
    assert (res.lang, res.source) == ("es", "system")
    assert res.warnings == (("unreadable_preference", str(tmp_path / "language.json")),)


@pytest.mark.parametrize("content", [{"lang": "fr"}, {"source": "system"}, ["es"], {"lang": 1}])
def test_an_invalid_preference_is_ignored_with_a_warning(tmp_path, content):
    (tmp_path / "language.json").write_text(json.dumps(content), encoding="utf-8")
    res = _resolve(tmp_path, {"LANG": "es_ES.UTF-8"})
    assert (res.lang, res.source) == ("es", "system")
    assert res.warnings == (("invalid_preference", str(tmp_path / "language.json")),)


def test_the_preference_path_is_reported_even_if_missing(tmp_path):
    res = _resolve(tmp_path / "nada", {})
    assert res.pref_path == tmp_path / "nada" / "language.json"


def test_windows_api_failure_is_the_fallback(tmp_path, monkeypatch):
    assert hook_common._windows_ui_language(_BrokenKernel32()) is None
    monkeypatch.setattr(hook_common, "_windows_ui_language", lambda: None)
    res = _resolve(tmp_path, {"LANG": "es_ES.UTF-8"}, platform="win32")
    assert (res.lang, res.source) == ("en", "fallback")


def test_windows_langid_outside_the_table_uses_the_primary_language():
    # 0x7C0A no está en `locale.windows_locale`; su idioma primario (0x0A) es el español.
    import locale

    assert 0x7C0A not in locale.windows_locale
    assert hook_common._windows_ui_language(_FakeKernel32(0x7C0A)) == "es"
    assert hook_common._windows_ui_language(_FakeKernel32(0x0C0A)) == "es_ES"


@pytest.mark.skipif(sys.platform != "win32", reason="la API real solo existe en Windows")
def test_the_real_windows_api_answers():
    assert isinstance(hook_common._windows_ui_language(), str)


# --- i18n: el idioma del proceso y el catálogo ----------------------------------------------------


def test_the_suite_runs_in_spanish():
    assert os.environ["LOCAL_DELEGATE_LANG"] == SUITE_LANGUAGE == "es"
    assert (i18n.lang(), i18n.current().source) == ("es", "variable")


def test_current_reads_the_preference_of_config_log_dir(tmp_path, monkeypatch):
    """El paquete pasa `config.LOG_DIR`, no el directorio que resolvería un hook por su cuenta.

    Se separan a propósito: con los dos iguales (lo normal en la suite), pasar el otro no se vería.
    """
    monkeypatch.delenv("LOCAL_DELEGATE_LANG")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "config_dir")
    _prefer(config.LOG_DIR, "en")
    i18n.reset()
    assert (i18n.lang(), i18n.current().source) == ("en", "preference")
    assert i18n.current().pref_path == config.LOG_DIR / "language.json"


def test_current_is_cached_until_reset(monkeypatch):
    assert i18n.lang() == "es"
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    assert i18n.lang() == "es"
    i18n.reset()
    assert i18n.lang() == "en"


def test_the_shipped_catalog_has_the_language_labels():
    assert i18n.t_lang("es", "common.language.source.fallback") == "reserva"
    assert i18n.t_lang("en", "common.language.source.fallback") == "fallback"
    assert i18n.t("common.language.source.preference") == "preferencia"
    text = i18n.t_lang("en", "common.output_language.warning.too_long", max=40)
    assert "40" in text and "{max}" not in text


@pytest.fixture
def fake_catalog(monkeypatch):
    data = {
        "es": {
            "x.hello": "Hola, {name}",
            "x.only_es": "solo es",
            "argparse.usage": "uso: ",
            "argparse.one": "un argumento",
            "argparse.many": "varios argumentos",
        },
        "en": {
            "x.hello": "Hello, {name}",
            "argparse.usage": "usage: ",
            "argparse.one": "one argument",
            "argparse.many": "several arguments",
        },
    }

    def fake(language: str) -> dict[str, str]:
        return data.get(language, {})

    fake.cache_clear = lambda: None  # `i18n.reset()` la llama también con el falso puesto
    i18n.reset()
    monkeypatch.setattr(i18n, "catalog", fake)
    yield data
    i18n.reset()


def test_t_lang_interpolates_and_falls_back_to_spanish(fake_catalog):
    assert i18n.t_lang("en", "x.hello", name="Ana") == "Hello, Ana"
    assert i18n.t_lang("en", "x.only_es") == "solo es"
    assert i18n.t_lang("en", "x.missing") == "x.missing"


def test_argparse_gettext_translates_only_in_spanish(fake_catalog, monkeypatch):
    assert i18n.argparse_gettext("usage: ") == "uso: "
    assert i18n.argparse_gettext("not in the catalog") == "not in the catalog"
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.current.cache_clear()
    assert i18n.argparse_gettext("usage: ") == "usage: "


def test_argparse_ngettext_picks_the_form_by_n(fake_catalog):
    assert i18n.argparse_ngettext("one argument", "several arguments", 1) == "un argumento"
    assert i18n.argparse_ngettext("one argument", "several arguments", 2) == "varios argumentos"


# --- config: LOCAL_DELEGATE_OUTPUT_LANGUAGE (enmienda de REQ-028) ---------------------------------


@pytest.mark.parametrize(
    ("raw", "value", "problem"),
    [
        (None, "", None),
        ("", "", None),
        ("   ", "", None),
        (" fr ", "fr", None),
        ("português do Brasil", "português do Brasil", None),
        ("x" * 40, "x" * 40, None),
        ("x" * 41, "", "too_long"),
        ("fr\nen", "", "control_chars"),
        ("fr\u2028en", "", "control_chars"),
        ("fr\u200b", "", "control_chars"),
        ("fr\x07", "", "control_chars"),
    ],
)
def test_output_language_is_validated(monkeypatch, raw, value, problem):
    if raw is None:
        monkeypatch.delenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raising=False)
    else:
        monkeypatch.setenv("LOCAL_DELEGATE_OUTPUT_LANGUAGE", raw)
    result = config.output_language()
    assert (result.value, result.problem) == (value, problem)
    assert result.raw == (raw or "")


# --- REQ-043: la suite no lee el idioma de la máquina ---------------------------------------------


def _fake_user_dirs(tmp_path: Path, monkeypatch) -> Path:
    """Directorios de datos «reales» falsos, con un `language.json` en inglés en cada sitio."""
    fake = tmp_path / "usuario"
    monkeypatch.setenv("LOCALAPPDATA", str(fake / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(fake / "share"))
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    for base in (
        fake / "AppData" / "Local",
        fake / "share",
        fake / "Library" / "Application Support",
    ):
        _prefer(base / "local-delegate", "en")
    return fake


def test_a_fake_user_preference_does_not_leak_in_process(tmp_path, monkeypatch):
    """REQ-043 a: con un `language.json` en inglés en el directorio «real», la suite sigue en es."""
    data_dir = tmp_path / "datos"
    monkeypatch.setattr(config, "LOG_DIR", data_dir)
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(data_dir))
    _fake_user_dirs(tmp_path, monkeypatch)
    i18n.reset()
    assert i18n.lang() == "es"
    assert hook_common.log_dir() == data_dir


def test_a_hook_subprocess_uses_the_suite_data_dir(tmp_path, monkeypatch):
    """REQ-043 b: un hook como subproceso, SIN la variable de idioma, lee la preferencia del
    directorio de la suite (`es`) y no la del usuario (`en`). Sin `LOCAL_DELEGATE_LOG_DIR` en el
    entorno (el fixture de conftest), resolvería al directorio «real» falso y diría `en`."""
    _prefer(config.LOG_DIR, "es")
    _fake_user_dirs(tmp_path, monkeypatch)
    env = {k: v for k, v in os.environ.items() if k != "LOCAL_DELEGATE_LANG"}
    code = "import hook_common as h; print(h.resolve_language(h.log_dir()).lang)"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=HOOKS_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.strip()
    assert out == "es"


# --- REQ-043: el `locale` del navegador del panel -------------------------------------------------


class _FakeBrowser:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    def new_page(self, **kwargs):
        self.kwargs = kwargs
        return "page"


def test_new_page_uses_spanish_by_default(new_page):
    browser = _FakeBrowser()
    assert new_page(browser, viewport={"width": 800, "height": 600}) == "page"
    assert browser.kwargs == {"locale": "es-ES", "viewport": {"width": 800, "height": 600}}


@pytest.mark.parametrize("browser_locale", ["en-US"])
def test_new_page_follows_an_overridden_locale(new_page, browser_locale):
    browser = _FakeBrowser()
    new_page(browser)
    assert browser.kwargs["locale"] == "en-US"
