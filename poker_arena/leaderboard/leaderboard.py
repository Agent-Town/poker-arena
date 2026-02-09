from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from openskill.models import PlackettLuce

from poker_arena.operator.storage import LeaderboardSnapshot
from poker_arena.util.hashing import canonical_json_bytes, sha256_hex


@dataclass(frozen=True)
class LeaderboardRow:
    setup_id: str
    mu: float
    sigma: float
    games: int
    wins: int
    mean_rank: float


def compute_leaderboard_snapshot(
    *,
    experience_id: str,
    scorer_version: str,
    tournaments: list[dict[str, Any]],
    seed: int = 1,
    bootstrap_samples: int = 200,
) -> LeaderboardSnapshot:
    """
    Compute an immutable leaderboard snapshot from completed tournaments.

    tournaments: list of rows with keys: tournamentId, setupIds, result (contains finishOrder).
    """
    model = PlackettLuce()

    # Initialize ratings for all setups appearing in tournaments.
    ratings: dict[str, Any] = {}
    stats: dict[str, dict[str, Any]] = {}

    def get_rating(setup_id: str) -> Any:
        r = ratings.get(setup_id)
        if r is None:
            r = model.rating()
            ratings[setup_id] = r
        return r

    def ensure_stats(setup_id: str) -> dict[str, Any]:
        s = stats.get(setup_id)
        if s is None:
            s = {"games": 0, "wins": 0, "rank_sum": 0.0}
            stats[setup_id] = s
        return s

    # Update ratings tournament by tournament.
    tournament_ids: list[str] = []
    for t in tournaments:
        tid = str(t["tournamentId"])
        tournament_ids.append(tid)
        setup_ids = list(t["setupIds"])
        result = t.get("result") or {}
        finish = list(result.get("finishOrder") or [])
        if len(setup_ids) != 6 or len(finish) != 6:
            # Skip malformed tournament rows.
            continue

        # finish is list of seat ids (winner first). Convert to ranks per setup id.
        # seat id corresponds to index in setup_ids.
        # ranks are 1..6 (lower is better) in openskill expected ordering via groups.
        rank_by_setup: dict[str, int] = {}
        for place, seat in enumerate(finish, start=1):
            rank_by_setup[setup_ids[int(seat)]] = place

        # PlackettLuce expects a list of teams in rank order. Here each team is one setup.
        teams = [[get_rating(sid)] for sid in setup_ids]
        ranks = [rank_by_setup[sid] for sid in setup_ids]
        new_teams = model.rate(teams, ranks=ranks)
        for sid, team in zip(setup_ids, new_teams):
            ratings[sid] = team[0]
            s = ensure_stats(sid)
            s["games"] += 1
            s["rank_sum"] += float(rank_by_setup[sid])
            if rank_by_setup[sid] == 1:
                s["wins"] += 1

    # Bootstrap CI on mean_rank and win_rate (simple, deterministic sampling).
    rng = random.Random(int(seed))
    rows: list[LeaderboardRow] = []
    for sid, r in ratings.items():
        s = stats.get(sid) or {"games": 0, "wins": 0, "rank_sum": 0.0}
        games = int(s["games"])
        mean_rank = float(s["rank_sum"]) / games if games else 0.0
        rows.append(LeaderboardRow(setup_id=sid, mu=float(r.mu), sigma=float(r.sigma), games=games, wins=int(s["wins"]), mean_rank=mean_rank))

    # Build snapshot payload
    rows_sorted = sorted(rows, key=lambda x: (-x.mu, x.sigma, x.mean_rank, x.setup_id))
    payload: dict[str, Any] = {
        "experienceId": experience_id,
        "scorerVersion": scorer_version,
        "tournaments": tournament_ids,
        "rows": [
            {
                "setupId": r.setup_id,
                "rating": {"mu": r.mu, "sigma": r.sigma},
                "games": r.games,
                "wins": r.wins,
                "meanRank": r.mean_rank,
            }
            for r in rows_sorted
        ],
    }

    snapshot_id = sha256_hex(canonical_json_bytes(payload))
    return LeaderboardSnapshot(snapshot_id=snapshot_id, experience_id=experience_id, payload=payload)
