from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pyspiel

DEFAULT_BETTING_ABSTRACTION = "fchpa"


def build_nlhe_game_string(
    *,
    num_players: int,
    stacks: list[int],
    small_blind: int,
    big_blind: int,
    betting_abstraction: str = DEFAULT_BETTING_ABSTRACTION,
) -> str:
    """
    Build an OpenSpiel universal_poker game string for NLHE.

    Notes:
    - OpenSpiel universal_poker supports a limited betting abstraction in no-limit.
      In the OpenSpiel 1.5 wheels, supported abstractions include: fc, fcpa, fchpa.
    - We use a fixed positional mapping expected by the parameters:
      - player0 posts BB
      - player1 posts SB
      - player2 acts first preflop when num_players >= 3 (UTG)
      - player1 acts first postflop when num_players >= 3 (SB)
      - for heads-up, player1 (SB/button) acts first preflop, and player0 acts first postflop.
    """
    if num_players < 2:
        raise ValueError("num_players must be >= 2")
    if len(stacks) != num_players:
        raise ValueError("stacks length must equal num_players")
    if small_blind <= 0 or big_blind <= 0:
        raise ValueError("blinds must be positive")
    if big_blind < small_blind:
        raise ValueError("big_blind must be >= small_blind")

    # OpenSpiel expects per-player blind contributions (in seat order).
    blind_parts = [str(big_blind), str(small_blind)] + ["0"] * (num_players - 2)

    # ACPC firstPlayer values are 1-indexed.
    if num_players == 2:
        first_player = "2 1 1 1"
    else:
        first_player = "3 2 2 2"

    # Universal poker parameters for Texas Hold'em:
    # - 2 hole cards
    # - 4 rounds: preflop, flop, turn, river
    # - board cards: 0, 3, 1, 1
    # - 52 card deck (13 ranks, 4 suits)
    stack_parts = [str(int(x)) for x in stacks]
    game_string = (
        "universal_poker("
        f"betting=nolimit,"
        f"bettingAbstraction={betting_abstraction},"
        f"numPlayers={num_players},"
        "numRounds=4,"
        f"blind={' '.join(blind_parts)},"
        f"firstPlayer={first_player},"
        "numSuits=4,"
        "numRanks=13,"
        "numHoleCards=2,"
        "numBoardCards=0 3 1 1,"
        f"stack={' '.join(stack_parts)}"
        ")"
    )
    return game_string


def load_game(game_string: str) -> pyspiel.Game:
    return pyspiel.load_game(game_string)


_OBS_KV = re.compile(r"\[([^\]]+)\]")


@dataclass(frozen=True)
class ParsedObservation:
    round: int
    current_player: int
    pot: int
    money: list[int]
    private: str
    public: str
    ante: list[int] | None = None
    sequences: str | None = None


def parse_observation_string(obs: str) -> ParsedObservation:
    """
    Parse OpenSpiel universal_poker observation_string().

    Example:
      [Round 0][Player: 2][Pot: 600][Money: 19900 19950 20000 ...][Private: AcKc][Public: ][Ante: 100 50 0 0 0 0]
    """
    parts = _OBS_KV.findall(obs or "")
    kv: dict[str, str] = {}
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            kv[k.strip()] = v.strip()
        else:
            # "Round 0" style
            toks = p.strip().split(" ", 1)
            if len(toks) == 2:
                kv[toks[0].strip()] = toks[1].strip()

    def get_int(key: str) -> int:
        v = kv.get(key)
        if v is None:
            raise ValueError(f"missing {key}")
        return int(v)

    def get_list_int(key: str) -> list[int]:
        v = kv.get(key, "")
        v = v.strip()
        if not v:
            return []
        return [int(x) for x in v.split()]

    return ParsedObservation(
        round=get_int("Round"),
        current_player=get_int("Player"),
        pot=get_int("Pot"),
        money=get_list_int("Money"),
        private=kv.get("Private", ""),
        public=kv.get("Public", ""),
        ante=get_list_int("Ante") if "Ante" in kv else None,
        sequences=kv.get("Sequences"),
    )


def legal_action_types(state: pyspiel.State, player: int) -> dict[str, int]:
    """
    Return a mapping of canonical action types to OpenSpiel action ids.

    Supported types (depending on betting abstraction):
    - FOLD
    - CALL  (includes CHECK when to-call is 0)
    - BET   (pot-sized)
    - HALF_POT
    - ALL_IN
    """
    out: dict[str, int] = {}
    for a in state.legal_actions(player):
        s = state.action_to_string(player, a)
        if "Fold" in s:
            out["FOLD"] = a
        elif "Call" in s:
            out["CALL"] = a
        elif "HalfPot" in s or "HalfPot" in s.replace(" ", ""):
            out["HALF_POT"] = a
        elif "AllIn" in s or "All-in" in s or "AllIn" in s.replace(" ", ""):
            out["ALL_IN"] = a
        elif "Bet" in s:
            out["BET"] = a
    return out


def canonical_legal_actions(state: pyspiel.State, player: int) -> list[dict[str, Any]]:
    m = legal_action_types(state, player)
    order = ["FOLD", "CALL", "HALF_POT", "BET", "ALL_IN"]
    out: list[dict[str, Any]] = []
    for t in order:
        if t in m:
            out.append({"type": t})
    return out
