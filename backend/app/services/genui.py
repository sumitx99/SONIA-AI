"""Validated, versioned UI parts carried by the existing answer stream."""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

VERSION = "2.0"
MAX_NODES = 48
MAX_DEPTH = 8
MAX_PAYLOAD = 24_000
MAX_RECORD_LINES = 256
MAX_STATE_KEYS = 16
MAX_DIAGRAM_NODES = 32
MAX_DIAGRAM_EDGES = 64
MAX_DIAGRAM_GROUPS = 8
MAX_STEPS = 12
MAX_STEP_TARGETS = 12
MAX_POINTS = 60
MAX_SERIES = 6
MAX_PARTS = 8
SLIDER_BOUND = 1000

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=100)]
Value = bool | Annotated[float, Field(allow_inf_nan=False, ge=-1e12, le=1e12)] | Label
NodeKind = Literal["process", "data", "actor", "decision", "queue", "external"]
Tone = Literal["neutral", "accent", "success", "warning", "danger"]
Direction = Literal["right", "down"]
ChartType = Literal["bar", "line", "area", "pie"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Start(StrictModel):
    version: Literal["2.0"]
    initial_state: dict[Identifier, Value] = Field(default_factory=dict, max_length=MAX_STATE_KEYS)


class Condition(StrictModel):
    key: Identifier
    equals: Value


class Node(StrictModel):
    id: Identifier
    parent: Identifier | None = None
    visible_when: Condition | None = None


class Layout(Node):
    type: Literal["column", "row", "card"]
    title: Label | None = None


class Text(Node):
    type: Literal["text"]
    content: str = Field(min_length=1, max_length=600)
    state_key: Identifier | None = None


class Button(Node):
    type: Literal["button"]
    label: Label
    key: Identifier
    value: Value


class Slider(Node):
    type: Literal["slider"]
    label: Label
    key: Identifier
    min: int = Field(ge=-SLIDER_BOUND, le=SLIDER_BOUND)
    max: int = Field(ge=-SLIDER_BOUND, le=SLIDER_BOUND)
    step: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def validate_range(self):
        if self.max <= self.min or (self.max - self.min) % self.step:
            raise ValueError("Invalid slider range")
        return self


class DiagramNode(StrictModel):
    id: Identifier
    label: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    detail: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None
    kind: NodeKind = "process"
    tone: Tone = "neutral"
    group: Identifier | None = None


class Group(StrictModel):
    id: Identifier
    label: Annotated[str, StringConstraints(min_length=1, max_length=60)]


class Edge(StrictModel):
    id: Identifier
    source: Identifier
    target: Identifier
    label: Annotated[str, StringConstraints(min_length=1, max_length=40)] | None = None
    dashed: bool = False


class Step(StrictModel):
    """One beat of a walkthrough: what to say, which nodes to spotlight, which edges carry flow."""
    caption: str = Field(min_length=1, max_length=200)
    focus: list[Identifier] = Field(default_factory=list, max_length=MAX_STEP_TARGETS)
    flow: list[Identifier] = Field(default_factory=list, max_length=MAX_STEP_TARGETS)


class Diagram(Node):
    """A graph the client lays out itself, so a spec describes structure and never geometry."""
    type: Literal["diagram"]
    title: Label
    direction: Direction = "right"
    nodes: list[DiagramNode] = Field(min_length=1, max_length=MAX_DIAGRAM_NODES)
    edges: list[Edge] = Field(default_factory=list, max_length=MAX_DIAGRAM_EDGES)
    groups: list[Group] = Field(default_factory=list, max_length=MAX_DIAGRAM_GROUPS)
    steps: list[Step] = Field(default_factory=list, max_length=MAX_STEPS)
    build: bool = False

    @model_validator(mode="after")
    def validate_graph(self):
        nodes = {node.id for node in self.nodes}
        edges = {edge.id for edge in self.edges}
        groups = {group.id for group in self.groups}
        # Steps name nodes (focus) and edges (flow) separately, so edges keep their own IDs.
        # Groups and nodes share the layout graph, so their IDs must not collide.
        if (len(nodes) != len(self.nodes) or len(edges) != len(self.edges) or len(groups) != len(self.groups)
                or nodes & groups):
            raise ValueError("Duplicate diagram IDs")
        if any(edge.source not in nodes or edge.target not in nodes or edge.source == edge.target
               for edge in self.edges):
            raise ValueError("Invalid edge endpoints")
        if any(node.group is not None and node.group not in groups for node in self.nodes):
            raise ValueError("Unknown diagram group")
        for step in self.steps:
            if not step.focus and not step.flow:
                raise ValueError("A step needs a node or an edge")
            if not set(step.focus) <= nodes or not set(step.flow) <= edges:
                raise ValueError("Unknown step target")
        if self.build and not self.steps:
            raise ValueError("A built-up diagram needs steps")
        return self


class Point(StrictModel):
    name: Label
    value: float = Field(allow_inf_nan=False, ge=-1e12, le=1e12)
    series: Label | None = None
    citation: int | None = Field(default=None, ge=1, le=99)


class Chart(Node):
    type: Literal["chart"]
    title: Label
    chart_type: ChartType
    x_label: Label
    y_label: Label
    stacked: bool = False
    data: list[Point] = Field(min_length=1, max_length=MAX_POINTS)
    # Local state that narrows what is drawn: a series name, and how many categories to show.
    series_key: Identifier | None = None
    count_key: Identifier | None = None

    @model_validator(mode="after")
    def validate_data(self):
        series = {point.series for point in self.data}
        if None in series and len(series) > 1:
            raise ValueError("Name the series of every point or of none")
        if len(series) > MAX_SERIES:
            raise ValueError("Too many series")
        if len({(point.series, point.name) for point in self.data}) != len(self.data):
            raise ValueError("Duplicate chart point")
        named = None not in series
        if self.chart_type == "pie" and (named or len(self.data) > MAX_PARTS or any(point.value < 0 for point in self.data)
                                         or not any(point.value for point in self.data)):
            raise ValueError("A pie shows a few non-negative parts of one series")
        if self.stacked and (not named or self.chart_type not in ("bar", "area")):
            raise ValueError("Only multi-series bar and area charts stack")
        if self.series_key is not None and not named:
            raise ValueError("A series selector needs named series")
        return self


Component = Annotated[Layout | Text | Button | Slider | Diagram | Chart, Field(discriminator="type")]


def _reads(node):
    """State keys whose value changes what this component shows."""
    keys = {node.visible_when.key} if node.visible_when else set()
    if isinstance(node, Text) and node.state_key is not None:
        keys.add(node.state_key)
    if isinstance(node, Chart):
        keys.update(key for key in (node.series_key, node.count_key) if key is not None)
    return keys


class GenUISpec(Start):
    nodes: list[Component] = Field(min_length=1, max_length=MAX_NODES)

    @model_validator(mode="after")
    def validate_composition(self):
        if len(self.model_dump_json(exclude_defaults=True)) > MAX_PAYLOAD:
            raise ValueError("UI exceeds the size limit")
        state = self.initial_state
        depths = {}
        containers = set()
        sliders = [node.key for node in self.nodes if isinstance(node, Slider)]
        if len(set(sliders)) != len(sliders):
            raise ValueError("Each slider needs its own state key")
        for node in self.nodes:
            if node.id in depths:
                raise ValueError("Duplicate component ID")
            if (node.parent is None and depths) or (node.parent is not None and node.parent not in containers):
                raise ValueError("Expected one root and parent-first layout")
            depths[node.id] = 1 + depths.get(node.parent, 0)
            if depths[node.id] > MAX_DEPTH:
                raise ValueError("Layout is too deeply nested")
            if isinstance(node, Layout):
                containers.add(node.id)
            if not _reads(node) <= state.keys():
                raise ValueError("Unknown state key")
            if node.visible_when and type(state[node.visible_when.key]) is not type(node.visible_when.equals):
                raise ValueError("Condition does not match its state type")
            if isinstance(node, Button):
                # A key nothing declares is an inert control (see snapshot), not a broken layout.
                if node.key in sliders or (node.key in state and type(state[node.key]) is not type(node.value)):
                    raise ValueError("Button does not match its state")
            if isinstance(node, Slider):
                value = state.get(node.key)
                if type(value) is not float or not node.min <= value <= node.max or (value - node.min) % node.step:
                    raise ValueError("Slider needs an initial value on its range")
            if isinstance(node, Chart):
                if node.series_key is not None and type(state[node.series_key]) is not str:
                    raise ValueError("A series selector reads text state")
                if node.count_key is not None and type(state[node.count_key]) is not float:
                    raise ValueError("A category count reads numeric state")
        return self

    def snapshot(self, keep_chart):
        """The renderable spec: unsupported charts and controls that change nothing are left out."""
        nodes = [node for node in self.nodes if not isinstance(node, Chart) or keep_chart(node)]
        read = set().union(*(_reads(node) for node in nodes))
        nodes = [node for node in nodes if not isinstance(node, Button) or node.key in read]
        # A container shows only through its contents; one left empty is dropped.
        parents = {node.id: node.parent for node in nodes}
        filled = set()
        for node in nodes:
            if not isinstance(node, Layout):
                parent = node.parent
                while parent is not None and parent not in filled:
                    filled.add(parent)
                    parent = parents.get(parent)
        nodes = [node for node in nodes if not isinstance(node, Layout) or node.id in filled]
        if not nodes:
            return None
        return {"version": self.version, "initial_state": self.initial_state,
                "nodes": [node.model_dump(mode="json", exclude_defaults=True) for node in nodes]}


def saved_spec(value):
    """A stored spec, or None when it predates this catalog version or no longer validates."""
    try:
        return GenUISpec.model_validate(value)
    except ValueError:
        return None


def _word(character):
    return character.isalnum() or character == "_"


def _without(text, label):
    """Text with whole-word mentions of a label removed, or None when it is never mentioned."""
    folded, needle = text.casefold(), label.casefold()
    if len(folded) != len(text):
        # Case folding changed the length (rare scripts); offsets would not line up.
        folded, needle = text, label
    kept, start, found = [], 0, False
    position = folded.find(needle)
    while position != -1:
        end = position + len(needle)
        if (position == 0 or not _word(text[position - 1])) and (end == len(text) or not _word(text[end])):
            kept.append(text[start:position])
            start, found = end, True
        position = folded.find(needle, end)
    return "".join(kept) + text[start:] if found else None


def _numbers(text):
    """Numeric values written in text, such as 120, 1,200.5, -3, 45% or 120ms.

    Digits that are part of a name (Q3, v2) or of a dotted sequence (1.2.3, 12.05.2024)
    are not values, and neither is a hyphen that joins a range (10-20).
    """
    values, index, size = [], 0, len(text)
    while index < size:
        if not text[index].isdigit():
            index += 1
            continue
        start = index
        while index < size and text[index].isdigit():
            index += 1
        if index - start <= 3:
            while (index + 3 < size and text[index] == "," and text[index + 1:index + 4].isdigit()
                   and not text[index + 4:index + 5].isdigit()):
                index += 4
        dots = 0
        while index + 1 < size and text[index] == "." and text[index + 1].isdigit():
            dots += 1
            index += 1
            while index < size and text[index].isdigit():
                index += 1
        if (index + 1 < size and text[index] in "eE" and dots < 2
                and (text[index + 1].isdigit() or (text[index + 1] in "+-" and text[index + 2:index + 3].isdigit()))):
            index += 2
            while index < size and text[index].isdigit():
                index += 1
        end = index
        while index < size and _word(text[index]):  # a unit written against the number
            index += 1
        if dots > 1 or (start and (_word(text[start - 1]) or text[start - 1] == ".")):
            continue
        literal = text[start:end].replace(",", "")
        if start and text[start - 1] in "-−" and (start == 1 or not _word(text[start - 2])):
            literal = "-" + literal
        values.append(literal)
    return values


def _supports(text, point):
    """The text names this point and states exactly one distinct value: the point's."""
    for label in filter(None, (point.name, point.series)):
        text = _without(text, label)
        if text is None:
            return False
    values = _numbers(text)
    try:
        return bool(values) and all(len(value) <= 32 and Decimal(value) == Decimal(str(point.value))
                                    for value in values)
    except InvalidOperation:
        return False


def supported_chart(chart, citations, user_text):
    """Require every point's labels and value in checked evidence or in a line of user data."""
    return all(
        _supports(citations.get(point.citation, ""), point) if point.citation is not None
        else any(_supports(line, point) for text in user_text for line in text.splitlines())
        for point in chart.data
    )


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\n]*)\n?$")
_UI_OPEN = "```genui"


