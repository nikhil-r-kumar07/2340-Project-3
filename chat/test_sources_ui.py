from pathlib import Path
from unittest.mock import patch

from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse


SOURCES = [
    {
        "file": "medicare-guide.pdf",
        "title": "Medicare Guide",
        "url": "https://example.com/guide.pdf",
    }
]


class ManageSourcesPageTests(TestCase):
    def test_page_lists_sources_and_is_linked_from_chat(self):
        with patch("chat.views.rag.load_manifest", return_value=SOURCES):
            response = self.client.get(reverse("manage_sources"))
            chat_response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Medicare Guide")
        self.assertContains(response, "medicare-guide.pdf")
        self.assertContains(chat_response, reverse("manage_sources"))

    @patch("chat.views.rag.load_manifest", return_value=[])
    @patch("chat.views.call_command")
    def test_local_upload_calls_existing_source_command(self, call_command, load_manifest):
        def verify_temp_upload(*args, **kwargs):
            self.assertEqual(args[:3], ("sources", "add", "--local"))
            self.assertTrue(Path(args[3]).is_file())
            self.assertEqual(Path(args[3]).read_bytes(), b"%PDF demo")

        call_command.side_effect = verify_temp_upload
        response = self.client.post(
            reverse("manage_sources"),
            {
                "action": "add_local",
                "title": "Uploaded guide",
                "file": SimpleUploadedFile("guide.pdf", b"%PDF demo", content_type="application/pdf"),
            },
            follow=True,
        )

        call_command.assert_called_once()
        self.assertContains(response, "Source added")

    @patch("chat.views.rag.load_manifest", return_value=SOURCES)
    @patch("chat.views.call_command")
    def test_update_ingest_and_remove_use_existing_commands(self, call_command, load_manifest):
        self.client.post(
            reverse("manage_sources"),
            {"action": "update", "file": "medicare-guide.pdf", "title": "Updated guide"},
        )
        call_command.assert_called_with(
            "sources", "update", "medicare-guide.pdf", "--title", "Updated guide"
        )

        self.client.post(
            reverse("manage_sources"),
            {"action": "ingest", "file": "medicare-guide.pdf"},
        )
        call_command.assert_called_with("ingest", "--source", "medicare-guide.pdf")

        self.client.post(
            reverse("manage_sources"),
            {"action": "remove", "file": "medicare-guide.pdf"},
        )
        call_command.assert_called_with("sources", "remove", "medicare-guide.pdf")

    @patch("chat.views.rag.load_manifest", return_value=SOURCES)
    @patch("chat.views.call_command", side_effect=CommandError("No source found."))
    def test_command_error_is_shown_to_the_developer(self, call_command, load_manifest):
        response = self.client.post(
            reverse("manage_sources"),
            {"action": "ingest", "file": "missing.pdf"},
            follow=True,
        )

        self.assertContains(response, "No source found.")

    @patch("chat.views.rag.load_manifest", return_value=[])
    @patch("chat.views.call_command")
    def test_non_pdf_or_txt_upload_is_rejected(self, call_command, load_manifest):
        response = self.client.post(
            reverse("manage_sources"),
            {
                "action": "add_local",
                "title": "Bad upload",
                "file": SimpleUploadedFile("guide.exe", b"not a document"),
            },
            follow=True,
        )

        call_command.assert_not_called()
        self.assertContains(response, "Choose a PDF or TXT file.")
