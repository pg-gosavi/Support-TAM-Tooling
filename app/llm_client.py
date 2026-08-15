"""
Provider-agnostic LLM client for Groq (primary) and Gemini (fallback).

- Single interface (`LLMClient.complete_json`) used by both Task 1 and
  Task 2 pipelines; switching providers or models is an env-var change.
- Default model: openai/gpt-oss-120b (Groq's production-tier reasoning
  model). Reasoning tokens are suppressed via `include_reasoning=False`
  and `reasoning_effort=low` so `message.content` stays clean JSON; these
  are Groq-specific params passed via `extra_body` since they aren't part
  of the standard OpenAI schema. qwen/qwen3.6-27b is supported as an
  opt-in override (`GROQ_MODEL` env var) but isn't the default — Groq
  serves it as a preview model and it's primarily a vision model, neither
  of which is a fit for this text-only pipeline.
- Structured output uses `response_format={"type": "json_object"}` plus
  Pydantic validation, with up to `max_retries` retries that feed the
  validation error back to the model.
- Requests retry on rate-limit/connection errors with exponential backoff
  before falling through to the caller.
- If no provider is configured, `available` is False and callers fall back
  to a deterministic rule-based path rather than raising.
"""

from __future__ import annotations

import json
import os
import time
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

try:
    from openai import OpenAI
    from openai import APIConnectionError, APITimeoutError, RateLimitError
except ImportError:  # pragma: no cover - openai is a hard requirement, but
    OpenAI = None    # keep import-time failures readable if it's missing.
    APIConnectionError = APITimeoutError = RateLimitError = Exception

T = TypeVar("T", bound=BaseModel)


class LLMUnavailableError(RuntimeError):
    """Raised when a caller asks for a real completion but no provider is configured."""


class LLMOutputError(RuntimeError):
    """Raised when the model never returns valid, schema-conforming JSON."""


GROQ_MODEL_DEFAULT = "openai/gpt-oss-120b"
GEMINI_MODEL = "gemini-2.5-flash"


class LLMClient:
    """Wraps whichever provider is configured via environment variables."""

    def __init__(self) -> None:
        self.provider: str | None = None
        self.model: str | None = None
        self.client = None

        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

        if groq_key and groq_key != "your-key-here" and OpenAI is not None:
            self.provider = "groq"
            # Overridable via GROQ_MODEL env var so a provider/model swap never
            # requires touching code (see .env.example). Defaults to
            # openai/gpt-oss-120b — Groq's production-stage recommendation.
            # qwen/qwen3.6-27b is Groq's other official migration target for
            # the retired llama-3.3-70b-versatile, but Groq serves it as a
            # preview model ("intended for evaluation, not production") and
            # it's primarily positioned as multimodal/vision — no benefit for
            # this text-only pipeline, so it's opt-in, not default.
            self.model = os.environ.get("GROQ_MODEL", "").strip() or GROQ_MODEL_DEFAULT
            self.client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
            )
        elif gemini_key and gemini_key != "your-key-here" and OpenAI is not None:
            self.provider = "gemini"
            self.model = GEMINI_MODEL
            self.client = OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=gemini_key,
            )

    @property
    def available(self) -> bool:
        return self.client is not None

    def _extra_body(self) -> dict:
        """Groq-specific params that aren't part of the standard OpenAI schema,
        so they must go through `extra_body` rather than as named kwargs (the
        openai SDK validates kwargs client-side and would reject them).

        gpt-oss and qwen3-family models use different reasoning-control knobs
        on Groq: gpt-oss takes reasoning_effort in {low,medium,high} plus a
        separate include_reasoning bool; qwen3 models take reasoning_effort
        in {none,default} with no include_reasoning param. Branching here is
        what makes GROQ_MODEL a true drop-in env-var swap — the caller
        doesn't need to know which family it's talking to."""
        if not self.model:
            return {}
        if "gpt-oss" in self.model:
            return {
                "reasoning_effort": "low",   # narrow classification tasks don't need "high"
                "include_reasoning": False,  # keep message.content pure JSON, no chain-of-thought
            }
        if self.model.startswith("qwen/"):
            return {"reasoning_effort": "none"}  # disable "thinking mode" for speed + clean JSON
        return {}

    def _call_with_backoff(self, messages: list[dict], temperature: float, max_attempts: int = 4):
        """Retries on rate limits / transient connection errors with exponential
        backoff. Separate from the JSON-parse retry loop in complete_json — this
        handles transport-level failures, not model-output failures."""
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    messages=messages,
                    extra_body=self._extra_body(),
                )
            except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
                last_exc = exc
                if attempt == max_attempts - 1:
                    break
                time.sleep(delay)
                delay *= 2
        raise LLMOutputError(f"[{self.provider}] Request failed after {max_attempts} attempts (rate limit/transport): {last_exc}")

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        max_retries: int = 2,
        temperature: float = 0.0,
    ) -> T:
        """Call the LLM, parse the response as JSON, and validate it against `schema`.

        Retries up to `max_retries` times on parse/validation failure, feeding
        the error back to the model so it can correct itself. Raises
        LLMOutputError if it still can't produce valid output.
        """
        if not self.available:
            raise LLMUnavailableError(
                "No LLM provider configured. Set GROQ_API_KEY (or GEMINI_API_KEY) "
                "in your .env file — see .env.example."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            response = self._call_with_backoff(messages, temperature)
            raw = response.choices[0].message.content or ""
            try:
                data = json.loads(raw)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That response failed to parse/validate with error: "
                            f"{exc}\n\nReturn ONLY a single valid JSON object matching "
                            "the required schema. No prose, no markdown code fences."
                        ),
                    }
                )
                continue

        raise LLMOutputError(
            f"[{self.provider}] Model did not return schema-valid JSON after "
            f"{max_retries + 1} attempts. Last error: {last_error}"
        )


_client: LLMClient | None = None


def get_client() -> LLMClient:
    """Module-level singleton so callers don't each re-read the environment."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
