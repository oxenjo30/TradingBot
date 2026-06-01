"""Tests for GET /api/update/check endpoint."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test.db")
    with patch("server.engine.start"), patch("server.engine.shutdown"):
        from server.main import app
        with TestClient(app, raise_server_exceptions=True) as tc:
            yield tc


def _mock_github_response(tag_name, body, html_url):
    """Build a mock httpx response for the GitHub releases API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": tag_name,
        "body": body,
        "html_url": html_url,
    }
    return mock_resp


def test_check_up_to_date(client, monkeypatch):
    """Returns up_to_date=True when installed version matches latest tag."""
    import server.version as ver
    monkeypatch.setattr(ver, "INSTALLED_VERSION", "v1.0.0")
    mock_resp = _mock_github_response("v1.0.0", "Some notes", "https://github.com/x/y/releases/tag/v1.0.0")
    with patch("httpx.get", return_value=mock_resp):
        r = client.get("/api/update/check")
    assert r.status_code == 200
    data = r.json()
    assert data["installed"] == "v1.0.0"
    assert data["latest"] == "v1.0.0"
    assert data["up_to_date"] is True
    assert data["release_notes"] == "Some notes"
    assert data["release_url"] == "https://github.com/x/y/releases/tag/v1.0.0"


def test_check_update_available(client, monkeypatch):
    """Returns up_to_date=False when installed version differs from latest tag."""
    import server.version as ver
    monkeypatch.setattr(ver, "INSTALLED_VERSION", "v1.0.0")
    mock_resp = _mock_github_response("v1.2.0", "New stuff", "https://github.com/x/y/releases/tag/v1.2.0")
    with patch("httpx.get", return_value=mock_resp):
        r = client.get("/api/update/check")
    assert r.status_code == 200
    data = r.json()
    assert data["up_to_date"] is False
    assert data["latest"] == "v1.2.0"


def test_check_release_notes_trimmed(client, monkeypatch):
    """Release notes body is trimmed to 1000 chars."""
    import server.version as ver
    monkeypatch.setattr(ver, "INSTALLED_VERSION", "v1.0.0")
    long_body = "x" * 2000
    mock_resp = _mock_github_response("v1.2.0", long_body, "https://github.com/x/y/releases/tag/v1.2.0")
    with patch("httpx.get", return_value=mock_resp):
        r = client.get("/api/update/check")
    assert len(r.json()["release_notes"]) == 1000


def test_check_no_body_returns_empty_string(client, monkeypatch):
    """GitHub response with no body field returns release_notes=''."""
    import server.version as ver
    monkeypatch.setattr(ver, "INSTALLED_VERSION", "v1.0.0")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"tag_name": "v1.2.0", "html_url": "https://github.com/x/y/releases/tag/v1.2.0"}
    with patch("httpx.get", return_value=mock_resp):
        r = client.get("/api/update/check")
    assert r.json()["release_notes"] == ""


def test_check_github_unreachable_returns_502(client):
    """Network error from GitHub returns 502."""
    import httpx
    with patch("httpx.get", side_effect=httpx.RequestError("timeout")):
        r = client.get("/api/update/check")
    assert r.status_code == 502
    assert "GitHub" in r.json()["detail"]


def test_check_github_non_200_returns_502(client):
    """Non-200 response from GitHub returns 502."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("httpx.get", return_value=mock_resp):
        r = client.get("/api/update/check")
    assert r.status_code == 502
    assert "GitHub" in r.json()["detail"]


def test_check_release_url_validated(client, monkeypatch):
    """release_url with non-github.com prefix is replaced with the fallback API URL."""
    import server.version as ver
    monkeypatch.setattr(ver, "INSTALLED_VERSION", "v1.0.0")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v1.2.0",
        "body": "Notes",
        "html_url": "javascript:alert(1)",
    }
    with patch("httpx.get", return_value=mock_resp):
        r = client.get("/api/update/check")
    assert r.status_code == 200
    assert r.json()["release_url"].startswith("https://")
    assert "github.com" in r.json()["release_url"]


def test_check_requires_auth(tmp_path, monkeypatch):
    """GET /api/update/check returns 401 when setup is complete but no session cookie."""
    import server.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "auth_test.db")
    with patch("server.auth.password_is_set", return_value=True), \
         patch("server.auth.setup_complete", return_value=True):
        with patch("server.engine.start"), patch("server.engine.shutdown"):
            from server.main import app
            with TestClient(app, raise_server_exceptions=True) as tc:
                r = tc.get("/api/update/check")
    assert r.status_code == 401, (
        f"Expected 401 for unauthenticated update check, got {r.status_code}"
    )
