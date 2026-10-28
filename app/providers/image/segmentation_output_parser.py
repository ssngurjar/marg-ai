"""SegmentationOutputParser: SAM 3.1's answer text → how many objects it found (spike F).

SAM 3.1 answers in `output_text` with one `<|box;…|>` token per object found (its fields
include `c=<confidence>`); no token means nothing was found. The API applies its own confidence
threshold (spike F saw nothing below 0.68), so every box counts.
"""

import re
from typing import ClassVar

from app.core.errors import ProviderResponseInvalid

PROVIDER = "meta_model_api"


class SegmentationOutputParser:
    BOX: ClassVar[re.Pattern[str]] = re.compile(r"<\|box;([^|]*)\|>")
    CONFIDENCE: ClassVar[re.Pattern[str]] = re.compile(r"^c=(0(\.\d+)?|1(\.0+)?)$")

    @staticmethod
    def count(output_text: str) -> int:
        """The number of boxes. Raises ProviderResponseInvalid when a box's confidence is not a
        number between 0 and 1, or an opened box token is never closed."""
        boxes = SegmentationOutputParser.BOX.findall(output_text)
        if output_text.count("<|box") != len(boxes):
            raise ProviderResponseInvalid("sam returned a malformed box", provider=PROVIDER)
        for fields in boxes:
            for field in fields.split(";"):
                if field.startswith("c=") and not SegmentationOutputParser.CONFIDENCE.match(field):
                    raise ProviderResponseInvalid(
                        "sam returned a malformed confidence", provider=PROVIDER
                    )
        return len(boxes)
