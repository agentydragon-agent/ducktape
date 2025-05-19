"""Webhook viewing endpoints."""

import math
from typing import Annotated, Any, Dict, List, Optional

from compact_json import Formatter
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.handlers import AuthContext
from ..config import settings
from ..database import get_db_session
from ..models import WebhookIntegration, WebhookPayload
from ..app import templates, register_with_all_auth_methods, app

router = APIRouter(tags=["webhook_view"])

# JSON formatter for consistent output
json_formatter = Formatter(
    indent_spaces=2,
    max_inline_length=70,
    max_inline_complexity=10,
)

# Default page size from config
DEFAULT_PAGE_SIZE = settings.webhook.default_page_size


async def get_webhook_integration(
    integration_name: str, db_session: AsyncSession
) -> WebhookIntegration:
    """Get webhook integration by name.

    Args:
        integration_name: Integration name
        db_session: Database session

    Returns:
        WebhookIntegration instance

    Raises:
        HTTPException: If integration not found or disabled
    """
    query = select(WebhookIntegration).where(
        WebhookIntegration.name == integration_name
    )
    result = await db_session.execute(query)
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_name}' not found",
        )

    if not integration.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Integration '{integration_name}' is disabled",
        )

    return integration


async def get_webhook_payloads(
    db_session: AsyncSession,
    integration_name: Optional[str] = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """Get webhook payloads with pagination.

    Args:
        db_session: Database session
        integration_name: Optional integration name to filter by
        page: Page number (starting from 1)
        page_size: Number of items per page

    Returns:
        Dict with template context variables
    """
    # Build base query
    count_query = select(func.count()).select_from(WebhookPayload)
    payloads_query = select(WebhookPayload).order_by(WebhookPayload.received_at.desc())

    # Apply filter if integration name provided
    if integration_name:
        count_query = count_query.where(
            WebhookPayload.integration_name == integration_name
        )
        payloads_query = payloads_query.where(
            WebhookPayload.integration_name == integration_name
        )

    # Get total count
    total_count = await db_session.scalar(count_query)
    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

    # Adjust page to be in bounds
    page = max(1, min(page, total_pages))

    # Get payloads
    offset = (page - 1) * page_size
    payloads_query = payloads_query.offset(offset).limit(page_size)
    result = await db_session.execute(payloads_query)
    payloads = result.scalars().all()

    # Format payloads for template with list comprehension
    formatted_payloads = [
        {
            "id": payload.id,
            "integration_name": payload.integration_name,
            "received_at": payload.received_at,
            "payload_json": json_formatter.serialize(payload.payload),
        }
        for payload in payloads
    ]

    return {
        "payloads": formatted_payloads,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
    }


@router.get("/webhooks/", response_class=HTMLResponse)
async def list_all_payloads(
    request: Request,
    auth: AuthContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
    db_session: AsyncSession = Depends(get_db_session),
):
    """List all webhook integrations and payloads."""
    # TODO: This lists all webhook payloads even from disabled integrations.
    # It's fine for now, but we should consider filtering by enabled integrations in the future.
    
    # TODO: Once we have human login, with human having logged in, it should also show disabled integrations
    
    # Get webhook integrations
    integrations_query = select(WebhookIntegration).where(WebhookIntegration.is_enabled == True)
    integrations_result = await db_session.execute(integrations_query)
    integrations = [
        {
            "id": integration.id,
            "name": integration.name,
            "description": integration.description,
        }
        for integration in integrations_result.scalars().all()
    ]
    
    # Get payloads with pagination
    context = await get_webhook_payloads(db_session, None, page, page_size)

    # Add request-specific context
    return templates.TemplateResponse(
        "webhook_payloads.html",
        context | {
            "request": request,
            "auth": auth,
            "header": "Webhook Integrations",
            "integration_name": "",
            "integrations": integrations,
        },
    )


@router.get("/webhooks/{integration_name}", response_class=HTMLResponse)
async def list_integration_payloads(
    request: Request,
    integration_name: str,
    auth: AuthContext,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PAGE_SIZE,
    db_session: AsyncSession = Depends(get_db_session),
):
    """List webhook payloads for a specific integration."""
    # Check if integration exists and is enabled
    integration = await get_webhook_integration(integration_name, db_session)
    
    # TODO: Add link back to showing all integrations in the template

    # Get payloads with pagination
    context = await get_webhook_payloads(db_session, integration_name, page, page_size)

    # Add request-specific context
    return templates.TemplateResponse(
        "webhook_payloads.html",
        context | {
            "request": request,
            "auth": auth,
            "header": f"{integration_name} Webhook Payloads",
            "integration_name": integration_name,
            "show_all_link": True,  # Flag to show link back to all integrations
            "integration": {
                "id": integration.id,
                "name": integration.name,
                "description": integration.description,
            },
        },
    )


# Register the webhook routes with all auth methods
register_with_all_auth_methods("/webhooks/", list_all_payloads)
register_with_all_auth_methods("/webhooks/{integration_name}", list_integration_payloads)