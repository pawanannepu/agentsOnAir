from fastapi import APIRouter

from app.api.v1.endpoints import (
    analytics,
    health,
    organizations,
    repositories,
    reviews,
    tasks,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(
    organizations.router, prefix="/organizations", tags=["organizations"]
)
api_router.include_router(
    repositories.router, prefix="/repositories", tags=["repositories"]
)
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(reviews.router, tags=["reviews"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
