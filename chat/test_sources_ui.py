from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY, get_user_model
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


class DeveloperLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff_user = get_user_model().objects.create_user(
            username="developer",
            password="test-password",
            is_staff=True,
        )
        cls.regular_user = get_user_model().objects.create_user(
            username="visitor",
            password="test-password",
        )

    def test_developer_login_page_is_separate_from_admin(self):
        response = self.client.get(reverse("developer_login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Developer Login")
        self.assertNotContains(response, "Django administration")

    def test_staff_user_can_log_in_and_reach_source_manager(self):
        response = self.client.post(
            reverse("developer_login"),
            {"username": "developer", "password": "test-password"},
        )

        self.assertRedirects(response, reverse("manage_sources"))
        self.assertEqual(
            self.client.session[SESSION_KEY],
            str(self.staff_user.pk),
        )

    def test_non_staff_user_is_rejected(self):
        response = self.client.post(
            reverse("developer_login"),
            {"username": "visitor", "password": "test-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This account does not have developer access.")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_developer_can_log_out(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(reverse("developer_logout"))

        self.assertRedirects(response, reverse("index"))
        self.assertNotIn(SESSION_KEY, self.client.session)


class SourceManagementAuthorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.regular_user = get_user_model().objects.create_user(
            username="visitor",
            password="test-password",
        )

    def test_anonymous_user_cannot_view_or_change_sources(self):
        with patch("chat.views.call_command") as call_command:
            get_response = self.client.get(reverse("manage_sources"))
            post_response = self.client.post(
                reverse("manage_sources"),
                {"action": "remove", "file": "medicare-guide.pdf"},
            )

        self.assertEqual(get_response.status_code, 403)
        self.assertEqual(post_response.status_code, 403)
        call_command.assert_not_called()

    def test_non_staff_user_cannot_view_or_change_sources(self):
        self.client.force_login(self.regular_user)

        with patch("chat.views.call_command") as call_command:
            get_response = self.client.get(reverse("manage_sources"))
            post_response = self.client.post(
                reverse("manage_sources"),
                {"action": "ingest", "file": "medicare-guide.pdf"},
            )

        self.assertEqual(get_response.status_code, 403)
        self.assertEqual(post_response.status_code, 403)
        call_command.assert_not_called()

    def test_manage_sources_link_is_hidden_from_non_staff_users(self):
        anonymous_response = self.client.get(reverse("index"))
        self.client.force_login(self.regular_user)
        regular_user_response = self.client.get(reverse("index"))

        self.assertNotContains(anonymous_response, reverse("manage_sources"))
        self.assertNotContains(regular_user_response, reverse("manage_sources"))
        self.assertContains(anonymous_response, reverse("developer_login"))
        self.assertContains(regular_user_response, reverse("developer_login"))


class ManageSourcesPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff_user = get_user_model().objects.create_user(
            username="developer",
            password="test-password",
            is_staff=True,
        )

    def setUp(self):
        self.client.force_login(self.staff_user)
        status_patcher = patch(
            "chat.views.rag.indexed_source_files",
            return_value={"medicare-guide.pdf"},
        )
        status_patcher.start()
        self.addCleanup(status_patcher.stop)

    def test_page_lists_sources_and_is_linked_from_chat(self):
        with patch("chat.views.rag.load_manifest", return_value=SOURCES):
            response = self.client.get(reverse("manage_sources"))
            chat_response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Knowledge base")
        self.assertContains(response, "Add a source")
        self.assertContains(response, "Source library")
        self.assertContains(response, "Medicare Guide")
        self.assertContains(response, "medicare-guide.pdf")
        self.assertContains(response, "Indexed")
        self.assertContains(response, 'data-source-status="indexed"')
        self.assertContains(response, "Cleaning options")
        self.assertContains(response, 'name="minimum_chunk_length"')
        self.assertContains(chat_response, reverse("manage_sources"))
        self.assertContains(chat_response, reverse("developer_logout"))

    @patch("chat.views.rag.indexed_source_files", return_value=set())
    @patch("chat.views.rag.load_manifest", return_value=SOURCES)
    def test_unindexed_source_is_clearly_ready_to_ingest(
        self,
        load_manifest,
        indexed_source_files,
    ):
        response = self.client.get(reverse("manage_sources"))

        self.assertContains(response, "Needs ingestion")
        self.assertContains(response, 'data-source-status="pending"')
        self.assertContains(response, "Ingest source")

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

    @patch("chat.views.rag.load_manifest", return_value=[])
    @patch("chat.views.call_command")
    def test_public_url_calls_existing_source_command(self, call_command, load_manifest):
        response = self.client.post(
            reverse("manage_sources"),
            {
                "action": "add_url",
                "title": "Public Medicare guide",
                "url": "https://example.com/medicare",
            },
            follow=True,
        )

        call_command.assert_called_once_with(
            "sources",
            "add",
            "--url",
            "https://example.com/medicare",
            "--title",
            "Public Medicare guide",
        )
        self.assertContains(response, "URL source added")

    @patch("chat.views.rag.load_manifest", return_value=SOURCES)
    @patch("chat.views.call_command")
    def test_update_ingest_and_remove_use_existing_commands(self, call_command, load_manifest):
        self.client.post(
            reverse("manage_sources"),
            {
                "action": "update",
                "file": "medicare-guide.pdf",
                "title": "Updated guide",
                "url": "https://example.com/updated-guide.pdf",
            },
        )
        call_command.assert_called_with(
            "sources",
            "update",
            "medicare-guide.pdf",
            "--title",
            "Updated guide",
            "--url",
            "https://example.com/updated-guide.pdf",
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
    @patch("chat.views.call_command")
    def test_cleaning_options_are_sent_to_source_command(self, call_command, load_manifest):
        self.client.post(
            reverse("manage_sources"),
            {
                "action": "update",
                "file": "medicare-guide.pdf",
                "normalize_unicode": "",
                "skip_contents_index": "on",
                "minimum_chunk_length": "120",
            },
        )

        call_command.assert_called_once_with(
            "sources",
            "update",
            "medicare-guide.pdf",
            "--no-normalize-unicode",
            "--skip-contents-index",
            "--minimum-chunk-length",
            "120",
        )

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
