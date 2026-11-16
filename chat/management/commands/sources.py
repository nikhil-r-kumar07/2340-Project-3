import json
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chat import rag


def valid_file_name(file_name):
    return bool(file_name) and Path(file_name).name == file_name and Path(file_name).suffix.lower() in {".pdf", ".txt"}


class Command(BaseCommand):
    # The JSON manifest is the source catalog; each entry points to a file in data/docs.
    help = "Add, update, list, or remove RAG sources in data/sources.json."

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest="action", required=True)

        actions.add_parser("list", help="List sources in the manifest.")

        add = actions.add_parser("add", help="Add a local PDF/text file or public URL.")
        input_group = add.add_mutually_exclusive_group(required=True)
        input_group.add_argument("--local", help="Path to a local PDF or UTF-8 text file.")
        input_group.add_argument("--url", help="Public URL to fetch when ingesting.")
        add.add_argument("--title", required=True, help="Display title for citations.")
        add.add_argument("--source-url", help="Citation URL for a local file.")
        add.add_argument("--file", help="Stored filename for a URL source.")

        update = actions.add_parser("update", help="Update source metadata or replace its local file.")
        update.add_argument("file", help="Current filename from the manifest.")
        update.add_argument("--title", help="New display title.")
        update.add_argument("--url", help="New public/citation URL.")
        update.add_argument("--from-file", help="Replacement local PDF or UTF-8 text file.")

        remove = actions.add_parser("remove", help="Remove a source and its indexed passages.")
        remove.add_argument("file", help="Filename from the manifest.")

    def handle(self, *args, **options):
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (settings.DATA_DIR / "docs").mkdir(parents=True, exist_ok=True)
        try:
            sources = rag.load_manifest()
        except FileNotFoundError:
            sources = []
        except json.JSONDecodeError as error:
            raise CommandError(f"Could not read data/sources.json: {error}") from error

        action = options["action"]
        if action == "list":
            if not sources:
                self.stdout.write("No sources configured.")
            for source in sources:
                self.stdout.write(f"{source['file']}\t{source['title']}\t{source.get('url', '')}")
        elif action == "add":
            self.add_source(sources, options)
        elif action == "update":
            self.update_source(sources, options)
        elif action == "remove":
            self.remove_source(sources, options["file"])

    def add_source(self, sources, options):
        if options["local"]:
            if options["file"]:
                raise CommandError("--file is only available with --url.")
            input_path = Path(options["local"]).expanduser().resolve()
            if not input_path.is_file():
                raise CommandError(f"Local file does not exist: {input_path}")
            file_name = input_path.name
            source_url = options["source_url"] or ""
            source_type = "local"
        else:
            if options["source_url"]:
                raise CommandError("--source-url is only available with --local.")
            source_url = options["url"]
            parsed_url = urlparse(source_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise CommandError("URL sources must use http:// or https://.")
            file_name = options["file"] or unquote(Path(parsed_url.path).name) or f"{parsed_url.netloc}.txt"
            if not Path(file_name).suffix or Path(file_name).suffix.lower() not in {".pdf", ".txt"}:
                # A stable local filename lets the URL source use the same ingestion pipeline as files.
                file_name = f"{Path(file_name).stem}.txt"
            input_path = None
            source_type = "url"

        if not valid_file_name(file_name):
            raise CommandError("Source filenames must be simple .pdf or .txt filenames.")
        if any(source["file"] == file_name for source in sources):
            raise CommandError(f"A source named {file_name} already exists; use 'sources update'.")

        if source_url and source_type == "local":
            parsed_url = urlparse(source_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise CommandError("Citation URLs must use http:// or https://.")
        if input_path:
            # Keep source files together so ingest can read them by manifest filename.
            shutil.copyfile(input_path, settings.DATA_DIR / "docs" / file_name)

        sources.append({
            "file": file_name,
            "title": options["title"],
            "url": source_url,
            "source_type": source_type,
        })
        rag.save_manifest(sources)
        self.stdout.write(self.style.SUCCESS(f"Added {file_name}. Run 'python manage.py ingest --source {file_name}' to index it."))

    def update_source(self, sources, options):
        if not any((options["title"], options["url"], options["from_file"])):
            raise CommandError("Specify --title, --url, or --from-file.")
        source = next((item for item in sources if item["file"] == options["file"]), None)
        if source is None:
            raise CommandError(f"No source named {options['file']}.")

        old_file = source["file"]
        if options["from_file"]:
            input_path = Path(options["from_file"]).expanduser().resolve()
            if not input_path.is_file():
                raise CommandError(f"Local file does not exist: {input_path}")
            new_file = input_path.name
            if not valid_file_name(new_file):
                raise CommandError("Source filenames must be simple .pdf or .txt filenames.")
            if new_file != old_file and any(item["file"] == new_file for item in sources):
                raise CommandError(f"A source named {new_file} already exists.")
            destination = settings.DATA_DIR / "docs" / new_file
            if input_path != destination.resolve():
                shutil.copyfile(input_path, destination)
            source["file"] = new_file
            source["source_type"] = "local"
        if options["title"]:
            source["title"] = options["title"]
        if options["url"] is not None:
            parsed_url = urlparse(options["url"])
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise CommandError("URL sources must use http:// or https://.")
            source["url"] = options["url"]
            if source.get("source_type") != "local":
                source["source_type"] = "url"

        # Metadata is stored in each Chroma passage, so discard stale passages before re-indexing.
        rag.remove_source(old_file)
        rag.save_manifest(sources)
        if old_file != source["file"]:
            (settings.DATA_DIR / "docs" / old_file).unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(
            f"Updated {source['file']}. Run 'python manage.py ingest --source {source['file']}' to refresh its passages."
        ))

    def remove_source(self, sources, file_name):
        source = next((item for item in sources if item["file"] == file_name), None)
        if source is None:
            raise CommandError(f"No source named {file_name}.")
        # Remove from both the catalog and the index so deleted sources are no longer searchable.
        rag.remove_source(file_name)
        sources.remove(source)
        rag.save_manifest(sources)
        (settings.DATA_DIR / "docs" / file_name).unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(f"Removed {file_name} from the catalog and vector store."))
