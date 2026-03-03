"""
Unit tests for the Lab Pattern Engine.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.services.lab_engine import LabEngine, Severity


@pytest_asyncio.fixture
async def lab_engine():
    engine = LabEngine()
    await engine.load()
    return engine


class TestLabPatternDetection:
    """Stage 3: Lab pattern engine tests."""

    def test_critical_low_glucose(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Glucose: 35")
        assert result is not None
        assert result.severity == Severity.CRITICAL_LOW
        assert result.test_name == "Glucose"

    def test_critical_high_potassium(self, lab_engine):
        result = lab_engine.detect_lab_pattern("K: 7.2")
        assert result is not None
        assert result.severity == Severity.CRITICAL_HIGH

    def test_low_hemoglobin(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Hgb: 6.5")
        assert result is not None
        assert result.severity in (Severity.LOW, Severity.CRITICAL_LOW)

    def test_high_sodium(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Na: 155")
        assert result is not None
        assert result.severity == Severity.HIGH

    def test_normal_glucose_returns_none(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Glucose: 90")
        assert result is None  # Normal values should not trigger

    def test_normal_sodium_returns_none(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Na: 140")
        assert result is None

    def test_no_lab_pattern(self, lab_engine):
        result = lab_engine.detect_lab_pattern("patient complains of headache")
        assert result is None

    def test_equals_separator(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Glucose = 35")
        assert result is not None
        assert result.severity == Severity.CRITICAL_LOW

    def test_lab_ranges_count(self, lab_engine):
        assert lab_engine.lab_ranges_count >= 85

    def test_loinc_code_present(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Glucose: 35")
        assert result is not None
        assert result.loinc_code is not None

    def test_message_format(self, lab_engine):
        result = lab_engine.detect_lab_pattern("K: 7.2")
        assert result is not None
        assert "normal range" in result.message.lower()

    def test_critical_high_glucose(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Glucose: 600")
        assert result is not None
        assert result.severity == Severity.CRITICAL_HIGH

    def test_elevated_troponin(self, lab_engine):
        result = lab_engine.detect_lab_pattern("Troponin: 0.5")
        assert result is not None
        assert result.severity in (Severity.HIGH, Severity.CRITICAL_HIGH)
