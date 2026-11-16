import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


class DeploymentCheckTests(TestCase):
    def prepare_paths(self, root):
        data_dir = root / "data"
        chroma_dir = root / "chroma"
        cache_dir = root / "cache"
        static_root = root / "static"
        for path in (data_dir, chroma_dir, cache_dir, static_root):
            path.mkdir()

        (data_dir / "sources.json").write_text(
            json.dumps([{"file": "guide.txt", "title": "Guide", "url": ""}]),
            encoding="utf-8",
        )
        (chroma_dir / "chroma.sqlite3").write_text("index", encoding="utf-8")
        (static_root / "style.css").write_text("body {}", encoding="utf-8")
        return data_dir, chroma_dir, cache_dir, static_root

    def test_ready_deployment_passes(self):
        get_user_model().objects.create_user(
            username="developer",
            password="test-password",
            is_staff=True,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = self.prepare_paths(Path(temporary_directory))
            output = StringIO()
            with (
                override_settings(
                    DEBUG=False,
                    LLM_API_KEY="configured-key",
                    DATA_DIR=paths[0],
                    CHROMA_DIR=paths[1],
                    EMBED_CACHE_DIR=paths[2],
                    STATIC_ROOT=paths[3],
                ),
                patch(
                    "chat.management.commands.deployment_check.checks.run_checks",
                    return_value=[],
                ),
                patch(
                    "chat.management.commands.deployment_check.importlib.util.find_spec",
                    return_value=object(),
                ),
            ):
                call_command("deployment_check", stdout=output)

        self.assertIn("Deployment readiness checks passed", output.getvalue())

    def test_missing_runtime_requirements_fail(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = self.prepare_paths(Path(temporary_directory))
            with (
                override_settings(
                    DEBUG=False,
                    LLM_API_KEY="",
                    DATA_DIR=paths[0],
                    CHROMA_DIR=paths[1],
                    EMBED_CACHE_DIR=paths[2],
                    STATIC_ROOT=paths[3],
                ),
                patch(
                    "chat.management.commands.deployment_check.checks.run_checks",
                    return_value=[],
                ),
                patch(
                    "chat.management.commands.deployment_check.importlib.util.find_spec",
                    return_value=None,
                ),
                self.assertRaises(CommandError) as error,
            ):
                call_command("deployment_check")

        message = str(error.exception)
        self.assertIn("LLM_API_KEY is missing", message)
        self.assertIn("Required Python package is missing: chromadb", message)
        self.assertIn("No active developer account", message)
