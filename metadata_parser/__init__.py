"""Image metadata extraction independent from AstrBot."""

from .parser import parse_image
from .types import ParsedMetadata

__all__ = ["ParsedMetadata", "parse_image"]
