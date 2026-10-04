from copy import deepcopy
import time
import threading
from contextlib import contextmanager
from app.analyzers.correlation import CorrelationEngine
from app.analyzers.llm import LLMAnalyzer, OpenAIProvider, DisabledProvider
from app.collectors.kubernetes import KubernetesCollector
from app.collectors.prometheus import PrometheusCollector
from app.collectors.loki import LokiCollector
from app.notifiers.discord import DiscordNotifier

class AnalysisEngine:
    def __init__(self, settings, collector_factory=None, prometheus=None, loki=None, llm=None, notifier=None):
        self.settings = settings
        self._lock = threading.Lock()
        self.collector_factory = collector_factory or (lambda: KubernetesCollector(context=settings.context))
        self.prometheus = prometheus or PrometheusCollector(settings.prometheus_url)
        self.loki = loki or LokiCollector(settings.loki_url, minutes=settings.loki_minutes, line_limit=settings.loki_line_limit)
        self.llm = llm or LLMAnalyzer(OpenAIProvider() if settings.llm_enabled else DisabledProvider())
        self.notifier = notifier or DiscordNotifier()
        self.correlation = CorrelationEngine(settings.restart_threshold, settings.cpu_threshold)

    @contextmanager
    def _exclusive(self):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('Analysis already in progress')
        try:
            yield
        finally:
            self._lock.release()

    def analyze(self, namespace):
        with self._exclusive():
            return self._analyze(namespace)

    def _analyze(self, namespace):
        if namespace not in self.settings.allowed_namespaces:
            raise ValueError('Namespace not allowed')
        collector = self.collector_factory()
        try:
            snapshot = collector.collect(namespace)
        finally:
            collector.close()
        return self._analyze_snapshot(snapshot)

    def analyze_snapshot(self, snapshot):
        with self._exclusive():
            return self._analyze_snapshot(snapshot)

    def _analyze_snapshot(self, snapshot):
        snapshot = deepcopy(snapshot)
        deadline = time.monotonic() + 60
        namespace = snapshot.namespace
        if namespace not in self.settings.allowed_namespaces:
            raise ValueError("Namespace not allowed")
        for component in (self.prometheus, self.loki):
            try:
                result = component.collect(namespace)
                snapshot.evidence.extend(result.evidence)
                snapshot.warnings.extend(result.warnings)
            except Exception:
                snapshot.warnings.append(type(component).__name__ + ': optional evidence unavailable')
        incidents = self.correlation.analyze(snapshot, self.settings.cluster)
        if len(incidents) > 10 and (self.settings.llm_enabled or self.settings.notifications_enabled):
            snapshot.warnings.append('advisory/notification: per-analysis limit reached (10 incidents)')
        for index, incident in enumerate(incidents):
            if time.monotonic() >= deadline:
                snapshot.warnings.append('advisory/notification: analysis deadline reached')
                break
            if index >= 10:
                continue
            try:
                incident.llm_analysis = self.llm.analyze(incident)
            except Exception:
                incident.llm_analysis = {'status': 'unavailable'}
            if self.settings.notifications_enabled:
                try:
                    status = self.notifier.notify(incident)
                except Exception:
                    status = 'unavailable'
                if status in ('unavailable', 'invalid_configuration'):
                    snapshot.warnings.append('discord: notification unavailable')
        return incidents, snapshot.warnings
