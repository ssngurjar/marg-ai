# S11 — RAG: corpus, chunking, embeddings, hybrid retrieval

> **Superseded in part on 2026-10-29:** retrieval is keyword-only (no embeddings, no `/embed`,
> no vector column), query rewriting is on, and relevance follows a new rule. The decisions log
> (2026-10-29) wins wherever this document's embedding and hybrid parts differ.

> **Hackathon build level: Phase 2.** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

## 1. Purpose

Give the mentor and roadmap layers (S12) a **verifiable** knowledge base: official-source
documents about exams, scholarships, sports, entrepreneurship, public service and skilling,
chunked, embedded and retrievable from Hindi, Hinglish or English questions. Every chunk carries
its `source_url`, so every claim in a reply can be cited. Retrieval also says clearly when
**nothing relevant** was found, which drives the honest "I don't know" path. That path is what
stops the mentor from inventing a career fact.

## 2. Read first

- [contracts.md](contracts.md): §1 `EmbedPurpose`, §2.5 `Citation`, §3 `Embedder`, `LanguageModel`, §4 errors, §7 settings
- [data-model.md](data-model.md): `corpus_documents`, `corpus_chunks`
- [corpus/SOURCES.md](../../corpus/SOURCES.md): source list, link status legend, document format
- [plan.md](../../plan.md) §4.5; [CLAUDE.md](../../CLAUDE.md) §1 (no invented facts), §3 (chunker properties), §10 (grounding)
- [s06-voice.md](s06-voice.md): the ml-sidecar, which also serves `/embed`

## 3. Scope

**In:** corpus file format and validator; the curation workflow; the chunker; the embedding
adapter (sidecar `/embed`); idempotent ingestion; hybrid retrieval with a relevance threshold;
the query-rewriting step; the `marg ingest-corpus` CLI; a retrieval eval (recall@k).

**Out:**
- Generating answers from chunks: S12.
- The sidecar service itself (deploy, model loading): S6 owns `services/ml_sidecar/`. S11 adds the `/embed` endpoint to it.
- Search grounding (live web): S12, behind a flag.
- End-to-end answer quality evals: S15. S11 only measures retrieval.

## 4. Design

### 4.1 Corpus file format

One markdown file per source page, at `corpus/<topic>/<slug>.md`. `<topic>` is one of the
folder names: `exams`, `scholarships`, `sports`, `entrepreneurship`, `public_service`,
`skilling`, `exposure_fields`. (`corpus/curriculum/` holds s10's chapter catalogue, which is
**not** corpus: ingestion skips that folder. `content/` at the repo root holds s10b's activity
catalogue and is never read by ingestion.)

```markdown
---
title: NMMS scholarship — eligibility and how to apply
source_url: https://…
retrieved_on: 2026-10-31
topic: scholarships
grades: [8]
keywords: [NMMS, scholarship, class 8, merit]
language: english
---
## What it is
…
## Who can apply
…
## How to apply
…
```

Frontmatter rules, enforced by `app/rag/corpus.py`:

| Key | Type | Rule |
|---|---|---|
| `title` | str | required, 5–120 chars |
| `source_url` | `HttpUrl` | required, `https` only |
| `retrieved_on` | `date` | required, not in the future, not older than 365 days at ingest time (warning at 180) |
| `topic` | Literal of the folder names | required, **must equal the parent folder** |
| `grades` | list[int] | optional, each 1–12; empty or absent means "all grades" |
| `keywords` | list[str] | required, 1–15 items, each non-empty after strip. Exam and scheme names go here (they drive keyword boosting and STT biasing) |
| `language` | Literal["english","hindi"] | optional, default `english` |

Unknown keys are **rejected**, not ignored. The body must be non-empty, contain at least one
`##` heading, and contain no raw HTML. Files under `corpus/` that aren't `*.md`, plus
`corpus/SOURCES.md` itself and everything under `corpus/curriculum/`, are skipped explicitly by
name. Frontmatter is parsed with `pyyaml` (decision B6); an invalid file raises
`CorpusValidationError` (contracts §4).

### 4.2 Curation workflow (human in the loop)

The corpus is content, but it's held to the same standard as code: **every fact comes from the
cited page.**

