"""Decide when fresh web information is required and read Groq's source metadata."""
import re
from app.services.web_activity import safe_url


def needs_web(query, history=None):
    text = query.lower()
    explicit = re.search(r'https?://|\b(?:web|browse|search|latest|current|today|news|recent|live)\b|आज|ताज़ा', text)
    if explicit:
        return True
    if re.search(r'\b(?:document|pdf|uploaded|provided context)\b', text):
        return False
    if re.search(r'\b(?:price|pricing|subscription|plans|cost|weather|exchange rate|release date)\b|कीमत|मौसम', text):
        return True
    if len(text) < 100 and re.search(r'^(?:what about|how about|and |aur |or |iska|uska)', text.strip()):
        recent = [turn['content'] for turn in (history or []) if turn['sender'] == 'user'][-3:]
        return any(needs_web(previous) for previous in recent)
    return False


def groq_sources(message):
    """Only structured provider results become source cards; never invented answer URLs."""
    result = {}
    for tool in message.get('executed_tools') or []:
        candidates = list(tool.get('browser_results') or [])
        candidates += (tool.get('search_results') or {}).get('results') or []
        for item in candidates:
            url = safe_url(item.get('url'))
            if url and url not in result and len(result) < 10:
                result[url] = {'url': url, 'title': str(item.get('title') or url)[:200]}
    return list(result.values())
