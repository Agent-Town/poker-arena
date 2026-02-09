from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from poker_arena.operator.models import (
    BatchCreateRequest,
    BatchCreateResponse,
    ExperienceUpsertRequest,
    ExperienceUpsertResponse,
    HealthResponse,
    LeaderboardGetResponse,
    LeaderboardComputeRequest,
    LeaderboardComputeResponse,
    ReplayVerifyResponse,
    SetupUpsertRequest,
    SetupUpsertResponse,
    TournamentGetResponse,
)
from poker_arena.operator.storage import OperatorStorage
from poker_arena.replay import replay_tournament_from_trace
from poker_arena.runner.runner import run_tournament
from poker_arena.leaderboard.leaderboard import compute_leaderboard_snapshot


def create_app(*, data_dir: str | None = None) -> FastAPI:
    app = FastAPI(title="Poker Arena Operator", version="0.1.0")
    storage = OperatorStorage.from_env(data_dir=data_dir)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(ok=True)

    @app.post("/v1/experiences", response_model=ExperienceUpsertResponse)
    def upsert_experience(req: ExperienceUpsertRequest) -> ExperienceUpsertResponse:
        exp = storage.put_experience(req)
        return ExperienceUpsertResponse(ok=True, experienceId=exp.experience_id, experienceHash=exp.experience_hash)

    @app.post("/v1/setups", response_model=SetupUpsertResponse)
    def upsert_setup(req: SetupUpsertRequest) -> SetupUpsertResponse:
        try:
            setup = storage.put_setup(req)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return SetupUpsertResponse(ok=True, setupId=setup.setup_id, setupHash=setup.setup_hash)

    @app.post("/v1/batches", response_model=BatchCreateResponse)
    def create_batch(req: BatchCreateRequest) -> BatchCreateResponse:
        exp = storage.get_experience(req.experienceId)
        if not exp:
            raise HTTPException(status_code=404, detail="EXPERIENCE_NOT_FOUND")

        for sid in req.setupIds:
            if not storage.get_setup(sid):
                raise HTTPException(status_code=404, detail=f"SETUP_NOT_FOUND:{sid}")

        batch = storage.create_batch(req)

        # MVP: run synchronously inside request (small N). Production: queue.
        tournament_ids: list[str] = []
        for i in range(req.numTournaments):
            seed = req.seedBase + i
            tournament_id = storage.create_tournament(
                batch_id=batch.batch_id,
                experience_id=req.experienceId,
                setup_ids=req.setupIds,
                seed=seed,
            )
            tournament_ids.append(tournament_id)
            run_tournament(storage=storage, tournament_id=tournament_id)

        storage.mark_batch_complete(batch.batch_id, tournament_ids=tournament_ids)
        return BatchCreateResponse(ok=True, batchId=batch.batch_id, tournamentIds=tournament_ids)

    @app.get("/v1/tournaments/{tournament_id}", response_model=TournamentGetResponse)
    def get_tournament(tournament_id: str) -> TournamentGetResponse:
        t = storage.get_tournament(tournament_id)
        if not t:
            raise HTTPException(status_code=404, detail="TOURNAMENT_NOT_FOUND")
        return TournamentGetResponse(ok=True, tournament=TournamentGetResponse.Tournament(**t))

    @app.get("/v1/tournaments/{tournament_id}/trace")
    def get_tournament_trace(tournament_id: str) -> FileResponse:
        t = storage.get_tournament(tournament_id)
        if not t:
            raise HTTPException(status_code=404, detail="TOURNAMENT_NOT_FOUND")
        p = t.get("tracePath")
        if not p:
            raise HTTPException(status_code=404, detail="TRACE_NOT_AVAILABLE")
        return FileResponse(path=p, media_type="application/jsonl")

    @app.get("/v1/tournaments/{tournament_id}/summary")
    def get_tournament_summary(tournament_id: str) -> FileResponse:
        t = storage.get_tournament(tournament_id)
        if not t:
            raise HTTPException(status_code=404, detail="TOURNAMENT_NOT_FOUND")
        p = t.get("summaryPath")
        if not p:
            raise HTTPException(status_code=404, detail="SUMMARY_NOT_AVAILABLE")
        return FileResponse(path=p, media_type="application/json")

    @app.post("/v1/tournaments/{tournament_id}/replay/verify", response_model=ReplayVerifyResponse)
    def verify_replay(tournament_id: str) -> ReplayVerifyResponse:
        t = storage.get_tournament(tournament_id)
        if not t:
            raise HTTPException(status_code=404, detail="TOURNAMENT_NOT_FOUND")
        p = t.get("tracePath")
        if not p:
            raise HTTPException(status_code=404, detail="TRACE_NOT_AVAILABLE")
        res = replay_tournament_from_trace(Path(p))
        return ReplayVerifyResponse(ok=True, tournamentId=tournament_id, hands=res.hands, finishOrder=res.finish_order)

    @app.post("/v1/leaderboards/compute", response_model=LeaderboardComputeResponse)
    def compute_leaderboard(req: LeaderboardComputeRequest) -> LeaderboardComputeResponse:
        exp = storage.get_experience(req.experienceId)
        if not exp:
            raise HTTPException(status_code=404, detail="EXPERIENCE_NOT_FOUND")
        tournaments = storage.list_tournaments(experience_id=req.experienceId, batch_id=req.batchId)
        if not tournaments:
            raise HTTPException(status_code=404, detail="NO_TOURNAMENTS")
        snapshot = compute_leaderboard_snapshot(
            experience_id=req.experienceId,
            scorer_version="scorer_v0",
            tournaments=tournaments,
            seed=req.bootstrapSeed,
            bootstrap_samples=req.bootstrapSamples,
        )
        storage.put_leaderboard_snapshot(snapshot)
        return LeaderboardComputeResponse(ok=True, snapshotId=snapshot.snapshot_id, leaderboard=snapshot.payload)

    @app.get("/v1/leaderboards/{snapshot_id}", response_model=LeaderboardGetResponse)
    def get_leaderboard_snapshot(snapshot_id: str) -> LeaderboardGetResponse:
        payload = storage.get_leaderboard_snapshot(snapshot_id)
        if not payload:
            raise HTTPException(status_code=404, detail="LEADERBOARD_NOT_FOUND")
        return LeaderboardGetResponse(ok=True, snapshotId=snapshot_id, leaderboard=payload)

    return app
