"""Spike E: Model API structured output and basics (s02 §4.6).

Measures with real calls against MODEL_API_BASE_URL:

- the models the key can use;
- for four strict schemas (router, exposure bridge, mentor answer, parent reflection), the
  schema-valid rate over 30 calls each, latency, usage, and whether the reply keeps the user's
  script (Devanagari for Hindi, Roman for Hinglish);
- the same schemas at reasoning effort `minimal` and `low`, on the same inputs, for latency;
- the S5 repair turn (s05 §4.1 wording) for a semantic problem and for invalid JSON;
- the 400 body for a recursive schema, and the rate-limit headers of a completion;
- optionally, the parent-reflection schema on Muse Spark Open (s10b §4.8), if
  OPEN_MODEL_BASE_URL and OPEN_MODEL_API_KEY are set.

Inputs are copied verbatim from evals/golden/*.yaml (checked when this script was written).
Writes results.json to --out-dir (outside the repo) and prints a summary; the findings doc is
written by hand from that in docs/spikes/structured-output.md.
"""

import argparse
import asyncio
import json
import os
import re
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from openai import (
    APIConnectionError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    omit,
)
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .common import require_env, timed, write_results

MODEL = "muse-spark-1.3"  # s02 §4.6; never a "-contributor" variant (CLAUDE.md §10)
CALLS_PER_SCHEMA = 30
EFFORT_SWEEP_CALLS = 10  # per schema and per effort level, on the first inputs of the main run
REPAIR_TRIES = 10
JSON_REPAIR_TRIES = 3
OPEN_MODEL_CALLS = 10
MAX_CONCURRENT_CALLS = 4
CALL_TIMEOUT_S = 60.0
TEMPERATURE = 0.0
ERROR_LIMIT = 400
RESULTS_NAME = "results.json"
OPEN_MODEL_RESULTS_NAME = "results-open-model.json"

# A reply "keeps Devanagari" when at least this share of its letters are Devanagari, and "stays
# Roman" when at most this share are. Exam names (NEET, NMMS) are legitimately Roman in Hindi.
DEVANAGARI_KEPT_SHARE = 0.6
ROMAN_KEPT_SHARE = 0.05
HINGLISH_MARKERS_FOR_FIXED = 3

type Register = Literal["hindi", "hinglish"]
type Effort = Literal["default", "minimal", "low"]
type ResultRow = dict[str, str | int | float | None]


# --- inputs (verbatim from evals/golden) ------------------------------------------------------


class Route(StrEnum):
    MENTOR = "mentor"
    EXPOSURE = "exposure"
    ROADMAP = "roadmap"
    OFF_TOPIC = "off_topic"


@dataclass(frozen=True, slots=True)
class GoldenInput:
    case_id: str
    text: str
    register: Register
    context: str | None = None  # e.g. the open activity and child's age, for the reflection
    expected_route: Route | None = None


ROUTER_INPUTS: tuple[GoldenInput, ...] = (
    GoldenInput(
        "student-mentor-001",
        "Didi 10th ke baad kya lena chahiye, science ya arts, papa bolte hain science lo",
        "hinglish",
        expected_route=Route.MENTOR,
    ),
    GoldenInput(
        "student-mentor-002",
        "मुझे डॉक्टर बनना है, उसके लिए कौन सा एग्जाम देना होगा?",
        "hindi",
        expected_route=Route.MENTOR,
    ),
    GoldenInput(
        "teacher-exposure-001",
        "Kal class 8 mein Force and Pressure chapter padhana hai, bacche bore ho jaate hain,"
        " kuch interesting batao",
        "hinglish",
        expected_route=Route.EXPOSURE,
    ),
    GoldenInput(
        "teacher-exposure-002",
        "कक्षा दस में लोकतंत्र और विविधता पढ़ा रहा हूँ, बच्चों को इससे आगे क्या करियर दिखा सकते हैं?",
        "hindi",
        expected_route=Route.EXPOSURE,
    ),
    GoldenInput(
        "roadmap-001",
        "Doctor banna hai, mujhe step by step plan bana do",
        "hinglish",
        expected_route=Route.ROADMAP,
    ),
    GoldenInput("roadmap-004", "मैंने NMMS का फॉर्म भर दिया", "hindi", expected_route=Route.ROADMAP),
    GoldenInput(
        "off-topic-001", "Koi naya gaana sunao", "hinglish", expected_route=Route.OFF_TOPIC
    ),
    GoldenInput(
        "off-topic-002",
        "मेरा पूरा निबंध लिख दो 'मेरा गाँव' पर",
        "hindi",
        expected_route=Route.OFF_TOPIC,
    ),
    GoldenInput(
        "translation-001",
        "Engineer aur scientist mein kya fark hai?",
        "hinglish",
        expected_route=Route.MENTOR,
    ),
    GoldenInput("translation-002", "वैज्ञानिक कैसे बनते हैं?", "hindi", expected_route=Route.MENTOR),
)

