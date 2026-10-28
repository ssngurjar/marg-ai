"""Shared student fixtures: a profile, scripted mentor and roadmap outputs, and a retriever over
a fake corpus with chosen relevance."""

from uuid import UUID

from pydantic import HttpUrl

from app.domain.enums import CorpusTopic, Language, Role
from app.domain.models.retrieval import RetrievedChunk
from app.domain.models.turn import TurnContext
from app.rag.retriever import Retriever, RetrieverSettings
from app.store.repositories.chunk_repository import Candidate
from tests.fakes.corpus import FakeChunkStore, FakeEmbedder, stored
from tests.support.turn_context import text_message, turn_context, user_profile

MENTOR_ANSWER: dict[str, object] = {
    "knows": True,
    "opening": "Achha sawaal hai, class 8 ki scholarship ke baare mein dekhte hain.",
    "claims": [
        {"text": "NMMS class 8 ke students ke liye hai.", "sources": ["C1"]},
        {"text": "Iska form National Scholarship Portal par bharte hain.", "sources": ["C2", "C1"]},
    ],
    "guidance": "Apne teacher se is baare mein baat karo.",
    "next_question": "Kya aap sarkari school mein padhte ho?",
    "suggest_roadmap": True,
    "spoken_text": "अच्छा सवाल है। एनएमएमएस कक्षा आठ के विद्यार्थियों के लिए है।",
}
DONT_KNOW_ANSWER: dict[str, object] = {
    "knows": False,
    "opening": "Is par abhi pakki jaankari nahi hai.",
    "claims": [],
    "guidance": "Apne science teacher se baat karo aur sirf official website dekho.",
    "next_question": None,
    "suggest_roadmap": False,
    "spoken_text": "इस पर अभी पक्की जानकारी नहीं है। अपने शिक्षक से बात करो।",
}
ROADMAP_STEPS: list[dict[str, object]] = [
    {"action": "Teacher se NMMS form ke baare mein poocho", "timeframe": "is hafte",
     "cost_inr": None, "source": "C1", "free_now": True},
    {"action": "Portal par registration karo", "timeframe": "form khulne par",
     "cost_inr": None, "source": "C2", "free_now": False},
    {"action": "Roz ek ghanta maths aur mental ability practice karo", "timeframe": "roz",
     "cost_inr": None, "source": None, "free_now": True},
]  # fmt: skip
ROADMAP_DRAFT: dict[str, object] = {
    "goal": "Class 8 mein NMMS scholarship",
    "steps": ROADMAP_STEPS,
    "spoken_text": "आपकी योजना: एनएमएमएस छात्रवृत्ति। पहले शिक्षक से फ़ॉर्म के बारे में पूछो।",
}


def student_ctx(
    text: str = "class 8 mein scholarship milti hai kya",
    language: Language = Language.HINGLISH,
    grade: int | None = 8,
) -> TurnContext:
    profile = user_profile(role=Role.STUDENT, language=language).model_copy(
        update={"grade": grade, "district": "Karauli"}
    )
    return turn_context(text_message(text), profile=profile)


def corpus_retriever(*, relevant: bool = True) -> tuple[Retriever, FakeChunkStore, FakeEmbedder]:
    """Two NMMS chunks from one document and one NSP chunk; similarity above or below 0.80."""
    similarity = 0.9 if relevant else 0.7
    hits = [
        Candidate(UUID(int=1), UUID(int=1001), similarity, keyword_exact=False),
        Candidate(UUID(int=2), UUID(int=1002), similarity - 0.01, keyword_exact=False),
        Candidate(UUID(int=3), UUID(int=1001), similarity - 0.02, keyword_exact=False),
    ]
    store = FakeChunkStore(
        chunks={
            UUID(int=1): stored(1, 1),
            UUID(int=2): stored(2, 2, CorpusTopic.SCHOLARSHIPS),
            UUID(int=3): stored(3, 1),
        },
        vector_hits=hits,
    )
    embedder = FakeEmbedder()
    return (
        Retriever(embedder, store, RetrieverSettings(top_k=5, min_similarity=0.80)),
        store,
        embedder,
    )


def retrieved(number: int) -> RetrievedChunk:
    """Chunk `number` of document `number`, as retrieval returns it."""
    chunk = stored(number, number)
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        title=chunk.title,
        heading_path=chunk.heading_path,
        text=chunk.text,
        source_url=HttpUrl(chunk.source_url),
        retrieved_on=chunk.retrieved_on,
        topic=chunk.topic,
        vector_similarity=0.9,
        keyword_rank=None,
        keyword_exact=False,
        fused_score=0.03,
    )
