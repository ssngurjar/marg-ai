"""Spike F: Muse Image khoj cards and SAM 3.1 activity photos (s02 §4.6a, decisions C6, C7).

Two parts, run separately:

- `cards`: generates khoj-card illustrations with muse-image-1.0 from the s10b §4.13 style
  template for five activity domains, saves them as PNG for checking by eye, and records latency.
- `photos`: runs SAM 3.1 over a folder of test photos described by a manifest CSV
  (`file,kind,phrase,expected_count`; kind is `person`, `no_person` or `count`) and records
  the person check (phrases person/face/hand) and the counts.

Test photos never enter git: they're read from --photos-dir, outside the repo. Findings report
file ids and numbers only. Results go to --out-dir (outside the repo).
"""

import argparse
import asyncio
import base64
import csv
import mimetypes
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, BadRequestError

from .common import require_env, timed, write_results

IMAGE_MODEL = "muse-image-1.0"
SEGMENTATION_MODEL = "sam-3.1"
CARD_SIZE = "1024x1024"
CARDS_PER_DOMAIN = 2
type ReasoningStrength = Literal["high", "low"]
MAX_CONCURRENT_CALLS = 4
CALL_TIMEOUT_S = 120.0
ERROR_LIMIT = 400
PERSON_PHRASES: tuple[str, ...] = ("person", "face", "hand")

type ResultRow = dict[str, str | int | float | None]
type PhotoKind = Literal["person", "no_person", "count"]

# s10b §4.13: a fixed style template; the child's name and the parent's words never go in.
STYLE_TEMPLATE = (
    "A warm Indian folk-art illustration in the style of Madhubani and Warli painting, soft earthy "
    "colours, a rural Indian village setting. Absolutely no text, letters, numbers or writing "
    "anywhere in the image. No realistic faces and no identifiable child: if people appear at all, "
    "they are small stylised folk-art figures seen from behind or far away. No wells, ponds, "
    "rivers or other open water, no fire, no roads or vehicles (s10b d7 hazards). Subject: "
)


@dataclass(frozen=True, slots=True)
class CardSubject:
    domain: str  # CuriosityDomain value (contracts §1)
    activity: str
    scene: str


CARD_SUBJECTS: tuple[CardSubject, ...] = (
    CardSubject(
        "earth_sky",
        "shadow-time",
        "a tree's shadow on a mud courtyard at morning, noon and evening, the sun moving across "
        "the sky",
    ),
    CardSubject(
        "nature_living",
        "leaf-sort",
        "fallen leaves of different shapes and sizes sorted into rows on a charpai",
    ),
    CardSubject(
        "numbers_patterns",
        "stone-count",
        "small smooth stones arranged in a line from smallest to biggest on a mud courtyard",
    ),
    CardSubject(
        "making_building",
        "mud-house",
        "a tiny house built from wet mud and twigs on the ground near a neem tree",
    ),
    CardSubject(
        "earth_sky",
        "moon-watch",
        "the changing shapes of the moon over a village at night, from crescent to full",
    ),
)


def _short(text: str) -> str:
    return text if len(text) <= ERROR_LIMIT else text[:ERROR_LIMIT] + "…"


def _outside_repo(path: Path) -> bool:
    repo_root = Path(__file__).resolve().parents[2]
    resolved = path.resolve()
    return resolved != repo_root and repo_root not in resolved.parents


# --- cards (Muse Image) -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CardRequest:
    subject: CardSubject
    attempt: int
    strength: ReasoningStrength  # Muse Image's `reasoning_strength` extension


@dataclass(frozen=True, slots=True)
class CardResult:
    subject: CardSubject
    attempt: int
    latency_s: float | None
    saved_as: str | None
    error: str | None


