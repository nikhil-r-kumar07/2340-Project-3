# loads the medicare pdfs into chromadb (story 3)
# python manage.py ingest          -> add/refresh every doc in data/sources.json
# python manage.py ingest --reset  -> wipe the store first then load everything
# if a pdf is missing from data/docs it gets downloaded from its url first

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chat import rag


class Command(BaseCommand):
    help = "Read the Medicare PDFs in data/sources.json into ChromaDB."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete all stored passages first.")

    def handle(self, *args, **options):
        if options["reset"]:
            rag.reset_store()
            self.stdout.write("Cleared the vector store.")

        docs_dir = settings.DATA_DIR / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        #load the model up front so the download message shows before anything else
        self.stdout.write("Loading the embedding model (downloads ~67 MB the first time)...")
        rag.get_embedder()

        total = 0
        for source in rag.load_manifest():
            path = docs_dir / source["file"]
            #download the pdf if its not in data/docs yet
            if not path.exists():
                self.stdout.write(f"  Downloading {source['url']}")
                try:
                    response = requests.get(source["url"], timeout=60, headers={"User-Agent": "Mozilla/5.0"})
                    response.raise_for_status()
                except requests.RequestException as error:
                    raise CommandError(f"Could not download {source['url']}: {error}")
                path.write_bytes(response.content)
            total += rag.ingest_source(source, log=self.stdout.write)

        self.stdout.write(self.style.SUCCESS(
            f"Done: {total} passages stored ({rag.get_collection().count()} in the store)."
        ))
