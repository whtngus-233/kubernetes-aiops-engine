"""Namespace-scoped instant queries with partial-failure isolation."""
import math
import re
from datetime import datetime, timezone
from app.http import HTTPTransport
from app.models import CollectionResult, MetricsEvidence

QUERIES = {
    'cpu_cores': 'sum by(namespace,pod,container) (rate(container_cpu_usage_seconds_total{namespace="%s",container!="",container!="POD"}[5m]))',
    'memory_bytes': 'container_memory_working_set_bytes{namespace="%s",container!="",container!="POD"}',
    'memory_limit_bytes': 'kube_pod_container_resource_limits{namespace="%s",resource="memory",unit="byte"}',
    'restarts_total': 'kube_pod_container_status_restarts_total{namespace="%s"}',
    'restart_increase': 'increase(kube_pod_container_status_restarts_total{namespace="%s"}[5m])',
    'waiting': 'kube_pod_container_status_waiting{namespace="%s"}',
    'terminated': 'kube_pod_container_status_terminated{namespace="%s"}',
    'phase': 'kube_pod_status_phase{namespace="%s"}',
    'ready': 'kube_pod_container_status_ready{namespace="%s"}',
}

class PrometheusCollector:
    def __init__(self, endpoint=None, timeout=5, transport=None):
        self.endpoint = endpoint.rstrip('/') if endpoint else None
        self.timeout = timeout
        self.transport = transport or HTTPTransport()

    def collect(self, namespace):
        result = CollectionResult()
        if not self.endpoint:
            return result
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', namespace):
            raise ValueError('Invalid namespace')
        for key, query in QUERIES.items():
            try:
                response = self.transport.request('GET', self.endpoint + '/api/v1/query',
                    params={'query': query % namespace}, timeout=self.timeout)
                if response.get('status') != 'success' or response['data']['resultType'] != 'vector':
                    raise ValueError('Invalid Prometheus response')
                rows = response['data']['result']
                if not isinstance(rows, list):
                    raise ValueError('Invalid vector')
                if response.get('warnings'):
                    result.warnings.append('prometheus: upstream partial response')
                for row in rows[:10000]:
                    try:
                        labels, sample = row['metric'], row['value']
                        value = float(sample[1])
                        timestamp = datetime.fromtimestamp(float(sample[0]), timezone.utc).isoformat()
                        if not math.isfinite(value) or labels.get('namespace') != namespace or not labels.get('pod'):
                            continue
                        result.evidence.append(MetricsEvidence('prometheus', timestamp, namespace,
                            labels['pod'], labels.get('container') or None, 'metric', key, value,
                            labels.get('phase', labels.get('reason', ''))))
                    except (KeyError, TypeError, ValueError, OverflowError, IndexError):
                        result.warnings.append('prometheus: invalid sample omitted')
                if len(rows) > 10000:
                    result.warnings.append('prometheus: sample limit reached')
            except Exception:
                result.warnings.append('prometheus: ' + key + ' unavailable or malformed')
        return result
