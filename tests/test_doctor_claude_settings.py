"""The `config.claude_settings` check of `doctor` (SDD backlog-minor-leftovers, L2).

- **REQ-012:** a `~/.claude/settings.json` that is not valid UTF-8 is a `warn` with its path and
  the cause, even when its content parses as JSON (`read_text` decodes with `errors="replace"`,
  so the other checks read it without noticing). UTF-8 with a BOM stays valid (REQ-026 of
  `retire-legacy-aliases`).
- **REQ-013:** the copy that the retired-names migration leaves next to `settings.json`
  (`settings.json.retired-names.bak` and its dated variants) is a `warn` with its path, a note
  that it may hold `env` keys and the advice to delete it. Its content is never printed. Without
  a copy, nothing about it shows up.

The HOME is always a `tmp_path`: the real `~/.claude` is never read.
"""

from __future__ import annotations

import json

from conftest import make_home
from test_checks import make_ctx, result_for

from local_delegate import checks, i18n, install

CHECK_ID = "config.claude_settings"
# A value that must never reach the output: it stands for an `env` key kept in the copy.
SECRET_MARK = "sk-never-print-this-0123456789"


def _settings(home):
    return home / ".claude" / "settings.json"


def _write_latin1_settings(home):
    """A `settings.json` that is valid JSON but saved as Latin-1 (`é` is the byte 0xE9)."""
    data = json.loads(_settings(home).read_text(encoding="utf-8"))
    data["note"] = "café"
    _settings(home).write_bytes(json.dumps(data, ensure_ascii=False).encode("latin-1"))


def test_the_check_is_registered_in_the_environment_group():
    check = next(c for c in checks.CHECKS if c.id == CHECK_ID)
    assert check.group == "environment"
    for lang in ("es", "en"):
        title = i18n.t_lang(lang, check.title_key)
        assert title and title != check.title_key, f"title missing in {lang}"


def test_a_utf8_settings_without_copies_is_ok(tmp_path):
    home = make_home(tmp_path)
    result = result_for(CHECK_ID, make_ctx(home))
    assert result.status == checks.OK, result.detail
    # REQ-013: without a copy, nothing about it shows up.
    assert install.RETIRED_NAMES_BACKUP not in result.detail
    assert result.fix_hint == ""


def test_utf8_with_bom_is_still_valid(tmp_path):
    home = make_home(tmp_path)
    raw = _settings(home).read_bytes()
    _settings(home).write_bytes(b"\xef\xbb\xbf" + raw)
    result = result_for(CHECK_ID, make_ctx(home))
    assert result.status == checks.OK, result.detail


def test_a_non_utf8_settings_that_parses_as_json_is_a_warning(tmp_path):
    home = make_home(tmp_path)
    _write_latin1_settings(home)
    # Guard: the file really is valid JSON once decoded as Latin-1, and the tolerant reader the
    # other checks use reads it without complaint. Otherwise this test would prove nothing.
    json.loads(_settings(home).read_text(encoding="latin-1"))
    data, reason = checks.read_json(_settings(home))
    assert reason is None and isinstance(data, dict)

    result = result_for(CHECK_ID, make_ctx(home))
    assert result.status == checks.WARN, result.detail
    assert str(_settings(home)) in result.detail
    # The cause: the offending byte, so the user can find it.
    assert "0xe9" in result.detail.lower()
    assert result.fix_hint


def test_no_settings_json_is_ok(tmp_path):
    home = make_home(tmp_path, complete=False)
    assert not _settings(home).exists()
    result = result_for(CHECK_ID, make_ctx(home))
    assert result.status == checks.OK, result.detail


def test_without_claude_code_it_is_unknown_like_the_other_claude_checks(tmp_path):
    home = make_home(tmp_path, claude=False)
    result = result_for(CHECK_ID, make_ctx(home))
    assert result.status == checks.UNKNOWN


def test_the_migration_copy_is_a_warning_without_its_content(tmp_path):
    home = make_home(tmp_path)
    backup = home / ".claude" / f"{install.RETIRED_NAMES_BACKUP}.bak"
    backup.write_text(json.dumps({"env": {"SOME_TOKEN": SECRET_MARK}}), encoding="utf-8")

    result = result_for(CHECK_ID, make_ctx(home))
    assert result.status == checks.WARN, result.detail
    assert str(backup) in result.detail
    assert "env" in result.detail
    assert result.fix_hint, "it must suggest deleting the copy"
    assert SECRET_MARK not in result.detail + result.fix_hint


def test_the_dated_copies_are_listed_too(tmp_path):
    """`_retired_names_backup` writes `….<stamp>.bak` and `….<stamp>-N.bak` when the first exists."""
    home = make_home(tmp_path)
    claude = home / ".claude"
    names = [
        f"{install.RETIRED_NAMES_BACKUP}.20261021120000.bak",
        f"{install.RETIRED_NAMES_BACKUP}.20261021120000-1.bak",
    ]
    for name in names:
        (claude / name).write_text("{}", encoding="utf-8")

    result = result_for(CHECK_ID, make_ctx(home))
    assert result.status == checks.WARN, result.detail
    for name in names:
        assert str(claude / name) in result.detail


def test_the_copy_the_migration_really_writes_is_detected(tmp_path):
    """The name comes from `install`, not from a literal: if it changes, this test follows it."""
    home = make_home(tmp_path)
    settings = _settings(home)
    written = install._retired_names_backup(settings, settings.read_bytes(), "20261021120000")
    written_again = install._retired_names_backup(settings, settings.read_bytes(), "20261021120000")

    detail = result_for(CHECK_ID, make_ctx(home)).detail
    assert str(written) in detail
    assert str(written_again) in detail


def test_deleting_the_copy_removes_the_warning(tmp_path):
    home = make_home(tmp_path)
    backup = home / ".claude" / f"{install.RETIRED_NAMES_BACKUP}.bak"
    backup.write_text("{}", encoding="utf-8")
    assert result_for(CHECK_ID, make_ctx(home)).status == checks.WARN
    backup.unlink()
    assert result_for(CHECK_ID, make_ctx(home)).status == checks.OK


def test_both_problems_are_reported_together(tmp_path):
    home = make_home(tmp_path)
    _write_latin1_settings(home)
    backup = home / ".claude" / f"{install.RETIRED_NAMES_BACKUP}.bak"
    backup.write_text("{}", encoding="utf-8")

    result = result_for(CHECK_ID, make_ctx(home))
    assert result.status == checks.WARN
    # The byte and not the path: the path of `settings.json` is a prefix of the copy's path.
    assert "0xe9" in result.detail.lower()
    assert str(backup) in result.detail
    assert len(result.fix_hint.split("; ")) == 2


def test_the_texts_exist_in_both_languages(tmp_path):
    home = make_home(tmp_path)
    _write_latin1_settings(home)
    (home / ".claude" / f"{install.RETIRED_NAMES_BACKUP}.bak").write_text("{}", encoding="utf-8")
    details = {}
    for lang in ("es", "en"):
        with i18n.override(lang):
            result = checks._probe_claude_settings(make_ctx(home))
        assert "doctor.probe." not in result.detail + result.fix_hint, "untranslated key"
        details[lang] = result.detail
    assert details["es"] != details["en"]
