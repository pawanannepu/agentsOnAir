"""Pure domain guardrail policy evaluation and risky action classification."""

import fnmatch
import hashlib
import json
import posixpath
import shlex
from dataclasses import dataclass, field
from typing import Any

RISK_CATEGORIES: tuple[str, ...] = (
    "destructive_shell",
    "external_network",
    "sensitive_path_edit",
    "force_git_op",
    "large_diff",
)

DEFAULT_PROTECTED_BRANCHES: tuple[str, ...] = ("main", "master", "release/*")

DEFAULT_SENSITIVE_PATH_GLOBS: tuple[str, ...] = (
    ".github/workflows/**",
    ".gitlab-ci.yml",
    "**/.env*",
    "**/auth/**",
)

_EXTERNAL_NET_CMDS = frozenset({"curl", "wget", "nc", "ssh", "scp"})
_FILE_MUTATION_CMDS = frozenset({"tee", "cp", "mv", "rm", "touch", "install", "sed"})


@dataclass(frozen=True, slots=True)
class EffectiveGuardrailPolicy:
    """Resolved guardrail and budget policy for an org and repository."""

    protected_branches: tuple[str, ...] = DEFAULT_PROTECTED_BRANCHES
    protected_branch_guard: bool = True
    require_approval_for: tuple[str, ...] = RISK_CATEGORIES
    max_task_cost_cents: int = 500
    max_monthly_org_cost_cents: int = 10000
    timeout_minutes: int = 10
    max_cycles: int = 3
    network_egress_mode: str = "off_after_install"
    allowed_egress_domains: tuple[str, ...] = ()
    large_diff_lines_threshold: int = 500

    def to_dict(self) -> dict[str, Any]:
        """Serialize policy into a JSON-compatible dictionary."""
        return {
            "protected_branches": list(self.protected_branches),
            "protected_branch_guard": self.protected_branch_guard,
            "require_approval_for": list(self.require_approval_for),
            "max_task_cost_cents": self.max_task_cost_cents,
            "max_monthly_org_cost_cents": self.max_monthly_org_cost_cents,
            "timeout_minutes": self.timeout_minutes,
            "max_cycles": self.max_cycles,
            "network_egress_mode": self.network_egress_mode,
            "allowed_egress_domains": list(self.allowed_egress_domains),
            "large_diff_lines_threshold": self.large_diff_lines_threshold,
        }


@dataclass(frozen=True, slots=True)
class RiskClassification:
    """Outcome of classifying a sandbox or host action against guardrail policy."""

    decision: str  # "allow" | "require_approval" | "block"
    risk_category: str | None = None
    action_type: str | None = None
    action_hash: str | None = None
    action_summary: str = ""
    action_payload: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None


def _normalize_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    normalized = posixpath.normpath(cleaned)
    if normalized == ".":
        return ""
    return normalized.removeprefix("./")


def _matches_sensitive_glob(normalized_path: str, pattern: str) -> bool:
    if not normalized_path:
        return False
    candidate = normalized_path.lstrip("/")
    if fnmatch.fnmatchcase(candidate, pattern):
        return True
    if pattern.startswith("**/"):
        sub_pattern = pattern[3:]
        if fnmatch.fnmatchcase(candidate, sub_pattern):
            return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        if candidate == prefix or candidate.startswith(f"{prefix}/"):
            return True
        if pattern.startswith("**/"):
            inner_prefix = pattern[3:-3].rstrip("/")
            parts = candidate.split("/")
            if inner_prefix in parts:
                return True
    return False


def is_sensitive_path(path: str) -> bool:
    """Return True if path matches any sensitive CI, secret, or auth glob."""
    normalized = _normalize_path(path)
    return any(
        _matches_sensitive_glob(normalized, glob)
        for glob in DEFAULT_SENSITIVE_PATH_GLOBS
    )


def _split_shell_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {"&&", "||", ";", "|"}:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _extract_redirection_targets(tokens: list[str]) -> list[str]:
    targets: list[str] = []
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in {">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>"}:
            if idx + 1 < len(tokens):
                targets.append(tokens[idx + 1])
                idx += 2
                continue
        elif tok.startswith((">>", ">", "1>>", "1>")):
            stripped = tok.lstrip("012&>")
            if stripped:
                targets.append(stripped)
        idx += 1
    return targets


