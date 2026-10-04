# Architecture

`KubernetesCollector → Snapshot → optional Prometheus/Loki → normalize → CorrelationEngine → IncidentReport`
이 핵심 파이프라인을 CLI/API가 공유합니다. 기존 `RuleEngine`은 호환성을 유지하고 correlation이
추가 증거가 있는 경우만 분류를 보완합니다.

- models: workload/status/event 및 공통 IncidentEvidence, MetricsEvidence/LogEvidence/KubernetesEvidence.
- HTTPTransport: response size limit, timeout, redirect 거부, 환경 proxy credentials 비활성화.
- Evidence: namespace/pod/container 경계 (container 없는 Kubernetes 증거는 공유), 기본 최근 20분과 최대 1분 미래 timestamp 허용. Pod Event는 UID로 연결됩니다.
- Rule/Correlation: 분류와 증거/원인 가설 분리, 설명 가능한 qualitative confidence.
- Structured report: UUID ID와 별도의 stable workload/category dedup hash.
- LLM: JSON schema + local validation; 장애/불완전 응답은 advisory unavailable로 처리.
- Notification: 한 process TTL dedup, 실패 시 sent로 기록하지 않음, bounded cache.
- Store/API: lock와 제한된 store; 단일 동시 수집, allowlist와 bearer auth.

Kubernetes는 필수이며 실패하면 불완전한 healthy 보고서 대신 오류를 반환합니다.
Prometheus/Loki는 선택 증거이며 오류는 warnings로 남습니다. Event 실패도 부분 보고서로 유지합니다.
LLM/Discord 장애는 규칙 결과를 제거하지 않습니다. 'No findings'는 전체 서비스 건강 증명이 아닙니다.

메모리 store/dedup는 재시작 시 초기화됩니다. 멀티 replica 일관성은 보장하지 않습니다.
metric/log는 UID가 없으므로 Pod 이름 재사용/수집 지연에 주의해야 합니다. window로 제한하되
UID-aware backend labels는 후속 개선입니다. 현재 ingress는 로그 기반 low-confidence 후보입니다.

엔진 lock은 API/scheduler의 같은 engine instance 중복 실행을 거부합니다. snapshot은 복사해 처리하므로
재사용 시 optional evidence가 누적되지 않습니다. 수집 단계 deadline과 advisory 시작 deadline은
cooperative bounds이며 진행 중 네트워크 요청은 자체 timeout으로 종료합니다. 임의 주입 adapter의
blocking call을 강제 중단하는 기능은 없습니다. scheduler는 SIGINT/SIGTERM과 stop_event를 지원하고
요청 종료 후 graceful shutdown합니다. API는 scheduler를 자동 시작하지 않습니다.

## Health execution

`/health` is async and requires neither a collector nor AnyIO worker capacity. Blocking
analysis remains in synchronous routes with existing overlap guards. Docker probes run
`python -S app/healthcheck.py` directly with no shell, application import or executor.
Docker's 3s timeout remains unchanged. HOST runtime evidence is required for final health
acceptance; see [host-validation.md](host-validation.md).
