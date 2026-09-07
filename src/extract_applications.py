from dotenv import load_dotenv
from googleapiclient.discovery import build
from src.auth import get_credentials
from src.extractor import extract_application, needs_review
from src.gmail_client import fetch_new_matching_emails

def main() -> None:
    load_dotenv()
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    emails = fetch_new_matching_emails(service, days=7)

    if not emails:
        print("No new matching emails found.")
        return

    for email in emails:
        extraction = extract_application(email)
        flag = " [needs review]" if needs_review(extraction) else ""
        print(
            f"{extraction.company} | {extraction.role} | {extraction.status}"
            f"{flag} (confidence {extraction.confidence:.2f})"
        )

if __name__ == "__main__":
    main()