EXPOSURE_INPUTS: tuple[GoldenInput, ...] = (
    GoldenInput(
        "teacher-exposure-001",
        "Kal class 8 mein Force and Pressure chapter padhana hai, bacche bore ho jaate hain,"
        " kuch interesting batao",
        "hinglish",
    ),
    GoldenInput(
        "teacher-exposure-002",
        "कक्षा दस में लोकतंत्र और विविधता पढ़ा रहा हूँ, बच्चों को इससे आगे क्या करियर दिखा सकते हैं?",
        "hindi",
    ),
    GoldenInput(
        "teacher-exposure-003",
        "percentage wala chapter hai class 7 ka, isko real life se kaise jodun",
        "hinglish",
    ),
    GoldenInput(
        "teacher-exposure-004",
        "Cell - the fundamental unit of life chapter ko sports se jod sakte hain kya?"
        " bacchon ko kabaddi pasand hai",
        "hinglish",
    ),
    GoldenInput("teacher-exposure-005", "बच्चों को कुछ नया सिखाना है", "hindi"),
    GoldenInput(
        "teacher-exposure-007",
        "Kal bacchon ko solar panel ke baare mein batana hai, gaon mein naye lage hain",
        "hinglish",
    ),
    GoldenInput(
        "teacher-exposure-008",
        "Economics padhne wale bacche kya kya ban sakte hain? sirf CA aur banking nahi",
        "hinglish",
    ),
)

MENTOR_INPUTS: tuple[GoldenInput, ...] = (
    GoldenInput(
        "student-mentor-001",
        "Didi 10th ke baad kya lena chahiye, science ya arts, papa bolte hain science lo",
        "hinglish",
    ),
    GoldenInput("student-mentor-002", "मुझे डॉक्टर बनना है, उसके लिए कौन सा एग्जाम देना होगा?", "hindi"),
    GoldenInput(
        "student-mentor-003",
        "Mujhe India ke liye cricket khelna hai, gaon mein koi academy nahi hai",
        "hinglish",
    ),
    GoldenInput(
        "student-mentor-004",
        "Marine biologist kaise bante hain? hamare yahan samundar nahi hai",
        "hinglish",
    ),
    GoldenInput(
        "student-mentor-005",
        "क्लास 8 में कोई स्कॉलरशिप मिलती है क्या? घर में पैसे की दिक्कत है",
        "hindi",
    ),
    GoldenInput(
        "student-mentor-006",
        "Main aage padhna chahti hoon par ghar wale shaadi ki baat kar rahe hain",
        "hinglish",
    ),
    GoldenInput(
        "student-mentor-007",
        "Gram sabha mein sadak ke baare mein baat hui, aise kaam karne wale log kya padhte hain?",
        "hinglish",
    ),
    GoldenInput(
        "student-mentor-008",
        "Mujhe naukri nahi apna kaam karna hai, dairy ka, kahan se shuru karun",
        "hinglish",
    ),
    GoldenInput("student-mentor-009", "मैं मैथ्स में फेल हो गया, अब मेरा कुछ नहीं हो सकता", "hindi"),
    GoldenInput("translation-001", "Engineer aur scientist mein kya fark hai?", "hinglish"),
)

# The parent journey is the MVP (mvp-scope.md); these are its report-back cases (s10b §4.8).
REFLECTION_INPUTS: tuple[GoldenInput, ...] = (
    GoldenInput(
        "parent-journey-002",
        "Munni ne kaha parchhai isliye ghoomti hai kyunki suraj chalta hai",
        "hinglish",
        context="Open activity: shadow-time. Child: Munni, age 5.",
    ),
    GoldenInput(
        "parent-journey-003",
        "बच्चे ने मना कर दिया, उसका मन नहीं था",
        "hindi",
        context="Open activity: leaf-sort. Child: age 4, no nickname.",
    ),
    GoldenInput(
        "parent-journey-010",
        "Munni ne patte ikatthe kiye",
        "hinglish",
        context="Open activity: leaf-sort. Child: Munni, age 5.",
    ),
    GoldenInput(
        "parent-journey-012",
        "Munni ne kaha parchhai suraj ke saath ghoomti hai, aur shaam ko lambi ho jaati hai"
        " kyunki suraj neeche hota hai",
        "hinglish",
        context="Open activity: shadow-time. Child: Munni, age 5.",
    ),
    GoldenInput(
        "parent-journey-013",
        "Munni poochh rahi hai, chaand roz shape kyun badalta hai?",
        "hinglish",
        context="No open activity; the parent reports a curiosity moment. Child: Munni, age 6.",
    ),
)


