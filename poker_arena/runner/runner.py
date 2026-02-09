from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyspiel

from poker_arena.engine.universal_poker import (
    DEFAULT_BETTING_ABSTRACTION,
    ParsedObservation,
    build_nlhe_game_string,
    canonical_legal_actions,
    legal_action_types,
    load_game,
    parse_observation_string,
)
from poker_arena.runner.agents.base import Agent, AgentDecision
from poker_arena.runner.agents.policies import PolicyAgent
from poker_arena.runner.trace import TraceWriter
from poker_arena.util.hashing import canonical_json_bytes, sha256_hex


@dataclass(frozen=True)
class BlindSchedule:
    levels: list[tuple[int, int]]  # (sb, bb)
    level_hands: int

    def blinds_for_hand(self, hand_index: int) -> tuple[int, int]:
        if not self.levels:
            raise ValueError("blind levels required")
        idx = min(hand_index // max(1, self.level_hands), len(self.levels) - 1)
        return self.levels[idx]


@dataclass(frozen=True)
class TournamentConfig:
    starting_stack: int = 10_000
    max_hands: int = 2_000
    decision_timeout_ms: int = 2_000
    betting_abstraction: str = DEFAULT_BETTING_ABSTRACTION
    blind_schedule: BlindSchedule = BlindSchedule(levels=[(50, 100), (75, 150), (100, 200)], level_hands=20)


def run_tournament_locally(
    *,
    tournament_id: str,
    seed: int,
    setup_ids: list[str],
    agents: list[Agent],
    trace_path: Path,
    config: TournamentConfig | None = None,
) -> dict[str, Any]:
    """
    Run one 6-seat tournament deterministically and write a JSONL trace.

    The environment is OpenSpiel universal_poker with an action abstraction.
    """
    cfg = config or TournamentConfig()
    if len(agents) != 6:
        raise ValueError("expected 6 agents")

    rng = random.Random(int(seed))
    trace = TraceWriter(trace_path)

    match_spec = {
        "tournamentId": tournament_id,
        "seed": int(seed),
        "setups": [{"seat": i, "setupId": setup_ids[i]} for i in range(6)],
        "config": {
            "startingStack": cfg.starting_stack,
            "maxHands": cfg.max_hands,
            "decisionTimeoutMs": cfg.decision_timeout_ms,
            "bettingAbstraction": cfg.betting_abstraction,
            "blindSchedule": {"levelHands": cfg.blind_schedule.level_hands, "levels": cfg.blind_schedule.levels},
        },
    }

    run_fingerprint = sha256_hex(canonical_json_bytes({"matchSpec": match_spec, "runner": "runner_v0"}))
    trace.append({"type": "RUN_START", "runFingerprint": run_fingerprint, "matchSpec": match_spec})

    # Seat ids are stable (0..5) even when busted. Stacks tracked per seat.
    stacks: list[int] = [cfg.starting_stack] * 6
    active: set[int] = {i for i in range(6)}
    button_seat = 5  # deterministic start: seat 5 is button in hand 0
    elimination: list[int] = []  # from first eliminated to last eliminated (winner last)

    def next_active(after_seat: int) -> int:
        for offset in range(1, 7):
            s = (after_seat + offset) % 6
            if s in active:
                return s
        return after_seat

    def build_positions() -> list[int]:
        # Clockwise positions starting from button.
        pos = [button_seat]
        cur = button_seat
        while len(pos) < len(active):
            cur = next_active(cur)
            pos.append(cur)
        return pos

    hand_index = 0
    while len(active) > 1 and hand_index < cfg.max_hands:
        sb, bb = cfg.blind_schedule.blinds_for_hand(hand_index)
        positions = build_positions()
        num_players = len(positions)

        # Map stable seat ids -> OpenSpiel player ids.
        # For 2 players: openspiel seat1 is button/SB, seat0 is BB.
        # For N>=3: openspiel seat(N-1)=button, seat1=SB, seat0=BB, seat2=UTG, seat3=..., seat(N-2)=CO.
        os_to_seat: list[int] = [-1] * num_players
        if num_players == 2:
            os_to_seat[1] = positions[0]  # button (SB)
            os_to_seat[0] = positions[1]  # BB
        else:
            os_to_seat[num_players - 1] = positions[0]  # button
            os_to_seat[1] = positions[1]  # SB
            os_to_seat[0] = positions[2]  # BB
            for j in range(3, num_players):
                os_to_seat[j - 1] = positions[j]

        seat_to_os = {seat: i for i, seat in enumerate(os_to_seat)}
        os_stacks = [stacks[s] for s in os_to_seat]

        game_string = build_nlhe_game_string(
            num_players=num_players,
            stacks=os_stacks,
            small_blind=sb,
            big_blind=bb,
            betting_abstraction=cfg.betting_abstraction,
        )
        game = load_game(game_string)
        state = game.new_initial_state()

        trace.append(
            {
                "type": "HAND_START",
                "handIndex": hand_index,
                "buttonSeat": button_seat,
                "activeSeats": positions,
                "smallBlind": sb,
                "bigBlind": bb,
                "stacksBySeat": {str(i): stacks[i] for i in range(6)},
                "openSpielToSeat": os_to_seat,
                "gameString": game_string,
            }
        )

        # Hand playthrough
        while not state.is_terminal():
            if state.is_chance_node():
                outcomes = state.chance_outcomes()
                actions, probs = zip(*outcomes)
                r = rng.random()
                cum = 0.0
                chosen = actions[-1]
                for a, p in zip(actions, probs):
                    cum += p
                    if r <= cum:
                        chosen = a
                        break
                trace.append(
                    {
                        "type": "CHANCE_ACTION",
                        "handIndex": hand_index,
                        "action": int(chosen),
                        "actionStr": state.action_to_string(state.current_player(), chosen),
                    }
                )
                state.apply_action(chosen)
                continue

            os_player = state.current_player()
            seat = os_to_seat[os_player]
            obs_str = state.observation_string(os_player)
            parsed: ParsedObservation = parse_observation_string(obs_str)
            legal = canonical_legal_actions(state, os_player)
            obs_obj = {
                "handIndex": hand_index,
                "seat": seat,
                "openSpielPlayer": os_player,
                "round": parsed.round,
                "pot": parsed.pot,
                "money": parsed.money,
                "private": parsed.private,
                "public": parsed.public,
                "legalActions": legal,
            }
            obs_hash = sha256_hex(canonical_json_bytes(obs_obj))
            trace.append({"type": "OBSERVATION", "handIndex": hand_index, "seat": seat, "obsHash": obs_hash, "obs": obs_obj})

            # Decision with one retry on invalid.
            action_type = None
            action_id = None
            types = legal_action_types(state, os_player)

            def forced_safe_action_type() -> str:
                return "CALL" if "CALL" in types else ("FOLD" if "FOLD" in types else next(iter(types.keys())))

            for attempt in range(2):
                start = time.time()
                decision: AgentDecision | None = None
                try:
                    decision = _decide_with_timeout(
                        agents[seat],
                        obs_obj,
                        timeout_ms=cfg.decision_timeout_ms,
                    )
                except TimeoutError:
                    violation = {"kind": "TIMEOUT", "attempt": attempt}
                    latency_ms = int((time.time() - start) * 1000)
                    trace.append({"type": "VIOLATION", "handIndex": hand_index, "seat": seat, "violation": violation})
                    action_type = forced_safe_action_type()
                    action_id = types[action_type]
                    trace.append(
                        {
                            "type": "AGENT_DECISION",
                            "handIndex": hand_index,
                            "seat": seat,
                            "actionType": action_type,
                            "openSpielAction": int(action_id),
                            "latencyMs": latency_ms,
                            "attempt": attempt,
                            "forced": True,
                            "violation": violation,
                        }
                    )
                    break
                latency_ms = int((time.time() - start) * 1000)

                if decision and decision.action_type in types:
                    action_type = decision.action_type
                    action_id = types[action_type]
                    trace.append(
                        {
                            "type": "AGENT_DECISION",
                            "handIndex": hand_index,
                            "seat": seat,
                            "actionType": action_type,
                            "openSpielAction": int(action_id),
                            "latencyMs": latency_ms,
                            "attempt": attempt,
                        }
                    )
                    break

                # Invalid
                violation = {"kind": "INVALID_ACTION", "attempt": attempt, "actionType": getattr(decision, "action_type", None)}
                trace.append(
                    {
                        "type": "VIOLATION",
                        "handIndex": hand_index,
                        "seat": seat,
                        "violation": violation,
                    }
                )
                if attempt == 0:
                    continue

                # Forced safe action on second failure.
                action_type = forced_safe_action_type()
                action_id = types[action_type]
                trace.append(
                    {
                        "type": "AGENT_DECISION",
                        "handIndex": hand_index,
                        "seat": seat,
                        "actionType": action_type,
                        "openSpielAction": int(action_id),
                        "latencyMs": latency_ms,
                        "attempt": attempt,
                        "forced": True,
                        "violation": violation,
                    }
                )
                break

            assert action_id is not None
            trace.append(
                {
                    "type": "ENGINE_APPLY",
                    "handIndex": hand_index,
                    "seat": seat,
                    "openSpielPlayer": os_player,
                    "action": int(action_id),
                    "actionStr": state.action_to_string(os_player, action_id),
                }
            )
            state.apply_action(action_id)

        returns = state.returns()
        # Update stacks for active seats in this hand.
        before = {s: stacks[s] for s in positions}
        for os_player, seat in enumerate(os_to_seat):
            delta = int(round(returns[os_player]))
            stacks[seat] += delta
        after = {s: stacks[s] for s in positions}

        busted: list[int] = []
        for s in list(active):
            if stacks[s] <= 0:
                stacks[s] = 0
                active.remove(s)
                busted.append(s)

        # Deterministic elimination ordering if multiple bust:
        # sort by stack-before-hand asc, then seat id asc (bust first).
        if busted:
            busted.sort(key=lambda s: (before.get(s, 0), s))
            elimination.extend(busted)

        trace.append(
            {
                "type": "HAND_END",
                "handIndex": hand_index,
                "returns": [int(round(x)) for x in returns],
                "stacksBefore": {str(k): v for k, v in before.items()},
                "stacksAfter": {str(k): v for k, v in after.items()},
                "busted": busted,
            }
        )

        # Advance button
        button_seat = next_active(button_seat)
        hand_index += 1

    if len(active) == 1:
        winner = next(iter(active))
        elimination.append(winner)
    else:
        # Fail-safe: rank remaining by stack desc, then seat id.
        remaining = sorted(list(active), key=lambda s: (-stacks[s], s))
        elimination.extend(remaining)

    finish_order = list(reversed(elimination))  # winner first

    result = {
        "tournamentId": tournament_id,
        "seed": int(seed),
        "runFingerprint": run_fingerprint,
        "setupIds": setup_ids,
        "finishOrder": finish_order,
        "hands": hand_index,
        "finalStacks": {str(i): stacks[i] for i in range(6)},
    }

    trace.append({"type": "TOURNAMENT_END", "result": result})
    trace_res = trace.close()

    result["traceSha256"] = trace_res.sha256
    result["traceBytes"] = trace_res.bytes_written
    return result


def _decide_with_timeout(agent: Agent, observation: dict[str, Any], *, timeout_ms: int) -> AgentDecision:
    """
    Runs agent.decide with a wall-clock timeout.
    """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(agent.decide, observation)
        try:
            return fut.result(timeout=timeout_ms / 1000.0)
        except concurrent.futures.TimeoutError as e:
            raise TimeoutError("decision timeout") from e


def make_agent_from_setup(setup: dict[str, Any], *, seed: int) -> Agent:
    policy = str((setup.get("config") or {}).get("policy") or "random")
    return PolicyAgent(policy=policy, seed=seed)


def run_tournament(*, storage: "OperatorStorage", tournament_id: str) -> None:
    """
    Operator entrypoint. Loads tournament row, runs it deterministically, writes trace+summary,
    then stores the result back into metadata storage.
    """
    # Local import to avoid a hard dependency cycle (operator imports runner).
    from poker_arena.operator.storage import OperatorStorage

    if not isinstance(storage, OperatorStorage):
        raise TypeError("storage must be OperatorStorage")

    t = storage.get_tournament(tournament_id)
    if not t:
        raise ValueError("TOURNAMENT_NOT_FOUND")

    exp = storage.get_experience(t["experienceId"])
    if not exp:
        raise ValueError("EXPERIENCE_NOT_FOUND")

    setups: list[dict[str, Any]] = []
    for sid in t["setupIds"]:
        s = storage.get_setup(sid)
        if not s:
            raise ValueError(f"SETUP_NOT_FOUND:{sid}")
        setups.append({"setupId": s.setup_id, "framework": s.framework, "config": s.config, "bundle": s.bundle})

    # For Season0 MVP we run local policy agents derived from setup configs.
    seed = int(t["seed"])
    agents: list[Agent] = []
    for seat, setup in enumerate(setups):
        # Derive a per-seat seed from tournament seed and seat id for determinism.
        agents.append(make_agent_from_setup(setup, seed=seed * 31 + seat))

    run_dir = storage.run_dir(tournament_id)
    trace_path = run_dir / "trace.jsonl"
    summary_path = run_dir / "summary.json"

    # Compute run fingerprint including the experience hash.
    match_fp_payload = {
        "experienceId": exp.experience_id,
        "experienceHash": exp.experience_hash,
        "tournamentId": tournament_id,
        "seed": seed,
        "setupIds": t["setupIds"],
        "runner": "runner_v0",
        "engine": exp.engine,
    }
    run_fingerprint = sha256_hex(canonical_json_bytes(match_fp_payload))
    storage.mark_tournament_running(tournament_id, run_fingerprint=run_fingerprint)

    try:
        result = run_tournament_locally(
            tournament_id=tournament_id,
            seed=seed,
            setup_ids=t["setupIds"],
            agents=agents,
            trace_path=trace_path,
        )
    finally:
        for a in agents:
            try:
                a.close()
            except Exception:
                pass

    # Persist summary immutably
    tmp = summary_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    tmp.replace(summary_path)
    os.chmod(summary_path, 0o444)

    storage.mark_tournament_complete(
        tournament_id,
        trace_path=str(trace_path),
        summary_path=str(summary_path),
        result=result,
    )
