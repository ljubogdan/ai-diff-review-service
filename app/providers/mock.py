from __future__ import annotations

import re

from app.models.domain import DiffFile, DiffLine, Finding
from app.providers.base import ReviewProvider


_CREDENTIAL_RE = re.compile(
    r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
    re.IGNORECASE,
)
_SQL_RE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_STRING_RE = re.compile(r"(['\"])(.*?)\1")
_EMPTY_CATCH_RE = re.compile(
    r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*(?:(?://[^\n]*\n)|(?:/\*.*?\*/\s*))*\}",
    re.DOTALL,
)

_RULES = (
    ("MOCK-001", "critical", "security", "eval usage", lambda text: "eval(" in text),
    ("MOCK-002", "critical", "security", "hardcoded credential", lambda text: bool(_CREDENTIAL_RE.search(text))),
    ("MOCK-003", "high", "security", "SQL string concatenation", lambda text: _sql_concatenation(text)),
    ("MOCK-005", "medium", "correctness", "loose null comparison", lambda text: "== null" in text or "!= null" in text),
    ("MOCK-006", "medium", "performance", "deep-clone via JSON", lambda text: "JSON.parse(JSON.stringify(" in text),
    ("MOCK-007", "low", "style", "console.log left in", lambda text: "console.log(" in text),
    ("MOCK-008", "low", "style", "unresolved marker", lambda text: "TODO" in text or "FIXME" in text),
    (
        "MOCK-INJ",
        "critical",
        "security",
        "prompt-injection content",
        lambda text: any(
            phrase in text.lower()
            for phrase in ("ignore previous instructions", "disregard all prior", "you are now")
        ),
    ),
)


def _sql_concatenation(text: str) -> bool:
    return "+" in text and any(_SQL_RE.search(match.group(2)) for match in _STRING_RE.finditer(text))


def _empty_catch(lines: list[DiffLine], index: int) -> bool:
    if lines[index].kind != "added" or not re.search(r"\bcatch\b", lines[index].text):
        return False
    window: list[str] = []
    for line in lines[index : index + 25]:
        window.append(line.text)
        candidate = "\n".join(window)
        if _EMPTY_CATCH_RE.search(candidate):
            return True
    return False


def _finding(rule_id: str, severity: str, category: str, title: str, file: DiffFile, line: DiffLine) -> Finding:
    return Finding(
        id=f"{rule_id}:{file.path}:{line.new_line}",
        ruleId=rule_id,
        path=file.path,
        line=line.new_line,
        severity=severity,
        category=category,
        title=title,
        evidence=line.text,
    )


class MockProvider(ReviewProvider):
    async def analyze(self, files: list[DiffFile]) -> list[Finding]:
        findings: list[Finding] = []
        for file in files:
            for index, line in enumerate(file.lines):
                if line.kind != "added":
                    continue
                for rule_id, severity, category, title, matches in _RULES:
                    if matches(line.text):
                        findings.append(_finding(rule_id, severity, category, title, file, line))
                if _empty_catch(file.lines, index):
                    findings.append(
                        _finding("MOCK-004", "high", "correctness", "swallowed exception", file, line)
                    )
        return findings
