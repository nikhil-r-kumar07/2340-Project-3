"""
Talks to the language model (Story 2).

This is the ONLY file that knows how to reach the LLM. It uses the
"OpenAI-compatible" chat format, which Groq, Ollama and many other providers
all accept. To switch models or providers, change LLM_BASE_URL / LLM_MODEL /
LLM_API_KEY in .env. No code changes needed.
"""
import re

import requests
from django.conf import settings


class LLMError(Exception):
    """Raised when the model can't be reached or returns something unexpected."""


def chat_completion(messages):
    """
    Send a list of chat messages to the model and return its reply as text.

    `messages` looks like:
        [{"role": "system", "content": "..."},
         {"role": "user", "content": "What is Part B?"}]
    """
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"

    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:  # local Ollama doesn't need a key
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"

    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": 0.3,  # lower = more consistent, factual answers
    }
    if settings.LLM_REASONING_EFFORT:  # only for reasoning models like gpt-oss
        payload["reasoning_effort"] = settings.LLM_REASONING_EFFORT

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as error:
        raise LLMError(str(error)) from error

    # Some reasoning models print their "thinking" inside <think> tags; hide it.
    answer = re.sub(r"<think>.*?</think>", "", answer or "", flags=re.DOTALL)
    return answer.strip()
