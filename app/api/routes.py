from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from app.api.errors import error_response
from app.config import (
    CHUNK_BYTES,
    MAX_CONCURRENT_JOBS,
    MAX_PAYLOAD_BYTES,
    RATE_LIMIT_PER_MINUTE,
    VERSION,
)
from app.models.domain import ReviewRequest
from app.services.diff_parser import InvalidDiffError
from app.services.reviews import IdempotencyConflictError, ReviewService
from app.storage.memory import Job, JobEvent


router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    return {
        "status": "ok",
        "version": VERSION,
        "uptimeSeconds": max(0, time.monotonic() - request.app.state.started_at),
    }


@router.get("/spec")
async def spec() -> dict[str, object]:
    return {
        "specVersion": "1.0",
        "providers": ["mock", "llm"],
        "limits": {
            "maxPayloadBytes": MAX_PAYLOAD_BYTES,
            "chunkBytes": CHUNK_BYTES,
            "maxConcurrentJobs": MAX_CONCURRENT_JOBS,
            "rateLimitPerMinute": RATE_LIMIT_PER_MINUTE,
        },
    }


def _service(request: Request) -> ReviewService:
    return request.app.state.review_service


@router.post("/v1/reviews", status_code=202)
async def submit_review(request: Request) -> JSONResponse:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_PAYLOAD_BYTES:
                return error_response(413, "payload_too_large", "Payload exceeds 1 MiB")
        except ValueError:
            pass

    body = await request.body()
    if len(body) > MAX_PAYLOAD_BYTES:
        return error_response(413, "payload_too_large", "Payload exceeds 1 MiB")

    allowed, retry_after = await request.app.state.rate_limiter.acquire()
    if not allowed:
        return error_response(
            429,
            "rate_limited",
            "Submission rate limit exceeded",
            {"Retry-After": str(retry_after)},
        )

    try:
        existing = await _service(request).find_idempotent(
            request.headers.get("idempotency-key"), body
        )
    except IdempotencyConflictError:
        return error_response(409, "idempotency_conflict", "Idempotency key was used with a different body")
    if existing is not None:
        return JSONResponse(status_code=202, content={"jobId": existing.job_id, "status": "queued"})

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return error_response(400, "invalid_json", "Request body is not valid JSON")

    try:
        review_request = ReviewRequest.model_validate(payload)
        job = await _service(request).submit(
            review_request.diff,
            review_request.options,
            body,
            request.headers.get("idempotency-key"),
        )
    except ValidationError as exc:
        return error_response(422, "invalid_diff", f"Invalid review request: {exc.errors()[0]['msg']}")
    except InvalidDiffError as exc:
        return error_response(422, "invalid_diff", str(exc))
    except IdempotencyConflictError:
        return error_response(409, "idempotency_conflict", "Idempotency key was used with a different body")

    return JSONResponse(status_code=202, content={"jobId": job.job_id, "status": "queued"})


def _job_response(job: Job) -> dict[str, object]:
    response: dict[str, object] = {
        "jobId": job.job_id,
        "status": job.status,
        "usage": job.usage.model_dump(),
    }
    if job.status == "done":
        response["findings"] = [finding.model_dump() for finding in job.findings]
    elif job.status == "failed":
        response["error"] = {"code": "internal", "message": job.error or "Review processing failed"}
    return response


@router.get("/v1/reviews/{job_id}")
async def get_review(request: Request, job_id: str) -> JSONResponse:
    job = _service(request).store.get(job_id)
    if job is None:
        return error_response(404, "not_found", "Review job was not found")
    return JSONResponse(content=_job_response(job))


def _serialize_event(event: JobEvent) -> str:
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.name}\ndata: {data}\n\n"


async def _event_stream(job: Job) -> AsyncIterator[str]:
    index = 0
    while True:
        async with job.condition:
            await job.condition.wait_for(
                lambda: index < len(job.events) or job.status in ("done", "failed")
            )
            events = job.events[index:]
        for event in events:
            index += 1
            yield _serialize_event(event)
        if job.status in ("done", "failed") and index >= len(job.events):
            return
        await asyncio.sleep(0)


@router.get("/v1/reviews/{job_id}/stream")
async def stream_review(request: Request, job_id: str) -> Response:
    job = _service(request).store.get(job_id)
    if job is None:
        return error_response(404, "not_found", "Review job was not found")
    return StreamingResponse(
        _event_stream(job),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
