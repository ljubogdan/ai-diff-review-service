import asyncio
import time
from collections.abc import Iterator

import httpx
import pytest

from app.config import Settings
from app.main import create_app


TOKEN = "test-bearer-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> Iterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(Settings(bearer_token=TOKEN)))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


async def wait_for_job(client: httpx.AsyncClient, job_id: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await client.get(f"/v1/reviews/{job_id}", headers=AUTH)
        data = response.json()
        if data["status"] in ("done", "failed"):
            return data
        await asyncio.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not finish")
