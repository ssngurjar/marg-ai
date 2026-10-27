"""ReplyPartsBuilder: a sealed reply into ordered outbound parts (s05 §4.7, s07 §4.2).

`ReplyDelivery` is sealed like `SafeReply`: only `ReplyPartsBuilder.build` can create one, and
it only takes `SafeReply`s. The outbox accepts nothing else, so no code path can queue an
unchecked message.
"""

from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from app.constants.whatsapp import MAX_CAPTION_CHARS, MAX_INTERACTIVE_BODY_CHARS
from app.domain.enums import FixedReplyKind, PartKind
from app.domain.models.reply import OutboundPart, ReplyButton, TemplateRef
from app.domain.rules.message_splitter import MessageSplitter
from app.safety.safety_gate import SafeReply

_DELIVERY_SEAL: Final = object()


@dataclass(frozen=True, slots=True)
class ReplyDelivery:
    parts: tuple[OutboundPart, ...]  # part_no 0, 1, 2, … in delivery order
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _DELIVERY_SEAL:
            raise TypeError("ReplyDelivery can only be created by ReplyPartsBuilder.build")


@dataclass(frozen=True, slots=True)
class _Content:
    kind: PartKind
    text: str | None
    buttons: tuple[ReplyButton, ...]
    audio_blob_id: UUID | None

    def as_part(self, part_no: int) -> OutboundPart:
        return OutboundPart(
            part_no=part_no,
            kind=self.kind,
            text=self.text,
            audio_blob_id=self.audio_blob_id,
            image_blob_id=None,
            buttons=list(self.buttons),
            template=None,
        )


class ReplyPartsBuilder:
    @staticmethod
    def build(
        reply: SafeReply,
        audio_blob_id: UUID | None,
        preamble: SafeReply | None = None,
        template: TemplateRef | None = None,
        trailer: SafeReply | None = None,
    ) -> ReplyDelivery:
        """The parts that carry `reply`, in order.

        - `template` (NUDGE turns only): exactly one TEMPLATE part, nothing else.
        - Otherwise: the preamble's text (with its own buttons) first, then the audio, then the
          reply's text split to the channel limit; buttons attach to the last text part, which
          becomes INTERACTIVE.
        - A fixed CRISIS reply puts its text before the audio, so helpline numbers arrive first.
        - The trailer's text (with its own buttons) comes last, e.g. the nudge-time question
          after the first khoj (s10b §4.11): a message holds at most 3 buttons.
        """
        if template is not None:
            return ReplyPartsBuilder._sealed([ReplyPartsBuilder._template_part(template)])
        if not reply.text.strip():
            raise ValueError(
                "ReplyPartsBuilder.build got an empty reply text; a reply always has text"
            )
        contents: list[_Content] = []
        if preamble is not None:
            contents.extend(ReplyPartsBuilder._text_contents(preamble.text, preamble.buttons))
        reply_text = ReplyPartsBuilder._text_contents(reply.text, buttons=reply.buttons)
        if audio_blob_id is None:
            contents.extend(reply_text)
        elif reply.fixed_kind is FixedReplyKind.CRISIS:
            contents.extend([*reply_text, _Content(PartKind.AUDIO, None, (), audio_blob_id)])
        else:
            contents.extend([_Content(PartKind.AUDIO, None, (), audio_blob_id), *reply_text])
        if trailer is not None:
            contents.extend(ReplyPartsBuilder._text_contents(trailer.text, trailer.buttons))
        return ReplyPartsBuilder._sealed(
            [content.as_part(part_no) for part_no, content in enumerate(contents)]
        )

    @staticmethod
    def _text_contents(text: str, buttons: tuple[ReplyButton, ...]) -> list[_Content]:
        """TEXT parts; with buttons, the last is INTERACTIVE and short enough to carry them."""
        pieces = MessageSplitter.split(text)
        if not buttons:
            return [_Content(PartKind.TEXT, piece, (), None) for piece in pieces]
        *leading, last = pieces
        tail = MessageSplitter.split(last, limit=MAX_INTERACTIVE_BODY_CHARS)
        *middle, buttons_body = tail
        contents = [_Content(PartKind.TEXT, piece, (), None) for piece in [*leading, *middle]]
        contents.append(_Content(PartKind.INTERACTIVE, buttons_body, buttons, None))
        return contents

    @staticmethod
    def card(reply: SafeReply, image_blob_id: UUID) -> ReplyDelivery:
        """A khoj card (s10b §4.13): exactly one IMAGE part, the sealed caption as its text."""
        return ReplyPartsBuilder._sealed([ReplyPartsBuilder._image_part(reply, image_blob_id)])

    @staticmethod
    def _image_part(reply: SafeReply, image_blob_id: UUID) -> OutboundPart:
        if len(reply.text) > MAX_CAPTION_CHARS:
            raise ValueError(f"an image caption is at most {MAX_CAPTION_CHARS} characters")
        return OutboundPart(
            part_no=0,
            kind=PartKind.IMAGE,
            text=reply.text,
            audio_blob_id=None,
            image_blob_id=image_blob_id,
            buttons=[],
            template=None,
        )

    @staticmethod
    def _template_part(template: TemplateRef) -> OutboundPart:
        return OutboundPart(
            part_no=0,
            kind=PartKind.TEMPLATE,
            text=None,
            audio_blob_id=None,
            image_blob_id=None,
            buttons=[],
            template=template,
        )

    @staticmethod
    def _sealed(parts: list[OutboundPart]) -> ReplyDelivery:
        return ReplyDelivery(parts=tuple(parts), _seal=_DELIVERY_SEAL)
