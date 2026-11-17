"""Durable agent state: executed run ids (replay protection) and undelivered results."""
from __future__ import annotations

import json
import pathlib
import threading

from proofos_agent.config import write_private

KEEP_SEEN = 5000


class State:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.spool = root / "spool"
        self.spool.mkdir(parents=True, exist_ok=True)
        self.work = root / "work"
        self.work.mkdir(parents=True, exist_ok=True)
        self._seen_file = root / "seen.json"
        self._lock = threading.Lock()
        try:
            self.seen: set[int] = set(json.loads(self._seen_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            self.seen = set()

    def mark_seen(self, run_id: int) -> None:
        """Persisted before execution starts, so a crash can never cause a second run (at-most-once)."""
        with self._lock:
            self.seen.add(run_id)
            keep = sorted(self.seen)[-KEEP_SEEN:]
            self.seen = set(keep)
            write_private(self._seen_file, json.dumps(keep))

    def spool_result(self, run_id: int, output: str, exit_code: int) -> None:
        write_private(self.spool / f"{run_id}.json", json.dumps({"run_id": run_id, "output": output, "exit_code": exit_code}))

    def spooled(self) -> list[pathlib.Path]:
        return sorted(self.spool.glob("*.json"))

    @property
    def locked(self) -> bool:
        return (self.root / "LOCKDOWN").exists()

    def set_lockdown(self, on: bool) -> None:
        flag = self.root / "LOCKDOWN"
        if on:
            flag.write_text("Remote execution locked by the local administrator.\n", encoding="utf-8")
        elif flag.exists():
            flag.unlink()
