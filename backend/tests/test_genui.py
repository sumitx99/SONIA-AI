import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import chat
from app.api.conversations import SavedMessage
from app.services.genui import EXAMPLES, GenUISpec, GenUIStream, _fence

ROOT = {"id": "root", "type": "column"}
BUTTON = {"id": "toggle", "parent": "root", "type": "button",
          "label": "Three instances", "key": "mode", "value": "multiple"}
# A control stays only while something reads its state.
NOTE = {"id": "note", "parent": "root", "type": "text", "content": "Three instances share the load.",
        "visible_when": {"key": "mode", "equals": "multiple"}}
CHART = {"id": "speed", "parent": "root", "type": "chart", "title": "Speed",
         "chart_type": "bar", "x_label": "Language", "y_label": "Time (ms)",
         "data": [{"name": "Python", "value": 120, "citation": 1}]}
START = {"version": "2.0", "initial_state": {"mode": "single"}}


def block(*nodes, close=True):
    lines = ["```genui\n", *(json.dumps(item) + "\n" for item in (START, *nodes))]
    return "".join(lines) + ("```\n" if close else "")


async def run_answer(parts, *, citations=(), query="Explain scaling"):
    async def model(*args, **kwargs):
        for item in parts:
            yield ("delta", {"text": item}) if isinstance(item, str) else item

    def check(draft, *_args):
        return draft.rstrip(), citations

    with patch.object(chat, "answer_with_tools", model), patch.object(chat, "check_citations", check):
        return [event async for event in chat._answer_events("user", query, "", [], {}, [])]


