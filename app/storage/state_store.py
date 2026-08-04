from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Protocol

from app.domain.models import WorkflowState, WorkflowStatus


class WorkflowStateStore(Protocol):
    def create(self, state: WorkflowState) -> WorkflowState:
        ...

    def get(self, workflow_id: str) -> WorkflowState | None:
        ...

    def update(self, state: WorkflowState) -> WorkflowState:
        ...

    def list_by_status(self, status: WorkflowStatus | None = None) -> list[WorkflowState]:
        ...


class JsonWorkflowStateStore:
    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create(self, state: WorkflowState) -> WorkflowState:
        with self._lock:
            path = self._path_for(state.workflow_id)
            if path.exists():
                raise ValueError(f"Workflow already exists: {state.workflow_id}")
            self._write(path, state)
            return state

    def get(self, workflow_id: str) -> WorkflowState | None:
        with self._lock:
            path = self._path_for(workflow_id)
            if not path.exists():
                return None
            return WorkflowState.model_validate_json(path.read_text(encoding="utf-8"))

    def update(self, state: WorkflowState) -> WorkflowState:
        with self._lock:
            self._write(self._path_for(state.workflow_id), state)
            return state

    def list_by_status(self, status: WorkflowStatus | None = None) -> list[WorkflowState]:
        with self._lock:
            states = [
                WorkflowState.model_validate_json(path.read_text(encoding="utf-8"))
                for path in sorted(self._storage_dir.glob("*.json"))
            ]
            if status is None:
                return states
            return [state for state in states if state.status == status]

    def _path_for(self, workflow_id: str) -> Path:
        safe_id = workflow_id.replace("/", "_").replace("\\", "_")
        return self._storage_dir / f"{safe_id}.json"

    @staticmethod
    def _write(path: Path, state: WorkflowState) -> None:
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(path)

