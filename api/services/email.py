import logging
from typing import Protocol

from core.config import settings

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send_magic_link(self, to_email: str, magic_link_url: str) -> None: ...


class ConsoleEmailSender:
    async def send_magic_link(self, to_email: str, magic_link_url: str) -> None:
        logger.info("magic_link_email to=%s url=%s", to_email, magic_link_url)


def get_email_sender() -> EmailSender:
    if settings.email_sender == "console":
        return ConsoleEmailSender()
    raise ValueError(f"Unsupported email_sender: {settings.email_sender}")
