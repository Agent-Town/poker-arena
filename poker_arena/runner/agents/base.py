from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentDecision:
    action_type: str
    raw: dict[str, Any] | None = None


class Agent(Protocol):
    def decide(self, observation: dict[str, Any]) -> AgentDecision:
        ...

    def close(self) -> None:
        ...

