# Medicare Helper

A chatbot that helps older adults with low health literacy understand Medicare in plain language.
CS 2340 Project 3.

**Sprint 1 so far:**
- **Story 1:** reach the chatbot through a web app.
- **Story 2:** ask natural-language Medicare questions and get relevant answers.
- **Story 3:** answers are grounded in official Medicare.gov documents.
- **Story 4:** each answer lists the documents and pages it came from, with links to them.
- **Story 8:** bigger text (Normal / Large / Extra large) and a high-contrast mode, saved for each visitor.
- **Story 9:** a "Read aloud" button under each answer that reads it out loud.


## Tech stack
- **Django 5:** web server, pages and sessions, with SQLite.
- **Plain HTML/CSS/JavaScript:** no build step.
- **LLM:** OpenAI's open-weights `gpt-oss-120b`, hosted free on [Groq](https://console.groq.com).
  - It's called through the standard OpenAI-compatible chat API using `requests` (`chat/llm.py`).
- **RAG:** ChromaDB vector store + `BAAI/bge-small-en-v1.5` embeddings run through fastembed (ONNX, so no PyTorch), with `pypdf` for reading PDFs.

## Setup
```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install --no-deps "chromadb==1.5.*"
cp .env.example .env              # then put your own Groq API key in .env
python manage.py migrate
python manage.py ingest
python manage.py runserver
```
Open http://127.0.0.1:8000.

Each teammate should create their own free Groq key, since rate limits are per key.


### Why `--no-deps` for ChromaDB?
A plain `pip install chromadb` installs server-only packages like kubernetes, which is about 520 MB. This is more than PythonAnywhere's free disk quota.
We only use Chroma's embedded `PersistentClient`, so `requirements.txt` lists just what that needs. This comes to about 350 MB total.

## The dataset
- `data/sources.json` lists each document's file, title, and official URL. The PDFs are in `data/docs/`.
- Add/remove/update sources with `python manage.py sources add`, `python manage.py sources remove`, and `python manage.py sources update`. These commands keep `data/sources.json` in sync; local files are copied into `data/docs/`.
- Local `.pdf` and UTF-8 `.txt` files are supported. Add a public `--url` source to fetch its text (or PDF) during ingestion. HTML pages are reduced to visible text.
- Run `python manage.py ingest` to refresh every source, or `python manage.py ingest --source FILE` to ingest one. URL sources are fetched again each time; existing URL-based sources are downloaded when their local file is missing.
- `python manage.py ingest --reset` rebuilds the store from scratch.
- Current documents (all from medicare.gov/publications): Medicare & You, Your Medicare Benefits, Medicare Costs, Understanding Medicare Advantage Plans, Your Guide to Medicare Prescription Drug Coverage, Choosing a Medigap Policy.

### Source management examples
```bash
# Make a local copy of a project PDF, then add and index it
cp data/docs/10116-your-medicare-benefits.pdf /tmp/local-medicare.pdf
python manage.py sources add --local /tmp/local-medicare.pdf --title "Local Medicare benefits"
python manage.py ingest --source local-medicare.pdf

# Fetch a public page, extract its visible text, and index it
python manage.py sources add --url https://www.medicare.gov/basics/get-started-with-medicare --title "Getting started with Medicare"
python manage.py ingest --source get-started-with-medicare.txt

# Update source metadata, or replace its local file and re-index
python manage.py sources update local-medicare.pdf --title "Updated Medicare benefits"
python manage.py ingest --source local-medicare.pdf
cp data/docs/10116-your-medicare-benefits.pdf /tmp/replacement-medicare.pdf
python manage.py sources update local-medicare.pdf --from-file /tmp/replacement-medicare.pdf --title "Replacement Medicare benefits"
python manage.py ingest --source replacement-medicare.pdf

# List or remove a source (removal also deletes its ChromaDB passages)
python manage.py sources list
python manage.py sources remove replacement-medicare.pdf
python manage.py sources remove get-started-with-medicare.txt
```


