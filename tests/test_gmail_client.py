import json
from pathlib import Path
from src.gmail_client import is_likely_job_email, parse_message

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())

def test_parses_plain_text_message():
    raw = load_fixture("fixture_plain_match.json")
    parsed = parse_message(raw)

    assert parsed["message_id"] == "msg_plain_001"
    assert parsed["from"] == "recruiting@acmecorp.com"
    assert parsed["from_email"] == "recruiting@acmecorp.com"
    assert "Acme Corp" in parsed["subject"]
    assert "Data Engineer" in parsed["body_text"]

def test_from_email_strips_display_name_and_quoting():
    raw = {
        "id": "msg_display_name_001",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": '"Acme/Junior Engineer" <e+abc123.acme@ats-mailbox.com>'},
                {"name": "Subject", "value": "Thank you for applying"},
                {"name": "Date", "value": "Mon, 1 Sep 2026 09:00:00 +0200"},
            ],
            "body": {"data": ""},
        },
    }
    parsed = parse_message(raw)

    assert parsed["from"] == '"Acme/Junior Engineer" <e+abc123.acme@ats-mailbox.com>'
    assert parsed["from_email"] == "e+abc123.acme@ats-mailbox.com"

def test_parses_multipart_html_message_preferring_plain_text():
    raw = load_fixture("fixture_html_match.json")
    parsed = parse_message(raw)

    assert parsed["message_id"] == "msg_html_002"
    assert "<b>" not in parsed["body_text"]
    assert "interview" in parsed["body_text"].lower()

def test_plain_and_html_fixtures_match_keyword_filter():
    for fixture_name in ("fixture_plain_match.json", "fixture_html_match.json"):
        parsed = parse_message(load_fixture(fixture_name))
        assert is_likely_job_email(parsed["subject"], parsed["body_text"], parsed["from"])

def test_unrelated_email_does_not_match_keyword_filter():
    parsed = parse_message(load_fixture("fixture_no_match.json"))

    assert not is_likely_job_email(parsed["subject"], parsed["body_text"], parsed["from"])

def test_glassdoor_digest_excluded_by_sender_domain():
    parsed = parse_message(load_fixture("fixture_glassdoor_alert.json"))

    assert not is_likely_job_email(parsed["subject"], parsed["body_text"], parsed["from"])

def test_security_alert_does_not_match_keyword_filter():
    parsed = parse_message(load_fixture("fixture_security_alert.json"))

    assert not is_likely_job_email(parsed["subject"], parsed["body_text"], parsed["from"])

def test_dutch_application_confirmation_matches():
    parsed = parse_message(load_fixture("fixture_dutch_match.json"))

    assert is_likely_job_email(parsed["subject"], parsed["body_text"], parsed["from"])
