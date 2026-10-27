"""The sealed reply path (s07 §4.2, s05 §4.7): seals, build_parts and the fixed texts."""

import ast
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.errors import ConfigError
from app.domain.enums import FixedReplyKind, Language, PartKind, SafetyDecision
from app.domain.replies import LocalisedReply, ReplyButton, TemplateRef
from app.domain.safety import SafetyVerdict
from app.pipeline import fallbacks
from app.pipeline.fallbacks import FixedReplyVariant, check_fixed_texts, localise_fixed
from app.pipeline.parts import INTERACTIVE_BODY_LIMIT, ReplyDelivery, build_parts
from app.safety.gate import SafeReply, SafetyGate

pytestmark = pytest.mark.unit

APP_ROOT = Path(__file__).resolve().parents[3] / "app"
GATE = SafetyGate()


def sealed(
    text: str,
    *,
    buttons: list[ReplyButton] | None = None,
    kind: FixedReplyKind = FixedReplyKind.HOLDING,
) -> SafeReply:
    reply = LocalisedReply(
        text=text,
        spoken_text=text,
        reply_register=Language.HINGLISH,
        citations=[],
        buttons=buttons or [],
    )
    return GATE.clear_fixed(reply, kind)


# --- seals -----------------------------------------------------------------------------------


def test_safe_reply_cannot_be_built_without_the_gate() -> None:
    with pytest.raises(TypeError, match="SafeReply can only be created by SafetyGate"):
        SafeReply(
            text="hi",
            spoken_text="hi",
            reply_register=Language.ENGLISH,
            citations=(),
            buttons=(),
            verdict=SafetyVerdict(decision=SafetyDecision.ALLOW, categories=[], source="fixed"),
            fixed_kind=None,
            _seal=object(),
        )


def test_reply_delivery_cannot_be_built_without_build_parts() -> None:
    with pytest.raises(TypeError, match="ReplyDelivery can only be created by build_parts"):
        ReplyDelivery(parts=(), _seal=object())


def test_clear_fixed_marks_the_verdict_as_fixed_without_a_classifier() -> None:
    safe = sealed("Thodi der baad likhiye.", kind=FixedReplyKind.TRY_AGAIN_LATER)
    assert safe.verdict == SafetyVerdict(
        decision=SafetyDecision.ALLOW, categories=[], source="fixed"
    )
    assert safe.fixed_kind is FixedReplyKind.TRY_AGAIN_LATER


def _module_references(name: str) -> list[str]:
    found: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Name) and node.id == name) or (
                isinstance(node, ast.alias) and node.name == name
            ):
                found.append(path.relative_to(APP_ROOT).as_posix())
                break
    return sorted(found)


def test_only_the_gate_references_the_reply_seal() -> None:
    assert _module_references("_SEAL") == ["safety/gate.py"]


def test_only_build_parts_references_the_delivery_seal() -> None:
    assert _module_references("_DELIVERY_SEAL") == ["pipeline/parts.py"]


def test_only_the_outbox_repository_inserts_outbox_rows() -> None:
    inserting: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            is_insert = (isinstance(callee, ast.Name) and callee.id == "insert") or (
                isinstance(callee, ast.Attribute) and callee.attr == "insert"
            )
            mentions_outbox = any(
                isinstance(argument, ast.Name) and argument.id == "outbox_messages"
                for argument in node.args
            ) or (
                isinstance(callee, ast.Attribute)
                and isinstance(callee.value, ast.Name)
                and callee.value.id == "outbox_messages"
            )
            if is_insert and mentions_outbox:
                inserting.append(path.relative_to(APP_ROOT).as_posix())
    assert sorted(set(inserting)) == ["store/repositories/outbox.py"]


# --- build_parts ---------------------------------------------------------------------------


def test_a_short_reply_is_one_text_part() -> None:
    delivery = build_parts(sealed("Munni ne parchhai dekhi!"), audio_blob_id=None)
    assert [(part.part_no, part.kind, part.text) for part in delivery.parts] == [
        (0, PartKind.TEXT, "Munni ne parchhai dekhi!")
    ]


def test_buttons_go_on_the_last_part_which_becomes_interactive() -> None:
    buttons = [ReplyButton(id="jrn:done", title="Ho gaya")]
    text = ("Ek lamba sandesh. " * 300).strip()  # longer than 4096
    delivery = build_parts(sealed(text, buttons=buttons), audio_blob_id=None)
    kinds = [part.kind for part in delivery.parts]
    assert kinds[:-1] == [PartKind.TEXT] * (len(kinds) - 1)
    assert kinds[-1] is PartKind.INTERACTIVE
    assert delivery.parts[-1].buttons == buttons
    last_text = delivery.parts[-1].text
    assert last_text is not None
    assert len(last_text) <= INTERACTIVE_BODY_LIMIT
    assert [part.part_no for part in delivery.parts] == list(range(len(delivery.parts)))


def test_audio_comes_before_the_text() -> None:
    audio = uuid4()
    delivery = build_parts(sealed("Suniye aur padhiye."), audio_blob_id=audio)
    assert [part.kind for part in delivery.parts] == [PartKind.AUDIO, PartKind.TEXT]
    assert delivery.parts[0].audio_blob_id == audio


def test_a_crisis_reply_puts_text_before_audio() -> None:
    delivery = build_parts(
        sealed("Helpline: abhi baat kijiye.", kind=FixedReplyKind.CRISIS), audio_blob_id=uuid4()
    )
    assert [part.kind for part in delivery.parts] == [PartKind.TEXT, PartKind.AUDIO]


def test_a_preamble_comes_first() -> None:
    delivery = build_parts(
        sealed("Aaj ki khoj: parchhai."), audio_blob_id=None, preamble=sealed("Profile ho gaya!")
    )
    assert [part.text for part in delivery.parts] == ["Profile ho gaya!", "Aaj ki khoj: parchhai."]


def test_a_template_is_the_only_part() -> None:
    template = TemplateRef(name="aaj_ki_khoj", language_code="hi", button_payloads=["jrn:today"])
    delivery = build_parts(sealed("ignored"), audio_blob_id=uuid4(), template=template)
    assert len(delivery.parts) == 1
    assert delivery.parts[0].kind is PartKind.TEMPLATE
    assert delivery.parts[0].template == template


@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_reply_is_a_programming_error(text: str) -> None:
    with pytest.raises(ValueError, match="empty reply text"):
        build_parts(sealed(text), audio_blob_id=None)


# --- fixed texts ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", list(Language))
def test_try_again_later_exists_in_every_language(language: Language) -> None:
    reply = localise_fixed(FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, language)
    assert reply.reply_register is language
    assert reply.text.strip()
    assert "http" not in reply.spoken_text


def test_unknown_language_falls_back_to_hinglish() -> None:
    reply = localise_fixed(FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, None)
    assert reply.reply_register is Language.HINGLISH


def test_a_kind_without_texts_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="no fixed text for crisis/default/hindi"):
        localise_fixed(FixedReplyKind.CRISIS, FixedReplyVariant.DEFAULT, Language.HINDI)


def test_every_registered_fixed_text_has_every_language() -> None:
    check_fixed_texts()


def test_a_missing_language_fails_the_startup_check(monkeypatch: pytest.MonkeyPatch) -> None:
    without_hindi = {
        key: text for key, text in fallbacks.FIXED_TEXTS.items() if key.language != Language.HINDI
    }
    monkeypatch.setattr(fallbacks, "FIXED_TEXTS", without_hindi)
    with pytest.raises(ConfigError, match="try_again_later/default/hindi"):
        check_fixed_texts()
