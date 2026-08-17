from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from app.models.domain import Finding, Usage


JobStatus = Literal["queued", "running", "done", "failed"]


@dataclass(frozen=True, slots=True)
class JobEvent:
    name: str
    data: dict[str, Any]


@dataclass(slots=True)
class Job:
    job_id: str
    status: JobStatus
    usage: Usage
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None
    events: list[JobEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def append_event(self, name: str, data: dict[str, Any]) -> None:
        async with self.condition:
            self.events.append(JobEvent(name, data))
            self.condition.notify_all()

    async def wait_until_terminal(self) -> None:
        async with self.condition:
            await self.condition.wait_for(lambda: self.status in ("done", "failed"))


class InMemoryJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.idempotency: dict[str, tuple[str, str]] = {}
        self.cache_sources: dict[str, str] = {}
        self.lock = asyncio.Lock()

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)