1. Pick a source from `corpus/SOURCES.md`. Open it in a browser from India if it's marked ⏳ or ⚠️.
2. Claude may **draft** the document from the fetched page text (WebFetch, or text you paste).
   The prompt must say: *only facts stated on this page; quote numbers exactly as written; if
   the page doesn't say it, leave it out.* Claude never writes corpus content from memory.
3. Write it in plain English at a class-10 reading level. Translation happens at reply time (S9).
4. A human reviewer goes through the checklist below, then commits. Commit message:
   `S11: add corpus <topic>/<slug> (source verified <date>)`.

Reviewer checklist (copy into the PR or commit description):
- [ ] Every number, date, amount, age limit and eligibility rule appears on the source page.
- [ ] `retrieved_on` is today's date, and the page was actually opened today.
- [ ] Nothing is stated as current that the page marks as past (old notices, closed windows).
- [ ] No personal data, no names of private individuals.
- [ ] Keywords include every exam or scheme acronym mentioned.
- [ ] Each `##` section stands on its own (it will be retrieved without the others).

Target: **80+ documents** before S12 starts. Coverage priority: scholarships and exams first,
since those are the most common student questions, then sports, skilling, entrepreneurship and public service.

### 4.3 Chunker — `app/rag/chunker.py`

Heading-aware, deterministic, token-budgeted.

- **Token counting:** a fixed approximation, `approx_tokens(text) = ceil(len(text.encode("utf-8")) / 4)`.
  No tokenizer dependency. It over-counts Devanagari, which is the safe direction. Budget:
  `CHUNK_MAX_TOKENS = 350`, overlap `CHUNK_OVERLAP_TOKENS = 50` (module constants, not settings,
  because changing them means re-ingesting everything).
- **Algorithm:**
  1. Split the body into sections on `##` / `###` headings. Each section keeps its heading path
     (`"Who can apply"`).
  2. A section that fits the budget is one chunk.
  3. A larger section is split into paragraphs, then sentences (on `.`, `?`, `!`, `।`, newline),
     packing units greedily up to the budget. The next chunk starts with the trailing units of the
     previous one, up to the overlap budget.
  4. A single sentence larger than the budget is split on whitespace at the budget boundary,
     never mid-grapheme. No `regex` dependency (decision B6): it uses the same `unicodedata` rule as
     s05's `MessageSplitter.split` (never cut before a combining mark, or next to a virama, ZWJ, ZWNJ or
     variation selector).
- **Chunk text as stored and embedded:** `"{title} — {heading path}\n\n{chunk body}"`. The title
  prefix makes a chunk self-describing when it's retrieved alone.

```python
@dataclass(frozen=True)
class ChunkDraft:
    position: int          # 0-based within the document
    heading_path: str
    text: str              # with the title/heading prefix

def chunk_document(title: str, body: str) -> list[ChunkDraft]: ...
def approx_tokens(text: str) -> int: ...
```

### 4.4 Embeddings — `app/providers/embeddings/sidecar.py`

Implements `Embedder` (contracts §3). It calls the sidecar `POST /embed`:

```
POST {SIDECAR_BASE_URL}/embed
Authorization: Bearer {SIDECAR_TOKEN}
{"texts": ["passage: …", …]}           → {"model": "intfloat/multilingual-e5-small", "dimensions": 384, "vectors": [[…], …]}
```

- The adapter adds the e5 prefixes: `EmbedPurpose.QUERY` → `"query: "`, `PASSAGE` → `"passage: "`.
  Callers pass raw text.
- Batches of at most 32 texts. Vectors are L2-normalised in the sidecar
  (`normalize_embeddings=True`), so cosine distance equals `1 - dot product`.
- `dimensions = 384`. The adapter checks every vector's length and that the returned `model`
  matches what's expected. A mismatch raises `ProviderResponseInvalid`.
- Timeout `TIMEOUT_EMBED_S` (proposed default 5 s, requested below). Retry policy from contracts §5.
- Sidecar implementation (added to `services/ml_sidecar/app.py`): sentence-transformers,
  `intfloat/multilingual-e5-small`, loaded once per container, CPU is enough.

