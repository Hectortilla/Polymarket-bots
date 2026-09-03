"""Saved-bot route assembly."""

from fastapi import APIRouter

from polybot_control_plane.api.routes.bots.run_launch import router as run_router
from polybot_control_plane.api.routes.bots.saved_bot import router as saved_bot_router


router = APIRouter()
router.include_router(saved_bot_router)
router.include_router(run_router)
