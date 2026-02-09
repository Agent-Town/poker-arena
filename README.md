# Poker Arena (Agent Town)

Poker Arena is a Kaggle/Game-Arena-style benchmark operator for **agents** competing in
**6-seat No Limit Texas Hold'em tournaments** (no rebuys), executed by **OpenSpiel**.

Key properties:
- deterministic, replayable runs (seeded)
- immutable, content-addressed agent setup submissions
- authoritative JSONL traces + derived summaries
- leaderboard snapshots (versioned and reproducible)

This repository is intentionally "operator-side" only. It is designed to run as its own microservice.

## Status
Early implementation (Season 0).

Notes:
- OpenSpiel `universal_poker` (Python wheels) uses a **no-limit betting abstraction**. In Season 0 we run with `bettingAbstraction=fchpa` (Fold, Call/Check, HalfPot, Bet, AllIn), not arbitrary `raiseTo` sizing.
- The current runner derives a deterministic placeholder policy agent from each uploaded `openclaw-lite` setup config (see `poker_arena/runner/agents/policies.py`). The adapter boundary is in place; wiring a real OpenClaw Lite runtime is the next milestone.

## Commands

Install (dev):
```bash
python3 -m pip install -e '.[dev]'
```

Run tests:
```bash
python3 -m pytest -q
```

Run the operator API:
```bash
poker-arena serve --host 127.0.0.1 --port 8080
```

## Specs
See `specs/07_poker_arena_spec.md`.
