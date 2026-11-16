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
from . import rag
from .llm import LLMError
from .prompts import build_system_prompt


#fake default search result to use in tests
def fake_passage(text="Part B covers doctor visits.", page=5, distance=0.2):
    return rag.Passage(
        text=text,
        title="Medicare & You",
        url="https://www.medicare.gov/publications/10050-medicare-and-you.pdf",
        page=page,
        distance=distance,
    )



class ChatPageTests(TestCase):
    def test_index_loads(self):
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Medicare Helper")


class AskApiTests(TestCase):
    def setUp(self):
        #every test gets a fake default passage unless it sets its own
        patcher = patch("chat.views.rag.search_conversation", return_value=[fake_passage()])
        self.mock_search = patcher.start()
        self.addCleanup(patcher.stop)
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
        self.assertEqual(history[1]["sources"], response.json()["sources"])
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

        self.mock_search.assert_called_with("How much does it cost?", "What is Part B?")
        self.assertTrue(all(set(m) == {"role", "content"} for m in sent_messages))

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


    #story 3 - answers are grounded in the documents

    @patch("chat.views.chat_completion", return_value="Part B covers doctor visits [1].")
    def test_passages_are_put_in_the_system_prompt(self, mock_llm):
        self.post_question("What does Part B cover?")
        system_prompt = mock_llm.call_args[0][0][0]["content"]
        self.assertIn("Part B covers doctor visits.", system_prompt)
        self.assertIn("[1]", system_prompt)
        self.assertIn("ONLY", system_prompt)

    @patch("chat.views.chat_completion", return_value="I couldn't find that.")
    def test_no_matching_passages_tells_model_not_to_guess(self, mock_llm):
        self.mock_search.return_value = []
        response = self.post_question("Who won the Super Bowl?")
        system_prompt = mock_llm.call_args[0][0][0]["content"]
        self.assertIn("Do not answer it from memory", system_prompt)
        self.assertEqual(response.json()["sources"], [])

    @patch("chat.views.chat_completion")
    def test_search_failure_returns_friendly_error(self, mock_llm):
        self.mock_search.side_effect = RuntimeError("store missing")
        with self.assertLogs("chat.views", level="ERROR"):
            response = self.post_question("What is Medicare?")
        self.assertEqual(response.status_code, 503)
        mock_llm.assert_not_called()

    #story 4 - user can see the sources

    @patch("chat.views.chat_completion", return_value="Answer [1] [2].")
    def test_sources_are_returned_with_page_links(self, mock_llm):
        self.mock_search.return_value = [
            fake_passage(page=5),
            fake_passage(text="More about Part B.", page=5), #same page so same source
            fake_passage(text="Part D covers drugs.", page=80),
        ]
        sources = self.post_question("What does Part B cover?").json()["sources"]
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["number"], 1)
        self.assertEqual(sources[0]["title"], "Medicare & You")
        self.assertTrue(sources[0]["url"].endswith(".pdf#page=5"))
        self.assertEqual(sources[1]["number"], 2)
        self.assertEqual(sources[1]["page"], 80)

    @patch("chat.views.chat_completion", return_value="Part B covers visits [2].")
    def test_only_cited_sources_are_shown(self, mock_llm):
        self.mock_search.return_value = [fake_passage(page=5), fake_passage(page=6)]
        sources = self.post_question("What does Part B cover?").json()["sources"]
        self.assertEqual([s["number"] for s in sources], [2])

    @patch("chat.views.chat_completion", return_value="Sorry, I can only help with Medicare.")
    def test_uncited_answer_shows_no_sources(self, mock_llm):
        sources = self.post_question("Who won the Super Bowl?").json()["sources"]
        self.assertEqual(sources, [])

    @patch("chat.views.chat_completion", return_value="Part B covers visits【1】 and tests【1†source】.")
    def test_odd_citation_brackets_are_normalized(self, mock_llm):
        data = self.post_question("What does Part B cover?").json()
        self.assertEqual(data["answer"], "Part B covers visits[1] and tests[1].")
        self.assertEqual(len(data["sources"]), 1)

    @patch("chat.views.chat_completion", return_value="Answer [1].")
    def test_sources_show_after_reload(self, mock_llm):
        self.post_question("What does Part B cover?")
        response = self.client.get(reverse("index"))
        self.assertContains(response, "Where this answer came from")
        self.assertContains(response, "10050-medicare-and-you.pdf#page=5")
        self.assertContains(
            response,
            'class="citation-link" href="https://www.medicare.gov/'
            'publications/10050-medicare-and-you.pdf#page=5"',
        )

    def test_linked_citations_keep_model_output_escaped(self):
        session = self.client.session
        session["history"] = [{
            "role": "assistant",
            "content": '<script>alert("unsafe")</script> See [1].',
            "sources": [{
                "number": 1,
                "title": "Medicare & You",
                "page": 5,
                "url": "https://example.com/guide.pdf#page=5",
            }],
        }]
        session.save()

        response = self.client.get(reverse("index"))

        self.assertNotContains(response, '<script>alert("unsafe")</script>')
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(
            response,
            'class="citation-link" href="https://example.com/guide.pdf#page=5"',
        )


