"""Diff parser for extracting modified file hunks and line ranges."""

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class DiffHunk:
    """Individual hunk within a git diff."""

    old_start: int
    old_length: int
    new_start: int
    new_length: int
    header: str
    lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FileDiff:
    """Diff for a single file in the pull request."""

    old_path: str
    new_path: str
    hunks: list[DiffHunk] = field(default_factory=list)
    raw_diff: str = ""

    def contains_new_line(self, line_number: int) -> bool:
        """Check if line_number falls within any new hunk range."""
        for hunk in self.hunks:
            if hunk.new_start <= line_number < hunk.new_start + hunk.new_length:
                return True
        return False


class DiffHunkParser:
    """Parses unified git diffs into structured file and hunk representations (AC-5)."""

    _HUNK_HEADER_RE = re.compile(
        r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$"
    )

    @classmethod
    def parse(cls, diff_text: str) -> dict[str, FileDiff]:
        """Parse unified diff string into mapping of file_path -> FileDiff."""
        files: dict[str, FileDiff] = {}
        current_file: FileDiff | None = None
        current_hunk: DiffHunk | None = None
        file_lines: list[str] = []

        lines = diff_text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith("diff --git "):
                if current_file:
                    current_file.raw_diff = "\n".join(file_lines)
                file_lines = [line]

                # Extract file paths
                parts = line.split(" ")
                old_p = parts[2][2:] if len(parts) > 2 else ""
                new_p = parts[3][2:] if len(parts) > 3 else ""

                current_file = FileDiff(old_path=old_p, new_path=new_p)
                files[new_p] = current_file
                current_hunk = None
                i += 1
                continue

            file_lines.append(line)

            match = cls._HUNK_HEADER_RE.match(line)
            if match and current_file:
                old_start = int(match.group(1))
                old_length = int(match.group(2) or 1)
                new_start = int(match.group(3))
                new_length = int(match.group(4) or 1)
                header = match.group(5).strip()

                current_hunk = DiffHunk(
                    old_start=old_start,
                    old_length=old_length,
                    new_start=new_start,
                    new_length=new_length,
                    header=header,
                )
                current_file.hunks.append(current_hunk)
                i += 1
                continue

            if current_hunk:
                current_hunk.lines.append(line)

            i += 1

        if current_file:
            current_file.raw_diff = "\n".join(file_lines)

        return files
