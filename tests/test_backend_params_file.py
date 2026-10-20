"""File, atomic writing, cache and resolution of the per-role parameters.

SDD `backend-extra-params`, T6: REQ-001 (file), REQ-002 (atomic writing under lock), REQ-008
(precedence), REQ-009 (cache), REQ-011 (`set`/`unset`/`reset` rules) and REQ-023 (warning of `set`).
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from local_delegate import backend_params as bp
from local_delegate import config, llamaswap_config

VARIABLE = "LOCAL_DELEGATE_BACKEND_PARAMS"
SENTINELS = ("SENTINEL-7Q", "SENTINEL-8R")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)
    # The context check reads the llama-swap config; a known context keeps it deterministic.
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (32768, False))
    bp._forget()
    yield
    bp._forget()


def _write_raw(text: str) -> None:
    bp.path().write_text(text, encoding="utf-8")


def _write_doc(roles: dict) -> None:
    _write_raw(json.dumps({"version": 1, "roles": roles}))


def _codes(warnings) -> list[tuple[str, str, str]]:
    return [(w.role, w.key, w.code) for w in warnings]


def test_path_is_in_log_dir(tmp_path):
    assert bp.path() == config.LOG_DIR / "backend-params.json" == tmp_path / "backend-params.json"
    assert bp.path(tmp_path / "x") == tmp_path / "x" / "backend-params.json"


# --- load (REQ-001) -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("absent", []),
        ("empty", []),
        ("blank", []),
        ("empty_roles", []),
        ("broken", [("", "", "file_unreadable")]),
        ("not_an_object", [("", "", "file_unreadable")]),
        ("roles_not_an_object", [("", "", "file_unreadable")]),
        ("not_utf8", [("", "", "file_unreadable")]),
        ("version2", [("", "", "file_bad_version")]),
        ("version_true", [("", "", "file_bad_version")]),
        ("no_version", [("", "", "file_bad_version")]),
        ("too_large", [("", "", "file_too_large")]),
        ("unknown_role", [("foo", "top_k", "unknown_role")]),
    ],
)
def test_load_tolerates(case, expected):
    file = bp.path()
    good = {"code": {"top_k": 20}}
    if case == "empty":
        file.write_bytes(b"")
    elif case == "blank":
        file.write_text("  \n", encoding="utf-8")
    elif case == "empty_roles":
        _write_doc({})
    elif case == "broken":
        _write_raw('{"version": 1, "roles": {')
    elif case == "not_an_object":
        _write_raw("[1, 2]")
    elif case == "roles_not_an_object":
        _write_raw('{"version": 1, "roles": [1]}')
    elif case == "not_utf8":
        file.write_bytes(b'{"version": 1, "roles": {"\xff": {}}}')
    elif case == "version2":
        _write_raw(json.dumps({"version": 2, "roles": good}))
    elif case == "version_true":
        _write_raw(json.dumps({"version": True, "roles": good}))
    elif case == "no_version":
        _write_raw(json.dumps({"roles": good}))
    elif case == "too_large":
        doc = json.dumps({"version": 1, "roles": good, "pad": "x" * bp.MAX_FILE_BYTES})
        _write_raw(doc)
    elif case == "unknown_role":
        _write_doc({"foo": {"top_k": 20}, "code": {"top_k": 20}})
    result = bp.load()
    assert _codes(result.warnings) == expected
    if case == "unknown_role":
        assert result.roles == {"code": {"top_k": 20}}  # the known role survives
    else:
        assert result.roles == {}


def test_load_exactly_64kb_is_read():
    head = json.dumps({"version": 1, "roles": {"code": {"top_k": 20}}, "pad": ""})
    doc = head[:-2] + "x" * (bp.MAX_FILE_BYTES - len(head)) + head[-2:]
    assert len(doc.encode()) == bp.MAX_FILE_BYTES
    _write_raw(doc)
    assert bp.load() == ({"code": {"top_k": 20}}, [])


def test_load_accepts_bom():
    bp.path().write_bytes(b"\xef\xbb\xbf" + json.dumps({"version": 1, "roles": {}}).encode())
    assert bp.load() == ({}, [])


def test_load_never_raises(monkeypatch):
    def boom(*_args):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(bp, "_read_document", boom)
    assert _codes(bp.load().warnings) == [("", "", "file_unreadable")]


# --- write (REQ-002) ------------------------------------------------------------------------------


def _temporaries() -> list[str]:
    return [p.name for p in bp.path().parent.iterdir() if p.name.endswith(".tmp")]


def test_failed_replace_keeps_original_and_no_temp(monkeypatch):
    assert bp.set_value("code", "top_k", "20")[0]
    before = bp.path().read_bytes()

    def failing_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(bp.os, "replace", failing_replace)
    ok, code, warnings = bp.set_value("code", "top_k", "30")
    assert (ok, code) == (False, "file_write_failed")
    assert _codes(warnings) == [("", "", "file_write_failed")]
    assert bp.path().read_bytes() == before
    assert _temporaries() == []

    with pytest.raises(OSError, match="disk full"):  # `write` itself lets the error through
        bp.write(lambda doc: doc["roles"].update({"code": {"top_k": 40}}))
    assert bp.path().read_bytes() == before
    assert _temporaries() == []


def test_concurrent_sets_keep_both_keys():
    barrier = threading.Barrier(2)
    results = []

    def one(key: str, value: str) -> None:
        barrier.wait()
        for _ in range(10):
            results.append(bp.set_value("code", key, value)[0])

    threads = [
        threading.Thread(target=one, args=("top_k", "20")),
        threading.Thread(target=one, args=("min_p", "0.1")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert results == [True] * 20
    doc = json.loads(bp.path().read_text(encoding="utf-8"))
    assert doc == {"version": 1, "roles": {"code": {"top_k": 20, "min_p": 0.1}}} or doc == {
        "version": 1,
        "roles": {"code": {"min_p": 0.1, "top_k": 20}},
    }
    assert _temporaries() == []


def test_busy_lock_is_a_code(monkeypatch):
    from filelock import FileLock

    monkeypatch.setattr(bp, "LOCK_TIMEOUT", 0.05)
    with FileLock(str(bp.path().parent / bp.LOCK_NAME)):
        holder = threading.Thread(
            target=lambda: results.append(bp.set_value("code", "top_k", "20"))
        )
        results: list = []
        holder.start()
        holder.join(timeout=30)
    assert results[0][:2] == (False, "file_busy")
    assert not bp.path().exists()


@pytest.mark.parametrize("problem", ["broken", "version2", "too_large"])
def test_set_never_overwrites_a_file_load_ignores(problem):
    if problem == "broken":
        _write_raw("{ hand edit")
        code = "file_unreadable"
    elif problem == "version2":
        _write_raw(json.dumps({"version": 2, "roles": {}}))
        code = "file_bad_version"
    else:
        _write_raw(json.dumps({"version": 1, "pad": "x" * bp.MAX_FILE_BYTES}))
        code = "file_too_large"
    before = bp.path().read_bytes()
    assert bp.set_value("code", "top_k", "20")[:2] == (False, code)
    assert bp.path().read_bytes() == before


def test_written_file_shape():
    assert bp.set_value("code", "top_k", "20") == (True, None, [])
    text = bp.path().read_text(encoding="utf-8")
    assert json.loads(text) == {"version": 1, "roles": {"code": {"top_k": 20}}}
    assert text.endswith("}\n") and "\r" not in text


# --- set / unset / reset (REQ-003, REQ-011) -------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "key", "text", "code"),
    [
        ("foo", "top_k", "20", "unknown_role"),
        ("code", "foo", "SENTINEL-7Q", "unknown_key"),
        ("code", "model", "SENTINEL-7Q", "reserved_key"),
        ("code", "top_k", "SENTINEL-8R", "bad_type"),
        ("code", "top_p", "1.5", "out_of_range"),
    ],
)
def test_set_rejects_before_writing(role, key, text, code):
    _write_doc({"code": {"min_p": 0.1}})
    before = bp.path().read_bytes()
    mtime = bp.path().stat().st_mtime_ns
    ok, got, warnings = bp.set_value(role, key, text)
    assert (ok, got) == (False, code)
    assert bp.path().read_bytes() == before
    assert bp.path().stat().st_mtime_ns == mtime
    for warning in warnings:
        for sentinel in SENTINELS:
            assert sentinel not in repr(warning)


def test_set_rejects_thinking_without_budget():
    ok, code, warnings = bp.set_value("code", "enable_thinking", "on")
    assert (ok, code) == (False, "thinking_without_budget")
    assert _codes(warnings) == [("code", "enable_thinking", "thinking_without_budget")]
    assert not bp.path().exists()
    # A budget in another role does not count.
    assert bp.set_value("long", "reasoning_budget_tokens", "512")[0]
    assert bp.set_value("code", "enable_thinking", "on")[:2] == (False, "thinking_without_budget")
    # Turning it off needs no budget.
    assert bp.set_value("code", "enable_thinking", "off")[0]


def test_set_budget_then_thinking_ok():
    assert bp.set_value("code", "reasoning_budget_tokens", "512")[:2] == (True, None)
    assert bp.set_value("code", "enable_thinking", "on")[:2] == (True, None)
    resolved = bp.effective("code")
    assert resolved.values == {"enable_thinking": True, "reasoning_budget_tokens": 512}
    assert resolved.warnings == []


def test_set_thinking_accepts_budget_from_env(monkeypatch):
    monkeypatch.setenv(VARIABLE, "code.reasoning_budget_tokens=512")
    assert bp.set_value("code", "enable_thinking", "on")[:2] == (True, None)


def test_unset_budget_rejected_while_thinking_on():
    bp.set_value("code", "reasoning_budget_tokens", "512")
    bp.set_value("code", "enable_thinking", "on")
    before = bp.path().read_bytes()
    ok, code, warnings = bp.unset("code", "reasoning_budget_tokens")
    assert (ok, code) == (False, "thinking_without_budget")
    assert _codes(warnings) == [("code", "reasoning_budget_tokens", "thinking_without_budget")]
    assert bp.path().read_bytes() == before
    # Control: with reasoning off first, the same `unset` goes through.
    assert bp.unset("code", "enable_thinking")[0]
    assert bp.unset("code", "reasoning_budget_tokens") == (True, None, [])
    assert json.loads(bp.path().read_text(encoding="utf-8"))["roles"] == {}


@pytest.mark.parametrize("scope", ["role", "all"])
def test_reset_empties_role_with_thinking_on(scope):
    # User decision 12: `reset` takes the role whole, reasoning and budget together, without asking
    # for `unset <role> enable_thinking` first.
    assert bp.set_value("code", "reasoning_budget_tokens", "512")[0]
    assert bp.set_value("code", "enable_thinking", "on")[0]
    assert bp.set_value("long", "top_k", "20")[0]
    assert bp.reset("code" if scope == "role" else None) == (True, None, [])
    roles = json.loads(bp.path().read_text(encoding="utf-8"))["roles"]
    assert roles == ({"long": {"top_k": 20}} if scope == "role" else {})
    assert bp.effective("code").values == {}


def test_unset_and_reset_other_cases():
    assert bp.unset("foo", "top_k")[:2] == (False, "unknown_role")
    assert bp.reset("foo")[:2] == (False, "unknown_role")
    assert bp.unset("code", "top_k") == (True, None, [])  # a missing key is not an error
    # A hand-edited invalid key can be cleaned with `unset`.
    _write_doc({"code": {"top_k": 20, "foo": 1}})
    assert bp.unset("code", "foo")[0]
    assert json.loads(bp.path().read_text(encoding="utf-8"))["roles"] == {"code": {"top_k": 20}}


# --- effective (REQ-008, REQ-009, REQ-011, REQ-006/007) -------------------------------------------


def test_env_wins_key_by_key(monkeypatch):
    _write_doc({"code": {"top_k": 20, "min_p": 0.1}})
    monkeypatch.setenv(VARIABLE, "code.top_k=40")
    resolved = bp.effective("code")
    assert resolved.values == {"top_k": 40, "min_p": 0.1}
    assert resolved.source == {"top_k": "env", "min_p": "file"}
    assert bp.effective("long") == ({}, {}, [])


def test_file_change_seen_without_restart():
    bp.set_value("code", "top_k", "20")
    assert bp.effective("code").values == {"top_k": 20}
    bp.set_value("code", "min_p", "0.1")
    assert bp.effective("code").values == {"top_k": 20, "min_p": 0.1}
    bp.unset("code", "top_k")
    assert bp.effective("code").values == {"min_p": 0.1}


def test_env_change_seen_without_restart(monkeypatch):
    _write_doc({"code": {"top_k": 20}})
    assert bp.effective("code").values == {"top_k": 20}
    monkeypatch.setenv(VARIABLE, "code.top_k=30")
    assert bp.effective("code").values == {"top_k": 30}
    monkeypatch.delenv(VARIABLE)
    assert bp.effective("code").values == {"top_k": 20}


@pytest.mark.parametrize("how", ["set", "in_place"])
def test_same_size_rewrite_is_seen(how):
    """`top_k 20` → `30`: same size. `in_place` keeps the inode and moves `mtime` by 100 ns.

    `in_place` is the one that tells the key apart: with `os.replace` the inode changes too, so
    only a rewrite of the same file with a 100 ns step shows that the key uses `st_mtime_ns` and
    not the float `st_mtime` (which cannot hold 100 ns at today's dates).
    """
    assert bp.set_value("code", "top_k", "20")[0]
    file = bp.path()
    base = 1_700_000_000_000_000_000
    os.utime(file, ns=(base, base))
    assert bp.effective("code").values == {"top_k": 20}
    size = file.stat().st_size
    if how == "set":
        assert bp.set_value("code", "top_k", "30")[0]
        os.utime(file, ns=(base, base))  # even with the same mtime, the new inode is seen
    else:
        file.write_bytes(file.read_bytes().replace(b"20", b"30"))  # same file, same inode
        os.utime(file, ns=(base + 100, base + 100))
    assert file.stat().st_size == size
    assert bp.effective("code").values["top_k"] == 30


def test_cache_is_used(monkeypatch):
    _write_doc({"code": {"top_k": 20}})
    calls = []
    real = bp.load
    monkeypatch.setattr(bp, "load", lambda log_dir=None: calls.append(1) or real(log_dir))
    for role in bp.ROLES:
        bp.effective(role)
    bp.report()
    assert len(calls) == 1


@pytest.mark.parametrize("where", ["file", "env"])
def test_thinking_without_budget_from_file_and_env_is_dropped(monkeypatch, where):
    if where == "file":
        _write_doc({"code": {"enable_thinking": True, "top_k": 20}})
    else:
        monkeypatch.setenv(VARIABLE, "code.enable_thinking=on;code.top_k=20")
    resolved = bp.effective("code")
    assert resolved.values == {"top_k": 20}
    assert _codes(resolved.warnings) == [("code", "enable_thinking", "thinking_without_budget")]
    # With the budget in the other source, the effective pair is complete.
    if where == "file":
        monkeypatch.setenv(VARIABLE, "code.reasoning_budget_tokens=512")
    else:
        _write_doc({"code": {"reasoning_budget_tokens": 512}})
    resolved = bp.effective("code")
    assert resolved.values == {"top_k": 20, "enable_thinking": True, "reasoning_budget_tokens": 512}
    assert resolved.warnings == []


@pytest.mark.parametrize("where", ["file", "env"])
def test_file_and_env_drop_only_bad_key(monkeypatch, where):
    """REQ-006 and REQ-007: the bad key goes, the rest of the role stays, no value is shown."""
    if where == "file":
        _write_doc(
            {
                "code": {"top_k": 20, "foo": "SENTINEL-7Q"},
                "mechanical": {"top_p": 1.5, "min_p": 0.1},
            }
        )
        expected = {"code": {"top_k": 20}, "mechanical": {"min_p": 0.1}}
        codes = {("code", "foo", "unknown_key"), ("mechanical", "top_p", "out_of_range")}
    else:
        monkeypatch.setenv(
            VARIABLE,
            "code.foo=SENTINEL-7Q;code.top_k=SENTINEL-8R;code.min_p=0.1;mechanical.top_k=x",
        )
        expected = {"code": {"min_p": 0.1}, "mechanical": {}}
        codes = {
            ("code", "foo", "unknown_key"),
            ("code", "top_k", "bad_type"),
            ("mechanical", "top_k", "bad_type"),
        }
    for role, values in expected.items():
        assert bp.effective(role).values == values
    rows = bp.report()
    assert {c for row in rows for c in _codes(row.warnings)} == codes
    dumped = repr(rows) + repr([bp.effective(role) for role in bp.ROLES])
    dumped += " ".join(bp.warning_text(w) for row in rows for w in row.warnings)
    for sentinel in SENTINELS:
        assert sentinel not in dumped


def test_broken_file_warns_every_role_and_env_still_applies(monkeypatch):
    _write_raw("{ broken")
    monkeypatch.setenv(VARIABLE, "code.top_k=30")
    resolved = bp.effective("code")
    assert resolved.values == {"top_k": 30}
    assert resolved.source == {"top_k": "env"}
    assert _codes(resolved.warnings) == [("", "", "file_unreadable")]
    assert _codes(bp.effective("long").warnings) == [("", "", "file_unreadable")]


# --- context_warnings and report (REQ-023, REQ-003 show) ------------------------------------------


def test_set_context_warning_writes_anyway(monkeypatch):
    monkeypatch.setattr(llamaswap_config, "model_context_size", lambda model: (8192, False))
    # mechanical: ceil(20000 / 4) + 2048 + budget. 512 fits in 8192; 2048 does not.
    assert config.max_chars_for_role("mechanical") == 20000
    assert config.CHUNK_MAX_TOKENS == 2048
    assert bp.set_value("mechanical", "reasoning_budget_tokens", "512") == (True, None, [])
    assert bp.set_value("mechanical", "enable_thinking", "on") == (True, None, [])  # control
    ok, code, warnings = bp.set_value("mechanical", "reasoning_budget_tokens", "2048")
    assert (ok, code) == (True, None)
    assert _codes(warnings) == [("mechanical", "", "context_overflow")]
    assert bp.effective("mechanical").values["reasoning_budget_tokens"] == 2048  # written
    # Exactly at the limit it fits: 5000 + 2048 + 1144 = 8192.
    assert bp.set_value("mechanical", "reasoning_budget_tokens", "1144") == (True, None, [])
    assert _codes(bp.set_value("mechanical", "reasoning_budget_tokens", "1145")[2]) == [
        ("mechanical", "", "context_overflow")
    ]


def test_context_estimated_and_vision(monkeypatch):
    seen = []

    def estimate(model):
        seen.append(model)
        return (8192, True)

    monkeypatch.setattr(llamaswap_config, "model_context_size", estimate)
    bp.set_value("code", "reasoning_budget_tokens", "512")
    _, _, warnings = bp.set_value("code", "enable_thinking", "on")
    assert _codes(warnings) == [("code", "", "context_estimated")]
    assert seen[-1] == config.models_by_role()["code"]
    # vision is out of the check, and without reasoning there is nothing to check.
    bp.set_value("vision", "reasoning_budget_tokens", "8192")
    assert bp.set_value("vision", "enable_thinking", "on") == (True, None, [])
    assert bp.context_warnings("long") == []


def test_report_shape(monkeypatch):
    _write_doc({"code": {"top_k": 20}, "foo": {"min_p": 0.1}})
    monkeypatch.setenv(VARIABLE, "code.min_p=0.2;broken")
    rows = bp.report()
    assert [row.role for row in rows] == [*bp.ROLES, ""]
    code = rows[bp.ROLES.index("code")]
    assert code.values == {"top_k": 20, "min_p": 0.2}
    assert code.source == {"top_k": "file", "min_p": "env"}
    assert code.warnings == []
    assert _codes(rows[-1].warnings) == [
        ("foo", "min_p", "unknown_role"),
        ("", "broken", "malformed_entry"),
    ]
    # Without general warnings there is no "" row.
    monkeypatch.delenv(VARIABLE)
    _write_doc({"code": {"top_k": 20}})
    assert [row.role for row in bp.report()] == list(bp.ROLES)
