"""Web search: Gemini's Google Search when it has quota, otherwise Groq browser search as a tool."""

import asyncio
import importlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

from test_llm import response

parser = types.ModuleType("app.services.parsing.docling_utils")
parser.process_pdf_with_docling = Mock()
parser.docling_enabled = Mock(return_value=False)
sys.modules.setdefault("app.services.parsing.docling_utils", parser)
llm = importlib.import_module("app.services.llm")
agent = importlib.import_module("app.mcp_client.agent")


def groq_reply(content, results):
    reply = response(200)
    reply.json.return_value = {"choices": [{"message": {"content": content, "executed_tools": [
        {"type": "browser.open", "search_results": {"results": results}}]}}]}
    return reply


PAGE = {"url": "https://official.example/pricing", "title": "Official pricing",
        "content": "L0: \nL1: Flash-Lite costs $0.25 per million input tokens."}


class GoogleSearchQuotaTests(unittest.TestCase):
    def setUp(self):
        llm._search_paused_until = 0.0
        self.addCleanup(setattr, llm, "_search_paused_until", 0.0)

    def test_rate_limited_search_pauses_search_without_losing_the_question(self):
        with patch.object(llm.requests, "post", return_value=response(429)) as post, \
             self.assertLogs("app.services.llm", level="WARNING"):
            parts = list(llm.stream_gemini_parts(llm.conversation_turns("Latest pricing?", ""), []))
        self.assertEqual(parts, [{"searchUnavailable": True}])
        self.assertEqual(post.call_count, 1)
        self.assertFalse(llm.google_search_ready())

    def test_billing_and_quota_errors_hand_over_to_the_backup(self):
        error = lambda status: llm.requests.HTTPError(response=Mock(status_code=status))
        self.assertTrue(llm.gemini_unavailable(error(402)))
        self.assertTrue(llm.gemini_unavailable(error(429)))
        self.assertFalse(llm.gemini_unavailable(error(403)))


class WebSearchToolTests(unittest.TestCase):
    def run_agent(self, rounds, search=None):
        seen = []

        def gemini(contents, declarations):
            seen.append([item["name"] for item in declarations])
            return iter(rounds[len(seen) - 1])

        async def main():
            return [event async for event in agent.answer_with_tools("user-1", "Gemini pricing?", "", [], {})]
        with patch.object(agent, "stream_gemini_parts", gemini), \
             patch.object(agent, "google_search_ready", return_value=False), \
             patch.object(agent, "web_search_available", return_value=True), \
             patch.object(agent, "search_web", search or Mock()):
            return asyncio.run(main()), seen

    def test_paused_google_search_offers_the_web_search_tool(self):
        _, seen = self.run_agent([[{"text": "Answer."}]])
        self.assertEqual(seen, [["web_search"]])

    def test_a_refused_search_asks_again_with_the_tool(self):
        events, seen = self.run_agent([[{"searchUnavailable": True}], [{"text": "Answer."}]])
        self.assertEqual(len(seen), 2)
        self.assertEqual(events, [("delta", {"text": "Answer."})])

    def test_web_search_returns_findings_links_and_page_text(self):
        search = Mock(return_value=("- $0.25 per million (https://official.example/pricing)",
                                    [{"url": PAGE["url"], "title": PAGE["title"]}],
                                    [{"url": PAGE["url"], "title": PAGE["title"], "text": "Flash-Lite costs $0.25"}]))
        call = [{"functionCall": {"name": "web_search", "args": {"query": "gemini pricing"}, "id": "c1"}}]
        events, _ = self.run_agent([call, [{"text": "It costs $0.25 [1]."}]], search)
        names = [name for name, _ in events]
        self.assertEqual(names, ["tool_call", "sources", "evidence", "tool_call", "delta"])
        self.assertEqual(events[3][1]["status"], "done")
        self.assertEqual(events[2][1]["sources"][0]["kind"], "web")
        search.assert_called_once_with("gemini pricing")


class GroqSearchTests(unittest.TestCase):
    def test_search_web_tries_the_next_model_and_keeps_page_text(self):
        with patch.object(llm, "GROQ_API_KEY", "k"), patch.object(llm, "GROQ_MODELS", ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]), \
             patch.object(llm.requests, "post", side_effect=[response(429), groq_reply("Findings 【1†L1-L1】", [PAGE])]) as post, \
             self.assertLogs("app.services.llm", level="WARNING"):
            findings, links, pages = llm.search_web("gemini pricing")
        self.assertEqual(findings, "Findings")
        self.assertEqual(links, [{"url": PAGE["url"], "title": PAGE["title"]}])
        self.assertEqual(pages[0]["text"].strip(), "Flash-Lite costs $0.25 per million input tokens.")
        self.assertEqual([call.kwargs["json"]["model"] for call in post.call_args_list],
                         ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
        for call in post.call_args_list:
            self.assertEqual(call.kwargs["json"]["tools"], [{"type": "browser_search"}])

    def test_backup_answer_shares_source_links_and_page_text(self):
        with patch.object(llm, "GROQ_API_KEY", "k"), patch.object(llm, "GROQ_WEB_SEARCH", True), \
             patch.object(llm.requests, "post", return_value=groq_reply("Answer [1]", [PAGE])):
            events = dict(event for event in llm.groq_web_answer("Gemini pricing?", "") if event[0] != "model")
        self.assertEqual(events["sources"], {"sources": [{"url": PAGE["url"], "title": PAGE["title"]}]})
        self.assertIn("$0.25", events["evidence"]["sources"][0]["text"])
        self.assertNotIn("gpt-oss", json.dumps(events.get("tool_call", {})))


if __name__ == "__main__":
    unittest.main()
