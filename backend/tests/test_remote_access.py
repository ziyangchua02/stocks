"""The backend is local-only by default; API_TOKEN and ALLOWED_ORIGINS open it up."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Environment


def build(tmp_path, providers, config, **extra):
    env = Environment(
        _env_file=None,
        database_path=tmp_path / "remote.sqlite3",
        finnhub_api_key="test-key",
        gemini_api_key="unused-test-key",
        **extra,
    )
    return create_app(env, config, providers)


@pytest.fixture
def token_client(tmp_path, config, providers):
    app = build(tmp_path, providers, config, api_token="s3cret", allowed_origins="https://app.example")
    with TestClient(app) as client:
        yield client


def test_api_rejects_requests_without_the_token(token_client):
    response = token_client.get("/api/health")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid API token"


def test_api_accepts_the_token(token_client):
    response = token_client.get("/api/health", headers={"X-API-Token": "s3cret"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_wrong_token_is_rejected(token_client):
    response = token_client.get("/api/health", headers={"X-API-Token": "wrong"})
    assert response.status_code == 401


def test_root_stays_open_as_a_liveness_check(token_client):
    assert token_client.get("/").status_code == 200


def test_configured_origin_may_mutate(token_client):
    response = token_client.post(
        "/api/alerts/acknowledge",
        headers={"X-API-Token": "s3cret", "Origin": "https://app.example"},
    )
    assert response.status_code != 403


def test_unknown_origin_still_cannot_mutate(token_client):
    response = token_client.post(
        "/api/alerts/acknowledge",
        headers={"X-API-Token": "s3cret", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_no_token_configured_leaves_the_api_open(tmp_path, config, providers):
    app = build(tmp_path, providers, config)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
