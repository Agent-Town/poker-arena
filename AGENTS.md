# Working agreements for coding agents

This repo is a microservice: Poker Arena (agent benchmark operator).

## Primary goals
1. Deterministic replay (seeded) with immutable, append-only traces.
2. Objective grading and reproducible leaderboard snapshots.
3. Content-addressed setup uploads (immutable by hash).
4. Test-driven development (pytest is the source of truth).

## Constraints
- Do not introduce real API keys or secrets in configs or tests.
- Keep the first implementation minimal and auditable.
- Prefer pure-Python orchestration; OpenSpiel is the authoritative game engine.

## Commands
Install:
```bash
python3 -m pip install -e '.[dev]'
```

Tests:
```bash
python3 -m pytest -q
```

Run operator:
```bash
poker-arena serve --host 127.0.0.1 --port 8080
```

## Definition of done
- All tests pass.
- Determinism tests (golden hashes) pass.
- Trace and leaderboard snapshot IDs are stable and versioned.

