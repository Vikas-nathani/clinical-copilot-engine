"""
Unit tests for the DictionaryService (abbreviation map + MARISA-Trie).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.services.dictionary import DictionaryService


@pytest_asyncio.fixture
async def dictionary():
    svc = DictionaryService()
    await svc.load()
    return svc


class TestAbbreviationLookup:
    """Stage 1: Abbreviation map tests."""

    def test_known_abbreviation(self, dictionary):
        result = dictionary.lookup_abbreviation("htn")
        assert result is not None
        term, icd, snomed = result
        assert term == "hypertension"
        assert icd == "I10"

    def test_case_insensitive(self, dictionary):
        result = dictionary.lookup_abbreviation("HTN")
        assert result is not None
        assert result[0] == "hypertension"

    def test_unknown_abbreviation(self, dictionary):
        result = dictionary.lookup_abbreviation("xyzabc123")
        assert result is None

    def test_diabetes_abbreviations(self, dictionary):
        for abbr in ("dm", "dm1", "dm2", "t1dm", "t2dm"):
            result = dictionary.lookup_abbreviation(abbr)
            assert result is not None, f"Expected {abbr} to be recognized"
            assert "diabetes" in result[0].lower()

    def test_abbreviation_with_whitespace(self, dictionary):
        result = dictionary.lookup_abbreviation("  htn  ")
        assert result is not None
        assert result[0] == "hypertension"

    def test_medication_abbreviations(self, dictionary):
        for abbr in ("nsaid", "ssri", "acei", "ppi"):
            result = dictionary.lookup_abbreviation(abbr)
            assert result is not None, f"Expected {abbr} to be recognized"

    def test_abbreviation_count(self, dictionary):
        assert dictionary.abbreviation_count > 200


class TestTriePrefixSearch:
    """Stage 2: MARISA-Trie prefix search tests."""

    def test_prefix_search_returns_results(self, dictionary):
        results = dictionary.search_prefix("hypert")
        assert len(results) > 0
        # First result should be the shortest match
        assert "hypert" in results[0][0].lower()

    def test_prefix_too_short(self, dictionary):
        results = dictionary.search_prefix("h")
        assert len(results) == 0

    def test_prefix_no_match(self, dictionary):
        results = dictionary.search_prefix("xyznonexistent")
        assert len(results) == 0

    def test_prefix_max_results(self, dictionary):
        results = dictionary.search_prefix("di", max_results=3)
        assert len(results) <= 3

    def test_trie_loaded(self, dictionary):
        assert dictionary.is_loaded
        assert dictionary.trie_term_count > 0
