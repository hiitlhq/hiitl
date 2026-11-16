"""The store's value-hash key (event_format.md §Redaction; HTL-22 row 163(c), ruled 2026-11-05).

Ruled by Trevor on HTL-20: "(c) the gateway's hash is keyed (HMAC)". The key is a file next to the audit database, made
once with mode 0600 and read at every later start. It is never in a record, an upload or a log: a reader who holds the
record and not the key cannot test a guessed value against a hash. A key a release before this one made beside a
name on the way to the file is the store's key, written beside the file and left where it was; keys that differ fail
the start (HTL-29 second review, condition 3). An in-memory store keeps an in-memory key.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

from hiitl.core.redaction import KEY_BYTES

SUFFIX = ".value_hash.key"
# SQLite's name for a database that lives only in its process: there is no file to keep a key beside
MEMORY = ":memory:"


def key_path(db_path: str | os.PathLike) -> Path:
    """Where the key of the store at `db_path` lives: beside the file its name resolves to, which SQLite opens "by its
    canonical name" and keeps its journal beside, so every name through a symbolic link reads one key (HTL-29 review,
    condition 3). The name is resolved as the filesystem resolves it: `..` after a link to a directory is the parent of
    the directory the link reaches (HTL-29 third review, condition 3). A name that reaches no file yet is read as
    written. Mirrors the TypeScript `keyPath`."""
    return Path(f"{os.path.realpath(db_path) if os.path.exists(db_path) else db_path}{SUFFIX}")


def _names(db_path: str | os.PathLike) -> list[str]:
    """The names on the way from `db_path` as written to its file: the name written and each symbolic link it passes
    through, a link's target read against the link's own directory. A name is joined as text and never normalised,
    so the filesystem reads each `..` in it after the links before it (HTL-29 third review, condition 3). A link met
    twice ends the way."""
    names, seen, name = [], set(), os.fspath(db_path)
    while True:
        names.append(name)
        try:
            st = os.lstat(name)
        except OSError:
            return names
        if not stat.S_ISLNK(st.st_mode) or (st.st_dev, st.st_ino) in seen:
            return names
        seen.add((st.st_dev, st.st_ino))
        name = os.path.join(os.path.dirname(name), os.readlink(name))


def _read(path: Path) -> bytes:
    key = path.read_bytes()
    if len(key) != KEY_BYTES:
        raise ValueError(
            f"The value-hash key {path} holds {len(key)} bytes, and a store's key is {KEY_BYTES}. It is the key the "
            f"store's records were hashed under: restore it, or move the store and its key aside to start a new one.")
    return key


def _found(db_path: str | os.PathLike) -> dict[str, bytes]:
    """Each key beside the file, or beside a name on the way, where a release before this one made it beside the name
    it was given: one per file, by the name it was found at (HTL-29 second review, condition 3)."""
    found, files = {}, set()
    for path in (key_path(db_path), *(Path(f"{name}{SUFFIX}") for name in _names(db_path))):
        if path.exists() and os.path.realpath(path) not in files:
            files.add(os.path.realpath(path))
            found[str(path)] = _read(path)
    return found


def _differ(files) -> str:
    return (f"The value-hash keys {', '.join(files)} differ. A release before this one made a key beside each name the "
            "store was given, so its records were hashed under one or more of them and nothing on disk says which, and "
            "none is chosen: keep the key its records were hashed under and move the others aside.")


def _place(path: Path, key: bytes) -> None:
    """Writes `key` at `path`, mode 0600, unless a key lands there first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, key)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(tmp, path)
    except FileExistsError:
        pass
    finally:
        tmp.unlink()


def store_key(db_path: str | os.PathLike) -> bytes:
    """The store's key: the one beside the store's file, or one a release before this one made beside a name on the
    way, written beside the file and left where it was; made there at the store's first start (mode 0600) when there is
    none. Two processes that start together keep the one that lands first. Raises ValueError, naming each file, for
    keys that differ and for a key file of another length."""
    if str(db_path) == MEMORY:
        return secrets.token_bytes(KEY_BYTES)
    path, found = key_path(db_path), _found(db_path)
    known = set(found.values())
    if len(known) > 1:
        raise ValueError(_differ(found))
    if not path.exists():
        _place(path, next(iter(known)) if known else secrets.token_bytes(KEY_BYTES))
    key = _read(path)
    if known and key not in known:          # another start wrote another key beside the file meanwhile
        raise ValueError(_differ([str(path), *found]))
    return key
