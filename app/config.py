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
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = ""
    gemini_timeout_seconds: float = 25.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bearer_token=os.getenv("BEARER_TOKEN", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_base_url=os.getenv(
                "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
            ).rstrip("/"),
            gemini_model=os.getenv("GEMINI_MODEL", ""),
            gemini_timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "25")),
        )