def _width(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


class GenUIStream:
    """Recognize top-level GenUI fences while ordinary answer text keeps streaming.

    Recovery is per record: a record that fails validation is skipped, malformed JSON ends its
    block, and later blocks join the visual under its root. Whatever is kept has been validated
    against everything kept before it; `dropped` records that some of the model's UI was lost.
    """

    def __init__(self):
        self.line = ""
        self.passthrough = False
        self.discard_line = False
        self.fence = ""
        self.in_ui = False
        self.seen_ui = False
        self.length = 0
        self.removed = []
        self.start = None
        self.record = []
        self.spec = None
        self.size = 0
        self.complete = False  # a valid visual exists and no block is open
        self.dropped = False  # part of the model's UI could not be kept
        self.invalid = False  # the open block ended early; its remaining lines are ignored
        self.block_start = None  # the open block's first record, once read
        self.block_root = None  # (ID the open block gave its root, ID that root has in the visual)

    def feed(self, text):
        lines = text.split("\n")
        for index, part in enumerate(lines):
            ended = index < len(lines) - 1
            piece = part + ("\n" if ended else "")
            if self.discard_line:
                self._hide(piece)
                self.discard_line = not ended
                continue
            if self.passthrough:
                self.passthrough = not ended
                if piece:
                    yield self._delta(piece)
                continue
            self.line += piece
            if self.in_ui:
                if ended:
                    yield from self._ui_line(self._take_line())
                elif len(self.line) > MAX_PAYLOAD:
                    self.discard_line = True
                    self._hide(self._take_line())
                    self._stop()
                continue
            stripped = self.line.lstrip(" ")
            possible_fence = len(self.line) - len(stripped) <= 3 and (
                "```".startswith(stripped) or "~~~".startswith(stripped)
                or stripped.startswith(("```", "~~~")))
            if ended:
                yield from self._ordinary_line(self._take_line())
            elif not possible_fence or len(self.line) > 256:
                self.passthrough = True
                yield from self._ordinary_line(self._take_line())

    def finish(self):
        if self.line:
            if self.in_ui:
                yield from self._ui_line(self._take_line())
            else:
                yield from self._ordinary_line(self._take_line())
        if self.in_ui:
            # The answer ended inside a block: keep its valid records, note the rest was lost.
            self.in_ui = False
            self._close(finished=False)

    def _take_line(self):
        line, self.line = self.line, ""
        return line

    def _ordinary_line(self, line):
        match = _FENCE.fullmatch(line)
        if match:
            fence, info = match.groups()
            if self.fence:
                if fence.startswith(self.fence) and not info.strip():
                    self.fence = ""
            elif line.strip() == _UI_OPEN:
                self.seen_ui = self.in_ui = True
                self.complete = self.invalid = False
                self.block_start = self.block_root = None
                self.record.clear()
                self._hide(line)
                return
            elif fence[0] == "~" or "`" not in info:
                self.fence = fence
        yield self._delta(line)

    def _delta(self, text):
        self.length += _width(text)
        return "delta", {"text": text}

    def _hide(self, text):
        end = self.length + _width(text)
        if self.removed and self.removed[-1][1] == self.length:
            self.removed[-1] = (self.removed[-1][0], end)
        else:
            self.removed.append((self.length, end))
        self.length = end

    def position(self, position):
        offset = 0
        for start, end in self.removed:
            if start < position <= end:
                return None
            if end < position:
                offset += end - start
        if self.in_ui and position > self.length:
            return None
        return position - offset

    def _stop(self):
        """End the open block early, keeping the records already accepted from it."""
        self.invalid = self.dropped = True
        self.record.clear()

    def _close(self, finished):
        if self.record or not finished:
            self.dropped = True
        self.record.clear()
        self.complete = self.spec is not None

    def _open(self, start):
        """Read a block's first record, merging its state into the visual it joins."""
        if self.spec is not None:
            state = dict(self.start.initial_state)
            for key, value in start.initial_state.items():
                if key in state and (type(state[key]) is not type(value) or state[key] != value):
                    raise ValueError("A later block redefines a state key")
                state[key] = value
            start = Start.model_validate({"version": start.version, "initial_state": state})
        self.block_start = self.start = start

    def _join(self, data):
        """A record re-parented, when it belongs to a later block, to hang under the visual's root."""
        if not isinstance(data, dict) or self.block_root is not None and data.get("parent") is None:
            # A second parent-less record in one block stays as written and fails validation.
            return data
        if data.get("parent") is None:
            own = data.get("id")
            if self.spec is None or not isinstance(own, str):
                self.block_root = (own, own)
                return data
            used = {node.id for node in self.spec.nodes}
            unique, suffix = own, 2
            while unique in used:
                unique = f"{own[:36]}{suffix}"
                suffix += 1
            # A root ID is only ever named by its own block's parent fields, so renaming is safe.
            self.block_root = (own, unique)
            return {**data, "id": unique, "parent": self.spec.nodes[0].id}
        if self.block_root and data.get("parent") == self.block_root[0]:
            return {**data, "parent": self.block_root[1]}
        return data

    def _ui_line(self, line):
        self._hide(line)
        if re.fullmatch(r" {0,3}`{3,}[ \t]*\r?\n?", line):
            self.in_ui = False
            self._close(finished=True)
            return
        if self.invalid:
            return
        self.size += len(line)
        if self.size > MAX_PAYLOAD:
            self._stop()
            return
        if not self.record and not line.lstrip().startswith("{"):
            # Every record is a JSON object. Text between records (a blank line, or a heading or
            # comment a model adds) can never become one, so it must not swallow the next record.
            return
        self.record.append(line)
        if len(self.record) > MAX_RECORD_LINES:
            self._stop()
            return
        try:
            data = json.loads("".join(self.record))
        except json.JSONDecodeError:
            # A model may pretty-print a single JSON object over several lines.
            return
        except (ValueError, RecursionError):
            self._stop()
            return
        self.record.clear()
        if self.block_start is None:
            try:
                self._open(Start.model_validate(data))
            except (ValueError, RecursionError):
                # Without its state the block's components cannot be checked; skip all of them.
                self._stop()
            return
        nodes = self.spec.nodes if self.spec else []
        try:
            self.spec = GenUISpec.model_validate({**self.start.model_dump(), "nodes": [*nodes, self._join(data)]})
        except (ValueError, RecursionError):
            self.dropped = True  # only this record is skipped; later ones are still checked
            return
        preview = self.spec.snapshot(lambda _chart: False)
        if preview and not isinstance(self.spec.nodes[-1], Chart):
            yield "ui_spec", {"spec": preview}


def _fence(*records):
    lines = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records)
    return "```genui\n" + "\n".join(lines) + "\n```"


