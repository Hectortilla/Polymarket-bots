"""Bot-definition catalog endpoint."""

from fastapi import APIRouter

from api.http.routes.paths import (
    BOT_DEFINITIONS_PATH,
    LIST_BOT_DEFINITIONS_OPERATION_ID,
)
from api.catalog.contracts import BotDefinitionDescriptor
from api.catalog.definitions import catalog_descriptors


router = APIRouter()


@router.get(
    BOT_DEFINITIONS_PATH,
    response_model=list[BotDefinitionDescriptor],
    operation_id=LIST_BOT_DEFINITIONS_OPERATION_ID,
)
async def list_bot_definitions() -> tuple[BotDefinitionDescriptor, ...]:
    return catalog_descriptors()
