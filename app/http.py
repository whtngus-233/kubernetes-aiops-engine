"""Bounded HTTP transport. No redirects, retries or implicit proxy credentials."""
import json
from urllib.parse import urlsplit
import requests

class HTTPTransport:
    def __init__(self, max_bytes=2_000_000):
        self.max_bytes = max_bytes

    def request(self, method, url, *, params=None, payload=None, headers=None, timeout=5):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid endpoint')
        with requests.Session() as session:
            session.trust_env = False
            with session.request(method, url, params=params, json=payload, headers=headers,
                                 timeout=timeout, allow_redirects=False, stream=True) as response:
                if not 200 <= response.status_code < 300:
                    raise ValueError('HTTP request failed')
                chunks, size = [], 0
                for chunk in response.iter_content(8192):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ValueError('HTTP response exceeds limit')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                return json.loads(raw) if raw else {}