def _options(literal):
    return ", ".join(f'"{option}"' for option in get_args(literal))


# Syntax samples for the model. Each differs in shape on purpose, and the tests validate
# them against the catalog so the instruction cannot drift from what the parser accepts.
EXAMPLES = (
    ("A layered system built up step by step", (
        {"version": VERSION, "initial_state": {}},
        {"id": "root", "type": "column"},
        {"id": "load", "type": "diagram", "parent": "root", "title": "How a page loads", "build": True,
         "groups": [{"id": "edge", "label": "Edge"}, {"id": "origin", "label": "Origin"}],
         "nodes": [{"id": "reader", "label": "Reader", "kind": "actor"},
                   {"id": "cdn", "label": "CDN", "detail": "Serves cached pages", "kind": "external", "group": "edge"},
                   {"id": "app", "label": "App server", "group": "origin"},
                   {"id": "store", "label": "Database", "kind": "data", "group": "origin"}],
         "edges": [{"id": "ask", "source": "reader", "target": "cdn", "label": "HTTPS"},
                   {"id": "miss", "source": "cdn", "target": "app", "label": "cache miss", "dashed": True},
                   {"id": "query", "source": "app", "target": "store"}],
         "steps": [{"caption": "The reader asks the nearest CDN node for the page.", "focus": ["reader", "cdn"], "flow": ["ask"]},
                   {"caption": "Only on a cache miss does the request reach the app server.", "focus": ["app"], "flow": ["miss"]},
                   {"caption": "The app server reads the content from the database.", "focus": ["store"], "flow": ["query"]}]},
    )),
    ("A branching process that loops back, with a switchable summary", (
        {"version": VERSION, "initial_state": {"view": "flow"}},
        {"id": "root", "type": "column"},
        {"id": "views", "type": "row", "parent": "root"},
        {"id": "showFlow", "type": "button", "parent": "views", "label": "Flow", "key": "view", "value": "flow"},
        {"id": "showRule", "type": "button", "parent": "views", "label": "Rule", "key": "view", "value": "rule"},
        {"id": "review", "type": "diagram", "parent": "root", "title": "Code review", "direction": "down",
         "visible_when": {"key": "view", "equals": "flow"},
         "nodes": [{"id": "open", "label": "Open pull request", "kind": "actor"},
                   {"id": "check", "label": "Review"},
                   {"id": "verdict", "label": "Approved?", "kind": "decision"},
                   {"id": "merge", "label": "Merge", "tone": "success"},
                   {"id": "revise", "label": "Revise", "tone": "warning"}],
         "edges": [{"id": "toCheck", "source": "open", "target": "check"},
                   {"id": "toVerdict", "source": "check", "target": "verdict"},
                   {"id": "yes", "source": "verdict", "target": "merge", "label": "yes"},
                   {"id": "no", "source": "verdict", "target": "revise", "label": "no"},
                   {"id": "again", "source": "revise", "target": "check", "label": "resubmit", "dashed": True}]},
        {"id": "rule", "type": "text", "parent": "root", "content": "Nothing merges without an approval.",
         "visible_when": {"key": "view", "equals": "rule"}},
    )),
    ("Several series the reader can filter and extend", (
        {"version": VERSION, "initial_state": {"source": "all", "years": 3}},
        {"id": "root", "type": "column"},
        {"id": "pick", "type": "row", "parent": "root"},
        {"id": "all", "type": "button", "parent": "pick", "label": "All", "key": "source", "value": "all"},
        {"id": "solar", "type": "button", "parent": "pick", "label": "Solar", "key": "source", "value": "Solar"},
        {"id": "wind", "type": "button", "parent": "pick", "label": "Wind", "key": "source", "value": "Wind"},
        {"id": "span", "type": "slider", "parent": "root", "label": "Years shown", "key": "years", "min": 1, "max": 3},
        {"id": "output", "type": "chart", "parent": "root", "title": "Generation by source", "chart_type": "line",
         "x_label": "Year", "y_label": "Output (TWh)", "series_key": "source", "count_key": "years",
         "data": [{"name": "2021", "series": "Solar", "value": 40, "citation": 1},
                  {"name": "2022", "series": "Solar", "value": 55, "citation": 2},
                  {"name": "2023", "series": "Solar", "value": 71, "citation": 3},
                  {"name": "2021", "series": "Wind", "value": 62, "citation": 4},
                  {"name": "2022", "series": "Wind", "value": 66, "citation": 5},
                  {"name": "2023", "series": "Wind", "value": 80, "citation": 6}]},
    )),
)

