import asyncio

from app.models.domain import DiffFile, Finding, ReviewOptions
from app.providers.base import ReviewProvider
from app.services.reviews import ReviewService


DIFF = "--- a/a\n+++ b/a\n@@ -0,0 +1 @@\n+x\n"


class BlockingProvider(ReviewProvider):
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.four_started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(self, files: list[DiffFile]) -> list[Finding]:
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active == 4:
            self.four_started.set()
        await self.release.wait()
        self.active -= 1
        return []


def test_four_jobs_run_concurrently_and_fifth_waits() -> None:
    async def scenario() -> None:
        provider = BlockingProvider()
        service = ReviewService({"mock": provider}, max_concurrent_jobs=4)
        jobs = []
        for index in range(5):
            diff = DIFF.replace("+x", f"+x{index}")
            jobs.append(await service.submit(diff, ReviewOptions(), f"body-{index}".encode(), None))
        await asyncio.wait_for(provider.four_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert provider.peak == 4
        assert sum(job.status == "running" for job in jobs) == 4
        assert sum(job.status == "queued" for job in jobs) == 1
        provider.release.set()
        await asyncio.gather(*service.tasks)
        assert all(job.status == "done" for job in jobs)

    asyncio.run(scenario())
