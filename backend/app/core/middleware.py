"""
Middleware — CORS, Rate Limiting, Structured Logging, Request Timing.

Production-grade middleware stack for Clinical Copilot Engine.
No authentication (by design — internal/trusted network use).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

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


# ── Request Timing + Logging Middleware (pure ASGI) ────────────────
# Uses raw ASGI instead of BaseHTTPMiddleware to avoid buffering
# streaming responses (SSE).


class RequestLoggingMiddleware:
    """
    Pure ASGI middleware for structured request/response logging.

    Unlike BaseHTTPMiddleware, this does NOT buffer the response body,
    so SSE/streaming endpoints work correctly.

    Adds:
    - Unique request ID
    - Method, path, status code
    - Response time in milliseconds
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        method = scope.get("method", "?")
        path = scope.get("path", "?")
        start = time.perf_counter()

        # Log incoming request
        logger.info("[%s] %s %s", request_id, method, path)

        # Store request_id in scope state for downstream access
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        status_code = 500  # default if headers never sent

        async def send_wrapper(message: Any) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                # Inject timing headers
                headers = list(message.get("headers", []))
                elapsed = (time.perf_counter() - start) * 1000
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"x-response-time-ms", f"{elapsed:.1f}".encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "[%s] %s %s → 500 (%.1fms) ERROR: %s",
                request_id, method, path, elapsed, e,
            )
            raise

        elapsed = (time.perf_counter() - start) * 1000
        log_fn = logger.info if status_code < 400 else logger.warning
        log_fn(
            "[%s] %s %s → %d (%.1fms)",
            request_id, method, path, status_code, elapsed,
        )


# ── Setup Function ──────────────────────────────────────────────────


def setup_middleware(app: FastAPI) -> None:
    """
    Attach all middleware to the FastAPI app.
    Call this once during app creation.
    """
    settings = get_settings()

    # 1. CORS — explicit headers instead of wildcard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
    )

    # 2. Request logging + timing (pure ASGI — safe for SSE streaming)
    app.add_middleware(RequestLoggingMiddleware)

    # 3. Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
