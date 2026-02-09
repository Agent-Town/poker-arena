from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from poker_arena.runner.agents.base import AgentDecision


@dataclass
class PolicyAgent:
    policy: str
    seed: int = 0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def decide(self, observation: dict[str, Any]) -> AgentDecision:
        legal = [a.get("type") for a in (observation.get("legalActions") or []) if isinstance(a, dict)]
        legal = [x for x in legal if isinstance(x, str)]
        if not legal:
            return AgentDecision(action_type="CALL")

        p = self.policy
        if p == "always_fold":
            return AgentDecision(action_type="CALL" if "CALL" in legal else legal[0]) if observation.get("public", {}).get("toCall", None) == 0 else AgentDecision(action_type="FOLD" if "FOLD" in legal else legal[0])
        if p == "always_all_in":
            if "ALL_IN" in legal:
                return AgentDecision(action_type="ALL_IN")
            return AgentDecision(action_type="CALL" if "CALL" in legal else legal[0])
        if p == "random":
            return AgentDecision(action_type=self._rng.choice(legal))
        if p == "invalid_once":
            # Useful in tests: first call invalid, second call folds if possible.
            if not hasattr(self, "_invalid_done"):
                setattr(self, "_invalid_done", True)
                return AgentDecision(action_type="INVALID_ACTION")
            return AgentDecision(action_type="FOLD" if "FOLD" in legal else legal[0])

        # Default: safe action.
        return AgentDecision(action_type="CALL" if "CALL" in legal else legal[0])

    def close(self) -> None:
        return

