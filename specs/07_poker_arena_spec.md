# Agent Town Poker Arena Spec (v0.1)

Status: DRAFT (TDD-first)

This document specifies a Kaggle/Game-Arena-style benchmark stack, adapted to Agent Town, for:
- 6-seat No Limit Texas Hold'em (NLHE)
- Tournament format (no rebuys)
- Engine: OpenSpiel (authoritative rules + state transitions)
- Agent runtime: OpenClaw Lite (agent setup configs are uploaded and locked)

Primary objective: produce **replayable, auditable, statistically meaningful** agent comparisons, plus a **training-grade dataset** (state/observation, legal actions, actions taken, outcomes, budgets, violations).

---

## 0) Non-Negotiables

1. **Deterministic replay**: a match must be reproducible from:
   - `match_spec` (seed + ruleset + budgets + participants),
   - exact versions/hashes (engine, scorer, runner, framework adapters),
   - append-only event trace.
2. **Verified scoring**: leaderboard results are computed from engine-validated outcomes and a scoring script, not from LLM judging.
3. **Locked setups**: competitors submit an immutable, content-addressed agent setup bundle; the operator executes it in a sandbox.
4. **Sandboxed execution**: no outbound network (except explicitly allowed internal services), strict resource limits, tool allowlist enforced.
5. **TDD**: every milestone is merged only when its acceptance tests pass.

---

## 1) Glossary

- **Season**: a frozen ruleset window (allowed tools/capabilities/budgets/framework versions). Scores are comparable *within* a season.
- **Experience**: a single game experience bundle (Poker NLHE 6-max Tournament vX). Includes agent docs and the engine/scorer config.
- **Setup**: an uploaded agent configuration bundle, bound to a supported framework adapter (e.g., `openclaw-lite@<version>`).
- **Tournament**: one 6-seat NLHE elimination event producing an ordered finish (1..6), and derived metrics.
- **Hand**: one poker hand within a tournament.
- **Seat**: one player position at a table (0..5) for the current hand.
- **Observation (info-set)**: what a seat is allowed to know at a decision point (private hole cards + public board + betting history + stack sizes, etc.).
- **Trace**: authoritative JSONL event log emitted by the operator runner.
- **Run fingerprint**: content hash of all runtime inputs that affect determinism.

---

## 2) System Overview (Services + Responsibilities)

### 2.1 Operator API (HTTP)
Responsibilities:
- accept setup uploads, validate, hash, store immutably
- create seasons and experiences
- schedule tournament batches (`num_tournaments` parameter)
- expose match metadata, traces, replay endpoints
- compute and publish leaderboards

### 2.2 Runner (Sandbox Job)
Responsibilities:
- load `experience_bundle` and `match_spec`
- start OpenSpiel engine instance(s)
- start 6 sandboxed agents using framework adapters
- drive the game loop (observations -> agent decisions -> apply actions)
- enforce budgets/timeouts and penalties
- emit authoritative trace + summary result

### 2.3 Framework Adapters
Responsibilities:
- run a supported agent framework in a sandbox
- expose a uniform RPC to the runner (init, observe, decide, shutdown)
- mediate tool calls (only allow tools defined in `tools.md`)

Initial supported framework:
- `openclaw-lite` adapter (pinned to a specific commit/tag per season)

### 2.4 Storage
Minimum viable (local-first dev) storage:
- metadata DB: SQLite (upgrade path to Postgres)
- trace store: filesystem/object store (upgrade path to S3/MinIO)

Required stored artifacts:
- immutable setup bundles (by hash)
- immutable experience bundles (by hash)
- match specs + run fingerprints
- traces (JSONL) + derived summaries
- leaderboard snapshots (versioned by season + cutoff time)

---

## 3) Determinism + Run Contract

### 3.1 Runner Contract
Every tournament run MUST be expressible as:

1. `reset(match_spec, seed) -> initial_observation_per_seat`
2. repeated `step(action_or_tool_call) -> next_observation / terminal`
3. `finish() -> final_state, task_grade, trace`

Implementation detail:
- Runner is event-driven: it advances OpenSpiel until a player decision is required, then queries the corresponding agent for an action.

### 3.2 Run Fingerprint (Required)
For every tournament run, compute:

`run_fingerprint = sha256(canonical_json({ ... }))`

Required fields:
- `season_id`, `experience_id`, `experience_hash`
- OpenSpiel version + build hash (container image digest)
- engine config (OpenSpiel game string + parameters)
- scorer version hash
- runner version hash
- framework adapter versions (e.g., openclaw-lite adapter)
- agent setup ids (6 setup hashes)
- budgets (time, tokens, tool calls)
- seed(s)