### 4.5 Ingestion — `app/rag/ingest.py`

Idempotent, keyed by `path` + `content_sha256` (SHA-256 of the whole file's bytes).

```
load all corpus files → validate every one (fail the whole run on any invalid file, listing all errors)
for each file:
    existing = corpus_documents where path = file.path
    if existing and existing.content_sha256 == file.sha256: skip
    chunk → embed passages (batched) → in ONE transaction:
        upsert corpus_documents (new id if new, same id if changed)
        delete corpus_chunks for that document
        insert new chunks
for each corpus_documents.path not present on disk: delete it (chunks cascade)
report: added / updated / unchanged / deleted counts, chunks written, embedding calls
```

- Validation happens **before** any database write. A single bad file aborts the run with every
  error listed, so a half-updated corpus is impossible.
- Embedding happens before the transaction opens, so a long transaction never waits on the network.
- `--dry-run` validates and chunks, prints what would change, and writes nothing.

### 4.6 Query rewriting (behind `QUERY_REWRITE_ENABLED`, default **off**, decision B9)

The rewriter is built and evaluated, but it only runs when `QUERY_REWRITE_ENABLED=true`. That flag
is switched on only if the retrieval eval (§4.9) shows rewriting improves recall@5 by **≥ 0.05**
over the raw text. With the flag off, retrieval uses the raw user text as the vector query and
`STT_KEYWORDS` / corpus keywords found in the text as the keyword list.

Most corpus documents are in English. Users speak Hindi or Hinglish. e5-small is multilingual,
but cross-lingual retrieval for short spoken questions is noticeably weaker than same-language
retrieval, and the keyword half of the hybrid search can't match `"डॉक्टर"` against `"NEET"` at all.

So retrieval runs a cheap rewriting call first (`app/rag/query_rewrite.py`, prompt `query_rewrite.md.j2`):

```python
class RetrievalQuery(BaseModel):             # structured output
    english_query: str                        # ≤ 200 chars, a standalone question in English
    keywords: list[str]                       # ≤ 8; exam/scheme/field names in canonical English form
    topics: list[Literal["exams","scholarships","sports","entrepreneurship","public_service",
                         "skilling","exposure_fields"]]   # ≤ 3, optional filter hints
```

- Inputs: the user's text, plus the last 2 exchanges (so "uske liye kya karna hoga" resolves the
  "it"), plus the profile's grade.
- Model `MODEL_TEXT`, `reasoning_effort="minimal"`, `max_output_tokens=200`.
- **If the rewrite fails** (timeout, invalid output), retrieval goes ahead with the raw user text
  as the query and no keywords. That's degraded, not failed. Recorded in `turn_steps` under
  `GENERATE` with `outcome=DEGRADED` and `detail="query_rewrite_failed"` (rewriting is part of the
  generate step, not a step of its own).
- `topics` is a **soft** filter: it adds a small score bonus and never excludes anything. A wrong
  guess must not hide the right document.

### 4.7 Hybrid retrieval — `app/rag/retriever.py`

Two candidate lists, fused with reciprocal rank fusion (RRF), then a relevance gate.

```python
class RetrievedChunk(BaseModel):
    chunk_id: UUID
    document_id: UUID
    title: str
    heading_path: str
    text: str
    source_url: HttpUrl
    retrieved_on: date
    vector_similarity: float        # 1 - cosine distance; 0 if only keyword-matched
    keyword_rank: int | None
    fused_score: float

class RetrievalResult(BaseModel):
    query: RetrievalQuery
    chunks: list[RetrievedChunk]    # ≤ RETRIEVAL_TOP_K, best first
    nothing_relevant: bool          # True → S12 must take the don't-know path

class Retriever:
    def __init__(self, embedder: Embedder, chunks: ChunkRepository) -> None: ...
    async def retrieve(self, query: RetrievalQuery, grade: int | None) -> RetrievalResult: ...
```

**Vector candidates** (top 20):

```sql
SELECT c.id, c.document_id, 1 - (c.embedding <=> :query_vec) AS similarity
FROM corpus_chunks c
JOIN corpus_documents d ON d.id = c.document_id
WHERE (:grade IS NULL OR cardinality(d.grades) = 0 OR :grade = ANY(d.grades))
ORDER BY c.embedding <=> :query_vec
LIMIT 20;
```

