"""TextEmbedder: multilingual-e5-small sentence vectors for corpus retrieval (s11 §4.4).

Mean-pooled over real tokens and L2-normalised, 384 numbers each. The caller adds e5's
"query: " / "passage: " prefixes.
"""

from collections.abc import Mapping, Sequence
from typing import ClassVar, Protocol

import torch


class Embedder(Protocol):
    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Tokenizer(Protocol):
    def __call__(
        self,
        texts: list[str],
        *,
        max_length: int,
        padding: bool,
        truncation: bool,
        return_tensors: str,
    ) -> Mapping[str, torch.Tensor]: ...


class EncoderOutput(Protocol):
    @property
    def last_hidden_state(self) -> torch.Tensor: ...


class Encoder(Protocol):
    def __call__(
        self, *, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> EncoderOutput: ...


class TextEmbedder:
    MODEL: ClassVar[str] = "intfloat/multilingual-e5-small"
    MAX_TOKENS: ClassVar[int] = 512

    def __init__(
        self, tokenizer: Tokenizer, encoder: Encoder, *, dimensions: int, device: str
    ) -> None:
        self._tokenizer = tokenizer
        self._encoder = encoder
        self._device = device
        self.dimensions: int = dimensions

    @classmethod
    def load(cls, device: str) -> "TextEmbedder":
        # transformers ships no type information; Tokenizer and Encoder above type what is used.
        from transformers import (  # type: ignore[import-untyped]  # noqa: PLC0415  # heavy; loaded at startup only
            AutoModel,
            AutoTokenizer,
        )

        tokenizer: Tokenizer = AutoTokenizer.from_pretrained(cls.MODEL)
        model = AutoModel.from_pretrained(cls.MODEL).to(device).eval()
        hidden_size = int(model.config.hidden_size)
        encoder: Encoder = model
        return cls(tokenizer, encoder, dimensions=hidden_size, device=device)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = self._tokenizer(
            list(texts),
            max_length=self.MAX_TOKENS,
            padding=True,
            truncation=True,
            return_tensors="pt",
        )
        input_ids = batch["input_ids"].to(self._device)
        attention_mask = batch["attention_mask"].to(self._device)
        with torch.inference_mode():
            hidden = self._encoder(input_ids=input_ids, attention_mask=attention_mask)
        token_states = hidden.last_hidden_state
        real_tokens = attention_mask.unsqueeze(-1).to(token_states.dtype)
        summed = (token_states * real_tokens).sum(dim=1)
        pooled = summed / real_tokens.sum(dim=1).clamp(min=1e-9)
        normalised = torch.nn.functional.normalize(pooled, p=2, dim=1)
        vectors: list[list[float]] = []
        for row in normalised.float().cpu().numpy():
            vectors.append([float(value) for value in row])
        return vectors
