"""User-visible web activity derived only from provider tool/grounding events."""
import re
from urllib.parse import urlsplit

KINDS = {'GOOGLE_SEARCH_WEB': ('google_search', 'Searching the web'),
         'GOOGLE_SEARCH_IMAGE': ('google_search_images', 'Searching web images'),
         'URL_CONTEXT': ('url_context', 'Reading web pages')}

_QUESTION_URL = re.compile(r"""https?://[^\s<>()\[\]"']+""", re.IGNORECASE)


def requested_urls(question: str) -> set[str]:
    return {url for match in _QUESTION_URL.finditer(question)
            if (url := safe_url(match.group().rstrip(".,;!?")))}


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
        return value
    except ValueError:
        return None


class WebActivity:
    def __init__(self):
        self.calls = {}
        self.pending = {}

    def event(self, payload, response=False, round_number=0):
        kind = payload.get('toolType')
        if kind not in KINDS:
            return None
        tool, title = KINDS[kind]
        identity = payload.get('id') or self.pending.get(kind) or f'{round_number}-{kind}'
        if not response:
            self.pending[kind] = identity
        key = f'web-{identity}'
        previous = self.calls.get(key, {})
        args = payload.get('args') or {}
        clean = {}
        if isinstance(args, dict):
            for name in ('query', 'queries', 'url', 'urls'):
                values = args.get(name)
                if isinstance(values, str):
                    clean[name] = values[:500]
                elif isinstance(values, list):
                    clean[name] = [value[:500] for value in values[:5] if isinstance(value, str)]
        result = {**previous, 'id': key, 'server': 'Web', 'tool': tool,
                  'title': ('Read web pages' if kind == 'URL_CONTEXT' else 'Searched the web') if response else title, 'arguments': previous.get('arguments', clean),
                  'status': 'done' if response else 'running'}
        self.calls[key] = result
        return result

    def finish(self, failed=False):
        for key, call in list(self.calls.items()):
            if call['status'] == 'running':
                call = {**call, 'status': 'error' if failed else 'done',
                        'summary': 'The web step was interrupted.' if failed else 'Web step finished.'}
                self.calls[key] = call
                yield call
