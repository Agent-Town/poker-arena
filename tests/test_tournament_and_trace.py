import json
import os
import time
from pathlib import Path

from poker_arena.replay import replay_tournament_from_trace
from poker_arena.runner.agents.policies import PolicyAgent
from poker_arena.runner.runner import BlindSchedule, TournamentConfig, run_tournament_locally


def _read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_tournament_completes_and_conserves_chips(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    agents = [PolicyAgent("always_all_in", seed=i) for i in range(6)]
    setup_ids = [f"setup_{i}" for i in range(6)]
    cfg = TournamentConfig(
        starting_stack=2000,
        max_hands=200,
        decision_timeout_ms=500,
        betting_abstraction="fchpa",
        blind_schedule=BlindSchedule(levels=[(10, 20)], level_hands=9999),
    )
    result = run_tournament_locally(
        tournament_id="t_test",
        seed=42,
        setup_ids=setup_ids,
        agents=agents,
        trace_path=trace_path,
        config=cfg,
    )
    assert result["finishOrder"] and len(result["finishOrder"]) == 6
    final_sum = sum(int(v) for v in result["finalStacks"].values())
    assert final_sum == 6 * cfg.starting_stack
    assert result["hands"] > 0

    # Trace is immutable (read-only) after close.
    st_mode = os.stat(trace_path).st_mode
    assert (st_mode & 0o200) == 0  # owner-writable bit should be off

    # Replay verifies and matches finish order
    rep = replay_tournament_from_trace(trace_path)
    assert rep.finish_order == result["finishOrder"]


def test_invalid_action_penalty_forces_safe_action(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    agents = [PolicyAgent("always_all_in", seed=i) for i in range(6)]
    agents[3] = PolicyAgent("invalid_once", seed=123)
    setup_ids = [f"setup_{i}" for i in range(6)]
    cfg = TournamentConfig(
        starting_stack=1500,
        max_hands=50,
        decision_timeout_ms=500,
        betting_abstraction="fchpa",
        blind_schedule=BlindSchedule(levels=[(10, 20)], level_hands=9999),
    )
    _ = run_tournament_locally(
        tournament_id="t_invalid",
        seed=7,
        setup_ids=setup_ids,
        agents=agents,
        trace_path=trace_path,
        config=cfg,
    )
    ev = _read_events(trace_path)
    violations = [e for e in ev if e.get("type") == "VIOLATION" and e.get("seat") == 3]
    assert violations, "expected at least one invalid-action violation for seat 3"


def test_timeout_forces_action(tmp_path) -> None:
    class SlowAgent(PolicyAgent):
        def decide(self, observation):
            time.sleep(0.01)
            return super().decide(observation)

    trace_path = tmp_path / "trace.jsonl"
    agents = [PolicyAgent("always_all_in", seed=i) for i in range(6)]
    agents[0] = SlowAgent("always_all_in", seed=0)
    setup_ids = [f"setup_{i}" for i in range(6)]
    cfg = TournamentConfig(
        starting_stack=1200,
        max_hands=12,
        decision_timeout_ms=1,  # force timeout
        betting_abstraction="fchpa",
        blind_schedule=BlindSchedule(levels=[(10, 20)], level_hands=9999),
    )
    _ = run_tournament_locally(
        tournament_id="t_timeout",
        seed=9,
        setup_ids=setup_ids,
        agents=agents,
        trace_path=trace_path,
        config=cfg,
    )
    ev = _read_events(trace_path)
    timeout_viol = [e for e in ev if e.get("type") == "AGENT_DECISION" and e.get("seat") == 0 and e.get("violation", {}).get("kind") == "TIMEOUT"]
    assert timeout_viol, "expected timeout violations for seat 0"
