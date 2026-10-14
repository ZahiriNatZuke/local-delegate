"""`doctor` en español y en inglés (frente B, ola B1b): REQ-019, REQ-022, REQ-034 y D11.

- **REQ-022:** los mismos 25 checks, en el mismo orden y con los mismos ids, en los dos idiomas;
  los títulos, estados, detalles, remedios, cabeceras y resumen salen en el idioma vigente.
- **REQ-034:** en inglés no aparece ninguna palabra distintiva del catálogo español (las que no
  salen en ningún valor inglés) ni tildes; control positivo permanente: en español sí aparecen.
- **REQ-019:** la cabecera dice el idioma, su origen («variable», «preferencia», «sistema» o
  «reserva») y el `language.json`, y avisa de un valor no válido.
- **D11:** si lo guardado en `language.json` vino de la variable, `doctor` dice cómo volver a
  seguir al sistema.
"""

from __future__ import annotations

import argparse
import json
import re
from importlib.resources import files
from pathlib import Path

import pytest
from conftest import make_home
from test_doctor import _stub_environment

from local_delegate import checks, config, doctor, i18n
from local_delegate.resources.hooks import hook_common

SURFACES = ("doctor", "common")
#: Textos que `doctor` imprime pero redactan módulos de olas posteriores, todavía en español
#: (fragmento → módulo que lo escribe). Se quitan de la salida inglesa antes de buscar palabras;
#: `test_the_pending_fragments_still_live_in_their_modules` obliga a quitarlos de aquí en cuanto
#: su ola los traduzca.
PENDING_FRAGMENTS = {
    "sin residente (recomendado)": "residency.py",  # B1c
    "el daemon no responde": "llamaswap_api.py",  # B1c
    "sin LLAMASWAP_CONFIG": "topology.py",  # B1c
    "sin residente (no se sabe: ": "chains.py",  # B2
    "sin residente": "chains.py",  # B2
}
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")
_ACCENTS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡«»]")


def _catalog(lang: str, surface: str) -> dict[str, str]:
    path = files("local_delegate").joinpath("resources", "i18n", lang, f"{surface}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _distinctive_spanish_words() -> set[str]:
    english: set[str] = set()
    for surface in SURFACES:
        for text in _catalog("en", surface).values():
            english.update(w.lower() for w in _WORD.findall(text))
    spanish: set[str] = set()
    for surface in SURFACES:
        es, en = _catalog("es", surface), _catalog("en", surface)
        for key, text in es.items():
            if text != en[key]:
                spanish.update(w.lower() for w in _WORD.findall(text))
    return spanish - english


def _set_language(monkeypatch, lang: str) -> None:
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", lang)
    i18n.reset()


def _spanish_in(text: str, words: set[str]) -> list[str]:
    # Las rutas son datos, no texto: la suite apunta el directorio de datos a `tests/_sin_logs`.
    text = " ".join(token for token in text.split() if "/" not in token and "\\" not in token)
    return sorted({w for w in (m.lower() for m in _WORD.findall(text)) if w in words})


def _doctor_output(tmp_path, monkeypatch, capsys, lang: str, *, complete: bool) -> tuple[int, str]:
    _set_language(monkeypatch, lang)
    _stub_environment(monkeypatch)
    home = make_home(tmp_path / lang, complete=complete)
    args = argparse.Namespace(config=None, online=False, home=str(home))
    code = doctor.run_doctor(args)
    return code, capsys.readouterr().out


def _check_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("  [")]


@pytest.mark.parametrize("complete", [True, False], ids=["complete-home", "empty-home"])
def test_doctor_in_english_has_no_spanish(complete, tmp_path, monkeypatch, capsys):
    words = _distinctive_spanish_words()
    assert len(words) >= 100, "sin palabras distintivas el test no discrimina"
    code_es, out_es = _doctor_output(tmp_path, monkeypatch, capsys, "es", complete=complete)
    code_en, out_en = _doctor_output(tmp_path, monkeypatch, capsys, "en", complete=complete)
    # Guarda de «esto llegó a comprobar algo»: los dos corrieron los 25 checks, con el mismo veredicto.
    assert code_es == code_en
    assert len(_check_lines(out_es)) == len(_check_lines(out_en)) == len(checks.CHECKS) == 25
    assert "Language:" in out_en and "Idioma:" in out_es
    for fragment in sorted(PENDING_FRAGMENTS, key=len, reverse=True):
        out_en = out_en.replace(fragment, " ")
    assert not _spanish_in(out_en, words), _spanish_in(out_en, words)
    assert not _ACCENTS.search(out_en), out_en
    # Control positivo permanente: la misma salida en español sí tiene palabras distintivas.
    assert _spanish_in(out_es, words)


