# Submission notes

## Architecture

- FastAPI handles the public metadata and authenticated `/v1` HTTP contract.
- A modular review service owns asynchronous job lifecycle and orchestration.
- Unified diffs are parsed once into file and added-line domain objects.
- Files are grouped into chunks of at most 64 KiB without splitting a file.
- Providers share one async interface and receive parsed file chunks.
- `MockProvider` is deterministic and contains no model-dependent behavior.
- `LLMProvider` uses structured Responses API output and validates grounding.
- In-memory storage owns jobs, events, idempotency keys, and cache sources.
- An asyncio semaphore allows four processing jobs and queues further work.
- Stored ordered events provide both live SSE delivery and identical replay.

## Verification

The pytest suite exercises every mock rule, new-file line numbers, multi-file chunk boundaries, ordering/deduplication, truncation, public/private auth, all specified errors, idempotency conflicts, cache hits, SSE replay, 30-request rate-limit burst, four concurrent jobs with a queued fifth, and graceful unconfigured LLM behavior. The LLM request/structured-response path is tested through an in-process mock transport without exposing credentials.

## AI use and judgment

OpenAI Codex was used to implement and test the service. I kept the suggested provider abstraction and event log. I rejected emitting mock findings immediately in raw scan order: the contract requires globally sorted findings across chunks, so the pipeline completes the scan, deduplicates and sorts, and only then records finding events.

## With more time

I would add durable shared job/cache storage for multi-instance deployments, distributed rate limiting, graceful task draining during deploys, metrics/tracing, and provider retry policies with bounded backoff.
