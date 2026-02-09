from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from poker_arena.operator.models import BatchCreateRequest, ExperienceUpsertRequest, SetupUpsertRequest
from poker_arena.util.hashing import canonical_json_bytes, sha256_hex


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _random_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{os.urandom(4).hex()}"


@dataclass(frozen=True)
class StoredExperience:
    experience_id: str
    experience_hash: str
    name: str
    bundle: dict[str, str]
    engine: dict[str, Any]


@dataclass(frozen=True)
class StoredSetup:
    setup_id: str
    setup_hash: str
    framework: str
    config: dict[str, Any]
    bundle: dict[str, str]


@dataclass(frozen=True)
class StoredBatch:
    batch_id: str
    experience_id: str
    setup_ids: list[str]
    num_tournaments: int
    seed_base: int


class OperatorStorage:
    def __init__(self, *, root_dir: Path):
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root_dir / "operator.sqlite"
        self._init_db()

        (self.root_dir / "experiences").mkdir(exist_ok=True)
        (self.root_dir / "setups").mkdir(exist_ok=True)
        (self.root_dir / "runs").mkdir(exist_ok=True)
        (self.root_dir / "leaderboards").mkdir(exist_ok=True)

    @staticmethod
    def from_env(*, data_dir: str | None = None) -> "OperatorStorage":
        root = Path(data_dir or os.environ.get("POKER_ARENA_DATA_DIR") or "./data").resolve()
        return OperatorStorage(root_dir=root)

    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS experiences (
                  id TEXT PRIMARY KEY,
                  hash TEXT NOT NULL,
                  name TEXT NOT NULL,
                  data TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS setups (
                  id TEXT PRIMARY KEY,
                  hash TEXT NOT NULL,
                  framework TEXT NOT NULL,
                  data TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS batches (
                  id TEXT PRIMARY KEY,
                  experience_id TEXT NOT NULL,
                  setup_ids TEXT NOT NULL,
                  num_tournaments INTEGER NOT NULL,
                  seed_base INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  tournament_ids TEXT,
                  created_at TEXT NOT NULL
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS tournaments (
                  id TEXT PRIMARY KEY,
                  batch_id TEXT,
                  experience_id TEXT NOT NULL,
                  setup_ids TEXT NOT NULL,
                  seed INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  run_fingerprint TEXT,
                  trace_path TEXT,
                  summary_path TEXT,
                  result TEXT,
                  created_at TEXT NOT NULL
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS leaderboards (
                  id TEXT PRIMARY KEY,
                  experience_id TEXT NOT NULL,
                  data TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            con.commit()
        finally:
            con.close()

    # --- experiences ---
    def put_experience(self, req: ExperienceUpsertRequest) -> StoredExperience:
        # Canonicalize bundle: sort keys, normalize to strings.
        bundle = {str(k): str(v) for k, v in (req.bundle or {}).items()}
        engine = dict(req.engine or {})
        payload = {"name": req.name, "bundle": bundle, "engine": engine}
        h = sha256_hex(canonical_json_bytes(payload))
        exp_id = f"exp_{h[:16]}"

        exp_dir = self.root_dir / "experiences" / exp_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "bundle.json").write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")

        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "INSERT OR REPLACE INTO experiences(id, hash, name, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (exp_id, h, req.name, json.dumps(payload, sort_keys=True), _now_iso()),
            )
            con.commit()
        finally:
            con.close()

        return StoredExperience(experience_id=exp_id, experience_hash=h, name=req.name, bundle=bundle, engine=engine)

    def get_experience(self, experience_id: str) -> StoredExperience | None:
        con = sqlite3.connect(self.db_path)
        try:
            row = con.execute("SELECT hash, name, data FROM experiences WHERE id=?", (experience_id,)).fetchone()
        finally:
            con.close()
        if not row:
            return None
        h, name, data = row
        payload = json.loads(data)
        return StoredExperience(experience_id=experience_id, experience_hash=h, name=name, bundle=payload["bundle"], engine=payload["engine"])

    # --- setups ---
    def put_setup(self, req: SetupUpsertRequest) -> StoredSetup:
        framework = str(req.framework or "").strip()
        if not framework:
            raise ValueError("MISSING_FRAMEWORK")
        config = req.config or {}
        bundle = {str(k): str(v) for k, v in (req.bundle or {}).items()}

        _validate_setup_config(config)
        payload = {"framework": framework, "config": config, "bundle": bundle}
        h = sha256_hex(canonical_json_bytes(payload))
        setup_id = f"setup_{h[:16]}"

        setup_dir = self.root_dir / "setups" / setup_id
        setup_dir.mkdir(parents=True, exist_ok=True)
        (setup_dir / "bundle.json").write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )

        con = sqlite3.connect(self.db_path)
        try:
            # Immutable by hash: if exists, do not overwrite created_at etc.
            exists = con.execute("SELECT 1 FROM setups WHERE id=?", (setup_id,)).fetchone()
            if not exists:
                con.execute(
                    "INSERT INTO setups(id, hash, framework, data, created_at) VALUES (?, ?, ?, ?, ?)",
                    (setup_id, h, framework, json.dumps(payload, sort_keys=True), _now_iso()),
                )
                con.commit()
        finally:
            con.close()

        return StoredSetup(setup_id=setup_id, setup_hash=h, framework=framework, config=dict(config), bundle=bundle)

    def get_setup(self, setup_id: str) -> StoredSetup | None:
        con = sqlite3.connect(self.db_path)
        try:
            row = con.execute("SELECT hash, framework, data FROM setups WHERE id=?", (setup_id,)).fetchone()
        finally:
            con.close()
        if not row:
            return None
        h, framework, data = row
        payload = json.loads(data)
        return StoredSetup(setup_id=setup_id, setup_hash=h, framework=framework, config=payload["config"], bundle=payload["bundle"])

    # --- batches / tournaments ---
    def create_batch(self, req: BatchCreateRequest) -> StoredBatch:
        batch_id = _random_id("batch")
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO batches(id, experience_id, setup_ids, num_tournaments, seed_base, status, tournament_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    req.experienceId,
                    json.dumps(req.setupIds),
                    int(req.numTournaments),
                    int(req.seedBase),
                    "running",
                    None,
                    _now_iso(),
                ),
            )
            con.commit()
        finally:
            con.close()
        return StoredBatch(batch_id=batch_id, experience_id=req.experienceId, setup_ids=req.setupIds, num_tournaments=req.numTournaments, seed_base=req.seedBase)

    def mark_batch_complete(self, batch_id: str, *, tournament_ids: list[str]) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "UPDATE batches SET status=?, tournament_ids=? WHERE id=?",
                ("complete", json.dumps(tournament_ids), batch_id),
            )
            con.commit()
        finally:
            con.close()

    def create_tournament(self, *, batch_id: str | None, experience_id: str, setup_ids: list[str], seed: int) -> str:
        tournament_id = _random_id("t")
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO tournaments(id, batch_id, experience_id, setup_ids, seed, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tournament_id, batch_id, experience_id, json.dumps(setup_ids), int(seed), "pending", _now_iso()),
            )
            con.commit()
        finally:
            con.close()
        return tournament_id

    def get_tournament(self, tournament_id: str) -> dict[str, Any] | None:
        con = sqlite3.connect(self.db_path)
        try:
            row = con.execute(
                "SELECT id, status, experience_id, setup_ids, seed, run_fingerprint, trace_path, summary_path, result FROM tournaments WHERE id=?",
                (tournament_id,),
            ).fetchone()
        finally:
            con.close()
        if not row:
            return None
        (
            tid,
            status,
            experience_id,
            setup_ids,
            seed,
            run_fingerprint,
            trace_path,
            summary_path,
            result,
        ) = row
        return {
            "tournamentId": tid,
            "status": status,
            "experienceId": experience_id,
            "setupIds": json.loads(setup_ids),
            "seed": int(seed),
            "runFingerprint": run_fingerprint,
            "tracePath": trace_path,
            "summaryPath": summary_path,
            "result": json.loads(result) if result else None,
        }

    def list_tournaments(self, *, experience_id: str, batch_id: str | None = None) -> list[dict[str, Any]]:
        con = sqlite3.connect(self.db_path)
        try:
            if batch_id:
                rows = con.execute(
                    "SELECT id, experience_id, setup_ids, seed, result FROM tournaments WHERE experience_id=? AND batch_id=? AND status='complete' ORDER BY created_at ASC",
                    (experience_id, batch_id),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT id, experience_id, setup_ids, seed, result FROM tournaments WHERE experience_id=? AND status='complete' ORDER BY created_at ASC",
                    (experience_id,),
                ).fetchall()
        finally:
            con.close()
        out: list[dict[str, Any]] = []
        for tid, expid, setup_ids, seed, result in rows:
            out.append(
                {
                    "tournamentId": tid,
                    "experienceId": expid,
                    "setupIds": json.loads(setup_ids),
                    "seed": int(seed),
                    "result": json.loads(result) if result else None,
                }
            )
        return out

    def mark_tournament_running(self, tournament_id: str, *, run_fingerprint: str) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "UPDATE tournaments SET status='running', run_fingerprint=? WHERE id=?",
                (run_fingerprint, tournament_id),
            )
            con.commit()
        finally:
            con.close()

    def mark_tournament_complete(
        self,
        tournament_id: str,
        *,
        trace_path: str,
        summary_path: str,
        result: dict[str, Any],
    ) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "UPDATE tournaments SET status='complete', trace_path=?, summary_path=?, result=? WHERE id=?",
                (trace_path, summary_path, json.dumps(result, sort_keys=True), tournament_id),
            )
            con.commit()
        finally:
            con.close()

    # --- leaderboards ---
    def put_leaderboard_snapshot(self, snapshot: "LeaderboardSnapshot") -> None:
        # Stored on disk + referenced in sqlite for listing.
        p = self.root_dir / "leaderboards" / f"{snapshot.snapshot_id}.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot.payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        tmp.replace(p)
        os.chmod(p, 0o444)

        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "INSERT OR REPLACE INTO leaderboards(id, experience_id, data, created_at) VALUES (?, ?, ?, ?)",
                (snapshot.snapshot_id, snapshot.experience_id, json.dumps(snapshot.payload, sort_keys=True), _now_iso()),
            )
            con.commit()
        finally:
            con.close()

    # Helper for runner: where to write run artifacts
    def run_dir(self, tournament_id: str) -> Path:
        d = self.root_dir / "runs" / tournament_id
        d.mkdir(parents=True, exist_ok=True)
        return d


def _validate_setup_config(config: dict[str, Any]) -> None:
    # This is intentionally strict. Season policies can relax later.
    def walk(x: Any, path: str) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                key = str(k)
                low = key.lower()
                if low in {"apikey", "api_key", "secret", "privatekey", "private_key", "password"}:
                    raise ValueError(f"DISALLOWED_SECRET_FIELD:{path + '.' if path else ''}{key}")
                if "http" in low or "url" in low:
                    # URLs belong in operator config, not user setups.
                    raise ValueError(f"DISALLOWED_URL_FIELD:{path + '.' if path else ''}{key}")
                walk(v, path + "." + key if path else key)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
        else:
            return

    walk(config, "")


# Circular import-safe type alias (runtime import in app.py)
@dataclass(frozen=True)
class LeaderboardSnapshot:
    snapshot_id: str
    experience_id: str
    payload: dict[str, Any]

