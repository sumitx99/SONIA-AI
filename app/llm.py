import json
import os

import requests

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# Google retires model versions; override in .env instead of editing code.
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
# How long the model "thinks" before writing. "minimal" cuts time-to-first-word from ~4 s to
# ~1 s, which is plenty for answering from retrieved passages; "low"/"high" think longer.
# Leave empty for the model's default (or for models without thinking levels).
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "minimal").strip()

# The chat UI renders GitHub-flavoured Markdown (tables, lists, code) and KaTeX math, and
# never renders raw HTML, so answers must be Markdown.
SYSTEM_INSTRUCTION = """You are Sonia, a helpful and knowledgeable professor who has read the user's documents.

Language: reply in the language the user writes in. English gets English; Hinglish gets
Hinglish (Hindi in Latin script); Hindi, Bhojpuri or any other language gets that language.

Content:
1. If the question relates to the Provided Document Context, answer from that context.
2. If it is general knowledge unrelated to the context, answer from your own knowledge.
3. If the context is empty, answer from your own knowledge.
4. Refuse unethical, malicious, illegal or harmful requests, politely.

Formatting (the answer is rendered as GitHub-flavoured Markdown):
- Start with the answer itself. No greetings such as "Hello!" and no restating the question.
- Use short paragraphs, "-" bullet lists and **bold** for key terms; use ## or ### headings
  only for answers with several sections.
- Use a Markdown table whenever the user asks for a table, or when comparing two or more
  items across the same attributes. Table rules:
  - a header row, then a separator row like | --- | --- |, then one row per item;
  - every row has the same number of cells; no blank lines inside the table;
  - keep cells short, with no line breaks inside a cell;
  - never wrap a table in a code block.
- Write maths with LaTeX: inline as $O(n^2 \\cdot d)$, on its own line as $$...$$.
- Put code in fenced code blocks with a language tag.
- Never output raw HTML."""


def _request_body(query: str, context: str) -> dict:
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": (
            f"Provided Document Context:\n{context or '(none)'}\n\n---\n\nUser's Question: {query}"
        )}]}],
    }
    if THINKING_LEVEL:
        body["generationConfig"] = {"thinkingConfig": {"thinkingLevel": THINKING_LEVEL}}
    return body


def _text_of(payload: dict) -> str:
    """The answer text in one Gemini response (or stream chunk), skipping any thought parts."""
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts if not part.get("thought"))


def get_llm_response(query: str, context: str):
    """
    Use Google Gemini to generate an answer with context, a defined persona, and safety guardrails.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{CHAT_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    response = requests.post(url, json=_request_body(query, context), timeout=120)
    response.raise_for_status()
    answer = _text_of(response.json()).strip()
    # A blocked or empty response has no candidates.
    return answer or "I am sorry, but I was unable to generate a response for that query."


def stream_llm_response(query: str, context: str):
    """Yields the answer in pieces as Gemini writes it (server-sent events from the API)."""
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{CHAT_MODEL}"
           f":streamGenerateContent?alt=sse&key={GOOGLE_API_KEY}")
    with requests.post(url, json=_request_body(query, context), stream=True, timeout=120) as response:
        response.raise_for_status()
        wrote_any = False
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            text = _text_of(json.loads(line[5:]))
            if text:
                wrote_any = True
                yield text
        if not wrote_any:
            yield "I am sorry, but I was unable to generate a response for that query."