# --- output schemas -----------------------------------------------------------------------------


class RouterOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: Route
    reason: str


class ExposureField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    connection: str
    careers: list[str]
    examples: list[str]


class ExposureBridge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter: str
    fields: list[ExposureField]
    activity: str


class MentorAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    key_points: list[str]
    follow_up: str | None
    source_note: str | None


class ParentReflection(BaseModel):
    """s10b §4.8, including its length limits, so the spike shows whether they hold."""

    model_config = ConfigDict(extra="forbid")

    praise_specific: str = Field(max_length=220)
    next_question: str = Field(max_length=160)
    parent_tip: str = Field(max_length=160)
    summary_for_record: str = Field(max_length=200)


class RecursiveNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    child: "RecursiveNode | None"


RecursiveNode.model_rebuild()


SAME_REGISTER = "Write every text field in the same language and script as the user's message."

ROUTER_SYSTEM = (
    "You route a user's message to one team: mentor (questions about studies and careers), "
    "exposure (a teacher asking how to connect a chapter to the real world), roadmap (a student "
    "asking for a step-by-step plan, or reporting progress on one), or off_topic (anything else). "
    "Reply with the route and one short reason. " + SAME_REGISTER
)
EXPOSURE_SYSTEM = (
    "You build an exposure bridge for a teacher: connect their chapter to exactly three "
    "real-world fields, each with careers and examples, plus one classroom activity. "
    + SAME_REGISTER
)
MENTOR_SYSTEM = "You answer a student's question briefly, with key points. " + SAME_REGISTER
REFLECTION_SYSTEM = (
    "A parent is telling you what their young child said or did during today's activity. "
    "Praise the specific idea the child had, ask exactly one question that extends it, give the "
    "parent one short tip about how children learn, and write a neutral third-person summary. "
    "Never correct the child harshly, never label the child, never mention careers. "
    + SAME_REGISTER
)
# Used only to produce a reply in the wrong register, as the premise of the repair test.
ENGLISH_ONLY_SYSTEM = "You answer a student's question briefly, with key points. Reply in English."

# s05 §4.1 repair message, with a semantic problem in place of schema errors.
SEMANTIC_REPAIR_MESSAGE = (
    "Your previous reply did not pass validation. Errors: register: expected hinglish, got "
    "english. Reply again with only the corrected JSON object."
)
JSON_REPAIR_MESSAGE = (
    "Your previous reply did not pass validation. Errors: (): Invalid JSON: EOF while parsing a "
    "list. Reply again with only the corrected JSON object."
)
BROKEN_JSON = (
    '{"answer": "NEET-UG ke liye NCERT se taiyaari karo", "key_points": ["NCERT padho", "mock'
)


@dataclass(frozen=True, slots=True)
class SchemaSpec:
    name: str
    output_model: type[BaseModel]
    system_prompt: str
    inputs: tuple[GoldenInput, ...]


SCHEMAS: tuple[SchemaSpec, ...] = (
    SchemaSpec("router", RouterOutput, ROUTER_SYSTEM, ROUTER_INPUTS),
    SchemaSpec("exposure_bridge", ExposureBridge, EXPOSURE_SYSTEM, EXPOSURE_INPUTS),
    SchemaSpec("mentor_answer", MentorAnswer, MENTOR_SYSTEM, MENTOR_INPUTS),
    SchemaSpec("parent_reflection", ParentReflection, REFLECTION_SYSTEM, REFLECTION_INPUTS),
)


# --- strict-subset check (s02 §4.6 step 2) ------------------------------------------------------


def check_strict_subset(schema: Mapping[str, object], name: str) -> list[str]:
    """Object root, no allOf/oneOf, every object closed, every property required."""
    violations: list[str] = []
    if schema.get("type") != "object":
        violations.append(f"{name}: root schema must be an object")
    violations.extend(_node_violations(schema, name))
    return violations


def _node_violations(node: Mapping[str, object], path: str) -> list[str]:
    violations = [
        f"{path}: {keyword} is not allowed in strict mode"
        for keyword in ("allOf", "oneOf")
        if keyword in node
    ]
    properties = node.get("properties")
    if isinstance(properties, Mapping):
        if node.get("additionalProperties") is not False:
            violations.append(f"{path}: object must set additionalProperties to false")
        required = node.get("required")
        required_names = set(required) if isinstance(required, list) else set()
        for property_name, property_schema in properties.items():
            if property_name not in required_names:
                violations.append(f"{path}: property {property_name!r} is missing from required")
            if isinstance(property_schema, Mapping):
                violations.extend(_node_violations(property_schema, f"{path}.{property_name}"))
    for child_path, child in _child_schemas(node, path):
        violations.extend(_node_violations(child, child_path))
    return violations


