"""
Pydantic models for API request / response validation.

Strict typing ensures malformed requests are rejected before
they reach the service layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ───────────────────────────────────────────────────────────


class SuggestionSource(str, Enum):
    """Where the autocomplete suggestion originated."""
    ABBREVIATION = "abbreviation"
    TRIE = "trie"
    UMLS = "umls"
    LAB_ENGINE = "lab_engine"
    LLM = "llm"


class LabFlag(str, Enum):
    """Clinical severity flags for lab values."""
    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    CRITICAL_LOW = "critical_low"
    CRITICAL_HIGH = "critical_high"


# ── Request Models ──────────────────────────────────────────────────


class SuggestRequest(BaseModel):
    """Incoming suggest request from the frontend editor."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The full text content from the clinical note editor.",
        examples=["patient has diab"],
    )
    cursor_position: int = Field(
        ...,
        ge=0,
        description="0-indexed cursor position within the text.",
        examples=[16],
    )
    context_window: Optional[int] = Field(
        default=200,
        ge=10,
        le=1000,
        description="Number of preceding characters to use for context (LLM stage).",
    )
    specialty: Optional[str] = Field(
        default="general",
        description="Clinical specialty context (e.g. cardiology, endocrinology).",
        examples=["endocrinology"],
    )

    @field_validator("cursor_position")
    @classmethod
    def cursor_within_text(cls, v: int, info) -> int:
        text = info.data.get("text", "")
        if v > len(text):
            raise ValueError(
                f"cursor_position ({v}) exceeds text length ({len(text)})"
            )
        return v


# Backward-compatible alias
AutocompleteRequest = SuggestRequest


# ── Response Models ─────────────────────────────────────────────────


class AutocompleteResponse(BaseModel):
    """Successful autocomplete suggestion."""

    suggestion: str = Field(
        ...,
        description="The suggested completion text.",
        examples=["etes mellitus type 2"],
    )
    source: SuggestionSource = Field(
        ...,
        description="Which pipeline stage produced this suggestion.",
        examples=["trie"],
    )
    icd_code: Optional[str] = Field(
        default=None,
        description="ICD-10-CM code, if the term maps to one.",
        examples=["E11.9"],
    )
    snomed_code: Optional[str] = Field(
        default=None,
        description="SNOMED-CT concept ID, if available.",
        examples=["44054006"],
    )
    loinc_code: Optional[str] = Field(
        default=None,
        description="LOINC code, if the term is a lab/observation.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (1.0 for deterministic, <1.0 for LLM).",
        examples=[0.95],
    )
    lab_flag: Optional[LabFlag] = Field(
        default=None,
        description="Lab severity flag (only set by lab_engine stage).",
    )
    specialty: Optional[str] = Field(
        default=None,
        description="Specialty context that influenced this suggestion.",
    )


class EmptyResponse(BaseModel):
    """Returned when no suggestion is available."""

    suggestion: None = None
    source: None = None
    message: str = Field(
        default="No suggestion available for the given input.",
    )


class HealthResponse(BaseModel):
    """Service health and loaded resource status."""

    status: str = Field(..., examples=["healthy"])
    trie_loaded: bool
    trie_term_count: int
    abbreviation_count: int
    lab_ranges_count: int
    ollama_available: bool
    umls_available: bool
    version: str


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    error: str
    detail: Optional[str] = None
