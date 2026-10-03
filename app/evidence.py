"""Normalize only safe status fields; never Pod specs, env or Secrets."""
from app.models import KubernetesEvidence
from app.security import sanitize

def normalize(snapshot):
    evidence = list(snapshot.evidence)
    for pod in snapshot.pods:
        evidence.append(KubernetesEvidence('kubernetes', pod.timestamp, pod.namespace, pod.name,
            None, 'status', 'phase', pod.phase))
        for c in pod.containers:
            for key, value in [('state', c.state), ('reason', c.waiting_reason or c.terminated_reason),
                ('restarts_total', c.restart_count), ('ready', c.ready),
                ('memory_limit_bytes', c.memory_limit_bytes), ('previous_reason', c.previous_terminated_reason)]:
                if value is not None:
                    evidence.append(KubernetesEvidence('kubernetes', c.timestamp, pod.namespace,
                        pod.name, c.name, 'status', key, value))
        for e in pod.events:
            evidence.append(KubernetesEvidence('kubernetes', e.timestamp, pod.namespace, pod.name,
                None, 'event', e.reason, e.count, sanitize(e.message)))
    return evidence
