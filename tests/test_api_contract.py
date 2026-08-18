import httpx
import pytest

from app.config import Settings
from app.main import create_app
from tests.conftest import AUTH, TOKEN, wait_for_job


pytestmark = pytest.mark.anyio


DIFF = """diff --git a/src/z.ts b/src/z.ts
--- a/src/z.ts
+++ b/src/z.ts
@@ -0,0 +1,2 @@
+console.log("x")
+eval(input)
diff --git a/src/a.ts b/src/a.ts
--- a/src/a.ts
+++ b/src/a.ts
@@ -0,0 +10,1 @@
+// TODO
"""


async def test_public_metadata_and_v1_auth(client: httpx.AsyncClient) -> None:
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["version"] == "1.0.0"
    assert isinstance(health.json()["uptimeSeconds"], (int, float))

    assert (await client.get("/spec")).json() == {
        "specVersion": "1.0",
        "providers": ["mock", "llm"],
        "limits": {
            "maxPayloadBytes": 1_048_576,
            "chunkBytes": 65_536,
            "maxConcurrentJobs": 4,
            "rateLimitPerMinute": 30,
        },
    }
    unauthorized = await client.get("/v1/reviews/anything")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"
    wrong = await client.get("/v1/reviews/anything", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401


async def test_submit_poll_ordering_and_max_findings(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/reviews",
        headers=AUTH,
        json={"diff": DIFF, "options": {"provider": "mock", "maxFindings": 2}, "ignored": True},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

    result = await wait_for_job(client, response.json()["jobId"])
    assert result["status"] == "done"
    assert [(item["path"], item["line"], item["ruleId"]) for item in result["findings"]] == [
        ("src/a.ts", 10, "MOCK-008"),
        ("src/z.ts", 1, "MOCK-007"),
    ]
    assert result["usage"] == {"inputBytes": len(DIFF.encode()), "chunks": 1, "cacheHit": False}


async def test_idempotency_and_cache(client: httpx.AsyncClient) -> None:
    payload = {"diff": DIFF, "options": {"provider": "mock"}}
    headers = {**AUTH, "Idempotency-Key": "same-request"}
    first = await client.post("/v1/reviews", headers=headers, json=payload)
    repeat = await client.post("/v1/reviews", headers=headers, content=first.request.content)
    assert first.json()["jobId"] == repeat.json()["jobId"]
    await wait_for_job(client, first.json()["jobId"])

    conflict = await client.post(
        "/v1/reviews",
        headers=headers,
        json={"diff": DIFF, "options": {"provider": "mock", "maxFindings": 1}},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    cached = await client.post("/v1/reviews", headers=AUTH, json=payload)
    cached_result = await wait_for_job(client, cached.json()["jobId"])
    assert cached_result["usage"]["cacheHit"] is True
    first_result = await wait_for_job(client, first.json()["jobId"])
    assert cached_result["findings"] == first_result["findings"]


async def test_finished_sse_replays_identically(client: httpx.AsyncClient) -> None:
    submitted = await client.post("/v1/reviews", headers=AUTH, json={"diff": DIFF})
    job_id = submitted.json()["jobId"]
    result = await wait_for_job(client, job_id)

    first = await client.get(f"/v1/reviews/{job_id}/stream", headers=AUTH)
    second = await client.get(f"/v1/reviews/{job_id}/stream", headers=AUTH)
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert first.text == second.text
    assert first.text.count("event: finding\n") == len(result["findings"])
    assert "event: status\n" in first.text
    assert "event: done\n" in first.text


async def test_error_taxonomy(client: httpx.AsyncClient) -> None:
    invalid_json = await client.post(
        "/v1/reviews", headers={**AUTH, "Content-Type": "application/json"}, content=b"{"
    )
    assert (invalid_json.status_code, invalid_json.json()["error"]["code"]) == (400, "invalid_json")

    invalid_diff = await client.post("/v1/reviews", headers=AUTH, json={"diff": "not a diff"})
    assert (invalid_diff.status_code, invalid_diff.json()["error"]["code"]) == (422, "invalid_diff")

    missing = await client.get("/v1/reviews/missing", headers=AUTH)
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")

    too_large = await client.post(
        "/v1/reviews",
        headers={**AUTH, "Content-Type": "application/json"},
        content=b"x" * (1_048_576 + 1),
    )
    assert (too_large.status_code, too_large.json()["error"]["code"]) == (413, "payload_too_large")


async def test_rate_limit_allows_thirty_then_returns_429() -> None:
    transport = httpx.ASGITransport(app=create_app(Settings(bearer_token=TOKEN)))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(30):
            assert (await client.post("/v1/reviews", headers=AUTH, json={"diff": DIFF})).status_code == 202
        limited = await client.post("/v1/reviews", headers=AUTH, json={"diff": DIFF})
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "rate_limited"
        assert int(limited.headers["retry-after"]) >= 1


async def test_llm_without_configuration_fails_gracefully(client: httpx.AsyncClient) -> None:
    submitted = await client.post(
        "/v1/reviews",
        headers=AUTH,
        json={"diff": DIFF, "options": {"provider": "llm"}},
    )
    assert submitted.status_code == 202
    result = await wait_for_job(client, submitted.json()["jobId"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "internal"
    assert result["error"]["message"] == "Gemini provider is not configured"


async def test_chunk_usage_uses_file_boundaries(client: httpx.AsyncClient) -> None:
    padding = "x" * 39_000
    diff = (
        f"--- a/a.txt\n+++ b/a.txt\n@@ -0,0 +1,1 @@\n+{padding}\n"
        f"--- a/b.txt\n+++ b/b.txt\n@@ -0,0 +1,1 @@\n+{padding}\n"
    )
    submitted = await client.post("/v1/reviews", headers=AUTH, json={"diff": diff})
    result = await wait_for_job(client, submitted.json()["jobId"])
    assert result["usage"]["chunks"] == 2


async def test_unknown_v1_route_is_still_authenticated(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1")).status_code == 401
    assert (await client.get("/v1/unknown")).status_code == 401
    response = await client.get("/v1/unknown", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
