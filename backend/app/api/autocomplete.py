"""
API Routes — POST /api/v1/suggest + GET /api/v1/suggest/stream + GET /health.

Thin transport layer. All business logic lives in the Orchestrator.
"""

from __future__ import annotations

import json
import logging
from typing import Union

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.models import (
    SuggestRequest,
    AutocompleteResponse,
    EmptyResponse,
    ErrorResponse,
    HealthResponse,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/api/v1/suggest",
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
async def suggest(
    payload: SuggestRequest,
    request: Request,
) -> Union[AutocompleteResponse, EmptyResponse]:
    """
    Main suggest endpoint.

    The orchestrator is attached to app.state during startup (lifespan).
    """
    try:
        orchestrator = request.app.state.orchestrator
        result = await orchestrator.suggest(payload)
        return result
    except Exception as e:
        logger.error("Suggest error: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(e)},
        )


@router.get(
    "/api/v1/suggest/stream",
    summary="Stream LLM tokens via SSE",
    description=(
        "Streams Server-Sent Events with individual tokens from the LLM. "
        "Useful for real-time typewriter-style completions."
    ),
)
async def suggest_stream(
    request: Request,
    text: str = Query(..., min_length=1, max_length=5000, description="Clinical note text"),
    context_window: int = Query(default=200, ge=10, le=1000),
):
    """Stream LLM tokens as Server-Sent Events."""
    llm_client = request.app.state.llm_client

    async def event_generator():
        try:
            async for token in llm_client.stream(text, context_window):
                data = json.dumps({"token": token})
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Stream error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
    umls_service = request.app.state.umls_service

    return HealthResponse(
        status="healthy",
        trie_loaded=dictionary.is_loaded,
        trie_term_count=dictionary.trie_term_count,
        abbreviation_count=dictionary.abbreviation_count,
        lab_ranges_count=lab_engine.lab_ranges_count,
        ollama_available=llm_client.is_available,
        umls_available=umls_service.is_available,
        version=settings.app_version,
    )
