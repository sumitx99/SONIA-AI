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
renderer = importlib.import_module("app.services.page_rendering")


def groq_reply(content, results):
    reply = response(200)
    reply.json.return_value = {"choices": [{"message": {"content": content, "executed_tools": [
        {"type": "browser.open", "search_results": {"results": results}}]}}]}
    return reply


PAGE = {"url": "https://official.example/pricing", "title": "Official pricing",
        "content": "L0: \nL1: Flash-Lite costs $0.25 per million input tokens."}


class BrowserRenderingTests(unittest.TestCase):
    def test_text_only_render_uses_content_endpoint(self):
        url = "https://example.com/"
        reply = response(200)
        reply.iter_content.return_value = [json.dumps({
            "success": True, "result": "<body>Rendered projects</body>",
        }).encode()]
        with patch.dict("os.environ", {"CLOUDFLARE_BROWSER_ACCOUNT_ID": "a" * 32,
                                      "CLOUDFLARE_BROWSER_API_TOKEN": "test-token"}), \
             patch.object(renderer, "public_addresses"), \
             patch.object(renderer.requests, "post", return_value=reply) as post:
            self.assertEqual(renderer.render_page(url, screenshot=False), ("Rendered projects", None))
        self.assertTrue(post.call_args.args[0].endswith("/browser-run/content"))
        self.assertNotIn("formats", post.call_args.kwargs["json"])

    def test_snapshot_returns_rendered_body_and_screenshot(self):
        url = "https://example.com/"
        reply = response(200)
        reply.iter_content.return_value = [json.dumps({
            "success": True, "meta": {"status": 200, "finalUrl": url},
            "result": {"content": "<head><title>Ignore</title></head><body>Rendered projects</body>",
                       "screenshot": "/9j/example"},
        }).encode()]
        with patch.dict("os.environ", {"CLOUDFLARE_BROWSER_ACCOUNT_ID": "a" * 32,
                                      "CLOUDFLARE_BROWSER_API_TOKEN": "test-token"}), \
             patch.object(renderer, "public_addresses") as public, \
             patch.object(renderer.requests, "post", return_value=reply) as post:
            self.assertEqual(renderer.render_page(url, screenshot=True), ("Rendered projects", "/9j/example"))
        public.assert_called_once_with("example.com")
        self.assertEqual(post.call_args.kwargs["json"]["url"], url)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])


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
    def test_exact_url_sent_to_search_opens_and_renders_the_requested_page(self):
        url = "https://example.com/"
        call = {"functionCall": {"id": "review", "name": "web_search", "args": {"query": url}}}
        rounds = iter([[call], [{"text": "The portfolio has a clear project section."}]])

        async def run():
            return [event async for event in agent.answer_with_tools(
                "user-1", f"{url}\n\ncan u rate this site", "", [], {})]

        with patch.object(agent, "URL_CONTEXT", True), \
             patch.object(agent, "stream_gemini_parts", side_effect=lambda *args: iter(next(rounds))) as model, \
             patch.object(agent, "read_source", return_value=""), \
             patch.object(agent, "render_page", return_value=("Projects", "/9j/test")) as render, \
             patch.object(agent, "search_web") as search:
            events = asyncio.run(run())

        search.assert_not_called()
        render.assert_called_once_with(url, screenshot=True)
        response = model.call_args.args[0][-1]["parts"][0]["functionResponse"]
        self.assertEqual(response["name"], "web_search")
        self.assertEqual(response["parts"][0]["inlineData"]["data"], "/9j/test")
        self.assertIn("Projects", response["response"]["result"])
        self.assertEqual(events[-1][0], "delta")

    def run_agent(self, rounds, search=None):
        seen = []

        def gemini(contents, declarations):
            seen.append([item["name"] for item in declarations])
            return iter(rounds[len(seen) - 1])

        async def main():
            return [event async for event in agent.answer_with_tools("user-1", "Gemini pricing?", "", [], {})]
        with patch.object(agent, "stream_gemini_parts", gemini), \
             patch.object(agent, "image_search_configured", return_value=False), \
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

    def test_backup_can_read_the_requested_page_and_rejects_an_unrequested_url(self):
        url = PAGE["url"]
        calls = [{"functionCall": {"name": "read_web_page", "args": {"url": target}}}
                 for target in ("https://other.example/", url)]
        rounds = iter([calls, [{"text": "The page lists pricing."}]])
        error = llm.requests.HTTPError(response=Mock(status_code=429))

        async def run():
            return [event async for event in agent.answer_with_tools(
                "user-1", f"Rate [this page]({url})", "", [], {})]

        with patch.object(agent, "stream_gemini_parts", side_effect=error), \
             patch.object(agent, "backup_configured", return_value=True), \
             patch.object(agent, "URL_CONTEXT", True), \
             patch.object(agent, "stream_tool_backup", side_effect=lambda *args, **kwargs: iter(next(rounds))) as backup, \
             patch.object(agent, "read_source", return_value="Flash-Lite pricing") as read:
            events = asyncio.run(run())

        read.assert_called_once_with(url, include_head=False)
        self.assertIn(llm.READ_WEB_PAGE_TOOL, backup.call_args_list[0].args[1])
        self.assertNotIn(llm.READ_WEB_PAGE_TOOL, backup.call_args_list[1].args[1])
        self.assertIn(("evidence", {"sources": [{"url": url, "title": url, "kind": "web",
                                               "text": "Flash-Lite pricing"}]}), events)


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
