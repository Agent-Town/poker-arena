from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool


class ExperienceUpsertRequest(BaseModel):
    # A content-addressed bundle (string files). In production, this would be a zip/tar upload.
    name: str = Field(..., min_length=1, max_length=200)
    bundle: dict[str, str] = Field(default_factory=dict)
    engine: dict[str, object] = Field(default_factory=dict)


class ExperienceUpsertResponse(BaseModel):
    ok: bool
    experienceId: str
    experienceHash: str


class SetupUpsertRequest(BaseModel):
    framework: str = Field(..., min_length=1, max_length=64)
    config: dict[str, object] = Field(default_factory=dict)
    bundle: dict[str, str] = Field(default_factory=dict)


class SetupUpsertResponse(BaseModel):
    ok: bool
    setupId: str
    setupHash: str


class BatchCreateRequest(BaseModel):
    experienceId: str
    setupIds: list[str] = Field(..., min_length=6, max_length=6)
    numTournaments: int = Field(..., ge=1, le=10_000)
    seedBase: int = Field(..., ge=0, le=2**31 - 1)


class BatchCreateResponse(BaseModel):
    ok: bool
    batchId: str
    tournamentIds: list[str]


class LeaderboardComputeRequest(BaseModel):
    experienceId: str
    batchId: str | None = None
    bootstrapSeed: int = 1
    bootstrapSamples: int = Field(default=200, ge=50, le=5_000)


class LeaderboardComputeResponse(BaseModel):
    ok: bool
    snapshotId: str
    leaderboard: dict[str, object]


class TournamentGetResponse(BaseModel):
    class Tournament(BaseModel):
        tournamentId: str
        status: str
        experienceId: str
        setupIds: list[str]
        seed: int
        runFingerprint: str | None = None
        tracePath: str | None = None
        summaryPath: str | None = None
        result: dict[str, object] | None = None

    ok: bool
    tournament: Tournament


class ReplayVerifyResponse(BaseModel):
    ok: bool
    tournamentId: str
    hands: int
    finishOrder: list[int]


class LeaderboardGetResponse(BaseModel):
    ok: bool
    snapshotId: str
    leaderboard: dict[str, object]
