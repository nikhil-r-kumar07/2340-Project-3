# Medicare Helper

A chatbot that helps older adults with low health literacy understand Medicare in plain language.
CS 2340 Project 3.

**Sprint 1 so far:**
- **Story 1:** reach the chatbot through a web app.
- **Story 2:** ask natural-language Medicare questions and get relevant answers.

## Tech stack
- **Django 5:** web server, pages and sessions, with SQLite.
- **Plain HTML/CSS/JavaScript:** no build step.
- **LLM:** OpenAI's open-weights `gpt-oss-120b`, hosted free on [Groq](https://console.groq.com).
  - It's called through the standard OpenAI-compatible chat API using `requests` (`chat/llm.py`).

## Setup
```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then put your own Groq API key in .env
python manage.py migrate
python manage.py runserver
```
Open http://127.0.0.1:8000.

Each teammate should create their own free Groq key, since rate limits are per key.

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
The tests use a fake model, so they need no internet connection or API key.

## How a question flows
1. `chat/static/chat/chat.js` sends the question to `POST /api/ask/`.
2. `chat/views.py` (`ask`) checks the question. It then builds the message list: system prompt + last 10 messages + the new question.
3. `chat/llm.py` (`chat_completion`) sends that list to the LLM and returns the reply text.
4. The view saves the conversation in the session and returns the answer as JSON. The page then shows it.

## Project layout
| File | What it does | Story |
|---|---|---|
| `config/settings.py` | Django settings, read from `.env` | 1 |
| `config/urls.py`, `chat/urls.py` | URL routes | 1 |
| `templates/base.html` | Page shell: header, footer, disclaimer | 1 |
| `chat/templates/chat/index.html` | Chat page | 1 |
| `chat/static/chat/style.css` | Styles: large text, high legibility, mobile-friendly | 1 |
| `chat/static/chat/chat.js` | Sends questions and shows answers without reloading | 1 |
| `chat/views.py` | `index`, `ask` and `reset` endpoints | 2 |
| `chat/llm.py` | The only code that talks to the LLM | 2 |
| `chat/prompts.py` | System prompt: plain language, Medicare-only, safe | 2 |
| `chat/tests.py` | Automated tests | 2 |

## Coming next
- RAG with ChromaDB and the `bge-small-en-v1.5` embeddings (stories 3–7).
- Source citations.
- Data ingestion.
- Admin controls.
- Text-size and high-contrast modes.
- Read-aloud.
- Deployment to PythonAnywhere.
