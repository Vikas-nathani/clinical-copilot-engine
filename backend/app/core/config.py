"""
Application configuration via environment variables.

Uses Pydantic BaseSettings for type-safe config with .env support.
All settings are loaded once at startup and shared via dependency injection.
"""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


# ── Path Constants ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[3]          # clinical-copilot-engine/

# DATA_DIR is configurable so it works both locally and in Docker.
# Local:  clinical-copilot-engine/data
# Docker: /app/data  (set DATA_DIR=/app/data in env or docker-compose)
_default_data_dir = (
    Path(os.environ["DATA_DIR"]) if "DATA_DIR" in os.environ
    else PROJECT_ROOT / "data"
)
DATA_DIR = _default_data_dir
RAW_DATA_DIR = DATA_DIR / "raw"
COMPILED_DATA_DIR = DATA_DIR / "compiled"


class Settings(BaseSettings):
    """
    Central configuration for Clinical Copilot Engine.

    Reads from environment variables (or .env file at project root).
    Every field has a sensible default for local development.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────
    app_name: str = "Clinical Copilot Engine"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # ── Server ──────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4

    # ── CORS ────────────────────────────────────────────────────────
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
    )

    # ── Rate Limiting ───────────────────────────────────────────────
    rate_limit_per_minute: int = 300

    # ── Ollama / BioMistral ─────────────────────────────────────────
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "cniongolo/biomistral"
    ollama_timeout_seconds: float = 30.0
    ollama_stream_timeout_seconds: float = 60.0
    ollama_max_tokens: int = 60
    ollama_temperature: float = 0.3
    ollama_top_p: float = 0.9
    ollama_repeat_penalty: float = 1.1

    # ── Autocomplete Tuning ─────────────────────────────────────────
    max_suggestion_length: int = 80
    min_prefix_length: int = 2
    max_trie_results: int = 10
    debounce_ms: int = 150

    # ── Data Paths ──────────────────────────────────────────────────
    trie_path: str = str(COMPILED_DATA_DIR / "medical_trie.marisa")
    abbreviations_path: str = str(COMPILED_DATA_DIR / "abbreviations.json")
    icd10_lookup_path: str = str(COMPILED_DATA_DIR / "icd10_lookup.json")
    snomed_lookup_path: str = str(COMPILED_DATA_DIR / "snomed_lookup.json")
    loinc_lookup_path: str = str(COMPILED_DATA_DIR / "loinc_lookup.json")
    lab_ranges_path: str = str(COMPILED_DATA_DIR / "lab_ranges.json")

    # ── UMLS / Data Download ────────────────────────────────────────
    umls_api_key: str = ""
    loinc_username: str = ""
    loinc_password: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached singleton — parsed once, reused everywhere.
    Call this as a FastAPI dependency or import directly.
    """
    return Settings()