(`SET LOCAL hnsw.ef_search = 60` inside the transaction for better recall at this corpus size.)

**Keyword candidates** (top 20). Search over the chunk text plus the document's keywords, with an
exact keyword match boosted:

```sql
WITH q AS (SELECT websearch_to_tsquery('simple', :keyword_query) AS tsq)
SELECT c.id, c.document_id,
       ts_rank_cd(c.tsv, q.tsq)
         + CASE WHEN d.keywords && :keywords_upper THEN 1.0 ELSE 0 END AS score
FROM corpus_chunks c
JOIN corpus_documents d ON d.id = c.document_id, q
WHERE (c.tsv @@ q.tsq OR d.keywords && :keywords_upper)
  AND (:grade IS NULL OR cardinality(d.grades) = 0 OR :grade = ANY(d.grades))
ORDER BY score DESC
LIMIT 20;
```

`:keyword_query` is `english_query` plus the keywords joined with `OR`. Keyword matching is
case-insensitive: ingestion stores `corpus_documents.keywords` upper-cased, and `:keywords_upper`
is the rewritten keywords upper-cased.

**Fusion:** `fused = Σ 1 / (60 + rank_in_list)` over the lists the chunk appears in, plus `0.005`
if the document's topic is in `query.topics`. Take the top `RETRIEVAL_TOP_K = 5`. **At most 2
chunks per document**, so one long document can't crowd out the rest.

**Relevance gate:** `nothing_relevant = True` when **both** are true:
- the best `vector_similarity` < `RETRIEVAL_MIN_SIMILARITY` (proposed 0.80 for e5-small, whose
  similarities cluster high; **calibrate on the retrieval eval set before S12**), and
- no candidate matched an exact keyword.

When `nothing_relevant` is true, `chunks` is still returned for telemetry, but S12 must not cite
them or ground an answer on them.

### 4.8 CLI — `marg ingest-corpus`

```
marg ingest-corpus [--dry-run] [--path corpus/scholarships/nmms.md]
marg retrieval-eval [--k 5]
```

