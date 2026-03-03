"""
Orchestrator — Waterfall Autocomplete Controller.

Executes the 4-stage waterfall in strict sequential order:
  1. Abbreviation map lookup
  2. MARISA-Trie prefix search
  3. Lab pattern engine
  4. BioMistral-7B (vLLM) fallback

Returns the first successful match, assembling it into an
AutocompleteResponse for the API layer.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Union

from app.schemas.models import (
    AutocompleteRequest,
    AutocompleteResponse,
    EmptyResponse,
    LabFlag,
    SuggestionSource,
)
from app.services.dictionary import DictionaryService, UMLSApiService
from app.services.lab_engine import LabEngine, Severity
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Central controller that runs the waterfall pipeline.

    Each stage is attempted in order. The first stage that produces
    a result short-circuits the rest — minimizing latency.
    """

    def __init__(
        self,
        dictionary: DictionaryService,
        lab_engine: LabEngine,
        llm_client: LLMClient,
        umls_service: Optional[UMLSApiService] = None,
    ) -> None:
        self._dictionary = dictionary
        self._lab_engine = lab_engine
        self._llm_client = llm_client
        self._umls = umls_service

    async def suggest(
        self, request: AutocompleteRequest
    ) -> Union[AutocompleteResponse, EmptyResponse]:
        """
        Run the waterfall pipeline and return the best suggestion.

        Args:
            request: Validated autocomplete request with text + cursor_position.

        Returns:
            AutocompleteResponse on match, EmptyResponse otherwise.
        """
        start = time.perf_counter()

        # Extract the relevant text up to the cursor
        text_to_cursor = request.text[: request.cursor_position]
        if not text_to_cursor.strip():
            return EmptyResponse()

        # Extract the last token (word) for abbreviation / trie lookup
        last_token = self._extract_last_token(text_to_cursor)

        # ── Stage 1: Abbreviation Map ──────────────────────────────
        if last_token:
            result = self._stage_abbreviation(last_token)
            if result:
                self._log_latency("abbreviation", start)
                return result

        # ── Stage 2: UMLS API (primary) → MARISA-Trie (fallback) ──
        if last_token and len(last_token) >= 2:
            result = await self._stage_umls(last_token)
            if result:
                self._log_latency("umls_api", start)
                return result
            result = self._stage_trie(last_token, text_to_cursor)
            if result:
                self._log_latency("trie", start)
                return result

        # ── Stage 3: Lab Pattern Engine ────────────────────────────
        result = self._stage_lab(text_to_cursor)
        if result:
            self._log_latency("lab_engine", start)
            return result

        # ── Stage 4: LLM Fallback ─────────────────────────────────
        result = await self._stage_llm(text_to_cursor, request.context_window or 200)
        if result:
            self._log_latency("llm", start)
            return result

        # ── No match ──────────────────────────────────────────────
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug("No suggestion found. Total time: %.1fms", elapsed)
        return EmptyResponse()

    # ── Stage Implementations ───────────────────────────────────────

    def _stage_abbreviation(self, token: str) -> Optional[AutocompleteResponse]:
        """Stage 1: Check abbreviation map."""
        match = self._dictionary.lookup_abbreviation(token)
        if not match:
            return None

        term, icd_code, snomed_code = match
        return AutocompleteResponse(
            suggestion=term,
            source=SuggestionSource.ABBREVIATION,
            icd_code=icd_code,
            snomed_code=snomed_code,
            confidence=1.0,
        )

    async def _stage_umls(self, token: str) -> Optional[AutocompleteResponse]:
        """Stage 2a: UMLS REST API live lookup (primary)."""
        if not self._umls or not self._umls.is_available:
            return None

        try:
            results = await self._umls.search(token, max_results=5)
            if not results:
                return None

            # Pick the best match (shortest term)
            results.sort(key=lambda r: len(r[0]))
            best_term, icd_code, snomed_code, loinc_code = results[0]

            token_lower = token.lower()
            if best_term.lower().startswith(token_lower):
                suggestion = best_term[len(token_lower):]
            else:
                suggestion = best_term

            return AutocompleteResponse(
                suggestion=suggestion,
                source=SuggestionSource.UMLS,
                icd_code=icd_code,
                snomed_code=snomed_code,
                loinc_code=loinc_code,
                confidence=0.95,
            )
        except Exception as e:
            logger.warning("UMLS stage error: %s", e)
            return None

    def _stage_trie(
        self, token: str, full_text: str
    ) -> Optional[AutocompleteResponse]:
        """Stage 2: MARISA-Trie prefix search."""
        results = self._dictionary.search_prefix(token, max_results=5)
        if not results:
            return None

        # Pick the best match (shortest term = most precise completion)
        best_term, icd_code, snomed_code, loinc_code = results[0]

        # The suggestion is the remaining portion after what the user typed
        token_lower = token.lower()
        if best_term.lower().startswith(token_lower):
            suggestion = best_term[len(token_lower):]
        else:
            suggestion = best_term

        if not suggestion:
            # Token exactly matches a term — no completion needed
            # But still return the code information
            suggestion = ""

        return AutocompleteResponse(
            suggestion=suggestion,
            source=SuggestionSource.TRIE,
            icd_code=icd_code,
            snomed_code=snomed_code,
            loinc_code=loinc_code,
            confidence=0.95,
        )

    def _stage_lab(self, text: str) -> Optional[AutocompleteResponse]:
        """Stage 3: Lab pattern detection."""
        lab_result = self._lab_engine.detect_lab_pattern(text)
        if not lab_result:
            return None

        # Map severity to LabFlag enum
        severity_to_flag = {
            Severity.LOW: LabFlag.LOW,
            Severity.HIGH: LabFlag.HIGH,
            Severity.CRITICAL_LOW: LabFlag.CRITICAL_LOW,
            Severity.CRITICAL_HIGH: LabFlag.CRITICAL_HIGH,
            Severity.NORMAL: LabFlag.NORMAL,
        }

        return AutocompleteResponse(
            suggestion=lab_result.message,
            source=SuggestionSource.LAB_ENGINE,
            loinc_code=lab_result.loinc_code,
            confidence=1.0,
            lab_flag=severity_to_flag.get(lab_result.severity, LabFlag.NORMAL),
        )

    async def _stage_llm(
        self, text: str, context_window: int
    ) -> Optional[AutocompleteResponse]:
        """Stage 4: BioMistral-7B via vLLM."""
        completion = await self._llm_client.complete(text, context_window)
        if not completion:
            return None

        return AutocompleteResponse(
            suggestion=completion,
            source=SuggestionSource.LLM,
            confidence=0.7,
        )

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_last_token(text: str) -> str:
        """
        Extract the last word/token from the text.
        Handles punctuation boundaries (colons, commas, etc.).
        """
        text = text.rstrip()
        if not text:
            return ""

        # Split on whitespace and common delimiters, keep the last token
        import re
        tokens = re.split(r"[\s,;]+", text)
        return tokens[-1] if tokens else ""

    @staticmethod
    def _log_latency(stage: str, start: float) -> None:
        elapsed = (time.perf_counter() - start) * 1000
        logger.info("Stage [%s] matched in %.1fms", stage, elapsed)
