import base64
from email.mime.text import MIMEText
from googleapiclient.discovery import build

def send_failure_alert(creds, error_summary: str) -> None:
    service = build("gmail", "v1", credentials=creds)
    own_address = service.users().getProfile(userId="me").execute()["emailAddress"]

    message = MIMEText(f"The job tracker pipeline failed with the following error:\n\n{error_summary}")
    message["to"] = own_address
    message["from"] = own_address
    message["subject"] = "Job tracker pipeline failed"

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
