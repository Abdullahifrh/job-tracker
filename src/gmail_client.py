import base64
import html
import json
import logging
import re
from email.utils import parseaddr
from pathlib import Path

from src.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# Pre-filter only — the LLM extraction step makes the real judgment call.
# Phrases only, deliberately no bare words like "position" or "offer": those
# match job-board marketing content constantly. Covers English and Dutch,
# since real application traffic here is bilingual.
JOB_KEYWORDS = [
    "thank you for applying", "thanks for applying", "application received",
    "received your application", "application confirmation",
    "regarding your application", "status of your application",
    "update on your application", "your application status",
    "interview invitation", "invitation to interview", "schedule an interview",
    "interview request", "coding assessment", "online assessment",
    "take-home assignment", "next steps in your application",
    "unfortunately, we have decided", "not moving forward with your application",
    "we have decided to move forward with other candidates",
    "offer letter", "pleased to offer you",
    "bedankt voor je sollicitatie", "bedankt voor jouw sollicitatie",
    "ontvangstbevestiging sollicitatie", "sollicitatie ontvangen",
    "status van je sollicitatie", "update over je sollicitatie",
    "uitnodiging sollicitatiegesprek", "uitnodiging voor een gesprek",
    "vervolgstap in je sollicitatie", "assessment uitnodiging",
    "helaas moeten we je informeren", "afwijzing sollicitatie",
    "we gaan niet verder met je sollicitatie", "aanbod voor de functie",
]

# Phrases used in mail you send yourself — an open application or a
# speculative pitch, as opposed to a reply about one you already sent.
OUTBOUND_KEYWORDS = [
    "open application", "speculative application", "open sollicitatie",
    "i am interested in opportunities", "interested in joining your team",
    "i would like to apply", "please find attached my resume",
    "please find my resume attached", "please find attached my cv",
    "attached is my cv", "attached my resume",
    "graag stel ik mij voor", "open sollicitatie naar",
]

# Known mass job-board / alert-digest senders. A match here overrides any
# keyword match — these are discovery emails, never real application updates.
EXCLUDED_SENDER_DOMAINS = [
    "glassdoor.com", "indeed.com", "linkedin.com", "ziprecruiter.com",
]

# Subject-line markers that reliably indicate a subscription digest rather
# than a response to something you actually applied to.
EXCLUDED_SUBJECT_MARKERS = [
    "job alert", "vacatures voor u", "solliciteer nu", "nieuwe vacatures",
    "vacatures bij", "en nog", "voor u.",
]

PROCESSED_IDS_PATH = Path("processed_ids.json")

def build_search_query(days: int = 7) -> str:
    """Build a Gmail search string: recency, both keyword sets, noisy senders excluded server-side."""
    all_keywords = JOB_KEYWORDS + OUTBOUND_KEYWORDS
    keyword_clause = " OR ".join(f'"{k}"' for k in all_keywords)
    exclusion_clause = " ".join(f"-from:{domain}" for domain in EXCLUDED_SENDER_DOMAINS)

    return f"newer_than:{days}d ({keyword_clause}) {exclusion_clause}"

def search_recent_messages(service, days: int = 7) -> list[str]:
    query = build_search_query(days)

    @retry_with_backoff()
    def _list() -> dict:
        return service.users().messages().list(userId="me", q=query).execute()

    response = _list()
    ids = [m["id"] for m in response.get("messages", [])]
    logger.info("Gmail search returned %d candidate message(s)", len(ids))

    return ids

def _decode_part(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)

    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")

def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text)

    return html.unescape(re.sub(r"\s+", " ", no_tags)).strip()

def _extract_body(payload: dict) -> str:
    """Walk the MIME tree and return the best available plain-text body."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_part(payload["body"]["data"])

    html_fallback = None
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _decode_part(part["body"]["data"])
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html_fallback = _strip_html(_decode_part(part["body"]["data"]))
        if part.get("parts"):
            nested = _extract_body(part)
            if nested:
                return nested

    return html_fallback or ""

def parse_message(raw_message: dict) -> dict:
    payload = raw_message.get("payload", {})
    headers = payload.get("headers", [])

    def header(name: str) -> str:
        return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")

    label_ids = raw_message.get("labelIds", [])
    auto_submitted = header("Auto-Submitted").lower()
    raw_from = header("From")

    return {
        "message_id": raw_message["id"],
        "from": raw_from,
        "from_email": parseaddr(raw_from)[1],
        "subject": header("Subject"),
        "date": header("Date"),
        "body_text": _extract_body(payload),
        "is_outbound": "SENT" in label_ids,
        "is_auto_reply": "auto-replied" in auto_submitted,
    }

def _sender_domain(sender: str) -> str:
    match = re.search(r"@([\w.-]+)", sender)

    return match.group(1).lower() if match else ""

def is_likely_job_email(subject: str, body_text: str, sender: str = "", is_outbound: bool = False) -> bool:
    haystack = f"{subject} {body_text}".lower()

    if is_outbound:
        return any(keyword in haystack for keyword in OUTBOUND_KEYWORDS)

    if any(domain in _sender_domain(sender) for domain in EXCLUDED_SENDER_DOMAINS):
        return False
    if any(marker in subject.lower() for marker in EXCLUDED_SUBJECT_MARKERS):
        return False

    return any(keyword in haystack for keyword in JOB_KEYWORDS)

def fetch_message(service, message_id: str) -> dict:
    @retry_with_backoff()
    def _get() -> dict:
        return service.users().messages().get(userId="me", id=message_id, format="full").execute()

    return _get()

def load_processed_ids(path: Path = PROCESSED_IDS_PATH) -> set[str]:
    if not path.exists():
        return set()

    return set(json.loads(path.read_text()))

def save_processed_ids(ids: set[str], path: Path = PROCESSED_IDS_PATH) -> None:
    path.write_text(json.dumps(sorted(ids)))

def fetch_new_matching_emails(service, processed_ids: set[str], days: int = 7) -> tuple[list[dict], list[str]]:
    """Fetch and parse recent messages not already in processed_ids, returning matches plus every ID seen this run."""
    candidate_ids = search_recent_messages(service, days=days)
    seen_ids = [mid for mid in candidate_ids if mid not in processed_ids]

    results = []
    for message_id in seen_ids:
        raw = fetch_message(service, message_id)
        parsed = parse_message(raw)

        if is_likely_job_email(parsed["subject"], parsed["body_text"], parsed["from"], parsed["is_outbound"]):
            logger.info("Matched: %s | %s", parsed["from"], parsed["subject"])
            results.append(parsed)

    logger.info("Scanned %d new email(s), %d matched a known application pattern", len(seen_ids), len(results))

    return results, seen_ids
