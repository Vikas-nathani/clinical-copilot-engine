"""
LLM Client — Stage 4 of the Waterfall.

Async client for BioMistral-7B served via vLLM with an OpenAI-compatible API.
Only invoked when all deterministic stages (abbreviation, trie, lab) fail.

Features:
- Async HTTP via httpx (non-blocking)
- Configurable timeout, temperature, max_tokens
- Graceful degradation if vLLM is unreachable
- Medical system prompt for grounded completions
"""

from __future__ import annotations

import logging
from typing import Optional

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
    Async client for vLLM-served BioMistral-7B.

    Uses the OpenAI-compatible /v1/completions endpoint.
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    async def initialize(self) -> None:
        """Create the async HTTP client and probe vLLM health."""
        settings = get_settings()
        self._client = httpx.AsyncClient(
            base_url=settings.vllm_base_url,
            timeout=httpx.Timeout(settings.vllm_timeout_seconds),
            headers={"Content-Type": "application/json"},
        )
        # Probe: check if vLLM is reachable
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
        Request a sentence completion from BioMistral-7B.

        Args:
            text: The clinical note text up to the cursor.
            context_window: How many trailing characters to send as context.

        Returns:
            The completion string, or None if the LLM is unavailable / errors.
        """
        if not self._client or not self._available:
            return None

        settings = get_settings()

        # Trim to context window (send only recent text for efficiency)
        context = text[-context_window:] if len(text) > context_window else text

        payload = {
            "model": settings.vllm_model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            "max_tokens": settings.vllm_max_tokens,
            "temperature": settings.vllm_temperature,
            "top_p": settings.vllm_top_p,
            "stop": ["\n", ".", "Patient", "ASSESSMENT", "PLAN"],
            "stream": False,
        }

        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            # Extract completion text from OpenAI-compatible response
            choices = data.get("choices", [])
            if not choices:
                logger.warning("LLM returned empty choices.")
                return None

            completion = choices[0].get("message", {}).get("content", "").strip()

            # Enforce max suggestion length
            if len(completion) > settings.max_suggestion_length:
                completion = completion[: settings.max_suggestion_length].rsplit(" ", 1)[0]

            return completion if completion else None

        except httpx.TimeoutException:
            logger.warning("LLM request timed out after %ss.", settings.vllm_timeout_seconds)
            return None
        except httpx.HTTPStatusError as e:
            logger.warning("LLM HTTP error: %s %s", e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            logger.error("LLM unexpected error: %s", e, exc_info=True)
            return None

    async def _health_check(self) -> None:
        """Probe vLLM /models endpoint to check availability."""
        if not self._client:
            self._available = False
            return

        try:
            response = await self._client.get("/models")
            if response.status_code == 200:
                data = response.json()
                models = [m.get("id", "") for m in data.get("data", [])]
                logger.info("vLLM is available. Models: %s", models)
                self._available = True
            else:
                logger.warning(
                    "vLLM health check returned %s. LLM stage disabled.",
                    response.status_code,
                )
                self._available = False
        except httpx.ConnectError:
            logger.info(
                "vLLM not reachable (connection refused). LLM stage disabled. "
                "This is expected in dev mode without a GPU."
            )
            self._available = False
        except Exception as e:
            logger.warning("vLLM health check failed: %s. LLM stage disabled.", e)
            self._available = False
