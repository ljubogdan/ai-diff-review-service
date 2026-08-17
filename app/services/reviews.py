from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Coroutine
from typing import Any

from app.config import MAX_CONCURRENT_JOBS
from app.models.domain import Finding, ReviewOptions, Usage
from app.providers.base import ProviderError, ReviewProvider
from app.services.diff_parser import chunk_files, parse_unified_diff
from app.storage.memory import InMemoryJobStore, Job, JobEvent, JobStatus


class IdempotencyConflictError(ValueError):
    pass


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _content_digest(diff: str, options: ReviewOptions) -> str:
    normalized = json.dumps(
        {"diff": diff, "options": options.model_dump()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _digest(normalized)


def _ordered_unique(findings: list[Finding]) -> list[Finding]:
    by_id: dict[str, Finding] = {}
    for finding in findings:
        by_id.setdefault(finding.id, finding)
    return sorted(by_id.values(), key=lambda item: (item.path, item.line, item.ruleId))


class ReviewService:
    def __init__(
        self,
        providers: dict[str, ReviewProvider],
        store: InMemoryJobStore | None = None,
        max_concurrent_jobs: int = MAX_CONCURRENT_JOBS,
    ) -> None:
        self.providers = providers
        self.store = store or InMemoryJobStore()
        self.semaphore = asyncio.Semaphore(max_concurrent_jobs)
        self.tasks: set[asyncio.Task[None]] = set()

    def _schedule(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def find_idempotent(self, idempotency_key: str | None, raw_body: bytes) -> Job | None:
        if idempotency_key is None:
            return None
        body_digest = _digest(raw_body)
        async with self.store.lock:
            previous = self.store.idempotency.get(idempotency_key)
            if previous is None:
                return None
            previous_digest, previous_job_id = previous
            if previous_digest != body_digest:
                raise IdempotencyConflictError
            return self.store.jobs[previous_job_id]

    async def submit(
        self,
        diff: str,
        options: ReviewOptions,
        raw_body: bytes,
        idempotency_key: str | None,
    ) -> Job:
        files = parse_unified_diff(diff)
        chunks = chunk_files(files)
        body_digest = _digest(raw_body)
        content_digest = _content_digest(diff, options)

        async with self.store.lock:
            if idempotency_key is not None and idempotency_key in self.store.idempotency:
                previous_digest, previous_job_id = self.store.idempotency[idempotency_key]
                if previous_digest != body_digest:
                    raise IdempotencyConflictError
                return self.store.jobs[previous_job_id]

            job_id = uuid.uuid4().hex
            source_id = self.store.cache_sources.get(content_digest)
            job = Job(
                job_id=job_id,
                status="queued",
                usage=Usage(
                    inputBytes=len(diff.encode("utf-8")),
                    chunks=len(chunks),
                    cacheHit=source_id is not None,
                ),
            )
            job.events.append(JobEvent("status", {"status": "queued"}))
            self.store.jobs[job_id] = job
            if idempotency_key is not None:
                self.store.idempotency[idempotency_key] = (body_digest, job_id)

            if source_id is None:
                self.store.cache_sources[content_digest] = job_id
                self._schedule(self._run(job, chunks, options, content_digest))
            else:
                self._schedule(self._copy_cached(job, self.store.jobs[source_id]))
            return job

    async def _set_status(self, job: Job, status: JobStatus, error: str | None = None) -> None:
        data: dict[str, object] = {"status": status}
        if error is not None:
            data["error"] = error
        async with job.condition:
            job.status = status
            job.error = error
            job.events.append(JobEvent("status", data))
            job.condition.notify_all()

    async def _complete(self, job: Job, findings: list[Finding]) -> None:
        job.findings = findings
        for finding in findings:
            await job.append_event("finding", finding.model_dump())
        async with job.condition:
            job.status = "done"
            job.events.append(JobEvent("status", {"status": "done"}))
            job.events.append(
                JobEvent("done", {"total": len(findings), "usage": job.usage.model_dump()})
            )
            job.condition.notify_all()

    async def _run(
        self,
        job: Job,
        chunks: list[list],
        options: ReviewOptions,
        content_digest: str,
    ) -> None:
        try:
            async with self.semaphore:
                await self._set_status(job, "running")
                provider = self.providers[options.provider]
                all_findings: list[Finding] = []
                for chunk in chunks:
                    all_findings.extend(await provider.analyze(chunk))
                findings = _ordered_unique(all_findings)[: options.maxFindings]
                await self._complete(job, findings)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ProviderError) else "Review processing failed"
            await self._set_status(job, "failed", message)
            async with self.store.lock:
                if self.store.cache_sources.get(content_digest) == job.job_id:
                    self.store.cache_sources.pop(content_digest, None)

    async def _copy_cached(self, job: Job, source: Job) -> None:
        await self._set_status(job, "running")
        await source.wait_until_terminal()
        if source.status == "failed":
            await self._set_status(job, "failed", source.error or "Cached review failed")
            return
        await self._complete(job, list(source.findings))
