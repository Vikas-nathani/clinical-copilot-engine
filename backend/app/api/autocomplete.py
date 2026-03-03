"""
API Routes — POST /api/v1/suggest + GET /api/v1/suggest/stream + GET /health.

Thin transport layer. All business logic lives in the Orchestrator.
"""

from __future__ import annotations

import json
import logging
from typing import Union

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import get_settings
from app.core.middleware import limiter
from app.schemas.models import (
    SuggestRequest,
    AutocompleteResponse,
    EmptyResponse,
    ErrorResponse,
    HealthResponse,
)
from app.services.dictionary import DictionaryService, UMLSApiService
from app.services.lab_engine import LabEngine
from app.services.llm_client import LLMClient
from app.services.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Dependency Injection ───────────────────────────────────────────
# Typed accessors for app.state — catches typos at import time,
# enables IDE autocompletion, and simplifies testing via DI overrides.


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def get_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client


def get_dictionary(request: Request) -> DictionaryService:
    return request.app.state.dictionary


def get_lab_engine(request: Request) -> LabEngine:
    return request.app.state.lab_engine


def get_umls_service(request: Request) -> UMLSApiService:
    return request.app.state.umls_service


# ── Suggest Endpoint ───────────────────────────────────────────────


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
@limiter.limit("300/minute")
async def suggest(
    request: Request,
    payload: SuggestRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> Union[AutocompleteResponse, EmptyResponse]:
    """
    Main suggest endpoint.

    The orchestrator is injected via Depends (backed by app.state).
    """
    try:
        result = await orchestrator.suggest(payload)
        return result
    except Exception as e:
        logger.error("Suggest error: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"},
        )


# ── Streaming Endpoint ────────────────────────────────────────────


@router.get(
    "/api/v1/suggest/stream",
    summary="Stream LLM tokens via SSE",
    description=(
        "Streams Server-Sent Events with individual tokens from the LLM. "
        "Useful for real-time typewriter-style completions."
    ),
)
@limiter.limit("60/minute")
async def suggest_stream(
    request: Request,
    text: str = Query(..., min_length=1, max_length=5000, description="Clinical note text"),
    context_window: int = Query(default=200, ge=10, le=1000),
    llm_client: LLMClient = Depends(get_llm_client),
):
    """Stream LLM tokens as Server-Sent Events."""

    async def event_generator():
        try:
            async for token in llm_client.stream(text, context_window):
                # Stop generating if the client disconnected
                if await request.is_disconnected():
                    logger.debug("SSE client disconnected, stopping stream.")
                    break
                data = json.dumps({"token": token})
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Stream error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'error': 'stream_error'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Health Endpoint ────────────────────────────────────────────────


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description="Returns service health status and loaded resource counts.",
)
async def health(
    response: Response,
    dictionary: DictionaryService = Depends(get_dictionary),
    lab_engine: LabEngine = Depends(get_lab_engine),
    llm_client: LLMClient = Depends(get_llm_client),
    umls_service: UMLSApiService = Depends(get_umls_service),
) -> HealthResponse:
    """Health check — reports status of all loaded resources."""
    settings = get_settings()

    # Compute status: degraded if critical resources are missing
    is_healthy = dictionary.is_loaded
    status = "healthy" if is_healthy else "degraded"

    if not is_healthy:
        response.status_code = 503

    return HealthResponse(
        status=status,
        trie_loaded=dictionary.is_loaded,
        trie_term_count=dictionary.trie_term_count,
        abbreviation_count=dictionary.abbreviation_count,
        lab_ranges_count=lab_engine.lab_ranges_count,
        ollama_available=llm_client.is_available,
        umls_available=umls_service.is_available,
        version=settings.app_version,
    )
