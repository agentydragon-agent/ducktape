from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
import homeassistant_api

from ..auth.dependencies import Auth
from ..config import get_settings
from ..shared import get_jinja_templates, make_ha_history_url

logger = logging.getLogger(__name__)

settings = get_settings()
templates = get_jinja_templates()
ha_history_url = make_ha_history_url(settings)

router = APIRouter(tags=["homeassistant"])


async def fetch_states() -> list[dict[str, Any]]:
    """Fetch states for configured entities."""
    entities: list[dict[str, Any]] = []
    async with homeassistant_api.Client(
        settings.home_assistant.api_url, settings.home_assistant.api_token, use_async=True, verify_ssl=False
    ) as client:
        for entity_id in settings.home_assistant.entities:
            try:
                state = await client.async_get_state(entity_id=entity_id)
                entities.append(
                    {
                        "entity_id": entity_id,
                        "state": state.state,
                        "last_changed": state.last_changed,
                        "friendly_name": state.attributes.get("friendly_name", entity_id),
                    }
                )
            except Exception as exc:  # pragma: no cover - network errors
                logger.error("Failed fetching %s: %s", entity_id, exc)
    return entities


@router.get("/ha/", response_class=HTMLResponse)
async def list_entities(request: Request, auth: Auth) -> HTMLResponse:
    """List configured Home Assistant entity states."""
    states = await fetch_states()
    is_human = auth.auth_type == "admin"
    return templates.TemplateResponse(
        "ha_entities.html",
        {
            "request": request,
            "auth": auth,
            "states": states,
            "header": "Entities",
            "is_human": is_human,
            "history": [],
            "ha_history_url": ha_history_url,
        },
    )


@router.get("/ha/{entity_id}", response_class=HTMLResponse)
async def entity_details(request: Request, entity_id: str, auth: Auth) -> HTMLResponse:
    """Display details for a single entity."""
    states = await fetch_states()
    entity = next((s for s in states if s["entity_id"] == entity_id), None)
    is_human = auth.auth_type == "admin"
    return templates.TemplateResponse(
        "ha_entity.html",
        {
            "request": request,
            "auth": auth,
            "state": entity,
            "header": f"{entity_id} Details",
            "is_human": is_human,
            "history": [],
            "ha_history_url": ha_history_url,
        },
    )
