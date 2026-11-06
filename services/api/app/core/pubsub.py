"""In-process pub/sub for WebSocket live events (single-worker)."""
from __future__ import annotations

import queue

_events: queue.Queue = queue.Queue()


def publish(event: dict) -> None:
    _events.put(event)


def drain() -> list[dict]:
    out: list[dict] = []
    while True:
        try:
            out.append(_events.get_nowait())
        except queue.Empty:
            break
    return out
