from __future__ import annotations

import asyncio
import base64
import os
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from .metadata_parser import ParsedMetadata, parse_image

try:
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.star import Context, Star
    import astrbot.api.message_components as Comp
except ImportError:  # Allows parser tests outside an AstrBot installation.
    AstrMessageEvent = Any
    Context = Any

    class Star:
        def __init__(self, *_args, **_kwargs):
            pass

    Comp = Any

    class _Filter:
        def command(self, *_args, **_kwargs):
            return lambda func: func

        def event_message_type(self, *_args, **_kwargs):
            return lambda func: func

        class EventMessageType:
            ALL = "ALL"

    filter = _Filter()

class ImageMetadataPlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        self._semaphore = asyncio.Semaphore(max(1, self._int_config("max_concurrent_images", 3)))

    @filter.command("kkt")
    async def kkt(self, event: AstrMessageEvent):
        """解析当前消息中的一张或多张 AI 生图元数据。"""
        images = _extract_images(event)
        if not images:
            yield event.plain_result("请在 /kkt 指令消息中附带图片。")
            return
        results = await self._parse_images(images)
        yield self._result_chain(event, results)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_image_message(self, event: AstrMessageEvent):
        """可选的自动解析监听器；无元数据时保持静默。"""
        if not self._bool_config("auto_parse", False):
            return
        if str(getattr(event, "message_str", "")).strip().lower().startswith("/kkt"):
            return
        images = _extract_images(event)
        if not images:
            return
        results = await self._parse_images(images)
        useful = [result for result in results if result.metadata.has_metadata]
        if useful:
            yield self._result_chain(event, useful)

    async def _parse_images(self, images: list[Any]) -> list["ImageResult"]:
        tasks = [self._parse_one(index, image) for index, image in enumerate(images, start=1)]
        return list(await asyncio.gather(*tasks))

    async def _parse_one(self, index: int, image: Any) -> "ImageResult":
        async with self._semaphore:
            path: str | None = None
            is_temp = False
            try:
                path, label, is_temp = await _materialize_image(
                    image,
                    max_bytes=max(1, self._int_config("max_file_size_mb", 20)) * 1024 * 1024,
                    timeout=max(1, self._int_config("download_timeout_seconds", 15)),
                )
                metadata = await asyncio.to_thread(parse_image, path)
                return ImageResult(index=index, label=label, metadata=metadata)
            except Exception as exc:
                return ImageResult(index=index, label="图片", error=str(exc))
            finally:
                if path and is_temp:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    def _result_chain(self, event: AstrMessageEvent, results: list["ImageResult"]):
        nodes = []
        for result in results:
            text = _format_result(
                result,
                show_raw=self._bool_config("show_raw_metadata", True),
                raw_limit=max(0, self._int_config("raw_metadata_max_chars", 8000)),
            )
            nodes.append(_make_node(event, text))
        return event.chain_result(nodes)

    def _bool_config(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default) if hasattr(self.config, "get") else default
        return bool(value)

    def _int_config(self, key: str, default: int) -> int:
        value = self.config.get(key, default) if hasattr(self.config, "get") else default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


class ImageResult:
    def __init__(self, index: int, label: str, metadata: ParsedMetadata | None = None, error: str | None = None):
        self.index = index
        self.label = label
        self.metadata = metadata or ParsedMetadata(source="Error")
        self.error = error


def _extract_images(event: Any) -> list[Any]:
    message = getattr(getattr(event, "message_obj", None), "message", None)
    if not isinstance(message, Iterable) or isinstance(message, (str, bytes)):
        return []
    images = []
    for component in message:
        name = component.__class__.__name__.lower()
        if name == "image" or "image" in name:
            images.append(component)
    return images


