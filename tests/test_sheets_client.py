from datetime import date, timedelta
from unittest.mock import MagicMock
from src.extractor import ExtractedApplication
from src.sheets_client import (
    _is_forward_progress,
    _role_similarity,
    flag_stale_applications,
    normalize_company_name,
    upsert_application,
)

def _mock_sheets_service(existing_rows: list[list[str]]):
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {"values": existing_rows}

    return service, values

def _extraction(**overrides) -> ExtractedApplication:
    defaults = {
        "company": "Acme Corp", "role": "Data Engineer", "status": "applied",
        "event_date": None, "location": None, "salary": None, "confidence": 0.9,
    }
    defaults.update(overrides)

    return ExtractedApplication.model_validate(defaults)

def _parsed_email(**overrides) -> dict:
    defaults = {
        "message_id": "m1", "from": "recruiting@acmecorp.com", "from_email": "recruiting@acmecorp.com", "subject": "x",
        "date": "Mon, 1 Sep 2026 10:00:00 +0200", "body_text": "x",
        "is_outbound": False, "is_auto_reply": False,
    }
    defaults.update(overrides)

    return defaults

def test_normalize_company_name_strips_suffixes_and_case():
    assert normalize_company_name("Axians B.V.") == "axians"
    assert normalize_company_name("Acme Corp") == "acme"
    assert normalize_company_name("acme") == "acme"

def test_role_similarity_scores_overlap():
    assert _role_similarity("Data Engineer", "Data Engineer") == 1.0
    assert _role_similarity("Data Engineer", "Marketing Manager") == 0.0
    assert 0 < _role_similarity("Senior Data Engineer", "Data Engineer") < 1.0

def test_forward_progress_allows_normal_advancement():
    assert _is_forward_progress("applied", "interview_scheduled")
    assert not _is_forward_progress("interview_scheduled", "applied")

def test_rejected_always_allowed():
    assert _is_forward_progress("interview_scheduled", "rejected")
    assert _is_forward_progress("applied", "rejected")

def test_new_company_appends_a_row():
    service, values = _mock_sheets_service([])

    upsert_application(service, "sheet123", _parsed_email(), _extraction())

    values.append.assert_called_once()

def test_existing_company_updates_in_place_without_overwriting_filled_fields():
    existing = [["Acme Corp", "Data Engineer", "2026-08-01", "Tilburg", "", "Applied", "hr@acmecorp.com", "Applied via Posting", "2026-08-01", ""]]
    service, values = _mock_sheets_service(existing)

    extraction = _extraction(status="interview_scheduled", company="Acme Corp", role="Data Engineer")
    upsert_application(service, "sheet123", _parsed_email(), extraction)

    values.update.assert_called_once()
    updated_row = values.update.call_args.kwargs["body"]["values"][0]
    assert updated_row[3] == "Tilburg"
    assert updated_row[5] == "Interview Scheduled"

def test_manual_salary_estimate_gets_replaced_by_real_offer_figure():
    existing = [["Acme Corp", "Data Engineer", "2026-08-01", "Tilburg", "40K-50K", "Applied", "", "", "2026-08-01", ""]]
    service, values = _mock_sheets_service(existing)

    extraction = _extraction(status="offer", company="Acme Corp", role="Data Engineer", salary="EUR 55,000")
    upsert_application(service, "sheet123", _parsed_email(), extraction)

    values.update.assert_called_once()
    updated_row = values.update.call_args.kwargs["body"]["values"][0]
    assert updated_row[4] == "EUR 55,000"

def test_location_stays_protected_while_contact_and_salary_update():
    existing = [["Acme Corp", "Data Engineer", "2026-08-01", "Tilburg", "40K-50K", "Applied", "hr@acmecorp.com", "", "2026-08-01", ""]]
    service, values = _mock_sheets_service(existing)

    extraction = _extraction(status="offer", company="Acme Corp", role="Data Engineer", salary="EUR 55,000", location="Rotterdam")
    upsert_application(service, "sheet123", _parsed_email(), extraction)

    updated_row = values.update.call_args.kwargs["body"]["values"][0]
    assert updated_row[3] == "Tilburg"
    assert updated_row[6] == "recruiting@acmecorp.com"

def test_contact_always_updates_to_most_recent_sender():
    existing = [["Acme Corp", "Data Engineer", "2026-08-01", "Tilburg", "", "Applied", "old-ats-noreply@greenhouse-mail.io", "", "2026-08-01", ""]]
    service, values = _mock_sheets_service(existing)

    extraction = _extraction(status="interview_scheduled", company="Acme Corp", role="Data Engineer")
    upsert_application(service, "sheet123", _parsed_email(from_email="real.recruiter@acmecorp.com"), extraction)

    updated_row = values.update.call_args.kwargs["body"]["values"][0]
    assert updated_row[6] == "real.recruiter@acmecorp.com"

def test_contact_falls_back_to_existing_value_if_new_address_fails_to_parse():
    existing = [["Acme Corp", "Data Engineer", "2026-08-01", "Tilburg", "", "Applied", "known-good@acmecorp.com", "", "2026-08-01", ""]]
    service, values = _mock_sheets_service(existing)

    extraction = _extraction(status="interview_scheduled", company="Acme Corp", role="Data Engineer")
    upsert_application(service, "sheet123", _parsed_email(from_email=""), extraction)

    updated_row = values.update.call_args.kwargs["body"]["values"][0]
    assert updated_row[6] == "known-good@acmecorp.com"

def test_manual_row_not_overwritten_with_duplicate():
    existing = [["Serenity Healthcare", "Marketing Coordinator", "2026-08-08", "", "", "Not Started", "", "", "", ""]]
    service, values = _mock_sheets_service(existing)

    extraction = _extraction(company="Serenity Healthcare", role="Coordinator", status="applied")
    upsert_application(service, "sheet123", _parsed_email(), extraction)

    values.append.assert_not_called()
    values.update.assert_called_once()

def test_ambiguous_multiple_matches_skips_write(caplog):
    existing = [
        ["Acme Corp", "Data Engineer", "", "", "", "Applied", "", "", "2026-08-01", ""],
        ["Acme Corp", "Marketing Manager", "", "", "", "Applied", "", "", "2026-08-01", ""],
    ]
    service, values = _mock_sheets_service(existing)

    extraction = _extraction(company="Acme Corp", role="Something Else Entirely", status="interview_scheduled")
    with caplog.at_level("WARNING"):
        upsert_application(service, "sheet123", _parsed_email(), extraction)

    values.append.assert_not_called()
    values.update.assert_not_called()
    assert "Ambiguous" in caplog.text

def test_stale_rejection_never_flagged_no_reply():
    old_date = (date.today() - timedelta(days=40)).isoformat()
    existing = [["Acme Corp", "Data Engineer", "", "", "", "Rejected", "", "", old_date, ""]]
    service, values = _mock_sheets_service(existing)

    flipped = flag_stale_applications(service, "sheet123")

    assert flipped == 0
    values.update.assert_not_called()

def test_stale_applied_row_flagged_no_reply():
    old_date = (date.today() - timedelta(days=40)).isoformat()
    existing = [["Acme Corp", "Data Engineer", "", "", "", "Applied", "", "", old_date, ""]]
    service, values = _mock_sheets_service(existing)

    flipped = flag_stale_applications(service, "sheet123")

    assert flipped == 1
    updated_row = values.update.call_args.kwargs["body"]["values"][0]
    assert updated_row[5] == "No Reply"
