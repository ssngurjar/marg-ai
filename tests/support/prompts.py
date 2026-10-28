"""The real prompt registry, with every shipped prompt, for tests."""

from functools import cache

from app.prompts.prompt_registry import PromptRegistry, PromptSettings
from app.wiring import PROMPT_SPECS

OPEN_MODEL = "meta-models/muse-spark-open"

TEST_PROMPT_SETTINGS = PromptSettings(
    models={
        "MODEL_TEXT": "muse-spark-1.3",
        "OPEN_MODEL": OPEN_MODEL,
        "MODEL_JUDGE": "muse-spark-1.3",
    },
    reasoning_effort="minimal",
    user_slot_max_chars=4000,
)


@cache
def shipped_registry() -> PromptRegistry:
    return PromptRegistry(specs=PROMPT_SPECS, settings=TEST_PROMPT_SETTINGS)
