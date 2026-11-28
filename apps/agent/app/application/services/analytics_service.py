"""PostgreSQL analytics aggregation service for reviews, tasks, rules, and AI costs."""

import json
import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.exceptions import NotFoundError
from app.infrastructure.db.models.pr_review_finding import PRReviewFindingModel
from app.infrastructure.db.models.pull_request_review import PullRequestReviewModel
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.review_rule import ReviewRuleModel
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.models.task_run import TaskRunModel
from app.infrastructure.db.models.usage_event import UsageEventModel

logger = logging.getLogger(__name__)


async def _get_cached_analytics(cache_key: str) -> dict[str, Any] | None:
    ttl = settings.ANALYTICS_CACHE_TTL_SECONDS
    if ttl <= 0 or not settings.REDIS_URL:
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.15,
            socket_timeout=0.5,
        )
        try:
            raw = await client.get(cache_key)
            if raw:
                return json.loads(raw)
        finally:
            await client.aclose()
    except Exception as exc:
        logger.debug("Analytics Redis cache read skipped: %s", exc)
    return None


async def _set_cached_analytics(cache_key: str, payload: dict[str, Any]) -> None:
    ttl = settings.ANALYTICS_CACHE_TTL_SECONDS
    if ttl <= 0 or not settings.REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.15,
            socket_timeout=0.5,
        )
        try:
            await client.setex(cache_key, ttl, json.dumps(payload))
        finally:
            await client.aclose()
    except Exception as exc:
        logger.debug("Analytics Redis cache write skipped: %s", exc)


def _to_utc_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.astimezone(UTC).date()
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val)[:10])


