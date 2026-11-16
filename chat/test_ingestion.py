import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from chat import rag


ARTICLE = (
    "Medicare coverage information explains enrollment periods, premiums, and benefits. "
    "People can review this guide to understand which services are covered and when "
    "they should contact Medicare for additional information."
)


class FakeCollection:
    def __init__(self):
        self.documents = []
        self.metadatas = []

    def delete(self, where):
        retained = [
            (document, metadata)
            for document, metadata in zip(self.documents, self.metadatas)
            if metadata["file"] != where["file"]
        ]
        self.documents = [document for document, _ in retained]
        self.metadatas = [metadata for _, metadata in retained]

    def add(self, documents, metadatas, **kwargs):
        self.documents.extend(documents)
        self.metadatas.extend(metadatas)

    def count(self):
        return len(self.documents)

    def query(self, **kwargs):
        return {
            "documents": [self.documents[:kwargs["n_results"]]],
            "metadatas": [self.metadatas[:kwargs["n_results"]]],
            "distances": [[0.1] * min(kwargs["n_results"], len(self.documents))],
        }


class SourceCommandTests(SimpleTestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_dir = Path(self.temporary_directory.name) / "data"
        (self.data_dir / "docs").mkdir(parents=True)
        (self.data_dir / "sources.json").write_text("[]", encoding="utf-8")
        self.settings_override = override_settings(DATA_DIR=self.data_dir)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def manifest(self):
        return json.loads((self.data_dir / "sources.json").read_text(encoding="utf-8"))

    def test_local_file_can_be_added_updated_and_removed(self):
        local_file = Path(self.temporary_directory.name) / "guide.txt"
        local_file.write_text(ARTICLE, encoding="utf-8")

        call_command("sources", "add", "--local", str(local_file), "--title", "Local guide")
        source = self.manifest()[0]
        self.assertEqual(source["file"], "guide.txt")
        self.assertEqual(source["source_type"], "local")
        self.assertEqual(source["preprocessing"], rag.DEFAULT_PREPROCESSING_OPTIONS)
        self.assertEqual((self.data_dir / "docs" / "guide.txt").read_text(encoding="utf-8"), ARTICLE)

        collection = FakeCollection()
        with (
            patch(
                "chat.rag.get_embedder",
                return_value=SimpleNamespace(token_count=lambda text: len(text.split())),
            ),
            patch("chat.rag.get_collection", return_value=collection),
            patch("chat.rag.embed_passages", side_effect=lambda texts: [[0.0] for _ in texts]),
            patch("chat.rag.embed_query", return_value=[0.0]),
        ):
            call_command("ingest", "--source", "guide.txt")
            results = rag.search("What does Medicare cover?")
        self.assertTrue(results)
        self.assertIn("Medicare coverage information", results[0].text)

        with patch("chat.management.commands.sources.rag.remove_source") as remove_source:
            call_command(
                "sources",
                "update",
                "guide.txt",
                "--title",
                "Updated guide",
                "--no-normalize-unicode",
                "--minimum-chunk-length",
                "120",
            )
            remove_source.assert_called_once_with("guide.txt")
        self.assertEqual(self.manifest()[0]["title"], "Updated guide")
        self.assertFalse(self.manifest()[0]["preprocessing"]["normalize_unicode"])
        self.assertEqual(self.manifest()[0]["preprocessing"]["minimum_chunk_length"], 120)

        replacement = Path(self.temporary_directory.name) / "replacement.txt"
        replacement.write_text(ARTICLE + " Updated content.", encoding="utf-8")
        with patch("chat.management.commands.sources.rag.remove_source") as remove_source:
            call_command("sources", "update", "guide.txt", "--from-file", str(replacement))
            remove_source.assert_called_once_with("guide.txt")
        self.assertEqual(self.manifest()[0]["file"], "replacement.txt")
        self.assertTrue((self.data_dir / "docs" / "replacement.txt").exists())
        self.assertFalse((self.data_dir / "docs" / "guide.txt").exists())

        with patch("chat.management.commands.sources.rag.remove_source"):
            call_command("sources", "remove", "replacement.txt")
        self.assertEqual(self.manifest(), [])
        self.assertFalse((self.data_dir / "docs" / "guide.txt").exists())

    def test_public_url_text_is_ingested_and_searchable(self):
        collection = FakeCollection()
        response = SimpleNamespace(
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=(
                "<html><body>"
                "<nav>navigation noise</nav>"
                f"<main>{ARTICLE}<aside>aside noise</aside></main>"
                "<footer>footer noise</footer>"
                "<script>hidden secret</script>"
                "</body></html>"
            ).encode(),
            encoding="utf-8",
            raise_for_status=lambda: None,
        )
        call_command(
            "sources",
            "add",
            "--url",
            "https://example.test/medicare-guide",
            "--title",
            "Online guide",
        )
        with (
            patch("chat.management.commands.ingest.requests.get", return_value=response),
            patch(
                "chat.rag.get_embedder",
                return_value=SimpleNamespace(token_count=lambda text: len(text.split())),
            ),
            patch("chat.rag.get_collection", return_value=collection),
            patch("chat.rag.embed_passages", side_effect=lambda texts: [[0.0] for _ in texts]),
            patch("chat.rag.embed_query", return_value=[0.0]),
        ):
            call_command("ingest", "--source", "medicare-guide.txt")
            results = rag.search("What does Medicare cover?")

        self.assertTrue(results)
        self.assertIn("Medicare coverage information", results[0].text)
        self.assertNotIn("hidden secret", results[0].text)
        self.assertNotIn("navigation noise", results[0].text)
        self.assertNotIn("aside noise", results[0].text)
        self.assertNotIn("footer noise", results[0].text)
        self.assertEqual(results[0].title, "Online guide")
        self.assertEqual(results[0].page, 0)

    def test_duplicate_chunks_are_removed_before_embedding(self):
        collection = FakeCollection()
        repeated_chunk = ARTICLE * 2
        source = {
            "file": "guide.txt",
            "title": "Guide",
            "url": "",
            "preprocessing": rag.DEFAULT_PREPROCESSING_OPTIONS,
        }

        with (
            patch(
                "chat.rag.read_source_pages",
                return_value=[(1, repeated_chunk), (2, repeated_chunk)],
            ),
            patch("chat.rag.preprocess", side_effect=lambda pages, options: list(pages)),
            patch("chat.rag.split_into_chunks", return_value=[repeated_chunk]),
            patch("chat.rag.get_collection", return_value=collection),
            patch("chat.rag.embed_passages", side_effect=lambda texts: [[0.0] for _ in texts]),
        ):
            count = rag.ingest_source(source)

        self.assertEqual(count, 1)
        self.assertEqual(collection.documents, [repeated_chunk])