def _child_schemas(node: Mapping[str, object], path: str) -> list[tuple[str, Mapping[str, object]]]:
    children: list[tuple[str, Mapping[str, object]]] = []
    items = node.get("items")
    if isinstance(items, Mapping):
        children.append((f"{path}[]", items))
    branches = node.get("anyOf")
    if isinstance(branches, list):
        for index, branch in enumerate(branches):
            if isinstance(branch, Mapping):
                children.append((f"{path}.anyOf[{index}]", branch))
    definitions = node.get("$defs")
    if isinstance(definitions, Mapping):
        for definition_name, definition in definitions.items():
            if isinstance(definition, Mapping):
                children.append((f"{path}.$defs.{definition_name}", definition))
    return children


# --- script and register signals ---------------------------------------------------------------

_DEVANAGARI_LETTER = re.compile("[ऀ-ॿ]")
_ROMAN_LETTER = re.compile("[A-Za-z]")
_HINGLISH_MARKER = re.compile(
    r"\b(hai|hain|kya|kaise|kyon|kyun|liye|mein|nahi|nahin|chahiye|sakta|sakte|sakti"
    r"|bahut|accha|acchi|acche|wala|wale|wali|banne|banna|karna|karne|karo"
    r"|hota|hote|hoti|hoga|hogi|raha|rahi|rahe|apna|apne|apni|aap|aapko|tum|tumhe"
    r"|mujhe|hamara|hamari|isliye|lekin|kyunki|zaroor|toh|bhi|aur|ke|ki|ko|se)\b"
)


def _string_values(value: object) -> list[str]:
    """Every string inside a decoded JSON value; keys are left out (they're always English)."""
    if isinstance(value, str):
        return [value]
    found: list[str] = []
    if isinstance(value, list):
        for item in value:
            found.extend(_string_values(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_string_values(item))
    return found


def reply_text(content: str) -> str | None:
    """The reply's text fields joined, or None if the content isn't JSON."""
    try:
        decoded: object = json.loads(content)
    except json.JSONDecodeError:
        return None
    return " ".join(_string_values(decoded))


def devanagari_share(text: str) -> float | None:
    """Devanagari letters over Devanagari + Roman letters; None for a reply with neither."""
    devanagari = len(_DEVANAGARI_LETTER.findall(text))
    roman = len(_ROMAN_LETTER.findall(text))
    if devanagari + roman == 0:
        return None
    return devanagari / (devanagari + roman)


def kept_script(register: Register, share: float | None) -> bool:
    if share is None:
        return False
    if register == "hindi":
        return share >= DEVANAGARI_KEPT_SHARE
    return share <= ROMAN_KEPT_SHARE


def hinglish_marker_count(text: str) -> int:
    return len(set(_HINGLISH_MARKER.findall(text.lower())))


def percentile(samples: Sequence[float], percent: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * percent / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _short(text: str) -> str:
    return text if len(text) <= ERROR_LIMIT else text[:ERROR_LIMIT] + "…"


# --- one call -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CallRequest:
    model: str
    messages: list[ChatCompletionMessageParam]
    schema_name: str
    schema: Mapping[str, object]
    effort: Effort = "default"


@dataclass(frozen=True, slots=True)
class CallResult:
    content: str | None
    latency_s: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    rate_limit_headers: Mapping[str, str]
    error: str | None


def _response_format(name: str, schema: Mapping[str, object]) -> ResponseFormatJSONSchema:
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "schema": dict(schema), "strict": True},
    }


def _failed(error: str) -> CallResult:
    return CallResult(
        content=None,
        latency_s=None,
        prompt_tokens=None,
        completion_tokens=None,
        reasoning_tokens=None,
        rate_limit_headers={},
        error=error,
    )


