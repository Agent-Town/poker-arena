import random

import pyspiel

from poker_arena.engine.universal_poker import build_nlhe_game_string, load_game
from poker_arena.util.hashing import canonical_json_bytes, sha256_hex


def _simulate_one_hand(*, seed: int) -> dict:
    rng = random.Random(seed)
    gs = build_nlhe_game_string(
        num_players=6,
        stacks=[20_000] * 6,
        small_blind=50,
        big_blind=100,
        betting_abstraction="fchpa",
    )
    game = load_game(gs)
    state = game.new_initial_state()

    actions = []
    while not state.is_terminal():
        if state.is_chance_node():
            outcomes = state.chance_outcomes()
            actions_list, probs = zip(*outcomes)
            r = rng.random()
            cum = 0.0
            chosen = actions_list[-1]
            for a, p in zip(actions_list, probs):
                cum += p
                if r <= cum:
                    chosen = a
                    break
            actions.append(int(chosen))
            state.apply_action(chosen)
        else:
            la = state.legal_actions(state.current_player())
            chosen = la[rng.randrange(len(la))]
            actions.append(int(chosen))
            state.apply_action(chosen)

    returns = [int(round(x)) for x in state.returns()]
    return {"gameString": gs, "seed": seed, "actions": actions, "returns": returns}


def test_load_game_nlhe_6max() -> None:
    gs = build_nlhe_game_string(
        num_players=6,
        stacks=[10_000] * 6,
        small_blind=50,
        big_blind=100,
        betting_abstraction="fchpa",
    )
    game = load_game(gs)
    assert isinstance(game, pyspiel.Game)
    assert game.num_players() == 6
    gt = game.get_type()
    assert gt.dynamics.name == "SEQUENTIAL"
    assert gt.chance_mode.name in {"EXPLICIT_STOCHASTIC", "SAMPLED_STOCHASTIC"}
    assert gt.information.name == "IMPERFECT_INFORMATION"


def test_random_hand_simulation_smoke() -> None:
    for s in range(10):
        rec = _simulate_one_hand(seed=1000 + s)
        assert len(rec["actions"]) > 0
        assert sum(rec["returns"]) == 0


def test_deterministic_hand_hash_golden() -> None:
    rec_a = _simulate_one_hand(seed=123)
    rec_b = _simulate_one_hand(seed=123)
    assert rec_a == rec_b
    h = sha256_hex(canonical_json_bytes({"actions": rec_a["actions"], "returns": rec_a["returns"]}))
    # Golden value pinned to OpenSpiel 1.5 universal_poker(fchpa) with the above simulation.
    assert h == "5a576bad5e6632a7c8cd6e3c09dd00924b52fdaaded07a910077d6d504b0c0b9"
