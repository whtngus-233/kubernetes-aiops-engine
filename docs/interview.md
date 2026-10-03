# Interview notes

## 왜 AIOps 프로젝트를 만들었나요?

MODUI EKS에서 Pod/Event/로그와 관측 지표를 반복 확인하는 조사 과정이 있었다.
여러 출처의 증거를 모으고 원인 후보를 설명해 운영자의 조사 시간을 줄이는 범용 도구를 만들었다.

## Kubernetes 장애를 어떻게 탐지하나요?

현재/이전 container state, phase, restart, readiness와 UID로 연결된 Event를 조회한다.
CrashLoop/ImagePull/OOM/Pending/Failed 등 deterministic rule을 적용하고 metrics/logs로 가설을 보완한다.
누적 restart는 현재 장애가 아니라 historical warning일 수 있다.

## 왜 LLM만으로 장애 원인을 판단하지 않나요?

LLM은 hallucination과 timeout이 있고 JSON이 맞아도 원인은 틀릴 수 있다.
관찰 사실은 rule/evidence에서 유지하며 LLM은 증거 기반 추가 확인과 원인 후보만 보조한다.

## Rule Engine이 왜 필요한가요?

입력과 판단 근거가 추적 가능한 재현성 있는 기준이다. LLM key가 없거나 장애가 나도 동작하며
단일 상태와 복합 correlation을 분리해 테스트할 수 있다.

## Prometheus와 Loki 역할 차이는?

Prometheus는 CPU rate/메모리/restart/readiness처럼 숫자 지표를 제공한다.
Loki는 refused/exception/5xx 등 사건 문맥을 제공한다. label/time으로 연결하며 raw logs를 무조건 LLM으로 보내지 않는다.

## Pod가 Running인데 서비스 장애가 날 수 있는 이유는?

Running은 lifecycle 상태다. readiness, dependency, Service endpoint, Ingress route, upstream timeout,
애플리케이션 오류는 별개다. 현재 routing 규칙은 ready + 5xx routing 로그의 low-confidence 후보이며
실제 Service/Ingress 증거 조회는 다음 개선이다.

## CrashLoopBackOff를 어떻게 분석하나요?

반복 종료 상태/종료 코드/최근 Event와 sanitized logs를 연결한다.
DB 관련 refused 로그가 있으면 dependency connection 후보지만 DB 장애를 확정하지 않는다.
probe/config/네트워크와 의존 서비스 상태를 추가 확인한다.

## OOMKilled는 어떻게 분석하나요?

OOM 종료와 memory working set/limit near 90%를 조합해 memory pressure를 제시한다.
현재 instant metric은 이전 peak/증가 추이를 보장하지 않으며 limit 설정/누수/workload 변화 검토가 필요하다.

## 왜 자동복구를 하지 않았나요?

원인이 불확실한 restart/scale이 장애를 확대할 수 있기 때문이다.
운영자의 판단을 보조하고 변경 권한 자체를 주지 않는 human-in-the-loop를 선택했다.

## 실제 EKS에서 어떻게 검증했나요?

기존 context 이름만 확인하고 pods/events와 관측 리소스를 READ-ONLY로 조회했다.
확장 Python Collector snapshot은 성공했고 11개 Running Pod 조회를 확인했다.
일부 API는 timeout되어 외부 observability 연동은 미확인으로 기록했다. 실제 운영 장애 주입은 하지 않았다.

## 보안은 어떻게 고려했나요?

pods/events get/list RBAC, Secret/env 비수집, API namespace allowlist, optional bearer와 webhook mandatory token,
마스킹과 bounded snippets, no-tools LLM, non-root/read-only Docker/Helm, Git/Docker credential 제외를 적용했다.
masking은 heuristic이므로 PII 정책과 데이터 외부 전송 검토가 필요하다.

## MLOps/AIOps와 어떤 관련이 있나요?

관측 데이터 수집/정규화/분석/보고 파이프라인과 failure isolation은 AIOps 기반이다.
LLM inference provider, structured output, fallback, 후속 eval 설계가 ML 서비스 운영과 닿아 있다.
현재 ML 모델 학습/배포나 학습 기반 anomaly detection을 구현한 것은 아니다.