async def call_model(
    client: AsyncOpenAI, limit: asyncio.Semaphore, request: CallRequest
) -> CallResult:
    """One attempt, no SDK retries. BadRequestError propagates: a 400 is a finding, not noise."""
    async with limit:
        try:
            raw, timing = await timed(
                request.schema_name,
                client.chat.completions.with_raw_response.create(
                    model=request.model,
                    messages=request.messages,
                    response_format=_response_format(request.schema_name, request.schema),
                    temperature=TEMPERATURE,
                    reasoning_effort=omit if request.effort == "default" else request.effort,
                ),
            )
        except (AuthenticationError, BadRequestError):
            raise
        except (APIConnectionError, APIStatusError) as exc:
            return _failed(_short(f"{type(exc).__name__}: {exc}"))
    completion = raw.parse()
    rate_limit_headers = {
        name: value
        for name, value in raw.headers.items()
        if "ratelimit" in name.lower() or name.lower() == "retry-after"
    }
    if not completion.choices:
        return _failed("empty choices")
    message = completion.choices[0].message
    usage = completion.usage
    details = usage.completion_tokens_details if usage is not None else None
    return CallResult(
        content=message.content,
        latency_s=timing.seconds,
        prompt_tokens=usage.prompt_tokens if usage is not None else None,
        completion_tokens=usage.completion_tokens if usage is not None else None,
        reasoning_tokens=details.reasoning_tokens if details is not None else None,
        rate_limit_headers=rate_limit_headers,
        error=None if message.content else f"empty content (refusal: {message.refusal})",
    )


# --- the schema runs ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SchemaCall:
    schema: str
    model: str
    effort: Effort
    attempt: int
    golden: GoldenInput
    result: CallResult
    valid: bool
    validation_error: str | None
    script_share: float | None
    route: str | None


def _user_message(golden: GoldenInput) -> str:
    if golden.context is None:
        return golden.text
    return f"{golden.context}\nParent's message: {golden.text}"


@dataclass(frozen=True, slots=True)
class SchemaRun:
    """One schema on one model at one reasoning effort."""

    spec: SchemaSpec
    model: str
    effort: Effort


def _judge(run: SchemaRun, attempt: int, golden: GoldenInput, result: CallResult) -> SchemaCall:
    spec = run.spec
    valid = False
    validation_error: str | None = None
    route: str | None = None
    share: float | None = None
    if result.content is not None:
        try:
            parsed = spec.output_model.model_validate_json(result.content)
        except ValidationError as exc:
            validation_error = _short(str(exc))
        else:
            valid = True
            if isinstance(parsed, RouterOutput):
                route = parsed.route.value
        text = reply_text(result.content)
        share = devanagari_share(text) if text is not None else None
    return SchemaCall(
        schema=spec.name,
        model=run.model,
        effort=run.effort,
        attempt=attempt,
        golden=golden,
        result=result,
        valid=valid,
        validation_error=validation_error,
        script_share=share,
        route=route,
    )


async def run_schema(
    client: AsyncOpenAI, limit: asyncio.Semaphore, run: SchemaRun, calls: int
) -> list[SchemaCall]:
    """`calls` calls, cycling through the spec's inputs, run concurrently under `limit`."""
    spec = run.spec
    schema = spec.output_model.model_json_schema()
    inputs = [spec.inputs[index % len(spec.inputs)] for index in range(calls)]

    async def one(attempt: int, golden: GoldenInput) -> SchemaCall:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": spec.system_prompt},
            {"role": "user", "content": _user_message(golden)},
        ]
        request = CallRequest(run.model, messages, spec.name, schema, run.effort)
        return _judge(run, attempt, golden, await call_model(client, limit, request))

    return await asyncio.gather(
        *(one(attempt, golden) for attempt, golden in enumerate(inputs, start=1))
    )


def call_row(call: SchemaCall) -> ResultRow:
    return {
        "section": "call",
        "schema": call.schema,
        "model": call.model,
        "effort": call.effort,
        "attempt": call.attempt,
        "input_id": call.golden.case_id,
        "register": call.golden.register,
        "valid": int(call.valid),
        "validation_error": call.validation_error,
        "latency_s": call.result.latency_s,
        "prompt_tokens": call.result.prompt_tokens,
        "completion_tokens": call.result.completion_tokens,
        "reasoning_tokens": call.result.reasoning_tokens,
        "script_share": call.script_share,
        "kept_script": int(kept_script(call.golden.register, call.script_share)),
        "route_expected": call.golden.expected_route.value if call.golden.expected_route else None,
        "route_got": call.route,
        "content": call.result.content,
        "error": call.result.error,
    }


@dataclass(frozen=True, slots=True)
class SchemaSummary:
    schema: str
    model: str
    effort: Effort
    calls: int
    valid: int
    kept_script: int
    p50_s: float | None
    p95_s: float | None
    mean_prompt_tokens: float | None
    mean_completion_tokens: float | None
    route_correct: int | None


