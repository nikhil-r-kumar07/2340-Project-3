"""
Web pages and API endpoints for the chatbot.

- index: shows the chat page (Story 1)
- ask:   receives a question, asks the model, returns the answer (Story 2)
- reset: clears the conversation for the "New chat" button (Story 2)
- display: saves the text size and high-contrast choices (Story 8)

The conversation is stored in the user's session (a cookie-linked record in
the database), so each visitor has their own chat without needing an account.
"""
import json
import logging
import re
import tempfile
from pathlib import Path

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import rag
from .forms import (
    PREPROCESSING_BOOLEAN_FIELDS,
    LocalSourceForm,
    UpdateSourceForm,
    UrlSourceForm,
)
from .llm import LLMError, chat_completion
from .prompts import build_system_prompt

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 1000
HISTORY_LIMIT = 10  # how many past messages to send the model for context

EXAMPLE_QUESTIONS = [
    "What does Medicare Part B cover?",
    "What is a deductible?",
    "When can I sign up for Medicare?",
    "What is the difference between Medicare and Medicaid?",
]

# Text size choices for the display settings bar (Story 8): (value, button label)
TEXT_SIZES = [
    ("normal", "Normal"),
    ("large", "Large"),
    ("larger", "Extra large"),
]
DEFAULT_DISPLAY = {"text_size": "normal", "high_contrast": False}


def get_display(request):
    """The visitor's saved display settings, with defaults filled in."""
    return {**DEFAULT_DISPLAY, **request.session.get("display", {})}


def index(request):
    history = request.session.get("history", [])
    return render(request, "chat/index.html", {
        "history": history,
        "examples": EXAMPLE_QUESTIONS,
        "display": get_display(request),
        "text_sizes": TEXT_SIZES,
    })