async def make_card(
    client: AsyncOpenAI, limit: asyncio.Semaphore, request: CardRequest, out_dir: Path
) -> CardResult:
    subject = request.subject
    attempt = request.attempt
    async with limit:
        try:
            response, timing = await timed(
                subject.activity,
                client.images.generate(
                    model=IMAGE_MODEL,
                    prompt=STYLE_TEMPLATE + subject.scene,
                    n=1,
                    size=CARD_SIZE,
                    response_format="b64_json",
                    output_format="png",
                    extra_body={"reasoning_strength": request.strength},
                ),
            )
        except (APIConnectionError, APIStatusError) as exc:
            return CardResult(subject, attempt, None, None, _short(f"{type(exc).__name__}: {exc}"))
    images = response.data or []
    encoded = images[0].b64_json if images else None
    if encoded is None:
        return CardResult(subject, attempt, timing.seconds, None, "no image in the response")
    path = out_dir / f"card-{request.strength}-{subject.activity}-{attempt}.png"
    path.write_bytes(base64.b64decode(encoded))
    return CardResult(subject, attempt, timing.seconds, path.name, None)


def percentile(samples: Sequence[float], percent: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * percent / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


async def run_cards(
    api_key: str, base_url: str, out_dir: Path, strength: ReasoningStrength
) -> Path:
    limit = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
    async with AsyncOpenAI(
        api_key=api_key, base_url=base_url, timeout=CALL_TIMEOUT_S, max_retries=0
    ) as client:
        jobs = [
            make_card(client, limit, CardRequest(subject, attempt, strength), out_dir)
            for subject in CARD_SUBJECTS
            for attempt in range(1, CARDS_PER_DOMAIN + 1)
        ]
        results = await asyncio.gather(*jobs)
    rows: list[ResultRow] = []
    for result in results:
        rows.append(
            {
                "section": "card",
                "domain": result.subject.domain,
                "activity": result.subject.activity,
                "attempt": result.attempt,
                "latency_s": result.latency_s,
                "saved_as": result.saved_as,
                "error": result.error,
            }
        )
        print(
            f"{result.subject.activity:<12} #{result.attempt} "
            f"{result.latency_s or 0:.1f}s {result.saved_as or result.error}"
        )
    latencies = [result.latency_s for result in results if result.latency_s is not None]
    p50 = percentile(latencies, 50.0)
    p95 = percentile(latencies, 95.0)
    rows.append(
        {
            "section": "card_summary",
            "reasoning_strength": strength,
            "made": len(latencies),
            "p50_s": p50,
            "p95_s": p95,
        }
    )
    print(f"cards made {len(latencies)}/{len(results)}  p50 {p50 or 0:.1f}s  p95 {p95 or 0:.1f}s")
    return write_results(out_dir, f"results-cards-{strength}.json", rows)


# --- photos (SAM 3.1) ---------------------------------------------------------------------------

_BOX_TOKEN = re.compile(r"<\|box;([^|]*)\|>")


@dataclass(frozen=True, slots=True)
class Detection:
    confidence: float | None


def parse_detections(output_text: str) -> list[Detection]:
    """One Detection per box token (s02: "one box and one mask per match"); empty = no match."""
    detections: list[Detection] = []
    for box_fields in _BOX_TOKEN.findall(output_text):
        confidence: float | None = None
        for field in box_fields.split(";"):
            key, _, value = field.partition("=")
            if key == "c":
                confidence = float(value)
        detections.append(Detection(confidence))
    return detections


@dataclass(frozen=True, slots=True)
class PhotoCase:
    file: str
    kind: PhotoKind
    phrase: str | None
    expected_count: int | None


def parse_kind(value: str, file: str) -> PhotoKind:
    match value.strip():
        case "person":
            return "person"
        case "no_person":
            return "no_person"
        case "count":
            return "count"
        case unknown:
            raise SystemExit(f"manifest: unknown kind {unknown!r} for {file}")


def read_manifest(path: Path) -> list[PhotoCase]:
    cases: list[PhotoCase] = []
    with path.open(newline="", encoding="utf-8") as manifest:
        for row in csv.DictReader(manifest):
            kind = parse_kind(row["kind"], row["file"])
            expected = row.get("expected_count", "").strip()
            phrase = row.get("phrase", "").strip()
            cases.append(
                PhotoCase(
                    file=row["file"].strip(),
                    kind=kind,
                    phrase=phrase or None,
                    expected_count=int(expected) if expected else None,
                )
            )
    return cases


def data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


@dataclass(frozen=True, slots=True)
class Segmentation:
    detections: list[Detection]
    latency_s: float | None
    error: str | None


async def segment(
    client: AsyncOpenAI, limit: asyncio.Semaphore, image_url: str, phrase: str
) -> Segmentation:
    async with limit:
        try:
            response, timing = await timed(
                phrase,
                client.responses.create(
                    model=SEGMENTATION_MODEL,
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": phrase},
                                {"type": "input_image", "image_url": image_url, "detail": "auto"},
                            ],
                        }
                    ],
                    metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
                ),
            )
        except BadRequestError:
            raise
        except (APIConnectionError, APIStatusError) as exc:
            return Segmentation([], None, _short(f"{type(exc).__name__}: {exc}"))
    return Segmentation(parse_detections(response.output_text), timing.seconds, None)


