"""Two tier context budget allocator for full repository reviews."""

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from app.application.services.diff_hunk_parser import DiffHunkParser
from app.application.services.symbol_indexer import SymbolCallGraph


@dataclass(slots=True)
class AssembledReviewContext:
    """Assembled prompt context bounded to 64k tokens."""

    tier1_content: str
    tier2_content: str
    total_token_count: int
    omitted_files: list[str] = field(default_factory=list)
    included_symbols: list[str] = field(default_factory=list)


class ContextBudgetAllocator:
    """Packs diff and repository symbols within strict token budgets (AC-3).

    - Tier 1: Diff hunks + root AGENTS.md (up to 32k tokens)
    - Tier 2: Callers, callees, enclosing types (up to 28k tokens)
    - Reserve: 4k tokens for model completion
    """

    TIER1_MAX_TOKENS = 32000
    TIER2_MAX_TOKENS = 28000
    TOTAL_BUDGET = 64000

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """Estimate token count (~4 characters per token heuristic)."""
        return max(1, len(text) // 4)

    @classmethod
    def _is_file_ignored(cls, file_path: str, ignored_patterns: list[str]) -> bool:
        """Check if file matches any ignored wildcard or path pattern."""
        for pat in ignored_patterns:
            if fnmatch.fnmatch(file_path, pat) or fnmatch.fnmatch(
                file_path, f"*/{pat}"
            ):
                return True
            clean = pat.replace("*", "")
            if clean and (file_path.startswith(clean) or file_path.endswith(clean)):
                return True
        return False

    @classmethod
    def assemble_context(
        cls,
        diff_text: str,
        symbol_graph: SymbolCallGraph,
        repo_dir: str | Path,
        agents_md_text: str | None = None,
        ignored_patterns: list[str] | None = None,
    ) -> AssembledReviewContext:
        file_diffs = DiffHunkParser.parse(diff_text)
        ignored = ignored_patterns or ["*.lock", "dist/**", "node_modules/**"]

        # 1. Tier 1: Core diff hunks and AGENTS.md
        tier1_parts: list[str] = []
        omitted_files: list[str] = []

        if agents_md_text:
            agents_capped = agents_md_text[: 4000 * 4]  # cap at ~4k tokens
            tier1_parts.append(f"# Project Guidelines (AGENTS.md)\n{agents_capped}\n")

        tier1_parts.append("# Pull Request Diff\n")
        tier1_tokens = sum(cls.estimate_tokens(p) for p in tier1_parts)

        modified_files: list[str] = []
        for file_path, fdiff in file_diffs.items():
            if cls._is_file_ignored(file_path, ignored):
                omitted_files.append(file_path)
                continue

            diff_tokens = cls.estimate_tokens(fdiff.raw_diff)
            if tier1_tokens + diff_tokens <= cls.TIER1_MAX_TOKENS:
                tier1_parts.append(fdiff.raw_diff)
                tier1_tokens += diff_tokens
                modified_files.append(file_path)
            else:
                omitted_files.append(file_path)

        tier1_content = "\n\n".join(tier1_parts)

        # 2. Tier 2: Symbol graph expansion (callers, callees, enclosing classes)
        tier2_parts: list[str] = ["# Repository Context & Symbols (Beyond Diff)\n"]
        tier2_tokens = cls.estimate_tokens(tier2_parts[0])
        included_symbols: list[str] = []

        # Find symbols in modified files
        target_symbol_keys: set[str] = set()
        for mod_file in modified_files:
            if mod_file in symbol_graph.file_symbols:
                target_symbol_keys.update(symbol_graph.file_symbols[mod_file])

        # Gather callers and callees
        related_symbol_keys: set[str] = set()
        for sym_key in target_symbol_keys:
            sym = symbol_graph.symbols.get(sym_key)
            if not sym:
                continue

            # Callers of this symbol
            if sym.name in symbol_graph.callers:
                related_symbol_keys.update(symbol_graph.callers[sym.name])

            # Callees called by this symbol
            if sym_key in symbol_graph.calls:
                for callee_name in symbol_graph.calls[sym_key]:
                    # Find callee definitions in graph
                    for k, s in symbol_graph.symbols.items():
                        if s.name == callee_name:
                            related_symbol_keys.add(k)

        # Pruning sequence: include callers and callees up to TIER2_MAX_TOKENS
        for sym_key in related_symbol_keys - target_symbol_keys:
            sym = symbol_graph.symbols.get(sym_key)
            if not sym:
                continue

            block = (
                f"### {sym.kind.capitalize()}: `{sym.name}` "
                f"({sym.file_path}:{sym.line_number})\n"
                f"Signature: `{sym.signature}`\n"
            )
            if sym.docstring:
                block += f"Docstring: {sym.docstring}\n"

            block_tokens = cls.estimate_tokens(block)
            if tier2_tokens + block_tokens <= cls.TIER2_MAX_TOKENS:
                tier2_parts.append(block)
                tier2_tokens += block_tokens
                included_symbols.append(sym_key)
            else:
                break

        tier2_content = "\n".join(tier2_parts)
        total_tokens = tier1_tokens + tier2_tokens

        return AssembledReviewContext(
            tier1_content=tier1_content,
            tier2_content=tier2_content,
            total_token_count=total_tokens,
            omitted_files=omitted_files,
            included_symbols=included_symbols,
        )
