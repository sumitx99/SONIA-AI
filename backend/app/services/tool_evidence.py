"""Exact, decoded passages from structured tool results, with their original field paths."""
import json


def bounded_tool_text(value, limit: int) -> str:
    """Bound tool data without breaking JSON or fabricating shortened field values.

    Oversized JSON fields/items are omitted. A wrapper explicitly marks incomplete
    results; retained strings/numbers are unchanged. Plain text keeps a marked prefix.
    """
    def encode(item):
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            marker = "\n…[truncated]"
            return value if len(value) <= limit else value[:limit - len(marker)] + marker
    serialized = encode(value)
    if len(serialized) <= limit:
        return serialized

    omitted = object()

    def fit(item, budget, depth=0):
        if budget < 2 or depth > 32:
            return omitted
        if len(encode(item)) <= budget:
            return item
        if isinstance(item, dict):
            kept, used = {}, 2
            for key, child in item.items():
                overhead = len(encode(key)) + 1 + bool(kept)
                part = fit(child, budget - used - overhead, depth + 1)
                if part is not omitted:
                    kept[key] = part
                    used += overhead + len(encode(part))
            return kept if kept or not item else omitted
        if isinstance(item, list):
            kept, used = [], 2
            for child in item:
                overhead = bool(kept)
                part = fit(child, budget - used - overhead, depth + 1)
                if part is omitted:
                    continue
                kept.append(part)
                used += overhead + len(encode(part))
            return kept if kept or not item else omitted
        return omitted

    wrapper = {"result": None, "_sonia_truncated": True}
    budget = limit - len(encode(wrapper)) + len("null")
    retained = fit(value, budget)
    wrapper["result"] = None if retained is omitted else retained
    return encode(wrapper)


def tool_passages(text: str) -> list[dict]:
    """Keep fields separate: values from different records must never form a made-up quote.

    JSON escapes are serialization, not source wording. Decode the same bounded result
    the model received, without sending a second copy of its fields to the model.
    """
    passages = []
    nodes = 0

    def walk(value, path, depth):
        nonlocal nodes
        nodes += 1
        if depth > 12 or nodes > 1000:
            return
        if isinstance(value, str):
            if len(value.strip()) >= 8:
                passages.append({"path": path, "text": value})
            # MCP gateways sometimes put another JSON document inside a text field.
            if value.lstrip().startswith(("{", "[")):
                try:
                    walk(json.loads(value), path + " (decoded)", depth + 1)
                except (ValueError, RecursionError):
                    pass
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}[{json.dumps(key, ensure_ascii=False)}]", depth + 1)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]", depth + 1)

    try:
        walk(json.loads(text), "$", 0)
    except (ValueError, RecursionError):
        pass
    return passages
