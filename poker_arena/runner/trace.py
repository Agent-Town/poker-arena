from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TraceResult:
    path: Path
    sha256: str
    bytes_written: int


class TraceWriter:
    """
    Append-only JSONL writer with an incremental SHA-256 of the raw bytes written.
    """

    def __init__(self, path: Path):
        self._path = path
        self._tmp = path.with_suffix(path.suffix + ".tmp")
        self._f = open(self._tmp, "wb")
        self._h = hashlib.sha256()
        self._bytes = 0
        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("trace is closed")
        line = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8") + b"\n"
        self._f.write(line)
        self._f.flush()
        os.fsync(self._f.fileno())
        self._h.update(line)
        self._bytes += len(line)

    def close(self) -> TraceResult:
        if self._closed:
            raise RuntimeError("trace already closed")
        self._closed = True
        self._f.flush()
        os.fsync(self._f.fileno())
        self._f.close()
        self._tmp.replace(self._path)
        os.chmod(self._path, 0o444)
        return TraceResult(path=self._path, sha256=self._h.hexdigest(), bytes_written=self._bytes)

