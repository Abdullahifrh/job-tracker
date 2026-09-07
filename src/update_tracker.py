import logging
import os
from dotenv import load_dotenv
from googleapiclient.discovery import build
from src.auth import get_credentials
from src.extractor import extract_application
from src.gmail_client import fetch_new_matching_emails
from src.sheets_client import (
    flag_stale_applications,
    load_processed_ids,
    save_processed_ids,
    upsert_application,
)

logger = logging.getLogger(__name__)

def run_pipeline() -> dict:
    """Run one full fetch-extract-update cycle and return a summary dict."""
    load_dotenv()
    creds = get_credentials()
    gmail_service = build("gmail", "v1", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)
    spreadsheet_id = os.environ["TRACKER_SHEET_ID"]

    processed = load_processed_ids(sheets_service, spreadsheet_id)
    emails, seen_ids = fetch_new_matching_emails(gmail_service, processed, days=7)

    for email in emails:
        extraction = extract_application(email)
        upsert_application(sheets_service, spreadsheet_id, email, extraction)

    save_processed_ids(sheets_service, spreadsheet_id, seen_ids)
    flipped = flag_stale_applications(sheets_service, spreadsheet_id)

    return {
        "emails_scanned": len(seen_ids),
        "emails_matched": len(emails),
        "rows_flagged_no_reply": flipped,
    }

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
    summary = run_pipeline()
    logger.info("Run summary: %s", summary)
    print(f"Processed {summary['emails_scanned']} email(s), {summary['emails_matched']} matched a known application pattern.")
    if summary["rows_flagged_no_reply"]:
        print(f"{summary['rows_flagged_no_reply']} row(s) flagged as no reply.")

if __name__ == "__main__":
    main()