class PolicyEvaluator:
    """Domain service for policy merging, branch checks, and risk grading."""

    @staticmethod
    def merge_policy(
        org_settings: dict[str, Any] | None = None,
        repo_config: dict[str, Any] | None = None,
    ) -> EffectiveGuardrailPolicy:
        """Merge org settings and repository guardrails overrides over spec defaults."""
        merged: dict[str, Any] = EffectiveGuardrailPolicy().to_dict()

        if isinstance(org_settings, dict):
            for key in merged:
                if key in org_settings and org_settings[key] is not None:
                    merged[key] = org_settings[key]

        if isinstance(repo_config, dict):
            overrides = repo_config.get("guardrails")
            if isinstance(overrides, dict):
                for key in merged:
                    if key in overrides and overrides[key] is not None:
                        merged[key] = overrides[key]

        return EffectiveGuardrailPolicy(
            protected_branches=tuple(merged["protected_branches"]),
            protected_branch_guard=bool(merged["protected_branch_guard"]),
            require_approval_for=tuple(merged["require_approval_for"]),
            max_task_cost_cents=int(merged["max_task_cost_cents"]),
            max_monthly_org_cost_cents=int(merged["max_monthly_org_cost_cents"]),
            timeout_minutes=int(merged["timeout_minutes"]),
            max_cycles=int(merged["max_cycles"]),
            network_egress_mode=str(merged["network_egress_mode"]),
            allowed_egress_domains=tuple(merged["allowed_egress_domains"]),
            large_diff_lines_threshold=int(merged["large_diff_lines_threshold"]),
        )

    @staticmethod
    def compute_action_hash(
        cycle_number: int,
        action_type: str,
        payload: dict[str, Any],
    ) -> str:
        """Compute deterministic SHA-256 action hash for replay idempotency."""
        canonical = json.dumps(
            {
                "cycle_number": cycle_number,
                "action_type": action_type,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def is_protected_branch(branch_name: str, policy: EffectiveGuardrailPolicy) -> bool:
        """Strip refs/heads/ and match branch against protected_branches globs."""
        stripped = branch_name.strip()
        if stripped.startswith("refs/heads/"):
            stripped = stripped[len("refs/heads/") :]
        if not stripped:
            return False
        return any(
            fnmatch.fnmatchcase(stripped, pattern)
            for pattern in policy.protected_branches
        )

    @staticmethod
    def count_diff_lines(diff_text: str) -> int:
        """Count added and removed diff lines excluding file and hunk headers."""
        count = 0
        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+") or line.startswith("-"):
                count += 1
        return count

    def classify_file_write(
        self,
        path: str,
        policy: EffectiveGuardrailPolicy,
        cycle_number: int = 1,
    ) -> RiskClassification:
        """Classify a file write path against sensitive path globs."""
        normalized = _normalize_path(path)
        if is_sensitive_path(normalized) and (
            "sensitive_path_edit" in policy.require_approval_for
        ):
            payload = {"path": normalized}
            return RiskClassification(
                decision="require_approval",
                risk_category="sensitive_path_edit",
                action_type="sandbox_file_write",
                action_hash=self.compute_action_hash(
                    cycle_number, "sandbox_file_write", payload
                ),
                action_summary=f"Write to sensitive path '{normalized}'",
                action_payload=payload,
            )
        return RiskClassification(decision="allow")

    def classify_command(
        self,
        command: str,
        policy: EffectiveGuardrailPolicy,
        cycle_number: int = 1,
    ) -> RiskClassification:
        """Classify a shell command via shlex parsing against risky categories."""
        stripped_cmd = command.strip()
        if not stripped_cmd:
            return RiskClassification(decision="allow")

        try:
            tokens = shlex.split(stripped_cmd)
        except ValueError:
            tokens = stripped_cmd.split()

        segments = _split_shell_segments(tokens)
        payload = {"command": stripped_cmd}

        for segment in segments:
            if not segment:
                continue
            exe = posixpath.basename(segment[0]).lower()
            args = segment[1:]
            args_lower = [a.lower() for a in args]

            # 1. External network commands
            if exe in _EXTERNAL_NET_CMDS:
                if policy.network_egress_mode == "off_after_install":
                    return RiskClassification(
                        decision="block",
                        risk_category="external_network",
                        action_type="sandbox_command",
                        action_hash=self.compute_action_hash(
                            cycle_number, "sandbox_command", payload
                        ),
                        action_summary=(
                            f"Blocked outbound network '{exe}' while egress is off"
                        ),
                        action_payload=payload,
                        reason="external_network_blocked_by_egress_policy",
                    )
                if "external_network" in policy.require_approval_for:
                    return RiskClassification(
                        decision="require_approval",
                        risk_category="external_network",
                        action_type="sandbox_command",
                        action_hash=self.compute_action_hash(
                            cycle_number, "sandbox_command", payload
                        ),
                        action_summary=(
                            f"Execute external network command '{stripped_cmd}'"
                        ),
                        action_payload=payload,
                    )

            # 2. Git force / reset / rebase operations
            if exe == "git" and args_lower:
                sub = args_lower[0]
                has_force = any(
                    a in {"-f", "--force", "--force-with-lease"} for a in args_lower[1:]
                )
                is_hard_reset = sub == "reset" and "--hard" in args_lower[1:]
                is_force_push = sub == "push" and has_force
                is_rebase = sub == "rebase"

                if is_force_push or is_hard_reset or is_rebase:
                    if "force_git_op" in policy.require_approval_for:
                        return RiskClassification(
                            decision="require_approval",
                            risk_category="force_git_op",
                            action_type="sandbox_command",
                            action_hash=self.compute_action_hash(
                                cycle_number, "sandbox_command", payload
                            ),
                            action_summary=f"Execute git operation '{stripped_cmd}'",
                            action_payload=payload,
                        )
                    if (is_force_push or is_hard_reset) and (
                        "destructive_shell" in policy.require_approval_for
                    ):
                        return RiskClassification(
                            decision="require_approval",
                            risk_category="destructive_shell",
                            action_type="sandbox_command",
                            action_hash=self.compute_action_hash(
                                cycle_number, "sandbox_command", payload
                            ),
                            action_summary=(
                                f"Execute destructive git command '{stripped_cmd}'"
                            ),
                            action_payload=payload,
                        )

            # 3. Destructive shell commands
            is_destructive = False
            if exe == "rm":
                short_flags = "".join(
                    a[1:]
                    for a in args_lower
                    if a.startswith("-") and not a.startswith("--")
                )
                has_recursive = "r" in short_flags or "--recursive" in args_lower
                has_force_rm = "f" in short_flags or "--force" in args_lower
                if has_recursive and has_force_rm:
                    is_destructive = True
            elif exe == "mkfs" or exe.startswith("mkfs.") or exe == "dd":
                is_destructive = True
            elif exe == "chmod" and any(
                a in {"777", "0777", "a+rwx"} for a in args_lower
            ):
                is_destructive = True

            if is_destructive and "destructive_shell" in policy.require_approval_for:
                return RiskClassification(
                    decision="require_approval",
                    risk_category="destructive_shell",
                    action_type="sandbox_command",
                    action_hash=self.compute_action_hash(
                        cycle_number, "sandbox_command", payload
                    ),
                    action_summary=(
                        f"Execute destructive shell command '{stripped_cmd}'"
                    ),
                    action_payload=payload,
                )

            # 4. Sensitive path file mutations via shell redirection or file tools
            candidate_paths = _extract_redirection_targets(segment)
            if exe in _FILE_MUTATION_CMDS:
                candidate_paths.extend(a for a in args if not a.startswith("-"))
            for candidate in candidate_paths:
                if is_sensitive_path(candidate) and (
                    "sensitive_path_edit" in policy.require_approval_for
                ):
                    norm = _normalize_path(candidate)
                    file_payload = {"path": norm, "command": stripped_cmd}
                    return RiskClassification(
                        decision="require_approval",
                        risk_category="sensitive_path_edit",
                        action_type="sandbox_file_write",
                        action_hash=self.compute_action_hash(
                            cycle_number, "sandbox_file_write", file_payload
                        ),
                        action_summary=(
                            f"Modify sensitive path '{norm}' via shell command"
                        ),
                        action_payload=file_payload,
                    )

        return RiskClassification(decision="allow")

    def classify_publish(
        self,
        head_branch: str,
        diff_text: str,
        policy: EffectiveGuardrailPolicy,
        cycle_number: int = 1,
        force: bool = False,
    ) -> RiskClassification:
        """Classify host publish for branch protection, force push, and diff size."""
        if self.is_protected_branch(head_branch, policy):
            stripped = head_branch.strip().removeprefix("refs/heads/")
            return RiskClassification(
                decision="block",
                risk_category="protected_branch",
                action_type="host_publish",
                action_summary=(
                    f"Direct push to protected branch '{stripped}' is blocked"
                ),
                action_payload={"head_branch": stripped},
                reason="protected_branch_blocked",
            )

        if force and "force_git_op" in policy.require_approval_for:
            payload = {"head_branch": head_branch, "force": True}
            return RiskClassification(
                decision="require_approval",
                risk_category="force_git_op",
                action_type="host_force_push",
                action_hash=self.compute_action_hash(
                    cycle_number, "host_force_push", payload
                ),
                action_summary=f"Force push to branch '{head_branch}'",
                action_payload=payload,
            )

        diff_lines = self.count_diff_lines(diff_text)
        if diff_lines > policy.large_diff_lines_threshold and (
            "large_diff" in policy.require_approval_for
        ):
            payload = {
                "head_branch": head_branch,
                "diff_lines": diff_lines,
                "threshold": policy.large_diff_lines_threshold,
            }
            return RiskClassification(
                decision="require_approval",
                risk_category="large_diff",
                action_type="host_publish",
                action_hash=self.compute_action_hash(
                    cycle_number, "host_publish", payload
                ),
                action_summary=(
                    f"Publish large diff ({diff_lines} changed lines, "
                    f"threshold {policy.large_diff_lines_threshold})"
                ),
                action_payload=payload,
            )

        return RiskClassification(decision="allow")
