from unittest.mock import MagicMock, patch
from src.alerts import send_failure_alert

def test_send_failure_alert_sends_to_own_address():
    service = MagicMock()
    service.users.return_value.getProfile.return_value.execute.return_value = {"emailAddress": "me@example.com"}

    with patch("src.alerts.build", return_value=service):
        send_failure_alert(creds=MagicMock(), error_summary="something broke")

    send_call = service.users.return_value.messages.return_value.send
    send_call.assert_called_once()
    assert send_call.call_args.kwargs["userId"] == "me"