async def _materialize_image(component: Any, max_bytes: int, timeout: int) -> tuple[str, str, bool]:
    reference = None
    for attr in ("file", "url", "path", "src"):
        value = getattr(component, attr, None)
        if value:
            reference = value
            break
    if not isinstance(reference, str):
        raise ValueError("图片消息缺少文件地址")
    reference = reference.strip()
    if reference.startswith("data:"):
        _, encoded = reference.split(",", 1)
        data = base64.b64decode(encoded, validate=True)
        return _write_temp(data, max_bytes), "Data URI", True
    if reference.startswith("base64://"):
        data = base64.b64decode(reference[9:], validate=True)
        return _write_temp(data, max_bytes), "base64 图片", True
    if re.match(r"^https?://", reference, re.I):
        data = await asyncio.to_thread(_download, reference, max_bytes, timeout)
        return _write_temp(data, max_bytes), reference, True
    path = _local_path(reference)
    if not path.is_file():
        raise ValueError("图片文件不存在")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"图片超过 {max_bytes // 1024 // 1024} MB 限制")
    return str(path), str(path), False


def _local_path(reference: str) -> Path:
    if not reference.startswith("file://"):
        return Path(reference)
    parsed = urlparse(reference)
    decoded = unquote(parsed.path)
    # file:///C:/path is the usual Windows URI spelling.
    if os.name == "nt" and decoded.startswith("/") and len(decoded) > 3 and decoded[2] == ":":
        decoded = decoded[1:]
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        decoded = f"//{parsed.netloc}{decoded}"
    return Path(decoded)


def _write_temp(data: bytes, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise ValueError(f"图片超过 {max_bytes // 1024 // 1024} MB 限制")
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        handle.write(data)
        return handle.name
    finally:
        handle.close()


def _download(url: str, max_bytes: int, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AstrBot-ImageMetadata/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                if int(declared) > max_bytes:
                    raise ValueError("远程图片超过大小限制")
            except ValueError as exc:
                if str(exc) == "远程图片超过大小限制":
                    raise
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("远程图片超过大小限制")
        return b"".join(chunks)


def _make_node(event: Any, text: str) -> Any:
    node_type = getattr(Comp, "Node", None)
    plain_type = getattr(Comp, "Plain", None)
    if node_type and plain_type:
        sender_id = "0"
        try:
            sender_id = str(event.get_self_id())
        except Exception:
            pass
        try:
            uin = int(sender_id)
        except ValueError:
            uin = 0
        return node_type(uin=uin, name="AI Image Metadata", content=[plain_type(text)])
    return text


def _format_result(result: ImageResult, show_raw: bool, raw_limit: int) -> str:
    if result.error:
        return f"图片 #{result.index} ({result.label})\n解析失败：{result.error}"
    metadata = result.metadata
    lines = [f"图片 #{result.index} ({result.label})", f"格式：{metadata.source}"]
    if metadata.width and metadata.height:
        lines.append(f"尺寸：{metadata.width} × {metadata.height}")
    fields = (
        ("正向提示词", metadata.positive_prompt), ("反向提示词", metadata.negative_prompt),
        ("模型", metadata.model), ("模型哈希", metadata.model_hash), ("VAE", metadata.vae),
        ("采样器", metadata.sampler), ("调度器", metadata.scheduler), ("步数", metadata.steps),
        ("CFG", metadata.cfg_scale), ("Seed", metadata.seed), ("LoRA", ", ".join(metadata.loras)),
        ("Clip skip", metadata.clip_skip), ("Denoise", metadata.denoise),
    )
    for label, value in fields:
        if value is not None and value != "":
            lines.append(f"{label}：{value}")
    if metadata.extra:
        lines.append("其他字段：" + ", ".join(f"{key}={value}" for key, value in metadata.extra.items()))
    if not metadata.has_metadata:
        lines.append("未找到可识别的内嵌元数据。")
    if show_raw and metadata.raw:
        raw = "\n".join(f"[{key}]\n{value}" for key, value in metadata.raw.items())
        if len(raw) > raw_limit:
            raw = raw[:raw_limit] + "\n…（原始元数据已截断）"
        lines.extend(["", "原始元数据：", raw])
    return "\n".join(lines)
