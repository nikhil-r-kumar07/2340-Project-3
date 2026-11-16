# rag stuff for stories 3 + 4 - the only file that touches chromadb and the embedding model
# ingestion: manage.py ingest reads the pdfs in data/sources.json, chunks them, embeds them, saves to chromadb
# retrieval: search() embeds the question and returns the closest passages with title, link and page
# supports hosted Hugging Face embeddings in production and FastEmbed locally

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import requests
from django.conf import settings

COLLECTION_NAME = "medicare"

# BGE supports 512 tokens. A 384-token chunk leaves room for tokenizer special
# tokens while providing substantially more coherent context than character cuts.
CHUNK_SIZE = 384
CHUNK_OVERLAP = 64
MIN_CHUNK_LENGTH = 80  # Skip headers and page fragments that contain no useful context.

DEFAULT_PREPROCESSING_OPTIONS = {
    "normalize_unicode": True,
    "remove_repeated_lines": True,
    "skip_contents_index": True,
    "filter_html_boilerplate": True,
    "deduplicate_chunks": True,
    "minimum_chunk_length": MIN_CHUNK_LENGTH,
}

UNICODE_REPLACEMENTS = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
    "\u00a0": " ",
})
PAGE_NUMBER_PATTERN = re.compile(
    r"^(?:page\s*)?(?:\d+|[ivxlcdm]+)(?:\s*(?:of|/)\s*\d+)?$",
    re.IGNORECASE,
)
DOT_LEADER_PATTERN = re.compile(r"(?:\.{3,}|…{2,})")
CONTENTS_HEADING_PATTERN = re.compile(
    r"^(?:table\s+of\s+)?contents$|^index$",
    re.IGNORECASE,
)

@dataclass
class Passage:
    text: str #passage text
    title: str #title of passage
    url: str #url for passage
    page: int #passage's page
    distance: float #how far the passage was from the question
    number: int = 0 #citation number for user

    @property
    def link(self):
        return f"{self.url}#page={self.page}" if self.page else self.url

#shared resources

class HuggingFaceEmbedding:
    """Small FastEmbed-compatible adapter for Hugging Face's hosted API."""

    def __init__(self, model, token, timeout=60):
        if not token:
            raise ValueError("HF_TOKEN is required when EMBED_PROVIDER=huggingface.")
        self.model = model
        self.token = token
        self.timeout = timeout
        self.url = (
            "https://router.huggingface.co/hf-inference/models/"
            f"{model}/pipeline/feature-extraction"
        )

    def token_count(self, text):
        # A conservative approximation used only for chunk boundaries. The API
        # performs the authoritative model tokenization.
        words_and_punctuation = len(re.findall(r"\w+|[^\w\s]", text))
        character_estimate = math.ceil(len(text) / 4)
        return max(1, words_and_punctuation, character_estimate)

    def embed(self, texts):
        texts = list(texts)
        try:
            response = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"},
                json={"inputs": texts, "options": {"wait_for_model": True}},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise ValueError(f"Hugging Face embedding request failed: {error}") from error

        if isinstance(payload, dict):
            if payload.get("error"):
                raise ValueError(f"Hugging Face embedding request failed: {payload['error']}")
            raise ValueError("Hugging Face returned an unexpected embedding response.")
        if len(texts) == 1 and payload and isinstance(payload[0], (int, float)):
            payload = [payload]
        if not isinstance(payload, list) or len(payload) != len(texts):
            raise ValueError("Hugging Face returned an unexpected embedding response.")
        return [self._pool_and_normalize(vector) for vector in payload]

    @staticmethod
    def _pool_and_normalize(vector):
        # Some feature-extraction models return token vectors rather than one
        # sentence vector. Mean-pool them so Chroma always receives one vector.
        if vector and isinstance(vector[0], list):
            width = len(vector[0])
            vector = [
                sum(token[index] for token in vector) / len(vector)
                for index in range(width)
            ]
        try:
            vector = [float(value) for value in vector]
        except (TypeError, ValueError) as error:
            raise ValueError("Hugging Face returned an invalid embedding vector.") from error
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else vector


@lru_cache(maxsize=1)
def get_embedder():
    if settings.EMBED_PROVIDER == "huggingface":
        return HuggingFaceEmbedding(
            settings.EMBED_MODEL,
            settings.HF_TOKEN,
            settings.EMBED_API_TIMEOUT,
        )
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=settings.EMBED_MODEL, cache_dir=str(settings.EMBED_CACHE_DIR))

@lru_cache(maxsize=1)
def get_client():
    import chromadb
    return chromadb.PersistentClient(path=str(settings.CHROMA_DIR))