def manage_sources(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        raise PermissionDenied

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_local":
                form = LocalSourceForm(request.POST, request.FILES)
                if form.is_valid():
                    upload = form.cleaned_data["file"]
                    with tempfile.TemporaryDirectory() as temporary_directory:
                        uploaded_path = Path(temporary_directory) / Path(upload.name).name
                        with uploaded_path.open("wb") as destination:
                            for chunk in upload.chunks():
                                destination.write(chunk)
                        command_args = [
                            "sources", "add", "--local", str(uploaded_path),
                            "--title", form.cleaned_data["title"],
                        ]
                        _append_preprocessing_args(
                            command_args,
                            form.cleaned_data,
                            request.POST,
                        )
                        call_command(*command_args)
                    messages.success(request, "Source added. Ingest it to make it searchable.")
                else:
                    messages.error(request, _form_errors(form))
            elif action == "add_url":
                form = UrlSourceForm(request.POST)
                if form.is_valid():
                    command_args = [
                        "sources", "add", "--url", form.cleaned_data["url"],
                        "--title", form.cleaned_data["title"],
                    ]
                    _append_preprocessing_args(
                        command_args,
                        form.cleaned_data,
                        request.POST,
                    )
                    call_command(*command_args)
                    messages.success(request, "URL source added. Ingest it to make it searchable.")
                else:
                    messages.error(request, _form_errors(form))
            elif action == "update":
                file_name = request.POST.get("file", "")
                form = UpdateSourceForm(request.POST, request.FILES)
                if form.is_valid():
                    command_args = ["sources", "update", file_name]
                    if form.cleaned_data["title"]:
                        command_args.extend(["--title", form.cleaned_data["title"]])
                    if form.cleaned_data["url"]:
                        command_args.extend(["--url", form.cleaned_data["url"]])
                    _append_preprocessing_args(
                        command_args,
                        form.cleaned_data,
                        request.POST,
                    )
                    upload = form.cleaned_data["file"]
                    if upload:
                        with tempfile.TemporaryDirectory() as temporary_directory:
                            uploaded_path = Path(temporary_directory) / Path(upload.name).name
                            with uploaded_path.open("wb") as destination:
                                for chunk in upload.chunks():
                                    destination.write(chunk)
                            command_args.extend(["--from-file", str(uploaded_path)])
                            call_command(*command_args)
                    else:
                        call_command(*command_args)
                    messages.success(request, "Source updated. Re-ingest it to refresh searchable content.")
                else:
                    messages.error(request, _form_errors(form))
            elif action in {"ingest", "remove"}:
                file_name = request.POST.get("file", "")
                if action == "ingest":
                    call_command("ingest", "--source", file_name)
                    messages.success(request, f"{file_name} ingested and searchable.")
                else:
                    call_command("sources", "remove", file_name)
                    messages.success(request, f"{file_name} removed from the catalog and search index.")
            else:
                messages.error(request, "Choose a valid source action.")
        except CommandError as error:
            messages.error(request, str(error))
        except OSError as error:
            messages.error(request, f"Could not read or save the source file: {error}")
        return redirect("manage_sources")

    try:
        sources = rag.load_manifest()
    except FileNotFoundError:
        sources = []
    except json.JSONDecodeError as error:
        sources = []
        messages.error(request, f"Could not read data/sources.json: {error}")

    try:
        indexed_files = rag.indexed_source_files()
    except Exception:
        logger.exception("Could not read source indexing status")
        indexed_files = None

    for source in sources:
        source["preprocessing"] = rag.preprocessing_options(source)
        if indexed_files is None:
            source["index_status"] = "unknown"
        elif source["file"] in indexed_files:
            source["index_status"] = "indexed"
        else:
            source["index_status"] = "pending"

    indexed_count = sum(source["index_status"] == "indexed" for source in sources)
    pending_count = sum(source["index_status"] == "pending" for source in sources)
    return render(request, "chat/manage_sources.html", {
        "sources": sources,
        "preprocessing_defaults": rag.DEFAULT_PREPROCESSING_OPTIONS,
        "source_count": len(sources),
        "indexed_count": indexed_count,
        "pending_count": pending_count,
        "index_status_available": indexed_files is not None,
    })


def _append_preprocessing_args(command_args, cleaned_data, submitted_data):
    for field in PREPROCESSING_BOOLEAN_FIELDS:
        if field in submitted_data:
            option = field.replace("_", "-")
            command_args.append(f"--{option}" if cleaned_data[field] else f"--no-{option}")
    if (
        "minimum_chunk_length" in submitted_data
        and cleaned_data.get("minimum_chunk_length") is not None
    ):
        command_args.extend([
            "--minimum-chunk-length",
            str(cleaned_data["minimum_chunk_length"]),
        ])


def _form_errors(form):
    return " ".join(error for errors in form.errors.values() for error in errors)


@require_POST
def ask(request):
    # 1. Read and check the question
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request."}, status=400)

    question = str(data.get("question", "")).strip()
    if not question:
        return JsonResponse({"error": "Please type a question."}, status=400)
    if len(question) > MAX_QUESTION_LENGTH:
        return JsonResponse(
            {"error": f"Please keep your question under {MAX_QUESTION_LENGTH} characters."},
            status=400,
        )

    # 2. Build the message list: instructions + recent conversation + new question
    history = request.session.get("history", [])
    # TODO (Story 3/4): retrieve relevant Medicare passages here and include them + their sources.
    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    try:
        passages = rag.search_conversation(question, previous)
    except Exception:
        #dont fall back to an ungrounded answer if search breaks, just show an error
        logger.exception("Retrieval failed")
        return JsonResponse(
            {"error": "Sorry, I can't look up Medicare information right now. Please try again in a minute."},
            status=503,
        )
    sources = rag.number_sources(passages)
    recent = [{"role": m["role"], "content": m["content"]} for m in history[-HISTORY_LIMIT:]]
    
    messages = (
        [{"role": "system", "content": build_system_prompt(passages)}]
        + recent
        + [{"role": "user", "content": question}]
    )

    # 3. Ask the model
    try:
        answer = chat_completion(messages)
    except LLMError:
        return JsonResponse(
            {"error": "Sorry, I'm having trouble answering right now. Please try again in a minute."},
            status=503,
        )

    answer = normalize_citations(answer)
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    sources = [s for s in sources if s["number"] in cited]

    # 4. Save both turns so follow-up questions have context
    history += [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer, "sources": sources},
    ]
    request.session["history"] = history

    return JsonResponse({"answer": answer, "sources": sources})

def normalize_citations(answer):
    return re.sub(r"【(\d+)[^】]*】", r"[\1]", answer)

@require_POST
def reset(request):
    request.session["history"] = []
    return JsonResponse({"ok": True})


@require_POST
def display(request):
    # Only the settings that were sent are changed, so each button can save on its own.
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request."}, status=400)

    current = get_display(request)
    if "text_size" in data:
        if data["text_size"] not in [value for value, _ in TEXT_SIZES]:
            return JsonResponse({"error": "Unknown text size."}, status=400)
        current["text_size"] = data["text_size"]
    if "high_contrast" in data:
        current["high_contrast"] = bool(data["high_contrast"])

    # Kept in the session (like the chat history), so it stays after a reload or "New chat".
    request.session["display"] = current
    return JsonResponse(current)