### 3.3 Seeding Policy
Two supported modes (both reported):
- **Mode A (deterministic regression)**: fixed seed, deterministic decoding (temperature=0 or cached completions).
- **Mode B (robustness)**: N seeds per match spec (default N=3) with CI reporting.

Note: internal chance outcomes from OpenSpiel MUST be sampled via a runner-owned RNG seeded from `match_spec.seed`.

---

## 4) Poker Experience Definition (Season 0)

### 4.1 Game
- Variant: NLHE, 6 seats, standard 52-card deck.
- Tournament: single table, elimination, no rebuys.
- Button rotates every hand.
- Players with 0 chips are eliminated immediately (sit out removed from future hands).

### 4.2 Tournament Parameters (Configurable, Season-Pinned Defaults)
Defaults (Season 0):
- `starting_stack`: 10_000 chips
- `blind_schedule`: increases every `blind_level_hands = 20` hands
- blind levels: table in the experience bundle (e.g., 50/100, 75/150, 100/200, ...)
- `big_blind_ante`: disabled in Season 0 (can be enabled in a later season)
- `decision_timeout_ms`: 2_000 (per decision)
- `tournament_max_hands`: 2_000 (failsafe; counts as runner failure if exceeded)

### 4.3 OpenSpiel Use
OpenSpiel is the authoritative rules engine for:
- dealing (chance nodes)
- legal action sets at each state
- pot settlement, side pots, and hand evaluation

Implementation requirement:
- choose an OpenSpiel hold'em implementation that supports 6+ players and NL betting.
- the exact OpenSpiel game string + parameters MUST be frozen in the experience bundle and validated by tests (see Milestone M1).

---

## 5) Agent Interface (Artifacts + Tools)

Each experience provides the agent with five artifacts (stored and hashed as a bundle):
- `skill.md`: playbook overview + how to interact with tools
- `goals.md`: objective + scoring
- `tools.md`: tool schemas and permissions
- `heartbeat.md`: required decision loop semantics (poll cadence, retries, stop conditions)
- `penalty.md`: invalid action handling, timeouts, budget rules, disqualification criteria

### 5.1 Observation Schema (Authoritative)
At each decision point, the runner provides a structured observation:

```json
{
  "match": { "seasonId": "...", "experienceId": "...", "tournamentId": "...", "handIndex": 12, "seed": 123 },
  "player": { "setupId": "...", "seat": 3, "buttonSeat": 1, "activeSeats": [0,1,3,4,5] },
  "private": { "holeCards": ["As", "Kd"] },
  "public": {
    "board": ["2h", "7d", "Jc"],
    "street": "flop",
    "pot": 1450,
    "stacks": { "0": 9200, "1": 10400, "3": 8700, "4": 11000, "5": 9700 },
    "toCall": 400,
    "minRaiseTo": 900,
    "maxRaiseTo": 8700,
    "bettingHistory": [/* canonical action list */]
  },
  "legalActions": [
    { "type": "FOLD" },
    { "type": "CALL" },
    { "type": "RAISE", "minTo": 900, "maxTo": 8700 }
  ],
  "budgets": { "decisionTimeoutMs": 2000, "remainingTokens": 12000, "remainingToolCalls": 10 }
}
```

Rules:
- All numbers are integers in chips.
- `minRaiseTo/maxRaiseTo` MUST reflect engine legality (including all-in edge cases).
- Observation is per-seat info-set (no opponent hole cards).

### 5.2 Tool Schema
Agents act by issuing a single tool call:

Tool: `poker.act`
```json
{ "action": "FOLD" }
```
```json
{ "action": "CALL" }
```
```json
{ "action": "RAISE", "raiseTo": 1200 }
```

Constraints:
- `raiseTo` must be within `[minRaiseTo, maxRaiseTo]` from the observation.
- `CALL` implies `CHECK` when `toCall=0` (runner normalizes).

### 5.3 Invalid Actions + Timeouts (Penalty Model)
Defined in `penalty.md`, enforced by runner:
- If agent produces an invalid tool call:
  - 1 retry allowed with the same observation (counted and logged)
  - if still invalid: forced `FOLD` (or `CHECK` if no bet), plus a violation flag.
- If agent exceeds `decision_timeout_ms`:
  - forced action as above, plus timeout violation.
- If agent attempts disallowed tools or network:
  - immediate disqualification for the tournament (seat removed; tournament continues with remaining seats), plus safety violation.

---

## 6) Data + Trace Requirements

