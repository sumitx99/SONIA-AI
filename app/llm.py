import os
import requests

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# Google retires model versions; override in .env instead of editing code.
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash")

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


def get_llm_response(query: str, context: str):
    """
    Use Google Gemini to generate an answer with context, a defined persona, and safety guardrails.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{CHAT_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    
    headers = {"Content-Type": "application/json"}

    data = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": (
            f"Provided Document Context:\n{context or '(none)'}\n\n---\n\nUser's Question: {query}"
        )}]}],
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    
    # It's good practice to check if the response was blocked or candidates are missing
    if "candidates" not in response.json() or not response.json()["candidates"]:
        return "I am sorry, but I was unable to generate a response for that query."

    answer = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return answer.strip()