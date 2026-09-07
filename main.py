import json
import logging
import functions_framework
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
    except Exception as exc:
        logger.error("Run failed: %s", exc, exc_info=True)
        try:
            send_failure_alert(get_credentials(), str(exc))
        except Exception as alert_exc:
            logger.error("Failed to send failure alert: %s", alert_exc)

        return (json.dumps({"error": str(exc)}), 500, {"Content-Type": "application/json"})
