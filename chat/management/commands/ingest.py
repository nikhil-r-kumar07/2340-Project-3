# loads the configured documents into chromadb
# python manage.py ingest          -> add/refresh every doc in data/sources.json
# python manage.py ingest --reset  -> wipe the store first then load everything

from html.parser import HTMLParser

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chat import rag


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)


class Command(BaseCommand):
    help = "Read sources in data/sources.json into ChromaDB."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete all stored passages first.")
        parser.add_argument("--source", help="Ingest only this manifest filename.")

    def handle(self, *args, **options):
        if options["reset"] and options["source"]:
            raise CommandError("--reset cannot be combined with --source; it would clear other indexed documents.")
        if options["reset"]:
            rag.reset_store()
            self.stdout.write("Cleared the vector store.")

        docs_dir = settings.DATA_DIR / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        #load the model up front so the download message shows before anything else
        self.stdout.write("Loading the embedding model (downloads ~67 MB the first time)...")
        rag.get_embedder()

        sources = rag.load_manifest()
        if options["source"]:
            sources = [source for source in sources if source["file"] == options["source"]]
            if not sources:
                raise CommandError(f"No source named {options['source']} in data/sources.json.")

        total = 0
        for source in sources:
            path = docs_dir / source["file"]
            # URL entries are refreshed on every run; local files are fetched only if absent.
            fetch_url = source.get("source_type") == "url" or not path.exists()
            if fetch_url:
                self.stdout.write(f"  Fetching {source['url']}")
                try:
                    response = requests.get(source["url"], timeout=60, headers={"User-Agent": "Mozilla/5.0"})
                    response.raise_for_status()
                except requests.RequestException as error:
                    raise CommandError(f"Could not fetch {source['url']}: {error}") from error

                content_type = response.headers.get("Content-Type", "").lower()
                if response.content.startswith(b"%PDF") or "application/pdf" in content_type:
                    path.write_bytes(response.content)
                elif (
                    "html" in content_type
                    or b"<html" in response.content[:1024].lower()
                    or b"<!doctype html" in response.content[:1024].lower()
                ):
                    parser = VisibleTextParser()
                    encoding = response.encoding if "charset=" in content_type else "utf-8-sig"
                    parser.feed(response.content.decode(encoding or "utf-8", errors="replace"))
                    path.write_text(" ".join(parser.parts), encoding="utf-8")
                else:
                    encoding = response.encoding if "charset=" in content_type else "utf-8-sig"
                    path.write_text(response.content.decode(encoding or "utf-8", errors="replace"), encoding="utf-8")

            try:
                # The shared RAG helper extracts pages, chunks text, embeds it, and replaces indexed passages.
                total += rag.ingest_source(source, log=self.stdout.write)
            except (OSError, ValueError) as error:
                raise CommandError(f"Could not ingest {source['file']}: {error}") from error

        self.stdout.write(self.style.SUCCESS(
            f"Done: {total} passages stored ({rag.get_collection().count()} in the store)."
        ))