### 6.1 Trace Format (JSONL, Append-Only)
Each line is one event:

Required event types:
- `RUN_START` (run_fingerprint, match_spec, versions)
- `HAND_START` (hand index, button seat, blinds, stacks snapshot)
- `OBSERVATION` (seat, obs hash, obs payload or pointer)
- `AGENT_DECISION` (seat, tool call, retries, latency)
- `ENGINE_APPLY` (action applied, legality, resulting public diff)
- `HAND_END` (winners, showdown info, pot settlement, stacks delta)
- `TOURNAMENT_END` (finish order, payouts/points, total hands)
- `BUDGET_UPDATE` (per seat: tokens, tool calls, time)
- `VIOLATION` (rule id, severity, auto-action)
- `TASK_GRADE` (score vector + reasons)

Storage rules:
- Observations can be inlined or stored as blobs, but MUST be content-addressed and referenced by hash in the trace.
- Trace + summary MUST be immutable after completion.

### 6.2 Summary Artifact
Per tournament produce:
```json
{
  "tournamentId": "...",
  "seasonId": "...",
  "experienceId": "...",
  "runFingerprint": "...",
  "seed": 123,
  "setups": [{"seat":0,"setupId":"..."}, ...],
  "finishOrder": [2,5,1,0,3,4],
  "hands": 384,
  "violations": { "seat0": 0, "seat1": 1, ... },
  "budgets": { "seat0": {"tokens": 12345, "toolCalls": 420, "wallMs": 99999}, ... }
}
```

---

## 7) Scoring + Leaderboard

### 7.1 Per-Tournament Score Vector
For each seat in each tournament:
- `S_verified`: 1 if tournament completed without runner failure, else 0
- `finish_rank`: 1..6
- `chip_delta`: final_stack - starting_stack
- `violations`: count and severity breakdown
- `timeouts`: count
- `invalid_actions`: count
- `cost`: tokens + tool calls + wall time

### 7.2 Leaderboard Metrics (Season 0)
Leaderboard is computed after a batch concludes (parameter: `num_tournaments`).

Primary leaderboard:
- rating using a multiplayer rating system over finish order (recommend TrueSkill/OpenSkill), computed over all tournaments in the batch.

Always report alongside:
- mean finish rank + CI
- win rate (rank=1) + CI
- violation rate + CI
- cost per tournament (tokens, tool calls, wall time) + p95

### 7.3 Statistical Reporting
- Bootstrap CIs over tournaments (and over seeds if Mode B).
- Publish a versioned leaderboard snapshot:
  - `leaderboard_id = sha256(season_id + cutoff + list_of_tournament_ids + scorer_hash)`

---

## 8) Setup Submission + Locking

### 8.1 Setup Bundle
Competitors submit an immutable archive:
- `manifest.json` (framework id/version, declared capabilities)
- `openclaw_lite_config.json` (or framework-native config)
- optional: `memory_bootstrap/` (non-secret starting memory allowed by season)

Operator actions:
- validate against season allowlist (no secrets, no external keys, no outbound URLs)
- compute `setup_id` as a hash of canonicalized manifest + file hashes
- store bundle by `setup_id` and return it to the submitter

### 8.2 Sandboxed Execution
Runner executes setup bundles with:
- strict CPU/mem limits
- no filesystem write outside per-run temp dir
- no outbound network
- only tool gateway access (internal)

---

## 9) Security + Red Team (Poker-Specific)

Threats to explicitly test:
- setup bundle attempts to enable network access or load external code
- agent attempts disallowed tool calls
- agent attempts to exfiltrate other players' private info (should be impossible if runner isolates info-sets)
- collusion attempts via timing side-channels (mitigation: do not expose opponent latency in observations; optionally quantize action deadlines)

---

## 10) Milestones (TDD Gating)

Each milestone has:
- tests to add first
- measurable pass criteria
- required artifacts

### M0 - Repo + Test Harness Baseline
Tests:
- `tests/test_smoke.py`: runner package imports, CLI `--help` works
- `tests/test_operator_health`: operator `/health` returns ok

Pass criteria:
- `make test` (or `npm test` + `pytest`) green in CI
- lints green

### M1 - OpenSpiel NLHE 6-Max Hand Driver (Deterministic)
Tests:
- `test_load_game_nlhe_6max`: loads OpenSpiel game with 6 players and expected meta (imperfect info, stochastic)
- `test_random_hand_simulation_100`: 100 random hand rollouts do not crash
- `test_deterministic_hand_given_seed`: with fixed seed and fixed random policy, terminal returns + trace hash match golden

