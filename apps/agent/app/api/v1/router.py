from fastapi import APIRouter

from app.api.v1.endpoints import health, reviews, tasks, webhooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(reviews.router, tags=["reviews"])
