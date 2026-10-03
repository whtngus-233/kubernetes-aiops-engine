"""Explicit hypotheses; legacy detection categories remain available separately."""
from datetime import datetime, timedelta, timezone
import re
from app.analyzers.rules import RuleEngine
from app.evidence import normalize
from app.structured import IncidentReport

CAUSES = {
    'DEPENDENCY_CONNECTION_FAILURE': ('critical', '의존 서비스 연결 실패 가능성', ['DB/service DNS, endpoint, 네트워크 정책과 의존 서비스 상태를 읽기 전용으로 확인하세요.']),
    'INGRESS_OR_ROUTING': ('warning', '애플리케이션 또는 ingress/routing 경로 장애 후보', ['Ingress/Service 대상과 endpoint, upstream 로그를 확인하세요. 애플리케이션 자체 오류도 배제하지 마세요.']),
    'MEMORY_PRESSURE': ('critical', '메모리 한도 근접과 OOM 종료 증거', ['메모리 추이와 limits, 누수 및 workload 변화 시점을 검토하세요.']),
    'HIGH_CPU': ('warning', 'CPU 사용량이 설정된 cores 임계값 이상', ['CPU requests/limits, 트래픽과 프로파일링 결과를 검토하세요.']),
    'IMAGE_PULL_FAILURE': ('critical', '이미지 pull 실패 상태와 Event가 함께 관찰됨', ['이미지 태그 존재 여부와 레지스트리 연결/권한을 확인하세요.']),
    'SCHEDULING_FAILURE': ('warning', 'Pending과 FailedScheduling Event가 함께 관찰됨', ['노드 용량, requests, affinity/taint와 스케줄러 메시지를 검토하세요.']),
    'HISTORICAL_RESTART_WARNING': ('warning', '현재 정상 상태에서 누적 재시작 기록이 관찰됨', ['이전 종료 시점과 재시작 증가율을 확인하세요. 현재 장애로 단정하지 마세요.']),
}

class CorrelationEngine:
    def __init__(self, restart_threshold=5, cpu_threshold=0.8, window_minutes=20):
        self.rules = RuleEngine(restart_threshold)
        if cpu_threshold <= 0 or not 1 <= window_minutes <= 1440:
            raise ValueError('Invalid correlation settings')
        self.cpu_threshold, self.window_minutes = cpu_threshold, window_minutes

    def analyze(self, snapshot, cluster='configured-context'):
        evidence = normalize(snapshot)
        reports = []
        now = datetime.fromisoformat(snapshot.timestamp)
        def recent(e):
            try:
                stamp = datetime.fromisoformat(e.timestamp.replace('Z', '+00:00'))
                return timedelta(minutes=-1) <= now - stamp <= timedelta(minutes=self.window_minutes)
            except (ValueError, TypeError):
                return False
        baseline = self.rules.analyze(snapshot)
        for pod in snapshot.pods:
            pe = [e for e in evidence if e.namespace == pod.namespace and e.pod == pod.name and recent(e)]
            emitted = set()
            replaced = set()
            def add(category, container, selected, confidence, reason):
                if (category, container) in emitted:
                    return
                emitted.add((category, container))
                severity, summary, actions = CAUSES[category]
                reports.append(IncidentReport(pod.namespace, pod.name, container, severity, category,
                    confidence, summary, selected, [summary], actions, reason, cluster))
            events = [e for e in pe if e.evidence_type == 'event']
            if pod.phase == 'Pending' and any(e.key == 'FailedScheduling' for e in events):
                add('SCHEDULING_FAILURE', None, pe, 'high', 'Pending과 최근 FailedScheduling Event가 일치합니다.')
                replaced.add(('Pending', None))
            for c in pod.containers:
                ce = [e for e in pe if e.container == c.name or (e.container is None and e.source == 'kubernetes')]
                logs = [e for e in ce if e.evidence_type == 'log']
                text = ' '.join(e.message for e in logs).lower()
                def metric(key):
                    values = [e for e in ce if e.key == key and e.source == 'prometheus' and isinstance(e.value, (int, float))]
                    return max(values, key=lambda e: e.timestamp).value if values else None
                reason = c.waiting_reason or c.terminated_reason
                if reason == 'CrashLoopBackOff' and 'connection refused' in text and re.search(r'postgres|mysql|mongodb|redis|database|\bdb[.:_-]', text):
                    add('DEPENDENCY_CONNECTION_FAILURE', c.name, ce, 'medium', 'CrashLoop과 DB 관련 refused 로그가 있으나 연결 대상의 실제 상태는 미확인입니다.')
                    replaced.add(('CrashLoopBackOff', c.name))
                if reason in ('ImagePullBackOff', 'ErrImagePull') and any(re.search(r'pull|image', e.message, re.I) and re.search(r'failed|back.?off|denied|unauthorized|not found', e.key+' '+e.message, re.I) for e in events):
                    add('IMAGE_PULL_FAILURE', c.name, ce, 'high', '이미지 pull 상태와 관련 Event를 관찰했습니다. 인증/태그 원인은 미확정입니다.')
                    replaced.add((reason, c.name))
                usage, limit = metric('memory_bytes'), metric('memory_limit_bytes') or c.memory_limit_bytes
                if reason == 'OOMKilled' and usage is not None and limit and usage / limit >= .9:
                    add('MEMORY_PRESSURE', c.name, ce, 'high', 'OOM과 메모리 한도 90% 이상 사용 샘플이 있습니다. 증가 추이는 별도 검증이 필요합니다.')
                    replaced.add(('OOMKilled', c.name))
                cpu, increase = metric('cpu_cores'), metric('restart_increase')
                if cpu is not None and cpu >= self.cpu_threshold and increase == 0:
                    add('HIGH_CPU', c.name, ce, 'medium', '5분 CPU rate가 임계값 이상이고 같은 기간 restart increase는 0입니다.')
                if pod.phase == 'Running' and c.state == 'running' and c.ready is True and re.search(r'\b5\d\d\b', text) and re.search(r'ingress|upstream|routing|gateway', text):
                    add('INGRESS_OR_ROUTING', c.name, ce, 'low', 'Running/ready와 routing 관련 5xx 로그만 확인했습니다. Service 상태와 원인 분리는 추가 조회가 필요합니다.')
                if c.restart_count >= self.rules.restart_threshold and pod.phase == 'Running' and c.state == 'running' and c.ready is not False:
                    add('HISTORICAL_RESTART_WARNING', c.name, ce, 'low', '누적 재시작만으로 현재 장애를 확정할 수 없습니다.')
                    replaced.add(('HighRestartCount', c.name))
            for finding in (i for i in baseline if i.pod is pod):
                if (finding.category, finding.container) in replaced:
                    continue
                selected = [e for e in pe if e.container in (None, finding.container)]
                reports.append(IncidentReport(pod.namespace, pod.name, finding.container, finding.severity,
                    finding.category, 'low', finding.probable_cause, selected, [finding.probable_cause],
                    finding.recommendations, '단일 상태 규칙입니다. 근본 원인 증거가 부족합니다.', cluster))
        return reports