class GenUITests(unittest.IsolatedAsyncioTestCase):
    async def test_split_model_chunks_stream_ui_and_keep_grounding_offsets(self):
        lead, end = "First 🚀.\n\n", "Final paragraph."
        raw = lead + block(ROOT, BUTTON, NOTE, CHART) + end
        position = len(raw.encode("utf-16-le")) // 2
        inside = len((lead + "```genui\n" + '{"version"').encode("utf-16-le")) // 2
        citation = {"url": "https://example.com", "title": "Example"}
        # Exercise fences and JSON objects split in the middle by provider deltas.
        events = await run_answer([
            *list(raw[:inside - 1]), ("inline_citation", {**citation, "position": inside}),
            *list(raw[inside - 1:]), ("inline_citation", {**citation, "position": position}),
        ], citations=[{"n": 1, "quote": "Python 120 ms", "verified": True}])
        text = "".join(value["text"] for kind, value in events if kind == "delta")
        self.assertEqual(text, lead + end)
        self.assertEqual([value["position"] for kind, value in events if kind == "inline_citation"],
                         [len(text.encode("utf-16-le")) // 2])
        previews = [value["spec"] for kind, value in events[:-1] if kind == "ui_spec"]
        self.assertTrue(any(BUTTON in spec["nodes"] for spec in previews))
        self.assertTrue(all(CHART not in spec["nodes"] for spec in previews))
        self.assertEqual(events[-2][0], "citations")
        spec = events[-1][1]["spec"]
        self.assertEqual(spec["nodes"][-1], CHART)
        message = SavedMessage.model_validate({"id": "answer", "sender": "bot", "content": text,
                                               "ui_spec": spec})
        self.assertEqual(message.ui_spec.nodes[-1].data[0].value, 120)

    async def test_incomplete_and_invalid_fences_discard_the_preview(self):
        for source in [block(ROOT, BUTTON, close=False),
                       block(ROOT, BUTTON, {**BUTTON, "onclick": "fetch()"})]:
            events = await run_answer(["Explanation.\n", source])
            self.assertEqual(events[-1], ("ui_spec", {"spec": None, "incomplete": True}))
            self.assertEqual(events[-2][1]["answer"], "Explanation.")

    async def test_later_blocks_join_the_visual_and_only_bad_records_are_dropped(self):
        first = block(ROOT, BUTTON, NOTE)
        second = {"id": "second", "parent": "root", "type": "text", "content": "Second visual."}
        # A heading between records is not a record; the second block reuses the root ID.
        joined = first + "\nMore prose.\n" + block(ROOT, second).replace("```genui\n", "```genui\n# Second\n", 1)
        events = await run_answer(["Explanation.\n", joined])
        self.assertEqual(events[-2][1]["answer"], "Explanation.\n\nMore prose.")
        nodes = events[-1][1]["spec"]["nodes"]
        self.assertEqual([(node["id"], node.get("parent")) for node in nodes],
                         [("root", None), ("toggle", "root"), ("note", "root"), ("root2", "root"), ("second", "root2")])
        kept = [ROOT, BUTTON, NOTE]
        joined = [{"id": "root2", "parent": "root", "type": "column"}, {**second, "parent": "root2"}]
        for bad, nodes in [
            # A component that fails validation; its emptied container is left out.
            (block(ROOT, {**second, "id": "note"}), kept),
            # An answer cut off inside a block keeps that block's valid records.
            (block(ROOT, second, close=False), kept + joined),
            # A later block that redefines state cannot be checked at all.
            (block(ROOT, second).replace('"single"', '"other"'), kept),
            # Malformed JSON ends its block; the records before it stay.
            (block(ROOT, second).replace("```\n", '{"id": "broken", "parent"\n```\n'), kept + joined),
        ]:
            events = await run_answer(["Explanation.\n", first, bad])
            self.assertEqual(events[-1], ("ui_spec", {"spec": {**START, "nodes": nodes}, "incomplete": True}))

    async def test_unverified_or_ambiguous_data_never_appears_in_chart(self):
        for quote, verified in [("Python 120 ms", False), ("Python 60 ms; Java 120 ms", True)]:
            events = await run_answer(["Explanation.\n", block(ROOT, CHART)],
                                      citations=[{"n": 1, "quote": quote, "verified": verified}])
            self.assertIsNone(events[-1][1]["spec"])
        chart = {**CHART, "data": [{"name": "Python", "value": 120}]}
        events = await run_answer(["Explanation.\n", block(ROOT, chart)], query="Chart this:\nPython: 120ms")
        self.assertEqual(events[-1][1]["spec"]["nodes"][-1], chart)
        # Every point of a series chart needs its category, its series and its own value.
        series = {**CHART, "chart_type": "line", "data": [
            {"name": "2023", "series": "Python", "value": 120, "citation": 1},
            {"name": "2023", "series": "Java", "value": 95.5, "citation": 2}]}
        for java, kept in [("Java took 95.5 ms in 2023", True), ("In 2023 the JVM took 95.5 ms", False)]:
            events = await run_answer(["Explanation.\n", block(ROOT, series)], citations=[
                {"n": 1, "quote": "2023: Python, 120 ms", "verified": True}, {"n": 2, "quote": java, "verified": True}])
            self.assertEqual(events[-1][1]["spec"] is not None, kept)

    async def test_examples_inside_other_fences_remain_code(self):
        text = "````markdown\n" + block(ROOT) + "````"
        events = await run_answer(list(text))
        self.assertEqual(events[-1][1]["answer"], text)
        self.assertFalse(any(kind == "ui_spec" for kind, _ in events))

    async def test_walkthroughs_describe_structure_and_never_geometry_or_controls(self):
        diagram = {
            "id": "route", "type": "diagram", "title": "Request path", "direction": "down", "build": True,
            "groups": [{"id": "backend", "label": "Backend"}],
            "nodes": [{"id": "client", "label": "Client", "kind": "actor"},
                      {"id": "server", "label": "Server", "group": "backend", "tone": "accent"}],
            "edges": [{"id": "routeEdge", "source": "client", "target": "server", "label": "HTTPS"}],
            "steps": [{"caption": "The client calls the server.", "focus": ["server"], "flow": ["routeEdge"]}],
        }
        events = await run_answer(["Explanation.\n", block(diagram)])
        self.assertEqual(events[-1][1]["spec"]["nodes"], [diagram])
        for extra in [{"controls": [{"type": "button", "label": "Play"}]},
                      {"nodes": [{**diagram["nodes"][0], "x": 0, "y": 0}, diagram["nodes"][1]]},
                      {"steps": [{"caption": "Nothing happens."}]}]:
            events = await run_answer(["Explanation.\n", block({**diagram, **extra})])
            self.assertEqual(events[-1], ("ui_spec", {"spec": None, "incomplete": True}))

    async def test_multiline_records_keep_both_views_and_drop_controls_nothing_reads(self):
        diagram = {
            "id": "diagram", "parent": "root", "type": "diagram", "title": "One server",
            "visible_when": {"key": "mode", "equals": "single"},
            "nodes": [{"id": "balancer", "label": "Balancer"}, {"id": "server", "label": "Server"}],
            "edges": [{"id": "request", "source": "balancer", "target": "server"}],
        }
        scaled = {
            **diagram, "id": "scaled", "title": "Three servers",
            "visible_when": {"key": "mode", "equals": "multiple"},
            "steps": [{"caption": "Requests spread out.", "flow": ["request"]}],
        }
        play = {**BUTTON, "id": "play", "key": "play", "label": "Play", "value": True}
        # The play button changes nothing whether or not its key was declared.
        for state in [START["initial_state"], {**START["initial_state"], "play": False}]:
            records = [{**START, "initial_state": state}, ROOT, BUTTON, play, diagram, scaled]
            source = "```genui\n" + "\n".join(json.dumps(record, indent=2) for record in records) + "\n```"
            events = await run_answer(["Explanation.\n", *list(source)])
            final = events[-1][1]["spec"]
            self.assertEqual([node["id"] for node in final["nodes"]], ["root", "toggle", "diagram", "scaled"])
            self.assertEqual(final["nodes"][-1]["steps"], scaled["steps"])

    def test_composition_rejects_dangling_edges_and_mismatched_state(self):
        diagram = {"id": "diagram", "type": "diagram", "title": "Request path",
                   "nodes": [{"id": "client", "label": "Client"}],
                   "edges": [{"id": "request", "source": "client", "target": "missing"}]}
        chart = {**CHART, "data": [{"name": "Python", "series": "Run", "value": 1}], "series_key": "missing"}
        for nodes in [[diagram], [ROOT, {**BUTTON, "value": 10}], [ROOT, chart],
                      [ROOT, {**CHART, "chart_type": "pie", "data": [{"name": "Python", "value": -1}]}]]:
            with self.assertRaises(ValidationError):
                GenUISpec.model_validate({**START, "nodes": nodes})

    def test_instruction_samples_are_valid_and_old_saved_visuals_are_dropped(self):
        for _title, records in EXAMPLES:
            stream = GenUIStream()
            list(stream.feed(_fence(*records) + "\n"))
            self.assertTrue(stream.complete)
            self.assertEqual(len(stream.spec.snapshot(lambda _chart: True)["nodes"]), len(records) - 1)
        saved = {"id": "answer", "sender": "bot", "content": "Explanation."}
        old = {"version": "1.0", "initial_state": {}, "nodes": [ROOT, {**NOTE, "visible_when": None}]}
        self.assertIsNone(SavedMessage.model_validate({**saved, "ui_spec": old}).ui_spec)

    def test_chat_transports_expose_ui_separately_from_prose(self):
        app = FastAPI()
        app.include_router(chat.router)
        app.dependency_overrides[chat.current_user] = lambda: "user"

        async def model(*args, **kwargs):
            yield "delta", {"text": "Explanation.\n"}
            yield "delta", {"text": block(ROOT, BUTTON, NOTE)}

        with (patch.object(chat, "answer_context", return_value=("", {})),
              patch.object(chat, "_load_tools", return_value=([], {})),
              patch.object(chat, "answer_with_tools", model),
              TestClient(app) as client):
            response = client.post("/chat/stream", data={"query": "Explain scaling"})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("```genui", response.text)
            self.assertLess(response.text.index("event: ui_spec"), response.text.index("event: citations"))
            self.assertLess(response.text.rindex("event: ui_spec"), response.text.index("event: done"))
            result = client.post("/chat", data={"query": "Explain scaling"}).json()
            self.assertEqual(result["answer"], "Explanation.")
            self.assertEqual(result["ui_spec"]["nodes"][1:], [BUTTON, NOTE])
