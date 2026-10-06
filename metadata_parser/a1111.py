from __future__ import annotations

import re

from .types import ParsedMetadata

_PAIR_RE = re.compile(r"\s*([^:,]+?):\s*(.*?)(?=,\s*[^:,]+?:\s*|$)")


def parse_a1111(text: str, width: int | None, height: int | None) -> ParsedMetadata | None:
    if not text or not any(token in text for token in ("Steps:", "Negative prompt:", "Sampler:", "CFG scale:")):
        return None
    lines = text.strip().splitlines()
    positive = lines[0].strip() if lines else None
    negative = None
    rest = "\n".join(lines[1:])
    if "Negative prompt:" in rest:
        before, rest = rest.split("Negative prompt:", 1)
        if before.strip():
            positive = (positive + "\n" + before.strip()).strip()
        if "Steps:" in rest:
            negative, rest = rest.split("Steps:", 1)
            rest = "Steps:" + rest
        else:
            negative, rest = rest, ""
    pairs = _parse_pairs(rest)
    item = ParsedMetadata(source="A1111", width=width, height=height, recognized=True)
    item.positive_prompt = positive or None
    item.negative_prompt = negative.strip() if negative is not None else None
    item.raw["parameters"] = text
    item.steps = _number(pairs.get("Steps"))
    item.sampler = pairs.get("Sampler")
    item.scheduler = pairs.get("Schedule type")
    item.cfg_scale = _number(pairs.get("CFG scale"))
    item.seed = _number_or_text(pairs.get("Seed"))
    if pairs.get("Size"):
        match = re.match(r"(\d+)x(\d+)", pairs["Size"])
        if match:
            item.width, item.height = int(match.group(1)), int(match.group(2))
    item.model = pairs.get("Model")
    item.model_hash = pairs.get("Model hash")
    item.vae = pairs.get("VAE")
    item.clip_skip = _number(pairs.get("Clip skip"))
    item.extra.update({k: v for k, v in pairs.items() if k not in {
        "Steps", "Sampler", "Schedule type", "CFG scale", "Seed", "Size",
        "Model", "Model hash", "VAE", "Clip skip",
    }})
    return item


def _parse_pairs(text: str) -> dict[str, str]:
    return {match.group(1).strip(): match.group(2).strip() for match in _PAIR_RE.finditer(text)}


def _number(value: str | None) -> int | float | None:
    if value is None:
        return None
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except ValueError:
        return None


def _number_or_text(value: str | None) -> int | str | None:
    number = _number(value)
    return number if number is not None else value
