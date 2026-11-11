"""The local map of project names, `LOG_DIR/project-names.json` (dashboard-project-filter).

`hook_common.project_fields` writes `hash → directory name` where and when it computes the hash,
in the `LOG_DIR` it is given (the process's by default, D12 of the earlier change). The map is
read with every guard (missing, corrupt, too big, bad entries), has a cap of entries, is replaced
whole (never half written) and survives writers in several threads and several processes without
losing a name one of them reported as written. `backfill_project_names` names the hashes of old
rows from the directory names of the projects root, without reading a transcript and without
creating a salt.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from local_delegate.resources.hooks import hook_common as common

HOOK_COMMON = Path(common.__file__)
SALT = "cd" * 32
TIMEOUT_S = 120


@pytest.fixture
def logs(tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    folder.mkdir()
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(folder))
    monkeypatch.setattr(common, "_NAMES_SEEN", {})
    monkeypatch.setattr(common, "_SALTS", {})
    monkeypatch.setattr(common, "_SELF_ENTRIES", {})
    return folder


def _map(folder: Path) -> dict:
    return json.loads((folder / common.PROJECT_NAMES_FILE).read_text(encoding="utf-8"))["names"]


def _hash(n: int) -> str:
    return f"{n:016x}"


# --- Written where the hash is computed -----------------------------------------------------------


def test_project_fields_writes_the_name_of_its_hash_and_the_fields_keep_no_name(logs):
    fields = common.project_fields("D--work-Shop")
    assert set(fields) == {"caller_project", "caller_project_kind"}
    assert "shop" not in json.dumps(fields).lower()
    assert _map(logs) == {fields["caller_project"]: "D--work-Shop"}
    assert common.read_project_names() == _map(logs)


def test_project_identity_writes_into_the_process_log_dir_not_elsewhere(logs, tmp_path):
    root = tmp_path / "projects"
    transcript = root / "D--work-shop" / "x.jsonl"
    other = tmp_path / "elsewhere"
    fields = common.project_identity(str(transcript), root=root)
    assert _map(logs) == {fields["caller_project"]: "D--work-shop"}
    assert not other.exists()
    # With an explicit `directory` (the backfill's), the map goes with the salt to that folder.
    other.mkdir()
    fields_there = common.project_identity(str(transcript), root=root, directory=other)
    assert _map(other) == {fields_there["caller_project"]: "D--work-shop"}


def test_without_a_salt_there_is_no_hash_and_no_name(logs, monkeypatch):
    monkeypatch.setattr(common, "project_salt", lambda directory=None: None)
    assert common.project_fields("D--work-shop") == {"caller_project_kind": "other"}
    assert not (logs / common.PROJECT_NAMES_FILE).exists()


def test_a_hash_keeps_its_first_name_and_is_written_once(logs, monkeypatch):
    assert common.record_project_name(_hash(1), "D--work-Shop")
    assert not common.record_project_name(_hash(1), "D--work-shop")  # same hash, other case
    assert _map(logs) == {_hash(1): "D--work-Shop"}
    writes = []
    real = common._write_names_atomically
    monkeypatch.setattr(
        common, "_write_names_atomically", lambda p, n: writes.append(1) or real(p, n)
    )
    for _ in range(5):
        common.record_project_name(_hash(1), "D--work-Shop")
    assert writes == []  # the process remembers it: the hot path does not rewrite


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "a\x00b",
        "line\nbreak",
        "tab\there",
        "c1\x85x",
        "sep\u2028x",
        "bidi\u202ex",
        "iso\u2066x",
        "zwsp\u200bx",
        "soft\u00adhyphen",
        "x" * 256,
        7,
        None,
    ],
)
def test_an_invalid_name_or_hash_is_not_recorded(logs, name):
    assert not common.record_project_name(_hash(1), name)
    assert not common.record_project_name("NOT-A-HASH", "D--ok")
    assert not common.record_project_name(_hash(1) + "\n", "D--ok")
    assert not common.is_project_hash(_hash(1) + "\n")
    assert not (logs / common.PROJECT_NAMES_FILE).exists()


def test_a_hostile_but_valid_name_is_stored_as_text(logs):
    hostile = '<img src=x onerror="alert(1)">&\'"'
    assert common.record_project_name(_hash(2), hostile)
    assert common.read_project_names() == {_hash(2): hostile}


# --- Reading with its guards ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"{not json",
        b"[1, 2]",
        b'{"names": []}',
        b'{"names": "x"}',
        b"\xff\xfe\x00\x01",
        b"[" * 100_000,
        b'{"names": {}}' + b" " * (common.PROJECT_NAMES_MAX_BYTES),
    ],
)
def test_a_corrupt_or_too_big_map_reads_empty_and_the_next_write_repairs_it(logs, content):
    (logs / common.PROJECT_NAMES_FILE).write_bytes(content)
    assert common.read_project_names() == {}
    assert common.record_project_name(_hash(3), "D--work-shop")
    assert _map(logs) == {_hash(3): "D--work-shop"}


def test_a_map_unreadable_for_a_moment_is_never_written_over(logs, monkeypatch):
    """Mutant: the writer reads under the lock with the lenient reader, gets `{}` from a map held
    by an antivirus, and writes a map with one name, losing the others."""
    common.record_project_name(_hash(1), "D--p1")
    common.record_project_name(_hash(2), "D--p2")
    target = str(logs / common.PROJECT_NAMES_FILE)
    real_open = open

    def held(path, *args, **kwargs):
        if str(path) == target:
            raise PermissionError(13, "held by another program")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(common, "open", held, raising=False)
    assert not common.record_project_name(_hash(3), "D--p3")
    assert common.backfill_project_names({_hash(4)}, directory=logs) == 0
    assert common.read_project_names() == {}  # the lenient reader: the panel just shows no names
    monkeypatch.setattr(common, "open", real_open, raising=False)
    assert _map(logs) == {_hash(1): "D--p1", _hash(2): "D--p2"}
    assert common.record_project_name(_hash(3), "D--p3")  # once readable, it is written


def test_a_map_too_big_to_write_is_not_retried_on_every_call(logs, monkeypatch):
    monkeypatch.setattr(common, "PROJECT_NAMES_MAX_BYTES", 10)
    calls = []
    real = common._write_names_atomically
    monkeypatch.setattr(
        common, "_write_names_atomically", lambda p, n: calls.append(1) or real(p, n)
    )
    assert not common.record_project_name(_hash(1), "D--a-long-enough-name")
    assert not common.record_project_name(_hash(1), "D--a-long-enough-name")
    assert calls == [1]


def test_bad_entries_are_dropped_on_reading(logs):
    names = {_hash(1): "ok", "ABCDEF0123456789": "upper", _hash(2): 5, _hash(3): "a\x07b"}
    (logs / common.PROJECT_NAMES_FILE).write_text(json.dumps({"names": names}), encoding="utf-8")
    assert common.read_project_names() == {_hash(1): "ok"}


def test_the_map_has_a_cap_of_entries(logs, monkeypatch):
    monkeypatch.setattr(common, "PROJECT_NAMES_MAX_ENTRIES", 3)
    for n in range(3):
        assert common.record_project_name(_hash(n), f"D--p{n}")
    assert not common.record_project_name(_hash(9), "D--p9")
    assert len(_map(logs)) == 3 and _hash(9) not in _map(logs)


def test_the_map_is_only_readable_by_its_user(logs):
    common.record_project_name(_hash(1), "D--p1")
    if os.name != "nt":
        assert (logs / common.PROJECT_NAMES_FILE).stat().st_mode & 0o077 == 0
    assert not list(logs.glob(".project-names.*.tmp"))  # no temporary file is left behind


def test_a_busy_lock_writes_nothing_and_a_later_call_retries(logs, monkeypatch):
    lock = common._open_shared(logs / (common.PROJECT_NAMES_FILE + ".lock"), os.O_RDWR)
    monkeypatch.setattr(common, "PROJECT_NAMES_LOCK_WAIT_S", 0.05)
    try:
        holder_ready = threading.Event()
        release = threading.Event()

        def hold():
            with common._exclusive(lock, 1.0) as locked:
                assert locked
                holder_ready.set()
                release.wait(5)

        holder = threading.Thread(target=hold)
        holder.start()
        holder_ready.wait(5)
        assert not common.record_project_name(_hash(4), "D--p4")
        release.set()
        holder.join(5)
    finally:
        os.close(lock)
    assert common.record_project_name(_hash(4), "D--p4")
    assert _map(logs) == {_hash(4): "D--p4"}


# --- Concurrency ----------------------------------------------------------------------------------


def test_threads_never_lose_a_name_they_reported_as_written(logs):
    written: list[str] = []
    failed: list[tuple[str, str]] = []
    guard = threading.Lock()

    def worker(t: int) -> None:
        for i in range(15):
            h, name = _hash(t * 100 + i), f"D--t{t}-{i}"
            ok = common.record_project_name(h, name)
            with guard:
                (written.append(h) if ok else failed.append((h, name)))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(TIMEOUT_S)
    stored = _map(logs)
    assert set(written) <= set(stored), "a reported write was lost"
    for h, name in failed:  # a busy lock writes nothing; the next call writes it
        common._NAMES_SEEN.clear()
        assert common.record_project_name(h, name) or h in _map(logs)
    assert len(_map(logs)) == 90


_WORKER = """
import importlib.util, json, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("hook_common", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
directory, base, start = Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
deadline = time.monotonic() + 60
while not start.exists() and time.monotonic() < deadline:
    time.sleep(0.002)  # the barrier: every process writes at the same moment
done = []
for i in range(30):
    h = f"{base + i:016x}"
    if module.record_project_name(h, f"D--proc-{base + i}", directory=directory):
        done.append(h)
print(json.dumps(done))
"""


def test_processes_never_lose_a_name_they_reported_as_written(logs, tmp_path):
    """Several processes (the daemon, the hooks, the backfill) adding names at the same moment:
    the map stays valid JSON and every name a process reported as written is in it."""
    script = tmp_path / "worker.py"
    script.write_text(_WORKER, encoding="utf-8")
    start = tmp_path / "start"
    procs = [
        subprocess.Popen(
            [sys.executable, "-I", str(script), str(HOOK_COMMON), str(logs), str(base), str(start)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for base in (1000, 2000, 3000, 4000)
    ]
    time.sleep(1.5)  # let the four import the module and wait at the barrier
    start.write_text("go", encoding="utf-8")
    reported: list[str] = []
    for proc in procs:
        out, err = proc.communicate(timeout=TIMEOUT_S)
        assert proc.returncode == 0, err.decode("utf-8", "replace")
        reported += json.loads(out)
    stored = _map(logs)
    assert reported, "guard: some process wrote"
    assert set(reported) <= set(stored), "a reported write was lost"
    assert all(stored[h] == f"D--proc-{int(h, 16)}" for h in stored)


# --- Backfill of the old rows ---------------------------------------------------------------------


def _root(tmp_path: Path, names: list[str]) -> Path:
    root = tmp_path / "projects"
    for name in names:
        (root / name).mkdir(parents=True)
    return root


def test_the_backfill_names_only_the_hashes_of_the_log(logs, tmp_path):
    (logs / common.PROJECT_SALT_FILE).write_text(SALT, encoding="ascii")
    root = _root(tmp_path, ["D--work-shop", "D--work-api", "D--never-delegated"])
    (root / "D--work-shop" / "s.jsonl").write_text("SECRET-CONTENT", encoding="utf-8")
    wanted = {common.project_hash("D--work-shop", SALT), common.project_hash("D--work-api", SALT)}
    added = common.backfill_project_names(wanted | {_hash(77)}, root=root, directory=logs)
    assert added == 2
    stored = _map(logs)
    assert stored == {
        common.project_hash("D--work-shop", SALT): "D--work-shop",
        common.project_hash("D--work-api", SALT): "D--work-api",
    }
    assert "SECRET" not in json.dumps(stored)
    # The name is the one `project_fields` would write today for the same directory.
    common._NAMES_SEEN.clear()
    assert common.project_fields("D--work-shop", directory=logs)["caller_project"] in stored


def test_the_backfill_without_a_salt_does_nothing_and_creates_none(logs, tmp_path):
    root = _root(tmp_path, ["D--work-shop"])
    assert common.backfill_project_names({_hash(1)}, root=root, directory=logs) == 0
    assert not (logs / common.PROJECT_SALT_FILE).exists()
    assert not (logs / common.PROJECT_NAMES_FILE).exists()


def test_the_backfill_keeps_the_names_already_there(logs, tmp_path):
    (logs / common.PROJECT_SALT_FILE).write_text(SALT, encoding="ascii")
    shop = common.project_hash("D--work-shop", SALT)
    common.record_project_name(shop, "D--work-SHOP")
    root = _root(tmp_path, ["D--work-shop"])
    assert common.backfill_project_names({shop}, root=root, directory=logs) == 0
    assert _map(logs) == {shop: "D--work-SHOP"}


def test_the_backfill_stops_at_its_budget_and_its_cap(logs, tmp_path, monkeypatch):
    (logs / common.PROJECT_SALT_FILE).write_text(SALT, encoding="ascii")
    names = [f"D--p{n:02d}" for n in range(10)]
    root = _root(tmp_path, names)
    wanted = {common.project_hash(n, SALT) for n in names}
    ticks = iter(range(1000))
    assert (
        common.backfill_project_names(
            wanted, root=root, directory=logs, clock=lambda: next(ticks), budget_s=0
        )
        <= 1
    )
    monkeypatch.setattr(common, "PROJECT_NAMES_BACKFILL_MAX_DIRS", 3)
    (logs / common.PROJECT_NAMES_FILE).unlink(missing_ok=True)
    assert common.backfill_project_names(wanted, root=root, directory=logs) <= 3


def test_the_backfill_never_raises(logs, tmp_path):
    (logs / common.PROJECT_SALT_FILE).write_text(SALT, encoding="ascii")
    assert common.backfill_project_names({_hash(1)}, root=tmp_path / "missing", directory=logs) == 0
    assert common.backfill_project_names(None, directory=logs) == 0  # type: ignore[arg-type]


def test_the_backfill_says_whether_its_pass_was_complete(logs, tmp_path, monkeypatch):
    (logs / common.PROJECT_SALT_FILE).write_text(SALT, encoding="ascii")
    root = _root(tmp_path, ["D--work-shop"])
    shop = common.project_hash("D--work-shop", SALT)
    outcome: dict = {}
    assert (
        common.backfill_project_names({_hash(5)}, root=root, directory=logs, outcome=outcome) == 0
    )
    assert outcome == {"complete": True}  # looked everywhere, nothing to name: settled
    real = common._add_project_names
    monkeypatch.setattr(common, "_add_project_names", lambda path, found: None)  # busy lock
    assert common.backfill_project_names({shop}, root=root, directory=logs, outcome=outcome) == 0
    assert outcome == {"complete": False}
    monkeypatch.setattr(common, "_add_project_names", real)
    ticks = iter(range(1000))
    common.backfill_project_names(
        {shop}, root=root, directory=logs, outcome=outcome, clock=lambda: next(ticks), budget_s=0
    )
    assert outcome == {"complete": False}  # the budget was spent before the directory
    assert common.backfill_project_names({shop}, root=root, directory=logs, outcome=outcome) == 1
    assert outcome == {"complete": True}
