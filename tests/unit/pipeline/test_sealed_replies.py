"""The sealed reply path (s07 §4.2, s05 §4.7): seals, the parts builder and the fixed texts."""

import ast
from pathlib import Path
from uuid import uuid4

import pytest

from app.audio.tts_text_preparer import TtsTextPreparer
from app.constants import fixed_replies
from app.constants.whatsapp import MAX_INTERACTIVE_BODY_CHARS
from app.core.errors import ConfigError
from app.domain.enums import (
    FixedReplyKind,
    FixedReplyVariant,
    Language,
    PartKind,
    SafetyDecision,
    Speaker,
)
from app.domain.models.reply import LocalisedReply, ReplyButton, TemplateRef
from app.domain.models.safety import SafetyVerdict
from app.pipeline.fixed_reply_service import FixedReplyService
from app.pipeline.reply_parts_builder import ReplyDelivery, ReplyPartsBuilder
from app.safety.safety_gate import SafeReply, SafetyGate
from tests.fakes.domain_policy import rules_only_policy
from tests.fakes.safety_classifier import FakeSafetyClassifier

pytestmark = pytest.mark.unit

APP_ROOT = Path(__file__).resolve().parents[3] / "app"
GATE = SafetyGate(FakeSafetyClassifier(), rules_only_policy())


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


def test_reply_delivery_cannot_be_built_without_the_parts_builder() -> None:
    with pytest.raises(
        TypeError, match=r"ReplyDelivery can only be created by ReplyPartsBuilder\.build"
    ):
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
    assert _module_references("_SEAL") == ["safety/safety_gate.py"]


def test_only_the_parts_builder_references_the_delivery_seal() -> None:
    assert _module_references("_DELIVERY_SEAL") == ["pipeline/reply_parts_builder.py"]


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
    assert sorted(set(inserting)) == ["store/repositories/outbox_repository.py"]


# --- ReplyPartsBuilder ----------------------------------------------------------------------------


def test_a_short_reply_is_one_text_part() -> None:
    delivery = ReplyPartsBuilder.build(sealed("Munni ne parchhai dekhi!"), audio_blob_id=None)
    assert [(part.part_no, part.kind, part.text) for part in delivery.parts] == [
        (0, PartKind.TEXT, "Munni ne parchhai dekhi!")
    ]


def test_buttons_go_on_the_last_part_which_becomes_interactive() -> None:
    buttons = [ReplyButton(id="jrn:done", title="Ho gaya")]
    text = ("Ek lamba sandesh. " * 300).strip()  # longer than 4096
    delivery = ReplyPartsBuilder.build(sealed(text, buttons=buttons), audio_blob_id=None)
    kinds = [part.kind for part in delivery.parts]
    assert kinds[:-1] == [PartKind.TEXT] * (len(kinds) - 1)
    assert kinds[-1] is PartKind.INTERACTIVE
    assert delivery.parts[-1].buttons == buttons
    last_text = delivery.parts[-1].text
    assert last_text is not None
    assert len(last_text) <= MAX_INTERACTIVE_BODY_CHARS
    assert [part.part_no for part in delivery.parts] == list(range(len(delivery.parts)))


def test_audio_comes_before_the_text() -> None:
    audio = uuid4()
    delivery = ReplyPartsBuilder.build(sealed("Suniye aur padhiye."), audio_blob_id=audio)
    assert [part.kind for part in delivery.parts] == [PartKind.AUDIO, PartKind.TEXT]
    assert delivery.parts[0].audio_blob_id == audio


def test_a_crisis_reply_puts_text_before_audio() -> None:
    delivery = ReplyPartsBuilder.build(
        sealed("Helpline: abhi baat kijiye.", kind=FixedReplyKind.CRISIS), audio_blob_id=uuid4()
    )
    assert [part.kind for part in delivery.parts] == [PartKind.TEXT, PartKind.AUDIO]


def test_a_preamble_comes_first() -> None:
    delivery = ReplyPartsBuilder.build(
        sealed("Aaj ki khoj: parchhai."), audio_blob_id=None, preamble=sealed("Profile ho gaya!")
    )
    assert [part.text for part in delivery.parts] == ["Profile ho gaya!", "Aaj ki khoj: parchhai."]


