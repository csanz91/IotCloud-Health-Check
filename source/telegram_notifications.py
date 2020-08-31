import logging
import logging.config

from notifiers import get_notifier
from docker_secrets import getDocketSecrets

logger = logging.getLogger()

TELEGRAM_TOKEN = getDocketSecrets("telegram_token")
TELEGRAM_CHAT_ID = getDocketSecrets("telegram_chat_id")

telegram = get_notifier("telegram")


def sendNotification(message):
    logger.info(message, exc_info=True)
    telegram.notify(
        message=f"[IotCloud]: {message}",
        token=TELEGRAM_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
    )
