from __future__ import annotations

import os
from dataclasses import dataclass


VERSION = "1.0.0"
MAX_PAYLOAD_BYTES = 1_048_576
CHUNK_BYTES = 65_536
MAX_CONCURRENT_JOBS = 4
RATE_LIMIT_PER_MINUTE = 30


@dataclass(frozen=True, slots=True)
class Settings:
    bearer_token: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    llm_timeout_seconds: float = 25.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bearer_token=os.getenv("BEARER_TOKEN", ""),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_model=os.getenv("LLM_MODEL", ""),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "25")),
        )
