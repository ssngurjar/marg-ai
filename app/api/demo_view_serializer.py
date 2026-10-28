"""DemoViewSerializer: a visitor's turn as the JSON the demo page renders (s14 §4.4, §4.5).

The same shape for the live stream's `turn` event and the polling fallback, so the page has one
renderer. Media goes by URL under /demo/media, which checks the visitor owns it.
"""

from uuid import UUID

from app.store.repositories.demo_repository import MessageView, TurnView


class DemoViewSerializer:
    @staticmethod
    def message(view: MessageView) -> dict[str, object]:
        turn = view.turn
        return {
            "status": view.message_status,
            "turn": DemoViewSerializer.turn(turn) if turn is not None else None,
        }

    @staticmethod
    def turn(turn: TurnView) -> dict[str, object]:
        return {
            "turn_id": str(turn.turn_id),
            "status": turn.status,
            "route": turn.route,
            "message_ids": list(turn.message_ids),
            "steps": [
                {
                    "step": step.step,
                    "outcome": step.outcome,
                    "duration_ms": step.duration_ms,
                    "detail": step.detail,
                    "cost_usd": str(step.cost_usd) if step.cost_usd is not None else None,
                    "model": step.model,
                }
                for step in turn.steps
            ],
            "parts": [
                {
                    "kind": part.kind,
                    "text": part.text,
                    "buttons": [
                        {"id": button.id, "title": button.title} for button in part.buttons
                    ],
                    "audio_url": _media_url(part.audio_blob_id),
                    "image_url": _media_url(part.image_blob_id),
                }
                for part in turn.parts
            ],
        }


def _media_url(blob_id: UUID | None) -> str | None:
    return f"/demo/media/{blob_id}" if blob_id is not None else None
