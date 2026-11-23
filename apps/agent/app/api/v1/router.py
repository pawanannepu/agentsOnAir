from fastapi import APIRouter

from app.api.v1.endpoints import health, tasks, webhooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
