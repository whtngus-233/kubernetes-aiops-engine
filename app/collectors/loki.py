"""Read-only query_range; filtering then sanitization before truncation."""
import re
from datetime import datetime, timedelta, timezone
from app.http import HTTPTransport
from app.models import CollectionResult, LogEvidence
from app.security import sanitize

SIGNAL = re.compile(r'error|exception|timeout|refused|failed|\b5\d\d\b|oom', re.I)
LABEL = re.compile(r'[a-z0-9](?:[a-z0-9._-]{0,251}[a-z0-9])?')

class LokiCollector:
    def __init__(self, endpoint=None, timeout=5, minutes=15, line_limit=100, transport=None,
                 namespace_label='namespace', pod_label='pod', container_label='container'):
        if not 1 <= minutes <= 1440 or not 1 <= line_limit <= 1000:
            raise ValueError('Invalid Loki bounds')
        for label in (namespace_label, pod_label, container_label):
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', label):
                raise ValueError('Invalid label')
        self.endpoint = endpoint.rstrip('/') if endpoint else None
        self.timeout, self.minutes, self.line_limit = timeout, minutes, line_limit
        self.transport = transport or HTTPTransport()
        self.labels = (namespace_label, pod_label, container_label)

    def collect(self, namespace, pod=None, container=None, incident_time=None):
        result = CollectionResult()
        if not self.endpoint:
            return result
        selectors = []
        for label, value in zip(self.labels, (namespace, pod, container)):
            if value is not None:
                if not LABEL.fullmatch(value):
                    raise ValueError('Invalid Loki selector')
                selectors.append(f'{label}="{value}"')
        end = datetime.now(timezone.utc)
        center = incident_time or end
        if center.tzinfo is None:
            raise ValueError('incident_time must be timezone aware')
        start = center - timedelta(minutes=self.minutes)
        if incident_time:
            end = min(end, center + timedelta(minutes=self.minutes))
        try:
            data = self.transport.request('GET', self.endpoint + '/loki/api/v1/query_range',
                params={'query': '{' + ','.join(selectors) + '}', 'start': str(int(start.timestamp()*1e9)),
                        'end': str(int(end.timestamp()*1e9)), 'limit': self.line_limit, 'direction': 'backward'},
                timeout=self.timeout)
            if data.get('status') != 'success' or data['data']['resultType'] != 'streams':
                raise ValueError('Invalid Loki response')
            rows = data['data']['result']
            if not isinstance(rows, list):
                raise ValueError('Invalid streams')
            count = 0
            for stream in rows[:1000]:
                labels = stream['stream']
                ns, p, c = (labels.get(k) for k in self.labels)
                if ns != namespace or not p or (pod and p != pod) or (container and c != container):
                    continue
                for stamp, line in stream['values']:
                    if count >= self.line_limit:
                        break
                    count += 1
                    if not isinstance(line, str) or not SIGNAL.search(line):
                        continue
                    timestamp = datetime.fromtimestamp(int(stamp)/1e9, timezone.utc).isoformat()
                    snippet = sanitize(line, 1000)
                    result.evidence.append(LogEvidence('loki', timestamp, namespace, p, c,
                        'log', 'error_signal', None, snippet))
        except Exception:
            result.warnings.append('loki: query unavailable or malformed')
        return result
