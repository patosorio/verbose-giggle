"""Research job enqueue seam — docs/04_build_plan.md Phase 4.

Local backend fires run_leg_research in-process via asyncio.create_task.
Cloud Tasks backend is intentionally not implemented until Phase 7.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol
from uuid import UUID

from core.config import settings
from db.models import ResearchRunType
from db.session import async_session

logger = logging.getLogger(__name__)


class ResearchTaskQueue(Protocol):
    async def enqueue_leg_research(
        self,
        leg_id: UUID,
        run_id: UUID,
        run_type: ResearchRunType,
    ) -> None: ...


class LocalResearchTaskQueue:
    """Fire-and-forget in-process runner for local/docker-compose."""

    async def enqueue_leg_research(
        self,
        leg_id: UUID,
        run_id: UUID,
        run_type: ResearchRunType,
    ) -> None:
        asyncio.create_task(
            self._run(leg_id, run_id, run_type),
            name=f"leg-research-{run_id}",
        )

    async def _run(
        self,
        leg_id: UUID,
        run_id: UUID,
        run_type: ResearchRunType,
    ) -> None:
        # Late import avoids circular import with services.research.
        from services.research import run_leg_research

        # Own session — the request session is closed before this task runs.
        async with async_session() as session:
            try:
                await run_leg_research(session, leg_id, run_id, run_type)
            except Exception:
                logger.exception(
                    "local_task_queue_run_failed leg_id=%s run_id=%s run_type=%s",
                    leg_id,
                    run_id,
                    run_type.value,
                )


def get_research_task_queue() -> ResearchTaskQueue:
    backend = settings.task_queue_backend.strip().lower()
    if backend == "local":
        return LocalResearchTaskQueue()
    if backend == "cloud_tasks":
        raise NotImplementedError(
            "TASK_QUEUE_BACKEND=cloud_tasks is Phase 7 — use local for now"
        )
    raise ValueError(f"Unknown TASK_QUEUE_BACKEND={settings.task_queue_backend!r}")


async def enqueue_leg_research(
    leg_id: UUID,
    run_id: UUID,
    run_type: ResearchRunType,
) -> None:
    queue = get_research_task_queue()
    await queue.enqueue_leg_research(leg_id, run_id, run_type)
