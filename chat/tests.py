"""
Tests for the chat pages and API (Stories 1 & 2).

The real model is never called: `patch` swaps chat_completion for a fake,
so tests run offline, fast, and without using up API rate limits.
Run with:  python manage.py test chat
"""
import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .llm import LLMError


class ChatPageTests(TestCase):
    def test_index_loads(self):
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Medicare Helper")


class AskApiTests(TestCase):
    def post_question(self, question):
        return self.client.post(
            reverse("ask"),
            data=json.dumps({"question": question}),
            content_type="application/json",
        )

    @patch("chat.views.chat_completion", return_value="Part B covers doctor visits.")
    def test_ask_returns_answer_and_saves_history(self, mock_llm):
        response = self.post_question("What does Part B cover?")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Part B covers doctor visits.")

        history = self.client.session["history"]
        self.assertEqual(history[0], {"role": "user", "content": "What does Part B cover?"})
        self.assertEqual(history[1]["role"], "assistant")

        # The system prompt is sent first, the question last.
        sent_messages = mock_llm.call_args[0][0]
        self.assertEqual(sent_messages[0]["role"], "system")
        self.assertEqual(sent_messages[-1]["content"], "What does Part B cover?")

    @patch("chat.views.chat_completion", return_value="It costs a monthly premium.")
    def test_follow_up_includes_previous_turns(self, mock_llm):
        self.post_question("What is Part B?")
        self.post_question("How much does it cost?")

        sent_messages = mock_llm.call_args[0][0]
        self.assertIn({"role": "user", "content": "What is Part B?"}, sent_messages)

    def test_empty_question_rejected(self):
        response = self.post_question("   ")
        self.assertEqual(response.status_code, 400)

    def test_too_long_question_rejected(self):
        response = self.post_question("a" * 1001)
        self.assertEqual(response.status_code, 400)

    @patch("chat.views.chat_completion", side_effect=LLMError("down"))
    def test_llm_failure_returns_friendly_error(self, mock_llm):
        response = self.post_question("What is Medicare?")
        self.assertEqual(response.status_code, 503)
        self.assertIn("trouble", response.json()["error"])

    @patch("chat.views.chat_completion", return_value="Answer")
    def test_reset_clears_history(self, mock_llm):
        self.post_question("What is Medicare?")
        response = self.client.post(reverse("reset"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["history"], [])
