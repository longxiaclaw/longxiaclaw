"""Tests for task scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from longxiaclaw.scheduler import TaskScheduler, ScheduledTask, StateManager


@pytest.fixture
def state_manager(tmp_path):
    (tmp_path / "scheduler").mkdir(exist_ok=True)
    return StateManager(tmp_path / "scheduler" / "state.yaml")


class TestTaskScheduler:
    def test_update_after_run_once(self, state_manager):
        task = ScheduledTask(
            id="t1", prompt="test", schedule_type="once",
            schedule_value="2020-01-01T00:00:00",
            next_run="2020-01-01T00:00:00",
        )
        state_manager.add_task(task)

        run_fn = AsyncMock(return_value="done")
        scheduler = TaskScheduler(state_manager, run_fn, lambda: False)
        scheduler._update_after_run(task)

        state = state_manager.load()
        updated = state.scheduled_tasks[0]
        assert updated.status == "completed"
        assert updated.last_run is not None
        assert updated.next_run is None

    def test_update_after_run_interval(self, state_manager):
        task = ScheduledTask(
            id="t1", prompt="test", schedule_type="interval",
            schedule_value="3600",
            next_run="2020-01-01T00:00:00",
        )
        state_manager.add_task(task)

        run_fn = AsyncMock(return_value="done")
        scheduler = TaskScheduler(state_manager, run_fn, lambda: False)
        scheduler._update_after_run(task)

        state = state_manager.load()
        updated = state.scheduled_tasks[0]
        assert updated.last_run is not None
        assert updated.next_run is not None
        # next_run should be roughly 1 hour from now
        next_dt = datetime.fromisoformat(updated.next_run)
        now = datetime.now()
        assert abs((next_dt - now).total_seconds() - 3600) < 5

    def test_update_after_run_cron(self, state_manager):
        task = ScheduledTask(
            id="t1", prompt="test", schedule_type="cron",
            schedule_value="0 9 * * *",
            next_run="2020-01-01T09:00:00",
        )
        state_manager.add_task(task)

        run_fn = AsyncMock(return_value="done")
        scheduler = TaskScheduler(state_manager, run_fn, lambda: False)
        scheduler._update_after_run(task)

        state = state_manager.load()
        updated = state.scheduled_tasks[0]
        assert updated.last_run is not None
        assert updated.next_run is not None
        next_dt = datetime.fromisoformat(updated.next_run)
        # next_run should be 9:00 of some future day
        assert next_dt.hour == 9
        assert next_dt.minute == 0

    @pytest.mark.asyncio
    async def test_start_and_stop(self, state_manager):
        run_fn = AsyncMock(return_value="done")
        scheduler = TaskScheduler(
            state_manager, run_fn, lambda: False, poll_interval=0.05,
        )

        # Run scheduler in background
        _task = asyncio.create_task(scheduler.start())  # noqa: F841

        # Let it run a couple cycles
        await asyncio.sleep(0.15)
        scheduler.stop()
        await asyncio.sleep(0.1)

        # Should have stopped without error
        assert not scheduler._running

    @pytest.mark.asyncio
    async def test_skips_when_busy(self, state_manager):
        # Add a due task
        task = ScheduledTask(
            id="t1", prompt="test", schedule_type="once",
            schedule_value="2020-01-01T00:00:00",
            next_run="2020-01-01T00:00:00",
        )
        state_manager.add_task(task)

        run_fn = AsyncMock(return_value="done")
        # Agent is always busy
        scheduler = TaskScheduler(
            state_manager, run_fn, lambda: True, poll_interval=0.05,
        )

        _sched_task = asyncio.create_task(scheduler.start())  # noqa: F841
        await asyncio.sleep(0.15)
        scheduler.stop()
        await asyncio.sleep(0.1)

        # run_fn should never have been called because agent was busy
        run_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_runs_due_task(self, state_manager):
        task = ScheduledTask(
            id="t1", prompt="do something", schedule_type="once",
            schedule_value="2020-01-01T00:00:00",
            next_run="2020-01-01T00:00:00",
        )
        state_manager.add_task(task)

        run_fn = AsyncMock(return_value="done")
        scheduler = TaskScheduler(
            state_manager, run_fn, lambda: False, poll_interval=0.05,
        )

        _sched_task = asyncio.create_task(scheduler.start())  # noqa: F841
        await asyncio.sleep(0.15)
        scheduler.stop()
        await asyncio.sleep(0.1)

        # run_fn should have been called with the task
        assert run_fn.call_count >= 1
        called_task = run_fn.call_args[0][0]
        assert called_task.id == "t1"

        # Task should now be completed
        state = state_manager.load()
        assert state.scheduled_tasks[0].status == "completed"