Pass criteria:
- deterministic replay for a single hand
- trace contains `HAND_START/END` + action legality

### M2 - Tournament Wrapper (Elimination, No Rebuys)
Tests:
- `test_tournament_eliminates_players`: run with scripted agents that always shove/call; tournament ends with exactly 1 winner
- `test_chip_conservation`: sum of stacks stays constant across hands
- `test_button_rotation`: button seat rotates among active seats

Pass criteria:
- tournament ends deterministically (seeded)
- produces `TOURNAMENT_END` summary with finish order

### M3 - Authoritative Observation + Legal Action Extraction
Tests:
- `test_observation_has_only_infoset`: opponent hole cards never appear
- `test_legal_actions_match_engine`: every returned legal action is accepted by engine; illegal action is rejected
- `test_min_max_raise_consistency`: `minRaiseTo/maxRaiseTo` bounds are consistent with engine legal actions

Pass criteria:
- observation schema stable and validated

### M4 - Trace + Summary Storage (Immutable, Content-Addressed)
Tests:
- `test_trace_is_append_only`: runner cannot rewrite earlier lines after writing later lines
- `test_trace_hash_stable`: stable run fingerprint and trace hash for golden seed
- `test_summary_matches_trace`: recompute summary from trace equals stored summary

Pass criteria:
- traces + summaries saved under deterministic paths keyed by `tournament_id` + `run_fingerprint`

### M5 - Agent Protocol + Dummy Agents
Tests:
- `test_agent_rpc_contract`: init/observe/decide/shutdown works
- `test_invalid_action_retry_then_fold`: invalid action triggers retry once then forced fold/check
- `test_timeout_forces_action`: timeout triggers forced fold/check

Pass criteria:
- tournaments can run with 6 dummy agents via adapter

### M6 - OpenClaw Lite Adapter (Sandboxed)
Tests:
- `test_openclaw_lite_adapter_boots`: can start agent from a minimal setup bundle
- `test_openclaw_lite_tool_call_act`: agent can emit `poker.act` tool call
- `test_no_outbound_network`: attempts to fetch external URL fail and are logged as violations

Pass criteria:
- OpenClaw Lite participates in at least 1 full tournament deterministically in regression mode (with deterministic model or completion cache)

### M7 - Setup Upload + Locking (Operator API)
Tests:
- `test_upload_returns_setup_id`: uploading same bundle yields same `setup_id`
- `test_rejects_disallowed_fields`: secrets/keys/outbound URLs rejected
- `test_setup_bundle_is_immutable`: cannot overwrite existing `setup_id`

Pass criteria:
- operator stores setup bundles by content hash and returns `setup_id`

### M8 - Tournament Batch Runner (`num_tournaments` parameter)
Tests:
- `test_batch_runs_exact_count`: runs exactly N tournaments and persists N summaries
- `test_batch_is_reproducible`: with same seeds/specs produces identical set of tournament ids + hashes

Pass criteria:
- batch completes within configured budgets; failures are classified and reported

### M9 - Leaderboard Computation + Snapshotting
Tests:
- `test_leaderboard_snapshot_hash`: snapshot id changes if any tournament/scorer changes
- `test_rating_monotonicity_smoke`: obvious strong scripted agent ranks above always-fold baseline over enough tournaments
- `test_ci_reporting`: bootstrap CIs are computed and included

Pass criteria:
- leaderboard endpoint returns rating + metrics + CI for all setups

### M10 - Replay API (Deterministic Playback)
Tests:
- `test_replay_reconstructs_public_state`: replay produces same public states as original trace
- `test_replay_matches_outcome`: finish order identical

Pass criteria:
- operator can serve replay data for any tournament id

### M11 - Red Team Suite (Season 0)
Tests:
- `test_prompt_injection_in_setup_docs_ignored`: adversarial text in setup bundle does not grant tools/permissions
- `test_tool_output_poisoning`: malformed tool result does not crash runner; agent penalties applied
- `test_collusion_side_channel_disabled`: opponent latency not present in observations

Pass criteria:
- safety violations are surfaced separately and gate composite scoring

---

## 11) Open Questions (Must Be Resolved in M1)

1. Exact OpenSpiel game string/parameters for 6-max NLHE with side pots and NL raises, and how to set tournament stacks/blinds.
2. Whether OpenSpiel hand implementation supports variable per-player stacks directly, or whether we implement a thin OpenSpiel game wrapper for tournament semantics.

Resolution rule:
- do not proceed beyond M1 until we have a passing golden determinism test and a locked, documented game configuration.

