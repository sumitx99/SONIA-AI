"""Inline citations: each quote is checked against the source the answer actually had."""

import json
import unittest
from unittest.mock import patch

from app.services import answer_verification as checker
from app.services.tool_evidence import tool_passages

PASSAGE = {"id": "D12", "kind": "document", "title": "attention.pdf", "document_id": 7, "chunk_id": 12,
           "text": "The big transformer model establishes a new state-of-the-art BLEU score of 28.4."}
CONTEXT = checker.MARKER + json.dumps({"sources": [PASSAGE]})
PAGE = "https://official.example/pricing"


def answer(entries, body="Transformer (big) reached 28.4 BLEU [1]."):
    return f"{body}\n\n```citations\n{json.dumps(entries)}\n```"


class CitationTests(unittest.TestCase):
    def test_document_quote_found_in_its_passage_is_verified(self):
        body, [citation] = checker.check_citations(
            answer([{"n": 1, "source": "D12", "quote": "new state-of-the-art BLEU score of 28.4"}]), CONTEXT)
        self.assertEqual(body, "Transformer (big) reached 28.4 BLEU [1].")
        self.assertEqual((citation["kind"], citation["document_id"], citation["verified"]), ("document", 7, True))

    def test_typography_differences_still_match_but_changed_words_do_not(self):
        smart = answer([{"n": 1, "source": "D12", "quote": "The big transformer model establishes a new state–of–the–art"}])
        changed = answer([{"n": 1, "source": "D12", "quote": "new state-of-the-art BLEU score of 29.1"}])
        self.assertTrue(checker.check_citations(smart, CONTEXT)[1][0]["verified"])
        self.assertFalse(checker.check_citations(changed, CONTEXT)[1][0]["verified"])

    def test_web_quote_is_checked_against_the_page_the_search_read(self):
        evidence = [{"kind": "web", "url": PAGE, "title": "Pricing", "text": "Flash-Lite costs $0.25 per million tokens."}]
        with patch.object(checker, "read_source") as fetch:
            _, [citation] = checker.check_citations(
                answer([{"n": 1, "source": PAGE, "quote": "Flash-Lite costs $0.25 per million tokens"}]), "", [], evidence)
        fetch.assert_not_called()
        self.assertEqual((citation["kind"], citation["url"], citation["verified"]), ("web", PAGE, True))

    def test_other_used_pages_are_fetched_once_but_invented_urls_never(self):
        sources = [{"url": PAGE, "title": "Pricing"}]
        entries = [{"n": 1, "source": PAGE, "quote": "costs $0.25 per million tokens"},
                   {"n": 2, "source": PAGE, "quote": "costs $0.25 per million tokens"},
                   {"n": 3, "source": "https://made-up.example/", "quote": "anything at all here"}]
        with patch.object(checker, "read_source", return_value="It costs $0.25 per million tokens.") as fetch:
            _, citations = checker.check_citations(answer(entries), "", sources)
        fetch.assert_called_once_with(PAGE)
        self.assertEqual([c["verified"] for c in citations], [True, True, False])
        self.assertEqual(citations[2]["kind"], "unknown")
        self.assertNotIn("url", citations[2])

    def test_tool_results_can_be_cited_by_their_id(self):
        evidence = [{"id": "Tab12cd34", "kind": "tool", "title": "Notes · Read note", "text": "Launch on Friday. Owner: Priya."}]
        _, [citation] = checker.check_citations(
            answer([{"n": 1, "source": "Tab12cd34", "quote": "Launch on Friday. Owner: Priya."}]), "", [], evidence)
        self.assertTrue(citation["verified"])

    def test_json_tool_quotes_match_decoded_field_text(self):
        title = 'Senior Software Engineer – MERN Stack\n"Platform" team'
        result = json.dumps({"data": {"jobs": [{"job_title": title, "employer_name": "Walkwel Technology"}]}})
        evidence = [{"id": "Tjobs", "kind": "tool", "title": "JSearch Jobs", "text": result}]
        entries = [{"n": 1, "source": "Tjobs", "quote": title},
                   {"n": 2, "source": "Tjobs", "quote": "Walkwel Technology"}]
        _, citations = checker.check_citations(answer(entries), "", [], evidence)
        self.assertEqual([c["verified"] for c in citations], [True, True])
        self.assertEqual(tool_passages(result)[0], {"path": '$["data"]["jobs"][0]["job_title"]', "text": title})

    def test_successful_tool_does_not_verify_assembled_or_changed_quotes(self):
        result = json.dumps({"jobs": [
            {"title": "Senior Software Engineer", "company": "Walkwel Technology", "city": "Mohali, Punjab"},
            {"title": "Full Stack Developer", "company": "Another company"}]})
        evidence = [{"id": "Tjobs", "kind": "tool", "title": "JSearch Jobs", "text": result}]
        quotes = ["Senior Software Engineer Company: Walkwel Technology Location: Mohali, Punjab",
                  "Walkwel Technology Full Stack Developer", "Salary: ₹85,000 per month"]
        entries = [{"n": n, "source": "Tjobs", "quote": quote} for n, quote in enumerate(quotes, 1)]
        _, citations = checker.check_citations(answer(entries), "", [], evidence)
        self.assertEqual([c["verified"] for c in citations], [False, False, False])

    def test_nested_gateway_json_is_decoded_without_trusting_unknown_sources(self):
        title = "Engineer – Platform"
        result = json.dumps({"content": [{"text": json.dumps({"title": title})}]})
        evidence = [{"id": "Tjobs", "kind": "tool", "title": "Jobs", "text": result}]
        entries = [{"n": 1, "source": "Tjobs", "quote": title},
                   {"n": 2, "source": "Tinvented", "quote": title}]
        _, citations = checker.check_citations(answer(entries), "", [], evidence)
        self.assertEqual([c["verified"] for c in citations], [True, False])

    def test_plain_or_truncated_tool_results_do_not_invent_decoded_excerpts(self):
        self.assertEqual(tool_passages("Plain source text."), [])
        self.assertEqual(tool_passages('{"jobs": [{"title": "Engineer…[truncated]'), [])

    def test_malformed_blocks_and_entries_are_ignored_safely(self):
        body, citations = checker.check_citations("Plain answer.\n\n```citations\nnot json\n```", CONTEXT)
        self.assertEqual((body, citations), ("Plain answer.", []))
        entries = [{"n": 0, "source": "D12", "quote": "x"}, {"n": 1, "source": "D12", "quote": 5},
                   {"n": 1, "source": "D12", "quote": "BLEU score of 28.4"}, {"n": 1, "source": "D12", "quote": "duplicate number"}]
        _, citations = checker.check_citations(answer(entries), CONTEXT)
        self.assertEqual([(c["n"], c["quote"]) for c in citations], [(1, "BLEU score of 28.4")])

    def test_long_quotes_are_shortened_and_plain_clients_get_footnotes(self):
        long_quote = " ".join(["word"] * 40)
        _, [citation] = checker.check_citations(answer([{"n": 1, "source": "D12", "quote": long_quote}]), CONTEXT)
        self.assertEqual(len(citation["quote"].split()), checker.MAX_QUOTE_WORDS)
        text = checker.with_footnotes("Answer [1].", [{**citation, "verified": False}])
        self.assertIn("[1] attention.pdf", text)
        self.assertIn("not verified", text)

    def test_wide_bracket_markers_become_chat_markers(self):
        body, _ = checker.check_citations(answer([], body="Scored 28.4 BLEU【1】 and more【12】."), CONTEXT)
        self.assertEqual(body, "Scored 28.4 BLEU[1] and more[12].")

    def test_an_unfinished_block_while_streaming_is_split_off(self):
        body, entries = checker.split_citations('Answer [1].\n\n```citations\n[{"n": 1, "sou')
        self.assertEqual((body, entries), ("Answer [1].", []))


if __name__ == "__main__":
    unittest.main()
