"""HTTP routes under /api."""

from fastapi import APIRouter

from app.api import health, images, index, search

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(search.router)
api_router.include_router(images.router)
api_router.include_router(index.router)