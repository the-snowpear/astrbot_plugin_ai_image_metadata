from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from message_sources import collect_command_media, extract_media, resolve_reference


def segment(kind, **data):
    return {"type": kind, "data": data}


def event_for(chain, *, group_id="100", raw_message=None):
    return SimpleNamespace(
        message_obj=SimpleNamespace(
            message=chain, group_id=group_id, self_id="123", raw_message=raw_message,
        ),
        bot=SimpleNamespace(call_action=AsyncMock()),
    )


class MessageSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_reply_image_and_file(self):
        class File:
            type = "File"
            name = "original.png"
            file_ = ""
            url = "https://example.test/file.png"

            @property
            def file(self):
                raise AssertionError("File.file must not download synchronously")

        image = SimpleNamespace(type="Image", file="opaque.image", url="https://example.test/image.png")
        reply = SimpleNamespace(type="Reply", id="42", chain=[image, File()])
        event = event_for([reply])
        sources = await collect_command_media(event, 1)
        self.assertEqual([source.kind for source in sources], ["image", "file"])
        self.assertEqual(await resolve_reference(sources[0], event, 1, 1000), image.url)
        self.assertEqual(await resolve_reference(sources[1], event, 1, 1000), File.url)
        event.bot.call_action.assert_not_awaited()

    async def test_reply_id_gets_raw_message_once(self):
        event = event_for([segment("reply", id="42"), segment("reply", id="42")])
        event.bot.call_action.return_value = {
            "status": "ok", "retcode": 0, "data": {
                "message": [segment("image", file="opaque.image", url="https://example.test/a.png")],
            },
        }
        sources = await collect_command_media(event, 1)
        self.assertEqual(len(sources), 1)
        event.bot.call_action.assert_awaited_once_with(action="get_msg", message_id=42, self_id="123")

    async def test_recover_reply_dropped_by_adapter(self):
        event = event_for([], raw_message={"message": [segment("reply", id="42")]})
        event.bot.call_action.return_value = {"message": [segment("file", file_id="file-id")]}
        sources = await collect_command_media(event, 1)
        self.assertEqual(sources[0].file_id, "file-id")

    async def test_group_and_private_files_resolve_by_id(self):
        for group_id, action in (("100", "get_group_file_url"), ("", "get_private_file_url")):
            with self.subTest(group_id=group_id):
                event = event_for([], group_id=group_id)
                event.bot.call_action.return_value = {"url": "https://example.test/file.png"}
                source = extract_media([segment("file", file_id="file-id", busid=0)])[0]
                self.assertEqual(await resolve_reference(source, event, 1, 1000), "https://example.test/file.png")
                expected = {"action": action, "file_id": "file-id", "self_id": "123"}
                if group_id:
                    expected.update(group_id=group_id, busid=0)
                event.bot.call_action.assert_awaited_once_with(**expected)

    async def test_file_fallback_uses_base64_for_separate_container(self):
        event = event_for([])
        event.bot.call_action.side_effect = [
            RuntimeError("no URL API"), {"file": "/protocol-only/absent.png", "base64": "YWJj"},
        ]
        source = extract_media([segment("file", file_id="f")])[0]
        self.assertEqual(await resolve_reference(source, event, 1, 1000), "base64://YWJj")
        self.assertEqual(event.bot.call_action.await_args.kwargs["action"], "get_file")

    async def test_image_without_url_uses_get_image(self):
        event = event_for([])
        event.bot.call_action.return_value = {"url": "https://example.test/a.png"}
        source = extract_media([segment("image", file="opaque.image")])[0]
        self.assertEqual(await resolve_reference(source, event, 1, 1000), "https://example.test/a.png")
        event.bot.call_action.assert_awaited_once_with(action="get_image", file="opaque.image", self_id="123")

    async def test_oversized_file_is_rejected_before_api(self):
        event = event_for([])
        source = extract_media([segment("file", file_id="f", file_size="1001")])[0]
        with self.assertRaisesRegex(ValueError, "超过大小限制"):
            await resolve_reference(source, event, 1, 1000)
        event.bot.call_action.assert_not_awaited()

    async def test_failure_does_not_discard_current_image(self):
        event = event_for([segment("image", file="base64://YWJj"), segment("reply", id="42")])
        event.bot.call_action.side_effect = RuntimeError("expired")
        sources = await collect_command_media(event, 1)
        self.assertEqual([source.kind for source in sources], ["image", "error"])
        self.assertIn("无法获取引用消息", sources[1].error)

    async def test_reply_timeout_is_reported(self):
        async def pending(**kwargs):
            await asyncio.sleep(10)

        event = event_for([segment("reply", id="42")])
        event.bot.call_action.side_effect = pending
        sources = await collect_command_media(event, 0.01)
        self.assertIsNotNone(sources[0].error)

    async def test_nested_reply_is_not_followed(self):
        event = event_for([segment("reply", id="42")])
        event.bot.call_action.return_value = {"message": [segment("reply", id="42")]}
        self.assertEqual(await collect_command_media(event, 1), [])
        self.assertEqual(event.bot.call_action.await_count, 1)

    async def test_dedup_preserves_order(self):
        first = segment("image", url="https://example.test/first.png")
        second = segment("image", url="https://example.test/second.png")
        event = event_for([first, segment("reply", id="42", chain=[first, second])])
        sources = await collect_command_media(event, 1)
        self.assertEqual([s.references[0] for s in sources], [first["data"]["url"], second["data"]["url"]])


if __name__ == "__main__":
    unittest.main()
