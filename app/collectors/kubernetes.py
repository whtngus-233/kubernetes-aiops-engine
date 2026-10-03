"""Read-only Pod/Event collector; never exposes mutation operations."""
import os
from kubernetes import client, config
from kubernetes.utils.quantity import parse_quantity
from app.security import sanitize
from app.models import ContainerEvidence, EventEvidence, PodEvidence, Snapshot


class CollectionError(RuntimeError):
    pass


class KubernetesCollector:
    def __init__(self, api=None, context=None, timeout=15):
        self.timeout = timeout
        self._owned_client = None
        if api is None:
            try:
                if os.getenv('KUBERNETES_SERVICE_HOST') and context is None:
                    config.load_incluster_config()
                    self._owned_client = client.ApiClient()
                else:
                    self._owned_client = config.new_client_from_config(context=context)
                self._owned_client.configuration.retries = 0
                api = client.CoreV1Api(self._owned_client)
            except Exception:
                raise CollectionError("kubeconfig 로드 실패: 현재 context와 인증 도구를 확인하세요.") from None
        self.api = api

    def close(self):
        if self._owned_client is not None:
            self._owned_client.close()

    def _list(self, method, namespace, **kwargs):
        items, token = [], None
        seen = set()
        for _ in range(100):
            response = method(namespace, limit=500, _continue=token,
                              _request_timeout=(self.timeout, self.timeout), **kwargs)
            items.extend(response.items)
            token = getattr(response.metadata, "_continue", None)
            if not token:
                return items
            if token in seen:
                raise CollectionError("Repeated pagination token")
            seen.add(token)
        raise CollectionError("Pagination bound exceeded")

    @staticmethod
    def _container(status, kind):
        state = status.state
        waiting = state.waiting if state else None
        terminated = state.terminated if state else None
        previous = status.last_state.terminated if status.last_state else None
        return ContainerEvidence(
            name=status.name, kind=kind,
            state="waiting" if waiting else "terminated" if terminated else
                  "running" if state and state.running else "unknown",
            restart_count=status.restart_count or 0,
            waiting_reason=waiting.reason if waiting else None,
            terminated_reason=terminated.reason if terminated else None,
            exit_code=terminated.exit_code if terminated else None,
            previous_terminated_reason=previous.reason if previous else None, ready=status.ready)

    def collect(self, namespace):
        try:
            raw_pods = self._list(self.api.list_namespaced_pod, namespace)
        except Exception:
            raise CollectionError("Pod 조회 실패: 네트워크, EKS 인증 및 pods list 권한을 확인하세요.") from None
        pods = []
        for raw in raw_pods:
            containers = []
            for attr, kind in (("container_statuses", "regular"),
                               ("init_container_statuses", "init"),
                               ("ephemeral_container_statuses", "ephemeral")):
                containers.extend(self._container(s, kind) for s in
                                  (getattr(raw.status, attr, None) or []))
            limits = {}
            if raw.spec:
                for spec in (raw.spec.containers or []) + (raw.spec.init_containers or []):
                    memory = (spec.resources.limits or {}).get('memory') if spec.resources else None
                    if memory:
                        try:
                            limits[spec.name] = float(parse_quantity(memory))
                        except (ValueError, TypeError):
                            pass
            for c in containers:
                c.memory_limit_bytes = limits.get(c.name)
            pods.append(PodEvidence(raw.metadata.name, raw.metadata.namespace,
                                    raw.metadata.uid, getattr(raw.status, "phase", None) or "Unknown", containers))
        snapshot = Snapshot(namespace, pods)
        try:
            events = self._list(self.api.list_namespaced_event, namespace,
                                field_selector="involvedObject.kind=Pod")
            by_uid = {p.uid: p for p in pods if p.uid}
            for event in events:
                pod = by_uid.get(event.involved_object.uid)
                if pod is None:
                    continue
                timestamp = event.last_timestamp or event.event_time or event.metadata.creation_timestamp
                pod.events.append(EventEvidence(event.reason or "Unknown", sanitize(event.message or ""),
                                                 event.type or "Unknown", event.count or 1,
                                                 str(timestamp or snapshot.timestamp)))
            for pod in pods:
                pod.events.sort(key=lambda e: e.timestamp)
        except Exception:
            snapshot.warnings.append("Event 조회 실패: 분석 증거가 불완전합니다. events list 권한/연결을 확인하세요.")
        return snapshot
