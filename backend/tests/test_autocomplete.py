"""
API endpoint tests for POST /autocomplete and GET /health.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """GET /health returns 200 with expected fields."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "trie_loaded" in data
    assert "abbreviation_count" in data
    assert "lab_ranges_count" in data
    assert "llm_available" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_autocomplete_abbreviation(client, sample_abbreviation_request):
    """POST /autocomplete with 'htn' returns abbreviation expansion."""
    response = await client.post("/autocomplete", json=sample_abbreviation_request)
    assert response.status_code == 200
    data = response.json()
    assert data["suggestion"] == "hypertension"
    assert data["source"] == "abbreviation"
    assert data["icd_code"] == "I10"
    assert data["confidence"] == 1.0


@pytest.mark.asyncio
async def test_autocomplete_trie(client, sample_trie_request):
    """POST /autocomplete with 'diab' returns trie prefix match."""
    response = await client.post("/autocomplete", json=sample_trie_request)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] in ("trie", "abbreviation")
    assert data["suggestion"] is not None


@pytest.mark.asyncio
async def test_autocomplete_lab_warning(client, sample_lab_request):
    """POST /autocomplete with 'Glucose: 35' returns lab warning."""
    response = await client.post("/autocomplete", json=sample_lab_request)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "lab_engine"
    assert "CRITICAL" in data["suggestion"] or "Low" in data["suggestion"]
    assert data["lab_flag"] in ("critical_low", "low")


@pytest.mark.asyncio
async def test_autocomplete_empty_input(client, sample_empty_request):
    """POST /autocomplete with whitespace-only text returns empty."""
    response = await client.post("/autocomplete", json=sample_empty_request)
    assert response.status_code == 200
    data = response.json()
    assert data["suggestion"] is None


@pytest.mark.asyncio
async def test_autocomplete_validation_error(client):
    """POST /autocomplete with invalid payload returns 422."""
    response = await client.post("/autocomplete", json={"text": "", "cursor_position": 0})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_autocomplete_cursor_exceeds_text(client):
    """POST /autocomplete with cursor > text length returns 422."""
    response = await client.post(
        "/autocomplete",
        json={"text": "hello", "cursor_position": 100},
    )
    assert response.status_code == 422