#tests for the helper functions in rag.py
class RagHelperTests(TestCase):
    def test_clean_text_normalizes_unicode_and_control_characters(self):
        cleaned = rag.clean_text(
            "The ﬁrst “Medicare” guide…\u00a0has odd\u0000 text\ufffd."
        )

        self.assertEqual(
            cleaned,
            'The first "Medicare" guide... has odd text.',
        )

    def test_preprocess_removes_repeated_page_furniture(self):
        pages = [
            (
                page,
                f"Medicare Handbook 2026 - Page {page}\n"
                f"Unique coverage guidance for page {page}.\n"
                f"Page {page}",
            )
            for page in range(1, 5)
        ]

        cleaned = rag.preprocess(pages)

        self.assertEqual(len(cleaned), 4)
        self.assertTrue(all("Medicare Handbook" not in text for _, text in cleaned))
        self.assertTrue(all(f"Page {page}" not in text for page, text in cleaned))
        self.assertIn("Unique coverage guidance for page 3.", dict(cleaned)[3])

    def test_preprocess_skips_contents_pages_and_dot_leaders(self):
        pages = [
            (
                1,
                "Table of Contents\n"
                "Part A ................................ 4\n"
                "Part B ................................ 8\n"
                "Part D ................................ 12",
            ),
            (2, "Benefits overview\nCovered services are described in this section."),
        ]

        cleaned = rag.preprocess(pages)

        self.assertEqual(cleaned, [
            (2, "Benefits overview\nCovered services are described in this section."),
        ])

    def test_chunks_are_limited_in_size_and_overlap(self):
        text = " ".join(f"Sentence number {i} is about Medicare." for i in range(200))
        word_count = lambda value: len(value.split())
        chunks = rag.split_into_chunks(
            text,
            size=40,
            overlap=8,
            token_counter=word_count,
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(word_count(chunk) <= 40 for chunk in chunks))
        # Neighboring chunks retain a complete shared sentence.
        first_sentences = {sentence.rstrip(".") for sentence in chunks[0].split(". ")}
        second_sentences = {sentence.rstrip(".") for sentence in chunks[1].split(". ")}
        self.assertTrue(first_sentences & second_sentences)

    def test_short_text_is_skipped(self):
        self.assertEqual(
            rag.split_into_chunks("Page 4", token_counter=lambda value: len(value.split())),
            [],
        )

    def test_number_sources_shares_numbers_for_same_page(self):
        passages = [fake_passage(page=1), fake_passage(page=2), fake_passage(page=1)]
        sources = rag.number_sources(passages)
        self.assertEqual([p.number for p in passages], [1, 2, 1])
        self.assertEqual([s["page"] for s in sources], [1, 2])

    def test_system_prompt_labels_passages_with_their_numbers(self):
        passages = [fake_passage(text="Alpha text."), fake_passage(text="Beta text.", page=9)]
        rag.number_sources(passages)
        prompt = build_system_prompt(passages)
        self.assertIn("[1] (from \"Medicare & You\", page 5)\nAlpha text.", prompt)
        self.assertIn("[2] (from \"Medicare & You\", page 9)\nBeta text.", prompt)


# Story 8: larger text and high-contrast display settings
class DisplaySettingsTests(TestCase):
    def save_display(self, setting):
        return self.client.post(
            reverse("display"),
            data=json.dumps(setting),
            content_type="application/json",
        )

    def test_page_starts_with_normal_text_and_contrast(self):
        response = self.client.get(reverse("index"))
        self.assertContains(response, 'class="text-normal"')
        self.assertContains(response, "High contrast")

    def test_text_size_is_saved_and_shown_after_reload(self):
        response = self.save_display({"text_size": "larger"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text_size"], "larger")

        page = self.client.get(reverse("index"))
        self.assertContains(page, 'class="text-larger"')

    def test_high_contrast_is_saved_and_shown_after_reload(self):
        self.save_display({"high_contrast": True})
        page = self.client.get(reverse("index"))
        self.assertContains(page, 'class="text-normal high-contrast"')
        self.assertRegex(page.content.decode(), r'id="contrast-toggle"[^>]*aria-pressed="true"')

    def test_changing_one_setting_keeps_the_other(self):
        self.save_display({"text_size": "large"})
        response = self.save_display({"high_contrast": True})
        self.assertEqual(response.json(), {"text_size": "large", "high_contrast": True})

    def test_unknown_text_size_rejected(self):
        response = self.save_display({"text_size": "huge"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("display", self.client.session)

    @patch("chat.views.rag.search_conversation", return_value=[])
    @patch("chat.views.chat_completion", return_value="Answer")
    def test_new_chat_keeps_display_settings(self, mock_llm, mock_search):
        self.save_display({"text_size": "large", "high_contrast": True})
        self.client.post(
            reverse("ask"),
            data=json.dumps({"question": "What is Medicare?"}),
            content_type="application/json",
        )
        self.client.post(reverse("reset"))
        page = self.client.get(reverse("index"))
        self.assertContains(page, 'class="text-large high-contrast"')


# Story 9: a button that reads the chatbot's answers aloud
class ReadAloudTests(TestCase):
    def test_greeting_has_read_aloud_button(self):
        response = self.client.get(reverse("index"))
        self.assertContains(response, 'class="btn btn-secondary read-aloud" hidden', count=1)
        self.assertContains(response, "Read aloud")

    @patch("chat.views.rag.search_conversation", return_value=[])
    @patch("chat.views.chat_completion", return_value="Part B covers doctor visits.")
    def test_saved_answers_get_a_button_but_questions_do_not(self, mock_llm, mock_search):
        self.client.post(
            reverse("ask"),
            data=json.dumps({"question": "What does Part B cover?"}),
            content_type="application/json",
        )
        response = self.client.get(reverse("index"))
        # One for the greeting and one for the saved answer, none for the question.
        self.assertContains(response, 'class="btn btn-secondary read-aloud" hidden', count=2)
