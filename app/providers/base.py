from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.domain import DiffFile, Finding


class ProviderError(RuntimeError):
    pass


class ReviewProvider(ABC):
    @abstractmethod
    async def analyze(self, files: list[DiffFile]) -> list[Finding]:
        raise NotImplementedError
