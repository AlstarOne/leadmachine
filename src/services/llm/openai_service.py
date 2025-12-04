"""OpenAI API service for text generation."""

import asyncio
from dataclasses import dataclass
from typing import Any

from src.config import get_settings


@dataclass
class GenerationResult:
    """Result of a text generation."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    finish_reason: str
    success: bool = True
    error: str | None = None


class OpenAIService:
    """Service for interacting with OpenAI API."""

    # Model configurations
    MODELS = {
        "gpt-4o-mini": {
            "max_tokens": 128000,
            "cost_per_1k_input": 0.00015,
            "cost_per_1k_output": 0.0006,
        },
        "gpt-4o": {
            "max_tokens": 128000,
            "cost_per_1k_input": 0.005,
            "cost_per_1k_output": 0.015,
        },
        "gpt-4-turbo": {
            "max_tokens": 128000,
            "cost_per_1k_input": 0.01,
            "cost_per_1k_output": 0.03,
        },
    }

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        """Initialize OpenAI service.

        Args:
            api_key: OpenAI API key. Defaults to settings.
            model: Model to use. Defaults to gpt-4o-mini.
            max_retries: Maximum retry attempts.
            timeout: Request timeout in seconds.
        """
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.model = model or self.DEFAULT_MODEL
        self.max_retries = max_retries
        self.timeout = timeout
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create OpenAI client."""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        stop: list[str] | None = None,
    ) -> GenerationResult:
        """Generate text using OpenAI API.

        Args:
            prompt: User prompt.
            system_prompt: System/role prompt.
            model: Model to use (overrides default).
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0-2).
            stop: Stop sequences.

        Returns:
            GenerationResult with generated text.
        """
        model = model or self.model
        client = self._get_client()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop,
            )

            choice = response.choices[0]
            usage = response.usage

            return GenerationResult(
                text=choice.message.content or "",
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                model=model,
                finish_reason=choice.finish_reason,
                success=True,
            )

        except Exception as e:
            return GenerationResult(
                text="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model=model,
                finish_reason="error",
                success=False,
                error=str(e),
            )

    async def generate_with_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> tuple[dict | None, GenerationResult]:
        """Generate JSON output using OpenAI API.

        Args:
            prompt: User prompt requesting JSON output.
            system_prompt: System/role prompt.
            model: Model to use.
            max_tokens: Maximum tokens.
            temperature: Sampling temperature.

        Returns:
            Tuple of (parsed_json, GenerationResult).
        """
        import json

        # Add JSON instruction to system prompt
        json_system = (system_prompt or "") + "\n\nYou must respond with valid JSON only. No markdown, no explanations."

        result = await self.generate(
            prompt=prompt,
            system_prompt=json_system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        if not result.success:
            return None, result

        try:
            # Try to extract JSON from response
            text = result.text.strip()

            # Handle markdown code blocks
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            parsed = json.loads(text.strip())
            return parsed, result
        except json.JSONDecodeError as e:
            result.success = False
            result.error = f"JSON parsing error: {e}"
            return None, result

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Count tokens in text.

        Args:
            text: Text to count tokens for.
            model: Model to use for tokenization.

        Returns:
            Token count.
        """
        try:
            import tiktoken

            model = model or self.model
            # Map model names to encoding
            if "gpt-4" in model or "gpt-3.5" in model:
                encoding = tiktoken.encoding_for_model(model)
            else:
                encoding = tiktoken.get_encoding("cl100k_base")

            return len(encoding.encode(text))
        except Exception:
            # Fallback: rough estimate (1 token ≈ 4 chars)
            return len(text) // 4

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Estimate cost for a request.

        Args:
            prompt_tokens: Number of input tokens.
            completion_tokens: Number of output tokens.
            model: Model used.

        Returns:
            Estimated cost in USD.
        """
        model = model or self.model
        if model not in self.MODELS:
            model = self.DEFAULT_MODEL

        config = self.MODELS[model]
        input_cost = (prompt_tokens / 1000) * config["cost_per_1k_input"]
        output_cost = (completion_tokens / 1000) * config["cost_per_1k_output"]
        return input_cost + output_cost

    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible.

        Returns:
            True if API is working.
        """
        try:
            result = await self.generate(
                prompt="Say 'ok'",
                max_tokens=5,
                temperature=0,
            )
            return result.success
        except Exception:
            return False
