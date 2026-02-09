from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from poker_arena.engine.universal_poker import load_game


@dataclass(frozen=True)
class ReplayResult:
    tournament_id: str
    finish_order: list[int]
    hands: int


def replay_tournament_from_trace(trace_path: Path) -> ReplayResult:
    """
    Deterministically replays a tournament from the authoritative trace by applying
    the recorded chance and decision actions to OpenSpiel.

    This is a verification tool: it asserts that the trace is internally consistent.
    """
    events = _read_jsonl(trace_path)

    # Basic metadata
    tournament_id = ""
    end_result: dict[str, Any] | None = None

    # Per-hand action streams in original trace order.
    hands: dict[int, dict[str, Any]] = {}
    for ev in events:
        t = ev.get("type")
        if t == "RUN_START":
            tournament_id = str((ev.get("matchSpec") or {}).get("tournamentId") or "")
        if t == "HAND_START":
            hi = int(ev["handIndex"])
            hands[hi] = {"gameString": ev["gameString"], "actions": [], "expectedReturns": None}
        if t == "CHANCE_ACTION":
            hi = int(ev["handIndex"])
            hands[hi]["actions"].append(int(ev["action"]))
        if t == "ENGINE_APPLY":
            hi = int(ev["handIndex"])
            hands[hi]["actions"].append(int(ev["action"]))
        if t == "HAND_END":
            hi = int(ev["handIndex"])
            hands[hi]["expectedReturns"] = [int(x) for x in ev.get("returns") or []]
        if t == "TOURNAMENT_END":
            end_result = ev.get("result") or None

    # Replay each hand independently.
    for hi in sorted(hands.keys()):
        rec = hands[hi]
        game = load_game(rec["gameString"])
        state = game.new_initial_state()
        for a in rec["actions"]:
            state.apply_action(a)
        if not state.is_terminal():
            raise ValueError(f"replay did not reach terminal for hand {hi}")
        expected = rec.get("expectedReturns")
        if expected is not None:
            got = [int(round(x)) for x in state.returns()]
            if got != expected:
                raise ValueError(f"return mismatch for hand {hi}: got={got} expected={expected}")

    if not end_result:
        raise ValueError("missing TOURNAMENT_END")
    finish = [int(x) for x in end_result.get("finishOrder") or []]
    return ReplayResult(tournament_id=tournament_id, finish_order=finish, hands=int(end_result.get("hands") or len(hands)))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = path.read_text(encoding="utf-8").splitlines()
    for line in raw:
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out

