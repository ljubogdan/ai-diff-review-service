from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["critical", "high", "medium", "low"]
Category = Literal["security", "correctness", "performance", "style"]
ProviderName = Literal["mock", "llm"]


class ReviewOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: ProviderName = "mock"
    maxFindings: int = Field(default=100, ge=0)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    diff: str
    options: ReviewOptions = Field(default_factory=ReviewOptions)


class Finding(BaseModel):
    id: str
    ruleId: str
    path: str
    line: int
    severity: Severity
    category: Category
    title: str
    evidence: str


class Usage(BaseModel):
    inputBytes: int
    chunks: int
    cacheHit: bool = False


@dataclass(frozen=True, slots=True)
class DiffLine:
    kind: Literal["added", "context"]
    text: str
    new_line: int


@dataclass(slots=True)
class DiffFile:
    path: str
    raw_bytes: int = 0
    lines: list[DiffLine] = field(default_factory=list)
