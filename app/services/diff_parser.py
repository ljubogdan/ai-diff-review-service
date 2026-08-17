from __future__ import annotations

import re
import shlex

from app.models.domain import DiffFile, DiffLine


CHUNK_BYTES = 65_536
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class InvalidDiffError(ValueError):
    pass


def _path_from_header(header: str) -> str:
    value = header[4:].split("\t", 1)[0].strip()
    if value.startswith('"'):
        try:
            value = shlex.split(value)[0]
        except (ValueError, IndexError) as exc:
            raise InvalidDiffError("Malformed file path in diff") from exc
    if value == "/dev/null":
        return value
    if value.startswith("b/"):
        value = value[2:]
    if not value:
        raise InvalidDiffError("Missing file path in diff")
    return value


def parse_unified_diff(diff: str) -> list[DiffFile]:
    if not diff or not diff.strip():
        raise InvalidDiffError("Diff must not be empty")

    physical_lines = diff.splitlines(keepends=True)
    files: list[DiffFile] = []
    current: DiffFile | None = None
    pending_bytes = 0
    in_hunk = False
    new_line = 0
    old_remaining = 0
    new_remaining = 0
    saw_hunk = False
    awaiting_new_header = False

    for physical in physical_lines:
        line = physical.rstrip("\r\n")
        size = len(physical.encode("utf-8"))
        if in_hunk and old_remaining == 0 and new_remaining == 0:
            in_hunk = False

        if line.startswith("diff --git "):
            if in_hunk and (old_remaining or new_remaining):
                raise InvalidDiffError("Hunk contains fewer lines than declared")
            pending_bytes = size
            current = None
            in_hunk = False
            awaiting_new_header = False
            continue

        if line.startswith("--- ") and not in_hunk:
            if current is not None:
                current = None
            pending_bytes += size
            awaiting_new_header = True
            continue

        if line.startswith("+++ ") and not in_hunk:
            if not awaiting_new_header:
                pending_bytes += size
                continue
            current = DiffFile(path=_path_from_header(line), raw_bytes=pending_bytes + size)
            files.append(current)
            pending_bytes = 0
            awaiting_new_header = False
            continue

        if current is None:
            pending_bytes += size
            continue

        current.raw_bytes += size
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            if in_hunk and (old_remaining or new_remaining):
                raise InvalidDiffError("Hunk contains fewer lines than declared")
            new_line = int(hunk_match.group(3))
            old_remaining = int(hunk_match.group(2) or "1")
            new_remaining = int(hunk_match.group(4) or "1")
            in_hunk = True
            saw_hunk = True
            continue

        if not in_hunk:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current.lines.append(DiffLine("added", line[1:], new_line))
            new_line += 1
            new_remaining = max(0, new_remaining - 1)
        elif line.startswith("-") and not line.startswith("---"):
            old_remaining = max(0, old_remaining - 1)
            continue
        elif line.startswith(" "):
            current.lines.append(DiffLine("context", line[1:], new_line))
            new_line += 1
            old_remaining = max(0, old_remaining - 1)
            new_remaining = max(0, new_remaining - 1)
        elif line.startswith("\\ No newline at end of file"):
            continue
        else:
            raise InvalidDiffError("Malformed line inside diff hunk")

    valid_files = [file for file in files if file.path != "/dev/null"]
    if in_hunk and (old_remaining or new_remaining):
        raise InvalidDiffError("Hunk contains fewer lines than declared")
    if not files or not saw_hunk:
        raise InvalidDiffError("Body is not a parseable unified diff")
    return valid_files or files


def chunk_files(files: list[DiffFile], chunk_bytes: int = CHUNK_BYTES) -> list[list[DiffFile]]:
    chunks: list[list[DiffFile]] = []
    current: list[DiffFile] = []
    current_size = 0

    for file in files:
        if current and current_size + file.raw_bytes > chunk_bytes:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(file)
        current_size += file.raw_bytes
        if file.raw_bytes > chunk_bytes:
            chunks.append(current)
            current = []
            current_size = 0

    if current:
        chunks.append(current)
    return chunks or [[]]