GENUI_INSTRUCTION = f"""

Interactive visual UI: Sonia's chat draws diagrams only from a genui block. A diagram written
as text (ASCII art, arrows or pipes in a code block, box-drawing characters) shows up as
unreadable monospace, so never draw one; use genui instead. Emit genui whenever the answer
explains how something is structured or how it proceeds: an architecture, a request or data
flow, a workflow, a lifecycle, a decision process, a sequence of stages, or a walkthrough the
user asks for, and also for an interactive comparison or an animation. Answer in Markdown
first, then emit one top-level fenced block named genui, before the citations block. Skip it
when nothing in the answer has structure or flow, such as a fact, a definition or a short
answer. Use the user's language in all labels and captions. Keep the explanation complete on
its own and explain any factual claims from the visual with citations in the prose. Do not emit
a plotly chart as well unless the user explicitly wants multiple visuals. Ordinary standalone
charts can use Plotly.

Inside the genui fence, write one complete JSON object per physical line and nothing else: no
comments, headings or notes, which belong in the Markdown. Several diagrams or charts go in this
one block as separate components under the same root, never in a second block. Keep arrays and
their contents on the same line as the component. Start with version "{VERSION}" and initial_state
(use {{}} for a static visual, at most {MAX_STATE_KEYS} keys), then one root column with no parent.
Give every later component a parent ID that points to an earlier column, row, or card. Use unique
IDs (letters, digits, hyphens, underscores, starting with a letter). At most {MAX_NODES} components
and {MAX_DEPTH} levels.
Allowed component fields, alongside id, type and parent:
- column, row: no extra fields. card: optional title.
- text: content (plain text), optional state_key to display its current value beside the text.
- button: label, key, value. A button sets local display state, so its key must be in
  initial_state with the same value type and be read by a visible_when, a text state_key or a
  chart. A button that nothing reads is removed.
- slider: label, key, min, max, optional step (default 1). Bounds and step are integers within
  ±{SLIDER_BOUND}. Use a separate state key per slider, with a numeric initial value aligned to the step.
- diagram: title, nodes [{{"id":"api","label":"API"}}] (at most {MAX_DIAGRAM_NODES}) and edges
  [{{"id":"call","source":"client","target":"api"}}] (at most {MAX_DIAGRAM_EDGES}). Describe structure
  only: the app positions, sizes and draws everything, so never give coordinates.
  Optional direction: {_options(Direction)} (the way the flow reads; default "right").
  Optional per node: kind ({_options(NodeKind)}) picks its shape, tone ({_options(Tone)})
  marks emphasis or outcome, detail is a short second line, group is the ID of an entry in
  groups [{{"id":"backend","label":"Backend"}}] (at most {MAX_DIAGRAM_GROUPS}) that boxes related nodes.
  Optional per edge: label, and dashed true for an optional, asynchronous or return path.
  Optional steps (at most {MAX_STEPS}) make it a guided walkthrough:
  [{{"caption":"What happens now","focus":["api"],"flow":["call"]}}]. Each step shows its caption,
  spotlights its focus nodes and animates its flow edges; give each step at least one of them.
  The app adds its own playback controls, so never add a play button or a controls field.
  Optional build true keeps nodes and edges hidden until a step first refers to them.
- chart: title, chart_type ({_options(ChartType)}), x_label, y_label (include units), data
  [{{"name":"A","value":10,"citation":1}}] (at most {MAX_POINTS} points). For several series (at
  most {MAX_SERIES}) add "series" to every point; stacked true stacks a multi-series bar or area
  chart; a pie takes one series of at most {MAX_PARTS} non-negative parts. Each referenced exact verified quote must
  contain the point's name, its series if it has one, and its single distinct numeric value. Omit
  citation only for data the user supplied on its own line with those labels and the value. Use a
  Markdown explanation alone when data is unavailable.
  Optional series_key: a text state key; when its value equals a series name only that series
  is drawn, any other value draws them all. Optional count_key: a numeric state key (a slider)
  giving how many categories to draw, counted from the first.
A component may have visible_when {{"key":"mode","equals":"single"}}; keys must exist in
initial_state and values must have matching scalar types. Use plain text in fields.
Never include HTML, scripts, URLs, colours, style fields, or actions beyond local state.

Shape the visual around the subject instead of a template: choose the direction, the node
kinds, the groups, whether it branches or loops back, and how many steps it takes from what
the topic actually contains, and add controls only when switching or scrubbing reveals
something. The samples below show syntax and the range of what is possible; do not reuse
their structure or content.
""" + "".join(f"\n{title}:\n{_fence(*records)}\n" for title, records in EXAMPLES)