def get_collection():
    return get_client().get_or_create_collection(
        COLLECTION_NAME,
        embedding_function=None,
        metadata={"hnsw:space": "cosine"},
    )

def embed_passages(texts):
    return [
        vector.tolist() if hasattr(vector, "tolist") else list(vector)
        for vector in get_embedder().embed(texts)
    ]

def embed_query(text):
    vector = next(iter(get_embedder().embed([settings.EMBED_QUERY_PREFIX + text])))
    return vector.tolist() if hasattr(vector, "tolist") else list(vector)

# ingestion
def preprocessing_options(source):
    """Return validated settings, including defaults for legacy manifest rows."""
    configured = source.get("preprocessing", {}) if isinstance(source, dict) else {}
    options = DEFAULT_PREPROCESSING_OPTIONS.copy()
    for name in options:
        if name in configured:
            options[name] = configured[name]
    for name in options:
        if name != "minimum_chunk_length":
            options[name] = bool(options[name])
    try:
        options["minimum_chunk_length"] = max(1, int(options["minimum_chunk_length"]))
    except (TypeError, ValueError):
        options["minimum_chunk_length"] = MIN_CHUNK_LENGTH
    return options


def clean_text(text, normalize_unicode=True):
    """Normalize extracted text while preserving lines for page-level cleanup."""
    if normalize_unicode:
        text = unicodedata.normalize("NFKC", text).translate(UNICODE_REPLACEMENTS)
    # Remove soft hyphens and non-printing control characters from PDF extraction.
    text = text.replace("\u00ad", "").replace("\ufffd", "")
    text = "".join(
        character
        for character in text
        if character in {"\n", "\t"} or not unicodedata.category(character).startswith("C")
    )
    # Rejoin words hyphenated across PDF lines, then normalize each remaining line.
    text = re.sub(r"-\s*\n\s*(?=[a-z])", "", text)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def repeated_line_key(line):
    key = re.sub(r"\s+", " ", line).strip().casefold()
    # Headers and footers often append the current page number.
    return re.sub(r"\s+(?:page\s+)?\d+\s*$", "", key)


def is_contents_or_index_page(lines):
    nonempty = [line.strip() for line in lines if line.strip()]
    if any(CONTENTS_HEADING_PATTERN.fullmatch(line) for line in nonempty[:8]):
        return True
    dot_leader_count = sum(bool(DOT_LEADER_PATTERN.search(line)) for line in nonempty)
    return dot_leader_count >= 3 and dot_leader_count >= len(nonempty) * 0.2


def preprocess(pages, options=None):
    """Apply configurable document-level cleaning before semantic chunking."""
    options = {**DEFAULT_PREPROCESSING_OPTIONS, **(options or {})}
    prepared = [
        (
            page,
            clean_text(text, normalize_unicode=options["normalize_unicode"]),
        )
        for page, text in pages
    ]

    repeated_lines = set()
    if options["remove_repeated_lines"] and len(prepared) >= 3:
        counts = Counter()
        for _, text in prepared:
            page_lines = {
                repeated_line_key(line)
                for line in text.splitlines()
                if line.strip() and len(line.strip()) <= 160
            }
            counts.update(page_lines)
        repeated_lines = {
            line
            for line, count in counts.items()
            if line and count > len(prepared) / 2
        }

    cleaned_pages = []
    for page, text in prepared:
        lines = text.splitlines()
        if options["skip_contents_index"] and is_contents_or_index_page(lines):
            continue

        kept_lines = []
        for line in lines:
            stripped = line.strip()
            if options["skip_contents_index"] and DOT_LEADER_PATTERN.search(stripped):
                continue
            if options["remove_repeated_lines"] and (
                PAGE_NUMBER_PATTERN.fullmatch(stripped)
                or repeated_line_key(stripped) in repeated_lines
            ):
                continue
            kept_lines.append(stripped)

        cleaned = "\n".join(line for line in kept_lines if line).strip()
        if cleaned:
            cleaned_pages.append((page, cleaned))
    return cleaned_pages


# SemChunk keeps semantic boundaries while enforcing the embedding model's token
# limit. The optional counter keeps unit tests fast and independent of model files.
def split_into_chunks(
    text,
    size=None,
    overlap=None,
    token_counter=None,
    minimum_length=MIN_CHUNK_LENGTH,
):
    import semchunk

    text = text.strip()
    if len(text) < minimum_length:
        return []

    size = size or settings.EMBED_CHUNK_SIZE
    overlap = settings.EMBED_CHUNK_OVERLAP if overlap is None else overlap
    token_counter = token_counter or get_embedder().token_count
    chunks = semchunk.chunk(
        text,
        chunk_size=size,
        token_counter=token_counter,
        overlap=overlap,
    )
    return [chunk.strip() for chunk in chunks if len(chunk.strip()) >= minimum_length]


