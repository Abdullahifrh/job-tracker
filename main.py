import json
import logging

import functions_framework
from google.auth.exceptions import RefreshError

from src.alerts import send_failure_alert
from src.auth import get_credentials
from src.update_tracker import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
logger = logging.getLogger(__name__)

@functions_framework.http
def handle_request(request):
    try:
        summary = run_pipeline()
        logger.info("Run completed: %s", summary)

        return (json.dumps(summary), 200, {"Content-Type": "application/json"})
    except RefreshError as exc:
        # No alert email is even attempted here: sending one also requires
        # working Gmail auth, which is exactly what just failed. Trying anyway
        # only adds a second, identical, misleading failure to the logs and
        # hides the one piece of information that actually matters here.
        logger.error(
            "Authentication itself failed, so no alert email could be sent: %s. "
            "The OAuth token in Secret Manager (gmail-sheets-oauth-token) needs "
            "to be refreshed with a newly consented token.json.",
            exc,
        )

        return (json.dumps({"error": str(exc)}), 500, {"Content-Type": "application/json"})
    except Exception as exc:
        logger.error("Run failed: %s", exc, exc_info=True)
        try:
            send_failure_alert(get_credentials(), str(exc))
        except Exception as alert_exc:
            logger.error("Failed to send failure alert: %s", alert_exc)

        return (json.dumps({"error": str(exc)}), 500, {"Content-Type": "application/json"})
