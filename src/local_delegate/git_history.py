"""Subjects of the last commits on HEAD, read from git's object store without running `git` (#548).

`local_commit_msg` follows the language of the repo's own commits. The reflog (`logs/HEAD`) only
records what was typed in one clone: a checkout that gets `main` through `git pull` has
`pull: Fast-forward` lines with no subject, and its few `commit:` lines can be months old. The
history itself lives in the commit objects, so this module walks HEAD's first-parent chain and
reads each commit's subject.

No `git` subprocess runs (the reason of #461: nothing in the repo's config or hooks may run). Every
file read here is disk input of an arbitrary repo, so each read is capped: the commits walked, the
inflated size of an object, the length of a delta chain and the number of pack files looked at. Any
surprise (a corrupt object, a SHA-256 repo, a missing ref) stops the walk; the caller then keeps the
reflog it used before.
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Self

MAX_COMMITS = 20
MAX_WALK = 200  # commits read at most, merges without a body included
MAX_OBJECT_BYTES = 1 << 20
MAX_DELTA_DEPTH = 50
MAX_PACKS = 64
_READ_CHUNK = 16_384
_SMALL_FILE = 4096
_PACKED_REFS_MAX_BYTES = 16 << 20

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_REF_NAME = re.compile(r"^refs/[A-Za-z0-9._/+-]+$")
_IDX_MAGIC = b"\xfftOc"
_OBJ_COMMIT, _OBJ_OFS_DELTA, _OBJ_REF_DELTA = 1, 6, 7
_OBJ_TYPES = {1: b"commit", 2: b"tree", 3: b"blob", 4: b"tag"}


class _Unreadable(Exception):
    """The object store did not give what git would have given; stop and fall back."""


def _regular_file(path: Path) -> bool:
    """Only regular files are opened: a FIFO or a device in a crafted `.git` would block or never
    end (`is_file` follows a symlink and says False for both)."""
    return path.is_file()


def _read_small(path: Path) -> str:
    if not _regular_file(path):
        raise FileNotFoundError(path)
    with path.open("rb") as handle:
        return handle.read(_SMALL_FILE).decode("utf-8", errors="strict").strip()


def _inflate(read_chunk, limit: int) -> bytes:
    """Inflate a zlib stream fed by `read_chunk()`; more than `limit` bytes is refused."""
    inflater = zlib.decompressobj()
    out = bytearray()
    while not inflater.eof:
        chunk = inflater.unconsumed_tail or read_chunk()
        if not chunk:
            raise _Unreadable  # truncated zlib stream
        out += inflater.decompress(chunk, limit + 1 - len(out))
        if len(out) > limit:
            raise _Unreadable  # object too large
    return bytes(out)


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    """A delta header size: 7 bits per byte, least significant first."""
    value = shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            raise _Unreadable  # bad delta header
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, pos


def _apply_delta(base: bytes, delta: bytes) -> bytes:
    src_size, pos = _varint(delta, 0)
    dst_size, pos = _varint(delta, pos)
    if src_size != len(base) or dst_size > MAX_OBJECT_BYTES:
        raise _Unreadable  # delta does not fit its base
    out = bytearray()
    while pos < len(delta):
        cmd = delta[pos]
        pos += 1
        if cmd & 0x80:
            offset = size = 0
            for bit in range(4):
                if cmd & (1 << bit):
                    offset |= delta[pos] << (8 * bit)
                    pos += 1
            for bit in range(3):
                if cmd & (1 << (4 + bit)):
                    size |= delta[pos] << (8 * bit)
                    pos += 1
            size = size or 0x10000
            if offset + size > len(base):
                raise _Unreadable  # delta copies outside its base
            out += base[offset : offset + size]
        elif cmd:
            out += delta[pos : pos + cmd]
            pos += cmd
        else:
            raise _Unreadable  # delta opcode 0
        if len(out) > dst_size:
            raise _Unreadable  # delta overflows its target
    if len(out) != dst_size:
        raise _Unreadable  # delta target size mismatch
    return bytes(out)


class _Pack:
    """One `pack-*.pack` with its version 2 `.idx`, read by seeking (big repos have big indexes)."""

    def __init__(self, idx: Path) -> None:
        if not (_regular_file(idx) and _regular_file(idx.with_suffix(".pack"))):
            raise _Unreadable  # not regular files
        self.idx = idx.open("rb")
        self.pack = None
        try:
            header = self.idx.read(8 + 256 * 4)
            if len(header) != 8 + 1024 or header[:4] != _IDX_MAGIC or header[4:8] != b"\0\0\0\2":
                raise _Unreadable  # not a version 2 pack index
            self.fanout = [
                int.from_bytes(header[8 + 4 * i : 12 + 4 * i], "big") for i in range(256)
            ]
            self.count = self.fanout[255]
            self.pack = idx.with_suffix(".pack").open("rb")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        for handle in (self.idx, self.pack):
            if handle is not None:
                handle.close()

    def _name(self, i: int) -> bytes:
        self.idx.seek(8 + 1024 + 20 * i)
        return self.idx.read(20)

    def offset_of(self, sha: bytes) -> int | None:
        low = self.fanout[sha[0] - 1] if sha[0] else 0
        high = self.fanout[sha[0]]
        while low < high:
            mid = (low + high) // 2
            name = self._name(mid)
            if len(name) != 20:
                raise _Unreadable  # truncated pack index
            if name == sha:
                break
            if name < sha:
                low = mid + 1
            else:
                high = mid
        else:
            return None
        table = 8 + 1024 + 24 * self.count  # names (20 each) and CRCs (4 each)
        self.idx.seek(table + 4 * mid)
        offset = int.from_bytes(self.idx.read(4), "big")
        if offset & 0x80000000:
            self.idx.seek(table + 4 * self.count + 8 * (offset & 0x7FFFFFFF))
            raw = self.idx.read(8)
            if len(raw) != 8:
                raise _Unreadable  # truncated pack index
            offset = int.from_bytes(raw, "big")
        return offset

    def entry(self, offset: int) -> tuple[int, bytes, int | bytes | None]:
        """`(type, inflated data, delta base)`: base is an offset, a SHA or `None`."""
        self.pack.seek(offset)
        head = self.pack.read(32)
        if not head:
            raise _Unreadable  # offset outside the pack
        byte = head[0]
        kind = (byte >> 4) & 7
        pos = 1
        while byte & 0x80:
            if pos >= len(head):
                raise _Unreadable  # bad pack entry header
            byte = head[pos]
            pos += 1
        base: int | bytes | None = None
        if kind == _OBJ_OFS_DELTA:
            byte = head[pos]
            pos += 1
            back = byte & 0x7F
            while byte & 0x80:
                if pos >= len(head):
                    raise _Unreadable  # bad delta offset
                byte = head[pos]
                pos += 1
                back = ((back + 1) << 7) | (byte & 0x7F)
            base = offset - back
            if base < 0 or base >= offset:
                raise _Unreadable  # delta base after its delta
        elif kind == _OBJ_REF_DELTA:
            base = head[pos : pos + 20]
            pos += 20
            if len(base) != 20:
                raise _Unreadable  # truncated delta base
        elif kind not in _OBJ_TYPES:
            raise _Unreadable  # unknown pack entry type
        self.pack.seek(offset + pos)
        return kind, _inflate(lambda: self.pack.read(_READ_CHUNK), MAX_OBJECT_BYTES), base


class _ObjectStore:
    def __init__(self, objects: Path) -> None:
        self.objects = objects
        self.packs: list[_Pack] | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        for pack in self.packs or []:
            pack.close()

    def _load_packs(self) -> list[_Pack]:
        if self.packs is None:
            self.packs = []
            try:
                indexes = sorted((self.objects / "pack").glob("pack-*.idx"))[:MAX_PACKS]
            except OSError:
                indexes = []
            for idx in indexes:
                try:
                    self.packs.append(_Pack(idx))
                except (OSError, _Unreadable):
                    continue
        return self.packs

    def read(self, sha: str, depth: int = 0) -> tuple[bytes, bytes]:
        """`(type, body)` of object `sha`."""
        if depth > MAX_DELTA_DEPTH:
            raise _Unreadable  # delta chain too long
        loose = self.objects / sha[:2] / sha[2:]
        try:
            if not _regular_file(loose):
                raise FileNotFoundError(loose)
            with loose.open("rb") as handle:
                raw = _inflate(lambda: handle.read(_READ_CHUNK), MAX_OBJECT_BYTES + 64)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise _Unreadable from exc  # loose object unreadable
        else:
            header, sep, body = raw.partition(b"\0")
            kind, _, size = header.partition(b" ")
            if not sep or kind not in _OBJ_TYPES.values() or size != str(len(body)).encode():
                raise _Unreadable  # bad loose object header
            return kind, body
        key = bytes.fromhex(sha)
        for pack in self._load_packs():
            offset = pack.offset_of(key)
            if offset is not None:
                return self._from_pack(pack, offset, depth)
        raise _Unreadable  # object not found

    def _from_pack(self, pack: _Pack, offset: int, depth: int) -> tuple[bytes, bytes]:
        if depth > MAX_DELTA_DEPTH:
            raise _Unreadable  # delta chain too long
        kind, data, base = pack.entry(offset)
        if kind == _OBJ_OFS_DELTA:
            base_kind, base_body = self._from_pack(pack, base, depth + 1)
        elif kind == _OBJ_REF_DELTA:
            base_kind, base_body = self.read(base.hex(), depth + 1)
        else:
            return _OBJ_TYPES[kind], data
        return base_kind, _apply_delta(base_body, data)


def _resolve_ref(refs_home: Path, name: str) -> str | None:
    if not _REF_NAME.match(name) or ".." in name.split("/"):
        return None
    loose = refs_home / name
    try:
        if loose.is_file():
            value = _read_small(loose)
            return value if _SHA1.match(value) else None
    except (OSError, UnicodeDecodeError):
        return None
    packed = refs_home / "packed-refs"
    try:
        if not _regular_file(packed) or packed.stat().st_size > _PACKED_REFS_MAX_BYTES:
            return None
        with packed.open("rb") as handle:
            read = 0
            while line := handle.readline(_SMALL_FILE):
                read += len(line)
                if read > _PACKED_REFS_MAX_BYTES:
                    return None
                sha, _, ref = line.decode("utf-8", errors="replace").strip().partition(" ")
                if ref == name:
                    return sha if _SHA1.match(sha) else None
    except OSError:
        return None
    return None


def _head_sha(git_dir: Path, refs_home: Path) -> str | None:
    try:
        head = _read_small(git_dir / "HEAD")
    except (OSError, UnicodeDecodeError):
        return None
    if _SHA1.match(head):
        return head
    if head.startswith("ref:"):
        return _resolve_ref(refs_home, head[len("ref:") :].strip())
    return None


def _subject_and_parent(body: bytes) -> tuple[str, str | None]:
    """The commit's subject and its first parent.

    A merge commit's subject is written by the tool, not by the people of the repo («Merge pull
    request #5 from owner/branch», «Merged in x»), and its English words would vote English in a
    Spanish repo. For a merge the first line of the body is used instead (GitHub puts the pull
    request's title there); a merge without a body gives no subject.
    """
    headers, _, message = body.partition(b"\n\n")
    parents = [
        line[len(b"parent ") :].decode("ascii", errors="replace").strip()
        for line in headers.split(b"\n")
        if line.startswith(b"parent ")
    ]
    parent = parents[0] if parents and _SHA1.match(parents[0]) else None
    lines = [ln.strip() for ln in message.decode("utf-8", errors="replace").splitlines()]
    lines = [ln for ln in lines if ln]
    if len(parents) > 1:
        return (lines[1] if len(lines) > 1 else ""), parent
    return (lines[0] if lines else ""), parent


def head_commit_subjects(
    git_dir: Path, common: Path | None = None, limit: int = MAX_COMMITS
) -> list[str]:
    """Subjects of the last `limit` commits on HEAD's first-parent chain, newest last.

    `git_dir` holds `HEAD` (a linked worktree's own git dir); `common` is the shared git dir that
    holds the refs and the objects, or `None` when `git_dir` is the repo's own. An empty list means
    the store could not be read (or HEAD has no commit), and the caller keeps its reflog.
    """
    home = common or git_dir
    sha = _head_sha(git_dir, home)
    subjects: list[str] = []
    try:
        with _ObjectStore(home / "objects") as store:
            seen: set[str] = set()
            while sha and len(subjects) < limit and sha not in seen and len(seen) < MAX_WALK:
                seen.add(sha)
                kind, body = store.read(sha)
                if kind != b"commit":
                    break
                subject, sha = _subject_and_parent(body)
                if subject:
                    subjects.append(subject)
    except (_Unreadable, OSError, ValueError, IndexError, zlib.error):
        pass
    return subjects[::-1]
