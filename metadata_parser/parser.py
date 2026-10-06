from __future__ import annotations

from pathlib import Path

from .a1111 import parse_a1111
from .comfyui import parse_comfyui
from .novelai import parse_novelai
from .png import read_png_metadata
from .types import ParsedMetadata


def parse_image(path: str | Path) -> ParsedMetadata:
    """Parse supported embedded metadata. Unsupported formats return empty metadata."""
    try:
        width, height, raw = read_png_metadata(path)
    except Exception as exc:
        return ParsedMetadata(source="Unsupported", extra={"error": str(exc)})
    if not raw:
        return ParsedMetadata(source="PNG", width=width, height=height)
    result = parse_a1111(raw.get("parameters", ""), width, height)
    if result is not None:
        return result
    result = parse_comfyui(raw, width, height)
    if result is not None:
        return result
    result = parse_novelai(raw, width, height)
    if result is not None:
        return result
    return ParsedMetadata(source="PNG", width=width, height=height, raw=raw)
