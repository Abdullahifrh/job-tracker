from unittest.mock import MagicMock, patch

from src.update_tracker import run_pipeline

def _email(message_id):
    return {
        "message_id": message_id, "from": "x", "subject": "x", "date": "x",
        "body_text": "x", "is_outbound": False, "is_auto_reply": False,
    }

@patch("src.update_tracker.flag_stale_applications", return_value=0)
@patch("src.update_tracker.save_processed_ids")
@patch("src.update_tracker.upsert_application")
@patch("src.update_tracker.extract_application")
@patch("src.update_tracker.fetch_new_matching_emails")
@patch("src.update_tracker.build")
@patch("src.update_tracker.get_credentials", return_value=MagicMock())
@patch("src.update_tracker.load_processed_ids", return_value=set())
def test_partial_batch_failure_still_saves_earlier_successes(
    mock_load, mock_creds, mock_build, mock_fetch, mock_extract, mock_upsert, mock_save, mock_flag, monkeypatch,
):
    monkeypatch.setenv("TRACKER_SHEET_ID", "sheet123")
    emails = [_email("m1"), _email("m2")]
    mock_fetch.return_value = (emails, ["m1", "m2", "m3"])
    mock_extract.side_effect = ["extraction-for-m1", RuntimeError("quota exceeded")]

    try:
        run_pipeline()
        assert False, "expected the RuntimeError to propagate"
    except RuntimeError:
        pass

    saved_id_batches = [call.args[2] for call in mock_save.call_args_list]
    assert ["m1"] in saved_id_batches
    assert mock_save.call_count == 1
    mock_flag.assert_not_called()
