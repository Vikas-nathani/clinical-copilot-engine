"""
LLM Client — Stage 4 of the Waterfall.

Async client for BioMistral-7B served via Ollama (CPU-friendly Q4 quant).
Only invoked when all deterministic stages (abbreviation, trie, lab) fail.

Features:
- Async HTTP via httpx (non-blocking)
- Configurable timeout, temperature, max_tokens
- Graceful degradation if Ollama is unreachable or model not yet pulled
- Medical system prompt for grounded completions
- Streaming support via async generator for SSE endpoint
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ── System Prompt ───────────────────────────────────────────────────
# Instructs the model to behave as a clinical note autocomplete engine.
SYSTEM_PROMPT = (
    "You are a medical clinical note autocomplete assistant. "
    "Given the beginning of a clinical note, complete the current "
    "sentence or phrase. Respond ONLY with the completion text — "
    "do NOT repeat the input, do NOT add explanations, do NOT use "
    "markdown. Keep completions concise (1-2 clauses maximum). "
    "Use standard medical terminology and accepted abbreviations."
)


class LLMClient:
    """
    Async client for Ollama-served BioMistral-7B.

    Uses the Ollama /api/chat endpoint.
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    async def initialize(self) -> None:
        """Create the async HTTP client and probe Ollama health."""
        settings = get_settings()
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_url,
            timeout=httpx.Timeout(settings.ollama_timeout_seconds),
            headers={"Content-Type": "application/json"},
        )
        # Probe: check if Ollama is reachable and model is available
        await self._health_check()

    async def shutdown(self) -> None:
        """Cleanly close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._available = False
            logger.info("LLM client shut down.")

    async def complete(
        self,
        text: str,
        context_window: int = 200,
    ) -> Optional[str]:
        """
        Request a sentence completion from BioMistral-7B via Ollama.

        Args:
            text: The clinical note text up to the cursor.
            context_window: How many trailing characters to send as context.

        Returns:
            The completion string, or None if Ollama is unavailable / errors.
        """
        if not self._client or not self._available:
            return None

        settings = get_settings()

        # Trim to context window (send only recent text for efficiency)
        context = text[-context_window:] if len(text) > context_window else text

        payload = {
            "model": settings.ollama_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            "stream": False,
            "options": {
                "num_predict": settings.ollama_max_tokens,
                "temperature": settings.ollama_temperature,
                "top_p": settings.ollama_top_p,
                "repeat_penalty": settings.ollama_repeat_penalty,
                "stop": ["\n", ".", "Patient", "ASSESSMENT", "PLAN"],
            },
        }

        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

            # Extract completion text from Ollama response
            completion = data.get("message", {}).get("content", "").strip()

            # Enforce max suggestion length
            if len(completion) > settings.max_suggestion_length:
                completion = completion[: settings.max_suggestion_length].rsplit(" ", 1)[0]

            return completion if completion else None

        except httpx.TimeoutException:
            logger.warning("Ollama request timed out after %ss.", settings.ollama_timeout_seconds)
            return None
        except httpx.ConnectError:
            logger.warning("Ollama not reachable. LLM stage skipped.")
            self._available = False
            return None
        except httpx.HTTPStatusError as e:
            logger.warning("Ollama HTTP error: %s %s", e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            logger.error("Ollama unexpected error: %s", e, exc_info=True)
            return None

    async def stream(
        self,
        text: str,
        context_window: int = 200,
    ) -> AsyncGenerator[str, None]:
        """
        Stream tokens from Ollama for the SSE endpoint.

        Yields:
            Individual token strings as they arrive from the model.
        """
        if not self._client or not self._available:
            return

        settings = get_settings()
        context = text[-context_window:] if len(text) > context_window else text

        payload = {
            "model": settings.ollama_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            "stream": True,
            "options": {
                "num_predict": settings.ollama_max_tokens,
                "temperature": settings.ollama_temperature,
                "top_p": settings.ollama_top_p,
                "repeat_penalty": settings.ollama_repeat_penalty,
                "stop": ["\n", ".", "Patient", "ASSESSMENT", "PLAN"],
            },
        }

        try:
            stream_timeout = httpx.Timeout(settings.ollama_stream_timeout_seconds)
            async with self._client.stream(
                "POST", "/api/chat", json=payload, timeout=stream_timeout
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
        except httpx.TimeoutException:
            logger.warning("Ollama stream timed out.")
        except httpx.ConnectError:
            logger.warning("Ollama not reachable during stream.")
            self._available = False
        except Exception as e:
            logger.error("Ollama stream error: %s", e, exc_info=True)

    async def _health_check(self) -> None:
        """Probe Ollama /api/tags endpoint to check availability and model presence."""
        if not self._client:
            self._available = False
            return

        settings = get_settings()
        try:
            response = await self._client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if our target model (or a prefix of it) is loaded
                model_found = any(
                    settings.ollama_model in m or m.startswith(settings.ollama_model.split(":")[0])
                    for m in models
                )
                if model_found:
                    logger.info("Ollama is available. Model '%s' found.", settings.ollama_model)
                    self._available = True
                else:
                    logger.warning(
                        "Ollama is running but model '%s' not found. "
                        "Available models: %s. Run pull_model.sh to download.",
                        settings.ollama_model,
                        models,
                    )
                    self._available = False
            else:
                logger.warning(
                    "Ollama health check returned %s. LLM stage disabled.",
                    response.status_code,
                )
                self._available = False
        except httpx.ConnectError:
            logger.info(
                "Ollama not reachable (connection refused). LLM stage disabled. "
                "This is expected if Ollama is still starting up."
            )
            self._available = False
        except Exception as e:
            logger.warning("Ollama health check failed: %s. LLM stage disabled.", e)
            self._available = False
