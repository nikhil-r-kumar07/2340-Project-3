# rag stuff for stories 3 + 4 - the only file that touches chromadb and the embedding model
# ingestion: manage.py ingest reads the pdfs in data/sources.json, chunks them, embeds them, saves to chromadb
# retrieval: search() embeds the question and returns the closest passages with title, link and page
# uses fastembed (onnx) instead of pytorch so it fits on pythonanywhere

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from django.conf import settings

COLLECTION_NAME = "medicare"

#for better retrieval for bge models for question not passages
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

CHUNK_SIZE = 1000 #characters for each passage (im estimating around 250 tokens out of the 512 model)
CHUNK_OVERLAP = 150 #repeated between neighboring passages so message doesnt cut off
MIN_CHUNK_LENGTH = 80 #skip pages that are less than this

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

@lru_cache(maxsize=1)
def get_embedder():
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
    return [vector.tolist() for vector in get_embedder().embed(texts)]

def embed_query(text):
    return next(iter(get_embedder().embed([QUERY_PREFIX + text]))).tolist()

# ingestion
# clean up the pdf (remove hyphens, joint-words)
def clean_text(text):
    # soft hyphens
    text = text.replace("\u00ad", "")
    # words hyphenated between lines
    text = re.sub(r"-\n(?=[a-z])", "", text) 
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()
#chunking algorithm
def split_into_chunks(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            #cut chunks at the end of a sentence instead of in the middle (searching 2nd half of the chunk)
            cut = max(text.rfind(". ", start + size // 2, end), text.rfind("? ", start + size // 2, end))
            if cut != -1:
                end = cut + 1
        chunk = text[start:end].strip()
        if len(chunk) >= MIN_CHUNK_LENGTH:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end-overlap, start+1)
        next_space = text.find(" ", start)
        if next_space != -1 and next_space < end:
            start = next_space + 1
    return chunks
# reads page one by one and cleans the page
def read_pdf_pages(path):
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    for number, page in enumerate(reader.pages, start=1):
        yield number, clean_text(page.extract_text() or "")


def read_source_pages(path):
    path = settings.DATA_DIR / "docs" / path if isinstance(path, str) else path
    with open(path, "rb") as source_file:
        is_pdf = source_file.read(5).startswith(b"%PDF")

    if is_pdf:
        yield from read_pdf_pages(path)
    else:
        # Plain text and fetched web pages have no page structure, so cite them with page 0.
        yield 0, clean_text(path.read_text(encoding="utf-8-sig", errors="replace"))


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

    ids, documents, metadatas = [], [], []
    for page, text in read_source_pages(path):
        for index, chunk in enumerate(split_into_chunks(text)):
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