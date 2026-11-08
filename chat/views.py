"""
Web pages and API endpoints for the chatbot.

- index: shows the chat page (Story 1)
- ask:   receives a question, asks the model, returns the answer (Story 2)
- reset: clears the conversation for the "New chat" button (Story 2)

The conversation is stored in the user's session (a cookie-linked record in
the database), so each visitor has their own chat without needing an account.
"""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .llm import LLMError, chat_completion
from .prompts import SYSTEM_PROMPT

MAX_QUESTION_LENGTH = 1000
HISTORY_LIMIT = 10  # how many past messages to send the model for context

EXAMPLE_QUESTIONS = [
    "What does Medicare Part B cover?",
    "What is a deductible?",
    "When can I sign up for Medicare?",
    "What is the difference between Medicare and Medicaid?",
]


def index(request):
    history = request.session.get("history", [])
    return render(request, "chat/index.html", {
        "history": history,
        "examples": EXAMPLE_QUESTIONS,
    })


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
    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history[-HISTORY_LIMIT:]
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

    # 4. Save both turns so follow-up questions have context
    history += [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]
    request.session["history"] = history

    return JsonResponse({"answer": answer})


@require_POST
def reset(request):
    request.session["history"] = []
    return JsonResponse({"ok": True})
