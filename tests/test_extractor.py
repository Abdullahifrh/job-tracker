import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.extractor import extract_application, needs_review
from src.gmail_client import parse_message

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return parse_message(json.loads((FIXTURES_DIR / name).read_text()))


SAMPLE_EMAILS = {
    "greenhouse_applied": {
        "message_id": "s01", "is_outbound": False, "is_auto_reply": False,
        "from": "no-reply@greenhouse.io",
        "subject": "Your application to Northwind Robotics",
        "date": "Mon, 1 Sep 2026 10:00:00 +0200",
        "body_text": (
            "Thanks for applying to the Machine Learning Engineer role at "
            "Northwind Robotics in Amsterdam. We'll review your application shortly."
        ),
    },
    "lever_oa_invite": {
        "message_id": "s02", "is_outbound": False, "is_auto_reply": False,
        "from": "jobs@bluepeak.lever.co",
        "subject": "Next step: online assessment for Data Engineer",
        "date": "Tue, 2 Sep 2026 09:00:00 +0200",
        "body_text": (
            "Congrats on making it to the next step. Please complete the "
            "attached online assessment for the Data Engineer role at Bluepeak "
            "Systems within 5 days."
        ),
    },
    "workday_interview": {
        "message_id": "s03", "is_outbound": False, "is_auto_reply": False,
        "from": "talentacquisition@myworkday.com",
        "subject": "Interview scheduled - AI Engineer at Meridian Health",
        "date": "Wed, 3 Sep 2026 11:00:00 +0200",
        "body_text": (
            "We're pleased to invite you to interview for the AI Engineer "
            "position at Meridian Health on September 10th."
        ),
    },
    "post_interview_thanks": {
        "message_id": "s08", "is_outbound": False, "is_auto_reply": False,
        "from": "talentacquisition@myworkday.com",
        "subject": "Thank you for interviewing - AI Engineer",
        "date": "Thu, 11 Sep 2026 15:00:00 +0200",
        "body_text": (
            "Thank you for taking the time to interview with us yesterday for "
            "the AI Engineer position at Meridian Health. We'll be in touch soon."
        ),
    },
    "linkedin_cold_outreach": {
        "message_id": "s04", "is_outbound": False, "is_auto_reply": False,
        "from": "messaging-digest@linkedin.com",
        "subject": "A recruiter wants to connect",
        "date": "Thu, 4 Sep 2026 08:00:00 +0200",
        "body_text": (
            "Hi, I came across your profile and think you'd be a great fit "
            "for a few roles we're hiring for. Let me know if you're open to "
            "a chat."
        ),
    },
    "workday_rejected": {
        "message_id": "s05", "is_outbound": False, "is_auto_reply": False,
        "from": "talentacquisition@myworkday.com",
        "subject": "Update on your application - Backend Engineer",
        "date": "Fri, 5 Sep 2026 14:00:00 +0200",
        "body_text": (
            "Thank you for your interest in the Backend Engineer role at "
            "Solace Dynamics. Unfortunately, we have decided to move forward "
            "with other candidates."
        ),
    },
    "recruiter_offer": {
        "message_id": "s06", "is_outbound": False, "is_auto_reply": False,
        "from": "hiring.manager@fernbridge.ai",
        "subject": "Offer letter - AI Engineer",
        "date": "Sat, 6 Sep 2026 09:00:00 +0200",
        "body_text": (
            "We're excited to offer you the AI Engineer position at "
            "Fernbridge AI, based in Rotterdam, with a salary of EUR 62,000."
        ),
    },
    "ambiguous_newsletter": {
        "message_id": "s07", "is_outbound": False, "is_auto_reply": False,
        "from": "news@techweekly.example.com",
        "subject": "5 companies hiring AI engineers this week",
        "date": "Sun, 7 Sep 2026 09:00:00 +0200",
        "body_text": (
            "This week's roundup of companies actively hiring AI engineers "
            "across Europe, including a few based in the Netherlands."
        ),
    },
    "open_application_sent": {
        "message_id": "s09", "is_outbound": True, "is_auto_reply": False,
        "from": "you@example.com",
        "subject": "Open application - Data & AI Engineer",
        "date": "Fri, 12 Sep 2026 10:00:00 +0200",
        "body_text": (
            "Dear hiring team, I am interested in opportunities at your "
            "company and have attached my resume for consideration."
        ),
    },
}

