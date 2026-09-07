import logging
import re
from datetime import date
from googleapiclient.discovery import build
from src.extractor import needs_review
from src.retry import retry_with_backoff

logger = logging.getLogger(__name__)

TRACKER_SHEET_NAME = "Tracker"
PROCESSED_IDS_SHEET_NAME = "ProcessedIDs"

FIELD_ORDER = [
    "company", "job_title", "date_applied", "location", "salary",
    "status", "contact", "source", "last_updated", "notes",
]

HEADER_LABELS = [
    "Company", "Job Title", "Date Applied", "Location", "Salary",
    "Status", "Contact", "Source", "Last Updated", "Notes",
]

STATUS_RANK = {"applied": 1, "interview_scheduled": 2, "interviewed": 3, "offer": 4}

STATUS_DISPLAY = {
    "not_started": "Not Started",
    "applied": "Applied",
    "interview_scheduled": "Interview Scheduled",
    "interviewed": "Interviewed",
    "offer": "Offer",
    "rejected": "Rejected",
    "no_reply": "No Reply",
}

STATUS_FROM_DISPLAY = {v: k for k, v in STATUS_DISPLAY.items()}

STATUS_COLORS = {
    "Not Started": {"red": 1.0, "green": 1.0, "blue": 1.0},
    "Applied": {"red": 0.81, "green": 0.89, "blue": 0.95},
    "Interview Scheduled": {"red": 0.85, "green": 0.82, "blue": 0.93},
    "Interviewed": {"red": 0.82, "green": 0.88, "blue": 0.89},
    "Offer": {"red": 0.85, "green": 0.92, "blue": 0.83},
    "Rejected": {"red": 0.96, "green": 0.80, "blue": 0.80},
    "No Reply": {"red": 0.94, "green": 0.94, "blue": 0.94},
}

SOURCE_DISPLAY = {"applied_via_posting": "Applied via Posting", "open_application": "Open Application"}
STALE_APPLIED_DAYS = 21
_COMPANY_SUFFIXES = {"bv", "nv", "inc", "llc", "ltd", "corp", "corporation", "gmbh", "co", "company"}

def get_sheets_service(creds):
    return build("sheets", "v4", credentials=creds)

def normalize_company_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", name.lower().strip())
    tokens = [t for t in cleaned.split() if t not in _COMPANY_SUFFIXES]

    return " ".join(tokens)

def _role_similarity(a: str, b: str) -> float:
    tokens_a, tokens_b = set(a.lower().split()), set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0

    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

def _is_forward_progress(current_status: str, new_status: str) -> bool:
    if new_status == "rejected":
        return True
    if current_status in ("", "not_started"):
        return True
    if new_status not in STATUS_RANK:
        return False

    return STATUS_RANK.get(new_status, 0) >= STATUS_RANK.get(current_status, 0)

def _row_to_dict(row_index: int, values: list[str]) -> dict:
    padded = values + [""] * (len(FIELD_ORDER) - len(values))
    record = dict(zip(FIELD_ORDER, padded))
    record["status"] = STATUS_FROM_DISPLAY.get(record["status"], "not_started")
    record["row_index"] = row_index

    return record

def _dict_to_row(record: dict) -> list[str]:
    row = [record.get(field, "") for field in FIELD_ORDER]
    status_index = FIELD_ORDER.index("status")
    row[status_index] = STATUS_DISPLAY.get(record["status"], "Not Started")

    return row

def read_tracker_rows(service, spreadsheet_id: str) -> list[dict]:
    range_name = f"{TRACKER_SHEET_NAME}!A2:J"

    @retry_with_backoff()
    def _get() -> dict:
        return service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()

    rows = _get().get("values", [])

    return [_row_to_dict(i + 2, row) for i, row in enumerate(rows) if any(row)]

def append_tracker_row(service, spreadsheet_id: str, record: dict) -> None:
    body = {"values": [_dict_to_row(record)]}

    @retry_with_backoff()
    def _append() -> None:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{TRACKER_SHEET_NAME}!A:J",
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()

    _append()
    logger.info("Appended new row: %s | %s", record.get("company"), record.get("job_title"))

def update_tracker_row(service, spreadsheet_id: str, row_index: int, record: dict) -> None:
    body = {"values": [_dict_to_row(record)]}

    @retry_with_backoff()
    def _update() -> None:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{TRACKER_SHEET_NAME}!A{row_index}:J{row_index}",
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()

    _update()
    logger.info("Updated row %d: %s | %s -> %s", row_index, record.get("company"), record.get("job_title"), record.get("status"))

def load_processed_ids(service, spreadsheet_id: str) -> set[str]:
    range_name = f"{PROCESSED_IDS_SHEET_NAME}!A2:A"

    @retry_with_backoff()
    def _get() -> dict:
        return service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()

    return {row[0] for row in _get().get("values", []) if row}

def save_processed_ids(service, spreadsheet_id: str, new_ids: list[str]) -> None:
    if not new_ids:
        return

    today = date.today().isoformat()
    body = {"values": [[message_id, today] for message_id in new_ids]}

    @retry_with_backoff()
    def _append() -> None:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{PROCESSED_IDS_SHEET_NAME}!A:B",
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()

    _append()

