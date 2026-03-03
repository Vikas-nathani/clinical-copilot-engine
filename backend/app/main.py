"""
Clinical Copilot Engine — FastAPI Application Entry Point.

Manages the application lifespan (startup / shutdown) and wires
together all services, routes, and middleware.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.autocomplete import router as autocomplete_router
from app.core.config import get_settings
from app.core.middleware import setup_middleware
from app.services.dictionary import DictionaryService
from app.services.lab_engine import LabEngine
from app.services.llm_client import LLMClient
from app.services.orchestrator import Orchestrator


# ── Structured Logging Setup ───────────────────────────────────────


def configure_logging() -> None:
    """Configure structlog + stdlib logging for production JSON output."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib root logger
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer()
        if settings.debug
        else structlog.processors.JSONRenderer(),
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ── Application Lifespan ───────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: load all services into app.state.
    Shutdown: cleanly release resources.
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting Clinical Copilot Engine...")

    # Initialize services
    dictionary = DictionaryService()
    lab_engine = LabEngine()
    llm_client = LLMClient()

    await dictionary.load()
    await lab_engine.load()
    await llm_client.initialize()

    orchestrator = Orchestrator(
        dictionary=dictionary,
        lab_engine=lab_engine,
        llm_client=llm_client,
    )

    # Attach to app.state for access in route handlers
    app.state.dictionary = dictionary
    app.state.lab_engine = lab_engine
    app.state.llm_client = llm_client
    app.state.orchestrator = orchestrator

    logger.info(
        "Startup complete — Trie: %d terms, Abbreviations: %d, "
        "Lab ranges: %d, LLM: %s",
        dictionary.trie_term_count,
        dictionary.abbreviation_count,
        lab_engine.lab_ranges_count,
        "available" if llm_client.is_available else "unavailable",
    )

    yield

    # Shutdown
    logger.info("Shutting down Clinical Copilot Engine...")
    await llm_client.shutdown()
    logger.info("Shutdown complete.")


# ── App Factory ────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Real-time autocomplete for clinical note-writing. "
            "Suggests medical terms, ICD-10 codes, and AI-powered "
            "sentence completions via a 4-stage waterfall pipeline."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Middleware
    setup_middleware(app)

    # Routes
    app.include_router(autocomplete_router, tags=["Autocomplete"])

    return app


# ── Application Instance ───────────────────────────────────────────
app = create_app()