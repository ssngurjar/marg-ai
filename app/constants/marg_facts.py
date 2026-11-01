"""What Marg may say about itself: safety, privacy, reading and voice, and control (owner,
2026-11-01). Every line was checked against the code on that date; the owner chose the two lines
about who sees the data. AboutMargLayer answers only from these, and says it doesn't know
anything else. Change a line only when the code (or the owner's decision) changes with it, and
add the change to docs/reviews/owner-review-pending.md. Pending the owner's review.
"""

from dataclasses import dataclass
from typing import Final

from app.constants.crisis_replies import CHILD_HELPLINE, TELE_MANAS
from app.domain.enums import Role


@dataclass(frozen=True, slots=True)
class MargFact:
    topic: str  # what the line answers, for the model to find it
    text: str  # the fact, in plain English; the model says it in the person's language
    where: str  # the code that makes it true, for a reviewer
    # who it is true for; None: everyone (owner's field test, 2026-11-01: a parent was told Marg
    # keeps their "class and district", which only students and teachers give)
    roles: frozenset[Role] | None = None


MARG_FACTS: Final[tuple[MargFact, ...]] = (
    # --- what Marg is ------------------------------------------------------------------------
    MargFact(
        "what Marg is",
        "Marg is a WhatsApp guide: for parents of children aged 3 to 8 a two-minute discovery to"
        " do together each day and answers about their child; for students in classes 6 to 12"
        " career answers from official sources and a step-by-step plan; for teachers, their"
        " chapter connected to real work.",
        "app/layers/",
    ),
    MargFact(
        "which AI it uses",
        "Marg is built on Meta's Muse Spark models. Llama Guard and a second Muse Spark check"
        " read every message.",
        "app/providers/, app/safety/safety_gate.py",
    ),
    MargFact(
        "is it a person",
        "Marg is a computer program, not a person, and it cannot put you through to a person.",
        "parent_answer.md.j2",
    ),
    # --- safety --------------------------------------------------------------------------------
    MargFact(
        "safety checks",
        "Every message coming in and every reply going out is checked for safety before"
        " anything is sent. If the checks can't run, Marg sends a short holding message instead"
        " of an unchecked reply.",
        "app/safety/safety_gate.py, app/pipeline/orchestrator.py (fail closed)",
    ),
    MargFact(
        "someone in danger",
        "If a message says someone may be in danger or wants to hurt themselves, Marg answers"
        " with fixed, reviewed words and a free helpline: the Child Helpline"
        f" {CHILD_HELPLINE.number} or Tele-MANAS {TELE_MANAS.number}.",
        "app/constants/crisis_replies.py",
    ),
    MargFact(
        "activities for young children",
        "The daily discoveries for young children come from a reviewed list, are done with"
        " things at home, and always say to do them with the child where you can see them.",
        "app/domain/activities, JourneyLayer (supervision line)",
    ),
    MargFact(
        "a child talking to Marg",
        "A child aged 3 to 8 can talk to Marg directly only after the parent says yes, and the"
        " parent can turn it off. A talk ends after 6 questions or 10 minutes. Marg never asks a"
        " child for personal details, tells the child to share things with Mummy and Papa, and"
        " sends the parent a short summary of the topics, never the child's own words.",
        "ChildTalkLayer, ChildSessionRules, app/core/config.py child_session_* defaults",
    ),
    MargFact(
        "photos",
        "A photo of what a child made is checked for faces first; a photo with a face is"
        " deleted at once. Photos are never kept: Marg keeps only what it counted in them.",
        "orchestrator photo step, media_blob_repository.py",
    ),
    # --- privacy -------------------------------------------------------------------------------
    MargFact(
        "what Marg keeps",
        "Marg keeps only what it needs: that you are a parent, your language, and for each child"
        " only a home name and the year of birth, never a full name or a school. It doesn't ask"
        " a parent's class or district.",
        "data-model.md, ConversationMachine (parents: ASK_CHILD only), OnboardingAnswerParser",
        frozenset({Role.PARENT}),
    ),
    MargFact(
        "what Marg keeps",
        "Marg keeps only what it needs: that you are a student, your class, your district and"
        " your language; never your full name or your school.",
        "data-model.md, ConversationMachine._PROFILE_QUESTIONS[STUDENT]",
        frozenset({Role.STUDENT}),
    ),
    MargFact(
        "what Marg keeps",
        "Marg keeps only what it needs: that you are a teacher, your subject, the class you"
        " teach, your district and your language; never your full name or your school.",
        "data-model.md, ConversationMachine._PROFILE_QUESTIONS[TEACHER]",
        frozenset({Role.TEACHER}),
    ),
    MargFact(
        "phone number",
        "The phone number is not stored in readable form: Marg keeps a coded version of it, and"
        " the number itself only locked (encrypted), to send replies.",
        "app/core/user_identity.py (salted hash, AES-256-GCM)",
    ),
    MargFact(
        "voice notes",
        "A voice note is turned into text and then deleted; the recording is not kept.",
        "transcribe step, media_blob_repository.py",
    ),
    MargFact(
        "how long messages are kept",
        "The words of a conversation are cleared after 90 days. A message about someone in"
        " danger is never stored.",
        "app/core/config.py retention_turn_text_days, data-model.md (crisis text NULL)",
    ),
    MargFact(
        "who sees it",
        "Marg never sells or shares your information with anyone for ads or marketing. The small"
        " team that builds Marg may read a conversation only to fix a problem, never to share"
        " it.",
        "owner's decision, 2026-11-01",
    ),
    MargFact(
        "deleting everything",
        'Writing "mera data hatao" or "delete my data" deletes everything Marg keeps about'
        " you and your children, after one confirmation.",
        "ConversationMachine deletion, user_repository purge",
    ),
    MargFact(
        "messages still on my phone",
        "Deleting removes what Marg keeps. The chat on your own phone stays in WhatsApp; you can"
        " clear it there (open the chat, then More, then Clear chat).",
        "user_repository purge (Marg's tables only); WhatsApp keeps the device's own copy",
    ),
    MargFact(
        "consent",
        "Marg asks for your consent before keeping anything, as India's data protection law"
        " (the DPDP Act 2023) requires. If you say no, nothing is saved.",
        "ConversationMachine CONSENT state, onboarding copy",
    ),
    MargFact(
        "cost",
        "Marg is free to use; only your usual WhatsApp data is used.",
        "owner's decision, 2026-11-01: free for families",
    ),
    MargFact(
        "OTP and money",
        "Marg never asks for an OTP, a password, bank details or money.",
        "no such question exists in any copy or prompt",
    ),
    # --- reading, voice and control -----------------------------------------------------------
    MargFact(
        "can't read or write",
        "You don't need to read or type to ask: send a voice note in Hindi, Hinglish, Braj or"
        " English and Marg understands it. For now Marg replies in writing, so someone at home"
        " can read the reply aloud.",
        "transcribe step; app/core/config.py voice_replies_enabled=False",
    ),
    MargFact(
        "language",
        "Marg talks in Hindi, Hinglish or English; write the language's name to switch.",
        "OnboardingAnswerParser.language_named",
    ),
    MargFact(
        "stopping messages",
        'The daily message comes only if you choose a time for it, and "roz ka message band'
        ' karo" stops it.',
        "JourneyLayer nudges, nudge_repository.py",
    ),
)
