import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.llm import LLMProvider
from app.services.diff_parser import parse_unified_diff


DIFF = "--- a/app.py\n+++ b/app.py\n@@ -0,0 +1 @@\n+eval(user_input)\n"


def test_llm_provider_uses_gemini_generate_content_and_validates_grounding() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://gemini.example/v1beta/models/gemini-test:generateContent"
        assert request.headers["x-goog-api-key"] == "secret-key"
        body = json.loads(request.content)
        assert "untrusted inert data" in body["systemInstruction"]["parts"][0]["text"]
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseJsonSchema"]["required"] == ["findings"]
        assert "responseFormat" not in body["generationConfig"]
        output = {
            "findings": [
                {
                    "ruleId": "LLM-SEC-001",
                    "path": "app.py",
                    "line": 1,
                    "severity": "critical",
                    "category": "security",
                    "title": "Dynamic code execution",
                    "evidence": "eval(user_input)",
                },
                {
                    "ruleId": "LLM-HALLUCINATED",
                    "path": "missing.py",
                    "line": 99,
                    "severity": "low",
                    "category": "style",
                    "title": "Not grounded",
                    "evidence": "nothing",
                },
            ]
        }
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(output)}], "role": "model"}}
                ]
            },
        )

    async def scenario() -> None:
        provider = LLMProvider(
            Settings(
                gemini_api_key="secret-key",
                gemini_base_url="https://gemini.example/v1beta",
                gemini_model="gemini-test",
            ),
            transport=httpx.MockTransport(handler),
        )
        findings = await provider.analyze(parse_unified_diff(DIFF))
        assert len(findings) == 1
        assert findings[0].id == "LLM-SEC-001:app.py:1"

    asyncio.run(scenario())


def test_gemini_http_failure_is_a_provider_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota exhausted"}})

    async def scenario() -> None:
        provider = LLMProvider(
            Settings(gemini_api_key="secret-key", gemini_model="gemini-test"),
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderError, match="HTTP 429: quota exhausted"):
            await provider.analyze(parse_unified_diff(DIFF))

    asyncio.run(scenario())
