import json
from src.auth import _running_in_cloud, _load_credentials_from_env

def test_not_running_in_cloud_by_default(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)

    assert not _running_in_cloud()

def test_running_in_cloud_when_k_service_present(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "job-tracker-pipeline")

    assert _running_in_cloud()

def test_loads_credentials_from_env_var(monkeypatch):
    token_info = {
        "token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "client_id": "fake-client-id",
        "client_secret": "fake-client-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
        ],
    }
    monkeypatch.setenv("GMAIL_OAUTH_TOKEN", json.dumps(token_info))

    creds = _load_credentials_from_env()

    assert creds.refresh_token == "fake-refresh-token"
    assert creds.client_id == "fake-client-id"
