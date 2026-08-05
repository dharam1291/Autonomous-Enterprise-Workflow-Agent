from __future__ import annotations

import queue
import threading
from typing import Any


class WorkflowEventBus:
    """Thread-safe pub/sub for streaming workflow node events to SSE clients."""

    def __init__(self) -> None:
        self._channels: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def create_channel(self, workflow_id: str) -> None:
        with self._lock:
            self._channels[workflow_id] = queue.Queue()

    def publish(self, workflow_id: str, event: dict[str, Any]) -> None:
        ch = self._channels.get(workflow_id)
        if ch is not None:
            ch.put_nowait(event)

    def get_channel(self, workflow_id: str) -> queue.Queue[dict[str, Any]] | None:
        return self._channels.get(workflow_id)

    def close_channel(self, workflow_id: str) -> None:
        with self._lock:
            self._channels.pop(workflow_id, None)
