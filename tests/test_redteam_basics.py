import json
from pathlib import Path

from poker_arena.runner.agents.policies import PolicyAgent
from poker_arena.runner.runner import BlindSchedule, TournamentConfig, run_tournament_locally


def test_observation_does_not_include_opponent_latency(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    agents = [PolicyAgent("always_all_in", seed=i) for i in range(6)]
    setup_ids = [f"setup_{i}" for i in range(6)]
    cfg = TournamentConfig(
        starting_stack=1000,
        max_hands=20,
        decision_timeout_ms=500,
        betting_abstraction="fchpa",
        blind_schedule=BlindSchedule(levels=[(10, 20)], level_hands=9999),
    )
    _ = run_tournament_locally(
        tournament_id="t_sidechannel",
        seed=5,
        setup_ids=setup_ids,
        agents=agents,
        trace_path=trace_path,
        config=cfg,
    )

    for line in trace_path.read_text(encoding="utf-8").splitlines():
        ev = json.loads(line)
        if ev.get("type") != "OBSERVATION":
            continue
        obs = ev.get("obs") or {}
        assert "latency" not in json.dumps(obs).lower()

