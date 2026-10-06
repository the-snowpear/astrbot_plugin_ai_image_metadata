from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class PluginLoadingTests(unittest.TestCase):
    def test_load_from_host_plugin_package(self) -> None:
        """The host adds its root, not each plugin directory, to sys.path."""
        project = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            host = Path(directory)
            plugin = host / "data" / "plugins" / "astrbot_plugin_ai_image_metadata"
            plugin.mkdir(parents=True)
            shutil.copy2(project / "main.py", plugin / "main.py")
            shutil.copytree(
                project / "metadata_parser",
                plugin / "metadata_parser",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            script = textwrap.dedent("""
                import importlib
                import sys

                sys.path.insert(0, sys.argv[1])
                package = "data.plugins.astrbot_plugin_ai_image_metadata"
                module = importlib.import_module(package + ".main")
                assert module.ParsedMetadata.__module__ == package + ".metadata_parser.types"
                assert module.parse_image.__module__ == package + ".metadata_parser.parser"
                assert "metadata_parser" not in sys.modules
                plugin = module.ImageMetadataPlugin(None, {"auto_parse": False})
                assert plugin.config["auto_parse"] is False
            """)
            # A fresh isolated interpreter prevents imports from the other tests
            # and the repository working directory from hiding packaging errors.
            result = subprocess.run(
                [sys.executable, "-I", "-c", script, str(host)],
                cwd=host,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
