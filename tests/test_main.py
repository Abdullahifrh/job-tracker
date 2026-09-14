from unittest.mock import MagicMock, patch

from google.auth.exceptions import RefreshError

from main import handle_request

def test_handle_request_returns_pipeline_summary_as_json():
    fake_summary = {"emails_scanned": 3, "emails_matched": 1, "rows_flagged_no_reply": 0}

    with patch("main.run_pipeline", return_value=fake_summary):
        body, status, headers = handle_request(None)

    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert '"emails_scanned": 3' in body

def test_handle_request_sends_alert_and_returns_500_on_failure():
    with patch("main.run_pipeline", side_effect=RuntimeError("something broke")), \
         patch("main.get_credentials", return_value=MagicMock()), \
         patch("main.send_failure_alert") as mock_alert:
        body, status, headers = handle_request(None)

    assert status == 500
    assert "something broke" in body
    mock_alert.assert_called_once()

def test_handle_request_returns_500_even_if_alert_itself_fails():
    with patch("main.run_pipeline", side_effect=RuntimeError("something broke")), \
         patch("main.get_credentials", return_value=MagicMock()), \
         patch("main.send_failure_alert", side_effect=RuntimeError("alert failed too")):
        body, status, headers = handle_request(None)

    assert status == 500

def test_handle_request_skips_alert_attempt_on_auth_failure():
    auth_error = RefreshError("invalid_grant: Token has been expired or revoked.")

    with patch("main.run_pipeline", side_effect=auth_error), \
         patch("main.send_failure_alert") as mock_alert:
        body, status, headers = handle_request(None)

    assert status == 500
    assert "invalid_grant" in body
    mock_alert.assert_not_called()