class AnalyticsService:
    """Computes organization-scoped turnaround, quality, rule, and cost analytics."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_overview(
        self,
        org_id: uuid.UUID,
        *,
        days: int = 30,
        repo_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        if repo_id is not None:
            repo_stmt = select(RepositoryModel.id).where(
                RepositoryModel.id == repo_id,
                RepositoryModel.org_id == org_id,
                RepositoryModel.deleted_at.is_(None),
            )
            if (await self._session.execute(repo_stmt)).scalar_one_or_none() is None:
                raise NotFoundError(f"Repository {repo_id} not found in organization")

        cache_key = f"aoa:analytics:overview:{org_id}:{days}:{repo_id or 'all'}"
        cached = await _get_cached_analytics(cache_key)
        if cached is not None:
            return cached

        today_utc = datetime.now(UTC).date()
        start_date = today_utc - timedelta(days=days - 1)
        start_dt = datetime.combine(start_date, time.min, tzinfo=UTC)

        # 1. PR review turnaround p50 / p95
        pr_filters = [
            PullRequestReviewModel.org_id == org_id,
            PullRequestReviewModel.status == "completed",
            PullRequestReviewModel.execution_duration_ms.is_not(None),
            PullRequestReviewModel.created_at >= start_dt,
        ]
        if repo_id is not None:
            pr_filters.append(PullRequestReviewModel.repo_id == repo_id)

        pr_stats_stmt = select(
            func.count(PullRequestReviewModel.id),
            func.percentile_cont(0.50).within_group(
                PullRequestReviewModel.execution_duration_ms
            ),
            func.percentile_cont(0.95).within_group(
                PullRequestReviewModel.execution_duration_ms
            ),
        ).where(*pr_filters)
        pr_count, pr_p50, pr_p95 = (await self._session.execute(pr_stats_stmt)).one()

        # 2. Autonomous task active turnaround p50 / p95
        task_duration_ms = (
            func.greatest(
                0.0,
                func.extract(
                    "epoch", TaskRunModel.completed_at - TaskRunModel.started_at
                )
                - TaskRunModel.paused_seconds,
            )
            * 1000.0
        )
        task_filters = [
            TaskModel.org_id == org_id,
            TaskRunModel.status == "completed",
            TaskRunModel.started_at.is_not(None),
            TaskRunModel.completed_at.is_not(None),
            TaskRunModel.completed_at >= start_dt,
        ]
        if repo_id is not None:
            task_filters.append(TaskModel.repo_id == repo_id)

        task_stats_stmt = (
            select(
                func.count(TaskRunModel.id),
                func.percentile_cont(0.50).within_group(task_duration_ms),
                func.percentile_cont(0.95).within_group(task_duration_ms),
            )
            .select_from(TaskRunModel)
            .join(TaskModel, TaskRunModel.task_id == TaskModel.id)
            .where(*task_filters)
        )
        task_count, task_p50, task_p95 = (
            await self._session.execute(task_stats_stmt)
        ).one()

        # 3. Findings by severity, category, and acceptance rate
        finding_filters = [
            PullRequestReviewModel.org_id == org_id,
            PRReviewFindingModel.created_at >= start_dt,
        ]
        if repo_id is not None:
            finding_filters.append(PullRequestReviewModel.repo_id == repo_id)

        findings_agg_stmt = (
            select(
                PRReviewFindingModel.severity,
                PRReviewFindingModel.category,
                PRReviewFindingModel.feedback_state,
                func.count(PRReviewFindingModel.id),
            )
            .select_from(PRReviewFindingModel)
            .join(
                PullRequestReviewModel,
                PRReviewFindingModel.review_id == PullRequestReviewModel.id,
            )
            .where(*finding_filters)
            .group_by(
                PRReviewFindingModel.severity,
                PRReviewFindingModel.category,
                PRReviewFindingModel.feedback_state,
            )
        )
        finding_rows = (await self._session.execute(findings_agg_stmt)).all()

        by_severity: dict[str, int] = {
            "critical": 0,
            "major": 0,
            "minor": 0,
            "info": 0,
        }
        by_category: dict[str, int] = {
            "security": 0,
            "bug": 0,
            "performance": 0,
            "architecture": 0,
            "style": 0,
        }
        accepted_count = 0
        dismissed_count = 0
        total_findings = 0
        for sev, cat, fb_state, cnt in finding_rows:
            cnt_int = int(cnt)
            total_findings += cnt_int
            by_severity[sev] = by_severity.get(sev, 0) + cnt_int
            by_category[cat] = by_category.get(cat, 0) + cnt_int
            if fb_state == "accepted":
                accepted_count += cnt_int
            elif fb_state == "dismissed":
                dismissed_count += cnt_int

        feedback_total = accepted_count + dismissed_count
        acceptance_rate: float | None = (
            round(accepted_count / feedback_total, 4) if feedback_total > 0 else None
        )

        # 4. Top triggered and dismissed non-deleted rules
        rule_filters = [
            PullRequestReviewModel.org_id == org_id,
            PRReviewFindingModel.created_at >= start_dt,
            PRReviewFindingModel.rule_id.is_not(None),
            ReviewRuleModel.deleted_at.is_(None),
        ]
        if repo_id is not None:
            rule_filters.append(PullRequestReviewModel.repo_id == repo_id)

        top_rules_stmt = (
            select(
                ReviewRuleModel.id,
                ReviewRuleModel.title,
                ReviewRuleModel.severity,
                ReviewRuleModel.category,
                func.count(PRReviewFindingModel.id).label("triggered_count"),
                func.sum(
                    case(
                        (PRReviewFindingModel.feedback_state == "accepted", 1),
                        else_=0,
                    )
                ).label("accepted_count"),
                func.sum(
                    case(
                        (PRReviewFindingModel.feedback_state == "dismissed", 1),
                        else_=0,
                    )
                ).label("dismissed_count"),
            )
            .select_from(PRReviewFindingModel)
            .join(
                PullRequestReviewModel,
                PRReviewFindingModel.review_id == PullRequestReviewModel.id,
            )
            .join(
                ReviewRuleModel,
                PRReviewFindingModel.rule_id == ReviewRuleModel.id,
            )
            .where(*rule_filters)
            .group_by(
                ReviewRuleModel.id,
                ReviewRuleModel.title,
                ReviewRuleModel.severity,
                ReviewRuleModel.category,
            )
            .order_by(
                func.count(PRReviewFindingModel.id).desc(),
                func.sum(
                    case(
                        (PRReviewFindingModel.feedback_state == "dismissed", 1),
                        else_=0,
                    )
                ).desc(),
            )
            .limit(10)
        )
        top_rule_rows = (await self._session.execute(top_rules_stmt)).all()
        top_rules = [
            {
                "rule_id": str(r_id),
                "title": r_title,
                "severity": r_sev,
                "category": r_cat,
                "triggered_count": int(trig or 0),
                "accepted_count": int(acc or 0),
                "dismissed_count": int(dis or 0),
            }
            for r_id, r_title, r_sev, r_cat, trig, acc, dis in top_rule_rows
        ]

        # 5. Daily AI cost series (UTC)
        usage_day_expr = func.date(func.timezone("UTC", UsageEventModel.created_at))
        usage_filters = [
            UsageEventModel.org_id == org_id,
            UsageEventModel.created_at >= start_dt,
        ]
        if repo_id is not None:
            usage_filters.append(
                or_(
                    TaskModel.repo_id == repo_id,
                    PullRequestReviewModel.repo_id == repo_id,
                )
            )

        usage_daily_stmt = (
            select(
                usage_day_expr.label("day_utc"),
                UsageEventModel.operation_type,
                func.coalesce(func.sum(UsageEventModel.estimated_cost_cents), 0),
            )
            .select_from(UsageEventModel)
            .outerjoin(TaskModel, UsageEventModel.task_id == TaskModel.id)
            .outerjoin(
                PullRequestReviewModel,
                UsageEventModel.pr_review_id == PullRequestReviewModel.id,
            )
            .where(*usage_filters)
            .group_by(usage_day_expr, UsageEventModel.operation_type)
        )
        usage_rows = (await self._session.execute(usage_daily_stmt)).all()

        # 6. Daily PR review p50 turnaround (UTC)
        pr_day_expr = func.date(func.timezone("UTC", PullRequestReviewModel.created_at))
        pr_daily_stmt = (
            select(
                pr_day_expr.label("day_utc"),
                func.percentile_cont(0.50).within_group(
                    PullRequestReviewModel.execution_duration_ms
                ),
            )
            .where(*pr_filters)
            .group_by(pr_day_expr)
        )
        pr_daily_rows = (await self._session.execute(pr_daily_stmt)).all()

        # 7. Daily autonomous task p50 turnaround (UTC)
        task_day_expr = func.date(func.timezone("UTC", TaskRunModel.completed_at))
        task_daily_stmt = (
            select(
                task_day_expr.label("day_utc"),
                func.percentile_cont(0.50).within_group(task_duration_ms),
            )
            .select_from(TaskRunModel)
            .join(TaskModel, TaskRunModel.task_id == TaskModel.id)
            .where(*task_filters)
            .group_by(task_day_expr)
        )
        task_daily_rows = (await self._session.execute(task_daily_stmt)).all()

        # Zero-fill UTC daily series
        daily_map: dict[date, dict[str, Any]] = {}
        for offset in range(days):
            d = start_date + timedelta(days=offset)
            daily_map[d] = {
                "date": d.isoformat(),
                "pr_review_cost_cents": 0,
                "autonomous_cost_cents": 0,
                "total_cost_cents": 0,
                "pr_review_p50_ms": 0.0,
                "task_p50_ms": 0.0,
            }

        total_cost_cents = 0
        total_pr_review_cost_cents = 0
        total_autonomous_cost_cents = 0
        for raw_day, op_type, cost_sum in usage_rows:
            d = _to_utc_date(raw_day)
            cents = int(cost_sum or 0)
            if d is not None and d in daily_map:
                if op_type == "pr_review":
                    daily_map[d]["pr_review_cost_cents"] += cents
                    total_pr_review_cost_cents += cents
                elif op_type in ("forge", "reviewer"):
                    daily_map[d]["autonomous_cost_cents"] += cents
                    total_autonomous_cost_cents += cents
                daily_map[d]["total_cost_cents"] = (
                    daily_map[d]["pr_review_cost_cents"]
                    + daily_map[d]["autonomous_cost_cents"]
                )
            total_cost_cents += cents

        for raw_day, p50_val in pr_daily_rows:
            d = _to_utc_date(raw_day)
            if d is not None and d in daily_map and p50_val is not None:
                daily_map[d]["pr_review_p50_ms"] = round(float(p50_val), 2)

        for raw_day, p50_val in task_daily_rows:
            d = _to_utc_date(raw_day)
            if d is not None and d in daily_map and p50_val is not None:
                daily_map[d]["task_p50_ms"] = round(float(p50_val), 2)

        overview: dict[str, Any] = {
            "days": days,
            "repo_id": str(repo_id) if repo_id else None,
            "kpis": {
                "total_reviews": int(pr_count or 0),
                "total_task_runs": int(task_count or 0),
                "turnaround_p50_ms": round(float(pr_p50), 2)
                if pr_p50 is not None
                else None,
                "turnaround_p95_ms": round(float(pr_p95), 2)
                if pr_p95 is not None
                else None,
                "task_turnaround_p50_ms": round(float(task_p50), 2)
                if task_p50 is not None
                else None,
                "task_turnaround_p95_ms": round(float(task_p95), 2)
                if task_p95 is not None
                else None,
                "total_findings": total_findings,
                "accepted_findings": accepted_count,
                "dismissed_findings": dismissed_count,
                "acceptance_rate": acceptance_rate,
                "total_cost_cents": total_cost_cents,
                "pr_review_cost_cents": total_pr_review_cost_cents,
                "autonomous_cost_cents": total_autonomous_cost_cents,
            },
            "findings_by_severity": by_severity,
            "findings_by_category": by_category,
            "top_rules": top_rules,
            "daily_series": list(daily_map.values()),
        }

        await _set_cached_analytics(cache_key, overview)
        return overview
