"""One-time Google Calendar login and the saved credentials."""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

BACKEND_DIR = Path(__file__).resolve().parents[2]
TOKEN_PATH = BACKEND_DIR / "secrets" / "calender-token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def client_path() -> Path:
    """Path to the OAuth client file saved from Google Cloud."""
    key_path = Path(os.environ["GOOGLE_CALENDAR_SA_FILE"])
    if not key_path.is_absolute():
        key_path = BACKEND_DIR / key_path
    return key_path


def login() -> None:
    """Open a browser once and store a refresh token for the calendar owner."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path()), SCOPES)
    creds = flow.run_local_server(port=8765, open_browser=True)
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())


def credentials() -> Credentials:
    """Load the saved calendar login, refreshing it when the access token expired."""
    if not TOKEN_PATH.is_file():
        raise RuntimeError(
            "Calendar login is missing. From the backend folder run: "
            ".venv/bin/python -m app.calender_login"
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
        return creds
    raise RuntimeError(
        "Calendar login expired. From the backend folder run: "
        ".venv/bin/python -m app.calender_login"
    )
