"""Google Sheets, read and written through a service account.

The sheet is the fund's working surface, not just an export target. A partner opens
it, reads what the pipeline found, and writes their own status and notes into it.
So this module has to do two things that pull against each other: write new rows on
every run, and never touch what a human wrote.

The rule that resolves it: the pipeline only ever appends, and only ever to columns
it owns. A human's column is read, shown in the app, and written back on their
instruction alone. `sheet_row` on each candidate records what has already gone out
so a rerun does not duplicate.

Google's edit view cannot be put in an iframe, so the app reads the sheet through
this module and renders its own editable table rather than embedding one.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Where the service account JSON is looked for, in order.
CREDENTIAL_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"
CREDENTIAL_PATH = Path("config/service-account.json")
SHEET_ENV = "VC_ALPHA_SHEET_ID"


class SheetsUnavailable(RuntimeError):
    """No credentials, no sheet id, or the client library is not installed.

    Carries a message aimed at the person who has to fix it, because this is the
    single most likely thing to be missing on a fresh install.
    """


@dataclass(frozen=True, slots=True)
class SheetStatus:
    configured: bool
    detail: str
    sheet_id: str | None = None

    @property
    def url(self) -> str | None:
        if not self.sheet_id:
            return None
        return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit"


def _credentials_source() -> tuple[str, dict] | None:
    """The service account JSON, from the environment or from disk."""
    if raw := os.environ.get(CREDENTIAL_ENV):
        try:
            # The variable holds either the JSON itself, which is what a CI secret
            # looks like, or a path to it, which is what a laptop looks like.
            if raw.strip().startswith("{"):
                return "environment", json.loads(raw)
            path = Path(raw)
            if path.exists():
                return str(path), json.loads(path.read_text())
        except (ValueError, OSError) as e:
            log.warning("could not read %s: %s", CREDENTIAL_ENV, e)
    if CREDENTIAL_PATH.exists():
        try:
            return str(CREDENTIAL_PATH), json.loads(CREDENTIAL_PATH.read_text())
        except (ValueError, OSError) as e:
            log.warning("could not read %s: %s", CREDENTIAL_PATH, e)
    return None


def status() -> SheetStatus:
    """What is configured and what is not. Drives the app's Setup screen.

    Never raises. A missing credential is the expected state on a fresh install,
    not an error condition.
    """
    sheet_id = os.environ.get(SHEET_ENV)
    creds = _credentials_source()

    try:
        import google.oauth2.service_account  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
    except ImportError:
        return SheetStatus(
            False,
            "Client library missing. Install with: uv sync --extra sheets",
            sheet_id,
        )
    if not creds:
        return SheetStatus(
            False,
            f"No service account found. Put the JSON at {CREDENTIAL_PATH} or set "
            f"{CREDENTIAL_ENV}. Create one in Google Cloud, enable the Sheets API, "
            "then share the sheet with the service account's email address.",
            sheet_id,
        )
    if not sheet_id:
        return SheetStatus(
            False,
            f"Service account found at {creds[0]}, but {SHEET_ENV} is not set. It is "
            "the long id in the sheet's URL, between /d/ and /edit.",
            None,
        )
    return SheetStatus(True, f"Using the service account at {creds[0]}.", sheet_id)


class Sheet:
    """A thin wrapper over the Sheets API. Constructed only when configured."""

    def __init__(self, sheet_id: str | None = None, tab: str = "Sheet1"):
        st = status()
        if not st.configured:
            raise SheetsUnavailable(st.detail)

        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        _, info = _credentials_source()
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        self.sheet_id = sheet_id or st.sheet_id
        self.tab = tab
        self._api = build("sheets", "v4", credentials=creds).spreadsheets()

    def read(self, cell_range: str | None = None) -> list[list[str]]:
        """Every row, headers included. Short sheets, so no paging."""
        result = self._api.values().get(
            spreadsheetId=self.sheet_id, range=cell_range or self.tab
        ).execute()
        return result.get("values", [])

    def append(self, rows: list[list[str]]) -> int:
        """Add rows at the bottom. Never overwrites, which is the whole point."""
        if not rows:
            return 0
        self._api.values().append(
            spreadsheetId=self.sheet_id,
            range=self.tab,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        return len(rows)

    def update_cell(self, row: int, column: int, value: str) -> None:
        """Write one cell, 1-indexed, as the app's inline editor does.

        Deliberately one cell at a time: the app writes what a person just typed,
        and a wider range would risk clobbering a neighbouring edit made in the
        Google UI between our read and our write.
        """
        self._api.values().update(
            spreadsheetId=self.sheet_id,
            range=f"{self.tab}!{_a1(column)}{row}",
            valueInputOption="USER_ENTERED",
            body={"values": [[value]]},
        ).execute()

    def ensure_headers(self, headers: list[str]) -> None:
        """Write the header row if the sheet is empty. Never rewrites an existing one,
        because a fund may well have renamed a column to suit themselves."""
        if self.read(f"{self.tab}!1:1"):
            return
        self._api.values().update(
            spreadsheetId=self.sheet_id,
            range=f"{self.tab}!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()


def _a1(column: int) -> str:
    """1 -> A, 27 -> AA."""
    out = ""
    while column > 0:
        column, rem = divmod(column - 1, 26)
        out = chr(65 + rem) + out
    return out
