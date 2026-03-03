"""
Middleware — CORS, Rate Limiting, Structured Logging, Request Timing.

Production-grade middleware stack for Clinical Copilot Engine.
No authentication (by design — internal/trusted network use).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ── Rate Limiter (singleton) ───────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Custom 429 response for rate limit violations."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": f"Too many requests. Limit: {exc.detail}",
        },
    )


# ── Request Timing + Logging Middleware ─────────────────────────────


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Adds structured request/response logging with:
    - Unique request ID
    - Method, path, status code
    - Response time in milliseconds
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        start = time.perf_counter()

        # Log incoming request
        logger.info(
            "[%s] %s %s",
            request_id,
            request.method,
            request.url.path,
        )

        try:
            response = await call_next(request)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "[%s] %s %s → 500 (%.1fms) ERROR: %s",
                request_id, request.method, request.url.path, elapsed, e,
            )
            raise

        elapsed = (time.perf_counter() - start) * 1000

        # Add timing header
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{elapsed:.1f}"

        # Log response
        log_fn = logger.info if response.status_code < 400 else logger.warning
        log_fn(
            "[%s] %s %s → %d (%.1fms)",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )

        return response


# ── Setup Function ──────────────────────────────────────────────────


def setup_middleware(app: FastAPI) -> None:
    """
    Attach all middleware to the FastAPI app.
    Call this once during app creation.
    """
    settings = get_settings()

    # 1. CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
    )

    # 2. Request logging + timing
    app.add_middleware(RequestLoggingMiddleware)

    # 3. Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
