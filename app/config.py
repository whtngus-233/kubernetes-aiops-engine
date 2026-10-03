from dataclasses import dataclass
import os
import re
import math

NAMESPACE = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')

@dataclass(frozen=True)
class Settings:
    allowed_namespaces: tuple[str, ...] = ('default',)
    cluster: str = 'configured-context'
    prometheus_url: str | None = None
    loki_url: str | None = None
    context: str | None = None
    restart_threshold: int = 5
    cpu_threshold: float = .8
    loki_minutes: int = 15
    loki_line_limit: int = 100
    llm_enabled: bool = False
    notifications_enabled: bool = False
    api_token: str | None = None
    webhook_token: str | None = None

    def __post_init__(self):
        if not self.allowed_namespaces or any(not NAMESPACE.fullmatch(n) for n in self.allowed_namespaces):
            raise ValueError('Invalid namespace allowlist')
        if type(self.restart_threshold) is not int or self.restart_threshold < 1 or not math.isfinite(self.cpu_threshold) or self.cpu_threshold <= 0:
            raise ValueError('Invalid rule thresholds')
        if type(self.loki_minutes) is not int or not 1 <= self.loki_minutes <= 1440 or type(self.loki_line_limit) is not int or not 1 <= self.loki_line_limit <= 1000:
            raise ValueError('Invalid Loki bounds')

    @classmethod
    def from_env(cls):
        return cls(allowed_namespaces=tuple(n.strip() for n in os.getenv('AIOPS_ALLOWED_NAMESPACES', 'default').split(',')),
            cluster=os.getenv('AIOPS_CLUSTER', 'configured-context'),
            prometheus_url=os.getenv('PROMETHEUS_URL') or None, loki_url=os.getenv('LOKI_URL') or None,
            context=os.getenv('AIOPS_CONTEXT') or None,
            restart_threshold=int(os.getenv('AIOPS_RESTART_THRESHOLD', '5')),
            cpu_threshold=float(os.getenv('AIOPS_CPU_THRESHOLD', '0.8')),
            loki_minutes=int(os.getenv('LOKI_MINUTES', '15')), loki_line_limit=int(os.getenv('LOKI_LINE_LIMIT', '100')),
            llm_enabled=os.getenv('AIOPS_LLM_ENABLED', 'false').lower() == 'true',
            notifications_enabled=os.getenv('AIOPS_NOTIFY_ENABLED', 'false').lower() == 'true',
            api_token=os.getenv('AIOPS_API_TOKEN') or None, webhook_token=os.getenv('ALERTMANAGER_TOKEN') or None)
