"""Append-only, hash-chained spend ledger (JSONL).

Each line commits to the previous line's hash, so silent edits and deletions
are detectable; `verify` walks the whole chain. Durability/concurrency (Ox
review #5, 2026-08-22): the tail is re-read from disk by seeking to the last
line (O(1), no cache to fork), every append is flushed+fsynced, and mutating
callers must hold the exclusive lock (`Ledger.lock()`).
"""
from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import os

GENESIS = "0" * 64


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _link_hash(prev: str, rec: dict) -> str:
    return hashlib.sha256((prev + _canon(rec)).encode()).hexdigest()


class Ledger:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    @contextlib.contextmanager
    def lock(self):
        """Exclusive lock for any mutating batch — two concurrent ingests
        would otherwise both read seq=N and fork the chain."""
        lockpath = self.path + ".lock"
        with open(lockpath, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def _tail(self):
        """Read (seq, hash) from the last line by seeking — no full scan,
        no cached state that can go stale or fork."""
        if not os.path.exists(self.path):
            return 0, GENESIS
        with open(self.path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return 0, GENESIS
            back = min(size, 65536)
            f.seek(size - back)
            chunk = f.read().decode("utf-8", "replace")
        lines = [l for l in chunk.splitlines() if l.strip()]
        if not lines:
            return 0, GENESIS
        try:
            row = json.loads(lines[-1])
        except ValueError:
            raise RuntimeError(
                f"{self.path}: last line is torn (crash mid-write?) — "
                "truncate it to the previous newline, then run verify") from None
        return row["seq"], row["hash"]

    def append(self, rec: dict) -> dict:
        seq, prev = self._tail()
        row = {"seq": seq + 1, "prev": prev, "rec": rec,
               "hash": _link_hash(prev, rec)}
        with open(self.path, "a") as f:
            f.write(_canon(row) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return row

    def append_batch(self, recs) -> int:
        """Locked batch append with ONE tail read and ONE fsync — 22k
        per-append fsyncs would turn bulk ingest into minutes of disk sync."""
        n = 0
        with self.lock():
            seq, prev = self._tail()
            with open(self.path, "a") as f:
                for rec in recs:
                    seq += 1
                    row = {"seq": seq, "prev": prev, "rec": rec,
                           "hash": _link_hash(prev, rec)}
                    f.write(_canon(row) + "\n")
                    prev = row["hash"]
                    n += 1
                f.flush()
                os.fsync(f.fileno())
        return n

    def records(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)["rec"]

    def known_ids(self) -> set:
        return {r["id"] for r in self.records()}

    def hash_at(self, seq: int):
        """Chain hash at a given seq, or None — used to check anchors."""
        if not os.path.exists(self.path):
            return None
        with open(self.path) as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    if row["seq"] == seq:
                        return row["hash"]
        return None

    def verify(self) -> tuple[bool, str]:
        prev, seq = GENESIS, 0
        if not os.path.exists(self.path):
            return True, "empty ledger"
        with open(self.path) as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    return False, f"line {n}: unparseable (torn write or corruption)"
                if row["seq"] != seq + 1:
                    return False, f"line {n}: seq {row['seq']} after {seq} (deletion or reorder)"
                if row["prev"] != prev:
                    return False, f"line {n}: prev-hash mismatch (chain broken)"
                if _link_hash(prev, row["rec"]) != row["hash"]:
                    return False, f"line {n}: record tampered (hash mismatch)"
                prev, seq = row["hash"], row["seq"]
        return True, f"{seq} records, chain intact"


def verify_anchors(ledger: "Ledger", anchors_path: str) -> tuple[bool, str]:
    """Check every witnessed (seq, hash) against the live chain. The anchors
    file lives in a git repo — a different trust domain from the ledger's
    writer — so a wholesale genesis rewrite has to also rewrite git history
    to stay hidden."""
    if not os.path.exists(anchors_path):
        return True, "no anchors yet"
    n = 0
    with open(anchors_path) as f:
        for line in f:
            if not line.strip():
                continue
            a = json.loads(line)
            h = ledger.hash_at(a["seq"])
            if h is None:
                return False, f"anchor seq={a['seq']} missing from ledger (history rewritten shorter)"
            if h != a["hash"]:
                return False, f"anchor seq={a['seq']} hash mismatch (history rewritten)"
            n += 1
    return True, f"{n} anchors match"
