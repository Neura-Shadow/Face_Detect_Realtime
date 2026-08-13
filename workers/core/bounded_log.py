"""Phase 13F size-bounded log writer for a long-lived service.

A service that is meant to survive reboots and run for weeks cannot write an
unbounded log. journald applies its own limits when systemd is supervising, but
the wrapper also writes its own structured log during Gate B (run by hand, no
journald) and on any host where journald's limits are not what we assume. So
the bound is enforced here rather than borrowed.

Rotation is deliberately primitive: when the active file would exceed
``max_bytes`` it is rotated to ``.1``, older generations shift down, and the
oldest is deleted. Total on-disk usage is therefore bounded by
``max_bytes * (backup_count + 1)`` and that number is reported so it can be
checked rather than assumed.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Dict, Optional

DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3


class BoundedJsonlLog:
    """Append-only JSONL log with size-based rotation and a hard total cap."""

    def __init__(
        self,
        path: Optional[str],
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
        echo: bool = False,
    ) -> None:
        self.path = path
        self.max_bytes = max(1024, int(max_bytes))
        self.backup_count = max(0, int(backup_count))
        self.echo = bool(echo)
        self.written_count = 0
        self.rotation_count = 0
        self.write_failure_count = 0
        self.dropped_count = 0
        self.last_error = ""
        self._lock = threading.Lock()
        self._handle = None  # type: Optional[Any]
        self._bytes = 0
        if path:
            directory = os.path.dirname(os.path.abspath(path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            self._open()

    def _open(self) -> None:
        if not self.path:
            return
        self._handle = open(self.path, "a", encoding="utf-8")
        try:
            self._bytes = os.path.getsize(self.path)
        except OSError:
            self._bytes = 0

    def _rotate(self) -> None:
        if not self.path or self._handle is None:
            return
        self._handle.flush()
        self._handle.close()
        self._handle = None
        try:
            if self.backup_count == 0:
                os.remove(self.path)
            else:
                oldest = "%s.%d" % (self.path, self.backup_count)
                if os.path.exists(oldest):
                    os.remove(oldest)
                for index in range(self.backup_count - 1, 0, -1):
                    source = "%s.%d" % (self.path, index)
                    if os.path.exists(source):
                        os.replace(source, "%s.%d" % (self.path, index + 1))
                os.replace(self.path, "%s.1" % self.path)
            self.rotation_count += 1
        except OSError as exc:
            self.write_failure_count += 1
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
        self._open()

    def write(self, event_type: str, **fields: Any) -> Dict[str, Any]:
        record = {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "monotonic": round(time.monotonic(), 6),
            "pid": os.getpid(),
            "event_type": str(event_type),
        }
        record.update(fields)
        with self._lock:
            try:
                line = json.dumps(record, sort_keys=True, default=str)
            except (TypeError, ValueError) as exc:
                self.dropped_count += 1
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
                return record
            if self.echo:
                # stderr, not stdout: under systemd both land in journald, but
                # keeping stdout clean means --preflight-only and --status stay
                # machine-readable instead of interleaving log lines with JSON.
                try:
                    print(line, file=sys.stderr, flush=True)
                except (OSError, ValueError):
                    pass
            if self._handle is not None:
                encoded = len(line.encode("utf-8")) + 1
                if self._bytes + encoded > self.max_bytes:
                    self._rotate()
                try:
                    self._handle.write(line + "\n")
                    self._handle.flush()
                    self._bytes += encoded
                    self.written_count += 1
                except OSError as exc:
                    self.write_failure_count += 1
                    self.last_error = "%s: %s" % (type(exc).__name__, exc)
            else:
                self.written_count += 1
        return record

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                try:
                    self._handle.flush()
                    self._handle.close()
                finally:
                    self._handle = None

    @property
    def max_total_bytes(self) -> int:
        return self.max_bytes * (self.backup_count + 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_path": self.path,
            "log_max_bytes": self.max_bytes,
            "log_backup_count": self.backup_count,
            "log_max_total_bytes": self.max_total_bytes,
            "log_written_count": self.written_count,
            "log_rotation_count": self.rotation_count,
            "log_write_failure_count": self.write_failure_count,
            "log_dropped_count": self.dropped_count,
            "log_last_error": self.last_error,
            "log_bounded": True,
        }
