from __future__ import annotations

import json
from typing import Any

from .types import ParsedMetadata


def parse_novelai(raw: dict[str, str], width: int | None, height: int | None) -> ParsedMetadata | None:
    documents: list[dict[str, Any]] = []
    for value in raw.values():
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(decoded, dict) and any(k in decoded for k in ("prompt", "uc", "steps", "scale", "seed", "sampler")):
            documents.append(decoded)
    if not documents and not any("novelai" in value.lower() for value in raw.values() if isinstance(value, str)):
        return None
    item = ParsedMetadata(source="NovelAI", width=width, height=height, recognized=True)
    item.raw.update(raw)
    for document in documents:
        _apply(document, item)
    return item


def _apply(document: dict[str, Any], item: ParsedMetadata) -> None:
    item.positive_prompt = item.positive_prompt or _text(document.get("prompt"))
    item.negative_prompt = item.negative_prompt or _text(document.get("uc"))
    item.model = item.model or _text(document.get("model"))
    item.sampler = item.sampler or _text(document.get("sampler")) or _text(document.get("sampler_name"))
    item.steps = item.steps if item.steps is not None else _number(document.get("steps"))
    item.cfg_scale = item.cfg_scale if item.cfg_scale is not None else _number(document.get("scale"))
    item.seed = item.seed if item.seed is not None else document.get("seed")
    for key in ("width", "height"):
        value = _number(document.get(key))
        if value is not None:
            setattr(item, key, int(value))
    known = {"prompt", "uc", "model", "sampler", "sampler_name", "steps", "scale", "seed", "width", "height"}
    item.extra.update({key: value for key, value in document.items() if key not in known})


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> int | float | None:
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None
