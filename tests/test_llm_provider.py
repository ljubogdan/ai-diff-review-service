import asyncio
import json

import httpx

from app.config import Settings
from app.providers.llm import LLMProvider
from app.services.diff_parser import parse_unified_diff


DIFF = "--- a/app.py\n+++ b/app.py\n@@ -0,0 +1 @@\n+eval(user_input)\n"


def test_llm_provider_uses_responses_api_and_validates_grounding() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://llm.example/v1/responses"
        assert request.headers["authorization"] == "Bearer secret-key"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["text"]["format"]["type"] == "json_schema"
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
            json={"output": [{"content": [{"type": "output_text", "text": json.dumps(output)}]}]},
        )

    async def scenario() -> None:
        provider = LLMProvider(
            Settings(
                llm_api_key="secret-key",
                llm_base_url="https://llm.example/v1",
                llm_model="test-model",
            ),
            transport=httpx.MockTransport(handler),
        )
        findings = await provider.analyze(parse_unified_diff(DIFF))
        assert len(findings) == 1
        assert findings[0].id == "LLM-SEC-001:app.py:1"

    asyncio.run(scenario())
