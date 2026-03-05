"""
Orchestrator — Waterfall Autocomplete Controller.

Executes the 4-stage waterfall in strict sequential order:
  1. Abbreviation map lookup
  2. Lab pattern engine
  3. MARISA-Trie prefix search (Local Dictionary)
  4. BioMistral-7B (vLLM) fallback

Returns the first successful match, assembling it into an
AutocompleteResponse for the API layer.
"""

from __future__ import annotations

import logging
import re
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
        """
        start = time.perf_counter()

        # 1. Validation
        if request.cursor_position is None or request.cursor_position < 0:
            # Fallback if cursor not provided: use end of text
            request.cursor_position = len(request.text)

        text_to_cursor = request.text[: request.cursor_position]
        if not text_to_cursor.strip():
            return EmptyResponse()

        # 2. Extract context
        last_token = self._extract_last_token(text_to_cursor)
        last_phrase = self._extract_last_phrase(text_to_cursor, max_words=3)

        # ── Stage 1: Abbreviation (single token only) ──────────────
        if last_token and " " not in last_token:
            result = self._stage_abbreviation(last_token)
            if result:
                self._log_latency("abbreviation", start)
                return result

        # ── Stage 2: Lab Pattern Engine ────────────────────────────
        # Checks for patterns like "Glucose: 35"
        result = self._stage_lab(text_to_cursor)
        if result:
            self._log_latency("lab_engine", start)
            return result

        # ── Stage 3: Dictionary (UMLS/Trie) ────────────────────────
        # Try phrase first (e.g. "type 2 dia"), then token (e.g. "obesi")
        search_term = last_phrase if len(last_phrase) > len(last_token) else last_token
        
        if search_term and len(search_term) >= 2:
            # A. Try UMLS API (if configured)
            result = await self._stage_umls(search_term)
            if result:
                self._log_latency("umls_api", start)
                return result
            
            # B. Try Local Trie (Primary Lookup)
            result = self._stage_trie(search_term, text_to_cursor)
            if result:
                self._log_latency("trie", start)
                return result
            
            # C. Fallback: Check just the last token in Trie if phrase failed
            if search_term != last_token and last_token and len(last_token) >= 2:
                result = self._stage_trie(last_token, text_to_cursor)
                if result:
                    self._log_latency("trie_token", start)
                    return result

        # ── Stage 4: LLM Fallback (BioMistral) ─────────────────────
        # Only triggers if no dictionary/lab/abbreviation match found
        result = await self._stage_llm(text_to_cursor, request.context_window or 200)
        if result:
            self._log_latency("llm", start)
            return result

        elapsed = (time.perf_counter() - start) * 1000
        logger.debug("No suggestion found. Total time: %.1fms", elapsed)
        return EmptyResponse()

    # ── Stage Implementations ───────────────────────────────────────

    def _stage_abbreviation(self, token: str) -> Optional[AutocompleteResponse]:
        """Stage 1: Check abbreviation map."""
        match = self._dictionary.lookup_abbreviation(token)
        if not match:
            return None

        # Expecting tuple: (term, icd_code, snomed_code)
        term, icd_code, snomed_code = match
        return AutocompleteResponse(
            suggestion=term,
            source=SuggestionSource.ABBREVIATION,
            icd_code=icd_code,
            snomed_code=snomed_code,
            confidence=1.0,
        )

    def _stage_lab(self, text: str) -> Optional[AutocompleteResponse]:
        """Stage 2: Lab pattern detection."""
        lab_result = self._lab_engine.detect_lab_pattern(text)
        if not lab_result:
            return None

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

    def _stage_trie(self, token: str, full_text: str) -> Optional[AutocompleteResponse]:
        """Stage 3B: MARISA-Trie prefix search."""
        # Search trie
        results = self._dictionary.search_prefix(token, max_results=5)
        if not results:
            return None

        # Dictionary returns list of: (term, icd_code, snomed_code, loinc_code)
        best_match = results[0]
        best_term = best_match[0]
        
        # Calculate completion (what needs to be added)
        token_lower = token.lower()
        if best_term.lower().startswith(token_lower):
            suggestion = best_term[len(token_lower):]
        else:
            suggestion = best_term # Should rare happen with prefix search

        return AutocompleteResponse(
            suggestion=suggestion,
            source=SuggestionSource.TRIE,
            icd_code=best_match[1],
            snomed_code=best_match[2],
            loinc_code=best_match[3],
            confidence=0.95,
        )

    async def _stage_umls(self, token: str) -> Optional[AutocompleteResponse]:
        """Stage 3A: UMLS REST API (Optional)."""
        if not self._umls or not self._umls.is_available:
            return None
        
        try:
            results = await self._umls.search(token, max_results=1)
            if not results:
                return None
            
            best_match = results[0]
            best_term = best_match[0]

            token_lower = token.lower()
            if best_term.lower().startswith(token_lower):
                suggestion = best_term[len(token_lower):]
            else:
                suggestion = best_term

            return AutocompleteResponse(
                suggestion=suggestion,
                source=SuggestionSource.UMLS,
                icd_code=best_match[1],
                snomed_code=best_match[2],
                loinc_code=best_match[3],
                confidence=0.95,
            )
        except Exception as e:
            logger.warning(f"UMLS lookup failed: {e}")
            return None

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
        """Extract the last word/token."""
        text = text.rstrip()
        if not text:
            return ""
        tokens = re.split(r"[\s,;]+", text)
        return tokens[-1] if tokens else ""

    @staticmethod
    def _extract_last_phrase(text: str, max_words: int = 3) -> str:
        """Extract last N words."""
        text = text.rstrip()
        if not text:
            return ""
        tokens = re.split(r"[\s,;]+", text)
        tokens = [t for t in tokens if t]
        return " ".join(tokens[-max_words:]).lower()

    @staticmethod
    def _log_latency(stage: str, start: float) -> None:
        elapsed = (time.perf_counter() - start) * 1000
        logger.info("Stage [%s] matched in %.1fms", stage, elapsed)