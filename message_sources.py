"""Resolve current/replied OneBot media without downloading via File.file."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


@dataclass
class MediaSource:
    kind: str
    references: tuple[str, ...] = ()
    file_id: str = ""
    busid: Any = None
    name: str = "图片"
    size: int | None = None
    error: str | None = None


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _kind(component: Any) -> str:
    kind = _get(component, "type", component.__class__.__name__)
    return str(getattr(kind, "value", kind)).lower()


def _data(component: Any) -> Any:
    return component.get("data", component) if isinstance(component, Mapping) else component


def _chain(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _source(component: Any) -> MediaSource:
    kind, data = _kind(component), _data(component)
    # AstrBot File.file is a downloading property. Read only its backing field.
    file_key = "file_" if kind == "file" and not isinstance(data, Mapping) else "file"
    references = tuple(
        value.strip() for key in ("url", file_key, "path", "src")
        if isinstance(value := _get(data, key), str) and value.strip()
    )
    size = _get(data, "file_size", _get(data, "size"))
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None
    return MediaSource(
        kind=kind, references=references,
        file_id=str(_get(data, "file_id") or ""), busid=_get(data, "busid"),
        name=str(_get(data, "name") or _get(data, "file_name") or ("文件" if kind == "file" else "图片")),
        size=size,
    )


def extract_media(chain: Any, *, include_files: bool = True) -> list[MediaSource]:
    kinds = {"image", "file"} if include_files else {"image"}
    return [_source(component) for component in _chain(chain) if _kind(component) in kinds]


async def call_onebot(event: Any, action: str, timeout: float, **params: Any) -> dict:
    bot = getattr(event, "bot", None)
    if not callable(getattr(bot, "call_action", None)):
        raise ValueError("当前渠道无法获取引用消息或文件，请使用 OneBot QQ 渠道")
    self_id = _get(getattr(event, "message_obj", None), "self_id")
    if self_id:
        params["self_id"] = self_id
    response = await asyncio.wait_for(bot.call_action(action=action, **params), timeout=timeout)
    if not isinstance(response, Mapping):
        raise ValueError("OneBot 返回格式无效")
    if response.get("status") == "failed" or response.get("retcode", 0) != 0:
        raise ValueError("OneBot 请求失败")
    # CQHttp normally unwraps data, but also accept full OneBot response envelopes.
    if isinstance(response.get("data"), Mapping):
        response = response["data"]
    return dict(response)


async def collect_command_media(event: Any, timeout: float) -> list[MediaSource]:
    message = getattr(event, "message_obj", None)
    chain = _chain(_get(message, "message"))
    raw_chain = _chain(_get(_get(message, "raw_message"), "message"))
    # Some adapter versions drop file/reply segments when resolving them fails.
    for kind in ("image", "file", "reply"):
        if not any(_kind(component) == kind for component in chain):
            chain.extend(component for component in raw_chain if _kind(component) == kind)

    sources: list[MediaSource] = []
    seen_replies: set[str] = set()
    for component in chain:
        kind = _kind(component)
        if kind in {"image", "file"}:
            sources.append(_source(component))
        elif kind == "reply":
            data = _data(component)
            reply_id = str(_get(data, "id") or "")
            if reply_id and reply_id in seen_replies:
                continue
            seen_replies.add(reply_id)
            quoted = extract_media(_get(data, "chain"))
            if not quoted and reply_id:
                try:
                    response = await call_onebot(event, "get_msg", timeout, message_id=int(reply_id))
                    quoted = extract_media(response.get("message"))
                except Exception:
                    sources.append(MediaSource(
                        kind="error", name="引用消息",
                        error="无法获取引用消息，可能已过期或协议端不支持；请重新发送图片或 PNG 文件后引用。",
                    ))
                    continue
            # Follow only the explicitly quoted message, never its reply history.
            sources.extend(quoted)

    result: list[MediaSource] = []
    seen: set[tuple] = set()
    for source in sources:
        key = (source.kind, source.references, source.file_id, source.error)
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


def local_path(reference: str) -> Path:
    if not reference.startswith("file:"):
        return Path(reference)
    parsed = urlparse(reference)
    decoded = unquote(parsed.path)
    if os.name == "nt" and len(decoded) > 3 and decoded[0] == "/" and decoded[2] == ":":
        decoded = decoded[1:]
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        decoded = f"//{parsed.netloc}{decoded}"
    return Path(decoded)


def _usable_reference(references: tuple[str, ...]) -> str | None:
    for reference in references:
        if reference.lower().startswith(("https://", "http://", "base64://", "data:")):
            return reference
        try:
            path = local_path(reference)
            # An opaque OneBot filename is not a file in AstrBot's working dir.
            if path.is_absolute() and path.is_file():
                return reference
        except (OSError, ValueError):
            continue
    return None


async def resolve_reference(source: MediaSource, event: Any, timeout: float, max_bytes: int) -> str:
    if source.error:
        raise ValueError(source.error)
    if source.size is not None and source.size > max_bytes:
        raise ValueError("图片或文件超过大小限制")
    reference = _usable_reference(source.references)
    if reference:
        return reference

    actions: list[tuple[str, dict]] = []
    if source.kind == "file" and source.file_id:
        message = getattr(event, "message_obj", None)
        group_id = _get(message, "group_id")
        if not group_id and callable(getattr(event, "get_group_id", None)):
            group_id = event.get_group_id()
        params: dict[str, Any] = {"file_id": source.file_id}
        if group_id:
            params["group_id"] = group_id
            if source.busid is not None:
                params["busid"] = source.busid
            actions.append(("get_group_file_url", params))
        else:
            actions.append(("get_private_file_url", params))
        actions.append(("get_file", {"file_id": source.file_id}))
    elif source.kind == "image" and source.references:
        actions.append(("get_image", {"file": source.references[0]}))

    for action, params in actions:
        try:
            response = await call_onebot(event, action, timeout, **params)
        except Exception:
            continue
        resolved = _source({"type": source.kind, "data": response})
        if resolved.size is not None and resolved.size > max_bytes:
            raise ValueError("图片或文件超过大小限制")
        reference = _usable_reference(resolved.references)
        if reference:
            return reference
        # A protocol-side path may be inaccessible to a separate AstrBot container.
        encoded = response.get("base64")
        if isinstance(encoded, str) and encoded:
            return encoded if encoded.startswith(("base64://", "data:")) else "base64://" + encoded
    raise ValueError("无法获取图片或文件下载地址，请确认文件未过期且协议端支持文件下载。")
