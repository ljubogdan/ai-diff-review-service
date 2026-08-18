# Submission notes

## Architecture

- FastAPI handles the public metadata and authenticated `/v1` HTTP contract.
- A modular review service owns asynchronous job lifecycle and orchestration.
- Unified diffs are parsed once into file and added-line domain objects.
- Files are grouped into chunks of at most 64 KiB without splitting a file.
- Providers share one async interface and receive parsed file chunks.
- `MockProvider` is deterministic and contains no model-dependent behavior.
- `LLMProvider` uses Gemini structured output and validates grounding.
- In-memory storage owns jobs, events, idempotency keys, and cache sources.
- An asyncio semaphore allows four processing jobs and queues further work.
- Stored ordered events provide both live SSE delivery and identical replay.

## Verification

The pytest suite exercises every mock rule, new-file line numbers, multi-file chunk boundaries, ordering/deduplication, truncation, public/private auth, all specified errors, idempotency conflicts, cache hits, SSE replay, 30-request rate-limit burst, four concurrent jobs with a queued fifth, and graceful unconfigured LLM behavior. The LLM request/structured-response path is tested through an in-process mock transport without exposing credentials. A production smoke test also verified auth, mock lifecycle, SSE replay, caching, idempotency, and a successful Gemini review end to end.

## AI use and judgment

I used OpenAI Codex to implement and test the service, and ChatGPT as a technical reviewer for architecture, contract, deployment, and security decisions. I did not accept the assumption that Gemini was already the configured provider; I verified the code first and then made an explicit migration decision. I also did not treat the existing passing tests as sufficient: I requested a scoring-oriented audit and targeted tests for live SSE, deduplication, findings across chunk boundaries, and an oversized single-file diff. Finally, I rejected emitting mock findings immediately in raw scan order because the contract requires globally sorted findings across chunks, so the pipeline completes the scan, deduplicates, sorts, and only then records finding events.

## With more time

I would add durable shared job/cache storage for multi-instance deployments, distributed rate limiting, graceful task draining during deploys, metrics/tracing, and provider retry policies with bounded backoff.
