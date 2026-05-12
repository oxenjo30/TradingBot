import os
os.environ.setdefault("TRADEBOT_LICENSE_SECRET", "test-secret-32-chars-seller-key!!")


def test_export_trades_returns_csv(client):
    r = client.get("/api/export/trades")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.strip().splitlines()
    # Header row must exist
    assert lines[0].startswith("timestamp,strategy,symbol,side")

def test_export_trades_limit(client):
    r = client.get("/api/export/trades?limit=5")
    assert r.status_code == 200

def test_export_positions_returns_csv(client):
    r = client.get("/api/export/positions")
    # May return 502 if no broker configured — that's acceptable in test env
    assert r.status_code in (200, 502)
    if r.status_code == 200:
        assert "text/csv" in r.headers["content-type"]
