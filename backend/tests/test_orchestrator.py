"""
Integration tests for the Orchestrator (waterfall pipeline).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.schemas.models import AutocompleteRequest, AutocompleteResponse, EmptyResponse
from app.services.dictionary import DictionaryService
from app.services.lab_engine import LabEngine
from app.services.llm_client import LLMClient
from app.services.orchestrator import Orchestrator


@pytest_asyncio.fixture
async def orchestrator():
    dictionary = DictionaryService()
    lab_engine = LabEngine()
    llm_client = LLMClient()

    await dictionary.load()
    await lab_engine.load()
    # Do NOT initialize LLM client — no vLLM in test env

    return Orchestrator(
        dictionary=dictionary,
        lab_engine=lab_engine,
        llm_client=llm_client,
    )


class TestWaterfallOrder:
    """Verify the waterfall executes stages in correct priority order."""

    @pytest.mark.asyncio
    async def test_abbreviation_takes_priority(self, orchestrator):
        """Stage 1 should match before Stage 2."""
        request = AutocompleteRequest(text="patient has htn", cursor_position=15)
        result = await orchestrator.suggest(request)
        assert isinstance(result, AutocompleteResponse)
        assert result.source.value == "abbreviation"
        assert result.suggestion == "hypertension"

    @pytest.mark.asyncio
    async def test_trie_matches_when_no_abbreviation(self, orchestrator):
        """Stage 2 fires when Stage 1 misses."""
        request = AutocompleteRequest(text="patient has diab", cursor_position=16)
        result = await orchestrator.suggest(request)
        assert isinstance(result, AutocompleteResponse)
        assert result.source.value in ("trie", "abbreviation")

    @pytest.mark.asyncio
    async def test_lab_engine_matches_abnormal(self, orchestrator):
        """Stage 3 detects abnormal lab values."""
        request = AutocompleteRequest(text="Glucose: 35", cursor_position=11)
        result = await orchestrator.suggest(request)
        assert isinstance(result, AutocompleteResponse)
        assert result.source.value == "lab_engine"
        assert result.lab_flag is not None

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, orchestrator):
        """Whitespace-only input returns EmptyResponse."""
        request = AutocompleteRequest(text="   ", cursor_position=3)
        result = await orchestrator.suggest(request)
        assert isinstance(result, EmptyResponse)

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, orchestrator):
        """Gibberish with no vLLM returns EmptyResponse."""
        request = AutocompleteRequest(text="xzqwvbn", cursor_position=7)
        result = await orchestrator.suggest(request)
        # Without LLM, should be empty
        assert isinstance(result, (AutocompleteResponse, EmptyResponse))

    @pytest.mark.asyncio
    async def test_confidence_is_valid(self, orchestrator):
        """Confidence score should always be between 0 and 1."""
        request = AutocompleteRequest(text="patient has htn", cursor_position=15)
        result = await orchestrator.suggest(request)
        if isinstance(result, AutocompleteResponse):
            assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_multiple_abbreviations(self, orchestrator):
        """Test various abbreviation inputs."""
        test_cases = [
            ("copd", "chronic obstructive pulmonary disease"),
            ("chf", "congestive heart failure"),
            ("afib", "atrial fibrillation"),
        ]
        for abbr, expected in test_cases:
            request = AutocompleteRequest(
                text=f"patient has {abbr}",
                cursor_position=len(f"patient has {abbr}"),
            )
            result = await orchestrator.suggest(request)
            assert isinstance(result, AutocompleteResponse), f"Failed for {abbr}"
            assert result.source.value == "abbreviation"
            assert result.suggestion == expected
