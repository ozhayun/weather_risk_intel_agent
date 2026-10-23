"""Test double for the StructuredLLM protocol."""

from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass
class Call:
    response_model: type
    messages: list[dict]
    context: dict | None


@dataclass
class FakeLLM:
    """Returns queued responses in order; an Exception in the queue is raised instead."""

    responses: list[BaseModel | Exception]
    calls: list[Call] = field(default_factory=list)

    def complete(self, response_model, messages, context=None):
        self.calls.append(Call(response_model, messages, context))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
