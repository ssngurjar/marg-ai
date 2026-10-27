"""Turning a sealed reply into ordered outbound parts (s05 §4.7, s07 §4.2).

`ReplyDelivery` is sealed like `SafeReply`: only `build_parts` can create one, and it only takes
`SafeReply`s. The outbox accepts nothing else, so no code path can queue an unchecked message.
"""

from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from app.domain.enums import FixedReplyKind, PartKind
from app.domain.replies import OutboundPart, ReplyButton, TemplateRef
from app.domain.text import split_for_channel
from app.safety.gate import SafeReply

_DELIVERY_SEAL: Final = object()
INTERACTIVE_BODY_LIMIT: Final = 1024  # WhatsApp's limit for a message that carries buttons


@dataclass(frozen=True, slots=True)
class ReplyDelivery:
    parts: tuple[OutboundPart, ...]  # part_no 0, 1, 2, … in delivery order
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _DELIVERY_SEAL:
            raise TypeError("ReplyDelivery can only be created by build_parts")


def build_parts(
    reply: SafeReply,
    audio_blob_id: UUID | None,
    preamble: SafeReply | None = None,
    template: TemplateRef | None = None,
) -> ReplyDelivery:
    """The parts that carry `reply`, in order.

    - `template` (NUDGE turns only): exactly one TEMPLATE part, nothing else.
    - Otherwise: the preamble's text first, then the audio, then the reply's text split to the
      channel limit; buttons attach to the last text part, which becomes INTERACTIVE.
    - A fixed CRISIS reply puts its text before the audio, so helpline numbers arrive first.
    """
    if template is not None:
        return _sealed([_template_part(template)])
    if not reply.text.strip():
        raise ValueError("build_parts got an empty reply text; a reply always has text")
    contents: list[_Content] = []
    if preamble is not None:
        contents.extend(_text_contents(preamble.text, buttons=()))
    reply_text = _text_contents(reply.text, buttons=reply.buttons)
    if audio_blob_id is None:
        contents.extend(reply_text)
    elif reply.fixed_kind is FixedReplyKind.CRISIS:
        contents.extend([*reply_text, _Content(PartKind.AUDIO, None, (), audio_blob_id)])
    else:
        contents.extend([_Content(PartKind.AUDIO, None, (), audio_blob_id), *reply_text])
    return _sealed([content.as_part(part_no) for part_no, content in enumerate(contents)])


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


def _text_contents(text: str, buttons: tuple[ReplyButton, ...]) -> list[_Content]:
    """TEXT parts for `text`; with buttons, the last is INTERACTIVE and short enough for them."""
    pieces = split_for_channel(text)
    if not buttons:
        return [_Content(PartKind.TEXT, piece, (), None) for piece in pieces]
    *leading, last = pieces
    tail = split_for_channel(last, limit=INTERACTIVE_BODY_LIMIT)
    *middle, interactive_body = tail
    contents = [_Content(PartKind.TEXT, piece, (), None) for piece in [*leading, *middle]]
    contents.append(_Content(PartKind.INTERACTIVE, interactive_body, buttons, None))
    return contents


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


def _sealed(parts: list[OutboundPart]) -> ReplyDelivery:
    return ReplyDelivery(parts=tuple(parts), _seal=_DELIVERY_SEAL)