MOCKED_RESPONSES = {
    "greenhouse_applied": {
        "company": "Northwind Robotics", "role": "Machine Learning Engineer",
        "status": "applied", "event_date": "2026-09-01", "location": "Amsterdam",
        "salary": None, "confidence": 0.95,
    },
    "lever_oa_invite": {
        "company": "Bluepeak Systems", "role": "Data Engineer",
        "status": "interview_scheduled", "event_date": "2026-09-02", "location": None,
        "salary": None, "confidence": 0.9,
    },
    "workday_interview": {
        "company": "Meridian Health", "role": "AI Engineer",
        "status": "interview_scheduled", "event_date": "2026-09-10", "location": None,
        "salary": None, "confidence": 0.92,
    },
    "post_interview_thanks": {
        "company": "Meridian Health", "role": "AI Engineer",
        "status": "interviewed", "event_date": "2026-09-10", "location": None,
        "salary": None, "confidence": 0.88,
    },
    "linkedin_cold_outreach": {
        "company": "Unknown", "role": "Unknown",
        "status": "other", "event_date": None, "location": None,
        "salary": None, "confidence": 0.2,
    },
    "workday_rejected": {
        "company": "Solace Dynamics", "role": "Backend Engineer",
        "status": "rejected", "event_date": "2026-09-05", "location": None,
        "salary": None, "confidence": 0.93,
    },
    "recruiter_offer": {
        "company": "Fernbridge AI", "role": "AI Engineer",
        "status": "offer", "event_date": None, "location": "Rotterdam",
        "salary": "EUR 62,000", "confidence": 0.96,
    },
    "ambiguous_newsletter": {
        "company": "Unknown", "role": "Unknown",
        "status": "other", "event_date": None, "location": None,
        "salary": None, "confidence": 0.3,
    },
    "open_application_sent": {
        "company": "Unknown", "role": "Unknown",
        "status": "applied", "event_date": "2026-09-12", "location": None,
        "salary": None, "confidence": 0.7,
    },
    "plain_match": {
        "company": "Acme Corp", "role": "Data Engineer",
        "status": "applied", "event_date": None, "location": None,
        "salary": None, "confidence": 0.9,
    },
    "html_match": {
        "company": "Globex", "role": "Backend Engineer",
        "status": "interview_scheduled", "event_date": None, "location": None,
        "salary": None, "confidence": 0.91,
    },
    "dutch_match": {
        "company": "Axians", "role": "Data & AI Engineer",
        "status": "applied", "event_date": None, "location": None,
        "salary": None, "confidence": 0.9,
    },
}

FIXTURE_EMAILS = {
    "plain_match": load_fixture("fixture_plain_match.json"),
    "html_match": load_fixture("fixture_html_match.json"),
    "dutch_match": load_fixture("fixture_dutch_match.json"),
}

ALL_EMAILS = {**SAMPLE_EMAILS, **FIXTURE_EMAILS}


@pytest.fixture(autouse=True)
def gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


@pytest.mark.parametrize("name", ALL_EMAILS.keys())
def test_extraction_matches_expected_status(name):
    with patch("src.extractor._call_gemini", return_value=MOCKED_RESPONSES[name]):
        result = extract_application(ALL_EMAILS[name])

    assert result.status == MOCKED_RESPONSES[name]["status"]
    assert result.company == MOCKED_RESPONSES[name]["company"]


def test_all_real_statuses_are_covered():
    statuses = {r["status"] for r in MOCKED_RESPONSES.values()}
    expected = {"applied", "interview_scheduled", "interviewed", "offer", "rejected"}
    assert expected <= statuses


def test_offer_carries_location_and_salary():
    with patch("src.extractor._call_gemini", return_value=MOCKED_RESPONSES["recruiter_offer"]):
        result = extract_application(SAMPLE_EMAILS["recruiter_offer"])

    assert result.location == "Rotterdam"
    assert result.salary == "EUR 62,000"


def test_non_offer_status_has_no_salary():
    with patch("src.extractor._call_gemini", return_value=MOCKED_RESPONSES["greenhouse_applied"]):
        result = extract_application(SAMPLE_EMAILS["greenhouse_applied"])

    assert result.salary is None


def test_low_confidence_flagged_for_review():
    with patch("src.extractor._call_gemini", return_value=MOCKED_RESPONSES["linkedin_cold_outreach"]):
        result = extract_application(SAMPLE_EMAILS["linkedin_cold_outreach"])

    assert needs_review(result)


def test_high_confidence_real_update_not_flagged():
    with patch("src.extractor._call_gemini", return_value=MOCKED_RESPONSES["workday_interview"]):
        result = extract_application(SAMPLE_EMAILS["workday_interview"])

    assert not needs_review(result)
