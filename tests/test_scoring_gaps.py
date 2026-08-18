import asyncio
import json

import httpx
import pytest

from app.api.routes import _event_stream
from app.models.domain import DiffFile, Finding, ReviewOptions
from app.providers.base import ReviewProvider
from app.services.reviews import ReviewService
from tests.conftest import AUTH, wait_for_job


pytestmark = pytest.mark.anyio
SMALL_DIFF = "--- a/live.py\n+++ b/live.py\n@@ -0,0 +1 @@\n+value = 1\n"


def _finding() -> Finding:
    return Finding(
        id="TEST-001:live.py:1",
        ruleId="TEST-001",
        path="live.py",
        line=1,
        severity="low",
        category="style",
        title="test finding",
        evidence="value = 1",
    )


class ControlledProvider(ReviewProvider):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(self, files: list[DiffFile]) -> list[Finding]:
        self.started.set()
        await self.release.wait()
        return [_finding()]


class DuplicateProvider(ReviewProvider):
    async def analyze(self, files: list[DiffFile]) -> list[Finding]:
        finding = _finding()
        return [finding, finding.model_copy()]


async def test_live_sse_emits_status_before_processing_finishes() -> None:
    provider = ControlledProvider()
    service = ReviewService({"mock": provider})
    job = await service.submit(SMALL_DIFF, ReviewOptions(), b"live-body", None)
    stream = _event_stream(job)

    queued = await asyncio.wait_for(anext(stream), timeout=1)
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    running = await asyncio.wait_for(anext(stream), timeout=1)

    assert job.status == "running"
    assert 'data: {"status":"queued"}' in queued
    assert 'data: {"status":"running"}' in running

    provider.release.set()
    remaining = [event async for event in stream]
    assert [event.splitlines()[0] for event in remaining] == [
        "event: finding",
        "event: status",
        "event: done",
    ]


async def test_duplicate_finding_ids_are_emitted_once() -> None:
    service = ReviewService({"mock": DuplicateProvider()})
    job = await service.submit(SMALL_DIFF, ReviewOptions(), b"dedup-body", None)
    await asyncio.wait_for(job.wait_until_terminal(), timeout=1)

    assert job.status == "done"
    assert [finding.id for finding in job.findings] == ["TEST-001:live.py:1"]
    assert sum(event.name == "finding" for event in job.events) == 1


async def test_findings_survive_file_boundary_chunking(client: httpx.AsyncClient) -> None:
    padding = "x" * 38_900
    diff = (
        f"--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+TODO {padding}\n"
        f"--- a/b.py\n+++ b/b.py\n@@ -0,0 +1 @@\n+console.log(value) {padding}\n"
    )
    submitted = await client.post("/v1/reviews", headers=AUTH, json={"diff": diff})
    assert submitted.status_code == 202
    result = await wait_for_job(client, submitted.json()["jobId"])

    assert result["status"] == "done"
    assert result["usage"]["chunks"] == 2
    assert [(finding["path"], finding["ruleId"]) for finding in result["findings"]] == [
        ("a.py", "MOCK-008"),
        ("b.py", "MOCK-007"),
    ]


async def test_oversized_single_file_is_one_chunk_and_keeps_findings(
    client: httpx.AsyncClient,
) -> None:
    padding = "x" * 70_000
    diff = f"--- a/large.py\n+++ b/large.py\n@@ -0,0 +1,2 @@\n+{padding}\n+eval(value)\n"
    body = json.dumps({"diff": diff}, separators=(",", ":")).encode()

    submitted = await client.post(
        "/v1/reviews",
        headers={**AUTH, "Content-Type": "application/json"},
        content=body,
    )
    assert submitted.status_code == 202
    result = await wait_for_job(client, submitted.json()["jobId"])

    assert result["status"] == "done"
    assert result["usage"] == {
        "inputBytes": len(diff.encode()),
        "chunks": 1,
        "cacheHit": False,
    }
    assert [(finding["ruleId"], finding["path"], finding["line"]) for finding in result["findings"]] == [
        ("MOCK-001", "large.py", 2)
    ]
