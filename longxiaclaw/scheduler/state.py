"""File-based state management using YAML."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ScheduledTask:
    id: str
    prompt: str
    schedule_type: str  # "cron", "interval", "once"
    schedule_value: str
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    status: str = "active"  # "active", "paused", "completed"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "schedule_type": self.schedule_type,
            "schedule_value": self.schedule_value,
            "next_run": self.next_run,
            "last_run": self.last_run,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduledTask:
        return cls(
            id=data["id"],
            prompt=data["prompt"],
            schedule_type=data["schedule_type"],
            schedule_value=data["schedule_value"],
            next_run=data.get("next_run"),
            last_run=data.get("last_run"),
            status=data.get("status", "active"),
            created_at=data.get("created_at", ""),
        )


@dataclass
class AppState:
    scheduled_tasks: list[ScheduledTask] = field(default_factory=list)
    last_updated: str = ""

    def to_dict(self) -> dict:
        return {
            "scheduled_tasks": [t.to_dict() for t in self.scheduled_tasks],
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AppState:
        tasks = [ScheduledTask.from_dict(t) for t in data.get("scheduled_tasks", [])]
        return cls(
            scheduled_tasks=tasks,
            last_updated=data.get("last_updated", ""),
        )


class StateManager:
    def __init__(self, state_path: Path):
        self._path = state_path

    def load(self) -> AppState:
        """Load state from YAML file. Returns default state if file missing."""
        if not self._path.exists():
            return AppState()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data is None:
                return AppState()
            return AppState.from_dict(data)
        except (yaml.YAMLError, KeyError, TypeError):
            return AppState()

    def save(self, state: AppState) -> None:
        """Atomic save: write to tmp file, then os.replace()."""
        state.last_updated = datetime.now().isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent, suffix=".tmp", prefix="state_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(state.to_dict(), f, default_flow_style=False)
            os.replace(tmp_path, self._path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def add_task(self, task: ScheduledTask) -> None:
        state = self.load()
        state.scheduled_tasks.append(task)
        self.save(state)

    def get_due_tasks(self) -> list[ScheduledTask]:
        """Return active tasks whose next_run is in the past."""
        state = self.load()
        now = datetime.now().isoformat()
        due = []
        for task in state.scheduled_tasks:
            if task.status == "active" and task.next_run and task.next_run <= now:
                due.append(task)
        return due

    def update_task(self, task_id: str, **updates) -> None:
        state = self.load()
        for task in state.scheduled_tasks:
            if task.id == task_id:
                for key, value in updates.items():
                    if hasattr(task, key):
                        setattr(task, key, value)
                break
        self.save(state)

    def delete_task(self, task_id: str) -> None:
        state = self.load()
        state.scheduled_tasks = [t for t in state.scheduled_tasks if t.id != task_id]
        self.save(state)
