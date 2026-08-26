from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def test_generate_reconcile_flow(tmp_path, monkeypatch):
    monkeypatch.chdir("/Users/sritarunlakkaraju/Desktop/rzpay")
    r = client.post("/generate", json={"seed": 7, "n_orders": 40})
    assert r.status_code == 200
    body = r.json()
    run_id = body["run_id"]
    assert body["counts"]["orders"] == 40

    r2 = client.post(f"/reconcile/{run_id}")
    assert r2.status_code == 200
    summary = r2.json()["summary"]
    assert summary["false_match_count"] == 0

    r3 = client.get(f"/runs/{run_id}/metrics")
    assert r3.status_code == 200
    assert "auto_match_rate" in r3.json()

    r4 = client.get(f"/runs/{run_id}/matches", params={"page": 1})
    assert r4.status_code == 200
    assert r4.json()["total"] > 0

    r5 = client.get(f"/runs/{run_id}/exceptions")
    assert r5.status_code == 200
    if r5.json()["items"]:
        exc_id = r5.json()["items"][0]["exception_id"]
        r6 = client.get(f"/runs/{run_id}/exceptions/{exc_id}")
        assert r6.status_code == 200
        assert "source_rows" in r6.json()

        r7 = client.post(f"/runs/{run_id}/explain/{exc_id}")
        assert r7.status_code == 200
        assert r7.json()["ai"]["explanation"]

    r8 = client.get(f"/runs/{run_id}/export.csv")
    assert r8.status_code == 200
    assert r8.headers["content-type"].startswith("text/csv")

    import shutil

    shutil.rmtree(f"runs/{run_id}", ignore_errors=True)


def test_unknown_run_404():
    r = client.get("/runs/doesnotexist/metrics")
    assert r.status_code == 404


def test_metrics_before_reconcile_409(monkeypatch):
    monkeypatch.chdir("/Users/sritarunlakkaraju/Desktop/rzpay")
    r = client.post("/generate", json={"seed": 8, "n_orders": 20})
    run_id = r.json()["run_id"]
    r2 = client.get(f"/runs/{run_id}/metrics")
    assert r2.status_code == 409

    import shutil

    shutil.rmtree(f"runs/{run_id}", ignore_errors=True)
