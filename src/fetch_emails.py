from dotenv import load_dotenv
from googleapiclient.discovery import build
from src.auth import get_credentials
from src.gmail_client import fetch_new_matching_emails, load_processed_ids, save_processed_ids

def main() -> None:
    load_dotenv()
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    processed = load_processed_ids()
    emails, seen_ids = fetch_new_matching_emails(service, processed, days=7)
    save_processed_ids(processed | set(seen_ids))

    if not emails:
        print("No new matching emails found.")
        return

    for email in emails:
        print("-" * 60)
        print(f"From:    {email['from']}")
        print(f"Subject: {email['subject']}")
        print(f"Date:    {email['date']}")
        print(f"Body:    {email['body_text'][:200]}...")

if __name__ == "__main__":
    main()
