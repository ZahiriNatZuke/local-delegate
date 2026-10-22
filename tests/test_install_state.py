"""install_state: what `install` wrote, so `doctor`/`update`/`uninstall` read it instead of guessing.

REQ-007 (SDD claude-plugin-and-mods, F1-delivery-core). The file follows the same write rule as
`language.json`: with a simulated HOME it is only written when `LOCAL_DELEGATE_LOG_DIR` chose the
data directory.
"""

from __future__ import annotations

import json

from local_delegate import install_state


def test_roundtrip(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    state = install_state.new_state("plugin", "0.40.0")
    state = install_state.with_piece(
        state, "plugin", now="2026-10-21T10:00:00Z", id="local-delegate@local-delegate"
    )
    state = install_state.with_piece(state, "marketplace", now="2026-10-21T10:00:00Z")

    written = install_state.save(home, state)

    assert written is not None and written.name == install_state.STATE_FILE
    loaded = install_state.load(home)
    assert loaded == state
    assert install_state.delivery(loaded) == "plugin"
    assert install_state.piece(loaded, "plugin") == {
        "at": "2026-10-21T10:00:00Z",
        "id": "local-delegate@local-delegate",
    }
    assert install_state.piece(loaded, "desktop_entry") is None
    # Removing a piece leaves the others.
    trimmed = install_state.without_piece(loaded, "plugin")
    assert install_state.piece(trimmed, "plugin") is None
    assert install_state.piece(trimmed, "marketplace") is not None


def test_missing_state_means_unknown_not_empty(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    # No file: "I don't know", never an empty state that would read as "install wrote nothing".
    assert install_state.load(home) is None
    assert install_state.delivery(None) is None
    assert install_state.piece(None, "plugin") is None

    # A corrupt file is also "I don't know".
    path = install_state.path(home)
    path.write_text("{not json", encoding="utf-8")
    assert install_state.load(home) is None
    path.write_text(json.dumps(["a", "list"]), encoding="utf-8")
    assert install_state.load(home) is None


def test_state_follows_language_dir_rule(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    state = install_state.new_state("settings", "0.40.0")

    # Simulated HOME without LOCAL_DELEGATE_LOG_DIR: nothing is written, like language.json.
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)
    assert install_state.path(home) is None
    assert install_state.save(home, state) is None
    assert install_state.load(home) is None
    assert not list(tmp_path.rglob(install_state.STATE_FILE))

    # With the variable, it goes to the data directory (config.LOG_DIR), not into the HOME.
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path))
    written = install_state.save(home, state)
    assert written == tmp_path / install_state.STATE_FILE
    assert install_state.load(home) == state

    # An explicit data_dir wins, as in install.data_dir_for.
    other = tmp_path / "other"
    assert install_state.save(home, state, data_dir=other) == other / install_state.STATE_FILE


def test_explicit_delivery_is_optional_and_keeps_schema():
    """A state written before the mark reads as "not chosen"; setting it keeps `schema` at 1."""
    old = install_state.new_state("settings", "0.39.0")
    assert install_state.EXPLICIT_FIELD not in old
    assert install_state.delivery_explicit(old) is False
    assert install_state.delivery_explicit(None) is False

    marked = install_state.with_delivery_explicit(old, True)
    assert install_state.delivery_explicit(marked) is True
    assert marked["schema"] == install_state.SCHEMA_VERSION == 1
    assert install_state.EXPLICIT_FIELD not in old  # a copy, not in place

    removed = install_state.with_delivery_explicit(marked, False)
    assert removed == old
