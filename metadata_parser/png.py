from __future__ import annotations

import struct
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PNGMetadataError(ValueError):
    pass


def read_png_metadata(path: str | Path) -> tuple[int, int, dict[str, str]]:
    """Read PNG dimensions and textual chunks without rewriting the image."""
    with Path(path).open("rb") as stream:
        if stream.read(8) != PNG_SIGNATURE:
            raise PNGMetadataError("不是 PNG 图片")
        width = height = None
        result: dict[str, str] = {}
        while True:
            header = stream.read(8)
            if len(header) != 8:
                raise PNGMetadataError("PNG 文件不完整")
            length, chunk_type = struct.unpack(">I4s", header)
            if length > 64 * 1024 * 1024:
                raise PNGMetadataError("PNG 块过大")
            data = stream.read(length)
            if len(data) != length or len(stream.read(4)) != 4:
                raise PNGMetadataError("PNG 块不完整")
            if chunk_type == b"IHDR" and len(data) >= 8:
                width, height = struct.unpack(">II", data[:8])
            elif chunk_type == b"tEXt":
                key, _, value = data.partition(b"\x00")
                result[_decode(key)] = _decode(value)
            elif chunk_type == b"zTXt":
                key, _, compressed = data.partition(b"\x00")
                if compressed[:1] == b"\x00":
                    try:
                        result[_decode(key)] = _decode(zlib.decompress(compressed[1:]))
                    except zlib.error:
                        pass
            elif chunk_type == b"iTXt":
                _read_itxt(data, result)
            if chunk_type == b"IEND":
                break
        if width is None or height is None:
            raise PNGMetadataError("PNG 缺少尺寸信息")
    return width, height, result


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").strip("\x00")


def _read_itxt(data: bytes, result: dict[str, str]) -> None:
    # keyword\0 compression_flag compression_method language\0 translated\0 text
    try:
        key, rest = data.split(b"\x00", 1)
        if len(rest) < 2:
            return
        compressed, method = rest[:2]
        rest = rest[2:]
        _, rest = rest.split(b"\x00", 1)
        _, text = rest.split(b"\x00", 1)
        if compressed == 1 and method == 0:
            text = zlib.decompress(text)
        result[_decode(key)] = _decode(text)
    except (ValueError, zlib.error):
        return
