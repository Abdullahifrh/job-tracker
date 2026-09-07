import json
import os
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Minimum scopes needed: read-only Gmail access, sending mail (for failure
# alerts only), and read/write on the tracker spreadsheet. Google issues a
# short-lived access token plus a long-lived refresh token limited to
# exactly these permissions.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]

CREDENTIALS_PATH = Path("credentials.json")
TOKEN_PATH = Path("token.json")
TOKEN_ENV_VAR = "GMAIL_OAUTH_TOKEN"


def _running_in_cloud() -> bool:
    return "K_SERVICE" in os.environ

def _load_credentials_from_env() -> Credentials:
    """Read the token JSON injected as a secret-backed environment variable at deploy time."""
    token_info = json.loads(os.environ[TOKEN_ENV_VAR])

    return Credentials.from_authorized_user_info(token_info, SCOPES)

def _load_credentials_from_disk() -> Credentials | None:
    if not TOKEN_PATH.exists():
        return None

    return Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

def get_credentials() -> Credentials:
    """Return valid OAuth2 credentials.

    Locally, the browser consent flow runs once and caches a refresh token
    in token.json. In the cloud, the same token content is read from a
    secret-backed environment variable instead, since no browser is available.
    """
    if _running_in_cloud():
        creds = _load_credentials_from_env()
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds

    creds = _load_credentials_from_disk()
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                "credentials.json not found. Download it from the GCP console "
                "OAuth Client ID (Desktop app) and place it in the project root."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())

    return creds
