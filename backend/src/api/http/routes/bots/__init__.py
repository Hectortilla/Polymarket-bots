"""Saved-bot route assembly."""

from fastapi import APIRouter

from api.http.routes.bots.run_launch import router as run_router
from api.http.routes.bots.saved_bot import router as saved_bot_router

router = APIRouter()
router.include_router(saved_bot_router)
router.include_router(run_router)