## Switching models
Edit `.env` only. No code changes are needed.

| Option | `LLM_BASE_URL` | `LLM_MODEL` | `LLM_REASONING_EFFORT` |
|---|---|---|---|
| Groq GPT-OSS 120B (default) | `https://api.groq.com/openai/v1` | `openai/gpt-oss-120b` | `low` |
| Groq Llama 3.3 70B (fallback) | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | *(blank)* |
| Local Ollama | `http://localhost:11434/v1` | `gpt-oss:20b` or `llama3.2` | `low` for gpt-oss |

## Running tests
```bash
python manage.py test chat
```
The tests use a fake model, so they need no internet connection or API key. They also use fake search so they need no `manage.py ingest`.

## How a question flows
1. `chat/static/chat/chat.js` sends the question to `POST /api/ask/`.
2. `chat/views.py` (`ask`) checks the question.
3. `chat/rag.py` (`search_conversation`) finds the closest Medicare passages in ChromaDB.
   - Follow-ups are also searched together with the previous question.
   - Passages with a cosine distance over 0.45 are ignored.
4. `chat/prompts.py` (`build_system_prompt`) puts the numbered passages in the system prompt, telling the model to answer only from them and cite them like [1].
5. `chat/llm.py` (`chat_completion`) sends system prompt + last 10 messages + the question to the LLM.
6. The view keeps only the sources the answer cites, saves the conversation, and returns `{answer, sources}`.
   - The page shows each source as a link to the PDF page.

## Display settings (Story 8)
- The bar above the chat has **Text size** (Normal / Large / Extra large) and **High contrast** buttons.
- Clicking one changes the page right away (`chat.js` swaps a class on `<html>`) and saves it with `POST /api/display/`.
- The choice is kept in the session, like the chat history, so it stays after a reload or "New chat".
- `base.html` adds the saved classes on the server, so the page never flashes the default look first.
- In `style.css` the modes only override variables: `--text-scale` grows everything sized in `rem`, and `.high-contrast` swaps the colors to black, white and yellow.

## Read aloud (Story 9)
- Every answer from Medicare Helper has a **Read aloud** button. While it reads, the button turns into **Stop reading**.
- It uses the browser's built-in voice (the Web Speech API), so there is no extra package, API key or cost.
- Citation numbers like [1] are skipped, and the voice reads a little slower than normal (`READING_RATE` in `chat.js`).
- Answers are read one sentence at a time because Chrome stops long speech after about 15 seconds.
- If a browser can't speak, the button stays hidden.

## Project layout
| File | What it does | Story |
|---|---|---|
| `config/settings.py` | Django settings, read from `.env` | 1 |
| `config/urls.py`, `chat/urls.py` | URL routes | 1 |
| `templates/base.html` | Page shell: header, footer, disclaimer | 1 |
| `chat/templates/chat/index.html` | Chat page | 1 |
| `chat/static/chat/style.css` | Styles: large text, high legibility, mobile-friendly, text-size and high-contrast modes, Read aloud button | 1, 8, 9 |
| `chat/static/chat/chat.js` | Sends questions and shows answers without reloading; display settings buttons; Read aloud | 1, 8, 9 |
| `chat/views.py` | `index`, `ask`, `reset` and `display` endpoints | 2, 8 |
| `chat/llm.py` | The only code that talks to the LLM | 2 |
| `chat/prompts.py` | System prompt: plain language, Medicare-only, safe | 2 |
| `chat/tests.py` | Automated tests | 2-4, 8, 9 |
| `chat/rag.py` | Embeddings, ChromaDB, chunking, search | 3 |
| `chat/management/commands/ingest.py` | `manage.py ingest`: loads `data/` into ChromaDB | 3 |
| `data/sources.json`, `data/docs/` | The curated Medicare.gov dataset | 3 |

## Coming next
- Admin controls.
- Deployment to PythonAnywhere.
