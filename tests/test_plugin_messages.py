from __future__ import annotations

import base64
import importlib
import sys
import types
import unittest
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_metadata_parser import png_with_text


# Load with a package name, exactly as required by the plugin's relative imports.
package_name = "_image_metadata_message_tests"
package = types.ModuleType(package_name)
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[package_name] = package
main = importlib.import_module(package_name + ".main")


class ComponentType(str, Enum):
    Image = "Image"
    Reply = "Reply"
    File = "File"


class Plain:
    def __init__(self, text):
        self.text = text


class Node:
    def __init__(self, *, uin, name, content):
        # Current AstrBot components validate this as str, not int.
        if not isinstance(uin, str):
            raise TypeError("uin must be a string")
        self.uin, self.name, self.content = uin, name, content


class Nodes:
    def __init__(self, nodes):
        self.nodes = nodes


class Event:
    def __init__(self, chain, text="", group_id="100"):
        self.message_obj = SimpleNamespace(message=chain, group_id=group_id, self_id="123")
        self.message_str = text
        self.bot = SimpleNamespace(call_action=AsyncMock())

    def get_self_id(self):
        return "123"

    def chain_result(self, chain):
        return chain

    def plain_result(self, text):
        return text


def image(file="opaque.image", url="https://example.test/a.png"):
    return SimpleNamespace(type=ComponentType.Image, file=file, url=url)


def quoted(*chain):
    return SimpleNamespace(type=ComponentType.Reply, id="42", chain=list(chain))


def result_text(reply):
    return "\n".join(component.text for node in reply[0].nodes for component in node.content)


class PluginMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.components = patch.object(main, "Comp", SimpleNamespace(Plain=Plain, Node=Node, Nodes=Nodes))
        self.components.start()
        self.addCleanup(self.components.stop)
        self.png = png_with_text(parameters="a cat\nNegative prompt: blurry\nSteps: 20, Seed: 42")

    async def test_quoted_image_is_parsed_and_temp_is_cleaned(self):
        plugin = main.ImageMetadataPlugin(None, {})
        event = Event([quoted(image())], "/kkt")
        created = []
        write_temp = main._write_temp

        def tracking_write(data, limit):
            path = write_temp(data, limit)
            created.append(Path(path))
            return path

        with patch.object(main, "_download", return_value=self.png) as download:
            with patch.object(main, "_write_temp", side_effect=tracking_write):
                replies = [reply async for reply in plugin.kkt(event)]
        download.assert_called_once_with("https://example.test/a.png", 20 * 1024 * 1024, 15)
        self.assertIn("A1111", result_text(replies[0]))
        self.assertIn("a cat", result_text(replies[0]))
        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))

    async def test_quoted_local_png_file_is_not_deleted(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "原图 test.png"
            path.write_bytes(self.png)
            file = SimpleNamespace(type=ComponentType.File, file_=path.as_uri(), name=path.name, url="")
            event = Event([quoted(file)], "/kkt")
            plugin = main.ImageMetadataPlugin(None, {})
            replies = [reply async for reply in plugin.kkt(event)]
            self.assertIn("A1111", result_text(replies[0]))
            self.assertEqual(path.read_bytes(), self.png)

    async def test_quoted_file_id_resolves_message_and_download_url(self):
        event = Event([quoted()], "/kkt")
        event.bot.call_action.side_effect = [
            {"message": [{"type": "file", "data": {"file_id": "f", "file": "original.png"}}]},
            {"url": "https://example.test/file.png"},
        ]
        plugin = main.ImageMetadataPlugin(None, {})
        with patch.object(main, "_download", return_value=self.png):
            replies = [reply async for reply in plugin.kkt(event)]
        self.assertIn("A1111", result_text(replies[0]))
        self.assertEqual([call.kwargs["action"] for call in event.bot.call_action.await_args_list],
                         ["get_msg", "get_group_file_url"])

    async def test_multiple_images_use_one_forward_message(self):
        event = Event([image(), quoted(image(url="https://example.test/b.png"))], "/kkt")
        plugin = main.ImageMetadataPlugin(None, {})
        with patch.object(main, "_download", return_value=self.png):
            replies = [reply async for reply in plugin.kkt(event)]
        self.assertEqual(len(replies), 1)
        self.assertEqual(len(replies[0]), 1)
        self.assertEqual(len(replies[0][0].nodes), 2)
        self.assertIn("#1", replies[0][0].nodes[0].content[0].text)
        self.assertIn("#2", replies[0][0].nodes[1].content[0].text)

    async def test_auto_uses_url_instead_of_opaque_filename(self):
        plugin = main.ImageMetadataPlugin(None, {"auto_parse": True})
        event = Event([image()])
        with patch.object(main, "_download", return_value=self.png) as download:
            replies = [reply async for reply in plugin.on_image_message(event)]
        self.assertEqual(len(replies), 1)
        self.assertIn("A1111", result_text(replies[0]))
        download.assert_called_once_with("https://example.test/a.png", 20 * 1024 * 1024, 15)

    async def test_auto_disabled_does_not_download(self):
        plugin = main.ImageMetadataPlugin(None, {})
        with patch.object(main, "_download") as download:
            self.assertEqual([reply async for reply in plugin.on_image_message(Event([image()]))], [])
        download.assert_not_called()

    async def test_auto_observes_config_changes(self):
        config = {}
        plugin = main.ImageMetadataPlugin(None, config)
        config["auto_parse"] = True
        with patch.object(main, "_download", return_value=self.png):
            replies = [reply async for reply in plugin.on_image_message(Event([image()]))]
        self.assertEqual(len(replies), 1)

    async def test_no_metadata_silent_auto_but_command_reports(self):
        plugin = main.ImageMetadataPlugin(None, {"auto_parse": True})
        with patch.object(main, "_download", return_value=png_with_text()):
            self.assertEqual([reply async for reply in plugin.on_image_message(Event([image()]))], [])
            replies = [reply async for reply in plugin.kkt(Event([quoted(image())], "/kkt"))]
        self.assertIn("未找到可识别", result_text(replies[0]))

    async def test_auto_does_not_follow_quotes_or_duplicate_command(self):
        plugin = main.ImageMetadataPlugin(None, {"auto_parse": True})
        for event in (Event([quoted(image())]), Event([image()], "/kkt"), Event([image()], "kkt")):
            with patch.object(main, "_download") as download:
                self.assertEqual([reply async for reply in plugin.on_image_message(event)], [])
            download.assert_not_called()
            event.bot.call_action.assert_not_awaited()
        event = Event([image()], "/kkt")
        with patch.object(main, "_download", return_value=self.png) as download:
            replies = [reply async for reply in plugin.kkt(event)]
            event.message_str = ""  # The framework may consume command text.
            self.assertEqual([reply async for reply in plugin.on_image_message(event)], [])
        self.assertEqual(len(replies), 1)
        self.assertEqual(download.call_count, 1)

    async def test_auto_download_failure_is_silent_and_logged(self):
        plugin = main.ImageMetadataPlugin(None, {"auto_parse": True})
        with patch.object(main, "_download", side_effect=TimeoutError("download timeout")):
            with self.assertLogs(main.__name__, level="WARNING"):
                replies = [reply async for reply in plugin.on_image_message(Event([image()]))]
        self.assertEqual(replies, [])

    async def test_failed_quote_reports_error(self):
        event = Event([quoted()], "/kkt")
        event.bot.call_action.side_effect = RuntimeError("expired")
        plugin = main.ImageMetadataPlugin(None, {})
        with self.assertLogs(main.__name__, level="WARNING"):
            replies = [reply async for reply in plugin.kkt(event)]
        self.assertIn("无法获取引用消息", result_text(replies[0]))

    async def test_no_image_explains_quote_usage(self):
        plugin = main.ImageMetadataPlugin(None, {})
        replies = [reply async for reply in plugin.kkt(Event([], "/kkt"))]
        self.assertIn("引用图片／PNG 文件", replies[0])

    async def test_base64_file_uses_same_parser(self):
        encoded = base64.b64encode(self.png).decode()
        file = SimpleNamespace(type=ComponentType.File, file_="base64://" + encoded, name="original.png", url="")
        plugin = main.ImageMetadataPlugin(None, {})
        replies = [reply async for reply in plugin.kkt(Event([quoted(file)], "/kkt"))]
        self.assertIn("A1111", result_text(replies[0]))

    async def test_command_size_limit_is_preserved(self):
        plugin = main.ImageMetadataPlugin(None, {"max_file_size_mb": 1})
        with patch.object(main, "_download", return_value=b"x" * (1024 * 1024 + 1)):
            with self.assertLogs(main.__name__, level="WARNING"):
                replies = [reply async for reply in plugin.kkt(Event([quoted(image())], "/kkt"))]
        self.assertIn("超过", result_text(replies[0]))


if __name__ == "__main__":
    unittest.main()
