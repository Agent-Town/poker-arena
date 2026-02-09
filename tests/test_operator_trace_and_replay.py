from fastapi.testclient import TestClient

from poker_arena.operator.app import create_app


def _seed_one_tournament(c: TestClient):
    exp = c.post("/v1/experiences", json={"name": "poker-nlhe-6max-s0", "bundle": {"skill.md": "ok"}, "engine": {}})
    assert exp.status_code == 200
    experience_id = exp.json()["experienceId"]

    setup_ids = []
    for i in range(6):
        resp = c.post(
            "/v1/setups",
            json={"framework": "openclaw-lite", "config": {"policy": "always_all_in" if i == 0 else "random"}},
        )
        assert resp.status_code == 200
        setup_ids.append(resp.json()["setupId"])

    batch = c.post(
        "/v1/batches",
        json={"experienceId": experience_id, "setupIds": setup_ids, "numTournaments": 1, "seedBase": 1234},
    )
    assert batch.status_code == 200
    batch_id = batch.json()["batchId"]
    tournament_id = batch.json()["tournamentIds"][0]
    return experience_id, batch_id, tournament_id


def test_operator_trace_summary_and_replay_endpoints(tmp_path) -> None:
    app = create_app(data_dir=str(tmp_path))
    c = TestClient(app)
    experience_id, batch_id, tournament_id = _seed_one_tournament(c)

    tr = c.get(f"/v1/tournaments/{tournament_id}/trace")
    assert tr.status_code == 200
    assert "RUN_START" in tr.text

    summ = c.get(f"/v1/tournaments/{tournament_id}/summary")
    assert summ.status_code == 200
    data = summ.json()
    assert data["tournamentId"] == tournament_id

    rep = c.post(f"/v1/tournaments/{tournament_id}/replay/verify")
    assert rep.status_code == 200
    payload = rep.json()
    assert payload["tournamentId"] == tournament_id
    assert payload["hands"] > 0
    assert len(payload["finishOrder"]) == 6

    # Leaderboard snapshot can be retrieved by id.
    lb = c.post("/v1/leaderboards/compute", json={"experienceId": experience_id, "batchId": batch_id, "bootstrapSamples": 50})
    assert lb.status_code == 200
    snapshot_id = lb.json()["snapshotId"]
    got = c.get(f"/v1/leaderboards/{snapshot_id}")
    assert got.status_code == 200
    assert got.json()["snapshotId"] == snapshot_id

