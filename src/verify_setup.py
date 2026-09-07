import os
from dotenv import load_dotenv
from googleapiclient.discovery import build
from src.auth import get_credentials

def list_recent_gmail_subjects(creds, count: int = 5) -> list[str]:
    service = build("gmail", "v1", credentials=creds)
    response = service.users().messages().list(userId="me", maxResults=count).execute()
    message_ids = [m["id"] for m in response.get("messages", [])]

    subjects = []
    for message_id in message_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata", metadataHeaders=["Subject"])
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
        subjects.append(subject)

    return subjects

def read_sheet_header_row(creds, spreadsheet_id: str) -> list[str]:
    service = build("sheets", "v4", credentials=creds)
    result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="A1:Z1").execute()

    return result.get("values", [[]])[0]

def main() -> None:
    load_dotenv()
    creds = get_credentials()

    print("Fetching 5 most recent Gmail subjects...")
    for subject in list_recent_gmail_subjects(creds):
        print(f"  - {subject}")

    spreadsheet_id = os.environ.get("TRACKER_SHEET_ID")
    if not spreadsheet_id:
        print("\nTRACKER_SHEET_ID not set in .env — skipping Sheets check.")
        return

    print(f"\nReading header row from spreadsheet {spreadsheet_id}...")
    header = read_sheet_header_row(creds, spreadsheet_id)
    print(f"  Header row: {header}")

if __name__ == "__main__":
    main()
