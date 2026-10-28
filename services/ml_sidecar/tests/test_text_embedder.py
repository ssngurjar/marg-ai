"""TextEmbedder's pooling over a fake encoder: padding ignored, vectors unit length."""

from collections.abc import Mapping

import pytest
import torch

from sidecar.text_embedder import EncoderOutput, TextEmbedder

pytestmark = pytest.mark.unit


class FakeTokenizer:
    """Two texts: the first has two real tokens, the second one real token and one pad."""

    def __call__(
        self,
        texts: list[str],
        *,
        max_length: int,
        padding: bool,
        truncation: bool,
        return_tensors: str,
    ) -> Mapping[str, torch.Tensor]:
        assert (max_length, padding, truncation, return_tensors) == (512, True, True, "pt")
        assert len(texts) == 2
        return {
            "input_ids": torch.tensor([[5, 6], [7, 0]]),
            "attention_mask": torch.tensor([[1, 1], [1, 0]]),
        }


class FakeOutput:
    def __init__(self, hidden: torch.Tensor) -> None:
        self._hidden = hidden

    @property
    def last_hidden_state(self) -> torch.Tensor:
        return self._hidden


class FakeEncoder:
    def __call__(self, *, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> EncoderOutput:
        del input_ids, attention_mask
        return FakeOutput(
            torch.tensor(
                [
                    [[3.0, 0.0], [3.0, 4.0]],  # mean (3, 2)
                    [[0.0, 2.0], [100.0, 100.0]],  # the pad must not count: (0, 2)
                ]
            )
        )


def test_vectors_are_mean_pooled_over_real_tokens_and_unit_length() -> None:
    embedder = TextEmbedder(FakeTokenizer(), FakeEncoder(), dimensions=2, device="cpu")
    vectors = embedder.embed(["passage: परछाई", "query: shadow"])
    norm = (3.0**2 + 2.0**2) ** 0.5
    assert vectors[0] == pytest.approx([3.0 / norm, 2.0 / norm])
    assert vectors[1] == pytest.approx([0.0, 1.0])
    assert embedder.dimensions == 2
