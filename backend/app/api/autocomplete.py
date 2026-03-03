"""
API Routes — POST /autocomplete + GET /health.

Thin transport layer. All business logic lives in the Orchestrator.
"""

from __future__ import annotations

import logging
from typing import Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas.models import (
    AutocompleteRequest,
    AutocompleteResponse,
    EmptyResponse,
    ErrorResponse,
    HealthResponse,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/autocomplete",
    response_model=Union[AutocompleteResponse, EmptyResponse],
    responses={
        200: {"description": "Suggestion returned successfully"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Get autocomplete suggestion",
    description=(
        "Accepts clinical note text + cursor position and returns "
        "a real-time autocomplete suggestion via the 4-stage waterfall pipeline."
    ),
)
async def autocomplete(
    payload: AutocompleteRequest,
    request: Request,
) -> Union[AutocompleteResponse, EmptyResponse]:
    """
    Main autocomplete endpoint.

    The orchestrator is attached to app.state during startup (lifespan).
    """
    try:
        orchestrator = request.app.state.orchestrator
        result = await orchestrator.suggest(payload)
        return result
    except Exception as e:
        logger.error("Autocomplete error: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(e)},
        )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description="Returns service health status and loaded resource counts.",
)
async def health(request: Request) -> HealthResponse:
    """Health check — reports status of all loaded resources."""
    settings = get_settings()
    dictionary = request.app.state.dictionary
    lab_engine = request.app.state.lab_engine
    llm_client = request.app.state.llm_client

    return HealthResponse(
        status="healthy",
        trie_loaded=dictionary.is_loaded,
        trie_term_count=dictionary.trie_term_count,
        abbreviation_count=dictionary.abbreviation_count,
        lab_ranges_count=lab_engine.lab_ranges_count,
        llm_available=llm_client.is_available,
        version=settings.app_version,
    )