def summarise(calls: Sequence[SchemaCall]) -> SchemaSummary:
    first = calls[0]
    latencies = [call.result.latency_s for call in calls if call.result.latency_s is not None]
    prompt_tokens = [call.result.prompt_tokens for call in calls if call.result.prompt_tokens]
    completion_tokens = [
        call.result.completion_tokens for call in calls if call.result.completion_tokens
    ]
    routed = [call for call in calls if call.golden.expected_route is not None]
    route_correct = sum(
        1
        for call in routed
        if call.golden.expected_route and call.route == call.golden.expected_route.value
    )
    return SchemaSummary(
        schema=first.schema,
        model=first.model,
        effort=first.effort,
        calls=len(calls),
        valid=sum(1 for call in calls if call.valid),
        kept_script=sum(
            1 for call in calls if kept_script(call.golden.register, call.script_share)
        ),
        p50_s=percentile(latencies, 50.0),
        p95_s=percentile(latencies, 95.0),
        mean_prompt_tokens=sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else None,
        mean_completion_tokens=(
            sum(completion_tokens) / len(completion_tokens) if completion_tokens else None
        ),
        route_correct=route_correct if routed else None,
    )


def summary_row(summary: SchemaSummary) -> ResultRow:
    return {
        "section": "schema_summary",
        "schema": summary.schema,
        "model": summary.model,
        "effort": summary.effort,
        "calls": summary.calls,
        "valid": summary.valid,
        "kept_script": summary.kept_script,
        "p50_s": summary.p50_s,
        "p95_s": summary.p95_s,
        "mean_prompt_tokens": summary.mean_prompt_tokens,
        "mean_completion_tokens": summary.mean_completion_tokens,
        "route_correct": summary.route_correct,
    }


def _seconds(value: float | None) -> str:
    return f"{value:.2f}s" if value is not None else "n/a"


def print_summary(summary: SchemaSummary) -> None:
    route = (
        f" route {summary.route_correct}/{summary.calls}"
        if summary.route_correct is not None
        else ""
    )
    print(
        f"{summary.schema:<18} {summary.model:<28} {summary.effort:<8} "
        f"valid {summary.valid}/{summary.calls}  script {summary.kept_script}/{summary.calls}  "
        f"p50 {_seconds(summary.p50_s)}  p95 {_seconds(summary.p95_s)}{route}"
    )


# --- repair (s05 §4.1) --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RepairTry:
    attempt: int
    golden: GoldenInput
    premise_ok: bool  # the first reply was valid JSON in English, so there is something to repair
    first: CallResult
    repaired: CallResult | None
    fixed: bool
    repaired_markers: int | None
    repaired_share: float | None


async def semantic_repair_try(
    client: AsyncOpenAI, limit: asyncio.Semaphore, attempt: int, golden: GoldenInput
) -> RepairTry:
    """Get an English reply (the "wrong register" premise), then run S5's repair turn on it
    under the real same-register system prompt, as S5 would."""
    schema = MentorAnswer.model_json_schema()
    english_messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": ENGLISH_ONLY_SYSTEM},
        {"role": "user", "content": golden.text},
    ]
    first = await call_model(
        client, limit, CallRequest(MODEL, english_messages, "mentor_answer", schema)
    )
    first_text = reply_text(first.content) if first.content is not None else None
    premise_ok = first_text is not None and hinglish_marker_count(first_text) == 0
    if not premise_ok or first.content is None:
        return RepairTry(
            attempt=attempt,
            golden=golden,
            premise_ok=False,
            first=first,
            repaired=None,
            fixed=False,
            repaired_markers=None,
            repaired_share=None,
        )
    repair_messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": MENTOR_SYSTEM},
        {"role": "user", "content": golden.text},
        {"role": "assistant", "content": first.content},
        {"role": "user", "content": SEMANTIC_REPAIR_MESSAGE},
    ]
    repaired = await call_model(
        client, limit, CallRequest(MODEL, repair_messages, "mentor_answer", schema)
    )
    repaired_text = reply_text(repaired.content) if repaired.content is not None else None
    markers = hinglish_marker_count(repaired_text) if repaired_text is not None else None
    share = devanagari_share(repaired_text) if repaired_text is not None else None
    fixed = (
        markers is not None
        and markers >= HINGLISH_MARKERS_FOR_FIXED
        and kept_script("hinglish", share)
        and _is_valid(MentorAnswer, repaired.content)
    )
    return RepairTry(
        attempt=attempt,
        golden=golden,
        premise_ok=True,
        first=first,
        repaired=repaired,
        fixed=fixed,
        repaired_markers=markers,
        repaired_share=share,
    )


def _is_valid(model: type[BaseModel], content: str | None) -> bool:
    if content is None:
        return False
    try:
        model.model_validate_json(content)
    except ValidationError:
        return False
    return True


