"""Slack webhook mock/integration."""
import logging

from pipeline.config import get_settings

logger = logging.getLogger(__name__)


def send_slack_notification(message: str) -> bool:
    """Send a notification to Slack or mock it if the webhook URL is empty."""
    settings = get_settings()
    webhook_url = settings.slack_webhook_url.get_secret_value()

    if not webhook_url:
        logger.info(f"notification_skipped: {message} (Slack webhook URL not configured)")
        return False

    logger.info(f"Sending Slack notification: {message}")
    try:
        import requests
        response = requests.post(webhook_url, json={"text": message}, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False