# Read pages without flattening line boundaries needed by preprocessing.
def read_pdf_pages(path):
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    for number, page in enumerate(reader.pages, start=1):
        yield number, page.extract_text() or ""


def read_source_pages(path):
    path = settings.DATA_DIR / "docs" / path if isinstance(path, str) else path
    with open(path, "rb") as source_file:
        is_pdf = source_file.read(5).startswith(b"%PDF")

    if is_pdf:
        yield from read_pdf_pages(path)
    else:
        # Plain text and fetched web pages have no page structure, so cite them with page 0.
        yield 0, path.read_text(encoding="utf-8-sig", errors="replace")


def load_manifest():
    with open(settings.DATA_DIR / "sources.json", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(sources):
    manifest_path = settings.DATA_DIR / "sources.json"
    temporary_path = manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(manifest_path)


# add/replace one document from sources.json in the vector store
def ingest_source(source, log=print):
    path = settings.DATA_DIR / "docs" / source["file"]
    collection = get_collection()
    options = preprocessing_options(source)

    ids, documents, metadatas = [], [], []
    seen_chunks = set()
    pages = preprocess(read_source_pages(path), options)
    for page, text in pages:
        for index, chunk in enumerate(split_into_chunks(
            text,
            minimum_length=options["minimum_chunk_length"],
        )):
            chunk_key = re.sub(r"\s+", " ", chunk).strip().casefold()
            if options["deduplicate_chunks"] and chunk_key in seen_chunks:
                continue
            seen_chunks.add(chunk_key)
            ids.append(hashlib.sha1(f"{source['file']}|{page}|{index}".encode()).hexdigest())
            documents.append(chunk)
            metadatas.append({
                "file": source["file"],
                "title": source["title"],
                "url": source["url"],
                "page": page,
            })

    if not documents:
        raise ValueError(f"No searchable text found in {path.name}.")

    batch = 64
    # Generate every embedding before deleting the old index, preserving it if embedding fails.
    embeddings = [
        embed_passages(documents[i:i + batch])
        for i in range(0, len(documents), batch)
    ]
    collection.delete(where={"file": source["file"]})
    for i in range(0, len(documents), batch):
        collection.add(
            ids=ids[i:i + batch],
            documents=documents[i:i + batch],
            embeddings=embeddings[i // batch],
            metadatas=metadatas[i:i + batch],
        )
    log(f"  {source['title']}: {len(documents)} passages")
    return len(documents)


def remove_source(file_name):
    get_collection().delete(where={"file": file_name})


def indexed_source_files():
    """Return manifest filenames that currently have passages in ChromaDB."""
    collection = get_collection()
    if collection.count() == 0:
        return set()
    result = collection.get(include=["metadatas"])
    return {
        metadata["file"]
        for metadata in result.get("metadatas", [])
        if metadata and metadata.get("file")
    }


def reset_store():
    from chromadb.errors import NotFoundError

    try:
        get_client().delete_collection(COLLECTION_NAME)
    except NotFoundError:
        pass

#retrieval

#embeds the question + asks croma db for closest 4 passages (cut off at 0.45)
def search(query, k=None, max_distance=None):
    k = k or settings.RAG_TOP_K
    max_distance = settings.RAG_MAX_DISTANCE if max_distance is None else max_distance

    collection = get_collection()
    if collection.count() == 0:
        return []

    results = collection.query(
        query_embeddings=[embed_query(query)],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )
    passages = []
    for text, meta, distance in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        if distance <= max_distance:
            passages.append(Passage(
                text=text,
                title=meta["title"],
                url=meta["url"],
                page=int(meta.get("page", 0)),
                distance=distance,
            ))
    return passages

#follow up handling
def search_conversation(question, previous_question=None):
    found = search(question)
    if previous_question:
        found += search(f"{previous_question} {question}")
    best = {}
    for passage in found:
        key = (passage.url, passage.page, passage.text)
        if key not in best or passage.distance < best[key].distance:
            best[key] = passage
    return sorted(best.values(), key=lambda p: p.distance)[:settings.RAG_TOP_K]

#citation numbers
def number_sources(passages):
    sources, numbers = [], {}
    for passage in passages:
        key = (passage.url, passage.page)
        if key not in numbers:
            numbers[key] = len(numbers) + 1
            sources.append({
                "number": numbers[key],
                "title": passage.title,
                "page": passage.page,
                "url": passage.link,
            })
        passage.number = numbers[key]
    return sources