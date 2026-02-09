from fastapi.testclient import TestClient

from poker_arena.operator.app import create_app


def test_health_ok(tmp_path) -> None:
    app = create_app(data_dir=str(tmp_path))
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

