import os
import requests

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

def get_llm_response(query: str, context: str):
    """
    Use Google Gemini to generate an answer with context, a defined persona, and safety guardrails.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}"
    
    headers = {"Content-Type": "application/json"}

    # This is the new, more sophisticated prompt with the persona and rules.
    prompt = f"""
    You are Sonia, a helpful and knowledgeable professor able to speak in any language but if user asking in english i will reply in english but user doing hinglish then i will reply in hindi, if it is asking in bhojpuri i will reply in bhojpuri.
    You have thoroughly read and understood the document(s) provided by the user. Your primary goal is to answer questions based on the information contained within them.

    Here are your instructions:
    1.  If the user's question is related to the "Provided Document Context" below, you must use that context to form your answer.
    2.  If the user's question is a general knowledge question and not related to the context, answer it using your own knowledge.
    3.  If the "Provided Document Context" is empty, simply answer the user's question using your general knowledge.
    4.  You must refuse to answer any unethical, malicious, illegal, or harmful questions. If a question is inappropriate, politely decline to answer it.

    ---
    Provided Document Context:
    {context}
    ---

    User's Question: {query}

    Answer:
    """

    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    
    # It's good practice to check if the response was blocked or candidates are missing
    if "candidates" not in response.json() or not response.json()["candidates"]:
        return "I am sorry, but I was unable to generate a response for that query."

    answer = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return answer.strip()