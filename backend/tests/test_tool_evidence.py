"""Bounded MCP source data stays valid and is the exact data citations check."""
import json
import unittest

from mcp import types
from app.mcp_client.session import MAX_RESULT_CHARS, result_text
from app.services.answer_verification import check_citations
from app.services.tool_evidence import bounded_tool_text, tool_passages


class ToolEvidenceTests(unittest.TestCase):
    def result(self, text, structured=None, error=False):
        return result_text(types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            structuredContent=structured, isError=error))

    def verifies(self, source, quote):
        answer = 'Answer [1].\n```citations\n' + json.dumps([
            {"n": 1, "source": "Ttest", "quote": quote}]) + '\n```'
        return check_citations(answer, "", [], [
            {"id": "Ttest", "kind": "tool", "title": "Test", "text": source}])[1][0]["verified"]

    def test_long_json_keeps_fields_intact_under_the_existing_limit(self):
        title = 'Senior Software Engineer – "Platform"'
        original = {"jobs": [{"title": title, "description": "long description " * 1000,
                               "company": "Walkwel Technology", "salary": 85000},
                              {"title": "Full Stack Developer", "company": "Second company"}]}
        source, error = self.result(json.dumps(original))
        self.assertLessEqual(len(source), MAX_RESULT_CHARS)
        decoded = json.loads(source)
        self.assertTrue(decoded["_sonia_truncated"])
        first, second = decoded["result"]["jobs"]
        self.assertEqual(first, {key: value for key, value in original["jobs"][0].items() if key != "description"})
        self.assertEqual(second, original["jobs"][1])
        self.assertTrue(self.verifies(source, title))
        self.assertTrue(self.verifies(source, "Walkwel Technology"))
        self.assertFalse(self.verifies(source, "long description long description"))
        self.assertFalse(error)

    def test_structured_data_is_preserved_instead_of_summary_or_duplicate(self):
        data = {"jobs": [{"title": "Backend Developer", "salary": 85000}]}
        source, _ = self.result("Search completed.", data)
        self.assertEqual(json.loads(source), data)
        self.assertNotIn("Search completed", source)
        self.assertTrue(self.verifies(source, "Backend Developer"))
        empty, _ = self.result("Search completed.", {})
        self.assertEqual(json.loads(empty), {})

    def test_multiple_json_blocks_and_plain_text_keep_parseable_structure(self):
        source, _ = result_text(types.CallToolResult(content=[
            types.TextContent(type="text", text='{"title":"Backend Developer"}'),
            types.TextContent(type="text", text='Additional exact source text. ' * 1000)]))
        self.assertLessEqual(len(source), MAX_RESULT_CHARS)
        self.assertEqual(json.loads(source)["result"], [{"title": "Backend Developer"}])

    def test_many_records_respect_budget_and_retained_values_are_original(self):
        original = [{"title": f"Engineer position {index}", "company": "Source company"} for index in range(1000)]
        source = bounded_tool_text(original, MAX_RESULT_CHARS)
        retained = json.loads(source)["result"]
        self.assertLessEqual(len(source), MAX_RESULT_CHARS)
        self.assertGreater(len(retained), 0)
        self.assertLess(len(retained), len(original))
        for index, item in enumerate(retained):
            for key, value in item.items():
                self.assertEqual(value, original[index][key])

    def test_plain_text_retains_marked_prefix_and_error_status(self):
        source, error = self.result("error details " * 1000, error=True)
        self.assertLessEqual(len(source), MAX_RESULT_CHARS)
        self.assertTrue(source.endswith("…[truncated]"))
        self.assertTrue(error)
        self.assertEqual(self.result("Short tool result.")[0], "Short tool result.")

    def test_oversized_scalar_is_omitted_not_rewritten_as_a_quote(self):
        source = bounded_tool_text({"message": "x" * 10000}, MAX_RESULT_CHARS)
        self.assertEqual(json.loads(source), {"result": None, "_sonia_truncated": True})

    def test_decoded_quote_after_1200_characters_is_still_checked(self):
        value = "word " * 300 + "Engineer – Platform"
        source = bounded_tool_text({"description": value}, MAX_RESULT_CHARS)
        self.assertEqual(tool_passages(source)[0]["text"], value)
        self.assertTrue(self.verifies(source, "Engineer – Platform"))


if __name__ == "__main__":
    unittest.main()