def repair_row(repair: RepairTry) -> ResultRow:
    repaired = repair.repaired
    return {
        "section": "repair",
        "attempt": repair.attempt,
        "input_id": repair.golden.case_id,
        "premise_ok": int(repair.premise_ok),
        "fixed": int(repair.fixed),
        "repaired_markers": repair.repaired_markers,
        "repaired_script_share": repair.repaired_share,
        "first_latency_s": repair.first.latency_s,
        "repair_latency_s": repaired.latency_s if repaired else None,
        "repair_prompt_tokens": repaired.prompt_tokens if repaired else None,
        "repair_completion_tokens": repaired.completion_tokens if repaired else None,
        "first_content": repair.first.content,
        "repaired_content": repaired.content if repaired else None,
        "error": (repaired.error if repaired else None) or repair.first.error,
    }


async def json_repair_try(client: AsyncOpenAI, limit: asyncio.Semaphore, attempt: int) -> ResultRow:
    golden = MENTOR_INPUTS[0]
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": MENTOR_SYSTEM},
        {"role": "user", "content": golden.text},
        {"role": "assistant", "content": BROKEN_JSON},
        {"role": "user", "content": JSON_REPAIR_MESSAGE},
    ]
    result = await call_model(
        client,
        limit,
        CallRequest(MODEL, messages, "mentor_answer", MentorAnswer.model_json_schema()),
    )
    return {
        "section": "repair_json",
        "attempt": attempt,
        "input_id": golden.case_id,
        "fixed": int(_is_valid(MentorAnswer, result.content)),
        "latency_s": result.latency_s,
        "content": result.content,
        "error": result.error,
    }


# --- the other probes ---------------------------------------------------------------------------


async def record_models(client: AsyncOpenAI, rows: list[ResultRow]) -> None:
    page = await client.models.list()
    model_ids = sorted(model.id for model in page.data)
    rows.extend({"section": "models", "model_id": model_id} for model_id in model_ids)
    print(f"models: {', '.join(model_ids)}")


async def record_recursive_schema(
    client: AsyncOpenAI, limit: asyncio.Semaphore, rows: list[ResultRow]
) -> None:
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": "Reply with any label."},
        {"role": "user", "content": "test"},
    ]
    request = CallRequest(MODEL, messages, "recursive", RecursiveNode.model_json_schema())
    try:
        result = await call_model(client, limit, request)
    except BadRequestError as exc:
        rows.append(
            {
                "section": "invalid_schema",
                "rejected": 1,
                "status": exc.status_code,
                "type": exc.type,
                "param": exc.param,
                "message": _short(exc.message),
            }
        )
        print(f"recursive schema: HTTP {exc.status_code}: {_short(exc.message)}")
        return
    rows.append({"section": "invalid_schema", "rejected": 0, "error": result.error})
    print("recursive schema: accepted (unexpected)")


def rate_limit_rows(calls: Sequence[SchemaCall]) -> list[ResultRow]:
    """Rate-limit headers from the first completion that returned any."""
    for call in calls:
        if call.result.rate_limit_headers:
            return [
                {"section": "rate_limit_header", "name": name, "value": value}
                for name, value in sorted(call.result.rate_limit_headers.items())
            ]
    return [{"section": "rate_limit_header", "name": None, "value": "none returned"}]


# --- main ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpenModelEndpoint:
    base_url: str
    api_key: str
    model: str


def open_model_endpoint() -> OpenModelEndpoint | None:
    base_url = os.environ.get("OPEN_MODEL_BASE_URL", "")
    api_key = os.environ.get("OPEN_MODEL_API_KEY", "")
    model = os.environ.get("OPEN_MODEL", "")
    if not (base_url and api_key and model):
        return None
    return OpenModelEndpoint(base_url, api_key, model)


async def _summarised(
    rows: list[ResultRow], pending: Awaitable[list[SchemaCall]]
) -> list[SchemaCall]:
    calls = await pending
    rows.extend(call_row(call) for call in calls)
    summary = summarise(calls)
    rows.append(summary_row(summary))
    print_summary(summary)
    return calls


