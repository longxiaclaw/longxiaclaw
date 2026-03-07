"""Cron/interval/once task scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from croniter import croniter

from .state import ScheduledTask, StateManager

logger = logging.getLogger("longxiaclaw")


class TaskScheduler:
    """Poll loop: check for due tasks every poll_interval seconds.
    Skips execution if agent is currently busy (one agent at a time)."""

    def __init__(
        self,
        state_manager: StateManager,
        run_task_fn: Callable[[ScheduledTask], Awaitable[str]],
        is_busy_fn: Callable[[], bool],
        poll_interval: float = 60.0,
    ):
        self._state = state_manager
        self._run_task = run_task_fn
        self._is_busy = is_busy_fn
        self._poll_interval = poll_interval
        self._running = False

    async def start(self) -> None:
        """Poll loop: check for due tasks every poll_interval seconds."""
        self._running = True
        while self._running:
            try:
                if not self._is_busy():
                    due = self._state.get_due_tasks()
                    for task in due:
                        if self._is_busy():
                            logger.info("Skipping scheduled task %s (agent busy)", task.id)
                            break
                        try:
                            logger.info("Running scheduled task: %s", task.id)
                            await self._run_task(task)
                            self._update_after_run(task)
                            logger.info("Scheduled task %s completed", task.id)
                        except Exception as e:
                            logger.error("Scheduled task %s failed: %s", task.id, e)
                            self._state.update_task(
                                task.id,
                                last_run=datetime.now().isoformat(),
                            )
            except Exception as e:
                logger.error("Scheduler error: %s", e)

            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    def _update_after_run(self, task: ScheduledTask) -> None:
        """Compute next_run based on schedule_type."""
        now = datetime.now()
        now_iso = now.isoformat()

        if task.schedule_type == "cron":
            cron = croniter(task.schedule_value, now)
            next_run = cron.get_next(datetime).isoformat()
            self._state.update_task(
                task.id,
                last_run=now_iso,
                next_run=next_run,
            )
            logger.info("Task %s next run (cron): %s", task.id, next_run)

        elif task.schedule_type == "interval":
            seconds = int(task.schedule_value)
            next_run = (now + timedelta(seconds=seconds)).isoformat()
            self._state.update_task(
                task.id,
                last_run=now_iso,
                next_run=next_run,
            )
            logger.info("Task %s next run (interval %ss): %s", task.id, seconds, next_run)

        elif task.schedule_type == "once":
            self._state.update_task(
                task.id,
                status="completed",
                last_run=now_iso,
                next_run=None,
            )
            logger.info("One-shot task %s marked completed", task.id)