Both run locally against `DATABASE_URL`. Ingestion against the deployed database is allowed (the
corpus isn't user data), but it prints the target host and asks for `--yes` when `ENVIRONMENT=prod`.

### 4.9 Retrieval eval — `evals/retrieval/queries.yaml`

A small labelled set, separate from the golden cases (S15), so retrieval can be tuned without
running the whole pipeline.

```yaml
- id: ret-001
  query: "क्लास 8 में कोई स्कॉलरशिप मिलती है क्या"
  grade: 8
  expected_paths: [corpus/scholarships/nmms.md]
- id: ret-002
  query: "Marine biologist kaise bante hain"
  grade: 12
  expect_nothing_relevant: true
```

- About 40 queries: 30 answerable (each with expected documents), 10 deliberately unanswerable.
- Metrics: **recall@5** over answerable queries (an expected document appears among the
  retrieved chunks' documents), and **don't-know precision and recall** over the unanswerable set.
- Targets before S12: recall@5 ≥ 0.85; unanswerable queries flagged `nothing_relevant` ≥ 0.8,
  with ≤ 1 answerable query wrongly flagged.
- Output: a printed table and `evals/results/retrieval-<date>.json`.
- Runs the real rewrite and embedding calls, so it isn't in default `pytest`.

## 5. Interfaces

```python
# app/rag/corpus.py
class CorpusFrontmatter(BaseModel): ...               # §4.1 keys; extra="forbid"
class CorpusFile(BaseModel):
    path: str                                         # repo-relative, posix
    frontmatter: CorpusFrontmatter
    body: str
    content_sha256: str
class CorpusValidationError(DomainError): ...         # requested addition, see §12
def load_corpus(root: Path) -> list[CorpusFile]: ...  # raises CorpusValidationError listing every bad file

# app/rag/chunker.py      — §4.3
# app/rag/query_rewrite.py
class QueryRewriter:
    def __init__(self, llm: LanguageModel, prompts: PromptRegistry, settings: Settings) -> None: ...
    async def rewrite(self, user_text: str, recent: Sequence[Exchange], grade: int | None
                      ) -> tuple[RetrievalQuery, StepUsage] | StepFailure: ...

# app/rag/retriever.py    — §4.7
# app/rag/ingest.py
class IngestReport(BaseModel):
    added: int; updated: int; unchanged: int; deleted: int; chunks_written: int
async def ingest_corpus(root: Path, embedder: Embedder, repo: ChunkRepository, dry_run: bool) -> IngestReport: ...

# app/store/repositories/chunks.py
class ChunkRepository:
    async def get_document_hash(self, path: str) -> str | None: ...
    async def replace_document(self, file: CorpusFile, chunks: Sequence[ChunkDraft],
                               vectors: Sequence[Sequence[float]]) -> None: ...   # one transaction
    async def delete_documents_not_in(self, paths: Collection[str]) -> int: ...
    async def vector_candidates(self, vector: Sequence[float], grade: int | None, limit: int) -> list[VectorCandidate]: ...
    async def keyword_candidates(self, keyword_query: str, keywords: Sequence[str], grade: int | None,
                                 limit: int) -> list[KeywordCandidate]: ...
    async def load_chunks(self, ids: Sequence[UUID]) -> list[RetrievedChunk]: ...
```

`VectorCandidate` and `KeywordCandidate` are private frozen dataclasses in the repository module.

## 6. Data

- **Creates:** `corpus_documents`, `corpus_chunks` (data-model.md), migration `s11_corpus_tables`
  (`CREATE EXTENSION IF NOT EXISTS vector`, both tables, HNSW + GIN indexes).
- `corpus_chunks.tsv` is `GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED`.
- Uses the `heading_path` column on `corpus_chunks` (data-model.md).
- **Reads:** both, at retrieval time. No user data is touched.

## 7. Configuration

Existing: `SIDECAR_BASE_URL`, `SIDECAR_TOKEN`, `MODEL_TEXT`, `DATABASE_URL`, `ENVIRONMENT`.
From contracts §7: `TIMEOUT_EMBED_S` (5.0), `RETRIEVAL_TOP_K` (5), `RETRIEVAL_MIN_SIMILARITY` (0.80),
`QUERY_REWRITE_ENABLED` (false).
Chunk sizes are module constants (§4.3).

## 8. Failure modes

| Failure | Effect on the user | Recorded |
|---|---|---|
| A corpus file is invalid at ingest | None. Ingestion aborts before writing and lists every error | CLI exit code 1 |
| Sidecar `/embed` is down at ingest | None. Ingestion aborts, and the database is unchanged for docs not yet processed (each doc is its own transaction) | CLI error naming the doc |
| Query rewrite fails at turn time | Retrieval uses the raw text, so quality may drop | `GENERATE` step `DEGRADED`, `query_rewrite_failed` |
| Embedding the query fails at turn time | Keyword-only retrieval. If that finds nothing, `nothing_relevant=True` → don't-know path | `DEGRADED`, `query_embed_failed` |
| Database error during retrieval | `StepFailure(GENERATE, INTERNAL)` → `TRY_AGAIN_LATER` | turn failure |
| Embedding dimension or model mismatch | `ProviderResponseInvalid`. Ingestion aborts, or the turn degrades to keyword-only | as above |
| Empty corpus | Every query → `nothing_relevant` → don't-know | `/readyz` warns if `corpus_chunks` is empty (S16) |

## 9. Tests

**Unit (`tests/unit/rag/`):**
- `test_frontmatter_rejects_unknown_key`, `…_missing_source_url`, `…_missing_retrieved_on`,
  `…_http_not_https`, `…_future_retrieved_on`, `…_topic_not_matching_folder`, `…_grade_13`,
  `…_empty_keywords_item`, `…_body_without_heading`, `…_raw_html`. Each asserts
  `CorpusValidationError` with a message naming the file and the key.
- `test_load_corpus_reports_all_invalid_files_not_just_first`.
- `test_load_corpus_skips_sources_md`.
- `test_chunk_prefix_includes_title_and_heading`.
- `test_short_section_is_single_chunk`; `test_devanagari_danda_is_sentence_boundary`.
- `test_embedder_adds_query_prefix` / `…_passage_prefix` (respx fake of `/embed`).
- `test_embedder_batches_at_32`; `test_embedder_rejects_wrong_dimension`
  (`ProviderResponseInvalid`); `test_embedder_rejects_wrong_model`.
- `test_fusion_caps_two_chunks_per_document`; `test_topic_hint_never_excludes`.
- `test_nothing_relevant_when_low_similarity_and_no_keyword`;
  `test_relevant_when_exact_keyword_match_despite_low_similarity`.
- `test_rewrite_failure_falls_back_to_raw_text_degraded`.

**Property (`@pytest.mark.unit`, hypothesis), the invariants from CLAUDE.md §3:**
- Chunks cover the source in order: concatenating chunk bodies with overlaps removed reproduces
  every non-whitespace character of the body, in order.
- Overlap is bounded: the shared prefix/suffix between consecutive chunks is ≤ `CHUNK_OVERLAP_TOKENS`.
- No chunk body exceeds `CHUNK_MAX_TOKENS` (except one unsplittable whitespace-free run, which must equal that run).
- Deterministic: `chunk_document(t, b) == chunk_document(t, b)`, including across processes (no dict-order dependence).
- No chunk is empty or whitespace-only.
- Strategies mix Devanagari, romanised Hindi, English, emoji and headings.
- RRF fusion is order-independent: shuffling the input candidate lists doesn't change the fused ranking.

**Negative:** empty query string → `nothing_relevant=True` without calling the embedder;
a query of only whitespace or emoji → same; grade 0 → `InvalidProfileValue` at the boundary;
`--path` outside `corpus/` → CLI error.

**Integration (`-m integration`, docker-compose.test.yml with pgvector):**
- `test_ingest_is_idempotent`: two runs, and the second reports all unchanged with zero embed calls (fake embedder counting calls).
- `test_changed_file_replaces_chunks_in_one_transaction`: kill mid-run (raise inside), and the old chunks remain.
- `test_removed_file_deletes_document_and_chunks`.
- `test_vector_and_keyword_sql_with_grade_filter`: a grade-8 document isn't returned for grade 11, and an all-grades document is.
- `test_keyword_boost_finds_acronym` ("NMMS" finds the NMMS doc even with an unrelated vector).
- `test_user_deletion_does_not_touch_corpus`.

## 10. Exit check

1. `marg ingest-corpus` on 80+ real, reviewed documents: the report shows everything added.
   Running it again shows everything unchanged.
2. `marg retrieval-eval` prints recall@5 ≥ 0.85 and don't-know flags meeting §4.9, and the
   result file is committed.
3. From a Python shell, `retrieve()` for "क्लास 8 में कोई स्कॉलरशिप मिलती है क्या" returns the
   NMMS chunks with their `source_url`, and "Marine biologist kaise bante hain" returns
   `nothing_relevant=True`.
4. The verification loop is green, including integration tests.

Golden cases that depend on S11 (checked end to end in S12/S15): student-mentor-002, -004,
-005, -008, -010; roadmap-001, -003; multiturn-003.

## 11. Open questions

1. ~~**Query rewriting**~~ **Resolved (decision B9):** behind `QUERY_REWRITE_ENABLED`, default off;
   switched on only if the retrieval eval shows ≥ +0.05 recall@5.
2. **Similarity threshold 0.80** is a starting guess. Calibrate it on the eval set before S12.
3. **Hindi-language corpus docs:** allowed (`language: hindi`), but recommend English-only for
   the MVP so reviewers can verify against mostly English official pages.
4. ~~**`regex` package**~~ **Resolved (decision B6):** not added; grapheme-safe splitting uses
   `unicodedata` as in s05's `MessageSplitter.split`.

## 12. Contract changes (resolved 2026-10-25)

- `corpus_chunks.heading_path`, `corpus_documents.language`, upper-cased `keywords`: **applied** (data-model.md).
- `CorpusValidationError`: **applied** (contracts §4), as a direct `MargError` subclass shared with
  the curriculum and activity catalogues.
- `TIMEOUT_EMBED_S`, `RETRIEVAL_TOP_K`, `RETRIEVAL_MIN_SIMILARITY`: **applied** (contracts §7),
  plus `QUERY_REWRITE_ENABLED` (decision B9).
- `RetrievalQuery`, `RetrievedChunk`, `RetrievalResult`: **applied** (contracts §2.7).

## 13. Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-25 | Query rewriting behind `QUERY_REWRITE_ENABLED` (default off, B9); no `regex`, `pyyaml` for frontmatter (B6); `corpus/curriculum/` skipped, `content/` isn't corpus; requested columns and settings applied | Consolidation against the updated foundation docs | owner (defaults) |
| 2026-10-28 | **Retrieval built (§4.1–§4.7).** Build choices: (1) `/embed` lives in the `marg-ai-tts` voice server (it already has torch and transformers; mean-pooled, L2-normalised e5-small, CPU), so no `sentence-transformers` and no new dependency; (2) no `pgvector` Python package either: vectors go in and are compared as SQL `CAST(:v AS vector)` literals, and `VectorColumn` declares the column for alembic; (3) `RankFusion` is a pure domain rule (property-tested: swapping the lists never changes the result); (4) `QueryRewriter` lives in `app/layers/` (the layering rule doesn't let `rag/` import prompts); (5) without rewriting, the keyword list is the corpus keywords found in the question as whole words, and the keyword query ORs every word; (6) first similarities from e5-small cluster 0.75–0.87 (a Hindi NMMS question 0.87, an unanswerable one 0.79), so `RETRIEVAL_MIN_SIMILARITY` 0.80 stays until the eval calibrates it | S11 build | pending owner review |
| 2026-10-28 | **First calibration on the real corpus** (50 documents, 235 chunks; ingestion re-run reports all unchanged): at 0.80, 10 of 11 sample questions behave right. NMMS (Hindi) 0.861, "nmms ka form" 0.842 + exact keyword, Sainik 0.861 + exact, ISRO 0.834 + exact, SC college scholarship 0.879 + exact; marine biologist 0.786, pilot 0.790, a song 0.789, cricket 0.782 → nothing relevant. Miss: "kabaddi khelna hai, sarkar se madad" 0.795 → don't-know (Khelo India not reached). Threshold kept at 0.80 (a miss is an honest don't-know, never a wrong fact); the full retrieval eval (§4.9) comes with S15 | S11 calibration | pending owner review |
| 2026-10-29 | **Retrieval is keyword-only; the embedding model is removed.** multilingual-e5-small isn't a Meta model, and every model Marg calls must be (organisers). The Model API has no embeddings; Meta's LASER (BSD) was the alternative, kept as the next step if mentor quality drops. Changes: migration `s11_keyword_retrieval` drops `corpus_chunks.embedding` and its HNSW index and rebuilds `tsv` with the `english` configuration over the heading and the text (stemming, stop-words); `/embed`, `Embedder`, `EmbedPurpose`, `EMBED_MODEL`, `TIMEOUT_EMBED_S` and `RETRIEVAL_MIN_SIMILARITY` are gone. **Query rewriting is on by default** (`QUERY_REWRITE_ENABLED=true`, was off under B9): the corpus is English, so a Hindi question must become English terms first; its `max_output_tokens` went from 300 to 1200, because reasoning shares that budget and 5 of 22 rewrites were cut off. **Relevance rule** (`nothing_relevant`): relevant when a name the rewrite gave exactly matches a document keyword, or the best text rank is at least `RETRIEVAL_MIN_TEXT_RANK` (1.3). Names found in the question by `keywords_in` still boost the order but don't count, because generic corpus keywords ("class 12", "college") matched unrelated questions. Calibrated on 22 questions (13 the corpus answers, 9 it doesn't): 10 of 13 found, 0 of 9 answered wrongly; raw text rank alone couldn't separate them (0.6–1.2 on both sides). **Measured:** student_mentor.yaml, three runs each, hybrid 36%, 36%, 45% (grounding 3.45) against keyword-only 55%, 45%, 55% (grounding 3.91–4.09), so LASER isn't needed | Organisers' ruling, 2026-10-29; owner chose "keyword first, LASER if it drops" | owner |
