from dataclasses import dataclass, field, asdict
from hashlib import sha256
from uuid import uuid4
from app.models import IncidentEvidence, utc_now
from app.security import sanitize_tree

@dataclass
class IncidentReport:
    namespace: str
    pod: str
    container: str | None
    severity: str
    category: str
    confidence: str
    summary: str
    evidence: list[IncidentEvidence]
    probable_causes: list[str]
    recommended_actions: list[str]
    confidence_reason: str
    cluster: str = 'configured-context'
    incident_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(default_factory=utc_now)
    automatic_action_taken: bool = False
    llm_analysis: dict | None = None

    @property
    def deduplication_key(self):
        identity = [self.cluster, self.namespace, self.pod, self.container, self.category]
        return sha256(repr(identity).encode()).hexdigest()

    def to_dict(self):
        return sanitize_tree(asdict(self))
