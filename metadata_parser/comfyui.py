from __future__ import annotations

import json
from typing import Any

from .types import ParsedMetadata


def parse_comfyui(raw: dict[str, str], width: int | None, height: int | None) -> ParsedMetadata | None:
    candidates: list[tuple[str, Any]] = []
    for key in ("prompt", "workflow", "ComfyUI", "comfyui"):
        if key in raw:
            try:
                candidates.append((key, json.loads(raw[key])))
            except (TypeError, json.JSONDecodeError):
                continue
    if not candidates:
        return None
    item = ParsedMetadata(source="ComfyUI", width=width, height=height, recognized=True)
    item.raw.update({key: raw[key] for key, _ in candidates})
    for _, document in candidates:
        _extract_graph_prompts(document, item)
        _extract_workflow_nodes(document, item)
        _walk(document, item)
    return item


def _extract_graph_prompts(document: Any, item: ParsedMetadata) -> None:
    """Resolve KSampler positive/negative links in the API prompt format."""
    if not isinstance(document, dict):
        return
    nodes = {
        str(node_id): node
        for node_id, node in document.items()
        if isinstance(node, dict) and isinstance(node.get("inputs"), dict)
    }
    for node in nodes.values():
        inputs = node["inputs"]
        if "positive" not in inputs and "negative" not in inputs:
            continue
        for polarity in ("positive", "negative"):
            link = inputs.get(polarity)
            if not isinstance(link, (list, tuple)) or not link:
                continue
            source = nodes.get(str(link[0]))
            if not source or "CLIPTextEncode" not in str(source.get("class_type", "")):
                continue
            text = source.get("inputs", {}).get("text")
            if isinstance(text, str) and text.strip():
                if polarity == "positive":
                    item.positive_prompt = item.positive_prompt or text
                else:
                    item.negative_prompt = item.negative_prompt or text


def _extract_workflow_nodes(document: Any, item: ParsedMetadata) -> None:
    """Extract common fields from the editor workflow JSON representation."""
    if not isinstance(document, dict) or not isinstance(document.get("nodes"), list):
        return
    for node in document["nodes"]:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type", node.get("class_type", "")))
        lower = node_type.lower()
        values = node.get("widgets_values")
        if not isinstance(values, list):
            continue
        title = str(node.get("title", node.get("properties", {}).get("Node name", ""))).lower()
        if "cliptextencode" in lower and values:
            text = _as_text(values[0])
            if text:
                if "negative" in title or "neg" in title:
                    item.negative_prompt = item.negative_prompt or text
                elif item.positive_prompt is None:
                    item.positive_prompt = text
                elif item.negative_prompt is None:
                    item.negative_prompt = text
        elif "checkpoint" in lower and values:
            item.model = item.model or _as_text(values[0])
        elif "ksampler" in lower and len(values) >= 6:
            item.seed = item.seed if item.seed is not None else _number_or_text(values[0])
            item.steps = item.steps if item.steps is not None else _number(values[2])
            item.cfg_scale = item.cfg_scale if item.cfg_scale is not None else _number(values[3])
            item.sampler = item.sampler or _as_text(values[4])
            item.scheduler = item.scheduler or _as_text(values[5])
            if len(values) > 6:
                item.denoise = item.denoise if item.denoise is not None else _number(values[6])


def _walk(value: Any, item: ParsedMetadata) -> None:
    if isinstance(value, dict):
        class_type = str(value.get("class_type", ""))
        inputs = value.get("inputs", value)
        if isinstance(inputs, dict):
            _extract_inputs(class_type, inputs, item)
        for child in value.values():
            _walk(child, item)
    elif isinstance(value, list):
        for child in value:
            _walk(child, item)


def _extract_inputs(class_type: str, inputs: dict[str, Any], item: ParsedMetadata) -> None:
    lower = class_type.lower()
    if "cliptextencode" in lower:
        text = inputs.get("text")
        if isinstance(text, str) and text.strip():
            if any(x in lower for x in ("negative", "neg")):
                item.negative_prompt = item.negative_prompt or text
            elif item.positive_prompt is None:
                item.positive_prompt = text
    if "checkpoint" in lower or "loadcheckpoint" in lower:
        item.model = item.model or _as_text(inputs.get("ckpt_name"))
    if "loraloader" in lower:
        for key in ("lora_name", "lora_name_1", "lora_name_2"):
            name = _as_text(inputs.get(key))
            if name and name not in item.loras:
                item.loras.append(name)
    if "ksampler" in lower or "sampler" in lower:
        item.seed = item.seed if item.seed is not None else _number_or_text(inputs.get("seed"))
        item.steps = item.steps if item.steps is not None else _number(inputs.get("steps"))
        item.cfg_scale = item.cfg_scale if item.cfg_scale is not None else _number(inputs.get("cfg"))
        item.sampler = item.sampler or _as_text(inputs.get("sampler_name"))
        item.scheduler = item.scheduler or _as_text(inputs.get("scheduler"))
        item.denoise = item.denoise if item.denoise is not None else _number(inputs.get("denoise"))
    for key, value in inputs.items():
        if key in {"width", "height"} and isinstance(value, (int, float)):
            setattr(item, key, int(value))
        if key.lower() in {"vae_name", "vae"} and item.vae is None:
            item.vae = _as_text(value)


def _as_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> int | float | None:
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None


def _number_or_text(value: Any) -> int | str | None:
    number = _number(value)
    return number if number is not None else _as_text(value)