def upsert_application(service, spreadsheet_id: str, parsed_email: dict, extraction) -> None:
    """Create or update one Tracker row from a single extracted email, never overwriting fields already filled in."""
    if extraction.status == "other":
        return

    rows = read_tracker_rows(service, spreadsheet_id)
    target_key = normalize_company_name(extraction.company)
    matches = [r for r in rows if normalize_company_name(r["company"]) == target_key]

    if len(matches) > 1:
        scored = sorted(matches, key=lambda r: _role_similarity(r["job_title"], extraction.role), reverse=True)
        if _role_similarity(scored[0]["job_title"], extraction.role) - _role_similarity(scored[1]["job_title"], extraction.role) < 0.15:
            logger.warning("Ambiguous match for '%s' — skipping automatic update, review manually.", extraction.company)
            return
        matches = [scored[0]]

    source = "open_application" if parsed_email["is_outbound"] else "applied_via_posting"
    note_suffix = " (auto-reply acknowledgment)" if parsed_email.get("is_auto_reply") else ""
    fallback_date = extraction.event_date.isoformat() if extraction.event_date else parsed_email["date"]

    if not matches:
        new_row = {
            "company": extraction.company,
            "job_title": extraction.role,
            "date_applied": fallback_date,
            "location": extraction.location or "",
            "salary": (extraction.salary or "") if extraction.status == "offer" else "",
            "status": extraction.status,
            "contact": parsed_email["from_email"],
            "source": SOURCE_DISPLAY[source],
            "last_updated": date.today().isoformat(),
            "notes": (("needs review" if needs_review(extraction) else "") + note_suffix).strip(),
        }
        append_tracker_row(service, spreadsheet_id, new_row)
        return

    existing = matches[0]
    if not _is_forward_progress(existing["status"], extraction.status):
        return

    existing["company"] = existing["company"] or extraction.company
    existing["job_title"] = existing["job_title"] or extraction.role
    existing["date_applied"] = existing["date_applied"] or fallback_date
    existing["location"] = existing["location"] or (extraction.location or "")
    # Salary is the one field allowed to overwrite a manually entered value —
    # a confirmed offer figure is always more accurate than an estimate.
    if extraction.status == "offer" and extraction.salary:
        existing["salary"] = extraction.salary
    existing["status"] = extraction.status
    # Contact intentionally always takes the latest sender, unlike every other
    # field here — a stale first-touch address is less useful than knowing who
    # most recently reached out. Falls back to the existing value only if the
    # new message's address somehow fails to parse, so a malformed header
    # can't silently blank out a previously known-good contact.
    existing["contact"] = parsed_email["from_email"] or existing["contact"]
    existing["last_updated"] = date.today().isoformat()
    if note_suffix:
        existing["notes"] = (existing["notes"] + note_suffix).strip()

    update_tracker_row(service, spreadsheet_id, existing["row_index"], existing)

def flag_stale_applications(service, spreadsheet_id: str, days: int = STALE_APPLIED_DAYS) -> int:
    """Flip rows stuck on 'applied' with no update for `days` to 'no_reply'. No inbound email ever signals this directly."""
    rows = read_tracker_rows(service, spreadsheet_id)
    today = date.today()
    flipped = 0

    for row in rows:
        if row["status"] != "applied" or not row["last_updated"]:
            continue

        last_updated = date.fromisoformat(row["last_updated"])
        if (today - last_updated).days >= days:
            row["status"] = "no_reply"
            update_tracker_row(service, spreadsheet_id, row["row_index"], row)
            flipped += 1

    return flipped

def _header_format_request(sheet_id: int) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                "startColumnIndex": 0, "endColumnIndex": len(HEADER_LABELS),
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    }

def _freeze_header_request(sheet_id: int) -> dict:
    return {
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }
    }

def _status_dropdown_request(sheet_id: int) -> dict:
    status_index = FIELD_ORDER.index("status")

    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id, "startRowIndex": 1,
                "startColumnIndex": status_index, "endColumnIndex": status_index + 1,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": label} for label in STATUS_DISPLAY.values()],
                },
                "showCustomUi": True,
                "strict": True,
            },
        }
    }

def _status_color_requests(sheet_id: int) -> list[dict]:
    status_index = FIELD_ORDER.index("status")
    requests = []

    for label, color in STATUS_COLORS.items():
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id, "startRowIndex": 1,
                        "startColumnIndex": status_index, "endColumnIndex": status_index + 1,
                    }],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": label}]},
                        "format": {"backgroundColor": color},
                    },
                },
                "index": 0,
            }
        })

    return requests

def build_tracker_sheet(service, spreadsheet_id: str, sheet_id: int) -> None:
    """One-time setup: header row, frozen row, colored status dropdown. Run once against an empty sheet."""
    requests = [
        {
            "updateCells": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "rows": [{"values": [{"userEnteredValue": {"stringValue": h}} for h in HEADER_LABELS]}],
                "fields": "userEnteredValue",
            }
        },
        _header_format_request(sheet_id),
        _freeze_header_request(sheet_id),
        _status_dropdown_request(sheet_id),
        *_status_color_requests(sheet_id),
    ]
    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
