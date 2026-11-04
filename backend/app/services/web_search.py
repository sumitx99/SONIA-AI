"""Read Groq browser-search results: source links, and the text of pages the model opened."""
import re

from app.services.web_activity import safe_url

# The browser shows pages as numbered lines ("L12: text") with links like 【3†title†host】.
_LINE_NUMBER = re.compile(r"(?m)^L\d+: ?")
_LINK = re.compile(r"【\d+†([^†】]*)(?:†[^】]*)?】")


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


def groq_pages(message):
    """Pages the model opened, as plain text, so quotes from them can be checked."""
    pages = {}
    for tool in message.get('executed_tools') or []:
        for item in (tool.get('search_results') or {}).get('results') or []:
            url, text = safe_url(item.get('url')), item.get('content')
            if url and isinstance(text, str) and text.strip() and url not in pages:
                pages[url] = {'url': url, 'title': str(item.get('title') or url)[:200],
                              'text': _LINK.sub(r'\1', _LINE_NUMBER.sub('', text))}
    return list(pages.values())