async def run_photos(api_key: str, base_url: str, photos_dir: Path, out_dir: Path) -> Path:
    cases = read_manifest(photos_dir / "manifest.csv")
    limit = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
    rows: list[ResultRow] = []
    latencies: list[float] = []
    async with AsyncOpenAI(
        api_key=api_key, base_url=base_url, timeout=CALL_TIMEOUT_S, max_retries=0
    ) as client:
        for case in cases:
            image_url = data_url(photos_dir / case.file)
            phrases = list(PERSON_PHRASES)
            if case.kind == "count" and case.phrase is not None:
                phrases.append(case.phrase)
            segmentations = await asyncio.gather(
                *(segment(client, limit, image_url, phrase) for phrase in phrases)
            )
            for phrase, segmentation in zip(phrases, segmentations, strict=True):
                if segmentation.latency_s is not None:
                    latencies.append(segmentation.latency_s)
                confidences = [d.confidence for d in segmentation.detections if d.confidence]
                rows.append(
                    {
                        "section": "segmentation",
                        "file": case.file,
                        "kind": case.kind,
                        "phrase": phrase,
                        "found": len(segmentation.detections),
                        "max_confidence": max(confidences) if confidences else None,
                        "min_confidence": min(confidences) if confidences else None,
                        "expected_count": case.expected_count if phrase == case.phrase else None,
                        "latency_s": segmentation.latency_s,
                        "error": segmentation.error,
                    }
                )
            found = {
                phrase: len(segmentation.detections)
                for phrase, segmentation in zip(phrases, segmentations, strict=True)
            }
            print(f"{case.file:<24} {case.kind:<9} {found}")
    p50 = percentile(latencies, 50.0)
    p95 = percentile(latencies, 95.0)
    rows.append({"section": "photo_summary", "calls": len(latencies), "p50_s": p50, "p95_s": p95})
    print(f"segmentation calls {len(latencies)}  p50 {p50 or 0:.1f}s  p95 {p95 or 0:.1f}s")
    return write_results(out_dir, "results-photos.json", rows)


# --- main ---------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spike F: Muse Image and SAM 3.1 (s02 §4.6a).")
    parser.add_argument("part", choices=("cards", "photos"))
    parser.add_argument(
        "--reasoning-strength",
        choices=("high", "low"),
        default="high",
        help="Muse Image reasoning strength for cards (the API default is high).",
    )
    parser.add_argument("--out-dir", required=True, type=Path, help="Outside the repo.")
    parser.add_argument(
        "--photos-dir", type=Path, help="Folder with manifest.csv and the test photos (photos)."
    )
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir
    if not _outside_repo(out_dir):
        print(f"refusing to write results inside the repo: {out_dir.resolve()}")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    base_url = require_env("MODEL_API_BASE_URL")
    api_key = require_env("MODEL_API_KEY")
    if args.part == "cards":
        strength: ReasoningStrength = "low" if args.reasoning_strength == "low" else "high"
        path = asyncio.run(run_cards(api_key, base_url, out_dir, strength))
    else:
        photos_dir: Path | None = args.photos_dir
        if photos_dir is None or not (photos_dir / "manifest.csv").is_file():
            print("photos needs --photos-dir with a manifest.csv")
            return 2
        if not _outside_repo(photos_dir):
            print("test photos must live outside the repo")
            return 2
        try:
            path = asyncio.run(run_photos(api_key, base_url, photos_dir, out_dir))
        except BadRequestError as exc:
            print(f"SAM 3.1 rejected the request: HTTP {exc.status_code}: {_short(exc.message)}")
            return 1
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