async def run(base_url: str, api_key: str, out_dir: Path) -> Path:
    rows: list[ResultRow] = []
    limit = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
    async with AsyncOpenAI(
        api_key=api_key, base_url=base_url, timeout=CALL_TIMEOUT_S, max_retries=0
    ) as client:
        await record_models(client, rows)
        main_calls: list[SchemaCall] = []
        for spec in SCHEMAS:
            main_calls.extend(
                await _summarised(
                    rows,
                    run_schema(client, limit, SchemaRun(spec, MODEL, "default"), CALLS_PER_SCHEMA),
                )
            )
        rows.extend(rate_limit_rows(main_calls))
        sweep_efforts: tuple[Effort, ...] = ("minimal", "low")
        for effort in sweep_efforts:
            for spec in SCHEMAS:
                await _summarised(
                    rows,
                    run_schema(client, limit, SchemaRun(spec, MODEL, effort), EFFORT_SWEEP_CALLS),
                )
        hinglish_mentor_inputs = [
            golden for golden in MENTOR_INPUTS if golden.register == "hinglish"
        ]
        repairs = await asyncio.gather(
            *(
                semantic_repair_try(
                    client,
                    limit,
                    attempt,
                    hinglish_mentor_inputs[(attempt - 1) % len(hinglish_mentor_inputs)],
                )
                for attempt in range(1, REPAIR_TRIES + 1)
            )
        )
        rows.extend(repair_row(repair) for repair in repairs)
        premises = sum(1 for repair in repairs if repair.premise_ok)
        fixed = sum(1 for repair in repairs if repair.fixed)
        print(
            f"semantic repair: fixed {fixed}/{premises} (premise held in {premises}/{len(repairs)})"
        )
        json_repairs = await asyncio.gather(
            *(
                json_repair_try(client, limit, attempt)
                for attempt in range(1, JSON_REPAIR_TRIES + 1)
            )
        )
        rows.extend(json_repairs)
        json_fixed = sum(1 for row in json_repairs if row["fixed"] == 1)
        print(f"json repair: fixed {json_fixed}/{len(json_repairs)}")
        await record_recursive_schema(client, limit, rows)
    await run_open_model(rows)
    return write_results(out_dir, RESULTS_NAME, rows)


async def run_open_model(rows: list[ResultRow]) -> None:
    """s10b §4.8 asks spike E to check that Muse Spark Open supports json_schema output."""
    endpoint = open_model_endpoint()
    if endpoint is None:
        rows.append({"section": "open_model", "status": "not configured"})
        print("muse spark open: not configured (OPEN_MODEL_BASE_URL / OPEN_MODEL_API_KEY unset)")
        return
    reflection = next(spec for spec in SCHEMAS if spec.name == "parent_reflection")
    limit = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
    async with AsyncOpenAI(
        api_key=endpoint.api_key, base_url=endpoint.base_url, timeout=CALL_TIMEOUT_S, max_retries=0
    ) as client:
        open_model_efforts: tuple[Effort, ...] = ("default", "minimal")
        try:
            for effort in open_model_efforts:
                await _summarised(
                    rows,
                    run_schema(
                        client,
                        limit,
                        SchemaRun(reflection, endpoint.model, effort),
                        OPEN_MODEL_CALLS,
                    ),
                )
        except BadRequestError as exc:
            status = f"HTTP {exc.status_code}: {_short(exc.message)}"
            rows.append({"section": "open_model", "status": status})
            print(f"muse spark open: json_schema rejected: {status}")


async def run_open_model_only(out_dir: Path) -> Path:
    """The Muse Spark Open check alone, for when Baseten is configured after the main run."""
    rows: list[ResultRow] = []
    await run_open_model(rows)
    return write_results(out_dir, OPEN_MODEL_RESULTS_NAME, rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spike E: structured output (s02 §4.6).")
    parser.add_argument("--out-dir", required=True, type=Path, help="Outside the repo.")
    parser.add_argument(
        "--open-model-only",
        action="store_true",
        help="Run only the Muse Spark Open check (results-open-model.json).",
    )
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir.resolve()
    repo_root = Path(__file__).resolve().parents[2]
    if out_dir == repo_root or repo_root in out_dir.parents:
        print(f"refusing to write results inside the repo: {out_dir}")
        return 2
    violations: list[str] = []
    for spec in SCHEMAS:
        violations.extend(check_strict_subset(spec.output_model.model_json_schema(), spec.name))
    if violations:
        print("\n".join(f"strict-subset violation: {violation}" for violation in violations))
        return 2
    print(f"strict-subset check: all {len(SCHEMAS)} schemas pass")
    if args.open_model_only:
        open_model_path = asyncio.run(run_open_model_only(out_dir))
        print(f"wrote {open_model_path}")
        return 0
    base_url = require_env("MODEL_API_BASE_URL")
    api_key = require_env("MODEL_API_KEY")
    try:
        path = asyncio.run(run(base_url, api_key, out_dir))
    except AuthenticationError as exc:
        print(f"model API authentication failed: HTTP {exc.status_code}")
        return 1
    except BadRequestError as exc:
        print(f"unexpected 400 from the model API: {_short(exc.message)}")
        return 1
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
