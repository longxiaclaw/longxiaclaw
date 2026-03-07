"""Tests for state module."""

from __future__ import annotations



from longxiaclaw.scheduler import AppState, ScheduledTask, StateManager


class TestScheduledTask:
    def test_to_dict_roundtrip(self):
        task = ScheduledTask(
            id="task-1",
            prompt="Check weather",
            schedule_type="cron",
            schedule_value="0 9 * * *",
            next_run="2026-01-01T09:00:00",
            status="active",
            created_at="2026-01-01T00:00:00",
        )
        d = task.to_dict()
        restored = ScheduledTask.from_dict(d)
        assert restored.id == task.id
        assert restored.prompt == task.prompt
        assert restored.schedule_type == task.schedule_type
        assert restored.schedule_value == task.schedule_value
        assert restored.next_run == task.next_run
        assert restored.status == task.status

    def test_from_dict_defaults(self):
        task = ScheduledTask.from_dict({
            "id": "t1",
            "prompt": "hello",
            "schedule_type": "once",
            "schedule_value": "2026-01-01T10:00:00",
        })
        assert task.status == "active"
        assert task.created_at == ""
        assert task.next_run is None
        assert task.last_run is None


class TestAppState:
    def test_to_dict_roundtrip(self):
        task = ScheduledTask(
            id="t1", prompt="test", schedule_type="once",
            schedule_value="2026-01-01T10:00:00",
        )
        state = AppState(scheduled_tasks=[task])
        d = state.to_dict()
        restored = AppState.from_dict(d)
        assert len(restored.scheduled_tasks) == 1
        assert restored.scheduled_tasks[0].id == "t1"

    def test_empty_state(self):
        state = AppState()
        assert state.scheduled_tasks == []


class TestStateManager:
    def test_load_missing_file(self, tmp_path):
        mgr = StateManager(tmp_path / "scheduler" / "state.yaml")
        state = mgr.load()
        assert state.scheduled_tasks == []

    def test_save_and_load(self, tmp_path):
        state_path = tmp_path / "scheduler" / "state.yaml"
        (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
        mgr = StateManager(state_path)

        state = AppState()
        mgr.save(state)

        loaded = mgr.load()
        assert loaded.last_updated != ""

    def test_atomic_save(self, tmp_path):
        state_path = tmp_path / "scheduler" / "state.yaml"
        (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
        mgr = StateManager(state_path)

        # Save initial
        mgr.save(AppState())
        # Overwrite
        mgr.save(AppState())

        loaded = mgr.load()
        assert loaded.last_updated != ""
        # No leftover temp files
        tmp_files = list((tmp_path / "scheduler").glob("state_*.tmp"))
        assert len(tmp_files) == 0

    def test_add_and_delete_task(self, tmp_path):
        state_path = tmp_path / "scheduler" / "state.yaml"
        (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
        mgr = StateManager(state_path)

        task = ScheduledTask(
            id="t1", prompt="test", schedule_type="once",
            schedule_value="2026-01-01T10:00:00",
        )
        mgr.add_task(task)

        state = mgr.load()
        assert len(state.scheduled_tasks) == 1

        mgr.delete_task("t1")
        state = mgr.load()
        assert len(state.scheduled_tasks) == 0

    def test_update_task(self, tmp_path):
        state_path = tmp_path / "scheduler" / "state.yaml"
        (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
        mgr = StateManager(state_path)

        task = ScheduledTask(
            id="t1", prompt="test", schedule_type="once",
            schedule_value="2026-01-01T10:00:00",
        )
        mgr.add_task(task)
        mgr.update_task("t1", status="completed", last_run="2026-01-01T10:01:00")

        state = mgr.load()
        assert state.scheduled_tasks[0].status == "completed"
        assert state.scheduled_tasks[0].last_run == "2026-01-01T10:01:00"

    def test_get_due_tasks(self, tmp_path):
        state_path = tmp_path / "scheduler" / "state.yaml"
        (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
        mgr = StateManager(state_path)

        # Past task (due)
        past = ScheduledTask(
            id="t1", prompt="past", schedule_type="once",
            schedule_value="2020-01-01T00:00:00",
            next_run="2020-01-01T00:00:00",
        )
        # Future task (not due)
        future = ScheduledTask(
            id="t2", prompt="future", schedule_type="once",
            schedule_value="2099-01-01T00:00:00",
            next_run="2099-01-01T00:00:00",
        )
        # Completed task (should be excluded)
        completed = ScheduledTask(
            id="t3", prompt="done", schedule_type="once",
            schedule_value="2020-01-01T00:00:00",
            next_run="2020-01-01T00:00:00",
            status="completed",
        )
        mgr.add_task(past)
        mgr.add_task(future)
        mgr.add_task(completed)

        due = mgr.get_due_tasks()
        assert len(due) == 1
        assert due[0].id == "t1"

    def test_load_corrupt_file(self, tmp_path):
        state_path = tmp_path / "scheduler" / "state.yaml"
        (tmp_path / "scheduler").mkdir(parents=True, exist_ok=True)
        state_path.write_text("{{invalid yaml: [", encoding="utf-8")

        mgr = StateManager(state_path)
        state = mgr.load()
        assert state.scheduled_tasks == []
