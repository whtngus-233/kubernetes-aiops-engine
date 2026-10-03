from dataclasses import dataclass, field
from datetime import datetime, timezone

def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ContainerEvidence:
    name: str
    kind: str
    state: str
    restart_count: int
    waiting_reason: str | None = None
    terminated_reason: str | None = None
    exit_code: int | None = None
    previous_terminated_reason: str | None = None
    ready: bool | None = None
    memory_limit_bytes: float | None = None
    source: str = "kubernetes"
    timestamp: str = field(default_factory=utc_now)


@dataclass
class EventEvidence:
    reason: str
    message: str
    type: str
    count: int
    timestamp: str
    source: str = "kubernetes"


@dataclass
class PodEvidence:
    name: str
    namespace: str
    uid: str
    phase: str
    containers: list[ContainerEvidence] = field(default_factory=list)
    events: list[EventEvidence] = field(default_factory=list)
    source: str = "kubernetes"
    timestamp: str = field(default_factory=utc_now)


@dataclass
class Snapshot:
    namespace: str
    pods: list[PodEvidence]
    warnings: list[str] = field(default_factory=list)
    evidence: list["IncidentEvidence"] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now)


@dataclass
class Incident:
    pod: PodEvidence
    category: str
    severity: str
    container: str | None
    evidence: str
    probable_cause: str
    recommendations: list[str]


@dataclass
class IncidentEvidence:
    source: str
    timestamp: str
    namespace: str
    pod: str
    container: str | None
    evidence_type: str
    key: str
    value: float | str | bool | None = None
    message: str = ""


@dataclass
class MetricsEvidence(IncidentEvidence):
    """value is in base units: CPU cores, memory bytes, restart count."""


@dataclass
class LogEvidence(IncidentEvidence):
    """Only sanitized, signal-bearing snippets are retained."""


@dataclass
class KubernetesEvidence(IncidentEvidence):
    pass


@dataclass
class CollectionResult:
    evidence: list[IncidentEvidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
