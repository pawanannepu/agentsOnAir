"""Application service for custom review rules, examples, and preference learning."""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache

from app.application.services.diff_hunk_parser import DiffHunkParser
from app.core.redaction import redact_credentials, sanitize_prompt_text
from app.domain.entities.review_example import ReviewExample
from app.domain.entities.review_feedback import (
    ReviewFindingFeedback,
    ReviewLearnedPreference,
)
from app.domain.entities.review_rule import EffectiveReviewRule

AUTO_DEFAULT_PREF_PREFIX = "Dismissed finding pattern:"

_SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "major": 3,
    "minor": 2,
    "info": 1,
}


@lru_cache(maxsize=1)
def _get_tiktoken_encoding():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base with len // 4 fallback."""
    if not text:
        return 0
    enc = _get_tiktoken_encoding()
    if enc is not None:
        try:
            return max(1, len(enc.encode(text)))
        except Exception:
            pass
    return max(1, len(text) // 4)


@lru_cache(maxsize=512)
def _compile_globstar(pattern: str) -> re.Pattern[str]:
    """Compile a globstar-aware pattern where `**/*` matches root and nested files."""
    norm = pattern.strip().lstrip("./").lstrip("/")
    if not norm:
        return re.compile(r"^$")

    regex_parts: list[str] = ["^"]
    i = 0
    n = len(norm)
    while i < n:
        ch = norm[i]
        if ch == "*":
            if i + 1 < n and norm[i + 1] == "*":
                if i + 2 < n and norm[i + 2] == "/":
                    # `**/` matches zero or more directory prefixes
                    regex_parts.append("(?:.+/)?")
                    i += 3
                    continue
                regex_parts.append(".*")
                i += 2
                continue
            regex_parts.append("[^/]*")
            i += 1
        elif ch == "?":
            regex_parts.append("[^/]")
            i += 1
        elif ch == "[":
            end = norm.find("]", i + 1)
            if end == -1:
                regex_parts.append(re.escape(ch))
                i += 1
            else:
                body = norm[i + 1 : end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                regex_parts.append(f"[{body}]")
                i = end + 1
        else:
            regex_parts.append(re.escape(ch))
            i += 1
    regex_parts.append("$")
    return re.compile("".join(regex_parts))


class ReviewContextService:
    """Pure matching, ranking, redaction, and XML formatting helpers."""

    @staticmethod
    def matches_path_glob(file_path: str, pattern: str) -> bool:
        """Globstar-aware matcher ensuring `**/*` matches root files too."""
        norm_path = file_path.strip().lstrip("./").lstrip("/")
        return bool(_compile_globstar(pattern).match(norm_path))

    @classmethod
    def rule_matches_files(
        cls, rule: EffectiveReviewRule, file_paths: Sequence[str]
    ) -> bool:
        """Return True if the rule applies to at least one modified file."""
        globs = rule.path_globs or ["**/*"]
        if not file_paths:
            return any(cls.matches_path_glob("README.md", g) for g in globs)
        return any(
            cls.matches_path_glob(path, glob) for path in file_paths for glob in globs
        )

    @classmethod
    def select_matching_rules(
        cls,
        merged_rules: Sequence[EffectiveReviewRule],
        modified_files: Sequence[str],
        max_rules: int = 25,
    ) -> list[EffectiveReviewRule]:
        """Filter enabled matching rules (severity DESC, repo first, created_at ASC)."""
        matching = [
            rule
            for rule in merged_rules
            if rule.is_enabled and cls.rule_matches_files(rule, modified_files)
        ]
        matching.sort(
            key=lambda r: (
                -_SEVERITY_RANK.get(r.severity, 0),
                0 if r.scope == "repo" else 1,
                r.created_at or datetime.min.replace(tzinfo=UTC),
            )
        )
        return matching[:max_rules]

    @staticmethod
    def top_level_dir(file_path: str) -> str:
        """Return top-level directory or `__root__` for root files."""
        norm = file_path.strip().lstrip("./").lstrip("/")
        if "/" not in norm:
            return "__root__"
        return norm.split("/", 1)[0] or "__root__"

    @classmethod
    def compute_pattern_key(
        cls, rule_id: uuid.UUID | None, category: str, file_path: str
    ) -> str:
        """Compute canonical pattern key (`rule:{id}` or `{category}:{top_dir}`)."""
        if rule_id is not None:
            return f"rule:{rule_id}"
        return f"{category}:{cls.top_level_dir(file_path)}"

    @staticmethod
    def is_preference_injectable(
        pref: ReviewLearnedPreference,
        source_feedback: ReviewFindingFeedback | None,
    ) -> bool:
        """Return True when a preference should be injected into reviewer prompts."""
        if pref.status == "suppressed":
            return False
        if pref.status == "dampened":
            return True
        if source_feedback is not None and (
            source_feedback.remember_preference
            or bool((source_feedback.reason or "").strip())
        ):
            return True
        return not pref.instruction.startswith(AUTO_DEFAULT_PREF_PREFIX)

    @classmethod
    def select_matching_preferences(
        cls,
        preferences: Sequence[
            tuple[ReviewLearnedPreference, ReviewFindingFeedback | None]
        ],
        active_rule_ids: set[uuid.UUID],
        modified_files: Sequence[str],
    ) -> tuple[list[ReviewLearnedPreference], set[str], set[str]]:
        """Return (injectable_preferences, dampened_keys, suppressed_keys)."""
        modified_dirs = {cls.top_level_dir(p) for p in modified_files}
        injectable: list[ReviewLearnedPreference] = []
        dampened_keys: set[str] = set()
        suppressed_keys: set[str] = set()

        for pref, source_fb in preferences:
            if pref.status == "dampened":
                dampened_keys.add(pref.pattern_key)
            elif pref.status == "suppressed":
                suppressed_keys.add(pref.pattern_key)

            if not cls.is_preference_injectable(pref, source_fb):
                continue

            if pref.rule_id is not None:
                if pref.rule_id in active_rule_ids or not modified_files:
                    injectable.append(pref)
            else:
                suffix = (
                    pref.pattern_key.split(":", 1)[1]
                    if ":" in pref.pattern_key
                    else pref.pattern_key
                )
                if not modified_files or suffix in modified_dirs:
                    injectable.append(pref)

        injectable.sort(
            key=lambda p: (
                0 if p.status == "dampened" else 1,
                -(p.last_feedback_at.timestamp() if p.last_feedback_at else 0.0),
            )
        )
        return injectable, dampened_keys, suppressed_keys

    @staticmethod
    def rank_examples(
        examples: Sequence[ReviewExample],
        modified_files: Sequence[str],
        limit: int = 5,
    ) -> list[ReviewExample]:
        """Rank curated example PRs by file overlap count DESC then updated_at DESC."""
        mod_set = {p.strip().lstrip("./").lstrip("/") for p in modified_files}

        def _score(ex: ReviewExample) -> tuple[int, float]:
            ex_set = {p.strip().lstrip("./").lstrip("/") for p in ex.modified_files}
            overlap = len(mod_set & ex_set) if mod_set else 0
            ts = ex.updated_at.timestamp() if ex.updated_at else 0.0
            return (-overlap, -ts)

        ranked = sorted(examples, key=_score)
        return ranked[:limit]

    @staticmethod
    def build_diff_summary_and_files(
        diff_text: str, max_tokens: int = 1500
    ) -> tuple[list[str], str, int]:
        """Extract modified_files, redact secrets, and cap summary at max_tokens."""
        file_diffs = DiffHunkParser.parse(diff_text)
        modified_files = list(file_diffs.keys())
        if not modified_files and not diff_text.strip():
            return [], "", 0

        redacted = redact_credentials(diff_text)
        if count_tokens(redacted) <= max_tokens:
            return modified_files, redacted, count_tokens(redacted)

        # Preserve file headers across chunks while staying within max_tokens
        sections: list[str] = []
        used_tokens = 0
        for file_path, fdiff in file_diffs.items():
            raw_redacted = redact_credentials(fdiff.raw_diff)
            lines = raw_redacted.splitlines()
            header_lines = [
                ln
                for ln in lines
                if ln.startswith(("diff --git ", "--- ", "+++ ", "@@ "))
            ][:4]
            header_block = (
                "\n".join(header_lines) if header_lines else f"+++ {file_path}"
            )
            header_tokens = count_tokens(header_block)
            if used_tokens + header_tokens > max_tokens:
                break

            kept_lines: list[str] = []
            running = header_block
            for ln in lines:
                candidate = f"{running}\n{ln}" if kept_lines else ln
                if used_tokens + count_tokens(candidate) > max_tokens:
                    break
                kept_lines.append(ln)
                running = "\n".join(kept_lines)

            block = "\n".join(kept_lines) if kept_lines else header_block
            block_tokens = count_tokens(block)
            if used_tokens + block_tokens <= max_tokens:
                sections.append(block)
                used_tokens += block_tokens
            elif used_tokens + header_tokens <= max_tokens:
                sections.append(header_block)
                used_tokens += header_tokens

        summary = "\n\n".join(sections)
        if not summary and redacted:
            # Fallback character truncation preserving start
            approx_chars = max_tokens * 4
            summary = redacted[:approx_chars]
        return modified_files, summary, count_tokens(summary)

    @staticmethod
    def format_rule_entry(rule: EffectiveReviewRule | dict) -> str:
        """Render a single rule inside sanitized text for `<custom_rules>`."""
        if isinstance(rule, dict):
            rid = str(rule.get("id", ""))
            sev = sanitize_prompt_text(str(rule.get("severity", "minor")))
            cat = sanitize_prompt_text(str(rule.get("category", "architecture")))
            title = sanitize_prompt_text(str(rule.get("title", "")))
            inst = sanitize_prompt_text(str(rule.get("instruction", "")))
            raw_globs = rule.get("path_globs") or ["**/*"]
            globs = ", ".join(sanitize_prompt_text(str(g)) for g in raw_globs)
        else:
            rid = str(rule.id)
            sev = sanitize_prompt_text(rule.severity)
            cat = sanitize_prompt_text(rule.category)
            title = sanitize_prompt_text(rule.title)
            inst = sanitize_prompt_text(rule.instruction)
            globs = ", ".join(sanitize_prompt_text(g) for g in rule.path_globs)
        return (
            f'- rule_id="{rid}" severity="{sev}" category="{cat}" '
            f'paths="{globs}" title="{title}": {inst}'
        )

    @staticmethod
    def format_preference_entry(pref: ReviewLearnedPreference | dict) -> str:
        """Render a single learned preference for `<team_preferences>`."""
        if isinstance(pref, dict):
            pkey = sanitize_prompt_text(str(pref.get("pattern_key", "")))
            status = sanitize_prompt_text(str(pref.get("status", "active")))
            inst = sanitize_prompt_text(str(pref.get("instruction", "")))
        else:
            pkey = sanitize_prompt_text(pref.pattern_key)
            status = sanitize_prompt_text(pref.status)
            inst = sanitize_prompt_text(pref.instruction)
        return f'- pattern="{pkey}" status="{status}": {inst}'

    @staticmethod
    def format_example_entry(example: ReviewExample | dict) -> str:
        """Render a single example PR inside sanitized text for `<example_prs>`."""
        if isinstance(example, dict):
            pr_num = example.get("pr_number", 0)
            cls_name = sanitize_prompt_text(str(example.get("classification", "good")))
            title = sanitize_prompt_text(str(example.get("pr_title", "")))
            note = sanitize_prompt_text(str(example.get("guidance_note", "")))
            diff_summary = sanitize_prompt_text(
                str(example.get("cached_diff_summary") or "")
            )
        else:
            pr_num = example.pr_number
            cls_name = sanitize_prompt_text(example.classification)
            title = sanitize_prompt_text(example.pr_title)
            note = sanitize_prompt_text(example.guidance_note)
            diff_summary = sanitize_prompt_text(example.cached_diff_summary or "")

        parts = [f'- PR #{pr_num} classification="{cls_name}" title="{title}"']
        parts.append(f"  Guidance: {note}")
        if diff_summary:
            parts.append(f"  Diff excerpt:\n{diff_summary}")
        return "\n".join(parts)
