"""WhatsApp Cloud API limits and error codes (s03 §4.9, §4.10).

Checked against Meta's docs on 2026-10-27.
"""

from datetime import timedelta
from typing import Final

from app.domain.rules.message_splitter import MessageSplitter

PROVIDER: Final = "whatsapp"
WHATSAPP_OBJECT: Final = "whatsapp_business_account"

MAX_TEXT_CHARS: Final = MessageSplitter.TEXT_LIMIT  # 4096
MAX_INTERACTIVE_BODY_CHARS: Final = 1024  # a message that carries buttons
MAX_BUTTONS: Final = 3
MAX_CAPTION_CHARS: Final = 1024
MAX_AUDIO_BYTES: Final = 16 * 1024 * 1024
MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024
VOICE_NOTE_MIME: Final = "audio/ogg; codecs=opus"
IMAGE_MIMES: Final = frozenset({"image/jpeg", "image/png"})

CUSTOMER_SERVICE_WINDOW: Final = timedelta(hours=24)
"""Free-form messages reach a user only within 24 h of their last message; templates always."""

RATE_LIMIT_CODES: Final = frozenset({4, 80007, 130429, 131056})
TRANSIENT_CODES: Final = frozenset({131000, 131016})

NOT_STORED_MESSAGE_TYPES: Final = frozenset({"reaction", "system"})
"""A reaction to our message isn't a request; number changes aren't followed in the MVP."""
