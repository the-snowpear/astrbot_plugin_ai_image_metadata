from __future__ import annotations

import json
import struct
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

from metadata_parser import parse_image
from metadata_parser.a1111 import parse_a1111
from metadata_parser.comfyui import parse_comfyui
from metadata_parser.novelai import parse_novelai


def png_with_text(**chunks: str) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 64, 32, 8, 2, 0, 0, 0)
    text = b"".join(chunk(b"tEXt", key.encode() + b"\0" + value.encode()) for key, value in chunks.items())
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + text + chunk(b"IEND", b"")


class MetadataParserTests(unittest.TestCase):
    def test_a1111_png(self) -> None:
        parameters = (
            "1girl, blue hair\n"
            "Negative prompt: low quality, blurry\n"
            "Steps: 28, Sampler: DPM++ 2M Karras, CFG scale: 7, Seed: 42, "
            "Size: 512x768, Model hash: abc123, Model: anime.safetensors, VAE: vae.pt"
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "a1111.png"
            path.write_bytes(png_with_text(parameters=parameters))
            result = parse_image(path)
        self.assertEqual(result.source, "A1111")
        self.assertEqual(result.positive_prompt, "1girl, blue hair")
        self.assertEqual(result.negative_prompt, "low quality, blurry")
        self.assertEqual(result.steps, 28)
        self.assertEqual(result.seed, 42)
        self.assertEqual((result.width, result.height), (512, 768))

    def test_comfyui_prompt(self) -> None:
        prompt = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat"}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality"}},
            "3": {"class_type": "KSampler", "inputs": {"positive": ["2", 0], "negative": ["4", 0], "seed": 123, "steps": 20, "cfg": 6.5, "sampler_name": "euler", "scheduler": "normal"}},
        }
        result = parse_comfyui({"prompt": json.dumps(prompt)}, 512, 512)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.source, "ComfyUI")
        self.assertEqual(result.model, "model.safetensors")
        self.assertEqual(result.positive_prompt, "a cat")
        self.assertEqual(result.negative_prompt, "low quality")
        self.assertEqual(result.seed, 123)
        self.assertEqual(result.cfg_scale, 6.5)

    def test_novelai_json(self) -> None:
        result = parse_novelai({"Comment": json.dumps({"prompt": "a fox", "uc": "bad anatomy", "steps": 28, "scale": 5, "seed": 99, "sampler": "k_euler"})}, 832, 1216)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.source, "NovelAI")
        self.assertEqual(result.negative_prompt, "bad anatomy")
        self.assertEqual(result.seed, 99)

    def test_comfyui_workflow_nodes(self) -> None:
        workflow = {
            "nodes": [
                {"type": "CLIPTextEncode", "title": "positive", "widgets_values": ["a castle"]},
                {"type": "CLIPTextEncode", "title": "negative", "widgets_values": ["blurry"]},
                {"type": "CheckpointLoaderSimple", "widgets_values": ["checkpoint.safetensors"]},
                {"type": "KSampler", "widgets_values": [7, "fixed", 24, 5.5, "euler", "normal", 1.0]},
            ]
        }
        result = parse_comfyui({"workflow": json.dumps(workflow)}, 768, 512)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.positive_prompt, "a castle")
        self.assertEqual(result.negative_prompt, "blurry")
        self.assertEqual(result.model, "checkpoint.safetensors")
        self.assertEqual(result.steps, 24)

    def test_png_without_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "plain.png"
            path.write_bytes(png_with_text())
            result = parse_image(path)
        self.assertEqual(result.source, "PNG")
        self.assertFalse(result.has_metadata)
        self.assertEqual((result.width, result.height), (64, 32))

    def test_unknown_text_is_not_recognized(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.png"
            path.write_bytes(png_with_text(author="camera"))
            result = parse_image(path)
        self.assertEqual(result.source, "PNG")
        self.assertFalse(result.has_metadata)
        self.assertEqual(result.raw["author"], "camera")

    def test_non_png_is_supported_error(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "not-image.jpg"
            path.write_bytes(b"not a png")
            result = parse_image(path)
        self.assertEqual(result.source, "Unsupported")
        self.assertIn("PNG", result.extra["error"])


if __name__ == "__main__":
    unittest.main()