def test_a_template_is_the_only_part() -> None:
    template = TemplateRef(name="aaj_ki_khoj", language_code="hi", button_payloads=["jrn:today"])
    delivery = ReplyPartsBuilder.build(sealed("ignored"), audio_blob_id=uuid4(), template=template)
    assert len(delivery.parts) == 1
    assert delivery.parts[0].kind is PartKind.TEMPLATE
    assert delivery.parts[0].template == template


@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_reply_is_a_programming_error(text: str) -> None:
    with pytest.raises(ValueError, match="empty reply text"):
        ReplyPartsBuilder.build(sealed(text), audio_blob_id=None)


# --- fixed texts ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", list(Language))
def test_try_again_later_exists_in_every_language(language: Language) -> None:
    reply = FixedReplyService.localise(
        FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, language
    )
    assert reply.reply_register is language
    assert reply.text.strip()
    assert "http" not in reply.spoken_text


def test_unknown_language_falls_back_to_hinglish() -> None:
    reply = FixedReplyService.localise(
        FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, None
    )
    assert reply.reply_register is Language.HINGLISH


def test_a_kind_without_texts_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="no fixed text for crisis/default/hindi"):
        FixedReplyService.localise(FixedReplyKind.CRISIS, FixedReplyVariant.DEFAULT, Language.HINDI)


def test_every_registered_fixed_text_has_every_language() -> None:
    FixedReplyService.check_all_languages()


def test_a_missing_language_fails_the_startup_check(monkeypatch: pytest.MonkeyPatch) -> None:
    without_hindi = {
        key: text
        for key, text in fixed_replies.FIXED_TEXTS.items()
        if key.language != Language.HINDI
    }
    monkeypatch.setattr(fixed_replies, "FIXED_TEXTS", without_hindi)
    with pytest.raises(ConfigError, match="try_again_later/default/hindi"):
        FixedReplyService.check_all_languages()


@pytest.mark.parametrize("key", sorted(fixed_replies.FIXED_TEXTS, key=str), ids=str)
def test_every_fixed_reply_can_be_spoken_by_its_voice(key: fixed_replies.FixedTextKey) -> None:
    """A voice turn speaks fixed replies too (s06 §4.7); Hinglish is spoken from the Hindi."""
    fixed = fixed_replies.FIXED_TEXTS[key]
    prepared = TtsTextPreparer.prepare(fixed.spoken_text, key.language)
    assert prepared.sentences


def test_hinglish_fixed_replies_are_spoken_from_the_reviewed_hindi() -> None:
    for key, fixed in fixed_replies.FIXED_TEXTS.items():
        if key.language is Language.HINGLISH:
            hindi = fixed_replies.FIXED_TEXTS[
                fixed_replies.FixedTextKey(key.kind, key.variant, Language.HINDI)
            ]
            assert fixed.spoken_text == hindi.spoken_text, key


@pytest.mark.parametrize("variant", [FixedReplyVariant.SELF_HARM, FixedReplyVariant.ABUSE])
@pytest.mark.parametrize("language", list(Language))
def test_a_child_in_crisis_gets_the_child_words_and_the_child_helpline(
    variant: FixedReplyVariant, language: Language
) -> None:
    reply = FixedReplyService.localise(FixedReplyKind.CRISIS, variant, language, Speaker.LEARNER)
    assert "1098" in reply.text
    assert "?" not in reply.text  # a child in crisis isn't asked anything
    voice = Language.HINDI if language is Language.HINGLISH else language
    assert TtsTextPreparer.prepare(reply.spoken_text, voice).sentences


@pytest.mark.parametrize("variant", list(FixedReplyVariant))
def test_any_refusal_to_a_child_is_the_child_wording(variant: FixedReplyVariant) -> None:
    reply = FixedReplyService.localise(
        FixedReplyKind.REFUSE, variant, Language.HINGLISH, Speaker.LEARNER
    )
    assert reply.text.startswith("Yeh baat Mummy-Papa ya doctor se poochho")


def test_other_fixed_replies_are_the_same_for_a_child() -> None:
    for_child = FixedReplyService.localise(
        FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, Language.HINDI, Speaker.LEARNER
    )
    for_parent = FixedReplyService.localise(
        FixedReplyKind.TRY_AGAIN_LATER, FixedReplyVariant.DEFAULT, Language.HINDI
    )
    assert for_child == for_parent
