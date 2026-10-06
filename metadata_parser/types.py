from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedMetadata:
    """Normalized metadata returned by a format parser."""

    source: str = "Unknown"
    width: int | None = None
    height: int | None = None
    positive_prompt: str | None = None
    negative_prompt: str | None = None
    model: str | None = None
    model_hash: str | None = None
    vae: str | None = None
    sampler: str | None = None
    scheduler: str | None = None
    steps: int | float | None = None
    cfg_scale: int | float | None = None
    seed: int | str | None = None
    loras: list[str] = field(default_factory=list)
    clip_skip: int | float | None = None
    denoise: int | float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)
    recognized: bool = False

    @property
    def has_metadata(self) -> bool:
        return self.recognized
