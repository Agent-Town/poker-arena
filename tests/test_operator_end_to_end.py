from fastapi.testclient import TestClient

from poker_arena.operator.app import create_app


def test_setup_upload_is_content_addressed_and_validated(tmp_path) -> None:
    app = create_app(data_dir=str(tmp_path))
    c = TestClient(app)

    r1 = c.post("/v1/setups", json={"framework": "openclaw-lite", "config": {"policy": "always_fold"}})
    assert r1.status_code == 200
    setup_id = r1.json()["setupId"]

    r2 = c.post("/v1/setups", json={"framework": "openclaw-lite", "config": {"policy": "always_fold"}})
    assert r2.status_code == 200
    assert r2.json()["setupId"] == setup_id

    bad = c.post("/v1/setups", json={"framework": "openclaw-lite", "config": {"apiKey": "nope"}})
    assert bad.status_code == 400


def test_batch_run_and_leaderboard(tmp_path) -> None:
    app = create_app(data_dir=str(tmp_path))
    c = TestClient(app)

    exp = c.post("/v1/experiences", json={"name": "poker-nlhe-6max-s0", "bundle": {"skill.md": "ok"}, "engine": {}})
    assert exp.status_code == 200
    experience_id = exp.json()["experienceId"]

    setup_ids = []
    for i in range(6):
        resp = c.post("/v1/setups", json={"framework": "openclaw-lite", "config": {"policy": "always_all_in" if i == 0 else "random"}})
        assert resp.status_code == 200
        setup_ids.append(resp.json()["setupId"])

    batch = c.post("/v1/batches", json={"experienceId": experience_id, "setupIds": setup_ids, "numTournaments": 3, "seedBase": 100})
    assert batch.status_code == 200
    data = batch.json()
    assert len(data["tournamentIds"]) == 3

    # Leaderboard snapshot should be computable from the batch.
    lb = c.post("/v1/leaderboards/compute", json={"experienceId": experience_id, "batchId": data["batchId"], "bootstrapSamples": 50})
    assert lb.status_code == 200
    payload = lb.json()["leaderboard"]
    assert payload["experienceId"] == experience_id
    assert len(payload["rows"]) >= 1

