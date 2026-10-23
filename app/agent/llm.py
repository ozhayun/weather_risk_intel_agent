"""Provider-agnostic structured LLM calls. Switch providers via LLM_MODEL only."""

from typing import Protocol, TypeVar

import instructor
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredLLM(Protocol):
    def complete(
        self, response_model: type[T], messages: list[dict], context: dict | None = None
    ) -> T: ...


class InstructorLLM:
    """`model` is "<provider>/<model>", e.g. openai/gpt-4o-mini, anthropic/..., ollama/..."""

    def __init__(self, model: str, max_retries: int = 2, temperature: float = 0.0):
        self.model = model
        self.max_retries = max_retries
        self.temperature = temperature
        self._client = instructor.from_provider(model)

    def complete(
        self, response_model: type[T], messages: list[dict], context: dict | None = None
    ) -> T:
        return self._client.create(
            response_model=response_model,
            messages=messages,
            max_retries=self.max_retries,
            context=context,
            temperature=self.temperature,
        )
