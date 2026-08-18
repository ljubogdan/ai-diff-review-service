# AI Diff Review Service

FastAPI service that accepts unified diffs, processes reviews asynchronously, and exposes polling and replayable SSE results. The deterministic `mock` provider implements the scoring contract; the `llm` provider uses the Google Gemini API.

## Local setup

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BEARER_TOKEN='local-development-token'
uvicorn app.main:app --reload
```

Public endpoints are `GET /health` and `GET /spec`. Every `/v1/*` request requires `Authorization: Bearer <BEARER_TOKEN>`.

Submit and poll a review:

```bash
curl -X POST http://localhost:8000/v1/reviews \
  -H 'Authorization: Bearer local-development-token' \
  -H 'Content-Type: application/json' \
  -d '{"diff":"--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+eval(value)\n"}'

curl -H 'Authorization: Bearer local-development-token' \
  http://localhost:8000/v1/reviews/JOB_ID
```

## Configuration

- `BEARER_TOKEN` — required for authenticated routes; protected routes return `401` when unset.
- `GEMINI_API_KEY` — server-side Gemini credential.
- `GEMINI_MODEL` — Gemini model available to that credential; `gemini-2.5-flash-lite` is a suitable free-tier choice.
- `GEMINI_BASE_URL` — optional API root, default `https://generativelanguage.googleapis.com/v1beta`.
- `GEMINI_TIMEOUT_SECONDS` — optional per-request timeout, default `25`.

The LLM path posts structured-output requests to Gemini's `generateContent` endpoint. Missing configuration, network failures, non-success responses, and invalid model output produce a `failed` job with a clear error; they do not crash the service. No secrets belong in the repository.

## Tests

```bash
pytest -q
```

Tests cover exact mock rules, diff line tracking, file-boundary chunking, auth, lifecycle, ordering, max findings, error taxonomy, idempotency, cache reuse, SSE replay, rate limiting, four-way concurrency, and graceful LLM failure.

## Deployment

`railway.toml` selects Railway's Railpack builder and provides the start command and `/health` check. `.python-version` pins Python 3.12. Configure the environment variables above in Railway, deploy the repository, then verify both providers end to end. Runtime jobs, idempotency records, rate-limit state, and cache entries are intentionally in-memory for this single-instance take-home service and reset on restart.