def test_the_missing_label_is_translated(tmp_path, monkeypatch, capsys):
    _code, out_es = _doctor_output(tmp_path, monkeypatch, capsys, "es", complete=False)
    _code, out_en = _doctor_output(tmp_path, monkeypatch, capsys, "en", complete=False)
    assert "[FALT]" in out_es and "[MISS]" not in out_es
    assert "[MISS]" in out_en and "[FALT]" not in out_en
    # La leyenda y el resumen usan los mismos rótulos que las líneas de los checks.
    assert "[MISS] missing" in out_en and "check [MISS] and [WARN] above" in out_en


def test_the_ids_and_order_do_not_change_with_the_language(monkeypatch):
    titles = {}
    for lang in ("es", "en"):
        _set_language(monkeypatch, lang)
        titles[lang] = [(c.id, c.group, c.title) for c in checks.CHECKS]
    assert [t[:2] for t in titles["es"]] == [t[:2] for t in titles["en"]]
    assert [t[2] for t in titles["es"]] != [t[2] for t in titles["en"]]


def test_every_check_title_is_in_both_catalogs():
    for lang in ("es", "en"):
        catalog = _catalog(lang, "doctor")
        missing = [c.title_key for c in checks.CHECKS if c.title_key not in catalog]
        assert missing == [], (lang, missing)


# --- REQ-019 y D11: la cabecera del idioma ---------------------------------------------------


def _language_lines(monkeypatch, tmp_path, *, variable: str | None, stored: dict | None) -> str:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    if variable is None:
        monkeypatch.delenv("LOCAL_DELEGATE_LANG", raising=False)
    else:
        monkeypatch.setenv("LOCAL_DELEGATE_LANG", variable)
    if stored is not None:
        (tmp_path / hook_common.LANGUAGE_PREFERENCE_FILE).write_text(
            json.dumps(stored), encoding="utf-8"
        )
    i18n.reset()
    return "\n".join(doctor.language_lines())


def test_doctor_shows_the_variable_as_the_source(monkeypatch, tmp_path):
    text = _language_lines(monkeypatch, tmp_path, variable="en", stored=None)
    assert text.startswith("Language:         en (variable; ")
    assert str(tmp_path / "language.json") in text


def test_doctor_shows_the_preference_and_its_path(monkeypatch, tmp_path):
    text = _language_lines(
        monkeypatch, tmp_path, variable=None, stored={"lang": "en", "source": "system"}
    )
    assert text.startswith("Language:         en (preference; ")
    assert str(tmp_path / "language.json") in text
    assert "follow the system again" not in text


def test_doctor_warns_about_an_invalid_variable(monkeypatch, tmp_path):
    text = _language_lines(
        monkeypatch, tmp_path, variable="english", stored={"lang": "es", "source": "system"}
    )
    assert text.startswith("Idioma:           es (preferencia; ")
    assert "aviso: `LOCAL_DELEGATE_LANG` vale «english», que no es válido" in text


def test_d11_remedy_when_the_stored_language_came_from_the_variable(monkeypatch, tmp_path):
    text = _language_lines(
        monkeypatch, tmp_path, variable=None, stored={"lang": "es", "source": "variable"}
    )
    path = tmp_path / "language.json"
    assert (
        f"para volver a seguir al sistema, borra `{path}` y ejecuta `local-delegate install`"
        in text
    )


@pytest.mark.parametrize("source", ["system", "fallback", None, "bogus"])
def test_no_d11_remedy_otherwise(source, monkeypatch, tmp_path):
    stored = {"lang": "es"} if source is None else {"lang": "es", "source": source}
    text = _language_lines(monkeypatch, tmp_path, variable=None, stored=stored)
    assert "volver a seguir al sistema" not in text


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"lang": "es", "source": "variable"}, "variable"),
        ({"lang": "en", "source": "system"}, "system"),
        ({"lang": "en", "source": "fallback"}, "fallback"),
        ({"lang": "en", "source": "preference"}, None),
        ({"lang": "en"}, None),
    ],
)
def test_resolve_language_reports_the_stored_source(stored, expected, tmp_path):
    (tmp_path / hook_common.LANGUAGE_PREFERENCE_FILE).write_text(
        json.dumps(stored), encoding="utf-8"
    )
    result = hook_common.resolve_language(Path(tmp_path), env={}, platform="linux")
    assert result.source == "preference"
    assert result.stored_source == expected


def test_the_pending_fragments_still_live_in_their_modules():
    """Cuando B1c o B2 traduzcan uno de estos textos, el literal sale de su módulo y esto falla."""
    package = Path(checks.__file__).parent
    for fragment, module in PENDING_FRAGMENTS.items():
        assert fragment in (package / module).read_text(encoding="utf-8"), (fragment, module)
