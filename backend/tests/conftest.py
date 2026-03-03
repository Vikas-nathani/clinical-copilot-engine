"""
Shared test fixtures for Clinical Copilot Engine backend tests.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """Async test client with full app lifespan (services loaded)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_abbreviation_request():
    return {"text": "patient has htn", "cursor_position": 15}


@pytest.fixture
def sample_trie_request():
    return {"text": "patient has diab", "cursor_position": 16}


@pytest.fixture
def sample_lab_request():
    return {"text": "Glucose: 35", "cursor_position": 11}


@pytest.fixture
def sample_normal_lab_request():
    return {"text": "Glucose: 90", "cursor_position": 11}


@pytest.fixture
def sample_empty_request():
    return {"text": "   ", "cursor_position": 3}
