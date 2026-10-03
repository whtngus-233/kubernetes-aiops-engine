"""Optional, bounded notifications; no automatic network calls on import."""
from collections import OrderedDict
import os
import re
import threading
import time
from app.http import HTTPTransport
from app.security import sanitize

class DiscordNotifier:
    def __init__(self, transport=None, timeout=5, dedup_seconds=900, max_keys=1000):
        self.transport = transport or HTTPTransport(max_bytes=100_000)
        self.timeout, self.dedup_seconds, self.max_keys = timeout, dedup_seconds, max_keys
        self._sent = OrderedDict()
        self._lock = threading.Lock()

    def notify(self, incident):
        webhook = os.getenv('DISCORD_WEBHOOK_URL')
        if not webhook:
            return 'disabled'
        if not re.fullmatch(r'https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+', webhook):
            return 'invalid_configuration'
        key, now = incident.deduplication_key, time.monotonic()
        with self._lock:
            if key in self._sent and now - self._sent[key] < self.dedup_seconds:
                return 'duplicate'
            data = incident.to_dict()
            lines = [f"[{data['severity']}] {data['namespace']}/{data['pod']} ({data['category']})", data['summary']]
            lines.extend(f"Evidence: {e['key']}={e['value']} {e['message']}" for e in data['evidence'][:3])
            lines.extend('Review: ' + action for action in data['recommended_actions'][:3])
            try:
                self.transport.request('POST', webhook, timeout=self.timeout,
                    payload={'content': sanitize('\n'.join(lines), 1900), 'allowed_mentions': {'parse': []}})
            except Exception:
                return 'unavailable'
            self._sent[key] = now
            self._sent.move_to_end(key)
            while len(self._sent) > self.max_keys:
                self._sent.popitem(last=False)
            return 'sent'
